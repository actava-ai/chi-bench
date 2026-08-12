import yaml

from chi_bench.experiment.config import ExperimentConfig
from chi_bench.experiment.runner import (
    _build_child_env,
    _build_harbor_command,
    _forward_agent_keys,
    _redact_command_for_log,
)


def test_experiment_config_agent_env_loads_and_defaults_empty(tmp_path):
    default = ExperimentConfig(dataset=str(tmp_path))
    assert default.agent_env == {}

    config_path = tmp_path / "experiment.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "dataset": str(tmp_path),
                "agent_env": {
                    "ANTHROPIC_API_KEY": "",
                    "ANTHROPIC_AUTH_TOKEN": "${OPENROUTER_API_KEY}",
                },
            }
        )
    )

    loaded = ExperimentConfig.from_yaml(config_path)
    assert loaded.agent_env == {
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "${OPENROUTER_API_KEY}",
    }


def test_forward_agent_keys_emits_present_only():
    env = {
        "ANTHROPIC_API_KEY": "ak-anthropic",
        "OPENAI_API_KEY": "ak-openai",
        # GEMINI_API_KEY absent
        "OPENROUTER_API_KEY": "ak-openrouter",
        "TINKER_API_KEY": "ak-tinker",
        "IRRELEVANT": "x",
    }
    flags = _forward_agent_keys(env)
    assert "--ae" in flags
    pairs = [flags[i + 1] for i, x in enumerate(flags) if x == "--ae"]
    assert "ANTHROPIC_API_KEY=ak-anthropic" in pairs
    assert "OPENAI_API_KEY=ak-openai" in pairs
    assert "OPENROUTER_API_KEY=ak-openrouter" in pairs
    assert "TINKER_API_KEY=ak-tinker" in pairs
    assert not any(p.startswith("GEMINI_API_KEY=") for p in pairs)
    assert not any("IRRELEVANT" in p for p in pairs)


def test_forward_agent_keys_no_overrides_signature():
    """Keep inherited forwarding separate from row-scoped config overrides."""
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
    assert (
        "--environment-import-path chi_bench.experiment.docker_env:ChiBenchDockerEnvironment" in s
    )
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


def test_build_harbor_command_appends_sorted_row_agent_env_and_redacts_values(tmp_path):
    native_judge_key = "native-anthropic-test-key"
    row_agent_env = {
        "ANTHROPIC_BASE_URL": "https://gateway.example.test/api",
        "ANTHROPIC_AUTH_TOKEN": "${OPENROUTER_API_KEY}",
        "ANTHROPIC_API_KEY": "",
        "CLAUDE_CODE_OAUTH_TOKEN": "",
        "ANTHROPIC_MODEL": "row-primary-model",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": "row-sonnet-model",
        "ANTHROPIC_DEFAULT_OPUS_MODEL": "row-opus-model",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": "row-haiku-model",
        "CLAUDE_CODE_SUBAGENT_MODEL": "row-subagent-model",
    }
    cfg = ExperimentConfig(
        dataset=str(tmp_path),
        agent="claude-code",
        model="anthropic/claude-fable-5",
        agent_env=row_agent_env,
    )

    cmd = _build_harbor_command(cfg, env={"ANTHROPIC_API_KEY": native_judge_key})
    agent_env_pairs = [cmd[i + 1] for i, arg in enumerate(cmd) if arg == "--ae"]
    expected_row_pairs = [f"{key}={value}" for key, value in sorted(row_agent_env.items())]

    assert "ANTHROPIC_API_KEY=native-anthropic-test-key" in agent_env_pairs
    assert "ANTHROPIC_AUTH_TOKEN=${OPENROUTER_API_KEY}" in agent_env_pairs
    assert agent_env_pairs[-len(expected_row_pairs) :] == expected_row_pairs
    assert agent_env_pairs.index("ANTHROPIC_API_KEY=native-anthropic-test-key") < (
        agent_env_pairs.index("ANTHROPIC_API_KEY=")
    )

    redacted = _redact_command_for_log(cmd)
    for value in [native_judge_key, *row_agent_env.values()]:
        if value:
            assert value not in redacted
    for key in row_agent_env:
        assert f"{key}=***" in redacted


def test_row_agent_env_overrides_gemini_auto_trust_default(tmp_path):
    cfg = ExperimentConfig(
        dataset=str(tmp_path),
        agent="gemini-cli",
        agent_env={"GEMINI_CLI_TRUST_WORKSPACE": "false"},
    )

    cmd = _build_harbor_command(cfg, env={})
    trust_entries = [
        cmd[i + 1]
        for i, arg in enumerate(cmd)
        if arg == "--ae" and cmd[i + 1].startswith("GEMINI_CLI_TRUST_WORKSPACE=")
    ]

    assert trust_entries == [
        "GEMINI_CLI_TRUST_WORKSPACE=true",
        "GEMINI_CLI_TRUST_WORKSPACE=false",
    ]


def test_agent_env_overrides_stay_out_of_child_server_and_judge_env(monkeypatch, tmp_path):
    native_judge_key = "native-anthropic-test-key"
    monkeypatch.setenv("ANTHROPIC_API_KEY", native_judge_key)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    cfg = ExperimentConfig(
        dataset=str(tmp_path),
        agent_env={
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_AUTH_TOKEN": "${OPENROUTER_API_KEY}",
        },
    )

    assert cfg.agent_env == {
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_AUTH_TOKEN": "${OPENROUTER_API_KEY}",
    }
    child_env = _build_child_env(cfg)
    assert child_env["ANTHROPIC_API_KEY"] == native_judge_key
    assert "ANTHROPIC_AUTH_TOKEN" not in child_env
