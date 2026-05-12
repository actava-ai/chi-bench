"""Unified ChiBench CLI.

Usage:
    chi_bench serve [--port 8023] [--host 0.0.0.0]
    chi_bench mcp [--provider] [--payer] [--cm] [--host 0.0.0.0]
    chi_bench experiment run [-f config.yaml] [--dataset path] [--agent claude-code] [--model X] [-n 1]
"""

from __future__ import annotations

import os

# Prevent CPython from writing __pycache__/*.pyc during imports on the
# host side. Modal's `Image.from_dockerfile` walks the repo during build,
# and if any Python process (this CLI, harbor, a parallel pytest, an
# IDE indexer) writes a fresh .pyc mid-walk, Modal aborts the build with
# `ExecutionError: <path>.pyc was modified during build process`. The
# Dockerfile bakes this same env in the container image; setting it here
# closes the host-side source of the race so we don't need a .dockerignore
# to mask it. Must run BEFORE any `import chi_bench.*` statement.
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from collections.abc import Callable
from pathlib import Path
from urllib.request import urlopen

import subprocess

import typer
import yaml

app = typer.Typer(
    name="chi_bench",
    help="Healthcare simulation environment for AI agent evaluation.",
    no_args_is_help=True,
)

# ─── Subcommand groups ───────────────────────────────────────────────────────

experiment_app = typer.Typer(help="Experiment runner commands.", no_args_is_help=True)

app.add_typer(experiment_app, name="experiment")

data_app = typer.Typer(help="Data layout commands.", no_args_is_help=True)
app.add_typer(data_app, name="data")

submission_app = typer.Typer(
    help="Leaderboard submission commands (validate / run / status / package).",
    no_args_is_help=True,
)
app.add_typer(submission_app, name="submission")


@data_app.command("verify")
def data_verify(
    data_dir: Path = typer.Option(
        Path("data"), "--data-dir", help="Root of the downloaded dataset tree."
    ),
) -> None:
    """Check that the downloaded data tree matches what the runner expects.

    Supports two layouts:

    * **Source layout** (the host's ``data/`` tree, as downloaded from the
      release artifacts): one ``<domain>/tasks/`` directory per task family.
    * **Baked image layout** (``/opt/chi-bench`` inside the runtime image,
      produced by ``docker/Dockerfile``): all task families flattened under
      a single ``tasks/`` directory, with ``marathon/`` and ``worlds/`` as
      siblings. The handbook lives at ``/workspace/skills/...`` in this
      layout, not under ``data_dir``.

    The layout is auto-detected: if ``data_dir/tasks`` exists at the root
    but ``data_dir/prior_auth_provider/tasks`` does not, the baked layout
    is assumed.
    """
    EXPECTED_TASKS = {
        "prior_auth_provider": 25,
        "prior_auth_um": 25,
        "care_management": 25,
        "prior_auth_e2e": 23,
    }
    missing: list[str] = []
    bad_counts: list[str] = []

    flat_tasks = data_dir / "tasks"
    source_tasks = data_dir / "prior_auth_provider" / "tasks"
    is_baked_layout = flat_tasks.is_dir() and not source_tasks.is_dir()

    if is_baked_layout:
        # In the baked image layout, every task family is COPYed into the
        # same /opt/chi-bench/tasks/ directory plus a sibling marathon/
        # subdir. Verify the merged count and the marathon subdirs.
        n_expected_total = sum(EXPECTED_TASKS.values())
        n_actual = sum(1 for p in flat_tasks.iterdir() if p.is_dir() and p.name != "marathon")
        if n_actual != n_expected_total:
            bad_counts.append(
                f"{flat_tasks}: expected {n_expected_total} task dirs, got {n_actual}"
            )

        for dom in ("prior_auth_provider", "prior_auth_um", "care_management"):
            m = flat_tasks / "marathon" / dom
            if not m.exists():
                missing.append(str(m))

        if not (data_dir / "worlds").is_dir():
            missing.append(str(data_dir / "worlds"))

        # Handbook is baked at /workspace/skills/..., not under data_dir.
        handbook = Path("/workspace/skills/managed-care-operations-handbook")
        if not (handbook / "SKILL.md").exists():
            missing.append(str(handbook))
    else:
        # Source ("downloaded data") layout: data/<domain>/tasks/...
        for dom, n_expected in EXPECTED_TASKS.items():
            tasks_dir = data_dir / dom / "tasks"
            if not tasks_dir.exists():
                missing.append(str(tasks_dir))
                continue
            n_actual = sum(1 for p in tasks_dir.iterdir() if p.is_dir())
            if n_actual != n_expected:
                bad_counts.append(f"{tasks_dir}: expected {n_expected}, got {n_actual}")

        for dom in ("prior_auth_provider", "prior_auth_um", "care_management"):
            m = data_dir / "marathon" / dom
            if not m.exists():
                missing.append(str(m))

        handbook = data_dir / "skills" / "managed-care-operations-handbook"
        if not (handbook / "SKILL.md").exists():
            missing.append(str(handbook))

    if missing or bad_counts:
        typer.echo(
            "Data layout INCOMPLETE — see README §'Download data' for setup steps.", err=True
        )
        for path in missing:
            typer.echo(f"  missing: {path}", err=True)
        for line in bad_counts:
            typer.echo(f"  count mismatch: {line}", err=True)
        raise typer.Exit(1)

    typer.echo("OK — data layout matches expectations.")


docker_app = typer.Typer(help="Docker image commands.", no_args_is_help=True)
app.add_typer(docker_app, name="docker")


@docker_app.command("build")
def docker_build(
    tag: str = typer.Option("chi-bench:latest", "--tag", "-t", help="Image tag."),
    target: str = typer.Option("runtime", "--target", help="Build stage: runtime | ci-skeleton."),
) -> None:
    """Build the chi-bench single-image container."""
    import subprocess

    cmd = ["docker", "build", "-f", "docker/Dockerfile", "--target", target, "-t", tag, "."]
    typer.echo(f"$ {' '.join(cmd)}")
    raise typer.Exit(subprocess.call(cmd))


def _configure_logging(level: str) -> None:
    """Shared logging setup for all CLI commands."""
    import logging

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("anthropic").setLevel(logging.WARNING)


def _backend_health_probe_host(backend_host: str) -> str:
    normalized = backend_host.strip()
    if normalized in {"", "0.0.0.0", "::"}:
        return "127.0.0.1"
    return normalized


def _wait_for_backend_health(
    *,
    backend_host: str,
    backend_port: int,
    timeout_sec: float,
    poll_interval_sec: float = 0.5,
    urlopen_factory: Callable[..., object] = urlopen,
    monotonic: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> bool:
    import time

    monotonic = monotonic or time.monotonic
    sleeper = sleeper or time.sleep
    health_url = f"http://{_backend_health_probe_host(backend_host)}:{backend_port}/health"
    deadline = monotonic() + max(timeout_sec, 0.0)

    while True:
        if should_stop is not None and should_stop():
            return False
        try:
            response = urlopen_factory(health_url, timeout=1.0)
            with response:
                status = getattr(response, "status", 200)
                return 200 <= int(status) < 300
        except OSError:
            pass

        remaining = deadline - monotonic()
        if remaining <= 0:
            return False
        sleeper(min(poll_interval_sec, remaining))


def _launch_frontend_after_backend_ready(
    *,
    backend_host: str,
    backend_port: int,
    frontend_port: int,
    timeout_sec: float,
    frontend_dir: Path,
    wait_for_health: Callable[..., bool] = _wait_for_backend_health,
    popen_factory: Callable[..., object] | None = None,
    echo: Callable[[str], None] | Callable[..., None] = typer.echo,
    should_stop: Callable[[], bool] | None = None,
):
    import subprocess

    if should_stop is not None and should_stop():
        return None
    if not wait_for_health(
        backend_host=backend_host,
        backend_port=backend_port,
        timeout_sec=timeout_sec,
        should_stop=should_stop,
    ):
        if should_stop is None or not should_stop():
            echo(
                "Frontend dev server was not started because backend health "
                f"did not become ready within {timeout_sec:.1f}s.",
                err=True,
            )
        return None
    if should_stop is not None and should_stop():
        return None
    popen_factory = popen_factory or subprocess.Popen
    proc = popen_factory(
        ["npm", "run", "dev", "--", "--port", str(frontend_port)],
        cwd=frontend_dir,
    )
    echo(f"Frontend dev server started on http://localhost:{frontend_port}")
    return proc


# ─── serve ───────────────────────────────────────────────────────────────────


@app.command()
def serve(
    port: int = typer.Option(8023, help="Port to listen on."),
    host: str = typer.Option("0.0.0.0", help="Host to bind to."),
    no_frontend: bool = typer.Option(
        True, "--no-frontend/--frontend", help="Skip starting the frontend dev server."
    ),
    frontend_port: int = typer.Option(5180, "--frontend-port", help="Frontend dev server port."),
    frontend_wait_timeout: float = typer.Option(
        120.0,
        "--frontend-wait-timeout",
        help="Seconds to wait for backend /health before starting the frontend dev server.",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level."),
) -> None:
    """Start the ChiBench simulation server."""
    import os
    import signal
    import threading

    _configure_logging(log_level)

    def _kill_port(p: int) -> None:
        """Kill chi_bench/node processes listening on the given port.

        Only terminates processes whose command line matches known
        chi_bench-related programs to avoid killing unrelated services.
        """
        import subprocess
        import time

        # Get PID and command name for each listener
        result = subprocess.run(
            ["lsof", "-ti", f"tcp:{p}"],
            capture_output=True,
            text=True,
        )
        pids = result.stdout.strip().split()
        if not pids:
            return

        _SAFE_COMMANDS = {"python", "python3", "node", "npm", "uvicorn"}
        for pid in pids:
            try:
                pid_int = int(pid)
            except ValueError:
                continue
            # Resolve the process command before killing
            cmd_result = subprocess.run(
                ["ps", "-p", pid, "-o", "comm="],
                capture_output=True,
                text=True,
            )
            cmd_name = cmd_result.stdout.strip().lower()
            if not any(safe in cmd_name for safe in _SAFE_COMMANDS):
                typer.echo(
                    f"Warning: skipping PID {pid} on :{p} (command={cmd_name!r}) "
                    f"— not a known chi_bench process"
                )
                continue
            try:
                os.kill(pid_int, signal.SIGTERM)
                typer.echo(f"Killed PID {pid} ({cmd_name}) on :{p}")
            except ProcessLookupError:
                pass

        # Brief wait for port to be released by the OS
        time.sleep(0.3)

    try:
        _kill_port(port)
    except FileNotFoundError:
        pass  # lsof not available (e.g., slim Docker image)

    os.environ.setdefault("CHI_BENCH_PAYER_MODE", "agent")

    frontend_proc_holder: list[object | None] = [None]
    frontend_waiter: threading.Thread | None = None
    frontend_stop = threading.Event()
    if not no_frontend:
        frontend_dir = Path(__file__).resolve().parents[2] / "frontend" / "chi_bench"
        if not (frontend_dir / "package.json").exists():
            typer.echo(
                f"Frontend not found at {frontend_dir}; running backend only.",
                err=True,
            )
            no_frontend = True

    if not no_frontend:
        _kill_port(frontend_port)
        typer.echo(
            "Waiting for backend health before starting frontend dev server "
            f"(timeout {frontend_wait_timeout:.1f}s)."
        )

        def _wait_and_start_frontend() -> None:
            frontend_proc_holder[0] = _launch_frontend_after_backend_ready(
                backend_host=host,
                backend_port=port,
                frontend_port=frontend_port,
                timeout_sec=frontend_wait_timeout,
                frontend_dir=frontend_dir,
                should_stop=frontend_stop.is_set,
            )

        frontend_waiter = threading.Thread(
            target=_wait_and_start_frontend,
            name="chi_bench-frontend-waiter",
            daemon=True,
        )
        frontend_waiter.start()

    from chi_bench.server.app import create_unified_app  # noqa: E402
    from chi_bench.services.service import WorldService  # noqa: E402

    import uvicorn  # noqa: E402

    # ── Unified-process MCP: start provider/payer/cm MCP servers as threads
    # against the SAME ServiceContext the HTTP server will use. This keeps the
    # in-memory FHIR client singleton — without this, the MCP process and the
    # HTTP process each built their own ScenarioFHIRClient, so resources an
    # agent wrote via MCP (e.g., ServiceRequest) were invisible to /export
    # during verification.
    service = WorldService.from_env()
    ctx = service._ctx  # noqa: SLF001 — intentional: shared-ctx is the whole point

    from chi_bench.mcp.cm_constants import CM_MCP_PORT  # noqa: E402
    from chi_bench.mcp.cm_server import build_cm_mcp  # noqa: E402
    from chi_bench.mcp.payer_server import build_payer_mcp  # noqa: E402
    from chi_bench.mcp.server import build_provider_mcp  # noqa: E402

    mcp_servers = [
        build_provider_mcp(host=host, port=8020, ctx=ctx),
        build_payer_mcp(host=host, port=8100, ctx=ctx),
        build_cm_mcp(host=host, port=CM_MCP_PORT, ctx=ctx),
    ]
    for mcp_server in mcp_servers:
        threading.Thread(
            target=mcp_server.run,
            kwargs={"transport": "streamable-http"},
            name=f"mcp-{mcp_server.name}",
            daemon=True,
        ).start()
    typer.echo("MCP servers running — provider:8020  payer:8100  cm:8200")

    try:
        uvicorn_app = create_unified_app(service=service)
        uvicorn.run(uvicorn_app, host=host, port=port, log_level=log_level.lower())
    finally:
        frontend_stop.set()
        if frontend_waiter is not None:
            frontend_waiter.join(timeout=0.1)
        frontend_proc = frontend_proc_holder[0]
        if frontend_proc is not None:
            frontend_proc.terminate()
            frontend_proc.wait()


# ─── mcp ─────────────────────────────────────────────────────────────────────


@app.command()
def mcp(
    provider: bool = typer.Option(False, help="Start only the provider MCP server."),
    payer: bool = typer.Option(False, help="Start only the payer MCP server."),
    cm: bool = typer.Option(False, help="Start only the care management MCP server."),
    host: str = typer.Option("0.0.0.0", help="Host to bind to."),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level."),
) -> None:
    """Start MCP servers. No flags starts all three; use --provider/--payer/--cm for one."""
    _configure_logging(log_level)

    start_all = not (provider or payer or cm)

    if start_all:
        import threading

        from chi_bench.mcp.cm_constants import CM_MCP_PORT
        from chi_bench.mcp.cm_server import build_cm_mcp
        from chi_bench.mcp.payer_server import build_payer_mcp
        from chi_bench.mcp.server import build_provider_mcp

        servers = [
            build_provider_mcp(host=host, port=8020),
            build_payer_mcp(host=host, port=8100),
            build_cm_mcp(host=host, port=CM_MCP_PORT),
        ]
        threads = [
            threading.Thread(target=s.run, kwargs={"transport": "streamable-http"}, daemon=True)
            for s in servers
        ]
        for t in threads:
            t.start()
        typer.echo("MCP servers running — provider:8020  payer:8100  cm:8200")
        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            pass
    elif cm:
        from chi_bench.mcp.cm_constants import CM_MCP_PORT
        from chi_bench.mcp.cm_server import build_cm_mcp

        build_cm_mcp(host=host, port=CM_MCP_PORT).run(transport="streamable-http")
    elif payer:
        from chi_bench.mcp.payer_server import build_payer_mcp

        build_payer_mcp(host=host, port=8100).run(transport="streamable-http")
    else:
        from chi_bench.mcp.server import build_provider_mcp

        build_provider_mcp(host=host, port=8020).run(transport="streamable-http")


# ─── experiment ──────────────────────────────────────────────────────────────


@experiment_app.command("run")
def experiment_run(
    config: str | None = typer.Option(None, "-f", "--config", help="Experiment config YAML."),
    dataset: str | None = typer.Option(None, "--dataset", help="Path to dataset or registry ID."),
    agent: str = typer.Option("claude-code", "--agent", help="Agent identifier."),
    model: str | None = typer.Option(None, "--model", help="Model identifier."),
    n_concurrent: int = typer.Option(1, "-n", help="Number of concurrent trials."),
    trials_dir: str | None = typer.Option(
        None, "--trials-dir", help="Harbor trials output directory."
    ),
    environment: str | None = typer.Option(
        None,
        "-e",
        "--environment",
        help=(
            "Execution environment: 'docker' (default) or 'modal'. "
            "The runner auto-terminates its own sandboxes on exit; residual "
            "orphans can still be listed with `modal container list` and "
            "stopped with `modal container stop <id>`."
        ),
    ),
    modal_profile: str | None = typer.Option(
        None,
        "--modal-profile",
        help="Modal profile name from ~/.modal.toml (default: actava). Pass '' to opt out of preflight.",
    ),
    modal_sandbox_timeout_secs: int | None = typer.Option(
        None,
        "--modal-sandbox-timeout-secs",
        help="Per-sandbox lifetime cap in seconds (default: 86400). "
        "Matches YAML key `modal.sandbox_timeout_secs`.",
    ),
    modal_force_build: bool | None = typer.Option(
        None,
        "--modal-force-build/--no-modal-force-build",
        help="Force Modal to rebuild the environment image.",
    ),
) -> None:
    """Run an experiment (Harbor trial or job)."""
    from chi_bench.experiment.runner import run_experiment

    if environment is not None and environment not in {"docker", "modal"}:
        raise typer.BadParameter(
            f"--environment must be 'docker' or 'modal' (got {environment!r})."
        )

    run_experiment(
        config=config,
        dataset=dataset,
        agent=agent,
        model=model,
        concurrency=n_concurrent,
        trials_dir=trials_dir,
        environment=environment,  # type: ignore[arg-type]
        modal_profile=modal_profile,
        modal_sandbox_timeout_secs=modal_sandbox_timeout_secs,
        modal_force_build=modal_force_build,
    )


@experiment_app.command("rejudge")
def experiment_rejudge(
    trial_root: Path = typer.Option(
        ...,
        "--trial-root",
        help="Directory containing Harbor trial subdirs (each with verifier/).",
    ),
    environment: str = typer.Option(
        "modal",
        "-e",
        "--environment",
        help=(
            "Execution environment: 'local' (sequential, in-process) or 'modal' "
            "(currently a ThreadPoolExecutor at --concurrency; true Modal "
            "sandbox wiring is a follow-up)."
        ),
    ),
    concurrency: int = typer.Option(
        10,
        "-n",
        "--concurrency",
        help="Max parallel judge sessions when --environment=modal.",
    ),
    output_subdir: str = typer.Option(
        "verifier_rejudge",
        "--output-subdir",
        help=(
            "Per-trial output directory for rejudge artifacts (scorecard.json, "
            "verdicts.json, judge_session_metadata.json). Original verifier/ "
            "dir is never modified."
        ),
    ),
    task_dataset_root: Path = typer.Option(
        Path("data/care_management/tasks"),
        "--task-dataset-root",
        help=(
            "Root of task dataset; each trial's expectations.json is resolved "
            "by stripping the Harbor '__<slug>' suffix from the trial dir name "
            "and looking under <task_dataset_root>/<task_id>/fixtures/."
        ),
    ),
) -> None:
    """Rerun only the judge stage across all trials under ``--trial-root``."""
    from chi_bench.experiment.runner import run_rejudge

    if environment not in {"local", "modal"}:
        raise typer.BadParameter(f"--environment must be 'local' or 'modal' (got {environment!r}).")

    run_rejudge(
        trial_root=trial_root,
        environment=environment,
        concurrency=concurrency,
        output_subdir=output_subdir,
        task_dataset_root=task_dataset_root,
    )


@experiment_app.command("status")
def experiment_status(
    trials_dir: str = typer.Option("trials/", "--trials-dir", help="Harbor trials directory."),
) -> None:
    """Show experiment status from Harbor trials directory."""
    from pathlib import Path

    trials_path = Path(trials_dir)
    if not trials_path.exists():
        typer.echo(f"Trials directory not found: {trials_dir}")
        raise typer.Exit(1)

    trial_dirs = sorted(d for d in trials_path.iterdir() if d.is_dir())
    typer.echo(f"Trials directory: {trials_path}")
    typer.echo(f"Total trials: {len(trial_dirs)}")

    for trial_dir in trial_dirs:
        reward_file = trial_dir / "reward.txt"
        status = "complete" if reward_file.exists() else "running"
        reward = reward_file.read_text().strip() if reward_file.exists() else "-"
        typer.echo(f"  {trial_dir.name}: {status} (reward={reward})")


# ─── submission ──────────────────────────────────────────────────────────────


@submission_app.command("validate")
def submission_validate(
    config: Path = typer.Option(
        ..., "-f", "--config", help="Submission YAML to validate."
    ),
    skip_preflight: bool = typer.Option(
        False,
        "--skip-preflight",
        help="Schema-check only; don't probe Docker / Modal / dataset state.",
    ),
) -> None:
    """Validate a submission YAML.

    Schema check is always performed. Without ``--skip-preflight`` the command
    also verifies dataset version pinning, the chosen environment's CLI/token,
    and (warns) on unknown agent names.

    Exit code 0 only when there are no errors; warnings are printed but
    non-blocking.
    """
    from pydantic import ValidationError

    from chi_bench.experiment.submission import SubmissionConfig, run_all_preflight

    try:
        cfg = SubmissionConfig.from_yaml(config)
    except ValidationError as e:
        typer.echo(f"Schema error in {config}:", err=True)
        typer.echo(str(e), err=True)
        raise typer.Exit(2) from None
    except (yaml.YAMLError, ValueError, OSError) as e:
        typer.echo(f"Could not load {config}: {e}", err=True)
        raise typer.Exit(2) from None

    typer.echo(f"Schema OK ({cfg.schema_})")
    typer.echo(f"  id:       {cfg.submission.id}")
    typer.echo(f"  agent:    {cfg.submission.agent}")
    typer.echo(f"  model:    {cfg.submission.model}")
    typer.echo(f"  domains:  {', '.join(cfg.dataset.domains)}")
    typer.echo(f"  env:      {cfg.run.environment}")
    typer.echo(f"  attempts: {cfg.run.n_attempts}")
    typer.echo(f"  output:   {cfg.paths.output_root}")

    if skip_preflight:
        return

    issues = run_all_preflight(cfg)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    for w in warnings:
        typer.echo(f"warning [{w.code}]: {w.message}")
    for e in errors:
        typer.echo(f"ERROR   [{e.code}]: {e.message}", err=True)

    if errors:
        raise typer.Exit(1)
    typer.echo("Preflight OK." if not warnings else f"Preflight OK ({len(warnings)} warning(s)).")


@submission_app.command("run")
def submission_run(
    config: Path = typer.Option(
        ..., "-f", "--config", help="Submission YAML to execute."
    ),
    domain: list[str] = typer.Option(
        [],
        "--domain",
        help=(
            "Restrict to one or more domains (pa | um | cm or canonical names). "
            "Repeatable. Default: every domain listed in sub.yaml."
        ),
    ),
    skip_preflight: bool = typer.Option(
        False,
        "--skip-preflight",
        help="Skip dataset/environment/agent preflight checks (NOT recommended).",
    ),
) -> None:
    """Run a submission end-to-end.

    Loads sub.yaml, runs preflight (unless skipped), then runs each selected
    domain through ``run_experiment()``. Outputs land under
    ``logs/submissions/<id>/`` by default. Aggregation + manifest writing is
    layered on in subsequent commands; this command produces the raw trial
    tree.
    """
    from pydantic import ValidationError

    from chi_bench.experiment.submission import (
        SubmissionConfig,
        run_all_preflight,
        run_submission,
    )

    try:
        cfg = SubmissionConfig.from_yaml(config)
    except ValidationError as e:
        typer.echo(f"Schema error in {config}:\n{e}", err=True)
        raise typer.Exit(2) from None
    except (yaml.YAMLError, ValueError, OSError) as e:
        typer.echo(f"Could not load {config}: {e}", err=True)
        raise typer.Exit(2) from None

    if not skip_preflight:
        issues = run_all_preflight(cfg)
        errors = [i for i in issues if i.severity == "error"]
        for w in (i for i in issues if i.severity == "warning"):
            typer.echo(f"warning [{w.code}]: {w.message}")
        if errors:
            for e in errors:
                typer.echo(f"ERROR   [{e.code}]: {e.message}", err=True)
            raise typer.Exit(1)

    try:
        output_root = run_submission(
            cfg=cfg,
            source_yaml=config,
            domain_filter=domain or None,
        )
    except (ValueError, RuntimeError) as e:
        typer.echo(f"Submission failed: {e}", err=True)
        raise typer.Exit(1) from None

    typer.echo(f"Submission '{cfg.submission.id}' finished. Outputs: {output_root}")


@submission_app.command("status")
def submission_status_cmd(
    config: Path = typer.Option(
        ..., "-f", "--config", help="Submission YAML."
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON instead of the table."
    ),
) -> None:
    """Show progress per domain for a submission's output tree.

    Counts completed trials and pass/fail tallies under
    ``logs/submissions/<id>/`` (or whatever ``paths.output_root`` points at).
    Trials without ``result.json`` are running and not yet counted.
    """
    from pydantic import ValidationError

    from chi_bench.experiment.submission import SubmissionConfig, status_submission

    try:
        cfg = SubmissionConfig.from_yaml(config)
    except (ValidationError, yaml.YAMLError, ValueError, OSError) as e:
        typer.echo(f"Could not load {config}: {e}", err=True)
        raise typer.Exit(2) from None

    status = status_submission(cfg)

    if json_out:
        import json as _json

        typer.echo(_json.dumps(status, indent=2))
        return

    typer.echo(f"Submission: {status['submission_id']}")
    typer.echo(f"Output:     {status['output_root']}")
    typer.echo(f"Started:    {status['started_at'] or '(not yet)'}")
    typer.echo(f"Finished:   {status['finished_at'] or '(in progress)'}")
    typer.echo("")
    typer.echo(f"{'Domain':<14} {'Expected':>9} {'Trials':>7} {'Pass':>6} {'Fail':>6}  State")
    for d in status["domains"]:
        expected = d["expected_tasks"] or "?"
        typer.echo(
            f"{d['domain']:<14} {str(expected):>9} {d['n_trials']:>7} "
            f"{d['n_passed']:>6} {d['n_failed']:>6}  {d['state']}"
        )


@submission_app.command("package")
def submission_package_cmd(
    config: Path = typer.Option(
        ..., "-f", "--config", help="Submission YAML."
    ),
    output_zip: Path | None = typer.Option(
        None,
        "-o",
        "--output",
        help="Zip output path. Default: <output_root>/<submission_id>.zip.",
    ),
) -> None:
    """Build the upload-ready submission packet.

    Bundles the manifest + CSV + frozen sub.yaml + per-trial scorecard /
    reward / result / trajectory.json. Workspace artifacts, server logs,
    agent session caches, and Harbor scratch files are deliberately
    excluded so the zip stays small (typically <50 MB for a 75-trial
    pass@1 submission). The raw trial tree on disk is unchanged.
    """
    from pydantic import ValidationError

    from chi_bench.experiment.submission import SubmissionConfig, package_submission

    try:
        cfg = SubmissionConfig.from_yaml(config)
    except (ValidationError, yaml.YAMLError, ValueError, OSError) as e:
        typer.echo(f"Could not load {config}: {e}", err=True)
        raise typer.Exit(2) from None

    try:
        zip_path = package_submission(cfg, zip_path=output_zip)
    except FileNotFoundError as e:
        typer.echo(f"Cannot package: {e}", err=True)
        raise typer.Exit(1) from None

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    typer.echo(f"Packet written: {zip_path} ({size_mb:.1f} MB)")


# ─── data download (writes data/.chi-bench-version) ─────────────────────────


@data_app.command("download")
def data_download(
    revision: str = typer.Option(
        ...,
        "--revision",
        help=(
            "HF dataset revision tag (e.g. 'chi-bench-v1.0.0'). Pinned in "
            "data/.chi-bench-version so submission preflight can verify it."
        ),
    ),
    repo_id: str = typer.Option(
        "actava/chi-bench", "--repo-id", help="HF repo id."
    ),
    data_dir: Path = typer.Option(
        Path("data"), "--data-dir", help="Local data root."
    ),
) -> None:
    """Download the chi-Bench dataset from Hugging Face at a pinned revision.

    Equivalent to ``huggingface-cli download <repo> --revision <rev>
    --local-dir data/``, plus writing the revision tag to
    ``data/.chi-bench-version``. Submitters MUST use this command (not raw
    ``huggingface-cli``) so the version pin works.
    """
    from chi_bench.experiment.submission import download_dataset

    try:
        download_dataset(revision=revision, repo_id=repo_id, data_root=data_dir)
    except (RuntimeError, subprocess.CalledProcessError) as e:
        typer.echo(f"Download failed: {e}", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Dataset downloaded into {data_dir} (revision={revision}).")
