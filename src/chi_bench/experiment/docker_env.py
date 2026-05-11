"""Local-Docker Harbor Environment for the chi-Bench single-image layout.

Mirrors ChiBenchModalEnvironment but runs a fresh local ``docker run`` per
trial. Wires the per-task fixtures by injecting CHI_BENCH_TASK_ID into the
container env; the in-container entrypoint resolves
``/opt/chi-bench/tasks/<id>`` based on that variable.

NOTE: This module currently ships only the argv assembly logic
(``build_docker_run_argv``) needed by the runner. Full Harbor ``Environment``
protocol integration (``start``/``stop``/``exec``/``download_dir`` lifecycle
methods, akin to ``ChiBenchModalEnvironment``) is intentionally deferred — it
will be added when the local-Docker backend is wired end-to-end through
Harbor's runner. See ``chi_bench.experiment.modal_env`` for the Harbor
protocol shape that future work will mirror.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path


# Host environment variables forwarded into the local Docker container.
# Mirrors the agent/server credential keys the Modal backend forwards,
# trimmed to the subset relevant for local single-image trial runs.
FORWARDED_ENV_KEYS: tuple[str, ...] = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "CHI_BENCH_SKILLS_ABLATE",
    "CHI_BENCH_TOOL_MODE",
)


@dataclass
class ChiBenchDockerEnvironment:
    """Minimal local-Docker environment shim.

    Encapsulates the argv assembly for ``docker run`` invocations against the
    single-image chi-Bench container. The in-container entrypoint reads
    ``CHI_BENCH_TASK_ID`` to resolve per-task fixtures from
    ``/opt/chi-bench/tasks/<task_id>``, so the only required wiring at the
    host boundary is forwarding that variable plus agent/provider API keys.
    """

    task_path: Path
    image: str = "chi-bench:latest"
    host_env: Mapping[str, str] = field(default_factory=dict)
    trial_artifacts_dir: Path | None = None

    @property
    def task_id(self) -> str:
        """Return the task id derived from the task directory name."""
        return self.task_path.name

    def build_docker_run_argv(self, agent_command: list[str]) -> list[str]:
        """Build a ``docker run`` argv that launches the trial container.

        Parameters
        ----------
        agent_command:
            The command (and its argv tail) to execute inside the container.
            Appended verbatim at the end of the returned argv.

        Returns
        -------
        list[str]
            A fully-formed argv ready for ``subprocess.run``.
        """
        argv: list[str] = ["docker", "run", "--rm"]
        argv += ["-e", f"CHI_BENCH_TASK_ID={self.task_id}"]
        for key in FORWARDED_ENV_KEYS:
            value = self.host_env.get(key)
            if value:
                argv += ["-e", f"{key}={value}"]
        if self.trial_artifacts_dir is not None:
            argv += ["-v", f"{self.trial_artifacts_dir}:/logs/artifacts"]
        argv += [self.image]
        argv += list(agent_command)
        return argv
