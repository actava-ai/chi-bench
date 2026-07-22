"""Contract tests for the reviewed frontier-model smoke matrix."""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from harbor.models.job.config import JobConfig
from harbor.models.trial.config import AgentConfig
from harbor.utils.env import resolve_env_vars

from chi_bench.experiment.config import ExperimentConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data"
MATRIX_PATH = REPO_ROOT / "configs/experiments/frontier_models_smoke_2026_07.yaml"
FULL_MATRIX_PATH = REPO_ROOT / "configs/experiments/frontier_models_full_2026_07.yaml"
FABLE_FULL_MATRIX_PATH = REPO_ROOT / "configs/experiments/fable5_openrouter_full_2026_07.yaml"
NEMOTRON_SMOKE_MATRIX_PATH = (
    REPO_ROOT / "configs/experiments/nemotron3_ultra_tinker_smoke_2026_07.yaml"
)
NEMOTRON_FULL_MATRIX_PATH = (
    REPO_ROOT / "configs/experiments/nemotron3_ultra_tinker_full_2026_07.yaml"
)
PRICES_PATH = REPO_ROOT / "configs/prices.yaml"

NEMOTRON_MODEL = "nvidia/NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16:peft:262144"
NEMOTRON_AGENT_KWARGS = {
    "provider_route": "tinker",
    "api_mode": "chat_completions",
    "reasoning_effort": "high",
    "max_turns": "50",
    "max_retries": "10",
    "max_tool_return_chars": "100000",
}
NEMOTRON_ROW = {
    "agent": "openai-agents",
    "model": NEMOTRON_MODEL,
    "agent_kwargs": NEMOTRON_AGENT_KWARGS,
}
NEMOTRON_SLICE_PREFIX = "01_openai-agents_nvidia-NVIDIA-Nemotron-3-Ultra-550B-A55B-BF16-peft-262144"
NEMOTRON_SMOKE_TRIALS_ROOT = "logs/experiments/nemotron3_ultra_tinker_smoke_2026_07"
NEMOTRON_FULL_TRIALS_ROOT = "logs/experiments/nemotron3_ultra_tinker_full_2026_07"

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
    NEMOTRON_MODEL: {"input": 3.32, "cache": 0.664, "output": 8.30},
}

EXPECTED_FULL_DOMAINS = {
    "pa_provider": {
        "dataset": "data/prior_auth_provider/tasks",
        "registry_path": "data/prior_auth_provider/registry.json",
    },
    "pa_um": {
        "dataset": "data/prior_auth_um/tasks",
        "registry_path": "data/prior_auth_um/registry.json",
    },
    "cm": {
        "dataset": "data/care_management/tasks",
        "registry_path": "data/care_management/registry.json",
    },
}

EXPECTED_FULL_ROWS = EXPECTED_ROWS[1:]

EXPECTED_NEMOTRON_SMOKE_MATRIX = {
    "name": "nemotron3_ultra_tinker_smoke_2026_07",
    "description": (
        "NVIDIA Nemotron 3 Ultra via Tinker on one representative task in each chi-Bench domain."
    ),
    "defaults": {
        "environment": "modal",
        "env_file": ".env",
        "concurrency": 1,
        "n_attempts": 1,
        "max_retries": 2,
        "trials_root": NEMOTRON_SMOKE_TRIALS_ROOT,
        "agent_timeout_multiplier": 2.0,
    },
    "domains": EXPECTED_DOMAINS,
    "rows": [NEMOTRON_ROW],
}

EXPECTED_NEMOTRON_FULL_MATRIX = {
    "name": "nemotron3_ultra_tinker_full_2026_07",
    "description": (
        "NVIDIA Nemotron 3 Ultra via Tinker across all chi-Bench tasks in the three benchmark "
        "domains."
    ),
    "defaults": {
        "environment": "modal",
        "env_file": ".env",
        "concurrency": 5,
        "n_attempts": 1,
        "max_retries": 2,
        "trials_root": NEMOTRON_FULL_TRIALS_ROOT,
        "agent_timeout_multiplier": 2.0,
    },
    "domains": EXPECTED_FULL_DOMAINS,
    "rows": [NEMOTRON_ROW],
}

FABLE_FULL_TRIALS_ROOT = "logs/experiments/fable5_openrouter_full_2026_07"
EMPTY_AGENT_ENV_TEMPLATE = "${CHI_BENCH_EMPTY_AGENT_ENV:-}"
FABLE_EMPTY_CREDENTIAL_KEYS = {
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
}
EXPECTED_FABLE_AGENT_ENV = {
    "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
    "ANTHROPIC_AUTH_TOKEN": "${OPENROUTER_API_KEY}",
    "ANTHROPIC_API_KEY": EMPTY_AGENT_ENV_TEMPLATE,
    "CLAUDE_CODE_OAUTH_TOKEN": EMPTY_AGENT_ENV_TEMPLATE,
    "ANTHROPIC_MODEL": "anthropic/claude-fable-5",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "anthropic/claude-fable-5",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "anthropic/claude-fable-5",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "anthropic/claude-fable-5",
    "CLAUDE_CODE_SUBAGENT_MODEL": "anthropic/claude-fable-5",
}
EXPECTED_FABLE_FULL_MATRIX = {
    "name": "fable5_openrouter_full_2026_07",
    "description": (
        "Fable 5 via OpenRouter across all chi-Bench tasks in the three benchmark domains."
    ),
    "defaults": {
        "environment": "modal",
        "env_file": ".env",
        "concurrency": 5,
        "n_attempts": 1,
        "max_retries": 2,
        "trials_root": FABLE_FULL_TRIALS_ROOT,
        "agent_timeout_multiplier": 2.0,
    },
    "domains": EXPECTED_FULL_DOMAINS,
    "rows": [
        {
            "agent": "claude-code",
            "model": "anthropic/claude-fable-5",
            "agent_kwargs": {
                "version": "2.1.216",
                "reasoning_effort": "high",
            },
            "agent_env": EXPECTED_FABLE_AGENT_ENV,
        }
    ],
}


def _load_emitted_slices(
    matrix_path: Path,
) -> tuple[list[str], list[tuple[dict[str, object], ExperimentConfig]]]:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/_emit_run_table_commands.py"),
            "--config",
            str(matrix_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    commands = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(commands) == len(set(commands))

    slices: list[tuple[dict[str, object], ExperimentConfig]] = []
    for command in commands:
        tokens = shlex.split(command)
        assert tokens[:3] == ["cb", "experiment", "run"]
        slice_path = REPO_ROOT / tokens[tokens.index("-f") + 1]
        slices.append(
            (
                yaml.safe_load(slice_path.read_text()),
                ExperimentConfig.from_yaml(slice_path),
            )
        )
    return commands, slices


def _assert_nemotron_slice(
    raw_slice: dict[str, object],
    config: ExperimentConfig,
    *,
    concurrency: int,
    trials_root: str,
    domain_name: str,
) -> None:
    assert config.agent == "openai-agents"
    assert config.model == NEMOTRON_MODEL
    assert config.agent_kwargs == NEMOTRON_AGENT_KWARGS
    assert "agent_env" not in raw_slice
    assert config.agent_env == {}
    assert config.environment == "modal"
    assert config.concurrency == concurrency
    assert config.n_attempts == 1
    assert config.max_retries == 2
    assert config.agent_timeout_multiplier == 2.0
    assert config.trials_dir == (f"{trials_root}/{NEMOTRON_SLICE_PREFIX}_{domain_name}")


def test_nemotron_tinker_smoke_matrix_matches_reviewed_configuration() -> None:
    assert NEMOTRON_SMOKE_MATRIX_PATH.is_file(), (
        f"missing Nemotron Tinker smoke matrix: {NEMOTRON_SMOKE_MATRIX_PATH}"
    )
    matrix = yaml.safe_load(NEMOTRON_SMOKE_MATRIX_PATH.read_text())

    assert matrix == EXPECTED_NEMOTRON_SMOKE_MATRIX


def test_nemotron_tinker_smoke_matrix_emits_3_unique_valid_slices() -> None:
    commands, slices = _load_emitted_slices(NEMOTRON_SMOKE_MATRIX_PATH)
    assert len(commands) == 3

    expected_domain_by_dataset = {
        domain["dataset"]: domain_name for domain_name, domain in EXPECTED_DOMAINS.items()
    }
    emitted_datasets: set[str] = set()
    trials_dirs: set[str] = set()
    for raw_slice, config in slices:
        assert config.dataset in expected_domain_by_dataset
        assert config.registry_path is None
        _assert_nemotron_slice(
            raw_slice,
            config,
            concurrency=1,
            trials_root=NEMOTRON_SMOKE_TRIALS_ROOT,
            domain_name=expected_domain_by_dataset[config.dataset],
        )
        emitted_datasets.add(config.dataset)
        assert config.trials_dir is not None
        trials_dirs.add(config.trials_dir)

    assert emitted_datasets == set(expected_domain_by_dataset)
    assert len(trials_dirs) == 3


def test_nemotron_tinker_full_matrix_matches_reviewed_configuration() -> None:
    assert NEMOTRON_FULL_MATRIX_PATH.is_file(), (
        f"missing Nemotron Tinker full matrix: {NEMOTRON_FULL_MATRIX_PATH}"
    )
    matrix = yaml.safe_load(NEMOTRON_FULL_MATRIX_PATH.read_text())

    assert matrix == EXPECTED_NEMOTRON_FULL_MATRIX


def test_nemotron_tinker_full_matrix_emits_3_unique_valid_slices() -> None:
    commands, slices = _load_emitted_slices(NEMOTRON_FULL_MATRIX_PATH)
    assert len(commands) == 3

    expected_domain_by_dataset = {
        domain["dataset"]: domain_name for domain_name, domain in EXPECTED_FULL_DOMAINS.items()
    }
    expected_registry_by_dataset = {
        domain["dataset"]: domain["registry_path"] for domain in EXPECTED_FULL_DOMAINS.values()
    }
    emitted_datasets: set[str] = set()
    trials_dirs: set[str] = set()
    for raw_slice, config in slices:
        assert config.dataset in expected_domain_by_dataset
        assert config.registry_path == expected_registry_by_dataset[config.dataset]
        _assert_nemotron_slice(
            raw_slice,
            config,
            concurrency=5,
            trials_root=NEMOTRON_FULL_TRIALS_ROOT,
            domain_name=expected_domain_by_dataset[config.dataset],
        )
        emitted_datasets.add(config.dataset)
        assert config.trials_dir is not None
        trials_dirs.add(config.trials_dir)

    assert emitted_datasets == set(expected_domain_by_dataset)
    assert len(trials_dirs) == 3


@pytest.mark.skipif(
    not all(
        (REPO_ROOT / domain["registry_path"]).is_file() for domain in EXPECTED_FULL_DOMAINS.values()
    ),
    reason="downloaded chi-Bench registries are unavailable",
)
def test_nemotron_tinker_full_matrix_schedules_75_registry_tasks() -> None:
    assert NEMOTRON_FULL_MATRIX_PATH.is_file(), (
        f"missing Nemotron Tinker full matrix: {NEMOTRON_FULL_MATRIX_PATH}"
    )
    matrix = yaml.safe_load(NEMOTRON_FULL_MATRIX_PATH.read_text())

    scheduled_tasks = 0
    for domain in matrix["domains"].values():
        registry = json.loads((REPO_ROOT / domain["registry_path"]).read_text())
        registry_tasks = [task for entry in registry for task in entry["tasks"]]
        assert len(registry_tasks) == 25
        scheduled_tasks += len(registry_tasks) * matrix["defaults"]["n_attempts"]

    assert scheduled_tasks == 75


def test_fable_openrouter_full_matrix_matches_reviewed_configuration() -> None:
    assert FABLE_FULL_MATRIX_PATH.is_file(), (
        f"missing Fable full-eval matrix: {FABLE_FULL_MATRIX_PATH}"
    )
    matrix = yaml.safe_load(FABLE_FULL_MATRIX_PATH.read_text())

    assert matrix == EXPECTED_FABLE_FULL_MATRIX
    assert {row["agent"] for row in matrix["rows"]} == {"claude-code"}
    assert all(row["agent"] != "openai-agents" for row in matrix["rows"])


def test_fable_openrouter_full_matrix_emits_3_unique_valid_slices() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/_emit_run_table_commands.py"),
            "--config",
            str(FABLE_FULL_MATRIX_PATH),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    commands = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(commands) == 3
    assert len(set(commands)) == 3

    expected_registry_by_dataset = {
        domain["dataset"]: domain["registry_path"] for domain in EXPECTED_FULL_DOMAINS.values()
    }
    emitted_datasets: set[str] = set()
    trials_dirs: set[str] = set()
    for command in commands:
        tokens = shlex.split(command)
        assert tokens[:3] == ["cb", "experiment", "run"]
        slice_path = REPO_ROOT / tokens[tokens.index("-f") + 1]
        config = ExperimentConfig.from_yaml(slice_path)

        assert config.agent == "claude-code"
        assert config.agent != "openai-agents"
        assert config.model == "anthropic/claude-fable-5"
        assert config.agent_kwargs == {
            "version": "2.1.216",
            "reasoning_effort": "high",
        }
        assert config.agent_env == EXPECTED_FABLE_AGENT_ENV
        assert config.dataset in expected_registry_by_dataset
        assert config.registry_path == expected_registry_by_dataset[config.dataset]
        assert config.environment == "modal"
        assert config.concurrency == 5
        assert config.n_attempts == 1
        assert config.max_retries == 2
        assert config.agent_timeout_multiplier == 2.0
        assert config.trials_dir is not None
        assert str(Path(config.trials_dir).parent) == FABLE_FULL_TRIALS_ROOT
        assert not config.trials_dir.startswith("logs/experiments/frontier_models_full_2026_07/")

        emitted_datasets.add(config.dataset)
        trials_dirs.add(config.trials_dir)

    assert emitted_datasets == set(expected_registry_by_dataset)
    assert len(trials_dirs) == 3


def test_fable_empty_credentials_use_resumable_empty_default_template(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CHI_BENCH_EMPTY_AGENT_ENV", raising=False)
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/_emit_run_table_commands.py"),
            "--config",
            str(FABLE_FULL_MATRIX_PATH),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    command = next(line for line in result.stdout.splitlines() if line.strip())
    tokens = shlex.split(command)
    slice_path = REPO_ROOT / tokens[tokens.index("-f") + 1]
    emitted_env = ExperimentConfig.from_yaml(slice_path).agent_env

    empty_credentials = {key: emitted_env[key] for key in FABLE_EMPTY_CREDENTIAL_KEYS}
    assert set(empty_credentials.values()) == {EMPTY_AGENT_ENV_TEMPLATE}
    assert resolve_env_vars(empty_credentials) == {key: "" for key in FABLE_EMPTY_CREDENTIAL_KEYS}

    agent_config = AgentConfig(name="claude-code", env=emitted_env)
    assert AgentConfig.model_validate_json(agent_config.model_dump_json()) == agent_config

    job_config = JobConfig(agents=[agent_config])
    assert JobConfig.model_validate_json(job_config.model_dump_json()) == job_config


def test_frontier_full_matrix_matches_reviewed_configuration() -> None:
    assert FULL_MATRIX_PATH.is_file(), f"missing full-eval matrix: {FULL_MATRIX_PATH}"
    matrix = yaml.safe_load(FULL_MATRIX_PATH.read_text())

    assert matrix["name"] == "frontier_models_full_2026_07"
    assert matrix["defaults"] == {
        "environment": "modal",
        "env_file": ".env",
        "concurrency": 5,
        "n_attempts": 1,
        "max_retries": 2,
        "trials_root": "logs/experiments/frontier_models_full_2026_07",
        "agent_timeout_multiplier": 2.0,
    }
    assert matrix["domains"] == EXPECTED_FULL_DOMAINS
    assert matrix["rows"] == EXPECTED_FULL_ROWS


def test_frontier_full_matrix_emits_15_unique_valid_slices() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/_emit_run_table_commands.py"),
            "--config",
            str(FULL_MATRIX_PATH),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    commands = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(commands) == 15
    assert len(set(commands)) == 15

    expected_registry_by_dataset = {
        domain["dataset"]: domain["registry_path"] for domain in EXPECTED_FULL_DOMAINS.values()
    }
    expected_models = {row["model"] for row in EXPECTED_FULL_ROWS}
    emitted_cells: set[tuple[str, str]] = set()
    trials_dirs: set[str] = set()
    for command in commands:
        tokens = shlex.split(command)
        assert tokens[:3] == ["cb", "experiment", "run"]
        slice_path = REPO_ROOT / tokens[tokens.index("-f") + 1]
        config = ExperimentConfig.from_yaml(slice_path)

        assert config.model is not None
        assert "fable" not in config.model.lower()
        assert config.dataset in expected_registry_by_dataset
        assert config.registry_path == expected_registry_by_dataset[config.dataset]
        assert config.model in expected_models
        assert config.environment == "modal"
        assert config.concurrency == 5
        assert config.n_attempts == 1
        assert config.max_retries == 2
        assert config.trials_dir is not None

        emitted_cells.add((config.dataset, config.model))
        trials_dirs.add(config.trials_dir)

    assert emitted_cells == {
        (dataset, model) for dataset in expected_registry_by_dataset for model in expected_models
    }
    assert len(trials_dirs) == 15


@pytest.mark.skipif(
    not all(
        (REPO_ROOT / domain["dataset"]).is_dir() and (REPO_ROOT / domain["registry_path"]).is_file()
        for domain in EXPECTED_FULL_DOMAINS.values()
    ),
    reason="downloaded chi-Bench data is unavailable",
)
def test_frontier_full_datasets_have_25_registry_matched_tasks() -> None:
    for domain in EXPECTED_FULL_DOMAINS.values():
        dataset_path = REPO_ROOT / domain["dataset"]
        registry_path = REPO_ROOT / domain["registry_path"]

        task_dirs = {path.name for path in dataset_path.iterdir() if path.is_dir()}
        registry = json.loads(registry_path.read_text())
        registry_tasks = {
            task["name"] for dataset_entry in registry for task in dataset_entry["tasks"]
        }

        assert len(task_dirs) == 25
        assert len(registry_tasks) == 25
        assert registry_tasks == task_dirs


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


@pytest.mark.skipif(not DATA_ROOT.is_dir(), reason="downloaded chi-Bench data is unavailable")
def test_frontier_smoke_datasets_exist_when_data_is_available() -> None:
    for domain in EXPECTED_DOMAINS.values():
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

    expected_datasets = {domain["dataset"] for domain in EXPECTED_DOMAINS.values()}
    emitted_datasets: set[str] = set()
    trials_dirs: set[str] = set()
    for command in commands:
        tokens = shlex.split(command)
        assert tokens[:3] == ["cb", "experiment", "run"]
        slice_path = REPO_ROOT / tokens[tokens.index("-f") + 1]
        config = ExperimentConfig.from_yaml(slice_path)
        assert config.dataset in expected_datasets
        emitted_datasets.add(config.dataset)
        assert config.trials_dir is not None
        trials_dirs.add(config.trials_dir)

    assert emitted_datasets == expected_datasets
    assert len(trials_dirs) == 18
