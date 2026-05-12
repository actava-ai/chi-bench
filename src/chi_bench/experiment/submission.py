"""chi-Bench submission configuration + validation.

A submission YAML names one (agent, model) pair and runs it across one or more
chi-Bench domains. The CLI fan-out lives in ``cli.py`` (``cb submission``);
this module owns the schema, loader, preflight checks, run loop, and provenance
capture.

The schema is intentionally minimal — everything tunable on the per-trial
``ExperimentConfig`` is exposed under ``run:``, dataset paths are derived from
``dataset.domains`` via a fixed registry, and provenance is captured at run
time (not in the YAML).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import platform
import shutil
import socket
import subprocess
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from chi_bench.experiment.config import Environment

logger = logging.getLogger(__name__)

SUBMISSION_SCHEMA_V1 = "chi-bench/submission/v1"

# Short aliases accepted on the CLI / in YAML, mapped to the canonical
# domain key. The canonical keys match dataset directory names.
DOMAIN_ALIASES: dict[str, str] = {
    "pa": "pa_provider",
    "pa_provider": "pa_provider",
    "pa-provider": "pa_provider",
    "um": "pa_um",
    "pa_um": "pa_um",
    "pa-um": "pa_um",
    "cm": "cm",
}

# Canonical domain registry: dataset + registry path relative to data_root.
DOMAIN_REGISTRY: dict[str, dict[str, str]] = {
    "pa_provider": {
        "dataset": "prior_auth_provider/tasks",
        "registry": "prior_auth_provider/registry.json",
    },
    "pa_um": {
        "dataset": "prior_auth_um/tasks",
        "registry": "prior_auth_um/registry.json",
    },
    "cm": {
        "dataset": "care_management/tasks",
        "registry": "care_management/registry.json",
    },
}

CANONICAL_DOMAINS: tuple[str, ...] = tuple(DOMAIN_REGISTRY.keys())

# Built-in harness names. Unknown values produce a soft warning rather than an
# error so custom harnesses (registered out-of-tree) still work.
KNOWN_AGENTS: frozenset[str] = frozenset(
    {
        "claude-code",
        "codex",
        "gemini-cli",
        "openclaw",
        "hermes",
        "openai-agents",
        "deepagents",
        "claude-code-cli",
        "codex-cli",
        "dual-pa-e2e",
    }
)


class SubmissionMeta(BaseModel):
    """Who is submitting and what they're submitting."""

    id: str = Field(
        description=(
            "Stable slug-safe identifier; used in output paths and the manifest. "
            "Lowercase letters, digits, hyphen, underscore only."
        ),
    )
    team: str = Field(description="Team or individual name; appears on the leaderboard.")
    contact: str = Field(description="Contact email; not published.")
    agent: str = Field(description="Harness name registered in AGENT_HARNESS_IMPORT_PATHS.")
    model: str = Field(description="Model id passed verbatim to the harness.")
    notes: str | None = Field(default=None, description="Optional free-text notes.")

    @field_validator("id")
    @classmethod
    def _slug_safe(cls, v: str) -> str:
        if not v:
            raise ValueError("submission.id must be non-empty")
        bad = [c for c in v if not (c.isalnum() or c in "-_")]
        if bad:
            raise ValueError(
                f"submission.id contains forbidden characters {bad!r}; "
                "use only lowercase letters, digits, '-', '_'"
            )
        if v != v.lower():
            raise ValueError("submission.id must be lowercase")
        return v


class SubmissionRun(BaseModel):
    """Per-run knobs forwarded into ExperimentConfig for each domain slice."""

    environment: Environment = Field(default="modal")
    n_attempts: int = Field(
        default=1,
        ge=1,
        le=10,
        description=(
            "Attempts per task. Submission default is 1 (pass@1). Override to "
            ">1 for pass^N analysis; the leaderboard publishes pass@1 either way."
        ),
    )
    concurrency: int = Field(default=5, ge=1)
    max_retries: int = Field(default=2, ge=0)
    timeout_multiplier: float | None = Field(default=2.0)
    agent_timeout_multiplier: float | None = Field(default=None)
    env_file: str = Field(default=".env")


class SubmissionDataset(BaseModel):
    """Dataset pin + domain selection."""

    version: str = Field(
        description=(
            "HF dataset revision tag (e.g. 'chi-bench-v1.0.0'). Verified against "
            "data/.chi-bench-version at run start; mismatch is a hard error."
        ),
    )
    domains: list[str] = Field(
        default_factory=lambda: list(CANONICAL_DOMAINS),
        description="Canonical domain keys (or aliases) to run.",
    )

    @field_validator("domains", mode="before")
    @classmethod
    def _normalize_domains(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("dataset.domains must list at least one domain")
        out: list[str] = []
        for raw in v:
            key = DOMAIN_ALIASES.get(str(raw).strip().lower())
            if key is None:
                raise ValueError(
                    f"unknown domain {raw!r}; valid: "
                    + ", ".join(sorted(set(DOMAIN_ALIASES) | set(CANONICAL_DOMAINS)))
                )
            if key not in out:
                out.append(key)
        return out


class SubmissionPaths(BaseModel):
    """Filesystem layout for inputs + outputs."""

    data_root: Path = Field(default=Path("data"))
    output_root: Path | None = Field(
        default=None,
        description="Defaults to logs/submissions/<submission.id> when omitted.",
    )


class SubmissionConfig(BaseModel):
    """Full submission YAML."""

    schema_: Literal["chi-bench/submission/v1"] = Field(alias="schema")
    submission: SubmissionMeta
    run: SubmissionRun = Field(default_factory=SubmissionRun)
    dataset: SubmissionDataset
    paths: SubmissionPaths = Field(default_factory=SubmissionPaths)

    model_config = {"populate_by_name": True, "extra": "forbid"}

    @model_validator(mode="after")
    def _resolve_output_root(self) -> SubmissionConfig:
        if self.paths.output_root is None:
            self.paths.output_root = Path("logs/submissions") / self.submission.id
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> SubmissionConfig:
        text = Path(path).read_text()
        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: top-level YAML must be a mapping")
        return cls(**data)

    def domain_dataset_path(self, domain: str) -> Path:
        return self.paths.data_root / DOMAIN_REGISTRY[domain]["dataset"]

    def domain_registry_path(self, domain: str) -> Path:
        return self.paths.data_root / DOMAIN_REGISTRY[domain]["registry"]


# ─── Preflight checks ────────────────────────────────────────────────────────


class PreflightIssue(BaseModel):
    """One problem found by preflight; severity drives exit code."""

    severity: Literal["error", "warning"]
    code: str
    message: str


def preflight_dataset(cfg: SubmissionConfig) -> list[PreflightIssue]:
    """Verify data/ exists and its version tag matches cfg.dataset.version."""
    issues: list[PreflightIssue] = []
    data_root = cfg.paths.data_root

    if not data_root.is_dir():
        issues.append(
            PreflightIssue(
                severity="error",
                code="dataset.missing_root",
                message=(
                    f"data_root {data_root} does not exist; download the dataset with "
                    "`huggingface-cli download actava/chi-bench --repo-type dataset "
                    "--revision <rev> --local-dir data/` first."
                ),
            )
        )
        return issues

    version_file = data_root / ".chi-bench-version"
    if not version_file.exists():
        issues.append(
            PreflightIssue(
                severity="warning",
                code="dataset.version_file_missing",
                message=(
                    f"{version_file} not found; dataset version cannot be verified. "
                    f"Download via `huggingface-cli` and write the revision tag into "
                    f"{version_file} (local data is fine for development)."
                ),
            )
        )
    else:
        recorded = version_file.read_text().strip()
        if recorded != cfg.dataset.version:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="dataset.version_mismatch",
                    message=(
                        f"dataset.version pinned to '{cfg.dataset.version}' but "
                        f"{version_file} records '{recorded}'. Either edit the YAML "
                        f"to match, or re-download with `huggingface-cli` at revision "
                        f"'{cfg.dataset.version}' and update {version_file}."
                    ),
                )
            )

    for dom in cfg.dataset.domains:
        ds_path = cfg.domain_dataset_path(dom)
        if not ds_path.is_dir():
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="dataset.domain_missing",
                    message=f"domain '{dom}' dataset dir not found: {ds_path}",
                )
            )

    return issues


def preflight_environment(cfg: SubmissionConfig) -> list[PreflightIssue]:
    """Check that the chosen runtime environment is actually usable."""
    issues: list[PreflightIssue] = []

    env_file = Path(cfg.run.env_file)
    if not env_file.exists():
        issues.append(
            PreflightIssue(
                severity="warning",
                code="env.file_missing",
                message=(
                    f"env_file {env_file} not found; provider keys must be in "
                    "the parent shell env or the run will fail at trial start."
                ),
            )
        )

    if cfg.run.environment == "docker":
        if not shutil.which("docker"):
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="docker.cli_missing",
                    message="docker CLI not found on PATH.",
                )
            )
            return issues
        proc = subprocess.run(
            ["docker", "image", "inspect", "chi-bench:latest"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            issues.append(
                PreflightIssue(
                    severity="warning",
                    code="docker.image_missing",
                    message=(
                        "chi-bench:latest not present locally; "
                        "run `cb docker build` (or it will build at trial start, "
                        "which delays the first slice by ~5 min)."
                    ),
                )
            )
    elif cfg.run.environment == "modal":
        if not shutil.which("modal"):
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="modal.cli_missing",
                    message="modal CLI not found on PATH; install with `uv pip install modal`.",
                )
            )
            return issues
        proc = subprocess.run(
            ["modal", "token", "info"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if proc.returncode != 0:
            issues.append(
                PreflightIssue(
                    severity="error",
                    code="modal.token_missing",
                    message=(
                        "modal token not configured; run "
                        "`uv run modal setup` (or `uv run modal token new`)."
                    ),
                )
            )

    return issues


def preflight_agent(cfg: SubmissionConfig) -> list[PreflightIssue]:
    """Soft check that the agent name is recognised; custom harnesses pass."""
    if cfg.submission.agent in KNOWN_AGENTS:
        return []
    return [
        PreflightIssue(
            severity="warning",
            code="agent.unknown",
            message=(
                f"agent '{cfg.submission.agent}' is not a built-in harness "
                f"(known: {sorted(KNOWN_AGENTS)}). If you registered a custom "
                "harness this is fine; otherwise check spelling."
            ),
        )
    ]


def run_all_preflight(cfg: SubmissionConfig) -> list[PreflightIssue]:
    """Compose every preflight check; callers decide what to do with the result."""
    issues: list[PreflightIssue] = []
    issues.extend(preflight_dataset(cfg))
    issues.extend(preflight_environment(cfg))
    issues.extend(preflight_agent(cfg))
    return issues


# ─── Provenance ──────────────────────────────────────────────────────────────


def _utcnow_iso() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_sha_and_dirty() -> tuple[str | None, bool]:
    """Return (sha, is_dirty). Both fields are best-effort — Git not installed
    or the checkout being a tarball returns (None, False)."""
    if not shutil.which("git"):
        return None, False
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        return sha, bool(status)
    except (subprocess.SubprocessError, OSError):
        return None, False


def _docker_image_digest(image: str = "chi-bench:latest") -> str | None:
    if not shutil.which("docker"):
        return None
    try:
        out = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
        return out or None
    except (subprocess.SubprocessError, OSError):
        return None


def _chi_bench_version() -> str | None:
    try:
        return _pkg_version("chi-bench")
    except PackageNotFoundError:
        return None


def capture_provenance(cfg: SubmissionConfig) -> dict[str, object]:
    """Snapshot everything that affects reproducibility, at run start."""
    sha, dirty = _git_sha_and_dirty()
    prov: dict[str, object] = {
        "code_sha": sha,
        "code_dirty": dirty,
        "chi_bench_version": _chi_bench_version(),
        "dataset_version": cfg.dataset.version,
        "environment": cfg.run.environment,
        "started_at": _utcnow_iso(),
        "finished_at": None,
        "host": socket.gethostname(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }
    if cfg.run.environment == "docker":
        prov["docker_image_digest"] = _docker_image_digest()
    return prov


# ─── Run loop ────────────────────────────────────────────────────────────────


def _resolve_domains(cfg: SubmissionConfig, domain_filter: list[str] | None) -> list[str]:
    """Intersect cfg.dataset.domains with an optional CLI filter."""
    if not domain_filter:
        return list(cfg.dataset.domains)
    normalized: list[str] = []
    for raw in domain_filter:
        key = DOMAIN_ALIASES.get(raw.strip().lower())
        if key is None:
            raise ValueError(
                f"--domain {raw!r} is not a known domain alias; valid: "
                + ", ".join(sorted(set(DOMAIN_ALIASES)))
            )
        if key not in cfg.dataset.domains:
            raise ValueError(
                f"--domain {raw!r} (resolved to {key!r}) is not in this "
                f"submission's dataset.domains ({cfg.dataset.domains})"
            )
        if key not in normalized:
            normalized.append(key)
    return normalized


def _build_slice_yaml(cfg: SubmissionConfig, domain: str) -> dict[str, object]:
    """Synthesize the ExperimentConfig YAML for one (submission × domain) slice."""
    slice_cfg: dict[str, object] = {
        "dataset": str(cfg.domain_dataset_path(domain)),
        "registry_path": str(cfg.domain_registry_path(domain)),
        "agent": cfg.submission.agent,
        "model": cfg.submission.model,
        "concurrency": cfg.run.concurrency,
        "n_attempts": cfg.run.n_attempts,
        "max_retries": cfg.run.max_retries,
        "environment": cfg.run.environment,
        "env_file": cfg.run.env_file,
        "trials_dir": str(cfg.paths.output_root / domain),  # type: ignore[operator]
        "job_name": f"{cfg.submission.id}__{domain}",
    }
    if cfg.run.timeout_multiplier is not None:
        slice_cfg["timeout_multiplier"] = cfg.run.timeout_multiplier
    if cfg.run.agent_timeout_multiplier is not None:
        slice_cfg["agent_timeout_multiplier"] = cfg.run.agent_timeout_multiplier
    return slice_cfg


def _freeze_inputs(cfg: SubmissionConfig, source_yaml: Path) -> None:
    """Copy the submission YAML to output_root/sub.yaml so the artifacts are
    self-describing (no dependency on the user's CWD or original path)."""
    assert cfg.paths.output_root is not None  # set by model_validator
    cfg.paths.output_root.mkdir(parents=True, exist_ok=True)
    target = cfg.paths.output_root / "sub.yaml"
    target.write_text(source_yaml.read_text())


def run_submission(
    cfg: SubmissionConfig,
    source_yaml: Path,
    domain_filter: list[str] | None = None,
    prices_path: Path | None = None,
) -> Path:
    """Execute a submission across selected domains. Returns ``output_root``.

    For each domain: synthesize a single-slice ``ExperimentConfig`` YAML under
    ``output_root/<domain>/slice.yaml`` and hand it to ``run_experiment()`` —
    which is the same codepath ``cb experiment run -f`` uses. Harbor
    writes the full per-trial tree (``trajectory.json``, ``scorecard.json``,
    ``verdicts.json``, ``result.json``, agent ``run_log.txt``, workspace
    artifacts) into ``output_root/<domain>/<trial_id>/`` — this raw tree is
    preserved for human verification and is NOT what gets uploaded. The
    upload-ready bundle is produced separately by ``submission package``,
    which downsamples to a smaller zip.

    After every selected domain finishes, aggregate results into
    ``output_root/results.csv`` (pass@1 only — see ``_SUBMISSION_RESULT_KEYS``)
    and write a ``submission.json`` manifest with provenance + submission
    meta + overall + per-domain pass@1.

    Provenance is captured before the first slice starts; ``finished_at`` is
    written even when a slice fails, so partial runs remain inspectable.

    Domains run sequentially. Within each domain, Harbor parallelizes per
    ``cfg.run.concurrency``.
    """
    from chi_bench.experiment.runner import run_experiment

    assert cfg.paths.output_root is not None  # set by model_validator
    domains = _resolve_domains(cfg, domain_filter)
    if not domains:
        raise ValueError("No domains selected after filter — nothing to run.")

    if cfg.run.n_attempts > 1:
        logger.warning(
            "run.n_attempts=%d (>1) is not a valid leaderboard submission — "
            "policy is one run per task. submission.json will still publish "
            "pass@1 only; extra attempts are kept on disk for analysis.",
            cfg.run.n_attempts,
        )

    issues = run_all_preflight(cfg)
    errors = [i for i in issues if i.severity == "error"]
    for w in (i for i in issues if i.severity == "warning"):
        logger.warning("preflight warning [%s]: %s", w.code, w.message)
    if errors:
        for e in errors:
            logger.error("preflight error [%s]: %s", e.code, e.message)
        raise RuntimeError(
            f"{len(errors)} preflight error(s) — fix or rerun with --skip-preflight."
        )

    _freeze_inputs(cfg, source_yaml)
    provenance = capture_provenance(cfg)
    provenance_path = cfg.paths.output_root / "provenance.json"
    provenance_path.write_text(json.dumps(provenance, indent=2))

    logger.info(
        "submission '%s' starting: agent=%s model=%s domains=%s env=%s",
        cfg.submission.id,
        cfg.submission.agent,
        cfg.submission.model,
        domains,
        cfg.run.environment,
    )

    try:
        for domain in domains:
            slice_dir = cfg.paths.output_root / domain
            slice_dir.mkdir(parents=True, exist_ok=True)
            slice_yaml = slice_dir / "slice.yaml"
            slice_yaml.write_text(
                yaml.safe_dump(
                    _build_slice_yaml(cfg, domain),
                    sort_keys=False,
                    default_flow_style=False,
                )
            )
            logger.info("─── running domain %s ───", domain)
            run_experiment(config=str(slice_yaml))
    finally:
        provenance["finished_at"] = _utcnow_iso()
        provenance_path.write_text(json.dumps(provenance, indent=2))

    # Aggregation + manifest are best-effort: a run that crashed mid-domain
    # still produces what it can. write_manifest handles partial trees.
    try:
        write_manifest(cfg, output_root=cfg.paths.output_root, prices_path=prices_path)
    except Exception:  # noqa: BLE001 — never let aggregation crash a successful run
        logger.exception("manifest write failed (aggregation skipped)")

    return cfg.paths.output_root


# ─── Aggregate + manifest ────────────────────────────────────────────────────


_RESULTS_CSV_NAME = "results.csv"
_MANIFEST_NAME = "submission.json"
_DEFAULT_PRICES_PATH = Path("configs/prices.yaml")

# Submission outputs publish pass@1 only — leaderboard policy is one attempt
# per task. pass@3 / pass^3 / Wilson CIs are paper-table statistics; they
# require ``n_attempts >= 3`` per task to mean anything and don't belong in a
# v1 submission manifest. Users who want them can run ``scripts/aggregate.py``
# directly over the raw trial tree (full row shape is preserved on disk).
_SUBMISSION_RESULT_KEYS: tuple[str, ...] = (
    "agent",
    "model",
    "n_trials",
    "n_tasks",
    "pass_at_1",
    "mean_cost_usd",
    "mean_walltime_s",
)


def _project_submission_row(row: dict[str, object]) -> dict[str, object]:
    """Strip a full aggregator row down to submission-relevant columns."""
    return {k: row[k] for k in _SUBMISSION_RESULT_KEYS if k in row}


def aggregate_submission(
    cfg: SubmissionConfig,
    output_root: Path | None = None,
    prices_path: Path | None = None,
) -> dict[str, object]:
    """Compute overall + per-domain pass@1 + cost for a submission.

    Walks ``output_root`` (default: ``cfg.paths.output_root``) once for the
    overall aggregate, then per ``cfg.dataset.domains`` for per-domain rows.
    Domains with no completed trials are omitted from ``per_domain`` rather
    than reported as zeroes — that lets ``submission status`` distinguish
    "didn't run" from "ran and failed".

    Rows are projected down to the submission schema
    (``_SUBMISSION_RESULT_KEYS``): only pass@1 and cost/walltime appear, no
    pass@3 / pass^3 / Wilson intervals.
    """
    from chi_bench.aggregator import aggregate_to_rows

    root = output_root or cfg.paths.output_root
    assert root is not None
    prices = prices_path or _DEFAULT_PRICES_PATH if _DEFAULT_PRICES_PATH.exists() else prices_path

    overall_rows = aggregate_to_rows(root, prices_path=prices)
    overall = _project_submission_row(overall_rows[0]) if overall_rows else None

    per_domain: dict[str, dict[str, object]] = {}
    for dom in cfg.dataset.domains:
        dom_root = root / dom
        if not dom_root.is_dir():
            continue
        dom_rows = aggregate_to_rows(dom_root, prices_path=prices)
        if dom_rows:
            # Submissions are single-(agent, model); always one row per domain
            per_domain[dom] = _project_submission_row(dom_rows[0])

    return {"overall": overall, "per_domain": per_domain}


def build_manifest(
    cfg: SubmissionConfig,
    output_root: Path | None = None,
    prices_path: Path | None = None,
) -> dict[str, object]:
    """Assemble the ``submission.json`` payload from cfg + provenance + results.

    Reads ``provenance.json`` (written at run start) and merges in the
    aggregator output. Designed to be deterministic given a fixed trial tree.
    """
    root = output_root or cfg.paths.output_root
    assert root is not None

    provenance_path = root / "provenance.json"
    if provenance_path.exists():
        provenance = json.loads(provenance_path.read_text())
    else:
        provenance = {}

    results = aggregate_submission(cfg, output_root=root, prices_path=prices_path)

    return {
        "schema": SUBMISSION_SCHEMA_V1,
        "submission": cfg.submission.model_dump(),
        "run": cfg.run.model_dump(),
        "dataset": cfg.dataset.model_dump(),
        "provenance": provenance,
        "results": results["overall"],
        "per_domain": results["per_domain"],
    }


# ─── Status ──────────────────────────────────────────────────────────────────


class DomainProgress(BaseModel):
    domain: str
    expected_tasks: int  # 0 means "unknown"
    n_trials: int
    n_passed: int
    n_failed: int

    @property
    def state(self) -> Literal["pending", "running", "done"]:
        if self.n_trials == 0:
            return "pending"
        if self.expected_tasks and self.n_trials < self.expected_tasks:
            return "running"
        return "done"


def status_submission(
    cfg: SubmissionConfig,
    output_root: Path | None = None,
) -> dict[str, object]:
    """Walk a submission output tree and report progress per domain.

    Counts trial dirs and their pass/fail state from ``result.json`` (which
    Harbor writes only after the trial completes). A trial dir without
    ``result.json`` is treated as "running, not yet counted" — both n_passed
    and n_failed exclude it. expected_tasks comes from a count of dataset
    task dirs (if ``data_root`` is populated); otherwise 0 = unknown.
    """
    root = output_root or cfg.paths.output_root
    assert root is not None

    domain_rows: list[DomainProgress] = []
    for dom in cfg.dataset.domains:
        dom_dir = root / dom
        if not dom_dir.is_dir():
            domain_rows.append(
                DomainProgress(
                    domain=dom,
                    expected_tasks=_count_tasks(cfg, dom),
                    n_trials=0,
                    n_passed=0,
                    n_failed=0,
                )
            )
            continue

        n_trials = 0
        n_passed = 0
        n_failed = 0
        for result_json in dom_dir.rglob("result.json"):
            try:
                data = json.loads(result_json.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            vr = data.get("verifier_result")
            if not isinstance(vr, dict):
                # Skip run-level aggregate result.json files; only per-trial
                # results carry a verifier_result block.
                continue
            n_trials += 1
            rb = vr.get("rewards")
            reward = float((rb or {}).get("reward", 0.0)) if rb else float(vr.get("reward", 0.0))
            if reward >= 1.0:
                n_passed += 1
            else:
                n_failed += 1

        domain_rows.append(
            DomainProgress(
                domain=dom,
                expected_tasks=_count_tasks(cfg, dom),
                n_trials=n_trials,
                n_passed=n_passed,
                n_failed=n_failed,
            )
        )

    started_at: str | None = None
    finished_at: str | None = None
    provenance_path = root / "provenance.json"
    if provenance_path.exists():
        try:
            prov = json.loads(provenance_path.read_text())
            started_at = prov.get("started_at")
            finished_at = prov.get("finished_at")
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "submission_id": cfg.submission.id,
        "output_root": str(root),
        "started_at": started_at,
        "finished_at": finished_at,
        "domains": [r.model_dump() | {"state": r.state} for r in domain_rows],
    }


def _count_tasks(cfg: SubmissionConfig, domain: str) -> int:
    """Count task dirs in the dataset tree; 0 = data_root not populated."""
    ds = cfg.domain_dataset_path(domain)
    if not ds.is_dir():
        return 0
    return sum(1 for p in ds.iterdir() if p.is_dir())


# ─── Package (audit zip) ─────────────────────────────────────────────────────


# Files copied verbatim from output_root → packet root.
_PACKET_TOP_LEVEL_FILES: tuple[str, ...] = (
    "submission.json",
    "results.csv",
    "sub.yaml",
    "provenance.json",
)

# Per-trial files kept in the packet. Paths are relative to each trial dir.
# Everything else (config.json, trial.log, artifacts/, verifier scratch,
# agent session caches) is dropped to keep the packet ≲50 MB zipped.
_PACKET_TRIAL_FILES: tuple[str, ...] = (
    "result.json",
    "verifier/scorecard.json",
    "verifier/reward.json",
    "agent/trajectory.json",
)


def _iter_trial_dirs(output_root: Path, domains: list[str]) -> list[tuple[str, Path]]:
    """Yield (domain, trial_dir) for every trial under output_root/<domain>/.

    A "trial dir" is identified by a per-trial ``result.json`` (verified via
    ``is_per_trial_result`` so the run-level aggregate file Harbor writes
    next to the trial dirs is skipped). Incomplete trials — those without
    ``result.json`` — are likewise excluded so the packet never claims more
    evidence than exists.
    """
    from chi_bench.aggregator import is_per_trial_result

    trials: list[tuple[str, Path]] = []
    for dom in domains:
        dom_dir = output_root / dom
        if not dom_dir.is_dir():
            continue
        for result_json in dom_dir.rglob("result.json"):
            if not is_per_trial_result(result_json):
                continue
            trials.append((dom, result_json.parent))
    return trials


def package_submission(
    cfg: SubmissionConfig,
    output_root: Path | None = None,
    zip_path: Path | None = None,
    refresh_manifest: bool = True,
    prices_path: Path | None = None,
) -> Path:
    """Build an upload-ready zip of evidence for human verification.

    Includes:
      - submission.json, results.csv, sub.yaml, provenance.json (at zip root)
      - per trial: result.json + verifier/scorecard.json + verifier/reward.json
        + agent/trajectory.json  (under ``trials/<domain>/<trial_id>/``)

    Skipped: workspace artifacts, server logs, agent session caches, Harbor
    config.json, trial.log, verifier intermediates. The raw trial tree on
    disk is untouched — this command is read-only.

    ``refresh_manifest=True`` (default) re-runs aggregation and rewrites
    ``submission.json`` + ``results.csv`` before zipping, so the packet is
    coherent with the current trial state even if the user re-ran some
    trials after the initial ``submission run``.

    Returns the zip path. Default location:
    ``<output_root>/<submission_id>.zip``.
    """
    import zipfile

    root = output_root or cfg.paths.output_root
    assert root is not None
    if not root.is_dir():
        raise FileNotFoundError(f"output_root not found: {root}")

    if refresh_manifest:
        try:
            write_manifest(cfg, output_root=root, prices_path=prices_path)
        except Exception:  # noqa: BLE001
            logger.exception("refresh_manifest failed; packaging stale manifest if present")

    out_zip = zip_path or root / f"{cfg.submission.id}.zip"
    out_zip.parent.mkdir(parents=True, exist_ok=True)

    trials = _iter_trial_dirs(root, list(cfg.dataset.domains))
    n_included = 0
    n_missing_files = 0
    missing_top: list[str] = []

    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Top-level files
        for name in _PACKET_TOP_LEVEL_FILES:
            src = root / name
            if src.exists():
                zf.write(src, arcname=name)
            else:
                missing_top.append(name)

        # Per-trial files
        for dom, trial_dir in trials:
            arc_trial_prefix = f"trials/{dom}/{trial_dir.name}"
            for rel in _PACKET_TRIAL_FILES:
                src = trial_dir / rel
                if src.exists():
                    zf.write(src, arcname=f"{arc_trial_prefix}/{rel}")
                else:
                    n_missing_files += 1
                    logger.debug("packet: %s missing from %s", rel, trial_dir)
            n_included += 1

    if missing_top:
        logger.warning(
            "packet: top-level files missing from output_root: %s — "
            "the zip is incomplete for upload; ensure `submission run` "
            "completed successfully.",
            missing_top,
        )

    logger.info(
        "packet written: %s  (trials=%d, missing-file-warnings=%d)",
        out_zip,
        n_included,
        n_missing_files,
    )
    return out_zip


# ─── Data download (HF dataset + .chi-bench-version) ─────────────────────────


def download_dataset(
    revision: str,
    repo_id: str = "actava/chi-bench",
    data_root: Path = Path("data"),
) -> Path:
    """Wrap ``huggingface-cli download`` and pin the revision tag.

    Writes ``data_root/.chi-bench-version`` so subsequent submission preflight
    can verify the data on disk matches ``sub.yaml``'s ``dataset.version``.
    """
    if not shutil.which("huggingface-cli"):
        raise RuntimeError(
            "huggingface-cli not on PATH; install with `uv pip install -U 'huggingface_hub[cli]'`."
        )
    data_root.mkdir(parents=True, exist_ok=True)
    logger.info("downloading %s revision %s into %s", repo_id, revision, data_root)
    subprocess.run(
        [
            "huggingface-cli",
            "download",
            repo_id,
            "--repo-type",
            "dataset",
            "--revision",
            revision,
            "--local-dir",
            str(data_root),
        ],
        check=True,
    )
    version_file = data_root / ".chi-bench-version"
    version_file.write_text(revision + "\n")
    logger.info("pinned %s = %s", version_file, revision)
    return data_root


def write_manifest(
    cfg: SubmissionConfig,
    output_root: Path | None = None,
    prices_path: Path | None = None,
) -> tuple[Path, Path | None]:
    """Write ``submission.json`` and (when there's data) ``results.csv``.

    The CSV uses the submission projection (pass@1 + cost only); paper-Table-1
    columns with Wilson CIs and pass^3 are deliberately omitted — see
    ``_SUBMISSION_RESULT_KEYS``. Users who want the full row shape can run
    ``scripts/aggregate.py`` directly over the trial tree (which stays intact).

    Returns the manifest path and the CSV path (None when no trials exist).
    """
    from chi_bench.aggregator import write_rows_csv

    root = output_root or cfg.paths.output_root
    assert root is not None
    root.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(cfg, output_root=root, prices_path=prices_path)
    manifest_path = root / _MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str))

    csv_path: Path | None = None
    overall = manifest.get("results")
    if isinstance(overall, dict):
        csv_path = root / _RESULTS_CSV_NAME
        write_rows_csv([overall], csv_path)

    return manifest_path, csv_path
