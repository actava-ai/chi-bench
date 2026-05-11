from pathlib import Path


from chi_bench.experiment.docker_env import ChiBenchDockerEnvironment


def test_docker_env_resolves_task_id_from_task_path():
    # task_path matches the dataset layout: data/<domain>/tasks/<task_id>/
    task_path = Path("/repo/data/prior_auth_um/tasks/pa_t008_t008_o002_p01_mdreview_payer")
    env = ChiBenchDockerEnvironment(task_path=task_path, image="chi-bench:latest")
    assert env.task_id == "pa_t008_t008_o002_p01_mdreview_payer"


def test_docker_env_builds_docker_run_argv():
    task_path = Path("/repo/data/care_management/tasks/cm_afib_moderate_anxious_001")
    env = ChiBenchDockerEnvironment(
        task_path=task_path,
        image="chi-bench:latest",
        host_env={
            "ANTHROPIC_API_KEY": "ak-anthropic",
            "OPENROUTER_API_KEY": "ak-openrouter",
        },
        trial_artifacts_dir=Path("/tmp/trial-xyz"),
    )
    argv = env.build_docker_run_argv(agent_command=["sleep", "1"])
    assert argv[:2] == ["docker", "run"]
    assert "--rm" in argv
    flat = " ".join(argv)
    assert "-e CHI_BENCH_TASK_ID=cm_afib_moderate_anxious_001" in flat
    assert "-e ANTHROPIC_API_KEY=ak-anthropic" in flat
    assert "-e OPENROUTER_API_KEY=ak-openrouter" in flat
    assert "chi-bench:latest" in argv
    # The agent command appears verbatim at the tail.
    assert argv[-2:] == ["sleep", "1"]
