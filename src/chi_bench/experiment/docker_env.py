"""Local-Docker Harbor Environment for the chi-Bench single-image layout.

One ``chi-bench:latest`` container per trial: the image is pre-built once via
``chi-bench docker build`` (or rebuilt here when ``force_build=True``) and the
per-task fixtures are selected by ``CHI_BENCH_TASK_ID``. The in-container
``docker/entrypoint.sh`` boots the chi-Bench HTTP server + three MCP session
managers as PID 1, then ``exec``s ``sleep infinity`` so harbor's lifecycle
operates against a long-lived container via ``docker exec`` / ``docker cp``.

Register with the harbor CLI:
    --environment-import-path chi_bench.experiment.docker_env:ChiBenchDockerEnvironment
"""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import re
import shlex
import shutil
import subprocess
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


# Default image tag — matches what ``chi-bench docker build`` produces.
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
    """Single-image local-Docker harbor environment for chi-Bench trials.

    Runtime shape:

      ``start``:    ``docker run -d --name <session_id> -e CHI_BENCH_TASK_ID=… image``
      ``exec``:     ``docker exec [-w cwd] [-e …] [-u user] <name> sh -c "<cmd>"``
      ``upload``:   ``docker cp <src> <name>:<dst>``
      ``download``: ``docker cp <name>:<src> <dst>``
      ``stop``:     ``docker rm -f <name>``

    The image must be pre-built (``chi-bench docker build``) unless
    ``force_build=True`` is passed at construction, in which case ``start``
    rebuilds it from ``docker/Dockerfile`` with repo root as context.
    """

    def __init__(
        self,
        *args,
        image: str = DEFAULT_IMAGE,
        force_build: bool | None = None,
        host_env: Mapping[str, str] | None = None,
        **kwargs,
    ) -> None:
        self._image = image
        self._force_build_default = bool(force_build) if force_build is not None else False
        # Snapshot at construction so later mutations of ``os.environ`` from
        # the parent process can't change which credentials get forwarded.
        self._host_env: dict[str, str] = (
            dict(host_env) if host_env is not None else dict(os.environ)
        )
        self._container_name: str | None = None
        super().__init__(*args, **kwargs)

    # ----- harbor protocol metadata ----------------------------------------

    @staticmethod
    def type() -> str:
        return EnvironmentType.DOCKER

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(
            gpus=False,
            disable_internet=True,
            windows=False,
            mounted=False,
        )

    @property
    def env_paths(self) -> EnvironmentPaths:
        # In-container POSIX paths regardless of host OS.
        return EnvironmentPaths.for_os(self.task_env_config.os)

    def _validate_definition(self) -> None:
        # Single-image design: no per-task ``environment/`` files required.
        # The image is the contract; ``start()`` surfaces missing-image errors.
        return

    @classmethod
    def preflight(cls) -> None:
        if shutil.which("docker") is None:
            raise SystemExit(
                "docker CLI not found on PATH — install Docker Desktop or "
                "the docker engine before running chi-bench experiment run "
                "with --environment docker."
            )

    # ----- task identity ---------------------------------------------------

    @property
    def task_id(self) -> str:
        """The per-trial task id forwarded to the in-container entrypoint."""
        return self.environment_name

    @property
    def container_name(self) -> str:
        if self._container_name is None:
            self._container_name = sanitize_container_name(self.session_id)
        return self._container_name

    # ----- lifecycle -------------------------------------------------------

    async def start(self, force_build: bool) -> None:
        if force_build or self._force_build_default:
            await self._build_image()

        argv = build_docker_run_argv(
            image=self._image,
            container_name=self.container_name,
            task_id=self.task_id,
            host_env=self._host_env,
            allow_internet=self.task_env_config.allow_internet,
            extra_env=self._persistent_env,
        )
        self.logger.info("starting container %s from %s", self.container_name, self._image)
        result = await _run_subprocess(argv)
        if result.return_code != 0:
            raise RuntimeError(
                f"docker run failed (rc={result.return_code}): {result.stderr or result.stdout}"
            )
        _register_container(self.container_name)

        # Provision harbor's expected log dirs and make them world-writable so
        # the in-container agent user (often non-root) can write trajectories.
        agent_dir = str(self.env_paths.agent_dir)
        verifier_dir = str(self.env_paths.verifier_dir)
        mkdir_cmd = f"mkdir -p {shlex.quote(agent_dir)} {shlex.quote(verifier_dir)} && chmod 777 {shlex.quote(agent_dir)} {shlex.quote(verifier_dir)}"
        provision = await self.exec(mkdir_cmd, user="root")
        if provision.return_code != 0:
            raise RuntimeError(
                f"failed to provision /logs dirs in {self.container_name}: "
                f"{provision.stderr or provision.stdout}"
            )

        await self._wait_for_server_ready()

    async def stop(self, delete: bool) -> None:
        if self._container_name is None:
            return
        argv = ["docker", "rm", "-f", self._container_name]
        result = await _run_subprocess(argv)
        if result.return_code != 0:
            self.logger.warning(
                "docker rm -f %s exited %d: %s",
                self._container_name,
                result.return_code,
                result.stderr or result.stdout,
            )
        _unregister_container(self._container_name)

    # ----- exec / file I/O -------------------------------------------------

    async def exec(
        self,
        command: str,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | int | None = None,
    ) -> ExecResult:
        user = self._resolve_user(user)
        merged_env = self._merge_env(env)
        effective_cwd = cwd or self.task_env_config.workdir

        argv = build_docker_exec_argv(
            container_name=self.container_name,
            command=command,
            cwd=effective_cwd,
            env=merged_env,
            user=user,
        )
        return await _run_subprocess(argv, timeout_sec=timeout_sec)

    async def upload_file(self, source_path: Path | str, target_path: str) -> None:
        argv = ["docker", "cp", str(source_path), f"{self.container_name}:{target_path}"]
        result = await _run_subprocess(argv)
        if result.return_code != 0:
            raise RuntimeError(f"docker cp upload failed: {result.stderr or result.stdout}")

    async def upload_dir(self, source_dir: Path | str, target_dir: str) -> None:
        # ``docker cp <src>/. <name>:<dst>`` copies contents of src into dst,
        # matching the semantics harbor callers expect (overwrite, not nest).
        await self.exec(f"mkdir -p {shlex.quote(target_dir)}", user="root")
        src = str(source_dir).rstrip("/") + "/."
        argv = ["docker", "cp", src, f"{self.container_name}:{target_dir}"]
        result = await _run_subprocess(argv)
        if result.return_code != 0:
            raise RuntimeError(f"docker cp upload_dir failed: {result.stderr or result.stdout}")

    async def download_file(self, source_path: str, target_path: Path | str) -> None:
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        argv = [
            "docker",
            "cp",
            f"{self.container_name}:{source_path}",
            str(target),
        ]
        result = await _run_subprocess(argv)
        if result.return_code != 0:
            raise RuntimeError(f"docker cp download failed: {result.stderr or result.stdout}")

    async def download_dir(self, source_dir: str, target_dir: Path | str) -> None:
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        argv = [
            "docker",
            "cp",
            f"{self.container_name}:{source_dir.rstrip('/')}/.",
            str(target),
        ]
        result = await _run_subprocess(argv)
        if result.return_code != 0:
            raise RuntimeError(f"docker cp download_dir failed: {result.stderr or result.stdout}")

    # ----- internal helpers -----------------------------------------------

    async def _build_image(self) -> None:
        repo_root = _resolve_repo_root()
        if repo_root is None:
            raise RuntimeError(
                "force_build=True but chi_bench is not installed from a source "
                "checkout (no docker/Dockerfile found above the package). "
                "Build the image manually with `chi-bench docker build`."
            )
        dockerfile = repo_root / "docker" / "Dockerfile"
        self.logger.info(
            "building image %s from %s (context=%s)", self._image, dockerfile, repo_root
        )
        argv = [
            "docker",
            "build",
            "-f",
            str(dockerfile),
            "-t",
            self._image,
            str(repo_root),
        ]
        result = await _run_subprocess(argv)
        if result.return_code != 0:
            raise RuntimeError(
                f"docker build failed (rc={result.return_code}): {result.stderr or result.stdout}"
            )

    async def _wait_for_server_ready(
        self,
        *,
        attempts: int = 120,
        poll_interval_s: float = 1.0,
    ) -> None:
        """Block until the in-container chi-bench server answers ``/health``.

        ``docker/entrypoint.sh`` runs as PID 1 and serially: boots the server,
        then probes :8023/health and the three MCP ports before ``exec``ing
        ``sleep infinity``. Once the entrypoint reaches the long-running CMD,
        all MCP session managers are wired up. We probe ``/health`` from
        the host via ``docker exec`` because harbor will start scheduling
        ``exec`` calls (agent install, agent run) as soon as ``start`` returns.
        """
        probe = (
            "import sys, urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('http://localhost:8023/health', timeout=3)\n"
            "    sys.exit(0)\n"
            "except Exception:\n"
            "    sys.exit(1)\n"
        )
        for attempt in range(attempts):
            result = await self.exec(f"python -c {shlex.quote(probe)}", timeout_sec=10, user="root")
            if result.return_code == 0:
                self.logger.debug(
                    "chi-bench server ready in %s after %d attempts",
                    self.container_name,
                    attempt + 1,
                )
                return
            await asyncio.sleep(poll_interval_s)
        raise RuntimeError(
            f"chi-bench server in {self.container_name} did not answer "
            f"/health within {attempts * poll_interval_s:.0f}s — check "
            f"container logs with `docker logs {self.container_name}`."
        )


# ----- subprocess helper ---------------------------------------------------


async def _run_subprocess(argv: list[str], *, timeout_sec: int | None = None) -> ExecResult:
    """Run ``argv`` and return harbor's ``ExecResult``.

    Captures stdout/stderr as decoded strings; surfaces timeouts as a
    distinguishable non-zero return code (124, mirroring ``timeout(1)``)
    so callers can react without inspecting an exception class.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
