"""Isolated agent and trusted simulator/verifier Docker lifecycle.

The agent receives public assets and a shared workspace only. Harbor's /tests
upload freezes the agent and begins trusted verification.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import atexit
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Mapping
from pathlib import Path

from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.environments.capabilities import EnvironmentCapabilities
from harbor.models.environment_type import EnvironmentType
from harbor.models.trial.paths import EnvironmentPaths

logger = logging.getLogger(__name__)


# Host environment variables forwarded into the local Docker container.
# Mirrors ``SERVER_ENV_FORWARD_KEYS`` in ``modal_env.py`` so both backends
# expose the same provider/judge/MCP toggles to the in-container chi-bench
# server + agent. Only keys with non-empty host values are forwarded.
FORWARDED_ENV_KEYS: tuple[str, ...] = (
    "CHI_BENCH_E2E_PROTOCOL",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "CHI_BENCH_JUDGE_MODEL",
    "CHI_BENCH_JUDGE_TIMEOUT_S",
    "CHI_BENCH_JUDGE_NUM_VOTES",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GROK_API_KEY",
    "XAI_API_KEY",
    "OPENROUTER_API_KEY",
    "CHI_BENCH_P2P_SIMULATOR_MODEL",
    "CHI_BENCH_PATIENT_SIM_MODEL",
    "CHI_BENCH_PAYER_MCP_PROFILE",
    "CHI_BENCH_TOOL_MODE",
    "CHI_BENCH_SKILLS_ABLATE",
    "CHI_BENCH_MCP_TOOL_SEP",
)


# Default image tag — matches what ``cb docker build`` produces.
DEFAULT_IMAGE = "chi-bench:latest"


_CONTAINER_NAME_INVALID = re.compile(r"[^a-zA-Z0-9_.-]")


def sanitize_container_name(name: str) -> str:
    """Coerce ``name`` into a valid Docker container name.

    Docker requires ``[a-zA-Z0-9][a-zA-Z0-9_.-]+``. Harbor's ``session_id`` is
    typically ``<task>__<trial_id>`` which is already valid; the substitution
    here is defensive for edge-case task ids and trial slugs.
    """
    safe = _CONTAINER_NAME_INVALID.sub("_", name)
    if not safe or not safe[0].isalnum():
        safe = "c_" + safe
    return safe[:64]


def _resolve_repo_root() -> Path | None:
    """Walk up from this file to find the repo root containing ``docker/Dockerfile``.

    Returns ``None`` when chi_bench is installed from a wheel / non-source
    checkout — in that case ``force_build`` cannot be honoured and callers
    must rely on a pre-built image.
    """
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "docker" / "Dockerfile").is_file() and (
            candidate / "pyproject.toml"
        ).is_file():
            return candidate
    return None


def build_docker_run_argv(
    *,
    image: str,
    container_name: str,
    task_id: str,
    host_env: Mapping[str, str],
    allow_internet: bool,
    extra_env: Mapping[str, str] | None = None,
    detached: bool = True,
) -> list[str]:
    """Assemble the ``docker run`` argv for a chi-bench trial container.

    Pure function so unit tests can pin the argv shape without spinning up
    docker.

    ``extra_env`` carries harbor-injected per-trial env (``task_env_config.env``
    merged into ``_persistent_env``) and wins over ``host_env`` on collision.
    """
    argv: list[str] = ["docker", "run"]
    if detached:
        argv += ["-d"]
    argv += ["--name", container_name]
    if not allow_internet:
        argv += ["--network", "none"]
    # Harbor uses the qualified task name (for example ``actava-ai/task-id``)
    # as ``environment_name``. The single-image layout stores baked tasks by
    # their leaf directory name, so the entrypoint must receive that leaf ID.
    task_id = task_id.rsplit("/", maxsplit=1)[-1]
    argv += ["-e", f"CHI_BENCH_TASK_ID={task_id}"]
    for key in FORWARDED_ENV_KEYS:
        value = host_env.get(key)
        if value:
            argv += ["-e", f"{key}={value}"]
    if extra_env:
        for key, value in extra_env.items():
            if value is None:
                continue
            argv += ["-e", f"{key}={value}"]
    argv.append(image)
    return argv


def build_docker_exec_argv(
    *,
    container_name: str,
    command: str,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    user: str | int | None = None,
) -> list[str]:
    """Assemble the ``docker exec`` argv for in-container command execution."""
    argv: list[str] = ["docker", "exec"]
    if cwd:
        argv += ["-w", cwd]
    if env:
        for key, value in env.items():
            argv += ["-e", f"{key}={value}"]
    if user is not None:
        argv += ["-u", str(user)]
    # Match harbor's stock docker plugin (harbor/environments/docker/docker_unix.py:63)
    # which uses ``bash -c`` — agent install scripts (e.g. codex's nvm bootstrap)
    # rely on bash builtins (``\. nvm.sh``, ``&>/dev/null``) that dash rejects.
    argv += [container_name, "bash", "-c", command]
    return argv


# ----- Orphan-container cleanup on interpreter exit ------------------------

_ACTIVE_CONTAINERS: list[str] = []
_ACTIVE_CONTAINERS_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False


def _register_container(name: str) -> None:
    global _ATEXIT_REGISTERED
    with _ACTIVE_CONTAINERS_LOCK:
        if name not in _ACTIVE_CONTAINERS:
            _ACTIVE_CONTAINERS.append(name)
        if not _ATEXIT_REGISTERED:
            atexit.register(_terminate_tracked_containers)
            _ATEXIT_REGISTERED = True


def _unregister_container(name: str) -> None:
    with _ACTIVE_CONTAINERS_LOCK:
        try:
            _ACTIVE_CONTAINERS.remove(name)
        except ValueError:
            pass


def _terminate_tracked_containers() -> None:
    with _ACTIVE_CONTAINERS_LOCK:
        names = list(_ACTIVE_CONTAINERS)
        _ACTIVE_CONTAINERS.clear()
    for name in names:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort at shutdown
            logger.warning("failed to terminate orphan container %s: %s", name, exc)


class ChiBenchDockerEnvironment(BaseEnvironment):
    """Two-container trial: a clean agent and a trusted simulator/verifier.

    The host-side upload of Harbor's reserved /tests directory begins the
    verifier phase. It stops the entire agent container, closes tool admission,
    and drains admitted work before any verifier inputs are installed.
    """

    _uses_host_network = False

    def __init__(
        self,
        *args,
        image=DEFAULT_IMAGE,
        agent_image=None,
        force_build=None,
        host_env=None,
        data_root=None,
        dataset_content_sha256=None,
        dataset_domains=None,
        **kwargs,
    ):
        self._image = image
        self._agent_image = agent_image or (
            "chi-bench:agent" if image == DEFAULT_IMAGE else image + "-agent"
        )
        self._force_build_default = bool(force_build)
        self._host_env = dict(host_env) if host_env is not None else dict(os.environ)
        self._data_root = Path(data_root) if data_root is not None else None
        self._dataset_content_sha256 = dataset_content_sha256
        self._dataset_domains = dataset_domains or []
        self._container_name = None
        self._control_token = secrets.token_urlsafe(32)
        self._verifying = False
        self._agent_created = False
        self._server_created = False
        self._owned_volumes = []
        self._network_created = False
        self._resource_prefix = "chi-" + secrets.token_hex(8)
        super().__init__(*args, **kwargs)

    @staticmethod
    def type():
        return EnvironmentType.DOCKER

    @property
    def capabilities(self):
        return EnvironmentCapabilities(
            gpus=False, disable_internet=True, windows=False, mounted=False
        )

    @property
    def env_paths(self):
        return EnvironmentPaths.for_os(self.task_env_config.os)

    def _validate_definition(self):
        return

    @classmethod
    def preflight(cls):
        if shutil.which("docker") is None:
            raise SystemExit(
                "Docker CLI not found; install Docker before using the Docker backend."
            )

    @property
    def task_id(self):
        task_dir = self.environment_dir.parent
        explicit = self._persistent_env.get("CHI_BENCH_TASK_ID")
        if explicit:
            value = explicit
        elif (task_dir / "fixtures" / "session_manifest.json").is_file():
            value = "marathon/" + task_dir.name
        else:
            value = self.environment_name.rsplit("/", 1)[-1]
        parts = Path(value).parts
        if not parts or Path(value).is_absolute() or any(p in (".", "..") for p in parts):
            raise ValueError("Invalid runtime task identity")
        return value

    @property
    def container_name(self):
        if self._container_name is None:
            self._container_name = sanitize_container_name(self.session_id)
        return self._container_name

    @property
    def server_container_name(self):
        return self.container_name[:54] + "-server"

    @property
    def _target_container(self):
        return self.server_container_name if self._verifying else self.container_name

    def _initial_role(self):
        urls = [s.url or "" for s in self.task_env_config.mcp_servers]
        if (
            any(":8200/" in u for u in urls)
            or self.task_id.startswith("cm_")
            or "care_management" in self.task_id
        ):
            return "cm"
        if (
            any(":8020/" in u for u in urls)
            or self.task_id.endswith(("_provider", "_e2e"))
            or "prior_auth_provider" in self.task_id
        ):
            return "provider"
        return "payer"

    def _agent_env(self):
        keys = ("CHI_BENCH_TOOL_MODE", "CHI_BENCH_MCP_TOOL_SEP")
        merged = {**self._host_env, **self._persistent_env}
        return {k: merged[k] for k in keys if merged.get(k)}

    async def _run(self, argv, *, timeout_sec=None, env=None):
        return await _run_subprocess(argv, timeout_sec=timeout_sec, env=env)

    async def _checked(self, argv, *, timeout_sec=None, env=None):
        result = await self._run(argv, timeout_sec=timeout_sec, env=env)
        if result.return_code != 0:
            detail = str(result.stderr or result.stdout or "command failed")
            for key, value in (env or {}).items():
                if value and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET")):
                    detail = detail.replace(value, "[redacted]")
            raise RuntimeError(
                f"Runtime operation failed (exit {result.return_code}): {detail[:2000]}"
            )
        return result

    async def start(self, force_build):
        try:
            runtime_manifest = self._runtime_material_manifest()
            if force_build or self._force_build_default:
                await self._build_image()
            volumes = {
                name: self._resource_prefix + "-" + name for name in ("workspace", "assets", "raw")
            }
            for volume in volumes.values():
                await self._checked(["docker", "volume", "create", volume])
                self._owned_volumes.append(volume)
            if self._network_is_public and not self._uses_host_network:
                await self._checked(["docker", "network", "create", self._resource_prefix])
                self._network_created = True
            network = (
                ("host" if self._uses_host_network else self._resource_prefix)
                if self._network_is_public
                else "none"
            )
            server_env = {k: self._host_env[k] for k in FORWARDED_ENV_KEYS if self._host_env.get(k)}
            server_env.update(self._persistent_env)
            server_env.update(
                {
                    "CHI_BENCH_TASK_ID": self.task_id,
                    "CHI_BENCH_CONTROL_TOKEN": self._control_token,
                    "CHI_BENCH_AGENT_ROLE": self._initial_role(),
                    "CHI_BENCH_PUBLISH_AGENT_ASSETS": "1",
                }
            )
            if runtime_manifest is not None:
                # Pin the same roots the guard checks, including with older
                # images whose inherited environment selected other paths.
                server_env["CHI_BENCH_TASKS_ROOT"] = self._runtime_tasks_root()
                server_env["CHI_BENCH_WORLDS_DIR"] = self._runtime_worlds_root()
            server = [
                "docker",
                "create",
                "--name",
                self.server_container_name,
                "--network",
                network,
                "--add-host",
                "chi-bench-server:127.0.0.1",
                "--log-opt",
                "max-size=10m",
                "--log-opt",
                "max-file=3",
                "-v",
                volumes["workspace"] + ":/logs/artifacts/workspaces",
                "-v",
                volumes["assets"] + ":/agent-assets",
                "-v",
                volumes["raw"] + ":/srv/chi-bench/raw/artifacts",
            ]
            for key in sorted(server_env):
                server += ["-e", key]
            if runtime_manifest is not None:
                server += ["--entrypoint", "/bin/sh"]
            server += [self._image]
            if runtime_manifest is not None:
                server += [
                    "-c",
                    "python /tmp/chi-bench-material-guard.py /tmp/chi-bench-materials.json"
                    " && exec /usr/bin/tini -- /usr/local/bin/entrypoint.sh sleep infinity",
                ]
            await self._checked(server, env=server_env)
            self._server_created = True
            if not self._uses_host_network:
                _register_container(self.server_container_name)
            source = self.environment_dir.parent
            if (source / "fixtures").is_dir():
                destination = self._runtime_tasks_root() + "/" + self.task_id
                await self._copy_to_container(
                    source, self.server_container_name, destination, directory=True
                )
            if runtime_manifest is not None:
                from chi_bench.experiment import runtime_materials

                await self._copy_to_container(
                    Path(runtime_materials.__file__),
                    self.server_container_name,
                    "/tmp/chi-bench-material-guard.py",
                )
                with tempfile.TemporaryDirectory(prefix="chi-bench-materials-") as temporary:
                    manifest_path = Path(temporary) / "manifest.json"
                    manifest_path.write_text(json.dumps(runtime_manifest))
                    await self._copy_to_container(
                        manifest_path, self.server_container_name, "/tmp/chi-bench-materials.json"
                    )
            await self._checked(["docker", "start", self.server_container_name])
            await self._wait_for_server_ready()
            # Task env is simulator configuration. Agent credentials arrive only
            # through Harbor's explicit agent-scoped per-exec environment.
            # Package installation needs normal UID/ownership capabilities;
            # raw sockets are excluded from the shared control network.
            agent_env = self._agent_env()
            agent = [
                "docker",
                "create",
                "--name",
                self.container_name,
                "--network",
                "container:" + self.server_container_name,
                "--cap-drop",
                "NET_RAW",
                "--security-opt",
                "no-new-privileges",
                "--log-opt",
                "max-size=10m",
                "--log-opt",
                "max-file=3",
                "-v",
                volumes["workspace"] + ":/logs/artifacts/workspaces",
                "-v",
                volumes["assets"] + ":/agent-assets:ro",
            ]
            if not self.task_id.endswith("_new_referral_provider"):
                agent += ["-v", volumes["raw"] + ":/agent-raw/artifacts:ro"]
            for key in sorted(agent_env):
                agent += ["-e", key]
            agent += [self._agent_image]
            await self._checked(agent, env=agent_env)
            self._agent_created = True
            if not self._uses_host_network:
                _register_container(self.container_name)
            await self._checked(["docker", "start", self.container_name])
            await self.exec(
                "mkdir -p /logs/agent /logs/artifacts /logs/verifier && chmod 777 /logs/agent /logs/artifacts /logs/verifier",
                user="root",
            )
        except BaseException:
            await asyncio.shield(self._save_startup_diagnostics())
            await asyncio.shield(self.stop(delete=True))
            raise

    def _runtime_material_manifest(self):
        from chi_bench.experiment.content_identity import DOMAIN_ROOTS, require_dataset_identity
        from chi_bench.experiment.runtime_materials import (
            build_runtime_material_manifest,
            infer_data_root,
            source_task_path,
        )

        source = self.environment_dir.parent
        data_root = self._data_root or infer_data_root(source)
        if self._dataset_content_sha256 is not None:
            if data_root is None:
                raise ValueError("An accepted dataset identity requires data_root")
            identity = require_dataset_identity(
                data_root, self._dataset_domains, self._dataset_content_sha256
            )
            source = source_task_path(data_root, self.task_id)
            if source.relative_to(data_root).parts[0] not in {
                DOMAIN_ROOTS[domain] for domain in identity.domains
            }:
                raise ValueError("Selected task is outside the accepted dataset domain scope")
        if data_root is None:
            return None  # Source-less development/synthetic environments.
        return build_runtime_material_manifest(
            data_root,
            source,
            self.task_id,
            worlds_root=self._runtime_worlds_root(),
            tasks_root=self._runtime_tasks_root(),
        )

    def _runtime_tasks_root(self):
        return self._persistent_env.get("CHI_BENCH_TASKS_ROOT") or "/opt/chi-bench/tasks"

    def _runtime_worlds_root(self):
        return self._persistent_env.get("CHI_BENCH_WORLDS_DIR") or "/opt/chi-bench/worlds"

    async def _save_startup_diagnostics(self):
        if not self._server_created:
            return
        try:
            result = await self._run(
                ["docker", "logs", "--tail", "120", self.server_container_name], timeout_sec=10
            )
            content = (result.stdout or "") + (result.stderr or "")
            for key, value in self._host_env.items():
                if value and any(word in key.upper() for word in ("KEY", "TOKEN", "SECRET")):
                    content = content.replace(value, "[redacted]")
            content = content.replace(self._control_token, "[redacted]")
            path = self.trial_paths.trial_dir / "environment-startup.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                stream.write(content)
        except Exception:
            self.logger.warning("Could not save trusted simulator startup diagnostics")

    async def stop(self, delete):
        del delete
        for name, created in (
            (self.container_name, self._agent_created),
            (self.server_container_name, self._server_created),
        ):
            if created:
                await self._run(["docker", "rm", "-f", name], timeout_sec=30)
                _unregister_container(name)
        self._agent_created = self._server_created = False
        for volume in self._owned_volumes:
            await self._run(["docker", "volume", "rm", volume], timeout_sec=30)
        self._owned_volumes.clear()
        if self._network_created:
            await self._run(["docker", "network", "rm", self._resource_prefix], timeout_sec=30)
            self._network_created = False

    async def _exec_in(
        self, container, command, *, cwd=None, env=None, timeout_sec=None, user=None
    ):
        argv = ["docker", "exec"]
        if cwd:
            argv += ["-w", cwd]
        if user is not None:
            argv += ["-u", str(user)]
        for key in sorted(env or {}):
            argv += ["-e", key]
        argv += [container, "bash", "-c", command]
        return await self._run(argv, env=env, timeout_sec=timeout_sec)

    async def _server_exec(self, command, *, env=None, timeout_sec=None):
        return await self._exec_in(
            self.server_container_name, command, env=env, timeout_sec=timeout_sec, user="root"
        )

    async def exec_control(self, command, env=None, timeout_sec=None):
        """Host-only control operation. Never executes in the model container."""
        return await self._server_exec(command, env=env, timeout_sec=timeout_sec)

    async def control_request(self, path, payload=None):
        if not path.startswith("/") or path.startswith("//"):
            raise ValueError("Control path must be relative to the simulator")
        script = (
            "import json,os,urllib.request\n"
            "from chi_bench.server.control import control_headers\n"
            "body=json.loads(os.environ['CHI_CONTROL_BODY'])\n"
            f"req=urllib.request.Request('http://localhost:8023'+{path!r},"
            "data=None if body is None else json.dumps(body).encode(),"
            "headers={**control_headers(),'Content-Type':'application/json'})\n"
            "with urllib.request.urlopen(req,timeout=135) as r: print(r.read().decode())\n"
        )
        result = await self.exec_control(
            "python -c " + shlex.quote(script),
            env={"CHI_CONTROL_BODY": json.dumps(payload)},
            timeout_sec=150,
        )
        if result.return_code:
            raise RuntimeError(
                "Trusted simulator request failed: " + str(result.stderr or result.stdout)[:1500]
            )
        return json.loads(result.stdout or "{}")

    async def begin_verification(self):
        if self._verifying:
            return
        if self._agent_created:
            await self._checked(["docker", "stop", "-t", "5", self.container_name], timeout_sec=20)
        await self.control_request("/_admin/agent_role", {"role": "closed"})
        result = await self._server_exec("mkdir -p /logs/verifier")
        if result.return_code:
            raise RuntimeError("Cannot prepare the trusted verifier output directory")
        self._verifying = True

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        if self._verifying:
            return await self._server_exec(command, env=env, timeout_sec=timeout_sec)
        merged = {**self._agent_env(), **(env or {})}
        for scoped in self._exec_env_overlays.get():
            merged.update(scoped)
        merged = {
            k: v
            for k, v in merged.items()
            if k != "CHI_BENCH_CONTROL_TOKEN" and not k.startswith("CHI_BENCH_JUDGE_")
        }
        return await self._exec_in(
            self.container_name,
            command,
            cwd=cwd or self.task_env_config.workdir,
            env=merged,
            timeout_sec=timeout_sec,
            user=self._resolve_user(user),
        )

    async def _copy_to_container(self, source, container, target, *, directory=False):
        source_arg = str(source.resolve()).rstrip("/") + ("/." if directory else "")
        await self._checked(["docker", "cp", source_arg, f"{container}:{target}"])

    async def _copy_from_container(self, container, source, target, *, directory=False):
        target = Path(target)
        (target if directory else target.parent).mkdir(parents=True, exist_ok=True)
        source_arg = source.rstrip("/") + ("/." if directory else "")
        await self._checked(["docker", "cp", f"{container}:{source_arg}", str(target)])

    async def upload_file(self, source_path, target_path):
        if str(target_path) == "/tests" or str(target_path).startswith("/tests/"):
            await self.begin_verification()
        await self._copy_to_container(Path(source_path), self._target_container, target_path)

    async def upload_dir(self, source_dir, target_dir):
        if str(target_dir).rstrip("/") == "/tests":
            await self.begin_verification()
        result = await self.exec("mkdir -p " + shlex.quote(str(target_dir)), user="root")
        if result.return_code:
            raise RuntimeError("Cannot create upload directory")
        await self._copy_to_container(
            Path(source_dir), self._target_container, target_dir, directory=True
        )

    def _download_container(self, source):
        value = str(source).rstrip("/")
        if value == "/logs/agent" or value.startswith("/logs/agent/"):
            return self.container_name
        if (
            value == "/logs/verifier"
            or value.startswith("/logs/verifier/")
            or value == "/logs/artifacts"
        ):
            return self.server_container_name
        return self._target_container

    async def download_file(self, source_path, target_path):
        await self._copy_from_container(
            self._download_container(source_path), source_path, Path(target_path)
        )

    async def download_dir(self, source_dir, target_dir):
        await self._copy_from_container(
            self._download_container(source_dir), source_dir, Path(target_dir), directory=True
        )

    async def _engine_build_context(self):
        root = _resolve_repo_root()
        if root is None:
            raise RuntimeError("Building the runtime requires a source checkout")
        return str(root)

    async def _build_image(self):
        context = await self._engine_build_context()
        for target, tag in (("runtime", self._image), ("agent", self._agent_image)):
            await self._checked(
                [
                    "docker",
                    "build",
                    *(["--network", "host"] if self._uses_host_network else []),
                    "-f",
                    context + "/docker/Dockerfile",
                    "--target",
                    target,
                    "-t",
                    tag,
                    context,
                ],
                timeout_sec=round(self.task_env_config.build_timeout_sec),
            )

    async def _wait_for_server_ready(self, *, attempts=600, poll_interval_s=1.0):
        script = "from pathlib import Path; import urllib.request; urllib.request.urlopen('http://localhost:8023/health',timeout=3); assert Path('/agent-assets/.ready').is_file()"
        for _ in range(attempts):
            result = await self._server_exec("python -c " + shlex.quote(script), timeout_sec=10)
            if result.return_code == 0:
                return
            state = await self._run(
                ["docker", "inspect", "--format", "{{.State.Status}}", self.server_container_name],
                timeout_sec=10,
            )
            if state.return_code == 0 and (state.stdout or "").strip() in ("exited", "dead"):
                raise RuntimeError("Trusted simulator exited during startup")
            await asyncio.sleep(poll_interval_s)
        raise RuntimeError("Simulator failed readiness checks; inspect trusted container logs")


# ----- subprocess helper ---------------------------------------------------


async def _run_subprocess(
    argv: list[str], *, timeout_sec: int | None = None, env: Mapping[str, str] | None = None
) -> ExecResult:
    """Run ``argv`` and return harbor's ``ExecResult``.

    Captures stdout/stderr as decoded strings; surfaces timeouts as a
    distinguishable non-zero return code (124, mirroring ``timeout(1)``)
    so callers can react without inspecting an exception class.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env} if env else None,
    )
    try:
        if timeout_sec is not None:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_sec)
        else:
            stdout_b, stderr_b = await proc.communicate()
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return ExecResult(stdout=None, stderr=f"timeout after {timeout_sec}s", return_code=124)
    return ExecResult(
        stdout=stdout_b.decode("utf-8", errors="replace") if stdout_b else "",
        stderr=stderr_b.decode("utf-8", errors="replace") if stderr_b else "",
        return_code=proc.returncode if proc.returncode is not None else -1,
    )


__all__ = [
    "ChiBenchDockerEnvironment",
    "FORWARDED_ENV_KEYS",
    "DEFAULT_IMAGE",
    "build_docker_run_argv",
    "build_docker_exec_argv",
    "sanitize_container_name",
]
