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
            "id": "x",
            "team": "T",
            "agent": "a",
            "model": "m",
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
