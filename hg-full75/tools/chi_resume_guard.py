"""Fail-closed task receipts. Never replay ambiguous paid work automatically."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

# A task that is known to have been interrupted (no valid trial) can be retired
# explicitly instead of blocking the whole domain forever. The marker must name the
# task, the run fingerprint, a known reason and the approval that authorised it;
# anything less stays "ambiguous" and still blocks resumption.
INTERRUPTED_MARKER = "hg-task-interrupted.json"
INTERRUPTED_STATE = "interrupted_do_not_replay"
INTERRUPTED_REASONS = {
    "budget_denied_402",        # proxy denied the call; no further provider work happened
    "provider_error_no_result",  # agent/judge failed; no valid trial produced
    "host_stop_no_receipt",      # stopped mid-flight without a receipt
    # The judge ran and returned a genuine invalid verdict. Requires the exact
    # validity.json to be present and hashed in the marker. Judge infrastructure
    # failures (no verdict at all) are deliberately NOT accepted here.
    "judge_invalid_no_replay",
}


def interrupted_record(out, fingerprint, task_id):
    path = Path(out) / INTERRUPTED_MARKER
    if not path.is_file():
        return None
    try:
        d = json.loads(path.read_text())
    except (ValueError, OSError):
        return None
    if (d.get("state") != INTERRUPTED_STATE or d.get("task_id") != task_id
            or d.get("fingerprint") != fingerprint or d.get("reason") not in INTERRUPTED_REASONS
            or not d.get("approved_by") or not d.get("evidence")):
        return None
    if d["reason"] == "judge_invalid_no_replay" and not _genuine_invalid_verdict(out, d):
        return None
    return d


# A valid rejudge of an interrupted-judge trial. The agent trial is never replayed;
# its verdict comes from `cb experiment rejudge` on an isolated copy, stored beside
# (never inside) the original trial. The marker binds the verdict to the original
# trial's artifact hashes, so any later alteration of either side blocks resumption.
REJUDGED_MARKER = "hg-task-rejudged.json"
REJUDGED_STATE = "completed_rejudged_do_not_replay"
REJUDGED_DIR = "rejudge"


def _trial_dir(out):
    out = Path(out)
    trials = [p for p in out.iterdir() if p.is_dir() and (p / "verifier").is_dir()] if out.is_dir() else []
    return trials[0] if len(trials) == 1 else None


def rejudged_record(out, fingerprint, task_id):
    out = Path(out)
    path = out / REJUDGED_MARKER
    if not path.is_file():
        return None
    try:
        d = json.loads(path.read_text())
        trial = _trial_dir(out)
        if (trial is None or d.get("state") != REJUDGED_STATE or d.get("task_id") != task_id
                or d.get("fingerprint") != fingerprint or not d.get("approved_by")
                or d.get("trial_name") != trial.name):
            return None
        if digest(artifact_hashes(trial)) != d.get("trial_manifest_sha256"):
            return None  # original trial altered since the rejudge
        rj = out / REJUDGED_DIR
        for name, expected in d.get("files_sha256", {}).items():
            if not (rj / name).is_file() or hashlib.sha256((rj / name).read_bytes()).hexdigest() != expected:
                return None
        validity = json.loads((rj / "validity.json").read_text())
        scorecard = json.loads((rj / "scorecard.json").read_text())
    except (ValueError, OSError, TypeError, KeyError):
        return None
    if validity.get("scoring_status") != "valid":
        return None
    checks = scorecard.get("checks", {})
    judge = {k: v for k, v in checks.items() if k.startswith("judge.")}
    if not judge or any(v not in (True, False) for v in judge.values()):
        return None  # every judge rubric must have a real verdict
    if scorecard.get("binary_reward") not in (0.0, 1.0):
        return None
    return d


def _genuine_invalid_verdict(out, marker):
    out = Path(out)
    validity = out / "verifier" / "validity.json"
    reward = out / "verifier" / "reward.json"
    if not (validity.is_file() and reward.is_file()):
        return False
    try:
        v = json.loads(validity.read_text())
    except (ValueError, OSError):
        return False
    if v.get("scoring_status") != "invalid" or not v.get("invalid_checks"):
        return False
    if "judge_error" in v or "judge_session_failed" in v:
        return False
    # A real verdict evaluated every invalid check. Judge outages leave them "unavailable".
    try:
        checks = json.loads((out / "verifier" / "scorecard.json").read_text()).get("checks", {})
    except (ValueError, OSError):
        return False
    if any(checks.get(name) is not False for name in v["invalid_checks"]):
        return False
    stdout = out / "verifier" / "test-stdout.txt"
    if stdout.is_file() and "Judge session failed" in stdout.read_text(errors="replace"):
        return False
    return marker.get("validity_sha256") == hashlib.sha256(validity.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, sort_keys=True, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def bind_contract(path, contract, rows, resume=False):
    required = ("run_id", "runtime_sha", "harness_sha", "dataset_sha256",
                "image_digest", "models", "reasoning_effort", "judge_model",
                "judge_num_votes", "budget_usd")
    if any(not contract.get(k) for k in required):
        raise ValueError("run contract incomplete")
    value = {"contract": contract, "tasks": [[n, cmd] for n, cmd, _ in rows]}
    fingerprint = digest(value)
    path = Path(path)
    if path.exists():
        saved = json.loads(path.read_text())
        if saved != {"fingerprint": fingerprint, "identity": value}:
            raise ValueError("run contract changed; refusing mixed or duplicate evaluation")
        if not resume:
            raise ValueError("existing run requires explicit --resume")
    else:
        if resume:
            raise ValueError("resume identity missing; cannot infer previous run")
        atomic_json(path, {"fingerprint": fingerprint, "identity": value})
    return fingerprint


def artifact_hashes(out):
    out = Path(out)
    if any(p.is_symlink() for p in out.rglob("*")):
        raise ValueError("symlink artifacts are not safe to seal or back up")
    # Include trajectories and exported state, not just score summaries.
    return {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob("*")) if p.is_file()
            and p.name not in {"hg-task-receipt.json", "hg-task-receipt.tmp"}}


def seal_task(out, fingerprint, task_id):
    out = Path(out)
    # Receipt is only a launcher completion record, never a replacement judge.
    results = list(out.rglob("result.json"))
    rewards = list(out.rglob("verifier/reward.json"))
    validity = list(out.rglob("verifier/validity.json"))
    if len(results) != 1 or len(rewards) != 1 or len(validity) != 1:
        raise ValueError("incomplete official trial")
    if json.loads(validity[0].read_text()).get("scoring_status") != "valid":
        raise ValueError("invalid judge evidence; reconcile without replaying agent")
    for p in results + rewards:
        json.loads(p.read_text())
    atomic_json(out / "hg-task-receipt.json", {
        "fingerprint": fingerprint, "task_id": task_id,
        "state": "completed_do_not_replay", "files": artifact_hashes(out)})


def classify_task(out, fingerprint, task_id):
    out = Path(out)
    if not out.exists():
        return "unstarted"
    receipt_path = out / "hg-task-receipt.json"
    if not receipt_path.is_file():
        if interrupted_record(out, fingerprint, task_id):
            return INTERRUPTED_STATE
        if rejudged_record(out, fingerprint, task_id):
            return REJUDGED_STATE
        return "ambiguous_do_not_replay"
    try:
        receipt = json.loads(receipt_path.read_text())
        if (receipt.get("fingerprint") != fingerprint or receipt.get("task_id") != task_id
                or receipt.get("state") != "completed_do_not_replay"
                or not receipt.get("files") or receipt["files"] != artifact_hashes(out)):
            return "ambiguous_do_not_replay"
    except (ValueError, OSError, TypeError):
        return "ambiguous_do_not_replay"
    return "completed_do_not_replay"


def resume_rows(rows, fingerprint):
    pending, completed, ambiguous, interrupted, rejudged = [], [], [], [], []
    for row in rows:
        state = classify_task(row[2], fingerprint, row[0])
        if state == "unstarted":
            pending.append(row)
        elif state == "completed_do_not_replay":
            completed.append(row[0])
        elif state == INTERRUPTED_STATE:
            interrupted.append(row[0])
        elif state == REJUDGED_STATE:
            rejudged.append(row[0])
        else:
            ambiguous.append(row[0])
    if ambiguous:
        raise ValueError("Reconcile interrupted/modified trials before paid replay: " + ", ".join(ambiguous))
    return pending, completed, interrupted, rejudged


def backup_task(out, backup_root, identity_path, fingerprint, task_id):
    """Copy a sealed task and identity; read back every byte before acknowledging.

    backup_root must be an independently provisioned durable filesystem. This
    routine proves integrity, not the storage provider's durability or offsite SLA.
    Existing backups are immutable; corrupted backups block further admission.
    """
    out, backup_root, identity_path = map(Path, (out, backup_root, identity_path))
    if classify_task(out, fingerprint, task_id) != "completed_do_not_replay":
        raise ValueError("cannot back up an unsealed task")
    identity = json.loads(identity_path.read_text())
    if identity.get("fingerprint") != fingerprint:
        raise ValueError("backup identity mismatch")
    destination = backup_root / fingerprint / task_id
    if out.resolve() == destination.resolve() or out.resolve() in destination.resolve().parents:
        raise ValueError("backup must be outside task output")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        temporary = Path(tempfile.mkdtemp(prefix=".pending-", dir=destination.parent))
        try:
            shutil.copytree(out, temporary / "task")
            atomic_json(temporary / "run_identity.json", identity)
            # Flush copied files before the commit rename.
            for file in temporary.rglob("*"):
                if file.is_file():
                    with file.open("rb") as stream:
                        os.fsync(stream.fileno())
            if classify_task(temporary / "task", fingerprint, task_id) != "completed_do_not_replay":
                raise ValueError("backup readback failed")
            temporary.rename(destination)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    if (json.loads((destination / "run_identity.json").read_text()) != identity
            or classify_task(destination / "task", fingerprint, task_id) != "completed_do_not_replay"
            or (destination / "task/hg-task-receipt.json").read_bytes() != (out / "hg-task-receipt.json").read_bytes()):
        raise ValueError("immutable backup corrupt or mismatched")
    ack = {"fingerprint": fingerprint, "task_id": task_id,
           "receipt_sha256": hashlib.sha256((out / "hg-task-receipt.json").read_bytes()).hexdigest(),
           "state": "backup_readback_verified"}
    atomic_json(destination / "backup_ack.json", ack)
    if json.loads((destination / "backup_ack.json").read_text()) != ack:
        raise ValueError("backup acknowledgement readback failed")
    return destination


def restore_task(source, out, identity_path, fingerprint, task_id):
    """Restore without overwrite. Never call an agent or judge."""
    source, out, identity_path = map(Path, (source, out, identity_path))
    ack = json.loads((source / "backup_ack.json").read_text())
    receipt = source / "task/hg-task-receipt.json"
    if (ack.get("fingerprint") != fingerprint or ack.get("task_id") != task_id
            or ack.get("state") != "backup_readback_verified"
            or ack.get("receipt_sha256") != hashlib.sha256(receipt.read_bytes()).hexdigest()
            or classify_task(source / "task", fingerprint, task_id) != "completed_do_not_replay"):
        raise ValueError("unverified backup")
    identity = json.loads((source / "run_identity.json").read_text())
    if identity.get("fingerprint") != fingerprint:
        raise ValueError("backup identity mismatch")
    if out.exists():
        raise ValueError("restore destination exists; reconcile without overwrite")
    if identity_path.exists() and json.loads(identity_path.read_text()) != identity:
        raise ValueError("restore identity mismatch")
    # Reserve destination first; interruption remains ambiguous and cannot replay.
    out.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source / "task", out, dirs_exist_ok=True)
    if classify_task(out, fingerprint, task_id) != "completed_do_not_replay":
        raise ValueError("restore readback failed")
    atomic_json(identity_path, identity)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Restore verified task backup; no inference")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--identity", required=True, type=Path)
    parser.add_argument("--fingerprint", required=True)
    parser.add_argument("--task", required=True)
    args = parser.parse_args()
    restore_task(args.source, args.out, args.identity, args.fingerprint, args.task)
    print("RESTORED_DO_NOT_REPLAY")
