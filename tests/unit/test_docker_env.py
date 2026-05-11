from chi_bench.experiment.docker_env import (
    DEFAULT_IMAGE,
    FORWARDED_ENV_KEYS,
    build_docker_exec_argv,
    build_docker_run_argv,
    sanitize_container_name,
)


def test_build_docker_run_argv_default_shape():
    argv = build_docker_run_argv(
        image=DEFAULT_IMAGE,
        container_name="pa_t008__abc123",
        task_id="pa_t008_t008_o002_p01_mdreview_payer",
        host_env={
            "ANTHROPIC_API_KEY": "ak-anthropic",
            "OPENROUTER_API_KEY": "ak-openrouter",
        },
        allow_internet=True,
    )
    assert argv[:4] == ["docker", "run", "-d", "--name"]
    assert "pa_t008__abc123" in argv
    flat = " ".join(argv)
    assert "-e CHI_BENCH_TASK_ID=pa_t008_t008_o002_p01_mdreview_payer" in flat
    assert "-e ANTHROPIC_API_KEY=ak-anthropic" in flat
    assert "-e OPENROUTER_API_KEY=ak-openrouter" in flat
    # Trailing image is the docker run target.
    assert argv[-1] == DEFAULT_IMAGE
    # allow_internet=True means no --network none flag.
    assert "--network" not in argv


def test_build_docker_run_argv_no_internet_adds_network_none():
    argv = build_docker_run_argv(
        image="chi-bench:test",
        container_name="t",
        task_id="t",
        host_env={},
        allow_internet=False,
    )
    flat = " ".join(argv)
    assert "--network none" in flat


def test_build_docker_run_argv_forwards_only_known_nonempty_keys():
    host_env = {
        "ANTHROPIC_API_KEY": "ak",
        "OPENAI_API_KEY": "",  # empty -> skipped
        "IRRELEVANT_KEY": "v",  # not in allowlist -> skipped
    }
    argv = build_docker_run_argv(
        image="chi-bench:latest",
        container_name="t",
        task_id="t",
        host_env=host_env,
        allow_internet=True,
    )
    flat = " ".join(argv)
    assert "ANTHROPIC_API_KEY=ak" in flat
    assert "OPENAI_API_KEY=" not in flat
    assert "IRRELEVANT_KEY" not in flat


def test_build_docker_run_argv_extra_env_wins():
    argv = build_docker_run_argv(
        image="chi-bench:latest",
        container_name="t",
        task_id="t",
        host_env={"ANTHROPIC_API_KEY": "from-host"},
        allow_internet=True,
        extra_env={"CHI_BENCH_TOOL_MODE": "cli", "ANTHROPIC_API_KEY": "from-task"},
    )
    flat = " ".join(argv)
    # Both appear; the later (extra_env) one is what docker uses for duplicate -e flags.
    assert "ANTHROPIC_API_KEY=from-host" in flat
    assert "ANTHROPIC_API_KEY=from-task" in flat
    host_idx = argv.index("ANTHROPIC_API_KEY=from-host")
    task_idx = argv.index("ANTHROPIC_API_KEY=from-task")
    assert host_idx < task_idx, "extra_env must come after host_env in -e order"
    assert "CHI_BENCH_TOOL_MODE=cli" in flat


def test_build_docker_exec_argv_shape():
    argv = build_docker_exec_argv(
        container_name="t",
        command="ls /workspace",
        cwd="/workspace",
        env={"FOO": "bar"},
        user="agent",
    )
    assert argv[:2] == ["docker", "exec"]
    assert "-w" in argv and "/workspace" in argv
    assert "-e" in argv and "FOO=bar" in argv
    assert "-u" in argv and "agent" in argv
    # ``bash -c "<command>"`` at the tail (matches harbor's docker_unix plugin).
    assert argv[-3:] == ["bash", "-c", "ls /workspace"]
    # Container name is the positional before the shell invocation.
    assert argv[-4] == "t"


def test_build_docker_exec_argv_no_optional_flags_when_unset():
    argv = build_docker_exec_argv(container_name="t", command="true")
    assert "-w" not in argv
    assert "-e" not in argv
    assert "-u" not in argv
    assert argv[-3:] == ["bash", "-c", "true"]


def test_sanitize_container_name_replaces_invalid_chars():
    # session_id typically looks like ``<task>__<slug>``; both are already valid.
    assert sanitize_container_name("pa_t008__abc-123") == "pa_t008__abc-123"
    # Slashes / colons / spaces get scrubbed.
    assert sanitize_container_name("foo/bar:baz qux") == "foo_bar_baz_qux"
    # Leading non-alnum gets an alnum prefix.
    assert sanitize_container_name("__weird").startswith("c_")
    # Length is capped to 64 (docker container-name limit).
    long_name = "a" * 200
    assert len(sanitize_container_name(long_name)) == 64


def test_forwarded_env_keys_match_modal_critical_subset():
    """Provider/judge keys both backends need must stay in sync."""
    critical = {
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "OPENROUTER_API_KEY",
        "CHI_BENCH_TOOL_MODE",
        "CHI_BENCH_SKILLS_ABLATE",
        "CLAUDE_CODE_OAUTH_TOKEN",
    }
    assert critical.issubset(set(FORWARDED_ENV_KEYS))
