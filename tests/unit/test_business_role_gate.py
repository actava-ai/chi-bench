from types import SimpleNamespace

from fastapi import APIRouter
from fastapi.testclient import TestClient


def test_business_http_cannot_bypass_active_mcp_role(monkeypatch):
    import chi_bench.server.app as server
    from chi_bench.server.control import agent_access_state

    def provider_router(service):
        router = APIRouter()

        @router.get("/visible")
        def visible():
            return {"patient": "public-for-provider"}

        return router

    monkeypatch.setattr(server, "create_provider_router", provider_router)
    monkeypatch.setattr(server, "create_payer_router", lambda service: APIRouter())
    monkeypatch.setattr(server, "create_cm_router", lambda service: APIRouter())
    monkeypatch.setattr(agent_access_state, "role", "payer")
    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "test-control")
    with TestClient(server.create_unified_app(SimpleNamespace(close=lambda: None))) as client:
        assert client.get("/provider/visible").status_code == 403
        assert client.get("/health").status_code == 200
        assert (
            client.get(
                "/provider/visible", headers={"Authorization": "Bearer test-control"}
            ).status_code
            == 200
        )
        agent_access_state.set_role("provider")
        assert client.get("/provider/visible").status_code == 200
        agent_access_state.set_role("closed")
        assert client.get("/provider/visible").status_code == 403
