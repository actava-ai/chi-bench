import pytest

from chi_bench.experiment.config import ExperimentConfig
from chi_bench.experiment.runner import _build_harbor_command, _forward_agent_keys


def test_forward_agent_keys_emits_present_only():
    env = {
        "ANTHROPIC_API_KEY": "ak-anthropic",
        "OPENAI_API_KEY": "ak-openai",
        # GEMINI_API_KEY absent
        "OPENROUTER_API_KEY": "ak-openrouter",
        "IRRELEVANT": "x",
    }
    flags = _forward_agent_keys(env)
    assert "--ae" in flags
    pairs = [flags[i + 1] for i, x in enumerate(flags) if x == "--ae"]
    assert "ANTHROPIC_API_KEY=ak-anthropic" in pairs
    assert "OPENAI_API_KEY=ak-openai" in pairs
    assert "OPENROUTER_API_KEY=ak-openrouter" in pairs
    assert not any(p.startswith("GEMINI_API_KEY=") for p in pairs)
    assert not any("IRRELEVANT" in p for p in pairs)


def test_forward_agent_keys_no_overrides_signature():
    """_forward_agent_keys MUST be a single-argument function — per-row override path removed."""
    import inspect
    sig = inspect.signature(_forward_agent_keys)
    assert list(sig.parameters.keys()) == ["env"], (
        f"per-row override 'overrides' param must be gone; got {list(sig.parameters)}"
    )


def test_build_harbor_command_docker_default(tmp_path):
    # Minimal config: docker env, single dataset, codex+gpt-5.5
    cfg = ExperimentConfig(
        dataset=str(tmp_path),
        agent="codex",
        model="openai/gpt-5.5",
        concurrency=1,
        environment="docker",
    )
    # Need a task.toml inside dataset to trigger single-trial path
    (tmp_path / "task.toml").write_text("")
    cmd = _build_harbor_command(cfg, env={"OPENAI_API_KEY": "ak-test"})
    s = " ".join(cmd)
    assert "trials start" in s
    assert "-a codex" in s
    assert "-m openai/gpt-5.5" in s
    assert "--environment-import-path chi_bench.experiment.docker_env:ChiBenchDockerEnvironment" in s
    assert "--ae OPENAI_API_KEY=ak-test" in s


def test_build_harbor_command_modal_keeps_modal_path(tmp_path):
    cfg = ExperimentConfig(
        dataset=str(tmp_path),
        agent="codex",
        model="openai/gpt-5.5",
        concurrency=1,
        environment="modal",
    )
    (tmp_path / "task.toml").write_text("")
    cmd = _build_harbor_command(cfg, env={"OPENAI_API_KEY": "ak-test"})
    s = " ".join(cmd)
    assert "chi_bench.experiment.modal_env:ChiBenchModalEnvironment" in s
    assert "chi_bench.experiment.docker_env" not in s
