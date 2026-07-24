import pytest
from harbor.models.task.config import NetworkMode, NetworkPolicy, TaskConfig
from harbor.models.trial.paths import TrialPaths

import chi_bench.experiment.modal_env as modal_env
from chi_bench.experiment.modal_env import ChiBenchModalEnvironment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("allow_internet", "expected_block_network"),
    [(True, False), (False, True)],
)
async def test_create_sandbox_uses_harbor_migrated_network_policy(
    monkeypatch,
    tmp_path,
    allow_internet,
    expected_block_network,
):
    with pytest.warns(DeprecationWarning, match="'allow_internet' field is deprecated"):
        task_config = TaskConfig.model_validate({"environment": {"allow_internet": allow_internet}})
    assert task_config.environment.allow_internet is None

    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    (environment_dir / "docker-compose.yaml").touch()
    environment = ChiBenchModalEnvironment(
        environment_dir=environment_dir,
        environment_name="task",
        session_id="task__trial__env",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=task_config.environment,
        network_policy=task_config.environment.resolve_baseline(),
    )
    assert environment._compose_mode is False
    assert environment.capabilities.disable_internet is True
    assert environment.capabilities.network_allowlist is False
    assert environment.capabilities.dynamic_network_policy is False

    app = object()
    environment._app = app
    environment._image = object()

    create_kwargs = {}
    sandbox = object()

    class FakeCreate:
        @staticmethod
        async def aio(**kwargs):
            create_kwargs.update(kwargs)
            return sandbox

    class FakeSandbox:
        create = FakeCreate()

    monkeypatch.setattr(modal_env, "Sandbox", FakeSandbox)
    monkeypatch.setattr(modal_env, "_collect_forwarded_env", lambda: {})
    monkeypatch.setattr(modal_env, "_register_sandbox", lambda _sandbox: None)

    result = await environment._create_sandbox(
        gpu_config=None,
        secrets_config=[],
        volumes_config={},
    )

    assert result is sandbox
    assert create_kwargs["app"] is app
    assert create_kwargs["block_network"] is expected_block_network


def test_constructor_rejects_unsupported_network_allowlist(tmp_path):
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    (environment_dir / "docker-compose.yaml").touch()

    with pytest.raises(ValueError, match="network_mode='allowlist' is not supported"):
        ChiBenchModalEnvironment(
            environment_dir=environment_dir,
            environment_name="task",
            session_id="task__trial__env",
            trial_paths=TrialPaths(tmp_path / "trial"),
            task_env_config=TaskConfig().environment,
            network_policy=NetworkPolicy(
                network_mode=NetworkMode.ALLOWLIST,
                allowed_hosts=["api.anthropic.com"],
            ),
        )


@pytest.mark.asyncio
async def test_runtime_network_policy_change_fails_closed(tmp_path):
    environment_dir = tmp_path / "environment"
    environment_dir.mkdir()
    (environment_dir / "docker-compose.yaml").touch()
    environment = ChiBenchModalEnvironment(
        environment_dir=environment_dir,
        environment_name="task",
        session_id="task__trial__env",
        trial_paths=TrialPaths(tmp_path / "trial"),
        task_env_config=TaskConfig().environment,
        network_policy=NetworkPolicy(network_mode=NetworkMode.PUBLIC),
    )

    with pytest.raises(ValueError, match="cannot change network policy after start"):
        await environment.set_network_policy(NetworkPolicy(network_mode=NetworkMode.NO_NETWORK))
