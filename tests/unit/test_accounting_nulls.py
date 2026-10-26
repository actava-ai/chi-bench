"""Unknown usage and pricing remain null through public result formats."""

import csv
import json
from pathlib import Path

import pytest

from chi_bench.aggregator import _parse_trial, aggregate, aggregate_to_rows


def _trial(root: Path, name: str, usage: dict | None, *, model="synthetic/priced") -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    provider, model_name = model.split("/", 1)
    path = folder / "result.json"
    path.write_text(
        json.dumps(
            {
                "task_name": "task-one",
                "agent_info": {
                    "name": "synthetic",
                    "model_info": {"provider": provider, "name": model_name},
                },
                "agent_result": usage,
                "verifier_result": {"rewards": {"reward": 1}},
            }
        )
    )
    return path


@pytest.fixture
def prices(tmp_path):
    path = tmp_path / "prices.yaml"
    path.write_text("prices:\n  synthetic/priced:\n    input: 10\n    output: 20\n    cache: 1\n")
    return path


@pytest.mark.parametrize(
    "usage", [None, {}, {"n_input_tokens": None, "n_output_tokens": None, "n_cache_tokens": None}]
)
def test_missing_usage_is_null_not_zero(tmp_path, prices, usage):
    path = _trial(tmp_path / "trials", "unknown", usage)
    parsed = _parse_trial(path)
    assert (parsed.input_tokens, parsed.output_tokens, parsed.cache_tokens) == (None, None, None)
    assert aggregate_to_rows(path.parent, prices)[0]["mean_cost_usd"] is None


@pytest.mark.parametrize("field", ["n_input_tokens", "n_output_tokens", "n_cache_tokens"])
@pytest.mark.parametrize("value", [None, -1, "not-a-count", True])
def test_one_unknown_or_invalid_usage_field_makes_full_cost_unknown(tmp_path, prices, field, value):
    usage = {"n_input_tokens": 1000, "n_output_tokens": 200, "n_cache_tokens": 0, field: value}
    path = _trial(tmp_path / "trials", "unknown", usage)
    assert aggregate_to_rows(path.parent, prices)[0]["mean_cost_usd"] is None


def test_unknown_price_is_null_even_with_nonzero_known_usage(tmp_path, prices):
    path = _trial(
        tmp_path / "trials",
        "unpriced",
        {"n_input_tokens": 1000000, "n_output_tokens": 1000000, "n_cache_tokens": 0},
        model="synthetic/unpriced",
    )
    assert aggregate_to_rows(path.parent, prices)[0]["mean_cost_usd"] is None


def test_known_zero_usage_keeps_numeric_zero(tmp_path, prices):
    path = _trial(
        tmp_path / "trials",
        "zero",
        {"n_input_tokens": 0, "n_output_tokens": 0, "n_cache_tokens": 0},
    )
    assert aggregate_to_rows(path.parent, prices)[0]["mean_cost_usd"] == 0.0


def test_one_unknown_trial_does_not_lower_population_mean(tmp_path, prices):
    root = tmp_path / "trials"
    _trial(
        root, "known", {"n_input_tokens": 1000000, "n_output_tokens": 1000000, "n_cache_tokens": 0}
    )
    _trial(root, "unknown", None)
    row = aggregate_to_rows(root, prices)[0]
    assert row["n_trials"] == 2
    assert row["pass_at_1"] == 1
    assert row["mean_cost_usd"] is None


def test_json_and_csv_explicitly_write_null_for_unknown_cost(tmp_path, prices):
    root = tmp_path / "trials"
    _trial(root, "unknown", None)
    out_json, out_csv = tmp_path / "results.json", tmp_path / "results.csv"
    aggregate(trials_dir=root, prices_path=prices, out_csv=out_csv, out_json=out_json)
    assert json.loads(out_json.read_text())[0]["mean_cost_usd"] is None
    with out_csv.open() as stream:
        assert next(csv.DictReader(stream))["mean_cost_usd"] == "null"


def test_openai_runner_writes_unknown_usage_on_failure(tmp_path):
    from chi_bench.experiment.agents.openai_agents_runner import write_result

    write_result(
        logs_dir=tmp_path,
        input_tokens=0,
        output_tokens=0,
        cached_tokens=0,
        cost_usd=0.0,
        turns=0,
        final_output=None,
        model="synthetic/priced",
        error="Synthetic interruption after partial work",
    )
    result = json.loads((tmp_path / "run_result.json").read_text())
    assert all(
        result[key] is None
        for key in ("input_tokens", "output_tokens", "cached_tokens", "cost_usd")
    )


def test_no_response_usage_is_unknown_in_runner():
    from types import SimpleNamespace
    from chi_bench.experiment.agents.openai_agents_runner import _extract_usage

    assert _extract_usage([SimpleNamespace(usage=None)]) == (None, None, None)


@pytest.mark.parametrize("missing_first", [False, True])
def test_sdk_missing_usage_sentinel_makes_response_totals_unknown(missing_first):
    from chi_bench.experiment.agents.openai_agents_runner import _extract_usage

    ModelResponse = pytest.importorskip("agents.items").ModelResponse
    Usage = pytest.importorskip("agents.usage").Usage
    # Both SDK API adapters substitute Usage() when the provider omits usage.
    # Its integer zero defaults must not erase the missing response's spend.
    missing = ModelResponse(output=[], usage=Usage(), response_id=None)
    known = ModelResponse(
        output=[],
        usage=Usage(requests=1, input_tokens=100, output_tokens=10, total_tokens=110),
        response_id="synthetic-known",
    )
    responses = [missing, known] if missing_first else [known, missing]
    assert _extract_usage(responses) == (None, None, None)


@pytest.mark.parametrize("input_tokens,output_tokens", [(0, 0), (100, 10)])
def test_sdk_reported_usage_preserves_explicit_zero_and_nonzero_counts(input_tokens, output_tokens):
    from chi_bench.experiment.agents.openai_agents_runner import _extract_usage

    ModelResponse = pytest.importorskip("agents.items").ModelResponse
    Usage = pytest.importorskip("agents.usage").Usage
    response = ModelResponse(
        output=[],
        usage=Usage(
            requests=1,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        ),
        response_id="synthetic-reported",
    )
    assert _extract_usage([response]) == (input_tokens, output_tokens, 0)


def test_one_unknown_role_phase_makes_e2e_totals_unknown():
    from harbor.models.agent.context import AgentContext
    from chi_bench.experiment.agents.dual_pa_e2e_phase_runner import (
        PhaseResult,
        aggregate_phase_contexts,
    )

    phases = [
        PhaseResult(
            "01_provider",
            "provider",
            "claude-code",
            "synthetic",
            AgentContext(n_input_tokens=100, n_output_tokens=10, n_cache_tokens=0, cost_usd=1.0),
            "01/trajectory.json",
            False,
        ),
        PhaseResult(
            "02_payer",
            "payer",
            "claude-code",
            "synthetic",
            AgentContext(),
            "02/trajectory.json",
            True,
        ),
    ]
    total = aggregate_phase_contexts(phases)
    assert total.cost_usd is None
    assert total.n_input_tokens is None
    assert total.n_output_tokens is None
    assert total.n_cache_tokens is None


def test_unparseable_e2e_phase_does_not_disappear_from_total(tmp_path, monkeypatch):
    from harbor.models.agent.context import AgentContext
    from chi_bench.experiment.agents.dual_pa_e2e_harness import DualPaE2EHarness
    from chi_bench.experiment.agents.dual_pa_e2e_phase_runner import PhaseResult

    harness = DualPaE2EHarness(logs_dir=tmp_path)
    for slug in ("01_provider_submit", "02_payer_review"):
        (tmp_path / "phases" / slug).mkdir(parents=True)

    def parse(folder, slug):
        if slug.startswith("02_"):
            raise ValueError("Synthetic incomplete phase artifact")
        return PhaseResult(
            slug,
            "provider",
            "claude-code",
            "synthetic",
            AgentContext(n_input_tokens=100, n_output_tokens=10, n_cache_tokens=0, cost_usd=1),
            "01/trajectory.json",
            False,
        )

    monkeypatch.setattr(harness, "_parse_phase_result", parse)
    context = AgentContext()
    harness.populate_context_post_run(context)
    assert context.cost_usd is None
    assert context.n_input_tokens is None
    assert context.metadata["phase_count"] == 2
    assert context.metadata["metrics_unavailable_phases"] == ["02_payer_review"]


@pytest.mark.asyncio
async def test_actual_runner_exception_path_preserves_unknown_usage(tmp_path, monkeypatch):
    import sys
    from chi_bench.experiment.agents import openai_agents_runner
    from tests.unit.test_openai_agents_runner_config import _install_fake_agents_sdk

    _install_fake_agents_sdk(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-no-network")
    monkeypatch.setenv("OPENAI_AGENTS_MODEL", "gpt-5.5")
    monkeypatch.setenv("OPENAI_AGENTS_API_MODE", "responses")

    async def fail(**kwargs):
        raise RuntimeError("Synthetic interruption after partial model work")

    monkeypatch.setattr(sys.modules["agents"].Runner, "run", fail)
    with pytest.raises(SystemExit):
        await openai_agents_runner.run_agent(
            "Synthetic", "http://example.invalid/mcp", logs_dir=tmp_path
        )
    result = json.loads((tmp_path / "run_result.json").read_text())
    assert all(
        result[key] is None
        for key in ("input_tokens", "output_tokens", "cached_tokens", "cost_usd")
    )


def test_packet_keeps_explicit_unknown_cost(tmp_path, monkeypatch):
    from chi_bench.experiment import submission

    cfg = submission.SubmissionConfig.model_validate(
        {
            "schema": submission.SUBMISSION_SCHEMA_V1,
            "submission": {
                "id": "null-cost",
                "team": "Synthetic",
                "contact": "test@example.invalid",
                "agent": "synthetic",
                "model": "synthetic/priced",
            },
            "dataset": {"version": "synthetic-v1", "content_sha256": "a" * 64},
        }
    )
    monkeypatch.setattr(
        submission,
        "aggregate_submission",
        lambda *a, **kw: {
            "overall": {"n_trials": 1, "n_tasks": 1, "pass_at_1": 1, "mean_cost_usd": None},
            "per_domain": {},
        },
    )
    manifest = submission._build_packet_manifest(cfg, tmp_path, "2026-10-24T00:00:00Z")
    assert "mean_cost_usd" in manifest["results"]
    assert manifest["results"]["mean_cost_usd"] is None
    assert manifest["provenance"]["judge_model"] is None


def test_packet_uses_recorded_judge_instead_of_prepare_environment(tmp_path, monkeypatch):
    from chi_bench.experiment import submission

    cfg = submission.SubmissionConfig.model_validate(
        {
            "schema": submission.SUBMISSION_SCHEMA_V1,
            "submission": {
                "id": "recorded-judge",
                "team": "Synthetic",
                "contact": "test@example.invalid",
                "agent": "synthetic",
                "model": "synthetic/priced",
            },
            "dataset": {"version": "synthetic-v1", "content_sha256": "a" * 64},
        }
    )
    (tmp_path / "provenance.json").write_text(json.dumps({"judge_model": "recorded-judge"}))
    monkeypatch.setenv("CHI_BENCH_JUDGE_MODEL", "different-prepare-judge")
    monkeypatch.setattr(
        submission, "aggregate_submission", lambda *a, **kw: {"overall": {}, "per_domain": {}}
    )
    manifest = submission._build_packet_manifest(cfg, tmp_path, "2026-10-24T00:00:00Z")
    assert manifest["provenance"]["judge_model"] == "recorded-judge"
