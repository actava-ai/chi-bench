"""The trusted orchestrator selects which MCP role can receive agent traffic."""

from contextlib import ExitStack, asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chi_bench.server import control
from chi_bench.server.routers.common import create_common_router


@pytest.fixture
def role_client(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "synthetic-control-token")
    app = FastAPI()
    router = create_common_router(object())
    app.include_router(router)
    app.include_router(router, prefix="/provider", include_in_schema=False)
    app.include_router(router, prefix="/payer", include_in_schema=False)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("prefix", ["", "/provider", "/payer"])
@pytest.mark.parametrize("authorization", [None, "Bearer incorrect-token"])
def test_role_change_requires_control_authentication(role_client, prefix, authorization):
    headers = {"Authorization": authorization} if authorization else {}
    response = role_client.post(
        prefix + "/_admin/agent_role", json={"role": "payer"}, headers=headers
    )
    assert response.status_code == 401


@pytest.mark.parametrize("prefix", ["", "/provider", "/payer"])
def test_role_change_is_disabled_without_control_configuration(role_client, monkeypatch, prefix):
    monkeypatch.delenv("CHI_BENCH_CONTROL_TOKEN")
    response = role_client.post(
        prefix + "/_admin/agent_role",
        json={"role": "payer"},
        headers={"Authorization": "Bearer synthetic-control-token"},
    )
    assert response.status_code == 503


@pytest.mark.parametrize("configured_role", [None, "", "provider", "payer", "cm", "closed"])
def test_agent_access_state_initializes_from_environment(monkeypatch, configured_role):
    if configured_role is None:
        monkeypatch.delenv("CHI_BENCH_AGENT_ROLE", raising=False)
    else:
        monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", configured_role)
    state = control.AgentAccessState()
    assert state.role == (configured_role or None)
    for role in ("provider", "payer", "cm"):
        assert state.permits(role) is (not configured_role or role == configured_role)


def test_invalid_initial_agent_role_fails_closed(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "unknown")
    with pytest.raises(ValueError, match="role"):
        control.AgentAccessState()


@pytest.mark.parametrize("authorization", [None, "Bearer incorrect-token"])
def test_unauthorized_role_change_cannot_mutate_shared_state(
    role_client, monkeypatch, authorization
):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "provider")
    state = control.AgentAccessState()
    monkeypatch.setattr(control, "agent_access_state", state)
    headers = {"Authorization": authorization} if authorization else {}

    response = role_client.post("/_admin/agent_role", json={"role": "payer"}, headers=headers)

    assert response.status_code == 401
    assert state.role == "provider"


def test_authorized_role_changes_update_running_mcp_access(role_client, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "provider")
    state = control.AgentAccessState()
    monkeypatch.setattr(control, "agent_access_state", state)
    with ExitStack() as stack:
        clients = {}
        for role in ("provider", "payer", "cm"):
            app = FastAPI()

            @app.get("/")
            def mcp_response():
                return {"ok": True}

            middleware = control.AgentRoleMiddleware(app, role=role, state=state)
            clients[role] = stack.enter_context(TestClient(middleware))

        for active_role in ("provider", "payer", "cm", "closed"):
            response = role_client.post(
                "/_admin/agent_role",
                json={"role": active_role},
                headers={"Authorization": "Bearer synthetic-control-token"},
            )
            assert response.status_code == 200
            assert response.json() == {"ok": True}
            assert state.role == active_role
            for role, client in clients.items():
                assert client.get("/").status_code == (200 if role == active_role else 403)


def test_invalid_role_change_does_not_mutate_shared_state(role_client, monkeypatch):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "provider")
    state = control.AgentAccessState()
    monkeypatch.setattr(control, "agent_access_state", state)

    response = role_client.post(
        "/_admin/agent_role",
        json={"role": "unrestricted"},
        headers={"Authorization": "Bearer synthetic-control-token"},
    )

    assert response.status_code == 422
    assert state.role == "provider"


def test_mcp_lifespan_passes_through_while_http_access_is_closed(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "closed")
    state = control.AgentAccessState()
    events = []

    @asynccontextmanager
    async def lifespan(app):
        events.append("startup")
        yield
        events.append("shutdown")

    app = FastAPI(lifespan=lifespan)
    middleware = control.AgentRoleMiddleware(app, role="provider", state=state)
    with TestClient(middleware) as client:
        assert events == ["startup"]
        assert client.post("/mcp", json={"method": "tools/list"}).status_code == 403
    assert events == ["startup", "shutdown"]


def test_mcp_middleware_uses_shared_state_by_default(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "payer")
    state = control.AgentAccessState()
    monkeypatch.setattr(control, "agent_access_state", state)
    app = FastAPI()

    @app.get("/")
    def mcp_response():
        return {"ok": True}

    with TestClient(control.AgentRoleMiddleware(app, role="provider")) as client:
        assert client.get("/").status_code == 403
        state.set_role("provider")
        assert client.get("/").status_code == 200


@pytest.mark.parametrize("active_role", ["provider", "closed"])
@pytest.mark.parametrize("mcp_role", ["provider", "payer", "cm"])
@pytest.mark.parametrize(
    "authorization, trusted",
    [
        (None, False),
        ("Bearer incorrect-token", False),
        ("Basic synthetic-control-token", False),
        ("Bearer synthetic-control-token", True),
    ],
)
def test_only_trusted_control_requests_bypass_the_mcp_role_gate(
    monkeypatch, active_role, mcp_role, authorization, trusted
):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", active_role)
    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "synthetic-control-token")
    state = control.AgentAccessState()
    app = FastAPI()

    @app.get("/")
    def mcp_response():
        return {"ok": True}

    middleware = control.AgentRoleMiddleware(app, role=mcp_role, state=state)
    with TestClient(middleware) as client:
        headers = {"Authorization": authorization} if authorization else {}
        response = client.get("/", headers=headers)

    permitted = trusted or active_role == mcp_role
    assert response.status_code == (200 if permitted else 403)
    assert state.role == active_role


def test_mcp_control_bypass_is_disabled_without_token_configuration(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "closed")
    monkeypatch.delenv("CHI_BENCH_CONTROL_TOKEN", raising=False)
    state = control.AgentAccessState()
    app = FastAPI()

    @app.get("/")
    def mcp_response():
        return {"ok": True}

    middleware = control.AgentRoleMiddleware(app, role="provider", state=state)
    with TestClient(middleware) as client:
        response = client.get("/", headers={"Authorization": "Bearer synthetic-control-token"})

    assert response.status_code == 403
    assert state.role == "closed"
