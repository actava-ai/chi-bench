"""Unit tests for the submission config schema + preflight + run helpers."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from chi_bench.experiment.submission import (
    DOMAIN_REGISTRY,
    SUBMISSION_SCHEMA_V1,
    SubmissionConfig,
    _build_slice_yaml,
    _resolve_domains,
    aggregate_submission,
    build_manifest,
    capture_provenance,
    preflight_agent,
    preflight_dataset,
    preflight_environment,
    run_submission,
    status_submission,
    write_manifest,
)


def _write(path: Path, body: str) -> Path:
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def _valid_yaml(**overrides: str) -> str:
    base = {
        "id": "my-team-claude-code-opus-4-7",
        "team": "My Team",
        "contact": "you@example.com",
        "agent": "claude-code",
        "model": "anthropic/claude-opus-4-7",
    }
    base.update(overrides)
    return textwrap.dedent(
        f"""
        schema: {SUBMISSION_SCHEMA_V1}
        submission:
          id: {base["id"]}
          team: "{base["team"]}"
          contact: "{base["contact"]}"
          agent: {base["agent"]}
          model: {base["model"]}
        dataset:
          version: chi-bench-v1.0.0
          domains: [pa, um, cm]
        """
    ).lstrip()


# ─── schema ──────────────────────────────────────────────────────────────────


def test_loads_valid_submission(tmp_path: Path) -> None:
    p = _write(tmp_path / "sub.yaml", _valid_yaml())
    cfg = SubmissionConfig.from_yaml(p)
    assert cfg.schema_ == SUBMISSION_SCHEMA_V1
    assert cfg.submission.id == "my-team-claude-code-opus-4-7"
    assert cfg.dataset.domains == ["pa_provider", "pa_um", "cm"]
    # default n_attempts is 1 (one trial per task, per submission policy)
    assert cfg.run.n_attempts == 1
    # output_root defaults to logs/submissions/<id>
    assert cfg.paths.output_root == Path("logs/submissions/my-team-claude-code-opus-4-7")


def test_domain_aliases_normalized(tmp_path: Path) -> None:
    yaml_body = _valid_yaml().replace("domains: [pa, um, cm]", "domains: [PA-Provider, Pa_UM, CM]")
    p = _write(tmp_path / "sub.yaml", yaml_body)
    cfg = SubmissionConfig.from_yaml(p)
    assert cfg.dataset.domains == ["pa_provider", "pa_um", "cm"]


def test_duplicate_domains_dedup(tmp_path: Path) -> None:
    yaml_body = _valid_yaml().replace("domains: [pa, um, cm]", "domains: [pa, pa_provider, um]")
    p = _write(tmp_path / "sub.yaml", yaml_body)
    cfg = SubmissionConfig.from_yaml(p)
    assert cfg.dataset.domains == ["pa_provider", "pa_um"]


def test_unknown_domain_rejected(tmp_path: Path) -> None:
    yaml_body = _valid_yaml().replace("domains: [pa, um, cm]", "domains: [marathon]")
    p = _write(tmp_path / "sub.yaml", yaml_body)
    with pytest.raises(ValidationError) as excinfo:
        SubmissionConfig.from_yaml(p)
    assert "unknown domain" in str(excinfo.value).lower()


def test_empty_domains_rejected(tmp_path: Path) -> None:
    yaml_body = _valid_yaml().replace("domains: [pa, um, cm]", "domains: []")
    p = _write(tmp_path / "sub.yaml", yaml_body)
    with pytest.raises(ValidationError):
        SubmissionConfig.from_yaml(p)


def test_bad_id_rejected(tmp_path: Path) -> None:
    yaml_body = _valid_yaml(id="My Team!")
    p = _write(tmp_path / "sub.yaml", yaml_body)
    with pytest.raises(ValidationError) as excinfo:
        SubmissionConfig.from_yaml(p)
    assert "forbidden characters" in str(excinfo.value)


def test_uppercase_id_rejected(tmp_path: Path) -> None:
    yaml_body = _valid_yaml(id="MyTeam")
    p = _write(tmp_path / "sub.yaml", yaml_body)
    with pytest.raises(ValidationError):
        SubmissionConfig.from_yaml(p)


def test_extra_fields_rejected(tmp_path: Path) -> None:
    body = _valid_yaml() + "rogue_top_level: 1\n"
    p = _write(tmp_path / "sub.yaml", body)
    with pytest.raises(ValidationError):
        SubmissionConfig.from_yaml(p)


def test_schema_version_pinned(tmp_path: Path) -> None:
    body = _valid_yaml().replace(
        f"schema: {SUBMISSION_SCHEMA_V1}", "schema: chi-bench/submission/v999"
    )
    p = _write(tmp_path / "sub.yaml", body)
    with pytest.raises(ValidationError):
        SubmissionConfig.from_yaml(p)


def test_domain_dataset_path_helper(tmp_path: Path) -> None:
    p = _write(tmp_path / "sub.yaml", _valid_yaml())
    cfg = SubmissionConfig.from_yaml(p)
    assert cfg.domain_dataset_path("pa_um") == Path("data/prior_auth_um/tasks")
    assert cfg.domain_registry_path("cm") == Path("data/" + DOMAIN_REGISTRY["cm"]["registry"])


# ─── preflight: dataset ──────────────────────────────────────────────────────


def _cfg_with_data_root(tmp_path: Path, data_root: Path) -> SubmissionConfig:
    yaml_body = _valid_yaml() + f"paths:\n  data_root: {data_root}\n"
    p = _write(tmp_path / "sub.yaml", yaml_body)
    return SubmissionConfig.from_yaml(p)


def test_preflight_dataset_missing_root(tmp_path: Path) -> None:
    cfg = _cfg_with_data_root(tmp_path, tmp_path / "nope")
    issues = preflight_dataset(cfg)
    codes = [i.code for i in issues]
    assert "dataset.missing_root" in codes


def test_preflight_dataset_missing_version_file(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    cfg = _cfg_with_data_root(tmp_path, data_root)
    issues = preflight_dataset(cfg)
    codes = [i.code for i in issues]
    assert "dataset.version_file_missing" in codes


def test_preflight_dataset_version_mismatch(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".chi-bench-version").write_text("chi-bench-v0.9.0\n")
    cfg = _cfg_with_data_root(tmp_path, data_root)
    issues = preflight_dataset(cfg)
    codes = [i.code for i in issues]
    assert "dataset.version_mismatch" in codes


def test_preflight_dataset_happy_path(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".chi-bench-version").write_text("chi-bench-v1.0.0\n")
    for dom_key, paths in DOMAIN_REGISTRY.items():
        (data_root / paths["dataset"]).mkdir(parents=True)
    cfg = _cfg_with_data_root(tmp_path, data_root)
    issues = preflight_dataset(cfg)
    assert issues == []


def test_preflight_dataset_domain_missing(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".chi-bench-version").write_text("chi-bench-v1.0.0\n")
    # Only create pa_provider, skip pa_um + cm
    (data_root / DOMAIN_REGISTRY["pa_provider"]["dataset"]).mkdir(parents=True)
    cfg = _cfg_with_data_root(tmp_path, data_root)
    issues = preflight_dataset(cfg)
    missing = [i for i in issues if i.code == "dataset.domain_missing"]
    assert len(missing) == 2  # pa_um + cm both missing


# ─── preflight: agent ────────────────────────────────────────────────────────


def test_preflight_agent_known(tmp_path: Path) -> None:
    p = _write(tmp_path / "sub.yaml", _valid_yaml(agent="claude-code"))
    cfg = SubmissionConfig.from_yaml(p)
    assert preflight_agent(cfg) == []


def test_preflight_agent_unknown_warns(tmp_path: Path) -> None:
    p = _write(tmp_path / "sub.yaml", _valid_yaml(agent="my-custom-harness"))
    cfg = SubmissionConfig.from_yaml(p)
    issues = preflight_agent(cfg)
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "agent.unknown"
    # The message must direct the user to the extension recipe and the
    # introspection command. Drift here is a UX regression — the soft
    # warning is most users' first hint that they need to register.
    assert "docs/extending.md" in issues[0].message
    assert "cb agent list" in issues[0].message
    assert "my-custom-harness" in issues[0].message


# ─── preflight: environment ──────────────────────────────────────────────────


def test_preflight_environment_env_file_missing_warns(tmp_path: Path, monkeypatch) -> None:
    yaml_body = _valid_yaml() + f"run:\n  env_file: {tmp_path / 'absent.env'}\n"
    p = _write(tmp_path / "sub.yaml", yaml_body)
    cfg = SubmissionConfig.from_yaml(p)
    # Skip the docker/modal probes by forcing environment to a value preflight
    # treats as a no-op (modal); we only assert on the env_file branch here.
    issues = preflight_environment(cfg)
    codes = {i.code for i in issues}
    assert "env.file_missing" in codes


# ─── domain filter resolution ────────────────────────────────────────────────


def _cfg_from_yaml_body(tmp_path: Path, body: str) -> SubmissionConfig:
    p = _write(tmp_path / "sub.yaml", body)
    return SubmissionConfig.from_yaml(p)


def test_resolve_domains_no_filter_returns_all(tmp_path: Path) -> None:
    cfg = _cfg_from_yaml_body(tmp_path, _valid_yaml())
    assert _resolve_domains(cfg, None) == ["pa_provider", "pa_um", "cm"]


def test_resolve_domains_filter_subset(tmp_path: Path) -> None:
    cfg = _cfg_from_yaml_body(tmp_path, _valid_yaml())
    assert _resolve_domains(cfg, ["pa", "cm"]) == ["pa_provider", "cm"]


def test_resolve_domains_filter_dedup(tmp_path: Path) -> None:
    cfg = _cfg_from_yaml_body(tmp_path, _valid_yaml())
    assert _resolve_domains(cfg, ["pa", "pa_provider", "pa-provider"]) == ["pa_provider"]


def test_resolve_domains_filter_not_in_submission(tmp_path: Path) -> None:
    body = _valid_yaml().replace("domains: [pa, um, cm]", "domains: [pa_um]")
    cfg = _cfg_from_yaml_body(tmp_path, body)
    with pytest.raises(ValueError, match="not in this submission's dataset.domains"):
        _resolve_domains(cfg, ["pa"])


def test_resolve_domains_filter_unknown_alias(tmp_path: Path) -> None:
    cfg = _cfg_from_yaml_body(tmp_path, _valid_yaml())
    with pytest.raises(ValueError, match="not a known domain alias"):
        _resolve_domains(cfg, ["marathon"])


# ─── slice YAML synthesis ────────────────────────────────────────────────────


def test_build_slice_yaml_shape(tmp_path: Path) -> None:
    cfg = _cfg_from_yaml_body(tmp_path, _valid_yaml())
    slice_cfg = _build_slice_yaml(cfg, "pa_um")
    assert slice_cfg["agent"] == "claude-code"
    assert slice_cfg["model"] == "anthropic/claude-opus-4-7"
    assert slice_cfg["dataset"] == "data/prior_auth_um/tasks"
    assert slice_cfg["registry_path"] == "data/prior_auth_um/registry.json"
    assert slice_cfg["n_attempts"] == 1  # submission default
    assert slice_cfg["environment"] == "modal"  # submission default
    assert slice_cfg["job_name"] == "my-team-claude-code-opus-4-7__pa_um"
    assert "pa_um" in str(slice_cfg["trials_dir"])


def test_build_slice_yaml_respects_run_overrides(tmp_path: Path) -> None:
    body = _valid_yaml() + textwrap.dedent(
        """
        run:
          environment: docker
          n_attempts: 3
          concurrency: 8
          max_retries: 5
        """
    )
    cfg = _cfg_from_yaml_body(tmp_path, body)
    slice_cfg = _build_slice_yaml(cfg, "cm")
    assert slice_cfg["environment"] == "docker"
    assert slice_cfg["n_attempts"] == 3
    assert slice_cfg["concurrency"] == 8
    assert slice_cfg["max_retries"] == 5


# ─── provenance ──────────────────────────────────────────────────────────────


def test_capture_provenance_fields_present(tmp_path: Path) -> None:
    cfg = _cfg_from_yaml_body(tmp_path, _valid_yaml())
    prov = capture_provenance(cfg)
    assert prov["dataset_version"] == "chi-bench-v1.0.0"
    assert prov["environment"] == "modal"
    assert prov["host"] is not None
    assert prov["started_at"] is not None
    assert prov["finished_at"] is None
    assert prov["python_version"] is not None


# ─── run_submission (mocked Harbor call) ─────────────────────────────────────


def test_run_submission_iterates_domains_and_writes_artifacts(tmp_path: Path) -> None:
    """End-to-end run shape: preflight passes, slice YAMLs are written,
    run_experiment is invoked once per domain, provenance.json is finalized."""
    # Set up a valid dataset tree
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".chi-bench-version").write_text("chi-bench-v1.0.0\n")
    for paths in DOMAIN_REGISTRY.values():
        (data_root / paths["dataset"]).mkdir(parents=True)

    out_root = tmp_path / "out"
    body = _valid_yaml() + textwrap.dedent(
        f"""
        run:
          environment: docker
        paths:
          data_root: {data_root}
          output_root: {out_root}
        """
    )
    p = _write(tmp_path / "sub.yaml", body)
    cfg = SubmissionConfig.from_yaml(p)

    # Stub out the environment preflight (docker probe would call out to real
    # docker) and the Harbor call itself.
    calls: list[str] = []

    def _fake_run_experiment(*, config: str) -> None:
        calls.append(config)
        # Verify the slice YAML exists at the path we were given
        assert Path(config).exists()

    with (
        patch(
            "chi_bench.experiment.submission.preflight_environment",
            return_value=[],
        ),
        patch("chi_bench.experiment.runner.run_experiment", _fake_run_experiment),
    ):
        out = run_submission(cfg, source_yaml=p, domain_filter=["pa", "cm"])

    assert out == out_root
    # Two slices ran, each with its own slice YAML
    assert len(calls) == 2
    slice_paths = sorted(Path(c) for c in calls)
    assert slice_paths == sorted(
        [out_root / "pa_provider" / "slice.yaml", out_root / "cm" / "slice.yaml"]
    )

    # sub.yaml was frozen at the output root
    assert (out_root / "sub.yaml").read_text() == p.read_text()

    # provenance.json was finalized
    prov = json.loads((out_root / "provenance.json").read_text())
    assert prov["finished_at"] is not None
    assert prov["dataset_version"] == "chi-bench-v1.0.0"


def test_run_submission_aborts_on_preflight_error(tmp_path: Path) -> None:
    body = _valid_yaml() + f"paths:\n  data_root: {tmp_path / 'nope'}\n"
    p = _write(tmp_path / "sub.yaml", body)
    cfg = SubmissionConfig.from_yaml(p)
    with pytest.raises(RuntimeError, match="preflight error"):
        run_submission(cfg, source_yaml=p)


# ─── aggregate + manifest ────────────────────────────────────────────────────


def _make_trial(
    trials_root: Path,
    name: str,
    reward: float,
    agent: str = "codex",
    model: str = "openai/gpt-5.5",
    n_in: int = 1000,
    n_out: int = 500,
    walltime: float = 10.0,
) -> None:
    """Mirror the fixture used by tests/unit/test_aggregate.py."""
    d = trials_root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(
        json.dumps(
            {
                "verifier_result": {"rewards": {"reward": reward}},
                "agent_result": {
                    "input_tokens": n_in,
                    "output_tokens": n_out,
                    "n_cache_tokens": 0,
                    "wall_clock_seconds": walltime,
                },
                "agent_info": {
                    "agent": agent,
                    "model_info": {
                        "provider": model.split("/")[0],
                        "name": model.split("/", 1)[1],
                    },
                },
                "task": {"path": f"data/prior_auth_um/tasks/{name.split('__')[0]}"},
            }
        )
    )
    (d / "reward.txt").write_text(str(reward))


def _populated_submission(tmp_path: Path, rewards: dict[str, list[float]]) -> SubmissionConfig:
    """Build a SubmissionConfig with a populated output_root.

    ``rewards`` is ``{domain: [reward_per_trial, ...]}``. Tasks are named
    ``t<i>``; one attempt per task.
    """
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".chi-bench-version").write_text("chi-bench-v1.0.0\n")
    for paths in DOMAIN_REGISTRY.values():
        (data_root / paths["dataset"]).mkdir(parents=True)
    out_root = tmp_path / "out"
    body = _valid_yaml(agent="codex", model="openai/gpt-5.5") + textwrap.dedent(
        f"""
        paths:
          data_root: {data_root}
          output_root: {out_root}
        """
    )
    p = _write(tmp_path / "sub.yaml", body)
    cfg = SubmissionConfig.from_yaml(p)

    out_root.mkdir(parents=True, exist_ok=True)
    for dom, dom_rewards in rewards.items():
        dom_dir = out_root / dom
        for i, r in enumerate(dom_rewards):
            _make_trial(dom_dir, f"t{i}__{dom}", r)

    # Provenance file (run loop writes this; aggregate path reads it)
    (out_root / "provenance.json").write_text(
        json.dumps(
            {
                "code_sha": "abc123",
                "started_at": "2026-05-12T00:00:00Z",
                "finished_at": "2026-05-12T01:00:00Z",
            }
        )
    )
    return cfg


def test_aggregate_submission_overall_and_per_domain(tmp_path: Path) -> None:
    cfg = _populated_submission(
        tmp_path,
        {
            "pa_provider": [1.0, 0.0, 1.0],  # 2/3 pass
            "pa_um": [1.0, 1.0, 1.0],  # 3/3 pass
            "cm": [0.0, 0.0],  # 0/2 pass
        },
    )
    results = aggregate_submission(cfg)
    overall = results["overall"]
    assert overall is not None
    assert overall["n_trials"] == 8
    # Overall pass@1 is the per-task mean of HumanEval pass@1 estimators.
    # The fixture reuses task slugs (t0/t1/t2) across domains, so when the
    # overall walker groups by task name it collapses 8 trials into 3 tasks:
    #   t0: 3 attempts (1+1+0), p1=2/3
    #   t1: 3 attempts (0+1+0), p1=1/3
    #   t2: 2 attempts (1+1),   p1=1.0
    # Mean over 3 tasks = (2/3 + 1/3 + 1.0) / 3 = 2/3.
    assert overall["pass_at_1"] == 2 / 3

    per_domain = results["per_domain"]
    assert set(per_domain.keys()) == {"pa_provider", "pa_um", "cm"}
    assert per_domain["pa_um"]["pass_at_1"] == 1.0
    assert per_domain["cm"]["pass_at_1"] == 0.0


def test_aggregate_submission_strips_bootstrap_and_pass3_columns(tmp_path: Path) -> None:
    """Submission rows must NOT carry pass@3, pass^3, or bootstrap CI columns —
    leaderboard policy is one run per task, so those statistics don't apply."""
    cfg = _populated_submission(tmp_path, {"pa_um": [1.0, 0.0, 1.0]})
    results = aggregate_submission(cfg)
    overall = results["overall"]
    forbidden = {
        "pass_at_1_lo",
        "pass_at_1_hi",
        "pass_at_3",
        "pass_at_3_lo",
        "pass_at_3_hi",
        "pass_pow_3",
        "pass_pow_3_lo",
        "pass_pow_3_hi",
    }
    assert overall is not None
    assert forbidden.isdisjoint(overall.keys()), (
        f"submission overall row leaked paper-table columns: {forbidden & overall.keys()}"
    )
    for dom, row in results["per_domain"].items():
        assert forbidden.isdisjoint(row.keys()), (
            f"submission per_domain['{dom}'] row leaked paper-table columns: "
            f"{forbidden & row.keys()}"
        )


def test_aggregate_submission_skips_domain_with_no_trials(tmp_path: Path) -> None:
    cfg = _populated_submission(tmp_path, {"pa_um": [1.0]})
    results = aggregate_submission(cfg)
    assert set(results["per_domain"].keys()) == {"pa_um"}  # the other two domains
    # don't appear because their subdirs don't exist


def test_build_manifest_shape(tmp_path: Path) -> None:
    cfg = _populated_submission(tmp_path, {"pa_um": [1.0, 0.0], "cm": [1.0]})
    manifest = build_manifest(cfg)
    assert manifest["schema"] == SUBMISSION_SCHEMA_V1
    assert manifest["submission"]["id"] == "my-team-claude-code-opus-4-7"
    assert manifest["dataset"]["version"] == "chi-bench-v1.0.0"
    # Provenance was read from disk
    assert manifest["provenance"]["code_sha"] == "abc123"
    # Aggregated results embedded
    assert manifest["results"]["n_trials"] == 3
    assert set(manifest["per_domain"].keys()) == {"pa_um", "cm"}


def test_write_manifest_creates_files(tmp_path: Path) -> None:
    cfg = _populated_submission(tmp_path, {"pa_um": [1.0, 0.0, 1.0]})
    manifest_path, csv_path = write_manifest(cfg)
    assert manifest_path.exists()
    assert csv_path is not None and csv_path.exists()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["results"]["pass_at_1"] == 2 / 3

    import csv as _csv

    rows = list(_csv.DictReader(csv_path.open()))
    assert len(rows) == 1
    assert rows[0]["agent"] == "codex"
    # CSV header reflects the submission projection — no bootstrap CIs, no pass@3.
    forbidden = {
        "pass_at_1_lo",
        "pass_at_1_hi",
        "pass_at_3",
        "pass_pow_3",
    }
    assert forbidden.isdisjoint(rows[0].keys())


def test_write_manifest_no_trials_no_csv(tmp_path: Path) -> None:
    cfg = _populated_submission(tmp_path, {})  # no domain dirs created
    manifest_path, csv_path = write_manifest(cfg)
    assert manifest_path.exists()
    assert csv_path is None  # nothing to aggregate
    manifest = json.loads(manifest_path.read_text())
    assert manifest["results"] is None
    assert manifest["per_domain"] == {}


# ─── status ──────────────────────────────────────────────────────────────────


def _make_trial_with_layout(
    trials_root: Path,
    trial_name: str,
    reward: float,
    add_trajectory: bool = True,
) -> Path:
    """Produce a trial dir matching the real Harbor layout (with files under
    verifier/ and agent/)."""
    d = trials_root / trial_name
    (d / "verifier").mkdir(parents=True, exist_ok=True)
    (d / "agent").mkdir(parents=True, exist_ok=True)
    (d / "result.json").write_text(
        json.dumps(
            {
                "verifier_result": {"rewards": {"reward": reward}},
                "agent_result": {
                    "input_tokens": 1000,
                    "output_tokens": 500,
                    "n_cache_tokens": 0,
                    "wall_clock_seconds": 10.0,
                },
                "agent_info": {
                    "agent": "codex",
                    "model_info": {"provider": "openai", "name": "gpt-5.5"},
                },
                "task": {"path": f"data/prior_auth_um/tasks/{trial_name.split('__')[0]}"},
            }
        )
    )
    (d / "verifier" / "scorecard.json").write_text(json.dumps({"checks": []}))
    (d / "verifier" / "reward.json").write_text(json.dumps({"reward": reward}))
    if add_trajectory:
        # ~1KB synthetic trajectory; packet tests assert it round-trips byte-exact.
        (d / "agent" / "trajectory.json").write_text(
            json.dumps({"events": [{"role": "user", "content": "x" * 100}] * 5})
        )
    return d


def test_status_pending_running_done_states(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    data_root.mkdir()
    (data_root / ".chi-bench-version").write_text("chi-bench-v1.0.0\n")
    # Populate dataset task dirs so expected_tasks > 0
    for paths in DOMAIN_REGISTRY.values():
        ds_dir = data_root / paths["dataset"]
        ds_dir.mkdir(parents=True)
        for i in range(3):  # 3 expected tasks per domain
            (ds_dir / f"task_{i}").mkdir()

    out_root = tmp_path / "out"
    body = _valid_yaml() + textwrap.dedent(
        f"""
        paths:
          data_root: {data_root}
          output_root: {out_root}
        """
    )
    p = _write(tmp_path / "sub.yaml", body)
    cfg = SubmissionConfig.from_yaml(p)

    # pa_provider: 3/3 done; pa_um: 2/3 running; cm: 0/3 pending
    out_root.mkdir(parents=True)
    for i, r in enumerate([1.0, 1.0, 0.0]):
        _make_trial_with_layout(out_root / "pa_provider", f"t{i}__abc", r)
    for i, r in enumerate([1.0, 0.0]):
        _make_trial_with_layout(out_root / "pa_um", f"t{i}__abc", r)
    # cm: no dir = pending

    status = status_submission(cfg)
    by_domain = {d["domain"]: d for d in status["domains"]}
    assert by_domain["pa_provider"]["state"] == "done"
    assert by_domain["pa_provider"]["n_passed"] == 2
    assert by_domain["pa_provider"]["n_failed"] == 1
    assert by_domain["pa_um"]["state"] == "running"
    assert by_domain["pa_um"]["expected_tasks"] == 3
    assert by_domain["cm"]["state"] == "pending"


def test_status_no_dataset_root_marks_expected_zero(tmp_path: Path) -> None:
    """When data_root isn't populated, expected_tasks falls back to 0 (unknown)
    rather than raising."""
    out_root = tmp_path / "out"
    body = _valid_yaml() + textwrap.dedent(
        f"""
        paths:
          data_root: {tmp_path / "absent_data"}
          output_root: {out_root}
        """
    )
    p = _write(tmp_path / "sub.yaml", body)
    cfg = SubmissionConfig.from_yaml(p)
    out_root.mkdir()
    _make_trial_with_layout(out_root / "pa_um", "t0__abc", 1.0)
    status = status_submission(cfg)
    by_domain = {d["domain"]: d for d in status["domains"]}
    assert by_domain["pa_um"]["expected_tasks"] == 0
    # n_trials > 0 with expected=0 → state is "done" (we don't claim to know
    # how many should have run)
    assert by_domain["pa_um"]["state"] == "done"


def test_status_ignores_run_level_aggregate_result_json(tmp_path: Path) -> None:
    # Harbor writes a per-run aggregate result.json next to the trial dirs
    # (no verifier_result block, just n_total_trials + stats). Status must
    # skip it; otherwise rglob double-counts and inflates n_failed.
    out_root = tmp_path / "out"
    body = _valid_yaml() + textwrap.dedent(
        f"""
        paths:
          data_root: {tmp_path / "absent_data"}
          output_root: {out_root}
        """
    )
    p = _write(tmp_path / "sub.yaml", body)
    cfg = SubmissionConfig.from_yaml(p)

    run_dir = out_root / "pa_um" / "sub__pa_um"
    run_dir.mkdir(parents=True)
    _make_trial_with_layout(run_dir, "t0__abc", 1.0)
    _make_trial_with_layout(run_dir, "t1__abc", 0.0)
    (run_dir / "result.json").write_text(
        json.dumps({"id": "agg", "n_total_trials": 2, "stats": {"n_trials": 2}})
    )

    status = status_submission(cfg)
    by_domain = {d["domain"]: d for d in status["domains"]}
    assert by_domain["pa_um"]["n_trials"] == 2
    assert by_domain["pa_um"]["n_passed"] == 1
    assert by_domain["pa_um"]["n_failed"] == 1
