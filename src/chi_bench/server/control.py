"""Authentication for simulator endpoints reserved for trusted runtime processes."""

from __future__ import annotations

import asyncio
import hmac
import inspect
import os
import threading
import time
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Annotated, Any, Literal, TypeVar, cast

from fastapi import Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from starlette.types import ASGIApp, Receive, Scope, Send

CONTROL_TOKEN_ENV = "CHI_BENCH_CONTROL_TOKEN"
AGENT_ROLE_ENV = "CHI_BENCH_AGENT_ROLE"
QUIESCENCE_TIMEOUT_SEC = 120.0
MCPRole = Literal["provider", "payer", "cm"]
AgentRole = Literal["provider", "payer", "cm", "closed"]
_MCP_ROLES = ("provider", "payer", "cm")
_bearer = HTTPBearer(auto_error=False)
_T = TypeVar("_T")


class AgentAccessState:
    """Shared role selection for the unified server and its MCP server threads."""

    def __init__(self) -> None:
        role = os.environ.get(AGENT_ROLE_ENV) or None
        if role is not None and role not in (*_MCP_ROLES, "closed"):
            raise ValueError("Invalid agent role configuration")
        self.role = cast(AgentRole | None, role)
        self._lock = threading.Lock()
        self._active = 0
        self._generation = 0
        self._workers: set[asyncio.Task[Any]] = set()

    def set_role(self, role: AgentRole) -> None:
        if role not in (*_MCP_ROLES, "closed"):
            raise ValueError("Invalid agent role")
        with self._lock:
            if self._active:
                raise RuntimeError("Use change_role to drain active agent work")
            self._generation += 1
            self.role = role

    def permits(self, role: MCPRole) -> bool:
        with self._lock:
            return self._permits(role)

    def _permits(self, role: MCPRole) -> bool:
        return role in _MCP_ROLES and (self.role is None or self.role == role)

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active

    def _admit(self, role: MCPRole, trusted: bool) -> None:
        with self._lock:
            if not trusted and not self._permits(role):
                raise HTTPException(status_code=403, detail="Agent role is not active")
            self._active += 1

    def _finish(self) -> None:
        with self._lock:
            self._active -= 1

    async def change_role(
        self, role: AgentRole, *, timeout_sec: float = QUIESCENCE_TIMEOUT_SEC
    ) -> None:
        """Close admission, drain admitted calls, then activate the requested role.

        Polling under a thread lock works across the HTTP and MCP event loops.
        Timeout, cancellation, and superseding transitions never reopen this
        transition's requested role.
        """
        if role not in (*_MCP_ROLES, "closed"):
            raise ValueError("Invalid agent role")
        with self._lock:
            self.role = "closed"
            self._generation += 1
            generation = self._generation
        deadline = time.monotonic() + timeout_sec
        while True:
            with self._lock:
                if generation != self._generation:
                    raise HTTPException(status_code=409, detail="Agent role change was superseded")
                if self._active == 0:
                    self.role = role
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise HTTPException(status_code=503, detail="Agent work did not become quiescent")
            await asyncio.sleep(min(0.01, remaining))

    async def run(
        self, role: MCPRole, operation: Callable[[], Awaitable[_T]], *, trusted: bool = False
    ) -> _T:
        """Track the worker itself even if its transport caller is cancelled."""
        self._admit(role, trusted)

        async def execute() -> _T:
            try:
                result = await operation()
            except asyncio.CancelledError:
                # Worker cancellation can abandon an underlying thread. Keep
                # its admission unresolved so a snapshot cannot claim idle.
                raise
            except BaseException:
                self._finish()
                raise
            else:
                self._finish()
                return result

        worker = asyncio.create_task(execute())
        with self._lock:
            self._workers.add(worker)

        def completed(task: asyncio.Task[Any]) -> None:
            with self._lock:
                self._workers.discard(task)
            if not task.cancelled():
                task.exception()  # Observe errors after a disconnected caller.

        worker.add_done_callback(completed)
        return await asyncio.shield(worker)


agent_access_state = AgentAccessState()


class AgentRoleBody(BaseModel):
    role: AgentRole


class AgentRoleMiddleware:
    """Check the current role before admitting each MCP HTTP request.

    All server threads use ``agent_access_state`` unless a state is supplied.
    A valid control token admits trusted readiness and diagnostic requests
    regardless of the selected agent role.
    Lifespan and other ASGI scopes pass through to the wrapped MCP application.
    """

    def __init__(
        self,
        app: ASGIApp,
        role: MCPRole,
        state: AgentAccessState | None = None,
        *,
        track_work: bool = False,
    ) -> None:
        if role not in _MCP_ROLES:
            raise ValueError("Invalid MCP role")
        self.app = app
        self.role = role
        self.state = state if state is not None else agent_access_state
        self.track_work = track_work

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            trusted = _valid_control_authorization(Request(scope).headers.get("authorization"))
            try:
                if self.track_work:
                    await self.state.run(
                        self.role, lambda: self.app(scope, receive, send), trusted=trusted
                    )
                    return
                if not trusted and not self.state.permits(self.role):
                    raise HTTPException(status_code=403)
            except HTTPException:
                response = JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "MCP role is not active"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _valid_control_authorization(authorization: str | None) -> bool:
    token = os.environ.get(CONTROL_TOKEN_ENV)
    if not token or not authorization:
        return False
    scheme, _, value = authorization.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(value.encode(), token.encode())


def _trusted_mcp_request() -> bool:
    # Streamable HTTP runs tool handlers in its session task, outside the
    # transport middleware task. Read the SDK's per-message request context.
    from mcp.server.lowlevel.server import request_ctx

    try:
        request = request_ctx.get().request
    except LookupError:
        return False
    return isinstance(request, Request) and _valid_control_authorization(
        request.headers.get("authorization")
    )


def track_agent_tool(target: Callable[..., Any], role: MCPRole) -> Callable[..., Any]:
    """Wrap an MCP callable, preserving its signature and sync/async identity."""
    if inspect.iscoroutinefunction(target):

        @wraps(target)
        async def async_tool(*args: Any, **kwargs: Any) -> Any:
            return await agent_access_state.run(
                role, lambda: target(*args, **kwargs), trusted=_trusted_mcp_request()
            )

        return async_tool

    @wraps(target)
    def sync_tool(*args: Any, **kwargs: Any) -> Any:
        state = agent_access_state
        state._admit(role, _trusted_mcp_request())
        try:
            return target(*args, **kwargs)
        finally:
            state._finish()

    return sync_tool


def control_headers() -> dict[str, str]:
    """Build control-request headers from the current trusted process environment.

    No token is generated or cached. An absent or empty configuration returns
    an empty mapping; the server disables privileged routes in that state.
    Only trusted runtime processes should receive this environment variable.
    """
    token = os.environ.get(CONTROL_TOKEN_ENV)
    return {"Authorization": f"Bearer {token}"} if token else {}


def require_control_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> None:
    """Reject requests before control handlers run, including if unconfigured."""
    token = os.environ.get(CONTROL_TOKEN_ENV)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trusted control endpoints are disabled",
        )
    if credentials is None or not hmac.compare_digest(
        credentials.credentials.encode(), token.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid control credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
