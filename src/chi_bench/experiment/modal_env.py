"""Modal transport for the isolated Docker server-and-agent trial lifecycle."""

from __future__ import annotations

import asyncio
import atexit
import logging
import os
import tempfile
import threading
import warnings
from pathlib import Path
from typing import Any
from uuid import uuid4

from harbor.environments.base import ExecResult
from harbor.environments.tar_transfer import extract_dir_from_file, pack_dir_to_file
from harbor.models.environment_type import EnvironmentType
from harbor.models.trial.paths import EnvironmentPaths
from modal import App, Image, Sandbox, Secret, Volume
from modal.exception import DeprecationError, PendingDeprecationError

from chi_bench.experiment.build_context import create_build_context_archive
from chi_bench.experiment.docker_env import FORWARDED_ENV_KEYS, ChiBenchDockerEnvironment

logger = logging.getLogger(__name__)


def _install_deprecation_filters() -> None:
    warnings.filterwarnings("ignore", category=DeprecationError)
    warnings.filterwarnings("ignore", category=PendingDeprecationError)


_install_deprecation_filters()
_ACTIVE_SANDBOXES: list[Any] = []
_ACTIVE_SANDBOXES_LOCK = threading.Lock()
_ATEXIT_REGISTERED = False


def _register_sandbox(sandbox: Any) -> None:
    global _ATEXIT_REGISTERED
    with _ACTIVE_SANDBOXES_LOCK:
        if sandbox not in _ACTIVE_SANDBOXES:
            _ACTIVE_SANDBOXES.append(sandbox)
        if not _ATEXIT_REGISTERED:
            atexit.register(_terminate_tracked_sandboxes)
            _ATEXIT_REGISTERED = True


def _unregister_sandbox(sandbox: Any) -> None:
    with _ACTIVE_SANDBOXES_LOCK:
        if sandbox in _ACTIVE_SANDBOXES:
            _ACTIVE_SANDBOXES.remove(sandbox)


def _terminate_tracked_sandboxes() -> None:
    with _ACTIVE_SANDBOXES_LOCK:
        sandboxes = list(_ACTIVE_SANDBOXES)
        _ACTIVE_SANDBOXES.clear()
    for sandbox in sandboxes:
        try:
            sandbox.terminate()
        except Exception:
            logger.warning("failed to terminate a tracked Modal sandbox")


SERVER_ENV_FORWARD_KEYS = FORWARDED_ENV_KEYS
MODAL_TASKS_ROOT = "/opt/chi-bench/tasks"
_AGENT_LOG_PRUNE_RELATIVE_PATHS = (".tmp/plugins", "cache/codex_apps_tools")


def _collect_forwarded_env() -> dict[str, str]:
    return {key: os.environ[key] for key in SERVER_ENV_FORWARD_KEYS if os.environ.get(key)}


def _is_agent_log_dir(source_dir: str) -> bool:
    return source_dir.rstrip("/") == str(EnvironmentPaths.agent_dir).rstrip("/")


def _resolve_repo_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "docker/Dockerfile").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("The Modal backend requires a chi-bench source checkout")


def _resolve_task_dir(environment_dir: Path) -> Path:
    task_dir = environment_dir.parent.resolve()
    if not (task_dir / "task.toml").is_file() or not (task_dir / "fixtures").is_dir():
        raise FileNotFoundError("The Modal task must contain task.toml and fixtures/")
    return task_dir


def _add_task_dir_override(image: Any, environment_dir: Path) -> Any:
    """Legacy image-builder helper; the isolated lifecycle uses server-only copies."""
    task_dir = _resolve_task_dir(environment_dir)
    return image.add_local_dir(
        task_dir, remote_path=f"{MODAL_TASKS_ROOT}/{task_dir.name}", copy=False
    )


class ChiBenchModalEnvironment(ChiBenchDockerEnvironment):
    """Run the common isolated lifecycle against a task-owned Modal Docker engine."""

    _uses_host_network = True

    def __init__(
        self,
        *args: Any,
        sandbox_timeout_secs: int = 86400,
        sandbox_idle_timeout_secs: int | None = None,
        secrets: list[str] | None = None,
        volumes: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        self._sandbox: Any = None
        self._app: Any = None
        self._outer_image: Any = None
        self._remote_build_context: str | None = None
        self._sandbox_timeout = sandbox_timeout_secs
        self._sandbox_idle_timeout = sandbox_idle_timeout_secs
        self._secrets = secrets or []
        self._volumes = volumes or {}
        super().__init__(*args, **kwargs)

    @staticmethod
    def type() -> str:
        return EnvironmentType.MODAL

    @classmethod
    def preflight(cls) -> None:
        # The host needs Modal credentials, not a local Docker daemon.
        return

    async def _create_sandbox(
        self, gpu_config: str | None, secrets_config: list, volumes_config: dict
    ) -> Sandbox:
        sandbox = await Sandbox.create.aio(
            app=self._app,
            image=self._outer_image,
            timeout=self._sandbox_timeout,
            idle_timeout=self._sandbox_idle_timeout,
            name=self.session_id,
            cpu=self.task_env_config.cpus,
            memory=self.task_env_config.memory_mb,
            gpu=gpu_config,
            block_network=False,
            secrets=secrets_config,
            volumes=volumes_config,
            experimental_options={"enable_docker": True},
        )
        _register_sandbox(sandbox)
        return sandbox

    async def start(self, force_build: bool) -> None:
        self._outer_image = Image.from_registry("docker:28.3.3-dind").run_commands(
            "mkdir -p /etc/docker",
            'printf \'%s\\n\' \'{"iptables":false,"bridge":"none"}\' > /etc/docker/daemon.json',
        )
        self._app = await App.lookup.aio(name="__harbor__", create_if_missing=True)
        try:
            creation = asyncio.create_task(
                self._create_sandbox(
                    gpu_config=None,
                    secrets_config=[Secret.from_name(name) for name in self._secrets],
                    volumes_config={
                        path: Volume.from_name(name) for path, name in self._volumes.items()
                    },
                )
            )
            try:
                self._sandbox = await asyncio.shield(creation)
            except asyncio.CancelledError:
                self._sandbox = await creation
                raise
            await self._wait_for_docker_ready()
            await super().start(force_build=True)
        except BaseException:
            try:
                await asyncio.shield(self.stop(delete=True))
            except Exception:
                self.logger.warning("Modal startup cleanup failed; sandbox remains tracked")
            raise

    async def stop(self, delete: bool) -> None:
        sandbox = self._sandbox
        if sandbox is None:
            return
        try:
            await super().stop(delete=delete)
        finally:
            await sandbox.terminate.aio()
            _unregister_sandbox(sandbox)
            self._sandbox = None
            self._app = None
            self._remote_build_context = None

    async def _run(
        self, argv: list[str], *, timeout_sec: int | None = None, env: dict | None = None
    ) -> ExecResult:
        if self._sandbox is None:
            raise RuntimeError("The Modal Docker engine has not been started")
        try:
            process = await self._sandbox.exec.aio(*argv, timeout=timeout_sec, env=env or None)
            reads = asyncio.gather(
                process.stdout.read.aio(), process.stderr.read.aio(), process.wait.aio()
            )
            if timeout_sec is None:
                stdout, stderr, return_code = await reads
            else:
                stdout, stderr, return_code = await asyncio.wait_for(reads, timeout=timeout_sec + 5)
        except TimeoutError:
            return ExecResult(return_code=124, stderr=f"timeout after {timeout_sec}s")
        return ExecResult(stdout=stdout, stderr=stderr, return_code=return_code)

    async def _wait_for_docker_ready(
        self, *, attempts: int = 60, poll_interval_s: float = 1.0
    ) -> None:
        for _ in range(attempts):
            result = await self._run(
                ["docker", "info", "--format", "{{.ServerVersion}}"], timeout_sec=5
            )
            if result.return_code == 0:
                return
            await asyncio.sleep(poll_interval_s)
        raise RuntimeError("The Modal Docker daemon did not become ready")

    async def _staging_command(self, argv: list[str]) -> None:
        result = await self._run(argv, timeout_sec=600)
        if result.return_code != 0:
            raise RuntimeError(f"Modal file staging failed (rc={result.return_code})")

    async def _remove_staging(self, path: str) -> None:
        try:
            await self._run(["rm", "-rf", path], timeout_sec=30)
        except Exception:
            self.logger.warning("failed to remove a Modal staging directory")

    async def _copy_to_container(
        self, source: Path, container: str, target: str, *, directory: bool = False
    ) -> None:
        if self._sandbox is None:
            raise RuntimeError("The Modal Docker engine has not been started")
        source = Path(source)
        staging = f"/tmp/chi-bench-transfer-{uuid4().hex}"
        try:
            await self._staging_command(["mkdir", "-p", staging])
            payload = f"{staging}/payload"
            if directory:
                archive = f"{staging}/upload.tar.gz"
                with tempfile.TemporaryDirectory(prefix="chi-bench-upload-") as local:
                    local_archive = Path(local) / "upload.tar.gz"
                    await asyncio.to_thread(pack_dir_to_file, source, local_archive)
                    await self._sandbox.filesystem.copy_from_local.aio(local_archive, archive)
                await self._staging_command(["mkdir", "-p", payload])
                await self._staging_command(["tar", "-xzf", archive, "-C", payload])
                payload += "/."
            else:
                await self._sandbox.filesystem.copy_from_local.aio(source, payload)
                await self._staging_command(
                    ["chmod", f"{source.stat().st_mode & 0o777:o}", payload]
                )
            await self._staging_command(["docker", "cp", payload, f"{container}:{target}"])
        finally:
            await self._remove_staging(staging)

    async def _copy_from_container(
        self, container: str, source: str, target: Path, *, directory: bool = False
    ) -> None:
        if self._sandbox is None:
            raise RuntimeError("The Modal Docker engine has not been started")
        target = Path(target)
        staging = f"/tmp/chi-bench-transfer-{uuid4().hex}"
        try:
            await self._staging_command(["mkdir", "-p", staging])
            payload = f"{staging}/payload"
            if directory:
                target.mkdir(parents=True, exist_ok=True)
                await self._staging_command(["mkdir", "-p", payload])
                await self._staging_command(
                    ["docker", "cp", f"{container}:{source.rstrip('/')}/.", payload]
                )
                archive = f"{staging}/download.tar.gz"
                # The agent is already stopped during verification. Filter the
                # outer staging archive without executing in either inner
                # container or modifying the frozen source logs.
                excludes = (
                    [f"--exclude=./{path}" for path in _AGENT_LOG_PRUNE_RELATIVE_PATHS]
                    if container == self.container_name and _is_agent_log_dir(source)
                    else []
                )
                await self._staging_command(["tar", *excludes, "-czf", archive, "-C", payload, "."])
                with tempfile.TemporaryDirectory(prefix="chi-bench-download-") as local:
                    local_archive = Path(local) / "download.tar.gz"
                    await self._sandbox.filesystem.copy_to_local.aio(archive, local_archive)
                    await asyncio.to_thread(extract_dir_from_file, local_archive, target)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                await self._staging_command(["docker", "cp", f"{container}:{source}", payload])
                await self._sandbox.filesystem.copy_to_local.aio(payload, target)
        finally:
            await self._remove_staging(staging)

    async def _engine_build_context(self) -> str:
        if self._remote_build_context is not None:
            return self._remote_build_context
        if self._sandbox is None:
            raise RuntimeError("The Modal Docker engine has not been started")
        staging = f"/tmp/chi-bench-build-{uuid4().hex}"
        context = f"{staging}/context"
        archive = f"{staging}/context.tar.gz"
        try:
            await self._staging_command(["mkdir", "-p", context])
            with tempfile.TemporaryDirectory(prefix="chi-bench-build-") as local:
                local_archive = Path(local) / "context.tar.gz"
                await asyncio.to_thread(
                    create_build_context_archive, _resolve_repo_root(), local_archive
                )
                await self._sandbox.filesystem.copy_from_local.aio(local_archive, archive)
            await self._staging_command(["tar", "-xzf", archive, "-C", context])
            await self._staging_command(["rm", "-f", archive])
        except BaseException:
            await self._remove_staging(staging)
            raise
        self._remote_build_context = context
        return context
