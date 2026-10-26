"""Closing agent admission waits for the work that can still mutate state."""

import asyncio
import inspect
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from chi_bench.server import control
from chi_bench.server.role_gate import BusinessRoleMiddleware
from chi_bench.server.routers.common import create_common_router


@pytest.fixture
def access(monkeypatch):
    monkeypatch.setenv("CHI_BENCH_AGENT_ROLE", "provider")
    monkeypatch.setenv("CHI_BENCH_CONTROL_TOKEN", "synthetic-control")
    state = control.AgentAccessState()
    monkeypatch.setattr(control, "agent_access_state", state)
    return state


def business_app(endpoint):
    app = FastAPI()
    app.add_middleware(BusinessRoleMiddleware)
    app.post("/provider/write")(endpoint)
    common = create_common_router(SimpleNamespace(export_state=lambda: {}))
    app.include_router(common)
    app.include_router(common, prefix="/provider")
    return app


@pytest.mark.asyncio
async def test_role_change_drains_admitted_http_work_before_activating_next_role(access):
    started, release = asyncio.Event(), asyncio.Event()
    writes = []

    async def write():
        started.set()
        await release.wait()
        writes.append("finished")
        return {"ok": True}

    app = business_app(write)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        work = asyncio.create_task(client.post("/provider/write"))
        await asyncio.wait_for(started.wait(), 1)
        close = asyncio.create_task(
            client.post(
                "/provider/_admin/agent_role",
                json={"role": "payer"},
                headers=control.control_headers(),
            )
        )
        try:
            await asyncio.sleep(0.03)
            assert not close.done(), "Role change returned while admitted work could still write"
            assert access.role == "closed"
            assert (await client.post("/provider/write")).status_code == 403
            assert (await client.get("/provider/health")).status_code == 200
            assert (
                await client.get("/provider/export", headers=control.control_headers())
            ).status_code == 200
        finally:
            release.set()
            await work
            response = await close
        assert response.status_code == 200
        assert writes == ["finished"]
        assert access.role == "payer"


@pytest.mark.asyncio
async def test_cancelled_http_client_does_not_hide_running_sync_endpoint(access):
    started, release = threading.Event(), threading.Event()
    writes = []

    def write():
        started.set()
        assert release.wait(3)
        writes.append("finished")
        return {"ok": True}

    app = business_app(write)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        work = asyncio.create_task(client.post("/provider/write"))
        assert await asyncio.to_thread(started.wait, 1)
        work.cancel()
        close = asyncio.create_task(access.change_role("closed", timeout_sec=1))
        try:
            await asyncio.sleep(0.03)
            assert not close.done()
        finally:
            release.set()
            await asyncio.gather(work, return_exceptions=True)
            await close
        assert writes == ["finished"]
        assert access.active_count == 0


def registered_mcp(monkeypatch, role, target):
    from chi_bench.mcp import cm_server, payer_server, server

    ctx = SimpleNamespace(provider_services=lambda: {"synthetic": SimpleNamespace(write=target)})
    monkeypatch.setattr(
        payer_server, "_agent_tool_specs", lambda ctx: [("synthetic.write", target)]
    )
    monkeypatch.setattr(cm_server, "_cm_tool_specs", lambda ctx: [("synthetic.write", target)])
    builder = {
        "provider": server.build_provider_mcp,
        "payer": payer_server.build_payer_mcp,
        "cm": cm_server.build_cm_mcp,
    }[role]
    return builder(ctx=ctx)._tool_manager.get_tool("synthetic.write")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["provider", "payer", "cm"])
@pytest.mark.parametrize("is_async", [False, True])
async def test_registered_mcp_callable_is_tracked_until_actual_completion(
    access, monkeypatch, role, is_async
):
    access.set_role(role)
    started, release = threading.Event(), threading.Event()
    writes = []

    def sync_write(value: str = "late") -> str:
        started.set()
        assert release.wait(3)
        writes.append(value)
        return value

    async def async_write(value: str = "late") -> str:
        started.set()
        await asyncio.to_thread(release.wait, 3)
        writes.append(value)
        return value

    target = async_write if is_async else sync_write
    tool = registered_mcp(monkeypatch, role, target)
    assert inspect.signature(tool.fn) == inspect.signature(target)
    assert inspect.iscoroutinefunction(tool.fn) is is_async
    if is_async:
        work = asyncio.create_task(tool.run({"value": "late"}))
    else:
        work = asyncio.create_task(
            asyncio.to_thread(lambda: asyncio.run(tool.run({"value": "late"})))
        )
    assert await asyncio.to_thread(started.wait, 1)
    work.cancel()
    await asyncio.gather(work, return_exceptions=True)
    close = asyncio.create_task(access.change_role("closed", timeout_sec=1))
    try:
        await asyncio.sleep(0.03)
        assert not close.done(), "MCP transport completion must not hide its worker"
        assert access.active_count == 1
    finally:
        release.set()
        await asyncio.gather(work, return_exceptions=True)
        await close
    assert writes == ["late"]
    assert access.active_count == 0
    with pytest.raises(Exception, match="role"):
        await tool.run({"value": "denied"})
    assert writes == ["late"]


@pytest.mark.asyncio
async def test_drain_timeout_and_cancelled_transition_remain_closed(access):
    started, release = asyncio.Event(), asyncio.Event()

    async def write():
        started.set()
        await release.wait()

    wrapped = control.track_agent_tool(write, "provider")
    work = asyncio.create_task(wrapped())
    await started.wait()
    try:
        with pytest.raises(HTTPException) as failure:
            await access.change_role("payer", timeout_sec=0.02)
        assert failure.value.status_code == 503
        assert access.role == "closed"
        assert access.active_count == 1
        transition = asyncio.create_task(access.change_role("payer", timeout_sec=1))
        await asyncio.sleep(0.01)
        transition.cancel()
        with pytest.raises(asyncio.CancelledError):
            await transition
        assert access.role == "closed"
    finally:
        release.set()
        await work
    assert access.role == "closed"
    await access.change_role("payer", timeout_sec=0.02)
    assert access.role == "payer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "authorization, trusted",
    [
        (None, False),
        ("Bearer wrong", False),
        ("Basic synthetic-control", False),
        ("Bearer synthetic-control", True),
    ],
)
async def test_registered_tool_uses_per_message_trusted_control_header(
    access, monkeypatch, authorization, trusted
):
    from mcp.server.lowlevel.server import request_ctx
    from starlette.requests import Request

    access.set_role("closed")

    def write(value: str) -> str:
        return value

    tool = registered_mcp(monkeypatch, "cm", write)
    headers = [(b"authorization", authorization.encode())] if authorization else []
    token = request_ctx.set(SimpleNamespace(request=Request({"type": "http", "headers": headers})))
    try:
        if trusted:
            assert await tool.run({"value": "trusted"}) == "trusted"
        else:
            with pytest.raises(Exception, match="role"):
                await tool.run({"value": "denied"})
        assert access.active_count == 0
    finally:
        request_ctx.reset(token)


@pytest.mark.asyncio
async def test_cancelled_worker_never_declares_an_abandoned_thread_idle(access):
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def write():
        started.set()
        assert release.wait(3)
        finished.set()

    async def operation():
        await asyncio.to_thread(write)

    work = asyncio.create_task(control.track_agent_tool(operation, "provider")())
    assert await asyncio.to_thread(started.wait, 1)
    worker = next(iter(access._workers))
    worker.cancel()
    await asyncio.gather(work, return_exceptions=True)
    try:
        with pytest.raises(HTTPException) as failure:
            await access.change_role("payer", timeout_sec=0.02)
        assert failure.value.status_code == 503
        assert access.role == "closed"
        assert access.active_count == 1
    finally:
        release.set()
        assert await asyncio.to_thread(finished.wait, 1)
    # Cancellation does not prove a backend finished all detached work. This
    # server instance must remain fail closed, including on a later retry.
    with pytest.raises(HTTPException):
        await access.change_role("payer", timeout_sec=0.02)


@pytest.mark.asyncio
async def test_concurrent_role_changes_do_not_reopen_a_superseded_role(access):
    started, release = asyncio.Event(), asyncio.Event()

    async def operation():
        started.set()
        await release.wait()

    work = asyncio.create_task(control.track_agent_tool(operation, "provider")())
    await started.wait()
    first = asyncio.create_task(access.change_role("payer", timeout_sec=1))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(access.change_role("cm", timeout_sec=1))
    try:
        with pytest.raises(HTTPException) as failure:
            await first
        assert failure.value.status_code == 409
        assert access.role == "closed"
    finally:
        release.set()
        await work
        await second
    assert access.role == "cm"


@pytest.mark.asyncio
async def test_authenticated_role_endpoint_reports_drain_timeout(access, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def write():
        started.set()
        await release.wait()
        return {"ok": True}

    change_role = access.change_role

    async def bounded_change(role):
        await change_role(role, timeout_sec=0.02)

    monkeypatch.setattr(access, "change_role", bounded_change)
    app = business_app(write)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        work = asyncio.create_task(client.post("/provider/write"))
        await started.wait()
        try:
            response = await client.post(
                "/_admin/agent_role", json={"role": "payer"}, headers=control.control_headers()
            )
            assert response.status_code == 503
            assert access.role == "closed"
            assert (await client.post("/provider/write")).status_code == 403
        finally:
            release.set()
            await work


@pytest.mark.asyncio
async def test_host_control_transport_timeout_exceeds_server_drain_budget():
    from harbor.environments.base import ExecResult

    from chi_bench.experiment.docker_env import ChiBenchDockerEnvironment

    environment = object.__new__(ChiBenchDockerEnvironment)
    environment.exec_control = AsyncMock(
        return_value=ExecResult(return_code=0, stdout='{"ok": true}', stderr="")
    )
    assert await environment.control_request("/_admin/agent_role", {"role": "closed"}) == {
        "ok": True
    }
    call = environment.exec_control.call_args
    assert "urlopen(req,timeout=135)" in call.args[0]
    assert call.kwargs["timeout_sec"] == 150
    assert 150 > 135 > control.QUIESCENCE_TIMEOUT_SEC
