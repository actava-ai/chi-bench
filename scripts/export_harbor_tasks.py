"""Export self-contained Harbor-hub task directories for chi-Bench.

Each emitted task is runnable from the Harbor hub with no repo checkout and no
hosted image: the per-task ``environment/Dockerfile`` (route X, fetch-at-build)
clones chi_bench from GitHub and downloads fixtures+handbook from Hugging Face
at build time, then selects the trial via ``CHI_BENCH_TASK_ID`` (set in
``task.toml [environment.env]``). See ``docker/Dockerfile.harbor``.

The task archive carries NO solution/, NO fixtures/, NO ground truth — the
scoring contract is baked into the image at build time and the in-container
entrypoint deliberately withholds it from the agent.

Usage:
    uv run python scripts/export_harbor_tasks.py \
        --data-root data \
        --out logs/harbor_export \
        --org actava-ai
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.harbor"

SOURCE_REPO = "https://github.com/actava-ai/chi-bench"
HF_DATASET = "https://huggingface.co/datasets/actava/chi-bench"
LEADERBOARD = "https://actava.ai/benchmarks/leaderboards"

# (family dir, task glob, domain label). marathon tasks live directly under the
# family dir (one self-contained session per domain), not under tasks/.
FAMILIES = {
    "prior_auth_um": ("prior_auth_um/tasks/*", "prior_auth_um"),
    "prior_auth_provider": ("prior_auth_provider/tasks/*", "prior_auth_provider"),
    "care_management": ("care_management/tasks/*", "care_management"),
    "prior_auth_e2e": ("prior_auth_e2e/tasks/*", "prior_auth_e2e"),
}
MARATHON = {
    "marathon/prior_auth_um": "marathon_prior_auth_um",
    "marathon/prior_auth_provider": "marathon_prior_auth_provider",
    "marathon/care_management": "marathon_care_management",
}

# Standard single-task verifier. CHI_BENCH_TASK_ID is in the persistent env
# (task.toml [environment.env]); the scoring contract is baked at the
# deterministic per-task path (the entrypoint deliberately does NOT expose
# /fixtures to the agent, so we pass the path explicitly).
TEST_SH = """\
#!/usr/bin/env bash
# chi-Bench verifier (same-container phase). The entrypoint has already booted
# `cb serve` + the three MCP servers; this scores the agent's final world state
# and writes the binary reward Harbor reads at /logs/verifier/reward.json.
set -euo pipefail
. /workspace/.venv/bin/activate
mkdir -p /logs/verifier
python -m chi_bench.verifier.task_runtime verify \\
    --expectations-path "/opt/chi-bench/tasks/${CHI_BENCH_TASK_ID}/fixtures/expectations.json"
"""

# Marathon (long-horizon session) verifier: scores every sub-task in the
# session and writes a session-level reward.json.
SESSION_TEST_SH = """\
#!/usr/bin/env bash
set -euo pipefail
. /workspace/.venv/bin/activate
mkdir -p /logs/verifier
python -m chi_bench.verifier.session_verifier \\
    --fixtures-dir "/opt/chi-bench/tasks/${CHI_BENCH_TASK_ID}/fixtures" \\
    --output-dir /logs/verifier
"""

README = """\
# chi-Bench task — runs via fetch-at-build (no hosted image)

This Harbor-hub task is self-contained: `environment/Dockerfile` clones
chi_bench from {repo} and downloads fixtures + the managed-care handbook from
Hugging Face at build time. No registry image, no repo checkout required.

The managed-care handbook is gated; the wrapper entrypoint downloads it at
container start, so you must pass an approved HF token at run time:

    harbor run -d {org}/chi-bench@<tag> -a <agent> -m <model> -e HF_TOKEN=<token>

This builds the image, downloads the handbook, boots the chi-Bench MCP servers,
runs your agent, then scores with the baked-in verifier.

- Source: {repo}
- Dataset: {dataset}
- Leaderboard: {leaderboard}
"""


def load_meta(data_root: Path) -> dict[str, dict]:
    """Map task_id -> tasks.jsonl record, when present."""
    f = data_root / "tasks.jsonl"
    if not f.exists():
        return {}
    out = {}
    for line in f.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["task_id"]] = r
    return out


def render_task_toml(name: str, cb_task_id: str, domain: str, meta: dict) -> str:
    title = meta.get("title", cb_task_id)
    excerpt = (meta.get("instruction_excerpt") or "").replace("\n", " ").strip()[:180]
    desc = f"chi-Bench {domain} task: {title}. {excerpt}".strip()
    desc = desc.replace('"', "'")
    kws = ["healthcare", "chi-bench", domain]
    if meta.get("task_kind"):
        kws.append(meta["task_kind"])
    kw_toml = ", ".join(f'"{k}"' for k in kws)
    agent_timeout = float(meta.get("agent_timeout_sec", 900.0))
    return f"""\
schema_version = "1.2"
artifacts = []

[task]
name = "{name}"
description = "{desc}"
authors = []
keywords = [{kw_toml}]

[metadata]
benchmark = "chi-bench"
domain = "{domain}"
source_repo = "{SOURCE_REPO}"
dataset = "{HF_DATASET}"
leaderboard = "{LEADERBOARD}"

[verifier]
timeout_sec = 1200.0

[verifier.env]

[agent]
timeout_sec = {agent_timeout}

[environment]
build_timeout_sec = 2400.0
os = "linux"
cpus = 2
memory_mb = 4096
storage_mb = 10240
gpus = 0
allow_internet = true

[environment.env]
CHI_BENCH_TASK_ID = "{cb_task_id}"

[[environment.mcp_servers]]
name = "chi-bench-provider"
transport = "streamable-http"
url = "http://localhost:8020/mcp"

[[environment.mcp_servers]]
name = "chi-bench-payer"
transport = "streamable-http"
url = "http://localhost:8100/mcp"

[[environment.mcp_servers]]
name = "chi-bench-cm"
transport = "streamable-http"
url = "http://localhost:8200/mcp"
"""


def emit_task(
    src: Path,
    out_dir: Path,
    name: str,
    task_id: str,
    cb_task_id: str,
    domain: str,
    meta: dict,
    *,
    session: bool = False,
) -> None:
    t = out_dir / task_id
    (t / "environment").mkdir(parents=True, exist_ok=True)
    (t / "tests").mkdir(parents=True, exist_ok=True)
    (t / "task.toml").write_text(render_task_toml(name, cb_task_id, domain, meta))
    instr = src / "instruction.md"
    (t / "instruction.md").write_text(instr.read_text() if instr.exists() else f"# {task_id}\n")
    shutil.copyfile(DOCKERFILE, t / "environment" / "Dockerfile")
    ts = t / "tests" / "test.sh"
    ts.write_text(SESSION_TEST_SH if session else TEST_SH)
    ts.chmod(0o755)
    (t / "README.md").write_text(
        README.format(repo=SOURCE_REPO, org=name.split("/")[0], dataset=HF_DATASET, leaderboard=LEADERBOARD)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, default=REPO_ROOT / "data")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--org", default="actava-ai")
    args = ap.parse_args()

    if not DOCKERFILE.exists():
        raise SystemExit(f"missing {DOCKERFILE}")
    meta = load_meta(args.data_root)
    out_tasks = args.out / "tasks"
    out_tasks.mkdir(parents=True, exist_ok=True)

    n = 0
    for _, (glob, domain) in FAMILIES.items():
        for src in sorted(args.data_root.glob(glob)):
            if not (src / "task.toml").exists() and not (src / "instruction.md").exists():
                continue
            tid = src.name
            emit_task(src, out_tasks, f"{args.org}/{tid}", tid, tid, domain, meta.get(tid, {}))
            n += 1
    # marathon: hub name uses underscores; CHI_BENCH_TASK_ID is the in-image
    # slash path (marathon/<domain>); scored by the session verifier.
    for rel, tid in MARATHON.items():
        src = args.data_root / rel
        if src.exists():
            emit_task(
                src, out_tasks, f"{args.org}/{tid}", tid, rel, "marathon",
                meta.get(tid, {}), session=True,
            )
            n += 1

    print(f"Exported {n} Harbor tasks to {out_tasks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
