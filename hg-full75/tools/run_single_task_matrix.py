from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event
from chi_resume_guard import bind_contract, resume_rows, seal_task, atomic_json, backup_task
from paid_run_gate import PaidRunDenied, require_paid_run_authorized
from offhost_backup_gate import BackupTargetDenied, require_offhost_backup_root
from chi_offhost_backup import BackupError, backup_dir_to_remote, remote_exists, require_rclone_remote
from chi_budget_proxy import BudgetDenied, require_budget_proxy, routing_problems

# Named rclone remote (e.g. chi-gdrive:HG-Backups/chi-bench). When set, every sealed
# local backup is also pushed off-host and byte-verified before the next task is admitted.
RCLONE_REMOTE: str | None = None


def backup_offhost(out, backup_root, identity_path, fingerprint, task_id, reack=False):
    backup_task(out, backup_root, identity_path, fingerprint, task_id)
    if RCLONE_REMOTE:
        remote_path = f"{RCLONE_REMOTE.rstrip('/')}/{fingerprint}/{task_id}.tgz"
        # A resumed completion re-acknowledges a copy that was already byte-verified
        # when it was written. Re-packing produces different bytes (fresh manifest
        # timestamp), so verify presence instead of pretending to re-verify content.
        if reack and remote_exists(remote_path):
            print(f"REMOTE_PRESENT {task_id}", flush=True)
            return
        try:
            backup_dir_to_remote(Path(backup_root) / fingerprint / task_id, remote_path)
        except BackupError as exc:
            raise OSError(f"remote_backup_failed:{exc}") from None

FREEZE_FILE = Path(__file__).resolve().parents[1] / "PAID_RUN_FREEZE.json"

# Match provider error signatures, not vague mentions of a budget.
API_LIMIT_SIGNATURES = (
    "insufficient_quota",
    "exceeded your current quota",
    "credit balance is too low",
    "billing_hard_limit_reached",
    "usage_limit_reached",
    "api usage limit",
    "usage limit reached",
    "usage limit has been reached",
    "quota exceeded",
    "billing limit",
    "spending limit has been reached",
    "rate limit exceeded",
    "rate limit reached",
    "rate_limit_error",
)


def api_limit_failure(out: Path) -> str | None:
    """Return a safe signature/source, never provider response text or secrets."""
    sources = [out / "launcher.log"]
    sources.extend(out.rglob("result.json"))
    # Tool errors may not propagate to exception_info (CM/P2P credit errors).
    sources.extend(out.rglob("agent/codex.txt"))
    for source in sources:
        if not source.is_file():
            continue
        with source.open(errors="replace") as log:
            for line in log:
                normalized = line.lower()
                for signature in API_LIMIT_SIGNATURES:
                    if signature in normalized:
                        return f"{source.relative_to(out)}: {signature}"
    return None


def write_checkpoint(path: Path, payload: dict) -> None:
    atomic_json(path, payload)

DOMAINS = {
    "provider": "prior_auth_provider",
    "payer": "prior_auth_um",
    "care": "care_management",
}


def plan(root: Path, domain: str, model: str, output_root: Path | None = None) -> list[tuple[str, list[str], Path]]:
    dataset = root / "data" / DOMAINS[domain] / "tasks"
    tasks = sorted(p for p in dataset.iterdir() if p.is_dir() and (p / "task.toml").is_file())
    if len(tasks) != 25:
        raise ValueError(f"{domain}: expected 25 official task.toml files, found {len(tasks)}")
    cb = root / ".venv" / "bin" / "cb"
    if not cb.is_file():
        raise ValueError(f"Missing installed CLI: {cb}")
    rows = []
    for task in tasks:
        out = (output_root or root / "trials" / "full75") / domain / task.name
        # Each path contains task.toml, forcing the official runner's
        # tested 'harbor trials start' route instead of 'jobs start'.
        cmd = [
            str(cb), "experiment", "run",
            "--dataset", str(task),
            "--agent", "hg-closure-codex",
            "--model", model,
            "--environment", "docker",
            "--trials-dir", str(out),
        ]
        rows.append((task.name, cmd, out))
    return rows


def execute(row: tuple[str, list[str], Path], root: Path, stop: Event, fingerprint: str | None = None) -> tuple[str, bool, str | None]:
    name, cmd, out = row
    if stop.is_set():
        return name, False, None
    out.mkdir(parents=True, exist_ok=False)
    if fingerprint:
        atomic_json(out / "hg-task-started.json", {"task_id": name, "fingerprint": fingerprint})
    print(f"START {name}", flush=True)
    with (out / "launcher.log").open("w") as log:
        result = subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=False)
    results = list(out.rglob("result.json"))
    rewards = list(out.rglob("verifier/reward.json"))
    limit = api_limit_failure(out)
    if limit:
        stop.set()
    complete = result.returncode == 0 and len(results) == 1 and len(rewards) == 1 and limit is None
    if complete and fingerprint:
        try:
            seal_task(out, fingerprint, name)
        except (ValueError, OSError):
            complete = False
            stop.set()
    print(f"END {name} exit={result.returncode} results={len(results)} rewards={len(rewards)}", flush=True)
    return name, complete, limit


def run_rows(rows: list[tuple[str, list[str], Path]], root: Path, domain: str, concurrency: int, fingerprint: str | None = None, output_root: Path | None = None, backup_root: Path | None = None) -> dict:
    """Bound submissions to running workers; never queue the remaining matrix."""
    if backup_root and (not fingerprint or concurrency != 1):
        raise ValueError("backup requires bound contract and concurrency=1")
    storage = output_root or root / "trials" / "full75"
    stop = Event()
    pending = iter(rows)
    launched: list[str] = []
    verified: list[str] = []
    failures: list[str] = []
    limits: dict[str, str] = {}
    checkpoint = storage / domain / "run_status.json"
    sentinel = storage / "API_LIMIT_STOP.json"

    def snapshot() -> dict:
        return {
            "domain": domain,
            "planned": len(rows),
            "launched": sorted(launched),
            "verified": sorted(verified),
            "incomplete": sorted(failures),
            "unlaunched": [name for name, _, _ in rows if name not in launched],
            "api_limit_failures": limits.copy(),
        }

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        running = {}

        def fill_slots() -> None:
            while len(running) < concurrency and not stop.is_set():
                row = next(pending, None)
                if row is None:
                    break
                launched.append(row[0])
                running[pool.submit(execute, row, root, stop, fingerprint)] = row

        fill_slots()
        write_checkpoint(checkpoint, snapshot())
        while running:
            done, _ = wait(running, return_when=FIRST_COMPLETED)
            # Consume every completed result before deciding to launch more.
            for future in done:
                row = running.pop(future)
                name = row[0]
                try:
                    _, complete, limit = future.result()
                except Exception as exc:
                    print(f"LAUNCH_ERROR {name}: {type(exc).__name__}", flush=True)
                    complete = False
                    limit = api_limit_failure(row[2]) if row[2].exists() else None
                if stop.is_set() and not row[2].exists():
                    # Submitted just before another worker tripped the guard,
                    # but the worker refused to start: report as unlaunched.
                    launched.remove(name)
                    continue
                if limit:
                    stop.set()
                    limits[name] = limit
                    # Persist across domain invocations, while other workers drain.
                    write_checkpoint(sentinel, snapshot())
                    print(f"API_LIMIT_STOP {name}: {limit}", file=sys.stderr, flush=True)
                if complete and backup_root:
                    try:
                        backup_offhost(row[2], backup_root, storage / domain / "run_identity.json", fingerprint, name)
                    except (ValueError, OSError):
                        complete = False
                        stop.set()
                        print(f"BACKUP_STOP {name}: no next task admitted", file=sys.stderr, flush=True)
                if not complete:
                    stop.set()
                (verified if complete else failures).append(name)
            write_checkpoint(checkpoint, snapshot())
            fill_slots()
    state = snapshot()
    write_checkpoint(checkpoint, state)
    if limits:
        write_checkpoint(sentinel, state)
    return state


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--domain", choices=DOMAINS, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--concurrency", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--run-contract", type=Path)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--output-root", type=Path, required=True)
    ap.add_argument("--backup-root", type=Path)
    ap.add_argument("--budget-proxy", help="URL of chi_budget_proxy enforcing the hard USD cap (required to execute)")
    ap.add_argument("--budget-proxy-container-url", help="same proxy as reached from containers (default: --budget-proxy)")
    ap.add_argument("--rclone-remote", help="named rclone remote:path for verified off-host copies")
    args = ap.parse_args()
    if not 1 <= args.concurrency <= 3:
        ap.error("concurrency must be between 1 and 3")
    root = args.root.resolve()
    storage = args.output_root.resolve()
    rows = plan(root, args.domain, args.model, storage)
    if args.dry_run:
        for name, cmd, _ in rows:
            print(f"PLANNED {args.domain} {name}: {cmd}")
        print(f"PLAN_OK {args.domain} 25 unique single-task launches")
        return 0
    # No spending authorization is inferred from historical manifests or flags.
    if not FREEZE_FILE.is_file() or json.loads(FREEZE_FILE.read_text()).get("frozen") is not False:
        ap.error("PAID_RUN_FREEZE active or unverified; no tasks launched")
    if not args.run_contract or not args.backup_root or args.concurrency != 1:
        ap.error("execution requires contract, durable backup root, concurrency=1")
    # Hard USD cap (agent + judge + simulators, including in-flight calls) is enforced
    # by the budget proxy; refuse to execute without a live proxy capped at <= USD 45.
    if not args.budget_proxy:
        ap.error("execution requires --budget-proxy (hard USD spend cap)")
    try:
        budget = require_budget_proxy(args.budget_proxy)
    except BudgetDenied as exc:
        ap.error(f"budget cap not enforced: {exc}")
    problems = routing_problems(
        os.environ,
        args.budget_proxy_container_url or args.budget_proxy,
        os.environ.get("HG_CHI_ENV_FILE", "/opt/chi-bench/.env"),
    )
    if problems:
        ap.error("; ".join(problems))
    print(f"BUDGET_OK cap={budget['cap_usd']} spent={budget['spent_usd']}", flush=True)
    # Never mistake a second local disk (such as F:) for off-host durability.
    global RCLONE_REMOTE
    if args.rclone_remote:
        # Local staging + verified rclone push replaces the remote-mount requirement.
        try:
            args.backup_root.mkdir(parents=True, exist_ok=True)
            require_rclone_remote(args.rclone_remote)
        except (BackupError, OSError) as exc:
            ap.error(f"off-host backup required: {exc}")
        RCLONE_REMOTE = args.rclone_remote
    else:
        try:
            require_offhost_backup_root(args.backup_root)
        except BackupTargetDenied as exc:
            ap.error(f"off-host backup required: {exc}")
    sentinel = storage / "API_LIMIT_STOP.json"
    if sentinel.exists():
        print(f"API_LIMIT_STOP already recorded: {sentinel}; no tasks launched", file=sys.stderr)
        return 1
    fingerprint = None
    restored = []
    interrupted = []
    rejudged = []
    if args.resume and not args.run_contract:
        ap.error("--resume requires the original --run-contract")
    if args.run_contract:
        contract = json.loads(args.run_contract.read_text())
        # This is a necessary fail-closed admission check, not a guarantee
        # that external providers enforce in-flight cumulative spending caps.
        try:
            require_paid_run_authorized(contract)
        except PaidRunDenied as exc:
            ap.error(f"paid run not authorized: {exc}")
        # Prevent a broad approval from silently covering different official tasks.
        planned_ids = {name for name, _, _ in rows}
        if set(contract.get("task_ids", [])) != planned_ids or len(contract["task_ids"]) != len(rows):
            ap.error("contract task_ids must exactly match the 25 planned domain tasks")
        if contract.get("models", {}).get(args.domain) != args.model:
            ap.error("model differs from run contract")
        effort = contract.get("reasoning_effort", {}).get(args.domain)
        if effort != "high":
            ap.error("historical recovery requires explicit high effort per domain")
        os.environ["HG_CHI_REASONING_EFFORT"] = effort
        fingerprint = bind_contract(storage / args.domain / "run_identity.json", contract, rows, args.resume)
        if args.resume:
            rows, restored, interrupted, rejudged = resume_rows(rows, fingerprint)
    # Re-acknowledge every recovered completion before admitting paid work.
    for name in restored:
        backup_offhost(storage / args.domain / name, args.backup_root,
                    storage / args.domain / "run_identity.json", fingerprint, name, reack=True)
    existing = [str(out) for _, _, out in rows if out.exists()]
    if existing:
        raise ValueError("Refusing to overwrite existing trials: " + ", ".join(existing))
    state = run_rows(rows, root, args.domain, args.concurrency, fingerprint, storage, args.backup_root)
    state["restored_without_paid_replay"] = restored
    state["verified"] = sorted(restored + state["verified"])
    state["interrupted_do_not_replay"] = sorted(interrupted)
    state["rejudged_do_not_replay"] = sorted(rejudged)
    state["verified"] = sorted(state["verified"] + rejudged)
    write_checkpoint(storage / args.domain / "run_status.json", state)
    total = len(state["verified"]) + len(interrupted)
    print(f"DOMAIN_COMPLETE {args.domain} verified={len(state['verified'])}/{total}"
          + (f" interrupted={len(interrupted)}" if interrupted else "")
          + (f" rejudged={len(rejudged)}" if rejudged else ""), flush=True)
    if state["incomplete"] or state["unlaunched"]:
        print("INCOMPLETE_TASKS " + ", ".join(state["incomplete"]), file=sys.stderr)
        print("UNLAUNCHED_TASKS " + ", ".join(state["unlaunched"]), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

