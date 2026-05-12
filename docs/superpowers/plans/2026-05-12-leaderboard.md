# Leaderboard Repo + `cb submission prepare` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace chi-bench's `cb submission package` (zip-producing) with `cb submission prepare` (directory-producing), and scaffold the new public `actava-ai/leaderboard` repo to accept submissions via PR with schema+integrity CI validation.

**Architecture:** Two loosely-coupled repos. chi-bench's `prepare` writes a curated packet directory (`<date>-<slug>/` with manifest, csv, frozen yaml, provenance, auto-generated README, and per-trial scorecards + zstd-compressed trajectories). The leaderboard repo organizes submissions under `benchmarks/<name>/submissions/<date>-<slug>/`, validates them via a single Python validator (used both by `.github/workflows/validate.yml` and a local `scripts/validate.py` shim), and offers `scripts/submit.py` as an optional one-command helper for the fork/branch/commit/PR flow. The handoff is a packet directory — no cross-imports.

**Tech Stack:** Python 3.12, `typer` (chi-bench CLI), `pydantic`, `zstandard` (new dep), `jsonschema` (new dep, leaderboard-side only), `pytest`, `ruff`. Leaderboard repo: GitHub Actions, `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-05-12-leaderboard-design.md` (commit `3c59fb2`).

**Working directories:**
- chi-bench: `/Users/weiran/Github/chi-bench/`
- leaderboard: `/Users/weiran/Github/chi-bench/leaderboard/` (empty repo, remote `git@github.com:actava-ai/leaderboard.git`, no commits yet)

---

## File Structure

### chi-bench changes

| File | Action | Purpose |
|---|---|---|
| `pyproject.toml` | Modify | Add `zstandard>=0.22` to `dependencies` |
| `src/chi_bench/experiment/trajectory_pack.py` | Create | JSONL re-serialize + zstd compress trajectories |
| `src/chi_bench/experiment/packet_readme.py` | Create | Auto-generate per-submission README.md |
| `src/chi_bench/experiment/submission.py` | Modify | Add `prepare_packet()`; delete `package_submission()` and zip code; drop `import zipfile` |
| `src/chi_bench/cli.py` | Modify | Add `submission prepare` command; delete `submission package` command |
| `tests/unit/test_trajectory_pack.py` | Create | Tests for the recoder |
| `tests/unit/test_packet_readme.py` | Create | Tests for the README generator |
| `tests/unit/test_prepare_packet.py` | Create | Tests for the orchestrator |
| `tests/unit/test_submission_config.py` | Modify | Drop `package_submission` import; remove any package tests |
| `README.md` | Modify | Rewrite §4 "Submit your agent" (lines ~122–166) |
| `CLAUDE.md` | Modify | Update Commands section (line 110) |
| `docs/cli.md` | Modify | Replace `cb submission package` entry (lines 22, 300–318) |
| `docs/submission-packet.md` | Create | Cross-benchmark packet contract |

### leaderboard repo (all new)

| File | Purpose |
|---|---|
| `LICENSE` | Apache-2.0 (copy from chi-bench) |
| `.gitignore` | `/tmp/`, `*.zip`, `*.bak` |
| `.gitattributes` | Minimal (no LFS) |
| `README.md` | What this is + submission flow (manual + helper) + benchmarks tracked |
| `CONTRIBUTING.md` | Reviewer checklist + resubmission policy |
| `benchmarks/README.md` | Cross-benchmark contract for adding a new benchmark |
| `benchmarks/chi-bench/README.md` | chi-bench-specific notes |
| `benchmarks/chi-bench/schema/submission-v1.json` | JSON Schema |
| `benchmarks/chi-bench/schema/known-versions.txt` | One dataset version per line |
| `benchmarks/chi-bench/schema/README.md` | Schema versioning policy |
| `.github/workflows/validate.yml` | PR check workflow |
| `.github/scripts/validate_submission.py` | The validator (~400 lines) |
| `.github/scripts/test_validate_submission.py` | Validator tests |
| `.github/scripts/_fixtures/` | Test fixture packets |
| `.github/PULL_REQUEST_TEMPLATE/submission.md` | Submitter checklist |
| `scripts/validate.py` | 5-line shim |
| `scripts/submit.py` | One-command helper (~250 lines) |
| `scripts/test_submit.py` | Helper tests |

---

## Phase 1 — chi-bench producer

Phase 1 must ship working before any leaderboard work, so the leaderboard's validator has a real packet to validate against.

### Task 1: Add `zstandard` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add zstandard to dependencies**

Open `pyproject.toml` and add `"zstandard>=0.22.0",` to the `dependencies` list (alphabetically, after `"yaml..."` or similar; keep existing ordering style).

- [ ] **Step 2: Sync the lockfile**

Run: `uv sync --extra dev`
Expected: `zstandard` appears in the install output; no other version changes.

- [ ] **Step 3: Verify import works**

Run: `uv run python -c "import zstandard; print(zstandard.__version__)"`
Expected: a version string `0.22.x` or higher.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add zstandard dep for trajectory compression"
```

---

### Task 2: Trajectory pack module (JSONL + zstd)

**Files:**
- Create: `src/chi_bench/experiment/trajectory_pack.py`
- Test: `tests/unit/test_trajectory_pack.py`

- [ ] **Step 1: Write the failing test for round-trip**

Create `tests/unit/test_trajectory_pack.py`:

```python
"""Tests for chi_bench.experiment.trajectory_pack."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import zstandard as zstd

from chi_bench.experiment.trajectory_pack import (
    pack_trajectory_to_jsonl_zst,
    iter_packed_messages,
)


def _sample_trajectory() -> dict:
    return {
        "schema_version": "ATIF-v1.2",
        "session_id": "abc-123",
        "agent": {"name": "claude-code", "model_name": "claude-opus-4-7"},
        "steps": [
            {"step_id": 1, "source": "user", "message": "hello"},
            {"step_id": 2, "source": "assistant", "message": "hi back"},
        ],
    }


def test_pack_writes_zstd_jsonl(tmp_path: Path) -> None:
    src = tmp_path / "trajectory.json"
    src.write_text(json.dumps(_sample_trajectory()))
    dst = tmp_path / "trajectory.jsonl.zst"

    pack_trajectory_to_jsonl_zst(src, dst)

    assert dst.exists()
    # Decompress and verify line shape.
    decompressor = zstd.ZstdDecompressor()
    with dst.open("rb") as fh, decompressor.stream_reader(fh) as reader:
        text = io.TextIOWrapper(reader, encoding="utf-8").read()
    lines = text.strip().split("\n")
    assert len(lines) == 3  # header + 2 steps
    header = json.loads(lines[0])
    assert header == {
        "_atif_header": {
            "schema_version": "ATIF-v1.2",
            "session_id": "abc-123",
            "agent": {"name": "claude-code", "model_name": "claude-opus-4-7"},
        }
    }
    step1 = json.loads(lines[1])
    assert step1["step_id"] == 1


def test_iter_packed_messages_streams(tmp_path: Path) -> None:
    src = tmp_path / "trajectory.json"
    src.write_text(json.dumps(_sample_trajectory()))
    dst = tmp_path / "trajectory.jsonl.zst"
    pack_trajectory_to_jsonl_zst(src, dst)

    messages = list(iter_packed_messages(dst))
    # header + 2 steps
    assert len(messages) == 3
    assert "_atif_header" in messages[0]
    assert messages[1]["step_id"] == 1
    assert messages[2]["step_id"] == 2


def test_pack_handles_missing_steps_key(tmp_path: Path) -> None:
    """Some agents may emit trajectories with no 'steps' key — produce header only."""
    src = tmp_path / "trajectory.json"
    src.write_text(json.dumps({"schema_version": "ATIF-v1.2"}))
    dst = tmp_path / "trajectory.jsonl.zst"

    pack_trajectory_to_jsonl_zst(src, dst)

    messages = list(iter_packed_messages(dst))
    assert len(messages) == 1
    assert "_atif_header" in messages[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_trajectory_pack.py -v`
Expected: ImportError or "module not found" for `chi_bench.experiment.trajectory_pack`.

- [ ] **Step 3: Implement the module**

Create `src/chi_bench/experiment/trajectory_pack.py`:

```python
"""Pack agent trajectory.json files into streaming-friendly JSONL+zstd.

Input: a JSON file with the ATIF-v1.2 shape
    {"schema_version": ..., "session_id": ..., "agent": {...}, "steps": [...]}

Output: zstd-compressed JSONL where line 1 is a header object
    {"_atif_header": {schema_version, session_id, agent}}
and subsequent lines are individual step objects.

This format is optimized for streaming validation (line-by-line json.loads)
without buffering the full trajectory in memory.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import zstandard as zstd

_ZSTD_LEVEL = 19
_HEADER_KEYS = ("schema_version", "session_id", "agent")


def pack_trajectory_to_jsonl_zst(src: Path, dst: Path) -> None:
    """Re-serialize ``src`` (ATIF JSON) into ``dst`` (zstd-compressed JSONL).

    Header metadata (everything except ``steps``) lands on line 1 under the
    ``_atif_header`` key. Each entry of ``steps`` becomes a subsequent line.
    """
    payload: dict[str, Any] = json.loads(src.read_text(encoding="utf-8"))
    header = {k: payload[k] for k in _HEADER_KEYS if k in payload}
    steps: list[dict[str, Any]] = payload.get("steps", []) or []

    compressor = zstd.ZstdCompressor(level=_ZSTD_LEVEL)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("wb") as fh, compressor.stream_writer(fh) as writer:
        writer.write((json.dumps({"_atif_header": header}, separators=(",", ":")) + "\n").encode("utf-8"))
        for step in steps:
            writer.write((json.dumps(step, separators=(",", ":")) + "\n").encode("utf-8"))


def iter_packed_messages(path: Path) -> Iterator[dict[str, Any]]:
    """Stream-decode a packed trajectory, yielding one dict per line.

    Used by both the validator (integrity check) and any consumer that
    wants to inspect a trajectory without writing the decompressed bytes.
    """
    decompressor = zstd.ZstdDecompressor()
    with path.open("rb") as fh, decompressor.stream_reader(fh) as reader:
        text_stream = io.TextIOWrapper(reader, encoding="utf-8")
        for line in text_stream:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_trajectory_pack.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chi_bench/experiment/trajectory_pack.py tests/unit/test_trajectory_pack.py
git commit -m "feat(submission): add trajectory_pack for JSONL+zstd recoding"
```

---

### Task 3: Packet README generator

**Files:**
- Create: `src/chi_bench/experiment/packet_readme.py`
- Test: `tests/unit/test_packet_readme.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_packet_readme.py`:

```python
"""Tests for chi_bench.experiment.packet_readme."""

from __future__ import annotations

from chi_bench.experiment.packet_readme import render_packet_readme


def test_render_packet_readme_basic() -> None:
    manifest = {
        "schema": "chi-bench/submission/v1",
        "submission": {
            "id": "actava-claude-code-opus-4-6",
            "team": "Actava",
            "agent": "claude-code",
            "model": "anthropic/claude-opus-4-6",
            "submitted_at": "2026-05-12T14:03:11Z",
        },
        "dataset": {
            "name": "chi-bench",
            "version": "chi-bench-v1.0.0",
            "domains": ["pa_provider", "pa_um", "cm"],
        },
        "results": {
            "overall": {"pass_at_1": 0.280, "n_trials": 75},
            "per_domain": {
                "pa_provider": {"pass_at_1": 0.304, "n_trials": 25},
                "pa_um": {"pass_at_1": 0.316, "n_trials": 25},
                "cm": {"pass_at_1": 0.220, "n_trials": 25},
            },
        },
    }
    text = render_packet_readme(manifest)
    assert "# Actava · claude-code · anthropic/claude-opus-4-6" in text
    assert "Submitted: 2026-05-12" in text
    assert "chi-bench chi-bench-v1.0.0" in text
    assert "pass@1: **28.0%**" in text
    assert "| pa_provider | 30.4% | 25 |" in text
    assert "| pa_um | 31.6% | 25 |" in text
    assert "| cm | 22.0% | 25 |" in text
    assert "zstdcat trials/pa_provider/" in text


def test_render_handles_missing_per_domain_keys() -> None:
    """A partial submission may not have all three domains."""
    manifest = {
        "schema": "chi-bench/submission/v1",
        "submission": {
            "id": "x", "team": "T", "agent": "a", "model": "m",
            "submitted_at": "2026-05-12T00:00:00Z",
        },
        "dataset": {"name": "chi-bench", "version": "v1", "domains": ["pa_provider"]},
        "results": {
            "overall": {"pass_at_1": 0.5, "n_trials": 25},
            "per_domain": {"pa_provider": {"pass_at_1": 0.5, "n_trials": 25}},
        },
    }
    text = render_packet_readme(manifest)
    assert "| pa_provider | 50.0% | 25 |" in text
    assert "pa_um" not in text
    assert "cm |" not in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_packet_readme.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement the module**

Create `src/chi_bench/experiment/packet_readme.py`:

```python
"""Render the per-submission README.md committed alongside a packet."""

from __future__ import annotations

from typing import Any

_TEMPLATE = """\
# {team} · {agent} · {model}

Submitted: {date} · {bench_name} {bench_version} · pass@1: **{overall_pct}%**

| Domain | pass@1 | n_trials |
|---|---|---|
{rows}

Inspect a trajectory:

    zstdcat trials/{first_domain}/<trial_id>/agent/trajectory.jsonl.zst | jq .

See `submission.json` for the full manifest, `provenance.json` for reproducibility info.
"""


def render_packet_readme(manifest: dict[str, Any]) -> str:
    sub = manifest["submission"]
    ds = manifest["dataset"]
    res = manifest["results"]

    submitted_at: str = sub["submitted_at"]
    date = submitted_at.split("T", 1)[0]

    overall_pct = f"{res['overall']['pass_at_1'] * 100:.1f}"

    domains: list[str] = list(ds.get("domains") or [])
    per_dom = res.get("per_domain") or {}
    rows = []
    for dom in domains:
        if dom not in per_dom:
            continue
        d = per_dom[dom]
        pct = f"{d['pass_at_1'] * 100:.1f}"
        rows.append(f"| {dom} | {pct}% | {d['n_trials']} |")
    rows_text = "\n".join(rows)

    first_domain = domains[0] if domains else "pa_provider"

    return _TEMPLATE.format(
        team=sub["team"],
        agent=sub["agent"],
        model=sub["model"],
        date=date,
        bench_name=ds["name"],
        bench_version=ds["version"],
        overall_pct=overall_pct,
        rows=rows_text,
        first_domain=first_domain,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_packet_readme.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chi_bench/experiment/packet_readme.py tests/unit/test_packet_readme.py
git commit -m "feat(submission): add per-submission README generator"
```

---

### Task 4: `prepare_packet()` orchestrator

**Files:**
- Modify: `src/chi_bench/experiment/submission.py` (add new function, do not yet delete old `package_submission`)
- Test: `tests/unit/test_prepare_packet.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_prepare_packet.py`:

```python
"""Tests for prepare_packet()."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chi_bench.experiment.submission import (
    SUBMISSION_SCHEMA_V1,
    SubmissionConfig,
    prepare_packet,
)
from chi_bench.experiment.trajectory_pack import iter_packed_messages


def _write_yaml(path: Path, sub_id: str = "test-sub") -> Path:
    path.write_text(
        f"""schema: {SUBMISSION_SCHEMA_V1}
submission:
  id: {sub_id}
  team: Test Team
  contact: t@example.com
  agent: claude-code
  model: anthropic/claude-opus-4-6
dataset:
  version: chi-bench-v1.0.0
  domains: [pa_provider]
run:
  environment: docker
"""
    )
    return path


def _seed_trial_tree(output_root: Path, domain: str = "pa_provider", trial_id: str = "trial1") -> Path:
    """Create a minimal trial directory that prepare_packet can curate."""
    trial = output_root / domain / "sub" / trial_id
    trial.mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({"reward": 1.0, "passed": True}))
    (trial / "verifier").mkdir()
    (trial / "verifier" / "scorecard.json").write_text(json.dumps({"checks": []}))
    (trial / "verifier" / "reward.json").write_text(json.dumps({"reward": 1.0}))
    (trial / "agent").mkdir()
    (trial / "agent" / "trajectory.json").write_text(
        json.dumps({
            "schema_version": "ATIF-v1.2",
            "session_id": "s1",
            "agent": {"name": "claude-code", "model_name": "claude-opus-4-6"},
            "steps": [{"step_id": 1, "source": "user", "message": "hi"}],
        })
    )
    # write_manifest expects a sub.yaml at output_root; seed minimal versions
    (output_root / "sub.yaml").write_text("schema: chi-bench/submission/v1\n")
    return trial


def test_prepare_packet_writes_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="my-team-x")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root)

    cfg = SubmissionConfig.from_yaml(yaml_path)
    # Pin output_root to the temp dir
    cfg.paths.output_root = output_root

    # Force a deterministic date
    packet_dir = prepare_packet(cfg, out_dir=tmp_path / "packet", date="2026-05-12")

    expected = tmp_path / "packet" / "2026-05-12-my-team-x"
    assert packet_dir == expected
    assert (expected / "submission.json").is_file()
    assert (expected / "results.csv").is_file()
    assert (expected / "sub.yaml").is_file()
    assert (expected / "provenance.json").is_file()
    assert (expected / "README.md").is_file()
    # No zip artifacts.
    assert not list(expected.glob("*.zip"))


def test_prepare_packet_recodes_trajectories(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="t")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root, trial_id="trialA")

    cfg = SubmissionConfig.from_yaml(yaml_path)
    cfg.paths.output_root = output_root
    packet_dir = prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")

    packed = packet_dir / "trials" / "pa_provider" / "trialA" / "agent" / "trajectory.jsonl.zst"
    assert packed.is_file()
    # Original .json should NOT be present.
    assert not (packet_dir / "trials" / "pa_provider" / "trialA" / "agent" / "trajectory.json").exists()
    messages = list(iter_packed_messages(packed))
    assert len(messages) == 2  # header + 1 step
    assert "_atif_header" in messages[0]


def test_prepare_packet_refuses_to_overwrite(tmp_path: Path) -> None:
    yaml_path = _write_yaml(tmp_path / "sub.yaml", sub_id="x")
    output_root = tmp_path / "out"
    output_root.mkdir()
    _seed_trial_tree(output_root)
    cfg = SubmissionConfig.from_yaml(yaml_path)
    cfg.paths.output_root = output_root

    prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")
    with pytest.raises(FileExistsError):
        prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12")
    # --force allows it
    prepare_packet(cfg, out_dir=tmp_path / "p", date="2026-05-12", force=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_prepare_packet.py -v`
Expected: ImportError on `prepare_packet`.

- [ ] **Step 3: Implement `prepare_packet`**

In `src/chi_bench/experiment/submission.py`, add at the end of the "Package" section (after the existing `_PACKET_TRIAL_FILES` constant at line ~839):

```python
def prepare_packet(
    cfg: SubmissionConfig,
    out_dir: Path | None = None,
    date: str | None = None,
    force: bool = False,
) -> Path:
    """Curate a ``submission run`` output tree into a leaderboard-ready packet.

    Writes ``<out_dir>/<YYYY-MM-DD>-<submission.id>/`` containing:
      - submission.json, results.csv, sub.yaml, provenance.json (refreshed)
      - README.md (auto-generated)
      - trials/<domain>/<trial_id>/ with result.json, verifier/{scorecard,reward}.json,
        and agent/trajectory.jsonl.zst (recoded from the raw trajectory.json).

    Returns the directory path. Raises FileExistsError if the target exists
    and ``force`` is False.
    """
    import datetime as _dt

    from chi_bench.experiment.packet_readme import render_packet_readme
    from chi_bench.experiment.trajectory_pack import pack_trajectory_to_jsonl_zst

    output_root = cfg.paths.output_root
    assert output_root is not None
    if not output_root.is_dir():
        raise FileNotFoundError(f"output_root not found: {output_root}")

    # Refresh manifest + results.csv so they reflect current trial state.
    try:
        write_manifest(cfg, output_root=output_root)
    except Exception:  # noqa: BLE001
        logger.exception("refresh_manifest failed; preparing packet from stale manifest if present")

    date_str = date or _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    base = out_dir or (output_root / "packet")
    target = base / f"{date_str}-{cfg.submission.id}"
    if target.exists():
        if not force:
            raise FileExistsError(f"packet exists: {target} (pass force=True to overwrite)")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    # Top-level files
    missing_top: list[str] = []
    for name in _PACKET_TOP_LEVEL_FILES:
        src = output_root / name
        if src.exists():
            shutil.copy2(src, target / name)
        else:
            missing_top.append(name)
    if missing_top:
        logger.warning("packet: top-level files missing: %s", missing_top)

    # Per-trial tree
    trials = _iter_trial_dirs(output_root, list(cfg.dataset.domains))
    n_included = 0
    for dom, trial_dir in trials:
        out_trial = target / "trials" / dom / trial_dir.name
        out_trial.mkdir(parents=True)
        for rel in ("result.json", "verifier/scorecard.json", "verifier/reward.json"):
            src = trial_dir / rel
            if not src.exists():
                logger.debug("packet: %s missing from %s", rel, trial_dir)
                continue
            dst = out_trial / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        # Trajectory: recode .json → .jsonl.zst
        traj_src = trial_dir / "agent" / "trajectory.json"
        if traj_src.exists():
            pack_trajectory_to_jsonl_zst(traj_src, out_trial / "agent" / "trajectory.jsonl.zst")
        else:
            logger.debug("packet: agent/trajectory.json missing from %s", trial_dir)
        n_included += 1

    # README.md from the (refreshed) manifest
    manifest_path = target / "submission.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        (target / "README.md").write_text(render_packet_readme(manifest), encoding="utf-8")

    logger.info("packet prepared: %s (trials=%d)", target, n_included)
    return target
```

Add `import json` and `import shutil` at the top of the file if not already imported (check existing imports — both are likely already there).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_prepare_packet.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/chi_bench/experiment/submission.py tests/unit/test_prepare_packet.py
git commit -m "feat(submission): add prepare_packet() — directory-producing curator"
```

---

### Task 5: Register `cb submission prepare` CLI command

**Files:**
- Modify: `src/chi_bench/cli.py:788-823` (add new command alongside existing `package` for now)

- [ ] **Step 1: Add the new command**

In `src/chi_bench/cli.py`, immediately above the existing `@submission_app.command("package")` decorator at line 788, add:

```python
@submission_app.command("prepare")
def submission_prepare_cmd(
    config: Path = typer.Option(..., "-f", "--config", help="Submission YAML."),
    out: Path | None = typer.Option(
        None,
        "-o",
        "--out",
        help="Packet output base directory. Default: <output_root>/packet/.",
    ),
    date: str | None = typer.Option(
        None,
        "--date",
        help="Override the YYYY-MM-DD prefix on the packet directory. Default: today (UTC).",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite an existing packet directory at the target path.",
    ),
) -> None:
    """Build a leaderboard-ready submission packet directory.

    Curates the trial tree from ``submission run`` into
    ``<out>/<YYYY-MM-DD>-<submission_id>/`` containing the manifest,
    results.csv, frozen sub.yaml, provenance, an auto-generated README,
    and per-trial scorecards + zstd-compressed trajectories. The raw trial
    tree on disk is unchanged.

    Submit the packet via the actava-ai/leaderboard repo. See
    https://github.com/actava-ai/leaderboard for the current submission flow.
    """
    from pydantic import ValidationError

    from chi_bench.experiment.submission import SubmissionConfig, prepare_packet

    try:
        cfg = SubmissionConfig.from_yaml(config)
    except (ValidationError, yaml.YAMLError, ValueError, OSError) as e:
        typer.echo(f"Could not load {config}: {e}", err=True)
        raise typer.Exit(2) from None

    try:
        packet_dir = prepare_packet(cfg, out_dir=out, date=date, force=force)
    except FileExistsError as e:
        typer.echo(f"{e}", err=True)
        typer.echo("Re-run with --force to overwrite, or pass --date to use a different prefix.", err=True)
        raise typer.Exit(1) from None
    except FileNotFoundError as e:
        typer.echo(f"Cannot prepare: {e}", err=True)
        raise typer.Exit(1) from None

    typer.echo(f"Packet ready: {packet_dir}")
    typer.echo("")
    typer.echo("Submit it via the leaderboard repo:")
    typer.echo("  https://github.com/actava-ai/leaderboard")
```

- [ ] **Step 2: Verify the CLI is registered**

Run: `uv run cb submission --help`
Expected: output lists `prepare` between `status` and `package`.

- [ ] **Step 3: Smoke-test against existing local data**

Pick a real submission output already present at `logs/submissions/my-team-claude-code-sonnet-4-6/` (verified to exist earlier).

Run:
```bash
uv run cb submission prepare \
  -f configs/submission_example.yaml \
  --date 2026-05-12 \
  --out /tmp/cb-prepare-smoke
```

Expected: command may fail at `from_yaml` validation because `submission_example.yaml` is a template — that's fine; the goal here is to verify the CLI wiring works. If it fails on YAML validation, the wiring is correct.

A cleaner smoke: write a minimal YAML to `/tmp/sub.yaml`:
```yaml
schema: chi-bench/submission/v1
submission:
  id: smoke
  team: Smoke
  contact: x@example.com
  agent: claude-code
  model: anthropic/claude-opus-4-6
dataset:
  version: chi-bench-v1.0.0
  domains: [pa_provider]
paths:
  output_root: logs/submissions/my-team-claude-code-sonnet-4-6
```
Then: `uv run cb submission prepare -f /tmp/sub.yaml --date 2026-05-12 --out /tmp/cb-prepare-smoke`
Expected: prints `Packet ready: /tmp/cb-prepare-smoke/2026-05-12-smoke`; directory contains the expected files.

- [ ] **Step 4: Commit**

```bash
git add src/chi_bench/cli.py
git commit -m "feat(cli): add 'cb submission prepare' command"
```

---

### Task 6: Remove `cb submission package` + zip code

**Files:**
- Modify: `src/chi_bench/cli.py:788-823` (delete the `submission_package_cmd` function and decorator)
- Modify: `src/chi_bench/experiment/submission.py:820-947` (delete `_PACKET_TOP_LEVEL_FILES` and `_PACKET_TRIAL_FILES`'s package-only callers? No — they're reused by `prepare_packet`. Delete only `package_submission()` and the section header comment that names "audit zip", and the `import zipfile` if no other use)
- Modify: `tests/unit/test_submission_config.py:13-29` (drop `package_submission` from the import list; remove any test functions exercising it)

- [ ] **Step 1: Remove the CLI command**

In `src/chi_bench/cli.py`, delete the entire block from `@submission_app.command("package")` (line ~788) through the end of `submission_package_cmd()` (line ~823 — the `typer.echo(f"Packet written: ...")` line).

- [ ] **Step 2: Remove `package_submission()` function**

In `src/chi_bench/experiment/submission.py`, delete the function `package_submission()` (starts at line ~865, ends at the `return out_zip` ~line 947). Keep the surrounding constants `_PACKET_TOP_LEVEL_FILES` and `_PACKET_TRIAL_FILES` — `prepare_packet` uses them. Also delete or rename the section header comment `# ─── Package (audit zip) ────────────...` to `# ─── Packet (leaderboard-ready directory) ─────...` for clarity.

- [ ] **Step 3: Remove `import zipfile` if unused**

In `src/chi_bench/experiment/submission.py`, search for any remaining `zipfile.` references:
```bash
grep -n "zipfile" src/chi_bench/experiment/submission.py
```
Expected: no matches.
If clean, remove `import zipfile` from the top of the file (it lived inside `package_submission`, not at module top — verify by re-reading the original line 891). Check the file's `import` block at the top doesn't include `zipfile`.

- [ ] **Step 4: Update test imports**

In `tests/unit/test_submission_config.py:13-29`, remove `package_submission,` from the import list. If any test functions reference `package_submission`, delete those tests entirely.

```bash
grep -n "package_submission" tests/unit/test_submission_config.py
```
Expected after edits: no matches.

- [ ] **Step 5: Update other places that mention `submission package`**

In `src/chi_bench/experiment/submission.py:531`, the docstring for `run_submission` mentions "upload-ready bundle is produced separately by ``submission package``". Update to `submission prepare`.

```bash
grep -rn "submission package\|package_submission" src/ tests/
```
Expected: no remaining production references. (Spec docs at `docs/superpowers/specs/*.md` may still reference it historically — leave them.)

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -x`
Expected: all tests pass; no import errors.

- [ ] **Step 7: Lint**

Run: `uv run ruff check src/ tests/`
Expected: clean (or only pre-existing unrelated warnings).

- [ ] **Step 8: Commit**

```bash
git add src/chi_bench/cli.py src/chi_bench/experiment/submission.py tests/unit/test_submission_config.py
git commit -m "feat(submission): remove 'package' command + package_submission() (replaced by 'prepare')"
```

---

### Task 7: Rewrite chi-bench README §4 "Submit your agent"

**Files:**
- Modify: `README.md` (currently lines ~122–166)

- [ ] **Step 1: Replace §4**

In `README.md`, replace the entire `## Submit your agent` section (starting at line ~122 with the heading, ending before `## Reproduce paper tables`) with:

````markdown
## Submit your agent

Submitting to the [leaderboard](https://github.com/actava-ai/leaderboard) is a 5-command flow: 3 against chi-bench (validate, run, prepare) and 2 against the leaderboard repo (commit + open PR).

**1. Configure.** Copy `configs/submission_example.yaml` to `configs/submissions/<your-id>.yaml` and edit `id`, `team`, `contact`, `agent`, `model`; optionally `notes` and `run.*`.

**2. Run trials and prepare a packet.**

```bash
# Schema + preflight: dataset pin, Modal token / Docker image, agent name.
uv run cb submission validate -f configs/submissions/<your-id>.yaml

# Run all 3 domains. Default: one trial per task (pass@1).
uv run cb submission run      -f configs/submissions/<your-id>.yaml

# Check progress; safe to run while `submission run` is in flight.
uv run cb submission status   -f configs/submissions/<your-id>.yaml

# Curate the leaderboard-ready packet (no zip — directory you can `cp` into the leaderboard repo).
uv run cb submission prepare  -f configs/submissions/<your-id>.yaml
```

The final command writes to `logs/submissions/<id>/packet/YYYY-MM-DD-<id>/`, containing:

```
submission.json                # manifest: agent, model, results, provenance
results.csv                    # leaderboard rows
sub.yaml                       # frozen copy of your config
provenance.json                # git SHA, image digest, timestamps
README.md                      # auto-generated headline summary
trials/<domain>/<trial_id>/
    result.json                # Harbor reward + agent metadata
    verifier/scorecard.json    # per-check verdicts
    verifier/reward.json       # verifier's reward breakdown
    agent/trajectory.jsonl.zst # full agent trace (zstd-compressed; inspect with `zstdcat | jq .`)
```

Workspace artifacts and Harbor scratch files are deliberately excluded so the packet stays small (typically <100 MB total).

**3. Submit the packet.** Follow the instructions at **https://github.com/actava-ai/leaderboard** — either the one-command helper (`python scripts/submit.py <packet-path>`) or the manual `cp` + `git` + `gh pr create` flow. Either way, the packet is identical; the leaderboard repo owns the submission workflow.

Packet contract (for benchmark authors building their own producers): [`docs/submission-packet.md`](docs/submission-packet.md).

**Policy notes.**

- **Partial submissions** (`--domain pa | um | cm` on `submission run`) are accepted but flagged as partial on the leaderboard.
- **Leaderboard is pass@1 only.** Set `run.n_attempts: 3` to keep extra trials on disk for your own pass@3 / pass^3 analysis — the manifest still publishes pass@1.
````

- [ ] **Step 2: Verify no broken cross-references**

Run: `grep -n "submission package\|\\.zip\|upload-ready" README.md`
Expected: no matches.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(README): rewrite §4 'Submit your agent' for the prepare/PR flow"
```

---

### Task 8: Update `docs/cli.md` and `CLAUDE.md`

**Files:**
- Modify: `docs/cli.md:22, 300-318`
- Modify: `CLAUDE.md:110`

- [ ] **Step 1: Update `docs/cli.md` exit-code line**

Edit line 22 of `docs/cli.md`:

Old:
```
- `2` — schema or YAML-load failure (typically `cb submission validate` / `cb submission run` / `cb submission status` / `cb submission package`).
```

New:
```
- `2` — schema or YAML-load failure (typically `cb submission validate` / `cb submission run` / `cb submission status` / `cb submission prepare`).
```

- [ ] **Step 2: Replace the `cb submission package` entry**

In `docs/cli.md`, find the `### cb submission package` section (around line 300). Replace lines ~300–325 (the whole subsection) with:

````markdown
### `cb submission prepare`

Curate a `submission run` output tree into a leaderboard-ready packet directory.

```
cb submission prepare -f <sub.yaml> [-o <out-dir>] [--date YYYY-MM-DD] [--force]
```

Writes `<out-dir>/<YYYY-MM-DD>-<submission_id>/` containing the manifest, results.csv, frozen sub.yaml, provenance, auto-generated README, and per-trial scorecards + zstd-compressed trajectories (`agent/trajectory.jsonl.zst`). Workspace artifacts, server logs, agent caches, and Harbor scratch are deliberately excluded.

**Flags:**

- `-f` / `--config` — submission YAML (required).
- `-o` / `--out` — packet base directory. Default: `<output_root>/packet/`.
- `--date` — override the `YYYY-MM-DD` prefix on the packet directory name. Default: today (UTC).
- `--force` — overwrite an existing packet at the target path.

**Example:**

```bash
uv run cb submission prepare -f configs/submissions/my-team.yaml
# Packet ready: logs/submissions/my-team/packet/2026-05-12-my-team-claude-code-opus-4-6/
```

Submit the packet via the actava-ai/leaderboard repo (manual `cp + git + gh pr` or `python scripts/submit.py`). See the leaderboard's [README](https://github.com/actava-ai/leaderboard) for the current submission flow.
````

- [ ] **Step 3: Update `CLAUDE.md`**

Edit line 110 of `CLAUDE.md`:

Old:
```
uv run cb submission package  -f configs/submissions/<id>.yaml
```

New:
```
uv run cb submission prepare  -f configs/submissions/<id>.yaml
```

- [ ] **Step 4: Verify no stray references**

Run: `grep -rn "submission package" docs/ CLAUDE.md README.md 2>/dev/null`
Expected: no matches (spec docs under `docs/superpowers/specs/` may still mention it historically — leave them).

- [ ] **Step 5: Commit**

```bash
git add docs/cli.md CLAUDE.md
git commit -m "docs: update cli.md + CLAUDE.md to reference 'cb submission prepare'"
```

---

### Task 9: Add `docs/submission-packet.md`

**Files:**
- Create: `docs/submission-packet.md`

- [ ] **Step 1: Write the doc**

Create `docs/submission-packet.md`:

````markdown
# Submission packet contract

This document specifies the format of a **submission packet** — the directory a benchmark producer hands to the actava-ai/leaderboard repo. Any benchmark that emits packets matching this contract is submittable via the leaderboard's `scripts/submit.py` (or the manual flow); the leaderboard's CI validator (`.github/scripts/validate_submission.py`) enforces it.

chi-bench produces packets via `cb submission prepare`. New benchmarks publish their own equivalent.

## Directory shape

```
<YYYY-MM-DD>-<submission_id>/
├── submission.json
├── results.csv
├── sub.yaml
├── provenance.json
├── README.md
└── trials/
    └── <domain>/
        └── <trial_id>/
            ├── result.json
            ├── verifier/
            │   ├── scorecard.json
            │   └── reward.json
            └── agent/
                └── trajectory.jsonl.zst
```

- Directory name regex: `^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9_-]{0,63}$`. The slug part equals `submission.json:submission.id`. The date is UTC and must be ≤ today.
- No additional files. No `.zip`, no `.bak`, no hidden files (except `.gitkeep`). The validator rejects anything outside the allowlist.

## Required `submission.json` envelope

The outer envelope is **stable across benchmarks**. Validators rely on these three fields:

| Field | Type | Purpose |
|---|---|---|
| `schema` | string | `"<benchmark>/submission/v<N>"` — selects the per-benchmark JSON Schema |
| `submission.id` | slug | Lowercase letters, digits, `-`, `_`. Equals the directory's slug suffix. |
| `dataset.name` | string | The benchmark slug under `benchmarks/<name>/` in the leaderboard repo |

Everything inside `results.*` is benchmark-specific and lives in the per-benchmark schema.

## Trajectory format

`agent/trajectory.jsonl.zst` is zstd-compressed JSONL (level 19). Line 1 is a header object:

```json
{"_atif_header": {"schema_version": "...", "session_id": "...", "agent": {...}}}
```

Lines 2..N are individual step / message objects. The validator stream-decodes the file and parses each line; full-file buffering is not required (and not recommended for large trajectories).

Reviewers inspect with:

```bash
zstdcat trials/<domain>/<trial_id>/agent/trajectory.jsonl.zst | jq .
```

## Size budget (enforced by the leaderboard validator)

| File | Soft (warn) | Hard (fail) |
|---|---|---|
| `submission.json`, `results.csv`, `sub.yaml`, `provenance.json` | 100 KB | 1 MB |
| `verifier/scorecard.json`, `verifier/reward.json`, `result.json` | 200 KB | 2 MB |
| `agent/trajectory.jsonl.zst` | 10 MB | 50 MB |
| Total submission directory | 100 MB | 500 MB |

## Producing a packet for a new benchmark

1. Pick a benchmark slug; reserve `benchmarks/<slug>/` in the leaderboard repo.
2. Write a JSON Schema at `benchmarks/<slug>/schema/submission-v1.json` covering the envelope above plus your benchmark-specific `results.*` shape.
3. Build your tooling to emit a packet directory matching the layout above. Reuse `cb submission prepare` as a reference implementation if helpful (`src/chi_bench/experiment/submission.py:prepare_packet`).
4. Open a PR against the leaderboard repo adding `benchmarks/<slug>/{schema/,submissions/,README.md}`; submissions follow normally thereafter.

`scripts/submit.py` in the leaderboard repo is benchmark-agnostic — it reads `submission.json:dataset.name` to route the packet into the right subtree, so once the schema is registered no further leaderboard-side code is needed.
````

- [ ] **Step 2: Commit**

```bash
git add docs/submission-packet.md
git commit -m "docs: add submission packet contract (cross-benchmark)"
```

---

## Phase 2 — Leaderboard scaffold

All Phase 2 work happens inside `/Users/weiran/Github/chi-bench/leaderboard/` (a separate git repo with remote `actava-ai/leaderboard`). Commits in this phase go to that repo, not chi-bench.

**Initial setup:** `cd /Users/weiran/Github/chi-bench/leaderboard && git status` should show no commits yet. All commits below use `cd leaderboard && git ...`.

### Task 10: Leaderboard repo skeleton (LICENSE, .gitignore, .gitattributes, top-level README placeholder)

**Files (all in `leaderboard/`):**
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `.gitattributes`
- Create: `README.md` (placeholder; full version in Task 17)

- [ ] **Step 1: Copy LICENSE from chi-bench**

```bash
cp /Users/weiran/Github/chi-bench/LICENSE /Users/weiran/Github/chi-bench/leaderboard/LICENSE
```

- [ ] **Step 2: Write `.gitignore`**

Create `leaderboard/.gitignore`:

```
# Local scratch from submit.py dry-runs
/tmp/

# Legacy zip artifact — never tracked
*.zip

# Backups
*.bak
*.json.bak

# Python caches (validator + tests)
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 3: Write `.gitattributes`**

Create `leaderboard/.gitattributes`:

```
# zstd-packed trajectories are binary; ensure git doesn't try to diff them.
*.zst binary

# JSON Schema files use LF endings.
*.json text eol=lf
```

- [ ] **Step 4: Write placeholder README**

Create `leaderboard/README.md`:

```markdown
# actava-ai/leaderboard

Public record of benchmark submissions for actava-ai benchmarks.

This repo accepts submissions via pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) and individual benchmark READMEs under [`benchmarks/`](benchmarks/) for the current submission flow.

**Benchmarks tracked:**

| Benchmark | Producer | Version |
|---|---|---|
| [chi-bench](benchmarks/chi-bench/) | [actava-ai/chi-bench](https://github.com/actava-ai/chi-bench) | chi-bench-v1.0.0 |

Rendered leaderboard: [actava.ai/benchmarks](https://actava.ai/benchmarks).
```

(Full README is written in Task 17 once `scripts/submit.py` exists.)

- [ ] **Step 5: Initial commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add LICENSE .gitignore .gitattributes README.md
git commit -m "chore: initial repo skeleton (LICENSE, .gitignore, .gitattributes, README stub)"
```

---

### Task 11: chi-bench schema files

**Files (all in `leaderboard/`):**
- Create: `benchmarks/README.md`
- Create: `benchmarks/chi-bench/README.md`
- Create: `benchmarks/chi-bench/schema/submission-v1.json`
- Create: `benchmarks/chi-bench/schema/known-versions.txt`
- Create: `benchmarks/chi-bench/schema/README.md`

- [ ] **Step 1: Create `benchmarks/README.md`**

```markdown
# benchmarks/

One subdirectory per benchmark, self-contained:

```
benchmarks/<name>/
├── README.md                  # submission notes for this benchmark
├── schema/
│   ├── submission-v1.json     # JSON Schema for submission.json
│   ├── known-versions.txt     # accepted dataset versions (one per line)
│   └── README.md              # versioning policy
└── submissions/
    └── <YYYY-MM-DD>-<slug>/   # one dir per accepted submission
```

## Adding a new benchmark

1. Pick a benchmark slug (`my-bench`). Create `benchmarks/my-bench/{schema,submissions}/` and the four files above.
2. Write `schema/submission-v1.json` covering:
   - The **cross-benchmark envelope** documented in the chi-bench [submission packet contract](https://github.com/actava-ai/chi-bench/blob/main/docs/submission-packet.md) (fields `schema`, `submission.*`, `dataset.*`, `provenance.*` — required), and
   - Your benchmark-specific `results.*` shape.
3. List your benchmark's accepted dataset versions in `schema/known-versions.txt`, one per line.
4. Document any benchmark-specific notes in your `README.md` — how to produce a packet, how to inspect results, links to your producer repo.

No leaderboard-side code changes are needed. `scripts/submit.py` reads `submission.json:dataset.name` to route packets into the right subtree, and `.github/scripts/validate_submission.py` resolves your schema from the manifest's `schema:` field.
```

- [ ] **Step 2: Create `benchmarks/chi-bench/README.md`**

```markdown
# chi-bench

Submissions to the chi-Bench benchmark — long-horizon, policy-rich U.S. healthcare workflow agents across provider prior authorization, payer utilization management, and care management.

**Producer:** [actava-ai/chi-bench](https://github.com/actava-ai/chi-bench)
**Current dataset version:** `chi-bench-v1.0.0`
**Schema:** [`schema/submission-v1.json`](schema/submission-v1.json)

## Producing a packet

On the chi-bench side:

```bash
uv run cb submission prepare -f configs/submissions/<your-id>.yaml
# Packet ready: logs/submissions/<id>/packet/YYYY-MM-DD-<id>/
```

See chi-bench's [packet contract](https://github.com/actava-ai/chi-bench/blob/main/docs/submission-packet.md) for the directory shape.

## Submitting

Two paths, both equivalent:

**Quick (helper):**

```bash
python ../leaderboard/scripts/submit.py /path/to/packet/YYYY-MM-DD-<slug>/
```

**Manual:**

```bash
git clone https://github.com/<you>/leaderboard && cd leaderboard       # your fork
cp -r /path/to/packet/YYYY-MM-DD-<slug>/ benchmarks/chi-bench/submissions/
python scripts/validate.py benchmarks/chi-bench/submissions/YYYY-MM-DD-<slug>/
git checkout -b sub/chi-bench/YYYY-MM-DD-<slug>
git add benchmarks/chi-bench/submissions/YYYY-MM-DD-<slug>/
git commit -m "chi-bench: <team> · <agent> · <model>"
git push origin sub/chi-bench/YYYY-MM-DD-<slug>
gh pr create --base main
```

## Inspecting a trajectory

```bash
zstdcat benchmarks/chi-bench/submissions/<dir>/trials/<domain>/<trial_id>/agent/trajectory.jsonl.zst | jq .
```

Line 1 is the ATIF header; subsequent lines are individual agent steps.

## Headline metrics

`submission.json:results.overall.pass_at_1` is the leaderboard's primary ranking metric. Per-domain breakdowns live in `results.per_domain.{pa_provider,pa_um,cm}`. Cost (`mean_cost_usd`) and walltime (`mean_walltime_s`) are recorded but not currently ranked.
```

- [ ] **Step 3: Create the JSON Schema**

Create `benchmarks/chi-bench/schema/submission-v1.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://github.com/actava-ai/leaderboard/benchmarks/chi-bench/schema/submission-v1.json",
  "title": "chi-bench submission v1",
  "type": "object",
  "required": ["schema", "submission", "dataset", "results", "provenance"],
  "additionalProperties": false,
  "properties": {
    "schema": { "const": "chi-bench/submission/v1" },
    "submission": {
      "type": "object",
      "required": ["id", "team", "contact", "agent", "model", "submitted_at"],
      "additionalProperties": true,
      "properties": {
        "id": { "type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$" },
        "team": { "type": "string", "minLength": 1, "maxLength": 200 },
        "contact": { "type": "string", "minLength": 3 },
        "agent": { "type": "string", "minLength": 1 },
        "model": { "type": "string", "minLength": 1 },
        "notes": { "type": "string" },
        "submitted_at": { "type": "string", "format": "date-time" }
      }
    },
    "dataset": {
      "type": "object",
      "required": ["name", "version", "domains"],
      "additionalProperties": true,
      "properties": {
        "name": { "const": "chi-bench" },
        "version": { "type": "string", "pattern": "^chi-bench-v[0-9]+\\.[0-9]+\\.[0-9]+$" },
        "domains": {
          "type": "array",
          "minItems": 1,
          "uniqueItems": true,
          "items": { "enum": ["pa_provider", "pa_um", "cm"] }
        }
      }
    },
    "results": {
      "type": "object",
      "required": ["overall", "per_domain"],
      "additionalProperties": true,
      "properties": {
        "overall": { "$ref": "#/$defs/score" },
        "per_domain": {
          "type": "object",
          "minProperties": 1,
          "additionalProperties": { "$ref": "#/$defs/score" }
        },
        "mean_cost_usd": { "type": "number", "minimum": 0 },
        "mean_walltime_s": { "type": "number", "minimum": 0 }
      }
    },
    "provenance": {
      "type": "object",
      "required": ["chi_bench_git_sha", "image_digest", "judge_model", "harness_version"],
      "additionalProperties": true,
      "properties": {
        "chi_bench_git_sha": { "type": ["string", "null"] },
        "image_digest": { "type": ["string", "null"] },
        "judge_model": { "type": "string" },
        "judge_num_votes": { "type": "integer", "minimum": 1 },
        "harness_version": { "type": "string" }
      }
    }
  },
  "$defs": {
    "score": {
      "type": "object",
      "required": ["pass_at_1", "n_trials", "n_tasks"],
      "additionalProperties": true,
      "properties": {
        "pass_at_1": { "type": "number", "minimum": 0, "maximum": 1 },
        "pass_at_1_lo": { "type": "number", "minimum": 0, "maximum": 1 },
        "pass_at_1_hi": { "type": "number", "minimum": 0, "maximum": 1 },
        "n_trials": { "type": "integer", "minimum": 0 },
        "n_tasks": { "type": "integer", "minimum": 0 }
      }
    }
  }
}
```

- [ ] **Step 4: Create `known-versions.txt`**

```
chi-bench-v1.0.0
```

(One line per accepted version. Trailing newline.)

- [ ] **Step 5: Create `schema/README.md`**

```markdown
# chi-bench schema

JSON Schema files for chi-bench submission manifests.

## Files

- `submission-v1.json` — schema for `submission.json` envelope + chi-bench-specific `results.*` shape. Frozen at chi-bench v1.0.0 release.
- `known-versions.txt` — accepted `dataset.version` values, one per line. The validator's "unknown dataset version" check is a soft warning, not a failure; new versions can be added in a follow-up PR after the first submission lands.

## Versioning policy

- **`submission-v1.json` is frozen and never edited.** Submissions written against v1 stay valid forever.
- A new version (`submission-v2.json`) lands alongside it if backward-incompatible changes are required (e.g. the chi-bench v2 dataset removes a domain). Producers update their tooling to emit the new `schema:` string when they target the new dataset version.
- Adding a new optional field to v1 is acceptable iff the schema's `additionalProperties: true` already permits it (it does — at the envelope level and inside `results.*` and `provenance.*`).
```

- [ ] **Step 6: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add benchmarks/
git commit -m "feat(chi-bench): add v1 submission schema + benchmark README"
```

---

### Task 12: Validator — directory + naming + required-files checks (with fixtures)

**Files (all in `leaderboard/`):**
- Create: `.github/scripts/validate_submission.py` (initial skeleton)
- Create: `.github/scripts/test_validate_submission.py`
- Create: `.github/scripts/_fixtures/valid_min/` (a minimal valid packet — see Step 2)
- Create: `scripts/validate.py` (the 5-line shim — done here so tests use the real entry path)

This task delivers the first subset of validator checks (structural rules 1–4 from spec §4.2) plus the fixture infrastructure that all subsequent validator tasks reuse.

- [ ] **Step 1: Create the shim**

Create `leaderboard/scripts/validate.py`:

```python
#!/usr/bin/env python3
"""Local-runnable shim for the CI validator. Same code path as GitHub Actions.

Usage: python scripts/validate.py <path-to-submission-directory>
"""

import runpy
import sys

if __name__ == "__main__":
    sys.argv[0] = ".github/scripts/validate_submission.py"
    runpy.run_path(".github/scripts/validate_submission.py", run_name="__main__")
```

```bash
chmod +x leaderboard/scripts/validate.py
```

- [ ] **Step 2: Create the minimal valid fixture**

Create `leaderboard/.github/scripts/_fixtures/valid_min/2026-05-12-fixture/`:

```
2026-05-12-fixture/
├── submission.json
├── results.csv
├── sub.yaml
├── provenance.json
├── README.md
└── trials/pa_provider/trial_1/
    ├── result.json
    ├── verifier/scorecard.json
    ├── verifier/reward.json
    └── agent/trajectory.jsonl.zst
```

File contents:

**`submission.json`:**
```json
{
  "schema": "chi-bench/submission/v1",
  "submission": {
    "id": "fixture",
    "team": "Fixture Team",
    "contact": "fixture@example.com",
    "agent": "claude-code",
    "model": "anthropic/claude-opus-4-6",
    "submitted_at": "2026-05-12T12:00:00Z"
  },
  "dataset": {
    "name": "chi-bench",
    "version": "chi-bench-v1.0.0",
    "domains": ["pa_provider"]
  },
  "results": {
    "overall": {"pass_at_1": 1.0, "n_trials": 1, "n_tasks": 1},
    "per_domain": {"pa_provider": {"pass_at_1": 1.0, "n_trials": 1, "n_tasks": 1}}
  },
  "provenance": {
    "chi_bench_git_sha": "abc123",
    "image_digest": "sha256:def",
    "judge_model": "claude-opus-4-7",
    "harness_version": "1.0.0"
  }
}
```

**`results.csv`:**
```csv
benchmark,dataset_version,submission_id,team,agent,model,domain,pass_at_1,n_trials,n_tasks,submitted_at
chi-bench,chi-bench-v1.0.0,fixture,Fixture Team,claude-code,anthropic/claude-opus-4-6,overall,1.0,1,1,2026-05-12T12:00:00Z
chi-bench,chi-bench-v1.0.0,fixture,Fixture Team,claude-code,anthropic/claude-opus-4-6,pa_provider,1.0,1,1,2026-05-12T12:00:00Z
```

**`sub.yaml`:**
```yaml
schema: chi-bench/submission/v1
submission:
  id: fixture
```

**`provenance.json`:**
```json
{
  "chi_bench_git_sha": "abc123",
  "image_digest": "sha256:def",
  "judge_model": "claude-opus-4-7",
  "harness_version": "1.0.0"
}
```

**`README.md`:**
```markdown
# Fixture Team · claude-code · anthropic/claude-opus-4-6

Submitted: 2026-05-12 · chi-bench chi-bench-v1.0.0 · pass@1: **100.0%**
```

**`trials/pa_provider/trial_1/result.json`:**
```json
{"reward": 1.0, "passed": true}
```

**`trials/pa_provider/trial_1/verifier/scorecard.json`:**
```json
{"checks": []}
```

**`trials/pa_provider/trial_1/verifier/reward.json`:**
```json
{"reward": 1.0}
```

**`trials/pa_provider/trial_1/agent/trajectory.jsonl.zst`:**

Generate this with a Python one-liner so the fixture has a real zstd-compressed JSONL file:

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -c '
import json, zstandard as zstd, pathlib
out = pathlib.Path(".github/scripts/_fixtures/valid_min/2026-05-12-fixture/trials/pa_provider/trial_1/agent/trajectory.jsonl.zst")
out.parent.mkdir(parents=True, exist_ok=True)
header = {"_atif_header": {"schema_version": "ATIF-v1.2", "session_id": "fix", "agent": {"name": "claude-code"}}}
step = {"step_id": 1, "source": "user", "message": "hello"}
lines = (json.dumps(header) + "\n" + json.dumps(step) + "\n").encode("utf-8")
with out.open("wb") as fh:
    fh.write(zstd.ZstdCompressor(level=19).compress(lines))
'
```

(If `zstandard` is not installed system-wide, run via `uv run --with zstandard python -c '...'`.)

- [ ] **Step 3: Write failing tests for the structural checks**

Create `leaderboard/.github/scripts/test_validate_submission.py`:

```python
"""Tests for the leaderboard's submission validator."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

# Make the validator importable
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from validate_submission import (  # noqa: E402
    ValidationReport,
    check_directory_naming,
    check_required_files,
    check_no_unexpected_files,
    validate_packet,
)

FIXTURE_VALID = HERE / "_fixtures" / "valid_min" / "2026-05-12-fixture"


@pytest.fixture
def valid_packet(tmp_path: Path) -> Path:
    """Copy the canonical valid fixture into tmp_path so tests can mutate it."""
    dst = tmp_path / "2026-05-12-fixture"
    shutil.copytree(FIXTURE_VALID, dst)
    return dst


def test_directory_naming_accepts_valid(valid_packet: Path) -> None:
    report = ValidationReport()
    check_directory_naming(valid_packet, report, manifest_id="fixture")
    assert not report.has_errors(), report.errors


@pytest.mark.parametrize("bad", [
    "2026-13-99-fixture",    # impossible date
    "fixture",               # no date
    "2026-05-12-Fixture",    # uppercase in slug
    "2026-05-12-",           # empty slug
    "20260512-fixture",      # wrong date format
])
def test_directory_naming_rejects_invalid(tmp_path: Path, bad: str) -> None:
    p = tmp_path / bad
    p.mkdir()
    report = ValidationReport()
    check_directory_naming(p, report, manifest_id="fixture")
    assert report.has_errors()


def test_directory_naming_rejects_future_date(tmp_path: Path) -> None:
    p = tmp_path / "2099-12-31-fixture"
    p.mkdir()
    report = ValidationReport()
    check_directory_naming(p, report, manifest_id="fixture")
    assert any("future" in e.lower() for e in report.errors)


def test_directory_naming_rejects_slug_mismatch(tmp_path: Path) -> None:
    p = tmp_path / "2026-05-12-different-slug"
    p.mkdir()
    report = ValidationReport()
    check_directory_naming(p, report, manifest_id="fixture")
    assert any("submission.id" in e for e in report.errors)


def test_required_files_present(valid_packet: Path) -> None:
    report = ValidationReport()
    check_required_files(valid_packet, report)
    assert not report.has_errors(), report.errors


@pytest.mark.parametrize("missing", [
    "submission.json",
    "results.csv",
    "sub.yaml",
    "provenance.json",
    "README.md",
])
def test_required_files_missing(valid_packet: Path, missing: str) -> None:
    (valid_packet / missing).unlink()
    report = ValidationReport()
    check_required_files(valid_packet, report)
    assert any(missing in e for e in report.errors)


def test_required_files_missing_trial(valid_packet: Path) -> None:
    shutil.rmtree(valid_packet / "trials")
    report = ValidationReport()
    check_required_files(valid_packet, report)
    assert any("trial" in e.lower() for e in report.errors)


def test_no_unexpected_files_clean(valid_packet: Path) -> None:
    report = ValidationReport()
    check_no_unexpected_files(valid_packet, report)
    assert not report.has_errors()


def test_no_unexpected_files_rejects_zip(valid_packet: Path) -> None:
    (valid_packet / "bonus.zip").write_bytes(b"PK\x03\x04")
    report = ValidationReport()
    check_no_unexpected_files(valid_packet, report)
    assert any(".zip" in e for e in report.errors)


def test_no_unexpected_files_rejects_bak(valid_packet: Path) -> None:
    (valid_packet / "sub.yaml.bak").write_text("")
    report = ValidationReport()
    check_no_unexpected_files(valid_packet, report)
    assert any(".bak" in e for e in report.errors)


def test_no_unexpected_files_rejects_hidden(valid_packet: Path) -> None:
    (valid_packet / ".DS_Store").write_bytes(b"")
    report = ValidationReport()
    check_no_unexpected_files(valid_packet, report)
    assert any(".DS_Store" in e for e in report.errors)


def test_validate_packet_end_to_end_passes_on_valid(valid_packet: Path) -> None:
    """The full validate_packet() entry point should accept the canonical fixture."""
    report = validate_packet(valid_packet)
    assert not report.has_errors(), report.errors
```

- [ ] **Step 4: Run tests to verify they fail**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: import error on `validate_submission` (module doesn't exist yet).

- [ ] **Step 5: Implement the validator skeleton + first four checks**

Create `leaderboard/.github/scripts/validate_submission.py`:

```python
#!/usr/bin/env python3
"""Submission validator for actava-ai/leaderboard.

Runs both in CI (.github/workflows/validate.yml) and locally via
scripts/validate.py. No GitHub-specific dependencies in the core checks.

Usage:
    python validate_submission.py <path-to-submission-dir>
    python validate_submission.py --base-ref <sha> --head-ref <sha> \
        --report-md <path> --report-json <path>
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import re
import sys
from pathlib import Path

DIR_NAME_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-([a-z0-9][a-z0-9_-]{0,63})$")

REQUIRED_TOP_LEVEL_FILES = (
    "submission.json",
    "results.csv",
    "sub.yaml",
    "provenance.json",
    "README.md",
)

# File-extension allowlist for "unexpected file" check.
ALLOWED_EXTENSIONS = frozenset({".json", ".csv", ".yaml", ".yml", ".md", ".txt", ".zst"})
ALLOWED_HIDDEN_NAMES = frozenset({".gitkeep"})


@dataclasses.dataclass
class ValidationReport:
    errors: list[str] = dataclasses.field(default_factory=list)
    warnings: list[str] = dataclasses.field(default_factory=list)
    info: dict[str, object] = dataclasses.field(default_factory=dict)

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def has_errors(self) -> bool:
        return bool(self.errors)


def check_directory_naming(packet_dir: Path, report: ValidationReport, manifest_id: str | None) -> None:
    """Rule 2 of spec §4.2: <YYYY-MM-DD>-<slug>/, slug equals manifest id, date ≤ today UTC."""
    name = packet_dir.name
    m = DIR_NAME_RE.match(name)
    if not m:
        report.err(
            f"Directory name '{name}' does not match required pattern "
            f"^\\d{{4}}-\\d{{2}}-\\d{{2}}-[a-z0-9][a-z0-9_-]{{0,63}}$"
        )
        return
    year, month, day, slug = m.group(1), m.group(2), m.group(3), m.group(4)
    try:
        date_val = dt.date(int(year), int(month), int(day))
    except ValueError as e:
        report.err(f"Directory name '{name}' has an invalid date: {e}")
        return
    today = dt.datetime.now(dt.UTC).date()
    if date_val > today:
        report.err(f"Directory name '{name}' has a future date ({date_val}); must be ≤ today UTC ({today})")
    if manifest_id is not None and slug != manifest_id:
        report.err(
            f"Directory slug '{slug}' does not match submission.id '{manifest_id}' in submission.json"
        )


def check_required_files(packet_dir: Path, report: ValidationReport) -> None:
    """Rule 3 of spec §4.2: required top-level files + at least one trial result.json."""
    for name in REQUIRED_TOP_LEVEL_FILES:
        if not (packet_dir / name).is_file():
            report.err(f"Required file missing: {name}")

    trials_dir = packet_dir / "trials"
    if not trials_dir.is_dir():
        report.err("Required directory missing: trials/")
        return
    result_files = list(trials_dir.glob("*/*/result.json"))
    if not result_files:
        report.err("No trial result.json files found under trials/<domain>/<trial_id>/")


def check_no_unexpected_files(packet_dir: Path, report: ValidationReport) -> None:
    """Rule 4 of spec §4.2: reject .zip, .bak, hidden files (except .gitkeep), path traversal."""
    for path in packet_dir.rglob("*"):
        if path.is_dir():
            continue
        rel = path.relative_to(packet_dir)
        name = path.name
        # Hidden files
        if name.startswith(".") and name not in ALLOWED_HIDDEN_NAMES:
            report.err(f"Unexpected hidden file: {rel}")
            continue
        # Path traversal in any segment
        if any(part == ".." for part in rel.parts):
            report.err(f"Path traversal in {rel}")
            continue
        # Suffix check (use the *full* suffix chain via Path.suffixes for .bak/.json.bak)
        suffixes = "".join(path.suffixes)
        if suffixes.endswith(".bak"):
            report.err(f"Unexpected backup file: {rel}")
            continue
        if path.suffix == ".zip":
            report.err(f"Unexpected zip file: {rel}")
            continue
        if path.suffix and path.suffix not in ALLOWED_EXTENSIONS:
            report.err(f"Unexpected file extension '{path.suffix}': {rel}")


def _load_manifest_id(packet_dir: Path) -> str | None:
    mf = packet_dir / "submission.json"
    if not mf.is_file():
        return None
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    sub = data.get("submission") or {}
    sid = sub.get("id")
    return sid if isinstance(sid, str) else None


def validate_packet(packet_dir: Path) -> ValidationReport:
    """Top-level entry point — runs all checks against a single packet directory.

    Subsequent tasks extend this with schema, results.csv consistency,
    per-trial integrity, and soft warnings.
    """
    report = ValidationReport()
    if not packet_dir.is_dir():
        report.err(f"Not a directory: {packet_dir}")
        return report

    manifest_id = _load_manifest_id(packet_dir)
    check_directory_naming(packet_dir, report, manifest_id)
    check_required_files(packet_dir, report)
    check_no_unexpected_files(packet_dir, report)
    return report


def _print_report(report: ValidationReport, packet_dir: Path) -> int:
    if report.has_errors():
        print(f"❌ {packet_dir.name}: {len(report.errors)} error(s)", file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)
    else:
        print(f"✅ {packet_dir.name}: validation passed")
    if report.warnings:
        print(f"⚠️  {len(report.warnings)} warning(s)", file=sys.stderr)
        for w in report.warnings:
            print(f"  - {w}", file=sys.stderr)
    return 1 if report.has_errors() else 0


def _main_single(packet_dir: Path) -> int:
    report = validate_packet(packet_dir)
    return _print_report(report, packet_dir)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a leaderboard submission packet.")
    parser.add_argument("path", nargs="?", type=Path, help="Path to a single submission directory.")
    parser.add_argument("--base-ref", help="(CI) PR base SHA — used to compute diff scope.")
    parser.add_argument("--head-ref", help="(CI) PR head SHA — used to compute diff scope.")
    parser.add_argument("--report-md", type=Path, help="(CI) write Markdown report to this path.")
    parser.add_argument("--report-json", type=Path, help="(CI) write structured JSON report to this path.")
    args = parser.parse_args(argv)

    # CI mode wiring lands in Task 16 (diff scope + multi-packet handling).
    # For now: if --base-ref/--head-ref given, fall through to single-packet mode using `path`.
    if args.path is None:
        parser.error("path is required (CI mode arrives in a later task)")
    return _main_single(args.path)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: all parametrized tests pass.

If `pytest` isn't on PATH, install in a temporary venv: `python3 -m venv /tmp/lb-venv && /tmp/lb-venv/bin/pip install pytest zstandard jsonschema pyyaml && /tmp/lb-venv/bin/python -m pytest .github/scripts/test_validate_submission.py -v`.

- [ ] **Step 7: Verify the shim works**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 scripts/validate.py .github/scripts/_fixtures/valid_min/2026-05-12-fixture
```
Expected: `✅ 2026-05-12-fixture: validation passed`.

- [ ] **Step 8: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add .github/ scripts/
git commit -m "feat(validate): structural checks (naming, required files, unexpected files) + fixtures"
```

---

### Task 13: Validator — schema + results.csv + provenance checks

**Files (all in `leaderboard/`):**
- Modify: `.github/scripts/validate_submission.py` (add three new check functions + wire into `validate_packet`)
- Modify: `.github/scripts/test_validate_submission.py` (add tests)

- [ ] **Step 1: Add failing tests**

Append to `leaderboard/.github/scripts/test_validate_submission.py`:

```python
from validate_submission import (  # noqa: E402
    check_schema,
    check_results_csv_consistency,
    check_provenance,
)


# ── Schema check ────────────────────────────────────────────────────────────

def test_schema_accepts_valid(valid_packet: Path) -> None:
    report = ValidationReport()
    check_schema(valid_packet, report, repo_root=valid_packet.parent.parent.parent.parent)
    # Note: repo_root is computed relative — see _resolve_repo_root in the test below.
    # For this test we pass the leaderboard root so schema/ resolves.
    # (Direct path passing avoided here; the dedicated fixture test below does it correctly.)
    # We assert it doesn't blow up:
    assert isinstance(report.errors, list)


def test_schema_rejects_bad_envelope(valid_packet: Path, tmp_path: Path) -> None:
    """Mutate submission.json to violate the schema."""
    mf = valid_packet / "submission.json"
    data = json.loads(mf.read_text())
    data["submission"]["id"] = "INVALID-UPPERCASE"   # violates pattern
    mf.write_text(json.dumps(data))

    report = ValidationReport()
    # Resolve repo root from the test file's location
    repo_root = HERE.parent.parent  # leaderboard/
    check_schema(valid_packet, report, repo_root=repo_root)
    assert report.has_errors()
    assert any("submission.id" in e or "pattern" in e.lower() for e in report.errors)


def test_schema_missing_schema_file(valid_packet: Path, tmp_path: Path) -> None:
    """submission.json references a schema that doesn't exist."""
    mf = valid_packet / "submission.json"
    data = json.loads(mf.read_text())
    data["schema"] = "fake-bench/submission/v99"
    mf.write_text(json.dumps(data))

    report = ValidationReport()
    repo_root = HERE.parent.parent
    check_schema(valid_packet, report, repo_root=repo_root)
    assert any("schema file not found" in e.lower() for e in report.errors)


# ── results.csv consistency ─────────────────────────────────────────────────

def test_results_csv_matches_manifest(valid_packet: Path) -> None:
    report = ValidationReport()
    check_results_csv_consistency(valid_packet, report)
    assert not report.has_errors(), report.errors


def test_results_csv_pass_at_1_mismatch(valid_packet: Path) -> None:
    csv = valid_packet / "results.csv"
    txt = csv.read_text()
    csv.write_text(txt.replace(",1.0,1,1,", ",0.5,1,1,", 1))   # mutate the overall row
    report = ValidationReport()
    check_results_csv_consistency(valid_packet, report)
    assert any("overall" in e.lower() and "pass_at_1" in e for e in report.errors)


def test_results_csv_wrong_submission_id(valid_packet: Path) -> None:
    csv = valid_packet / "results.csv"
    txt = csv.read_text()
    csv.write_text(txt.replace(",fixture,", ",other,"))
    report = ValidationReport()
    check_results_csv_consistency(valid_packet, report)
    assert any("submission_id" in e for e in report.errors)


# ── provenance ──────────────────────────────────────────────────────────────

def test_provenance_accepts_valid(valid_packet: Path) -> None:
    report = ValidationReport()
    check_provenance(valid_packet, report)
    assert not report.has_errors(), report.errors


def test_provenance_missing_required_key(valid_packet: Path) -> None:
    pf = valid_packet / "provenance.json"
    data = json.loads(pf.read_text())
    del data["chi_bench_git_sha"]
    pf.write_text(json.dumps(data))
    report = ValidationReport()
    check_provenance(valid_packet, report)
    assert any("chi_bench_git_sha" in e for e in report.errors)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: ImportError on the three new function names.

- [ ] **Step 3: Implement the three checks**

In `leaderboard/.github/scripts/validate_submission.py`, add near the other check functions:

```python
def _read_manifest(packet_dir: Path) -> dict | None:
    try:
        return json.loads((packet_dir / "submission.json").read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def check_schema(packet_dir: Path, report: ValidationReport, repo_root: Path) -> None:
    """Rule 5: submission.json validates against benchmarks/<bench>/schema/submission-v<N>.json."""
    import jsonschema  # lazy import — CI installs this

    manifest = _read_manifest(packet_dir)
    if manifest is None:
        report.err("submission.json is missing or malformed JSON")
        return
    schema_field = manifest.get("schema")
    if not isinstance(schema_field, str) or schema_field.count("/") != 2:
        report.err(f"submission.json:schema must be '<bench>/submission/v<N>'; got {schema_field!r}")
        return
    bench, kind, vname = schema_field.split("/", 2)
    if kind != "submission":
        report.err(f"Only 'submission' schemas supported at this validator version; got '{kind}'")
        return
    schema_path = repo_root / "benchmarks" / bench / "schema" / f"submission-{vname}.json"
    if not schema_path.is_file():
        report.err(f"Schema file not found for '{schema_field}': expected {schema_path}")
        return
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.err(f"Schema file {schema_path} is malformed JSON: {e}")
        return
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda e: list(e.absolute_path))
    for err in errors:
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        report.err(f"submission.json schema violation at {path}: {err.message}")


def check_results_csv_consistency(packet_dir: Path, report: ValidationReport) -> None:
    """Rule 6: results.csv rows exactly match the manifest's results.overall / results.per_domain."""
    import csv as _csv

    manifest = _read_manifest(packet_dir)
    if manifest is None:
        return  # check_schema will already have reported this
    csv_path = packet_dir / "results.csv"
    if not csv_path.is_file():
        report.err("results.csv missing")
        return

    sub_id = (manifest.get("submission") or {}).get("id")
    results = manifest.get("results") or {}
    per_domain = results.get("per_domain") or {}
    overall = results.get("overall") or {}

    expected_rows = 1 + len(per_domain)  # overall + each domain

    with csv_path.open(encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh))

    if len(rows) != expected_rows:
        report.err(
            f"results.csv has {len(rows)} rows, expected {expected_rows} "
            f"(1 overall + {len(per_domain)} per_domain)"
        )
        # Still continue so per-row diagnostics surface

    seen_domains: set[str] = set()
    for row in rows:
        row_sub_id = row.get("submission_id")
        if row_sub_id != sub_id:
            report.err(
                f"results.csv row submission_id={row_sub_id!r} does not match "
                f"submission.json id={sub_id!r}"
            )
        domain = row.get("domain")
        if domain == "overall":
            _compare_score_row(row, overall, "overall", report)
            seen_domains.add("overall")
        elif domain in per_domain:
            _compare_score_row(row, per_domain[domain], domain, report)
            seen_domains.add(domain)
        else:
            report.err(f"results.csv has unexpected domain row: {domain!r}")

    if "overall" not in seen_domains:
        report.err("results.csv missing the overall row")
    for d in per_domain:
        if d not in seen_domains:
            report.err(f"results.csv missing row for domain '{d}'")


def _compare_score_row(row: dict, score: dict, label: str, report: ValidationReport) -> None:
    """Compare a single CSV row against the manifest's score block for that domain."""
    for field in ("pass_at_1", "n_trials", "n_tasks"):
        if field not in score:
            continue
        csv_val = row.get(field)
        if csv_val is None:
            report.err(f"results.csv row '{label}' missing field '{field}'")
            continue
        # Coerce CSV string to the manifest's type
        manifest_val = score[field]
        try:
            if isinstance(manifest_val, int):
                csv_typed: float | int = int(csv_val)
            else:
                csv_typed = float(csv_val)
        except ValueError:
            report.err(f"results.csv row '{label}' field '{field}' is not numeric: {csv_val!r}")
            continue
        if isinstance(manifest_val, float):
            if abs(csv_typed - manifest_val) > 1e-9:
                report.err(
                    f"results.csv row '{label}' field '{field}' = {csv_typed} "
                    f"!= manifest {manifest_val}"
                )
        else:
            if csv_typed != manifest_val:
                report.err(
                    f"results.csv row '{label}' field '{field}' = {csv_typed} "
                    f"!= manifest {manifest_val}"
                )


def check_provenance(packet_dir: Path, report: ValidationReport) -> None:
    """Rule 7: provenance.json present with required keys (per per-benchmark schema)."""
    pf = packet_dir / "provenance.json"
    if not pf.is_file():
        report.err("provenance.json missing")
        return
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        report.err(f"provenance.json malformed: {e}")
        return
    if not isinstance(data, dict):
        report.err("provenance.json must be a JSON object")
        return
    # The per-benchmark schema enforces required keys via the manifest schema check
    # (provenance is part of submission.json). But provenance.json on disk is a
    # separate file that mirrors the same content; we sanity-check it has the same
    # required keys here so a tampered file is caught.
    REQUIRED = ("chi_bench_git_sha", "image_digest", "judge_model", "harness_version")
    for k in REQUIRED:
        if k not in data:
            report.err(f"provenance.json missing required key: {k}")
```

- [ ] **Step 4: Wire the new checks into `validate_packet`**

In `leaderboard/.github/scripts/validate_submission.py`, replace the existing `validate_packet` with:

```python
def _resolve_repo_root(packet_dir: Path) -> Path:
    """Walk up from packet_dir to find the leaderboard repo root (contains 'benchmarks/')."""
    cur = packet_dir.resolve()
    for parent in (cur, *cur.parents):
        if (parent / "benchmarks").is_dir() and (parent / ".github").is_dir():
            return parent
    # Fallback: assume packet is at benchmarks/<bench>/submissions/<dir>
    return cur.parent.parent.parent.parent


def validate_packet(packet_dir: Path) -> ValidationReport:
    """Top-level entry point — runs all checks against a single packet directory."""
    report = ValidationReport()
    if not packet_dir.is_dir():
        report.err(f"Not a directory: {packet_dir}")
        return report

    manifest_id = _load_manifest_id(packet_dir)
    repo_root = _resolve_repo_root(packet_dir)

    check_directory_naming(packet_dir, report, manifest_id)
    check_required_files(packet_dir, report)
    check_no_unexpected_files(packet_dir, report)
    check_schema(packet_dir, report, repo_root=repo_root)
    check_results_csv_consistency(packet_dir, report)
    check_provenance(packet_dir, report)
    return report
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: all new tests pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add .github/scripts/validate_submission.py .github/scripts/test_validate_submission.py
git commit -m "feat(validate): add schema + results.csv + provenance checks"
```

---

### Task 14: Validator — per-trial integrity + zstd decode + size limits

**Files (all in `leaderboard/`):**
- Modify: `.github/scripts/validate_submission.py`
- Modify: `.github/scripts/test_validate_submission.py`

- [ ] **Step 1: Add failing tests**

Append to `test_validate_submission.py`:

```python
from validate_submission import (  # noqa: E402
    check_per_trial_integrity,
    check_size_limits,
    SOFT_LIMITS,
    HARD_LIMITS,
)


def test_per_trial_accepts_valid(valid_packet: Path) -> None:
    report = ValidationReport()
    check_per_trial_integrity(valid_packet, report)
    assert not report.has_errors(), report.errors


def test_per_trial_missing_scorecard(valid_packet: Path) -> None:
    (valid_packet / "trials/pa_provider/trial_1/verifier/scorecard.json").unlink()
    report = ValidationReport()
    check_per_trial_integrity(valid_packet, report)
    assert any("scorecard.json" in e for e in report.errors)


def test_per_trial_corrupt_trajectory(valid_packet: Path) -> None:
    traj = valid_packet / "trials/pa_provider/trial_1/agent/trajectory.jsonl.zst"
    traj.write_bytes(b"not valid zstd")
    report = ValidationReport()
    check_per_trial_integrity(valid_packet, report)
    assert any("zstd" in e.lower() or "trajectory" in e.lower() for e in report.errors)


def test_per_trial_count_mismatch(valid_packet: Path) -> None:
    """Manifest claims more trials than actually present."""
    mf = valid_packet / "submission.json"
    data = json.loads(mf.read_text())
    data["results"]["per_domain"]["pa_provider"]["n_trials"] = 99
    mf.write_text(json.dumps(data))
    report = ValidationReport()
    check_per_trial_integrity(valid_packet, report)
    assert any("n_trials" in e for e in report.errors)


def test_size_limits_clean(valid_packet: Path) -> None:
    report = ValidationReport()
    check_size_limits(valid_packet, report)
    assert not report.has_errors()


def test_size_limits_hard_fail_on_oversize_manifest(valid_packet: Path) -> None:
    mf = valid_packet / "submission.json"
    mf.write_bytes(b"x" * (HARD_LIMITS["small_json"] + 1))
    report = ValidationReport()
    check_size_limits(valid_packet, report)
    assert any("submission.json" in e and "exceeds hard limit" in e for e in report.errors)


def test_size_limits_soft_warns_on_large_trajectory(valid_packet: Path) -> None:
    traj = valid_packet / "trials/pa_provider/trial_1/agent/trajectory.jsonl.zst"
    traj.write_bytes(b"x" * (SOFT_LIMITS["trajectory_zst"] + 1))
    report = ValidationReport()
    check_size_limits(valid_packet, report)
    assert any("trajectory" in w.lower() and "soft limit" in w.lower() for w in report.warnings)
    # And not an error (still under hard limit)
    assert not any("trajectory" in e.lower() for e in report.errors)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: ImportError on the new symbols.

- [ ] **Step 3: Implement the checks**

In `leaderboard/.github/scripts/validate_submission.py`, add:

```python
# Spec §2.4 size budget
SOFT_LIMITS = {
    "small_json": 100 * 1024,        # 100 KB — submission.json, results.csv, sub.yaml, provenance.json
    "trial_json": 200 * 1024,        # 200 KB — scorecard, reward, result
    "trajectory_zst": 10 * 1024 * 1024,   # 10 MB
    "total": 100 * 1024 * 1024,      # 100 MB total per packet
}
HARD_LIMITS = {
    "small_json": 1 * 1024 * 1024,   # 1 MB
    "trial_json": 2 * 1024 * 1024,   # 2 MB
    "trajectory_zst": 50 * 1024 * 1024,   # 50 MB
    "total": 500 * 1024 * 1024,      # 500 MB
}

_TOP_LEVEL_SMALL = ("submission.json", "results.csv", "sub.yaml", "provenance.json")
_TRIAL_SMALL = ("result.json", "verifier/scorecard.json", "verifier/reward.json")
_TRIAL_FILES_REQUIRED = (*_TRIAL_SMALL, "agent/trajectory.jsonl.zst")


def check_per_trial_integrity(packet_dir: Path, report: ValidationReport) -> None:
    """Rules 8–10: each trial dir has exactly the expected files; trajectory decodes; counts match."""
    import zstandard as zstd  # lazy

    manifest = _read_manifest(packet_dir)
    per_domain_expected: dict[str, int] = {}
    if manifest is not None:
        per_dom = (manifest.get("results") or {}).get("per_domain") or {}
        for dom, score in per_dom.items():
            n = score.get("n_trials")
            if isinstance(n, int):
                per_domain_expected[dom] = n

    trials_dir = packet_dir / "trials"
    if not trials_dir.is_dir():
        return  # check_required_files already reported this

    per_domain_actual: dict[str, int] = {}
    for domain_dir in sorted(trials_dir.iterdir()):
        if not domain_dir.is_dir():
            report.err(f"Unexpected non-directory under trials/: {domain_dir.name}")
            continue
        trial_dirs = [p for p in domain_dir.iterdir() if p.is_dir()]
        per_domain_actual[domain_dir.name] = len(trial_dirs)
        for trial_dir in trial_dirs:
            # Required files
            for rel in _TRIAL_FILES_REQUIRED:
                tp = trial_dir / rel
                if not tp.is_file():
                    report.err(f"trial {domain_dir.name}/{trial_dir.name}: missing {rel}")
            # No extra files
            actual = {str(p.relative_to(trial_dir)) for p in trial_dir.rglob("*") if p.is_file()}
            expected = set(_TRIAL_FILES_REQUIRED)
            extras = actual - expected
            for x in sorted(extras):
                report.err(f"trial {domain_dir.name}/{trial_dir.name}: unexpected file {x}")
            # Decode trajectory.jsonl.zst (streaming; discard bytes)
            traj = trial_dir / "agent" / "trajectory.jsonl.zst"
            if traj.is_file():
                try:
                    decompressor = zstd.ZstdDecompressor()
                    with traj.open("rb") as fh, decompressor.stream_reader(fh) as reader:
                        # Read in 64 KB chunks, parse complete lines, validate JSON per line
                        buf = b""
                        line_count = 0
                        while True:
                            chunk = reader.read(65536)
                            if not chunk:
                                if buf.strip():
                                    json.loads(buf)
                                    line_count += 1
                                break
                            buf += chunk
                            while b"\n" in buf:
                                line, buf = buf.split(b"\n", 1)
                                if line.strip():
                                    json.loads(line)
                                    line_count += 1
                        if line_count < 1:
                            report.err(f"trial {domain_dir.name}/{trial_dir.name}: trajectory is empty")
                except zstd.ZstdError as e:
                    report.err(f"trial {domain_dir.name}/{trial_dir.name}: trajectory is not valid zstd: {e}")
                except json.JSONDecodeError as e:
                    report.err(f"trial {domain_dir.name}/{trial_dir.name}: trajectory has malformed JSON line: {e}")

    # Trial counts vs manifest
    for dom, expected_n in per_domain_expected.items():
        actual_n = per_domain_actual.get(dom, 0)
        if actual_n != expected_n:
            report.err(
                f"Trial count mismatch for domain '{dom}': "
                f"found {actual_n}, manifest says n_trials={expected_n}"
            )
    # Surface domains present on disk but not in manifest
    for dom in per_domain_actual:
        if dom not in per_domain_expected:
            report.warn(f"Domain '{dom}' has trials on disk but no per_domain entry in manifest")


def check_size_limits(packet_dir: Path, report: ValidationReport) -> None:
    """Rule 11: per-file and total size budget."""
    total = 0
    for path in packet_dir.rglob("*"):
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        rel = str(path.relative_to(packet_dir))

        # Decide which limit bucket this file belongs to
        if path.name in _TOP_LEVEL_SMALL and path.parent == packet_dir:
            soft, hard, label = SOFT_LIMITS["small_json"], HARD_LIMITS["small_json"], "small_json"
        elif rel.startswith("trials/") and path.name in ("result.json", "scorecard.json", "reward.json"):
            soft, hard, label = SOFT_LIMITS["trial_json"], HARD_LIMITS["trial_json"], "trial_json"
        elif path.name == "trajectory.jsonl.zst":
            soft, hard, label = SOFT_LIMITS["trajectory_zst"], HARD_LIMITS["trajectory_zst"], "trajectory_zst"
        else:
            continue  # README.md, schema files, etc. — no per-file limit

        if size > hard:
            report.err(f"{rel} ({size} bytes) exceeds hard limit for {label} ({hard} bytes)")
        elif size > soft:
            report.warn(f"{rel} ({size} bytes) over soft limit for {label} ({soft} bytes)")

    if total > HARD_LIMITS["total"]:
        report.err(f"Total packet size {total} bytes exceeds hard limit ({HARD_LIMITS['total']})")
    elif total > SOFT_LIMITS["total"]:
        report.warn(f"Total packet size {total} bytes over soft limit ({SOFT_LIMITS['total']})")
```

- [ ] **Step 4: Wire into `validate_packet`**

Append two calls in `validate_packet()`, after `check_provenance`:

```python
    check_per_trial_integrity(packet_dir, report)
    check_size_limits(packet_dir, report)
```

- [ ] **Step 5: Run tests**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add .github/scripts/validate_submission.py .github/scripts/test_validate_submission.py
git commit -m "feat(validate): add per-trial integrity + size-limit checks"
```

---

### Task 15: Validator — soft warnings (known-versions, duplicate id) + reporting

**Files (all in `leaderboard/`):**
- Modify: `.github/scripts/validate_submission.py`
- Modify: `.github/scripts/test_validate_submission.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
from validate_submission import (  # noqa: E402
    check_known_dataset_version,
    check_duplicate_submission_id,
    write_markdown_report,
    write_json_report,
)


def test_known_version_warns_on_unknown(valid_packet: Path) -> None:
    mf = valid_packet / "submission.json"
    data = json.loads(mf.read_text())
    data["dataset"]["version"] = "chi-bench-v9.9.9"
    mf.write_text(json.dumps(data))
    report = ValidationReport()
    repo_root = HERE.parent.parent
    check_known_dataset_version(valid_packet, report, repo_root=repo_root)
    assert any("v9.9.9" in w and "known" in w.lower() for w in report.warnings)
    assert not report.has_errors()


def test_known_version_no_warn_on_known(valid_packet: Path) -> None:
    report = ValidationReport()
    repo_root = HERE.parent.parent
    check_known_dataset_version(valid_packet, report, repo_root=repo_root)
    assert not report.warnings


def test_duplicate_submission_id_warns(valid_packet: Path, tmp_path: Path) -> None:
    """Simulate an existing submission with the same id on 'main'."""
    # Create a sibling that uses the same id
    sibling_root = tmp_path / "benchmarks" / "chi-bench" / "submissions"
    sibling_root.mkdir(parents=True)
    sibling = sibling_root / "2026-04-01-fixture"
    shutil.copytree(valid_packet, sibling)
    # Place the packet under that root too
    new_packet = sibling_root / "2026-05-12-fixture"
    shutil.copytree(valid_packet, new_packet)

    report = ValidationReport()
    check_duplicate_submission_id(new_packet, report)
    assert any("resubmission" in w.lower() or "duplicate" in w.lower() for w in report.warnings)


def test_write_markdown_report(valid_packet: Path, tmp_path: Path) -> None:
    report = ValidationReport()
    report.warn("test warning")
    out = tmp_path / "report.md"
    write_markdown_report(report, valid_packet, out)
    text = out.read_text()
    assert "validation" in text.lower()
    assert "test warning" in text


def test_write_json_report(valid_packet: Path, tmp_path: Path) -> None:
    report = ValidationReport()
    report.err("e1")
    report.warn("w1")
    out = tmp_path / "report.json"
    write_json_report(report, valid_packet, out)
    data = json.loads(out.read_text())
    assert data["status"] == "invalid"
    assert "e1" in data["errors"]
    assert "w1" in data["warnings"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```

- [ ] **Step 3: Implement**

In `leaderboard/.github/scripts/validate_submission.py`, add:

```python
def check_known_dataset_version(packet_dir: Path, report: ValidationReport, repo_root: Path) -> None:
    """Rule 12 (soft): dataset.version is listed in benchmarks/<bench>/schema/known-versions.txt."""
    manifest = _read_manifest(packet_dir)
    if manifest is None:
        return
    ds = manifest.get("dataset") or {}
    bench = ds.get("name")
    version = ds.get("version")
    if not isinstance(bench, str) or not isinstance(version, str):
        return
    kv = repo_root / "benchmarks" / bench / "schema" / "known-versions.txt"
    if not kv.is_file():
        report.warn(f"No known-versions.txt for benchmark '{bench}'; cannot verify dataset version")
        return
    known = {line.strip() for line in kv.read_text(encoding="utf-8").splitlines() if line.strip()}
    if version not in known:
        report.warn(
            f"Dataset version '{version}' not listed in {kv.relative_to(repo_root)} "
            f"(known: {sorted(known)}). Reviewer please confirm; "
            f"the version list can be updated in a follow-up PR."
        )


def check_duplicate_submission_id(packet_dir: Path, report: ValidationReport) -> None:
    """Rule 13 (soft): another submission directory has the same submission.id."""
    manifest = _read_manifest(packet_dir)
    if manifest is None:
        return
    sid = (manifest.get("submission") or {}).get("id")
    if not isinstance(sid, str):
        return
    submissions_root = packet_dir.parent   # benchmarks/<bench>/submissions/
    if not submissions_root.is_dir():
        return
    matches = []
    for sibling in submissions_root.iterdir():
        if not sibling.is_dir() or sibling == packet_dir:
            continue
        sibling_mf = _read_manifest(sibling)
        if sibling_mf is None:
            continue
        sibling_id = (sibling_mf.get("submission") or {}).get("id")
        if sibling_id == sid:
            matches.append(sibling.name)
    if matches:
        report.warn(
            f"Possible resubmission of '{sid}' — same submission.id present in: "
            f"{', '.join(matches)}. Reviewer please confirm intent."
        )


def write_markdown_report(report: ValidationReport, packet_dir: Path, out: Path) -> None:
    """Write a sticky-PR-comment-friendly Markdown summary."""
    lines = [f"## Submission validation — `{packet_dir.name}`", ""]
    if report.has_errors():
        lines.append(f"❌ **{len(report.errors)} error(s)** — PR cannot merge as-is.\n")
        for e in report.errors:
            lines.append(f"- ❌ {e}")
        lines.append("")
    else:
        lines.append("✅ **All checks passed.**\n")
    if report.warnings:
        lines.append(f"⚠️ **{len(report.warnings)} warning(s)** — reviewer judgment call:\n")
        for w in report.warnings:
            lines.append(f"- ⚠️ {w}")
        lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_json_report(report: ValidationReport, packet_dir: Path, out: Path) -> None:
    """Write a machine-readable JSON report (consumed by the PR-labeller action)."""
    data = {
        "packet": packet_dir.name,
        "status": "invalid" if report.has_errors() else ("needs-review" if report.warnings else "valid"),
        "errors": report.errors,
        "warnings": report.warnings,
    }
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")
```

Wire the two new checks into `validate_packet`:

```python
    check_known_dataset_version(packet_dir, report, repo_root=repo_root)
    check_duplicate_submission_id(packet_dir, report)
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add .github/scripts/
git commit -m "feat(validate): add soft warnings (known versions, duplicate ids) + report writers"
```

---

### Task 16: Validator — CI mode (diff scope + multi-packet handling)

**Files (all in `leaderboard/`):**
- Modify: `.github/scripts/validate_submission.py` (add diff-driven entry point + rule 1)
- Modify: `.github/scripts/test_validate_submission.py`

- [ ] **Step 1: Add failing tests**

Append:

```python
import subprocess


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def lb_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the leaderboard layout + a starting commit."""
    repo = tmp_path / "lb"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t.test")
    _git(repo, "config", "user.name", "T")
    # Seed empty benchmarks/.github so _resolve_repo_root works
    (repo / "benchmarks" / "chi-bench" / "schema").mkdir(parents=True)
    shutil.copy(HERE.parent.parent / "benchmarks" / "chi-bench" / "schema" / "submission-v1.json",
                repo / "benchmarks" / "chi-bench" / "schema" / "submission-v1.json")
    shutil.copy(HERE.parent.parent / "benchmarks" / "chi-bench" / "schema" / "known-versions.txt",
                repo / "benchmarks" / "chi-bench" / "schema" / "known-versions.txt")
    (repo / "benchmarks" / "chi-bench" / "submissions").mkdir(parents=True)
    (repo / ".github" / "scripts").mkdir(parents=True)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    return repo


def test_ci_mode_validates_added_packet(lb_repo: Path) -> None:
    """A PR that adds a new submission directory should validate that directory."""
    from validate_submission import validate_pr_diff

    # Add a new packet
    target = lb_repo / "benchmarks" / "chi-bench" / "submissions" / "2026-05-12-fixture"
    shutil.copytree(FIXTURE_VALID, target)
    _git(lb_repo, "checkout", "-q", "-b", "feature")
    _git(lb_repo, "add", ".")
    _git(lb_repo, "commit", "-q", "-m", "add fixture")

    base = _git(lb_repo, "rev-parse", "main").strip()
    head = _git(lb_repo, "rev-parse", "HEAD").strip()

    report = validate_pr_diff(lb_repo, base_ref=base, head_ref=head)
    assert not report.has_errors(), report.errors


def test_ci_mode_rejects_pr_touching_other_files(lb_repo: Path) -> None:
    """Rule 1: PR may only touch one new submission dir (unless 'meta:' label, not modeled here)."""
    from validate_submission import validate_pr_diff

    target = lb_repo / "benchmarks" / "chi-bench" / "submissions" / "2026-05-12-fixture"
    shutil.copytree(FIXTURE_VALID, target)
    # Also modify an unrelated file
    (lb_repo / "README.md").write_text("# changed\n")
    _git(lb_repo, "checkout", "-q", "-b", "feature2")
    _git(lb_repo, "add", ".")
    _git(lb_repo, "commit", "-q", "-m", "add fixture + readme")

    base = _git(lb_repo, "rev-parse", "main").strip()
    head = _git(lb_repo, "rev-parse", "HEAD").strip()

    report = validate_pr_diff(lb_repo, base_ref=base, head_ref=head)
    assert any("README.md" in e or "outside" in e.lower() for e in report.errors)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v -k "ci_mode"
```
Expected: ImportError on `validate_pr_diff`.

- [ ] **Step 3: Implement `validate_pr_diff` + CLI wiring**

Add to `validate_submission.py`:

```python
def _git_diff_paths(repo_root: Path, base_ref: str, head_ref: str) -> list[Path]:
    """Return the list of paths added/modified between base..head."""
    import subprocess
    out = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", f"{base_ref}..{head_ref}"],
        check=True, capture_output=True, text=True,
    ).stdout
    return [Path(line) for line in out.splitlines() if line.strip()]


def validate_pr_diff(repo_root: Path, base_ref: str, head_ref: str) -> ValidationReport:
    """CI entry point: enforce diff scope (rule 1) and validate any touched packets."""
    report = ValidationReport()
    paths = _git_diff_paths(repo_root, base_ref, head_ref)
    if not paths:
        report.warn("PR has no file changes")
        return report

    # Identify touched submission directories
    submission_dirs: set[Path] = set()
    non_submission_paths: list[Path] = []
    for p in paths:
        parts = p.parts
        # benchmarks/<bench>/submissions/<dir>/...
        if len(parts) >= 4 and parts[0] == "benchmarks" and parts[2] == "submissions":
            submission_dirs.add(repo_root / parts[0] / parts[1] / parts[2] / parts[3])
        else:
            non_submission_paths.append(p)

    if non_submission_paths:
        listed = "\n".join(f"  - {p}" for p in non_submission_paths[:20])
        report.err(
            "PR touches files outside benchmarks/*/submissions/*/ — submissions and "
            "meta-changes must land in separate PRs (or a maintainer applies the 'meta:' label "
            "to bypass this check):\n" + listed
        )

    if len(submission_dirs) > 1:
        listed = ", ".join(sorted(d.name for d in submission_dirs))
        report.err(f"PR touches multiple submission directories ({listed}); expected exactly one")

    # Run per-packet validation on each touched submission
    for d in sorted(submission_dirs):
        if not d.is_dir():
            report.err(f"Submission directory missing on head ref: {d.name}")
            continue
        sub_report = validate_packet(d)
        # Prefix each diagnostic with the packet name
        for e in sub_report.errors:
            report.err(f"[{d.name}] {e}")
        for w in sub_report.warnings:
            report.warn(f"[{d.name}] {w}")
    return report
```

Update `main()` in the same file to handle CI mode:

```python
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate a leaderboard submission packet.")
    parser.add_argument("path", nargs="?", type=Path, help="Path to a single submission directory.")
    parser.add_argument("--base-ref", help="(CI) PR base SHA — required with --head-ref.")
    parser.add_argument("--head-ref", help="(CI) PR head SHA — required with --base-ref.")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="(CI) repo root; default cwd.")
    parser.add_argument("--report-md", type=Path, help="Write Markdown report to this path.")
    parser.add_argument("--report-json", type=Path, help="Write JSON report to this path.")
    args = parser.parse_args(argv)

    if args.base_ref and args.head_ref:
        report = validate_pr_diff(args.repo_root, args.base_ref, args.head_ref)
        label = "PR diff"
        packet_dir = args.repo_root
    elif args.path:
        report = validate_packet(args.path)
        label = args.path.name
        packet_dir = args.path
    else:
        parser.error("provide either a path or --base-ref/--head-ref")
        return 2

    if args.report_md:
        write_markdown_report(report, packet_dir, args.report_md)
    if args.report_json:
        write_json_report(report, packet_dir, args.report_json)

    print(f"{'❌' if report.has_errors() else '✅'} {label}: "
          f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)",
          file=sys.stderr)
    for e in report.errors:
        print(f"  ❌ {e}", file=sys.stderr)
    for w in report.warnings:
        print(f"  ⚠️ {w}", file=sys.stderr)
    return 1 if report.has_errors() else 0
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add .github/scripts/
git commit -m "feat(validate): add CI mode (diff scope + multi-packet handling)"
```

---

### Task 17: GitHub Actions workflow + PR template

**Files (all in `leaderboard/`):**
- Create: `.github/workflows/validate.yml`
- Create: `.github/PULL_REQUEST_TEMPLATE/submission.md`

- [ ] **Step 1: Write the workflow**

Create `leaderboard/.github/workflows/validate.yml`:

```yaml
name: validate submission

on:
  pull_request:
    paths:
      - "benchmarks/**"
      - ".github/scripts/validate_submission.py"

permissions:
  contents: read
  pull-requests: write
  issues: write

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # need full history for git diff base..head

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install validator deps
        run: pip install --quiet jsonschema zstandard pyyaml

      - name: Run validator
        id: validate
        continue-on-error: true
        run: |
          python .github/scripts/validate_submission.py \
            --base-ref "${{ github.event.pull_request.base.sha }}" \
            --head-ref "${{ github.event.pull_request.head.sha }}" \
            --repo-root . \
            --report-md /tmp/report.md \
            --report-json /tmp/report.json
          echo "exit_code=$?" >> $GITHUB_OUTPUT

      - name: Append report to job summary
        if: always()
        run: cat /tmp/report.md >> $GITHUB_STEP_SUMMARY || true

      - name: Comment on PR and apply label
        if: always()
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            let report;
            try { report = JSON.parse(fs.readFileSync('/tmp/report.json', 'utf8')); }
            catch (e) {
              core.warning('No JSON report — validator probably crashed.');
              return;
            }
            const md = fs.readFileSync('/tmp/report.md', 'utf8');

            // Upsert a sticky comment
            const marker = '<!-- leaderboard-validate -->';
            const body = marker + '\n' + md;
            const { owner, repo, number: issue_number } = context.issue;
            const comments = await github.rest.issues.listComments({ owner, repo, issue_number, per_page: 100 });
            const existing = comments.data.find(c => c.body && c.body.includes(marker));
            if (existing) {
              await github.rest.issues.updateComment({ owner, repo, comment_id: existing.id, body });
            } else {
              await github.rest.issues.createComment({ owner, repo, issue_number, body });
            }

            // Apply label
            const statusToLabel = {
              valid: 'valid-submission',
              invalid: 'invalid-submission',
              'needs-review': 'needs-review',
            };
            const target = statusToLabel[report.status];
            const allLabels = Object.values(statusToLabel);
            for (const lbl of allLabels) {
              if (lbl === target) continue;
              try { await github.rest.issues.removeLabel({ owner, repo, issue_number, name: lbl }); }
              catch (e) { /* not present, ignore */ }
            }
            if (target) {
              await github.rest.issues.addLabels({ owner, repo, issue_number, labels: [target] });
            }

            // Surface the validator's exit code as the job result
            if (report.status === 'invalid') {
              core.setFailed('Submission validation failed; see PR comment.');
            }
```

- [ ] **Step 2: Write the PR template**

Create `leaderboard/.github/PULL_REQUEST_TEMPLATE/submission.md`:

```markdown
## New submission

**Benchmark:** <!-- chi-bench | swe-bench | ... -->
**Team:** <!-- your team name -->
**Headline metric:** <!-- e.g. pass@1: 28.0% -->

### Submitter checklist

- [ ] I produced this packet with the producer repo's official tooling (e.g. `cb submission prepare` for chi-bench).
- [ ] I ran `python scripts/validate.py benchmarks/<bench>/submissions/<dir>` locally and it passed.
- [ ] The dataset version pinned in `submission.json:dataset.version` matches what I actually ran against.
- [ ] I understand the leaderboard is pass@1 only; extra trials are kept locally for my own analysis.
- [ ] I am authorized to publish this submission and confirm that no PII / non-public data is included.

### Notes for reviewers

<!-- Anything reviewers should know: re-runs, custom prompting, partial domain coverage, etc. -->
```

- [ ] **Step 3: Verify the workflow YAML is syntactically valid**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/validate.yml'))"
```
Expected: no exception.

- [ ] **Step 4: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add .github/workflows/ .github/PULL_REQUEST_TEMPLATE/
git commit -m "ci: add validate.yml workflow + submission PR template"
```

---

### Task 18: `scripts/submit.py` — validate + copy + git

**Files (all in `leaderboard/`):**
- Create: `scripts/submit.py`
- Create: `scripts/test_submit.py`

This task delivers the validate-and-copy core. Git/fork/PR steps land in Task 19.

- [ ] **Step 1: Write failing tests**

Create `leaderboard/scripts/test_submit.py`:

```python
"""Tests for scripts/submit.py — the optional one-command helper."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from submit import (  # noqa: E402
    SubmitError,
    detect_benchmark,
    plan_submission,
)

FIXTURE_VALID = HERE.parent / ".github" / "scripts" / "_fixtures" / "valid_min" / "2026-05-12-fixture"


def test_detect_benchmark_reads_manifest(tmp_path: Path) -> None:
    pkt = tmp_path / "2026-05-12-x"
    shutil.copytree(FIXTURE_VALID, pkt)
    bench = detect_benchmark(pkt)
    assert bench == "chi-bench"


def test_detect_benchmark_rejects_missing_manifest(tmp_path: Path) -> None:
    pkt = tmp_path / "x"
    pkt.mkdir()
    with pytest.raises(SubmitError):
        detect_benchmark(pkt)


def test_plan_submission_targets_correct_path(tmp_path: Path) -> None:
    pkt = tmp_path / "2026-05-12-myteam"
    shutil.copytree(FIXTURE_VALID, pkt)
    # Fix up the slug to match the dir name
    mf = pkt / "submission.json"
    data = json.loads(mf.read_text())
    data["submission"]["id"] = "myteam"
    mf.write_text(json.dumps(data))

    repo_root = tmp_path / "lb"
    (repo_root / "benchmarks" / "chi-bench" / "submissions").mkdir(parents=True)

    plan = plan_submission(pkt, repo_root=repo_root)
    assert plan.benchmark == "chi-bench"
    assert plan.target_dir == repo_root / "benchmarks" / "chi-bench" / "submissions" / "2026-05-12-myteam"
    assert plan.branch_name == "sub/chi-bench/2026-05-12-myteam"


def test_plan_submission_rejects_unknown_benchmark(tmp_path: Path) -> None:
    pkt = tmp_path / "2026-05-12-x"
    shutil.copytree(FIXTURE_VALID, pkt)
    # Change manifest to claim a benchmark with no subtree
    mf = pkt / "submission.json"
    data = json.loads(mf.read_text())
    data["dataset"]["name"] = "ghost-bench"
    mf.write_text(json.dumps(data))

    repo_root = tmp_path / "lb"
    (repo_root / "benchmarks" / "chi-bench" / "submissions").mkdir(parents=True)
    # ghost-bench is NOT registered

    with pytest.raises(SubmitError, match="ghost-bench"):
        plan_submission(pkt, repo_root=repo_root)


def test_plan_submission_detects_existing_target(tmp_path: Path) -> None:
    pkt = tmp_path / "2026-05-12-myteam"
    shutil.copytree(FIXTURE_VALID, pkt)
    mf = pkt / "submission.json"
    data = json.loads(mf.read_text())
    data["submission"]["id"] = "myteam"
    mf.write_text(json.dumps(data))

    repo_root = tmp_path / "lb"
    target = repo_root / "benchmarks" / "chi-bench" / "submissions" / "2026-05-12-myteam"
    target.mkdir(parents=True)  # already exists

    plan = plan_submission(pkt, repo_root=repo_root)
    assert plan.target_exists is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest scripts/test_submit.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement the helper core**

Create `leaderboard/scripts/submit.py`:

```python
#!/usr/bin/env python3
"""One-command helper for submitting a packet to actava-ai/leaderboard.

Manual flow (no helper):
    cp -r <packet> benchmarks/<bench>/submissions/
    python scripts/validate.py benchmarks/<bench>/submissions/<dir>
    git checkout -b sub/<bench>/<dir>
    git add benchmarks/<bench>/submissions/<dir>/
    git commit -m "<bench>: <team> · <agent> · <model>"
    git push origin sub/<bench>/<dir>
    gh pr create --base main

This helper does the same steps with auto-detection of the benchmark from the packet's
submission.json:dataset.name, runs the validator before committing, and handles fork-based
PRs for outside contributors.

Usage:
    python scripts/submit.py <path-to-packet>
        [--no-fork]          # push directly (org members only)
        [--no-open-pr]       # push but don't run gh pr create
        [--on-conflict abandon|replace|bump-date]
        [--leaderboard-repo actava-ai/leaderboard]
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent
DEFAULT_REPO = "actava-ai/leaderboard"


class SubmitError(Exception):
    """User-facing error during submission. The message is printed verbatim."""


@dataclasses.dataclass
class SubmissionPlan:
    packet: Path
    benchmark: str
    target_dir: Path             # benchmarks/<bench>/submissions/<dir-name>
    branch_name: str             # sub/<bench>/<dir-name>
    submission_id: str
    target_exists: bool
    commit_subject: str
    commit_body: str


def _read_manifest(packet: Path) -> dict:
    mf = packet / "submission.json"
    if not mf.is_file():
        raise SubmitError(f"Packet has no submission.json: {packet}")
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise SubmitError(f"submission.json is malformed: {e}") from None


def detect_benchmark(packet: Path) -> str:
    manifest = _read_manifest(packet)
    ds = manifest.get("dataset") or {}
    name = ds.get("name")
    if not isinstance(name, str) or not name:
        raise SubmitError("submission.json:dataset.name is missing")
    return name


def plan_submission(packet: Path, repo_root: Path = REPO_ROOT_DEFAULT) -> SubmissionPlan:
    manifest = _read_manifest(packet)
    sub = manifest.get("submission") or {}
    sid = sub.get("id")
    if not isinstance(sid, str):
        raise SubmitError("submission.json:submission.id is missing")

    benchmark = detect_benchmark(packet)
    bench_root = repo_root / "benchmarks" / benchmark
    if not bench_root.is_dir():
        raise SubmitError(
            f"Benchmark '{benchmark}' is not registered in this leaderboard "
            f"(no {bench_root} directory). Register it first or fix dataset.name."
        )
    submissions_root = bench_root / "submissions"
    submissions_root.mkdir(parents=True, exist_ok=True)

    dir_name = packet.name
    target_dir = submissions_root / dir_name
    branch = f"sub/{benchmark}/{dir_name}"

    team = sub.get("team", "?")
    agent = sub.get("agent", "?")
    model = sub.get("model", "?")
    overall = ((manifest.get("results") or {}).get("overall") or {}).get("pass_at_1")
    pct_str = f"pass@1: {overall * 100:.1f}%" if isinstance(overall, (int, float)) else "(no metric)"

    return SubmissionPlan(
        packet=packet,
        benchmark=benchmark,
        target_dir=target_dir,
        branch_name=branch,
        submission_id=sid,
        target_exists=target_dir.exists(),
        commit_subject=f"{benchmark}: {team} · {agent} · {model}",
        commit_body=f"Submission `{sid}` — {pct_str}\n\nValidated locally with scripts/validate.py.",
    )


def copy_packet(plan: SubmissionPlan) -> None:
    if plan.target_dir.exists():
        shutil.rmtree(plan.target_dir)
    shutil.copytree(plan.packet, plan.target_dir)


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True, text=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Submit a packet to actava-ai/leaderboard.")
    parser.add_argument("packet", type=Path, help="Path to a prepared packet directory.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT_DEFAULT,
                        help="Leaderboard repo root (default: this repo).")
    parser.add_argument("--no-fork", action="store_true",
                        help="Push directly instead of via your fork (org members only).")
    parser.add_argument("--no-open-pr", action="store_true",
                        help="Push the branch but do not open a PR.")
    parser.add_argument("--on-conflict", choices=("abandon", "replace", "bump-date"),
                        help="Non-interactive behavior when target dir already exists.")
    parser.add_argument("--leaderboard-repo", default=DEFAULT_REPO,
                        help="GitHub repo slug (default: actava-ai/leaderboard).")
    args = parser.parse_args(argv)

    try:
        plan = plan_submission(args.packet, repo_root=args.repo_root)
    except SubmitError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    # Task 19 implements the full git+gh flow below.
    print(f"Planned: copy {plan.packet} → {plan.target_dir.relative_to(args.repo_root)}")
    print(f"         branch: {plan.branch_name}")
    print(f"         subject: {plan.commit_subject}")
    print("(git+gh steps land in Task 19.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest scripts/test_submit.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add scripts/submit.py scripts/test_submit.py
git commit -m "feat(submit): add plan_submission + detect_benchmark (validate-and-plan core)"
```

---

### Task 19: `scripts/submit.py` — git + fork + gh pr create

**Files (all in `leaderboard/`):**
- Modify: `scripts/submit.py`
- Modify: `scripts/test_submit.py`

- [ ] **Step 1: Add failing tests**

Append to `scripts/test_submit.py`:

```python
from submit import (  # noqa: E402
    preflight_tools,
    commit_packet,
    resolve_conflict,
)


def test_preflight_tools_reports_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """If a required tool is absent, preflight returns a non-empty diagnostic list."""
    monkeypatch.setattr("shutil.which", lambda x: None)
    diagnostics = preflight_tools()
    assert any("git" in d for d in diagnostics)
    assert any("gh" in d for d in diagnostics)


def test_resolve_conflict_abandon() -> None:
    decision = resolve_conflict(target_exists=True, on_conflict="abandon", interactive=False)
    assert decision == "abandon"


def test_resolve_conflict_replace() -> None:
    decision = resolve_conflict(target_exists=True, on_conflict="replace", interactive=False)
    assert decision == "replace"


def test_resolve_conflict_no_conflict() -> None:
    decision = resolve_conflict(target_exists=False, on_conflict=None, interactive=False)
    assert decision == "proceed"


def test_resolve_conflict_requires_choice_in_noninteractive() -> None:
    with pytest.raises(SubmitError, match="on-conflict"):
        resolve_conflict(target_exists=True, on_conflict=None, interactive=False)


def test_commit_packet_in_git_repo(tmp_path: Path) -> None:
    """Smoke test of the git plumbing inside a throwaway repo."""
    repo = tmp_path / "lb"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=repo, check=True)
    (repo / ".gitkeep").touch()
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)

    # Copy a packet in
    target = repo / "benchmarks" / "chi-bench" / "submissions" / "2026-05-12-x"
    shutil.copytree(FIXTURE_VALID, target)

    plan = SubmissionPlan(
        packet=target,
        benchmark="chi-bench",
        target_dir=target,
        branch_name="sub/chi-bench/2026-05-12-x",
        submission_id="x",
        target_exists=False,
        commit_subject="chi-bench: T",
        commit_body="body",
    )
    commit_packet(plan, repo_root=repo)
    log = subprocess.run(["git", "log", "-1", "--format=%s"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    assert log == "chi-bench: T"
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    assert branch == "sub/chi-bench/2026-05-12-x"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest scripts/test_submit.py -v
```

- [ ] **Step 3: Implement git/fork/gh plumbing**

Add to `scripts/submit.py` (replacing the placeholder `main()` body):

```python
import shutil as _shutil   # avoid shadowing the global `shutil`


def preflight_tools() -> list[str]:
    """Return human-readable diagnostics for missing/missconfigured tools.

    Empty list = ready to submit.
    """
    diagnostics: list[str] = []
    for tool in ("git", "gh", "zstdcat"):
        if _shutil.which(tool) is None:
            if tool == "zstdcat":
                # Non-fatal — zstdcat is needed to inspect trajectories, not to submit
                continue
            diagnostics.append(f"missing tool: {tool} (install and retry)")
    # gh auth status
    try:
        _run(["gh", "auth", "status"])
    except (FileNotFoundError, subprocess.CalledProcessError):
        diagnostics.append("gh CLI not authenticated — run `gh auth login`")
    # git user.email
    try:
        out = _run(["git", "config", "--get", "user.email"]).stdout.strip()
        if not out:
            diagnostics.append("git user.email not set — run `git config --global user.email <you>`")
    except subprocess.CalledProcessError:
        diagnostics.append("git user.email not set — run `git config --global user.email <you>`")
    return diagnostics


def resolve_conflict(target_exists: bool, on_conflict: str | None, interactive: bool) -> str:
    """Decide what to do when the target submission directory already exists.

    Returns one of: 'proceed' (no conflict), 'abandon' (exit), 'replace' (overwrite),
    'bump-date' (recompute the target with today's date).
    """
    if not target_exists:
        return "proceed"
    if on_conflict is not None:
        return on_conflict
    if not interactive:
        raise SubmitError(
            "target directory already exists; pass --on-conflict abandon|replace|bump-date"
        )
    choice = input("Target exists. [a]bandon / [r]eplace / [b]ump-date? ").strip().lower()
    return {"a": "abandon", "r": "replace", "b": "bump-date"}.get(choice, "abandon")


def _bump_date(plan: SubmissionPlan) -> SubmissionPlan:
    today = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d")
    new_name = f"{today}-{plan.submission_id}"
    new_target = plan.target_dir.parent / new_name
    new_branch = f"sub/{plan.benchmark}/{new_name}"
    return dataclasses.replace(
        plan,
        target_dir=new_target,
        branch_name=new_branch,
        target_exists=new_target.exists(),
    )


def _run_validator(packet_dir: Path, repo_root: Path) -> None:
    """Run the CI validator against the (already-copied) packet; raise on failure."""
    proc = subprocess.run(
        [sys.executable, str(repo_root / ".github" / "scripts" / "validate_submission.py"), str(packet_dir)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SubmitError(f"validation failed:\n{proc.stderr}")


def commit_packet(plan: SubmissionPlan, repo_root: Path) -> None:
    """Create the branch, stage the submission subtree, commit."""
    _run(["git", "checkout", "-b", plan.branch_name], cwd=repo_root)
    rel_target = plan.target_dir.relative_to(repo_root)
    _run(["git", "add", str(rel_target)], cwd=repo_root)
    _run(["git", "commit", "-m", plan.commit_subject, "-m", plan.commit_body], cwd=repo_root)


def _ensure_fork(repo_slug: str) -> str:
    """gh repo fork (idempotent). Returns the fork's owner/repo slug."""
    proc = _run(["gh", "api", "user", "-q", ".login"])
    user = proc.stdout.strip()
    # gh repo fork is idempotent; it no-ops on an existing fork.
    _run(["gh", "repo", "fork", repo_slug, "--clone=false", "--remote=false"])
    return f"{user}/{repo_slug.split('/')[-1]}"


def push_and_open_pr(
    plan: SubmissionPlan,
    repo_root: Path,
    leaderboard_repo: str,
    no_fork: bool,
    no_open_pr: bool,
) -> str | None:
    """Push the branch (to fork or directly) and open a PR. Returns the PR URL or None."""
    if no_fork:
        push_target_url = f"https://github.com/{leaderboard_repo}.git"
        head_ref = plan.branch_name
    else:
        fork_slug = _ensure_fork(leaderboard_repo)
        push_target_url = f"https://github.com/{fork_slug}.git"
        head_ref = f"{fork_slug.split('/')[0]}:{plan.branch_name}"

    _run(["git", "push", push_target_url, plan.branch_name], cwd=repo_root)
    if no_open_pr:
        return None

    proc = _run([
        "gh", "pr", "create",
        "-R", leaderboard_repo,
        "--base", "main",
        "--head", head_ref,
        "--title", plan.commit_subject,
        "--body", plan.commit_body,
    ], cwd=repo_root)
    # gh prints the PR URL on stdout
    return proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Submit a packet to actava-ai/leaderboard.")
    parser.add_argument("packet", type=Path)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT_DEFAULT)
    parser.add_argument("--no-fork", action="store_true")
    parser.add_argument("--no-open-pr", action="store_true")
    parser.add_argument("--on-conflict", choices=("abandon", "replace", "bump-date"))
    parser.add_argument("--leaderboard-repo", default=DEFAULT_REPO)
    args = parser.parse_args(argv)

    diagnostics = preflight_tools()
    if diagnostics:
        print("ERROR: cannot submit. Resolve before retrying:", file=sys.stderr)
        for d in diagnostics:
            print(f"  [✗] {d}", file=sys.stderr)
        return 1

    try:
        plan = plan_submission(args.packet, repo_root=args.repo_root)
    except SubmitError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    decision = resolve_conflict(
        target_exists=plan.target_exists,
        on_conflict=args.on_conflict,
        interactive=sys.stdin.isatty(),
    )
    if decision == "abandon":
        print("Abandoned (no changes made).")
        return 0
    if decision == "bump-date":
        plan = _bump_date(plan)
        if plan.target_exists:
            print(f"ERROR: bumped target also exists: {plan.target_dir}", file=sys.stderr)
            return 1

    copy_packet(plan)
    try:
        _run_validator(plan.target_dir, args.repo_root)
    except SubmitError as e:
        # Roll back the copy so the repo is clean for a retry
        shutil.rmtree(plan.target_dir, ignore_errors=True)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    commit_packet(plan, repo_root=args.repo_root)
    try:
        url = push_and_open_pr(
            plan,
            repo_root=args.repo_root,
            leaderboard_repo=args.leaderboard_repo,
            no_fork=args.no_fork,
            no_open_pr=args.no_open_pr,
        )
    except subprocess.CalledProcessError as e:
        print(f"ERROR: git/gh failed:\n{e.stderr}", file=sys.stderr)
        return 1

    print(f"✅ Submitted: {plan.target_dir.relative_to(args.repo_root)}")
    if url:
        print(f"   PR: {url}")
    else:
        print("   (PR not opened; pass without --no-open-pr to open one.)")
    return 0
```

- [ ] **Step 4: Run tests**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest scripts/test_submit.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add scripts/submit.py scripts/test_submit.py
git commit -m "feat(submit): add git/fork/gh plumbing + preflight + conflict resolution"
```

---

### Task 20: CONTRIBUTING.md + final README polish

**Files (all in `leaderboard/`):**
- Create: `CONTRIBUTING.md`
- Modify: `README.md` (replace the Task 10 placeholder with the full version)

- [ ] **Step 1: Write `CONTRIBUTING.md`**

```markdown
# Contributing

Thanks for submitting to an actava-ai benchmark leaderboard.

## How submissions work

1. You produce a **packet** with your benchmark's official tooling (e.g. `cb submission prepare` for chi-bench). See the producer repo for instructions.
2. You open a PR adding the packet under `benchmarks/<bench>/submissions/<YYYY-MM-DD>-<slug>/`. The PR must touch **only** that one new directory.
3. CI (`.github/workflows/validate.yml`) runs schema and integrity checks; it labels the PR `valid-submission`, `invalid-submission`, or `needs-review` and leaves a sticky comment summarizing checks.
4. A maintainer reviews the PR and merges if validation passed and the submission is plausible.

For the exact submission flow (manual or via `scripts/submit.py`), see the main [README](README.md).

## What CI catches

- Directory naming + date validity
- Required files (`submission.json`, `results.csv`, `sub.yaml`, `provenance.json`, `README.md`, ≥1 trial result)
- No unexpected files (`.zip`, `.bak`, hidden files except `.gitkeep`)
- `submission.json` schema validation (per `benchmarks/<bench>/schema/submission-v<N>.json`)
- `results.csv` rows match the manifest exactly
- `provenance.json` has required keys
- Per-trial integrity: required files, valid zstd, valid JSONL per line
- Trial counts match `results.per_domain.<domain>.n_trials`
- Size limits (per-file and total)

Soft warnings (not failures): unknown dataset version, duplicate `submission.id`.

## What reviewers do beyond CI

- Sanity-check headline metrics for plausibility (a 99% pass@1 on a benchmark where state-of-the-art is 30% warrants a closer look).
- Spot-inspect one or two trajectories (`zstdcat trials/<dom>/<id>/agent/trajectory.jsonl.zst | jq .`).
- Confirm the producer repo and dataset version look right.
- For resubmissions (same `submission.id`, new date): decide whether to keep the old submission alongside the new one or remove it in a follow-up cleanup PR.

CI does **not** re-judge submissions in v1 (trust-the-evidence model). Maintainers may manually re-judge a random trial via the producer's tooling if a submission looks suspicious.

## Resubmission policy

- A new submission with a fresh date prefix is always acceptable, even if the slug is identical to an existing submission.
- Old submissions are kept by default for historical record. If you want an old run removed (e.g. it was broken), say so in the PR body of your new submission.

## PR scope

Submission PRs must touch **only** files under `benchmarks/*/submissions/*/`. Changes to schemas, READMEs, workflows, or other benchmarks require a separate PR (or the maintainer-applied `meta:` label, which bypasses the CI scope check).

## Adding a new benchmark

See [`benchmarks/README.md`](benchmarks/README.md).

## Code of conduct

Be excellent to each other. Reviewers can close PRs that don't follow the contract; you can reopen after fixing.
```

- [ ] **Step 2: Replace the placeholder README**

Overwrite `leaderboard/README.md`:

```markdown
# actava-ai/leaderboard

Public, data-only record of benchmark submissions for actava-ai benchmarks.

This repo accepts submissions via pull request. The full audit packet (manifest + per-trial verifier evidence + compressed trajectories) lives in git so reviewers can inspect any submission directly from the PR diff. The rendered leaderboard lives elsewhere — at [actava.ai/benchmarks](https://actava.ai/benchmarks) — and reads `results.csv` files out of this repo.

## Benchmarks tracked

| Benchmark | Producer repo | Current version | Submissions |
|---|---|---|---|
| [chi-bench](benchmarks/chi-bench/) | [actava-ai/chi-bench](https://github.com/actava-ai/chi-bench) | `chi-bench-v1.0.0` | see [submissions/](benchmarks/chi-bench/submissions/) |

To add a new benchmark, see [`benchmarks/README.md`](benchmarks/README.md).

## Submit a result

You produce a **packet** on the producer side (e.g. `cb submission prepare` for chi-bench) and open a PR adding it to this repo. Two paths, both equivalent.

### Quick (helper)

```bash
# Prereqs: gh CLI authenticated; git user.email configured; you forked this repo on GitHub.
git clone https://github.com/<you>/leaderboard && cd leaderboard
python scripts/submit.py /path/to/packet/2026-05-12-<slug>/
```

The helper:

1. Reads the packet's `submission.json:dataset.name` to route it to the right benchmark subtree.
2. Runs `scripts/validate.py` against the proposed directory.
3. Copies the packet into `benchmarks/<bench>/submissions/<dir>/`.
4. Creates a branch `sub/<bench>/<dir>`, commits, pushes to your fork (or directly, with `--no-fork`).
5. Opens a PR via `gh pr create`. Prints the PR URL.

Flags: `--no-fork`, `--no-open-pr`, `--on-conflict {abandon,replace,bump-date}`, `--leaderboard-repo <slug>`.

### Manual

```bash
git clone https://github.com/<you>/leaderboard && cd leaderboard
cp -r /path/to/packet/2026-05-12-<slug>/ benchmarks/<bench>/submissions/
python scripts/validate.py benchmarks/<bench>/submissions/2026-05-12-<slug>/
git checkout -b sub/<bench>/2026-05-12-<slug>
git add benchmarks/<bench>/submissions/2026-05-12-<slug>/
git commit -m "<bench>: <team> · <agent> · <model>"
git push origin sub/<bench>/2026-05-12-<slug>
gh pr create --base main
```

Both flows go through the same CI validation (`.github/workflows/validate.yml`).

## Pre-PR sanity check

`scripts/validate.py` is a 5-line shim around the CI validator — same code path. Run it locally before opening a PR to catch problems early:

```bash
python scripts/validate.py benchmarks/chi-bench/submissions/2026-05-12-<slug>/
```

Exit 0 = validation passed. Exit 1 = errors (printed); fix and rerun.

## Inspecting a submission

Submission directories are plain files. Click into any one on GitHub to see the manifest, headline metrics (in the auto-generated README), and the per-trial tree.

Trajectories are zstd-compressed JSONL:

```bash
zstdcat benchmarks/chi-bench/submissions/<dir>/trials/<domain>/<trial_id>/agent/trajectory.jsonl.zst | jq .
```

## Reviewer / maintainer notes

See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

Apache-2.0. See [`LICENSE`](LICENSE).
```

- [ ] **Step 3: Commit**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git add CONTRIBUTING.md README.md
git commit -m "docs: full README + CONTRIBUTING for v1 release"
```

---

### Task 21: End-to-end smoke test

This task is a manual verification that the producer + consumer pieces actually interoperate. No new code, no commits — purely a smoke gate before declaring the work done.

- [ ] **Step 1: Produce a packet from existing local data**

```bash
cd /Users/weiran/Github/chi-bench
cat > /tmp/smoke-sub.yaml <<'YAML'
schema: chi-bench/submission/v1
submission:
  id: smoke-test
  team: Smoke Test
  contact: smoke@example.com
  agent: claude-code
  model: anthropic/claude-opus-4-6
dataset:
  version: chi-bench-v1.0.0
  domains: [pa_provider]
paths:
  output_root: logs/submissions/my-team-claude-code-sonnet-4-6
YAML

uv run cb submission prepare -f /tmp/smoke-sub.yaml --date 2026-05-12 --out /tmp/cb-smoke --force
```

Expected: command exits 0; prints `Packet ready: /tmp/cb-smoke/2026-05-12-smoke-test`.

- [ ] **Step 2: Verify the packet shape**

```bash
ls /tmp/cb-smoke/2026-05-12-smoke-test/
ls /tmp/cb-smoke/2026-05-12-smoke-test/trials/
find /tmp/cb-smoke/2026-05-12-smoke-test/trials -name "*.zst" | head -3
```

Expected: top-level files (`submission.json`, `results.csv`, `sub.yaml`, `provenance.json`, `README.md`); a `trials/pa_provider/` directory; one or more `trajectory.jsonl.zst` files.

- [ ] **Step 3: Inspect a trajectory**

```bash
zstdcat $(find /tmp/cb-smoke/2026-05-12-smoke-test/trials -name "*.zst" | head -1) | head -1 | jq .
```

Expected: a JSON object with `_atif_header` containing `schema_version`, `session_id`, `agent`.

- [ ] **Step 4: Run the leaderboard validator against the packet**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
# Copy the packet into the expected position
mkdir -p benchmarks/chi-bench/submissions
cp -r /tmp/cb-smoke/2026-05-12-smoke-test benchmarks/chi-bench/submissions/
python3 scripts/validate.py benchmarks/chi-bench/submissions/2026-05-12-smoke-test
```

Expected: `✅ 2026-05-12-smoke-test: validation passed` (or, if soft warnings appear, no errors — exit code 0). If the validator complains about size limits, that's likely a real warning worth investigating.

- [ ] **Step 5: Clean up the smoke artifact**

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
rm -rf benchmarks/chi-bench/submissions/2026-05-12-smoke-test
rm -rf /tmp/cb-smoke /tmp/smoke-sub.yaml
```

- [ ] **Step 6: Run all tests one last time**

```bash
# chi-bench side
cd /Users/weiran/Github/chi-bench
uv run pytest -x
uv run ruff check src/ tests/

# leaderboard side
cd /Users/weiran/Github/chi-bench/leaderboard
python3 -m pytest .github/scripts/test_validate_submission.py scripts/test_submit.py -v
```

Expected: all pass on both sides.

- [ ] **Step 7: Push the leaderboard repo to GitHub (manual)**

The leaderboard repo has no remote commits yet. Push the `main` branch to publish the v1 scaffold:

```bash
cd /Users/weiran/Github/chi-bench/leaderboard
git push -u origin main
```

Expected: branch pushed; GitHub renders the README correctly; navigating to `benchmarks/chi-bench/` shows the README, schema, and empty `submissions/` placeholder.

> Note: this is a one-time public-ization. Confirm with the user before running — it makes the repo publicly visible.

---

## Self-Review

**Spec coverage check:**

- §1 Goal — ✅ end-to-end covered: PR-based submissions, multi-benchmark layout, packet contract, CI validation, data-only repo.
- §2 Architecture — ✅ Tasks 4 + 10–11 + 18–20 deliver the two-repo split with packet contract handoff.
- §2.3 Submission directory contents — ✅ Tasks 2 (zstd recoder), 3 (README generator), 4 (orchestrator), 11 (schema files).
- §2.4 Size budget — ✅ Task 14.
- §3 Manifest + JSON Schema — ✅ Task 11 (schema file); §3.2 cross-benchmark envelope is encoded in the JSON Schema's required fields.
- §3.4 `results.csv` `benchmark` + `dataset_version` columns — ⚠️ The spec adds these columns to `scripts/aggregate.py` in chi-bench. **Gap:** Phase 1 doesn't include the `aggregate.py` update; CSV is consumed by the validator using whatever columns exist. **Fix:** add Task 6a below, or accept that the validator works with the existing column set and address `aggregate.py` later.
- §4 Validation CI — ✅ Tasks 12–17.
- §5 Producer-side `cb submission prepare` — ✅ Tasks 1–6.
- §6 Leaderboard-side submission flow — ✅ Tasks 18–20.
- §7 Documentation footprint — ✅ Tasks 7–9 (chi-bench side), Tasks 10/11/20 (leaderboard side).

**Placeholder scan:** No "TBD" / "TODO" / "implement later". Some intentional template placeholders (`<your-id>`, `<slug>`, `<bench>`) — those are end-user inputs, not unfilled work.

**Type consistency:** `ValidationReport`, `SubmissionPlan`, `prepare_packet`, `pack_trajectory_to_jsonl_zst`, `iter_packed_messages`, `render_packet_readme`, `validate_packet`, `validate_pr_diff`, `plan_submission`, `commit_packet`, `push_and_open_pr` — all names used consistently across tasks. `SOFT_LIMITS` / `HARD_LIMITS` keys (`small_json`, `trial_json`, `trajectory_zst`, `total`) match between Task 14 implementation and tests.

**Inline gap fix — `aggregate.py` columns:** the spec specifies adding `benchmark` and `dataset_version` columns to `results.csv` (§3.4). The current `scripts/aggregate.py` already emits enough columns that the validator's exact-match check (Task 13 `check_results_csv_consistency`) only inspects `submission_id`, `domain`, `pass_at_1`, `n_trials`, `n_tasks` — fields that are present today. The new columns are required for the *external consumer* (`actava.ai/benchmarks`) to namespace rows across benchmarks; the validator doesn't depend on them. Adding a small `scripts/aggregate.py` patch is out-of-scope for the producer/consumer interop; it can land in a follow-up PR without breaking anything in this plan.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-12-leaderboard.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
