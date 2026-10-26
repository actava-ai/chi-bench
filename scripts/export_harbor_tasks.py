"""Export Harbor 0.20 tasks with isolated agent, simulator and verifier images.

The task archive contains public instructions, image build definitions and the
separate verifier launcher. Fixtures and scoring code are fetched into trusted
image stages. The main agent image receives only its runner and public mounts.

Usage: uv run python scripts/export_harbor_tasks.py --data-root data --out OUTPUT
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "docker" / "Dockerfile.harbor"
SOURCE_REPO = "https://github.com/actava-ai/chi-bench"
HF_DATASET = "https://huggingface.co/datasets/actava/chi-bench"
LEADERBOARD = "https://actava.ai/benchmarks/leaderboards"


@dataclass(frozen=True)
class BuildPins:
    """Explicit immutable identities for all independently fetched inputs."""

    source: str
    dataset: str
    handbook: str

    def __post_init__(self) -> None:
        for field in ("source", "dataset", "handbook"):
            if re.fullmatch(r"[0-9a-f]{40}", getattr(self, field)) is None:
                raise ValueError(
                    f"{field} revision must be a full lowercase 40-character commit SHA"
                )

    def build_args(self) -> dict[str, str]:
        return {
            "CHI_BENCH_REF": self.source,
            "CHI_BENCH_DATASET_REV": self.dataset,
            "CHI_BENCH_HANDBOOK_REV": self.handbook,
        }


def validate_source_checkout(root: Path, revision: str) -> None:
    """Reject dirty or locally unpublished templates rather than claiming release acceptance.

    A canonical origin remote-tracking ref must contain the exact clean HEAD.
    This is an offline guard, not a remote availability certificate: the image
    build still fetches that exact SHA and verifies the resolved commit.
    """

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
        )
        if result.returncode:
            raise ValueError("Cannot validate the source checkout against its canonical remote")
        return result.stdout.strip()

    if git("rev-parse", "HEAD") != revision:
        raise ValueError("Source revision must equal the export checkout HEAD")
    if git("status", "--porcelain", "--untracked-files=normal", "--", ".", ":!data", ":!logs"):
        raise ValueError(
            "Hub export requires a clean source checkout; uncommitted source is not accepted"
        )
    remote = git("remote", "get-url", "origin").removesuffix(".git")
    if remote not in {SOURCE_REPO, "git@github.com:actava-ai/chi-bench"}:
        raise ValueError("Hub export requires the canonical source origin remote")
    if not git(
        "for-each-ref", f"--contains={revision}", "--format=%(refname)", "refs/remotes/origin"
    ):
        raise ValueError(
            "Source revision is not in an origin remote-tracking ref; push and fetch it first"
        )


def render_dockerfile(pins: BuildPins) -> str:
    """Embed the explicit pins for Harbor's verifier build, which has no args API."""
    text = DOCKERFILE.read_text()
    for key, value in pins.build_args().items():
        text, count = re.subn(rf"(?m)^ARG {key}(?:=.*)?$", f"ARG {key}={value}", text)
        if count != 1:
            raise ValueError(f"Hub Dockerfile must declare exactly one {key} build argument")
    return text


FAMILIES = {
    "prior_auth_um": ("prior_auth_um/tasks/*", "prior_auth_um"),
    "prior_auth_provider": ("prior_auth_provider/tasks/*", "prior_auth_provider"),
    "care_management": ("care_management/tasks/*", "care_management"),
}
# E2E requires the source runner's two-agent orchestrator and is not exported.
MARATHON = {
    "marathon/prior_auth_um": "marathon_prior_auth_um",
    "marathon/prior_auth_provider": "marathon_prior_auth_provider",
    "marathon/care_management": "marathon_care_management",
}
SERVER_ENV_KEYS = (
    "HF_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "XAI_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CHI_BENCH_JUDGE_MODEL",
    "CHI_BENCH_JUDGE_TIMEOUT_S",
    "CHI_BENCH_JUDGE_NUM_VOTES",
    "CHI_BENCH_PATIENT_SIM_MODEL",
    "CHI_BENCH_P2P_SIMULATOR_MODEL",
    "CHI_BENCH_TOOL_MODE",
    "CHI_BENCH_MCP_TOOL_SEP",
    "CHI_BENCH_PAYER_MCP_PROFILE",
    "CHI_BENCH_SKILLS_ABLATE",
)

COLLECT_SCRIPT = """from pathlib import Path
from chi_bench.experiment.frozen_state import collect_frozen_state
collect_frozen_state(
    token_path=Path("/run/chi-bench/control-token"),
    output=Path("/logs/artifacts/final-state.json"),
)
"""


_VERIFIER_PRELUDE = """#!/usr/bin/env bash
set -euo pipefail
STATE=/logs/artifacts/final-state.json
if [ ! -s "$STATE" ]; then
    echo "Missing required frozen simulator state" >&2
    exit 1
fi
. /workspace/.venv/bin/activate
python -c 'import json,sys; state=json.load(open(sys.argv[1])); proof=state.get("_evaluation_boundary",{}); assert proof.get("version")==1 and proof.get("main_stopped") is True and proof.get("main_container_id")' "$STATE"
/usr/local/bin/ensure-handbook
mkdir -p /logs/verifier
"""
TEST_SH = (
    _VERIFIER_PRELUDE
    + """python -m chi_bench.verifier.task_runtime verify \\
    --expectations-path "/opt/chi-bench/tasks/${CHI_BENCH_TASK_ID}/fixtures/expectations.json" \\
    --exported-state-input "$STATE"
"""
)
SESSION_TEST_SH = (
    _VERIFIER_PRELUDE
    + """python -m chi_bench.verifier.session_verifier \\
    --fixtures-dir "/opt/chi-bench/tasks/${CHI_BENCH_TASK_ID}/fixtures" \\
    --output-dir /logs/verifier \\
    --exported-state-input "$STATE"
"""
)
README = """# chi-Bench Harbor task

This task requires Harbor 0.20.0. It builds a clean agent image and a trusted
simulator from {repo}; benchmark fixtures come from the pinned dataset revision.
The managed-care handbook is gated. Set an approved HF_TOKEN in the runner's
host environment before starting the task. Set simulator and judge credentials
there too; agent credentials follow the selected Harbor harness's own setup.

    HF_TOKEN=<token> harbor run -d {org}/chi-bench@<tag> -i {org}/<task> -a <agent> -m <model> -y

The agent receives public skills/tool references, allowed raw artifact files,
and the workflow workspace. Harbor stops main before collecting trusted
simulator evidence. A separate verifier image scores the frozen state and
workspace; the agent never receives the verifier tests or control token.
The source task's agent and verifier timeout values are retained.

- Source: {repo}
- Dataset: {dataset}
- Leaderboard: {leaderboard}
"""


def _role(domain: str, cb_task_id: str) -> str:
    family = cb_task_id.rsplit("/", 1)[-1] if domain == "marathon" else domain
    return {"prior_auth_um": "payer", "prior_auth_provider": "provider", "care_management": "cm"}[
        family
    ]


def render_compose(domain: str, cb_task_id: str, *, pins: BuildPins) -> str:
    simulator_env = {key: "${" + key + ":-}" for key in SERVER_ENV_KEYS}
    simulator_env.update(
        {
            "CHI_BENCH_TASK_ID": "${CHI_BENCH_TASK_ID}",
            "CHI_BENCH_AGENT_ROLE": _role(domain, cb_task_id),
            "CHI_BENCH_PUBLISH_AGENT_ASSETS": "1",
            "CHI_BENCH_COMPOSE_PROJECT": "${COMPOSE_PROJECT_NAME:?Missing trusted Compose project identity}",
        }
    )
    main_volumes = [
        "workspaces:/logs/artifacts/workspaces",
        {
            "type": "volume",
            "source": "agent-assets",
            "target": "/agent-assets",
            "read_only": True,
            # Main can be created first; only simulator may populate this volume.
            "volume": {"nocopy": True},
        },
    ]
    if not cb_task_id.endswith("_new_referral_provider"):
        main_volumes.append("raw-artifacts:/agent-raw/artifacts:ro")
    compose = {
        "services": {
            "main": {
                "build": {
                    "context": ".",
                    "dockerfile": "Dockerfile",
                    "target": "agent",
                    "args": pins.build_args(),
                },
                "network_mode": "service:simulator",
                "depends_on": {"simulator": {"condition": "service_healthy"}},
                "volumes": main_volumes,
                "cap_drop": ["NET_RAW"],
                "security_opt": ["no-new-privileges:true"],
                "healthcheck": {
                    "test": ["CMD", "test", "-f", "/agent-assets/.ready"],
                    "interval": "5s",
                    "timeout": "5s",
                    "retries": 48,
                },
                "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
            },
            "simulator": {
                "build": {
                    "context": ".",
                    "dockerfile": "Dockerfile",
                    "target": "simulator",
                    "args": pins.build_args(),
                },
                "command": ["sleep", "infinity"],
                "environment": simulator_env,
                "volumes": [
                    "workspaces:/logs/artifacts/workspaces",
                    "agent-assets:/agent-assets",
                    "raw-artifacts:/srv/chi-bench/raw/artifacts",
                    {
                        "type": "bind",
                        "source": "${CHI_BENCH_DOCKER_SOCKET:-/var/run/docker.sock}",
                        "target": "/var/run/docker.sock",
                        "read_only": True,
                    },
                ],
                "healthcheck": {
                    "test": [
                        "CMD",
                        "/workspace/.venv/bin/python",
                        "-c",
                        "from pathlib import Path; import urllib.request; urllib.request.urlopen('http://localhost:8023/health',timeout=3); assert Path('/agent-assets/.ready').is_file()",
                    ],
                    "interval": "5s",
                    "timeout": "5s",
                    "retries": 48,
                    "start_period": "240s",
                },
                "logging": {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}},
            },
        },
        "volumes": {"workspaces": {}, "agent-assets": {}, "raw-artifacts": {}},
    }
    return yaml.safe_dump(compose, sort_keys=False)


def load_meta(data_root: Path) -> dict[str, dict]:
    """Index viewer metadata by task ID and dataset-relative path."""
    source = data_root / "tasks.jsonl"
    if not source.exists():
        return {}
    rows = {}
    for line in source.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["task_id"]] = row
            if row.get("path"):
                rows[row["path"]] = row
    return rows


def _toml_literal(value: object) -> str:
    # TOML accepts Unicode scalars directly, but rejects JSON surrogate escapes.
    return json.dumps(value, ensure_ascii=False)


def render_task_toml(
    name: str,
    cb_task_id: str,
    domain: str,
    meta: dict,
    *,
    verifier_timeout: float,
    agent_timeout: float,
) -> str:
    title = meta.get("title", cb_task_id)
    excerpt = (meta.get("instruction_excerpt") or "").replace("\n", " ").strip()[:180]
    description = f"chi-Bench {domain} task: {title}. {excerpt}".strip()
    keywords = ["healthcare", "chi-bench", domain]
    if meta.get("task_kind"):
        keywords.append(meta["task_kind"])
    artifacts = [
        {
            "source": "/logs/artifacts",
            "destination": "agent-publish",
            "service": "main",
            "exclude": ["workspaces", "final-state.json"],
        },
        {
            "source": "/logs/artifacts/final-state.json",
            "destination": "trusted/final-state.json",
            "service": "simulator",
        },
        {
            "source": "/logs/artifacts/workspaces",
            "destination": "trusted/workspaces",
            "service": "simulator",
        },
        {
            "source": "/workspace/skills/managed-care-operations-handbook",
            "destination": "trusted/handbook",
            "service": "simulator",
        },
    ]
    lines = [
        'schema_version = "1.2"',
        "artifacts = [",
        *(
            "  { "
            + ", ".join(f"{key} = {_toml_literal(value)}" for key, value in entry.items())
            + " },"
            for entry in artifacts
        ),
        "]",
        "",
        "[task]",
        f"name = {_toml_literal(name)}",
        f"description = {_toml_literal(description)}",
        "authors = []",
        "keywords = " + _toml_literal(keywords),
        "",
        "[metadata]",
        'benchmark = "chi-bench"',
        f"domain = {_toml_literal(domain)}",
        f"source_repo = {_toml_literal(SOURCE_REPO)}",
        f"dataset = {_toml_literal(HF_DATASET)}",
        f"leaderboard = {_toml_literal(LEADERBOARD)}",
        "",
        "[verifier]",
        f"timeout_sec = {verifier_timeout}",
        'environment_mode = "separate"',
        "",
        "[[verifier.collect]]",
        'service = "simulator"',
        'user = "root"',
        "timeout_sec = 300.0",
        "command = " + _toml_literal("python -c " + shlex.quote(COLLECT_SCRIPT)),
        "",
        "[verifier.env]",
        "CHI_BENCH_TASK_ID = " + _toml_literal(cb_task_id),
        *(f'{key} = "${{{key}:-}}"' for key in SERVER_ENV_KEYS),
        "",
        "[verifier.environment]",
        "build_timeout_sec = 2400.0",
        'os = "linux"',
        "cpus = 2",
        "memory_mb = 4096",
        "storage_mb = 10240",
        "gpus = 0",
        'network_mode = "public"',
        "",
        "[agent]",
        f"timeout_sec = {agent_timeout}",
        "",
        "[environment]",
        "build_timeout_sec = 2400.0",
        'os = "linux"',
        "cpus = 2",
        "memory_mb = 4096",
        "storage_mb = 10240",
        "gpus = 0",
        'network_mode = "public"',
        "",
        "[environment.env]",
        "CHI_BENCH_TASK_ID = " + _toml_literal(cb_task_id),
        'CHI_BENCH_TOOL_MODE = "${CHI_BENCH_TOOL_MODE:-mcp}"',
        'CHI_BENCH_MCP_TOOL_SEP = "${CHI_BENCH_MCP_TOOL_SEP:-}"',
        "",
    ]
    role = _role(domain, cb_task_id)
    port = {"provider": 8020, "payer": 8100, "cm": 8200}[role]
    lines += [
        "[[environment.mcp_servers]]",
        f'name = "chi-bench-{role}"',
        'transport = "streamable-http"',
        f'url = "http://localhost:{port}/mcp"',
    ]
    return "\n".join(lines) + "\n"


def read_source_timeouts(src: Path) -> tuple[float, float]:
    source = src / "task.toml"
    document = tomllib.loads(source.read_text()) if source.exists() else {}
    return float(document.get("verifier", {}).get("timeout_sec", 1200)), float(
        document.get("agent", {}).get("timeout_sec", 900)
    )


def emit_task(
    src: Path,
    out_dir: Path,
    name: str,
    task_id: str,
    cb_task_id: str,
    domain: str,
    meta: dict,
    *,
    pins: BuildPins,
    session: bool = False,
) -> None:
    target = out_dir / task_id
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Export destination must be empty: {target}")
    (target / "environment").mkdir(parents=True, exist_ok=True)
    (target / "tests").mkdir(parents=True, exist_ok=True)
    verifier_timeout, agent_timeout = read_source_timeouts(src)
    (target / "task.toml").write_text(
        render_task_toml(
            name,
            cb_task_id,
            domain,
            meta,
            verifier_timeout=verifier_timeout,
            agent_timeout=agent_timeout,
        )
    )
    instruction = src / "instruction.md"
    (target / "instruction.md").write_text(
        instruction.read_text() if instruction.exists() else f"# {task_id}\n"
    )
    dockerfile = render_dockerfile(pins)
    (target / "environment/Dockerfile").write_text(dockerfile)
    (target / "environment/docker-compose.yaml").write_text(
        render_compose(domain, cb_task_id, pins=pins)
    )
    (target / "tests/Dockerfile").write_text(
        dockerfile
        + '\nFROM verifier AS evaluation\nCOPY test.sh /tests/test.sh\nRUN chmod +x /tests/test.sh\nENTRYPOINT []\nCMD ["sleep", "infinity"]\n'
    )
    test_script = target / "tests/test.sh"
    test_script.write_text(SESSION_TEST_SH if session else TEST_SH)
    test_script.chmod(0o755)
    (target / "README.md").write_text(
        README.format(
            repo=SOURCE_REPO, org=name.split("/")[0], dataset=HF_DATASET, leaderboard=LEADERBOARD
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=REPO_ROOT / "data")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--org", default="actava-ai")
    parser.add_argument(
        "--source-revision",
        required=True,
        help="Full commit SHA of the clean published source checkout",
    )
    parser.add_argument("--dataset-revision", required=True, help="Full dataset commit SHA")
    parser.add_argument("--handbook-revision", required=True, help="Full handbook commit SHA")
    args = parser.parse_args()
    try:
        pins = BuildPins(args.source_revision, args.dataset_revision, args.handbook_revision)
        validate_source_checkout(REPO_ROOT, pins.source)
    except ValueError as exc:
        parser.error(str(exc))
    metadata = load_meta(args.data_root)
    out_tasks = args.out / "tasks"
    count = 0
    for _, (glob, domain) in FAMILIES.items():
        for source in sorted(args.data_root.glob(glob)):
            if not (source / "task.toml").exists() and not (source / "instruction.md").exists():
                continue
            task_id = source.name
            emit_task(
                source,
                out_tasks,
                f"{args.org}/{task_id}",
                task_id,
                task_id,
                domain,
                metadata.get(task_id, {}),
                pins=pins,
            )
            count += 1
    for relative, task_id in MARATHON.items():
        source = args.data_root / relative
        if source.exists():
            emit_task(
                source,
                out_tasks,
                f"{args.org}/{task_id}",
                task_id,
                relative,
                "marathon",
                metadata.get(relative, metadata.get(task_id, {})),
                pins=pins,
                session=True,
            )
            count += 1
    print(f"Exported {count} Harbor tasks to {out_tasks}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
