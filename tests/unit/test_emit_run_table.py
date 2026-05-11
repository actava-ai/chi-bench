"""Smoke test for scripts/_emit_run_table_commands.py.

Verifies the per-slice YAMLs it writes are valid ExperimentConfig YAMLs.
"""

import subprocess
import sys
from pathlib import Path

from chi_bench.experiment.config import ExperimentConfig

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_emit(args: list[str]) -> list[str]:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / "_emit_run_table_commands.py"), *args]
    res = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT)
    assert res.returncode == 0, f"stderr: {res.stderr}"
    return [line for line in res.stdout.splitlines() if line.strip()]


def test_emit_table1_first_row_pa_um():
    lines = _run_emit(
        [
            "--config",
            "configs/experiments/table1_main_matrix.yaml",
            "--row",
            "1",
            "--domain",
            "pa_um",
        ]
    )
    assert len(lines) == 1
    # Line shape: chi-bench experiment run -f <path-to-slice-yaml>
    tokens = lines[0].split()
    assert tokens[0] == "chi-bench"
    f_idx = tokens.index("-f")
    slice_yaml = REPO_ROOT / tokens[f_idx + 1]
    cfg = ExperimentConfig.from_yaml(str(slice_yaml))
    assert cfg.dataset == "data/prior_auth_um/tasks"
    assert cfg.agent == "claude-code"
    assert cfg.model == "anthropic/claude-opus-4-7"
    assert cfg.environment == "docker"
    assert cfg.n_attempts == 3


def test_emit_table4_no_domain_pa_um_has_skill_ablation():
    lines = _run_emit(
        [
            "--config",
            "configs/experiments/table4_skill_ablation.yaml",
            "--condition",
            "no_domain",
            "--domain",
            "pa_um",
        ]
    )
    assert len(lines) == 1
    # First token should be the env-var prefix
    assert lines[0].startswith("CHI_BENCH_SKILLS_ABLATE=")
    tokens = lines[0].split()
    f_idx = tokens.index("-f")
    slice_yaml = REPO_ROOT / tokens[f_idx + 1]
    cfg = ExperimentConfig.from_yaml(str(slice_yaml))
    assert "provider-pa" in cfg.skill_ablation
    assert "payer-um" in cfg.skill_ablation
    assert "care-manager" in cfg.skill_ablation


def test_emit_table5_cli_has_tool_mode():
    lines = _run_emit(
        [
            "--config",
            "configs/experiments/table5_mcp_vs_cli.yaml",
            "--condition",
            "cli",
        ]
    )
    # 3 lines (one per domain)
    assert len(lines) == 3
    for line in lines:
        assert line.startswith("CHI_BENCH_TOOL_MODE=cli")
        tokens = line.split()
        f_idx = tokens.index("-f")
        slice_yaml = REPO_ROOT / tokens[f_idx + 1]
        cfg = ExperimentConfig.from_yaml(str(slice_yaml))
        assert cfg.tool_mode == "cli"


def test_emit_table2_e2e_arena_single_row():
    lines = _run_emit(
        [
            "--config",
            "configs/experiments/table2_e2e_arena.yaml",
        ]
    )
    assert len(lines) == 1
    tokens = lines[0].split()
    f_idx = tokens.index("-f")
    slice_yaml = REPO_ROOT / tokens[f_idx + 1]
    cfg = ExperimentConfig.from_yaml(str(slice_yaml))
    assert cfg.agent == "dual-pa-e2e"
    assert cfg.provider_agent == "codex"
    assert cfg.payer_agent == "codex"
    # agent_kwargs preserved
    assert cfg.agent_kwargs.get("phase_max_turns") == "50"
