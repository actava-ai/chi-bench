"""Contract tests for the reviewed frontier-model smoke matrix."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import yaml

from chi_bench.experiment.config import ExperimentConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = REPO_ROOT / "configs/experiments/frontier_models_smoke_2026_07.yaml"
PRICES_PATH = REPO_ROOT / "configs/prices.yaml"

EXPECTED_DOMAINS = {
    "pa_provider": {
        "dataset": ("data/prior_auth_provider/tasks/pa_t014_t014_o001_p01_new_referral_provider")
    },
    "pa_um": {"dataset": "data/prior_auth_um/tasks/pa_t034_t034_o002_p01_intake_payer"},
    "cm": {"dataset": "data/care_management/tasks/cm_afib_moderate_anxious_001"},
}

EXPECTED_ROWS = [
    {
        "agent": "claude-code",
        "model": "anthropic/claude-fable-5",
        "agent_kwargs": {"version": "2.1.216", "reasoning_effort": "high"},
    },
    {
        "agent": "codex",
        "model": "openai/gpt-5.6-sol",
        "agent_kwargs": {
            "version": "0.145.0",
            "reasoning_effort": "high",
            "reasoning_summary": "auto",
        },
    },
    {
        "agent": "codex",
        "model": "openai/gpt-5.6-terra",
        "agent_kwargs": {
            "version": "0.145.0",
            "reasoning_effort": "high",
            "reasoning_summary": "auto",
        },
    },
    {
        "agent": "codex",
        "model": "openai/gpt-5.6-luna",
        "agent_kwargs": {
            "version": "0.145.0",
            "reasoning_effort": "high",
            "reasoning_summary": "auto",
        },
    },
    {
        "agent": "openai-agents",
        "model": "moonshotai/kimi-k3",
        "agent_kwargs": {
            "max_turns": "50",
            "max_retries": "10",
            "max_tool_return_chars": "100000",
        },
    },
    {
        "agent": "openai-agents",
        "model": "thinkingmachines/Inkling:peft:262144",
        "agent_kwargs": {
            "api_mode": "chat_completions",
            "reasoning_effort": "high",
            "max_turns": "50",
            "max_retries": "10",
            "max_tool_return_chars": "100000",
        },
    },
]

EXPECTED_PRICES = {
    "anthropic/claude-fable-5": {"input": 10.0, "cache": 1.0, "output": 50.0},
    "openai/gpt-5.6-sol": {"input": 5.0, "cache": 0.5, "output": 30.0},
    "openai/gpt-5.6-terra": {"input": 2.5, "cache": 0.25, "output": 15.0},
    "openai/gpt-5.6-luna": {"input": 1.0, "cache": 0.1, "output": 6.0},
    "moonshotai/kimi-k3": {"input": 3.0, "cache": 0.3, "output": 15.0},
    "thinkingmachines/Inkling:peft:262144": {
        "input": 3.74,
        "cache": 0.748,
        "output": 9.36,
    },
}


def test_frontier_smoke_matrix_matches_reviewed_configuration() -> None:
    matrix = yaml.safe_load(MATRIX_PATH.read_text())

    assert matrix["name"] == "frontier_models_smoke_2026_07"
    assert matrix["defaults"] == {
        "environment": "docker",
        "env_file": ".env",
        "trials_root": "logs/experiments/frontier_models_smoke_2026_07",
        "agent_timeout_multiplier": 2.0,
    }
    assert matrix["domains"] == EXPECTED_DOMAINS
    assert matrix["rows"] == EXPECTED_ROWS

    for domain in matrix["domains"].values():
        assert (REPO_ROOT / domain["dataset"] / "task.toml").is_file()


def test_frontier_model_prices_match_reviewed_rates() -> None:
    prices = yaml.safe_load(PRICES_PATH.read_text())["prices"]

    for model, expected in EXPECTED_PRICES.items():
        assert prices[model] == expected


def test_frontier_smoke_matrix_emits_18_unique_valid_slices() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/_emit_run_table_commands.py"),
            "--config",
            str(MATRIX_PATH),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    commands = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(commands) == 18
    assert len(set(commands)) == 18

    trials_dirs: set[str] = set()
    for command in commands:
        tokens = shlex.split(command)
        assert tokens[:3] == ["cb", "experiment", "run"]
        slice_path = REPO_ROOT / tokens[tokens.index("-f") + 1]
        config = ExperimentConfig.from_yaml(slice_path)
        assert (REPO_ROOT / config.dataset / "task.toml").is_file()
        assert config.trials_dir is not None
        trials_dirs.add(config.trials_dir)

    assert len(trials_dirs) == 18
