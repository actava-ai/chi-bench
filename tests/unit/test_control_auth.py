"""Trusted control routes reject agent requests before reading or mutating state."""

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chi_bench.server.routers.common import create_common_router

CONTROL_TOKEN = "synthetic-control-token"
PHASE_MARKER = {
    "case_id": "CASE-TEST",
    "action": "enter",
    "logical_phase": "provider_submit",
    "role": "provider",
    "role_phase": "submission",
}
CONTROL_ROUTES = [
    ("GET", "/export"),
    ("POST", "/_oracle/solve"),
    ("POST", "/_admin/phase_marker"),
]


class SyntheticWorldService:
    def __init__(self) -> None:
        self._ctx = self
        self.calls: list[str] = []
        self.phase_markers: list[dict[str, Any]] = []

    def export_state(self) -> dict[str, str]:
        self.calls.append("export")
        return {"state": "synthetic"}

    def run_oracle(self) -> dict[str, bool]:
        self.calls.append("oracle")
        return {"solved": True}

    def stage_trace(self, case_id: str, stage: str, event: str, **metadata: str) -> None:
        self.calls.append("phase_marker")
        self.phase_markers.append({"case_id": case_id, "stage": stage, "event": event, **metadata})


@pytest.fixture
def control_client(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", CONTROL_TOKEN)
    service = SyntheticWorldService()
    router = create_common_router(service)
    app = FastAPI()
    app.include_router(router)
    # The unified app mounts the same common router at both compatibility prefixes.
    app.include_router(router, prefix="/provider", include_in_schema=False)
    app.include_router(router, prefix="/payer", include_in_schema=False)
    with TestClient(app) as client:
        yield client, service


@pytest.mark.parametrize("prefix", ["", "/provider", "/payer"])
@pytest.mark.parametrize("method,path", CONTROL_ROUTES)
@pytest.mark.parametrize(
    "authorization", [None, "Bearer incorrect-token", "Basic synthetic-control-token", "Bearer"]
)
def test_control_routes_require_the_configured_token(
    control_client, prefix, method, path, authorization
):
    client, service = control_client
    headers = {"Authorization": authorization} if authorization else {}

    response = client.request(method, prefix + path, headers=headers, json=PHASE_MARKER)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert service.calls == []
    assert service.phase_markers == []


@pytest.mark.parametrize("prefix", ["", "/provider", "/payer"])
@pytest.mark.parametrize("method,path", CONTROL_ROUTES)
def test_control_routes_preserve_authorized_behavior(control_client, prefix, method, path):
    client, service = control_client

    response = client.request(
        method,
        prefix + path,
        headers={"Authorization": f"Bearer {CONTROL_TOKEN}"},
        json=PHASE_MARKER,
    )

    assert response.status_code == 200
    if path == "/export":
        assert response.json() == {"state": "synthetic"}
        assert service.calls == ["export"]
    elif path == "/_oracle/solve":
        assert response.json() == {"solved": True}
        assert service.calls == ["oracle"]
    else:
        assert response.json() == {"ok": True}
        assert service.calls == ["phase_marker"]
        assert service.phase_markers == [
            {"stage": "e2e_phase_marker", "event": "enter", **PHASE_MARKER}
        ]


@pytest.mark.parametrize("configured_token", [None, ""])
@pytest.mark.parametrize("prefix", ["", "/provider", "/payer"])
@pytest.mark.parametrize("method,path", CONTROL_ROUTES)
def test_control_routes_are_disabled_without_configuration(
    control_client, monkeypatch, configured_token, prefix, method, path
):
    client, service = control_client
    if configured_token is None:
        monkeypatch.delenv("CHI_BENCH_CONTROL_TOKEN")
    else:
        monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", configured_token)

    response = client.request(
        method,
        prefix + path,
        headers={"Authorization": f"Bearer {CONTROL_TOKEN}"},
        json=PHASE_MARKER,
    )

    assert response.status_code == 503
    assert service.calls == []
    assert service.phase_markers == []


@pytest.mark.parametrize("prefix", ["", "/provider", "/payer"])
def test_health_remains_public_without_control_configuration(control_client, monkeypatch, prefix):
    client, service = control_client
    monkeypatch.delenv("CHI_BENCH_CONTROL_TOKEN")

    response = client.get(prefix + "/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert service.calls == []


@pytest.mark.parametrize("configured_token", [None, "", CONTROL_TOKEN])
def test_control_headers_read_current_trusted_configuration(monkeypatch, configured_token):
    from chi_bench.server.control import control_headers

    if configured_token is None:
        monkeypatch.delenv("CHI_BENCH_CONTROL_TOKEN", raising=False)
    else:
        monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", configured_token)

    expected = {"Authorization": f"Bearer {configured_token}"} if configured_token else {}
    assert control_headers() == expected

    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "another-synthetic-token")
    assert control_headers() == {"Authorization": "Bearer another-synthetic-token"}
