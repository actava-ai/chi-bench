"""Apply the active agent role to the canonical business HTTP routes."""

from typing import cast

from starlette.types import ASGIApp, Receive, Scope, Send

from chi_bench.server.control import AgentRoleMiddleware, MCPRole


class BusinessRoleMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            parts = scope.get("path", "").split("/", 2)
            role = parts[1]
            suffix = parts[2] if len(parts) > 2 else ""
            common = suffix in ("health", "export") or suffix.startswith("_admin/")
            if role in ("provider", "payer", "cm") and not common:
                await AgentRoleMiddleware(self.app, cast(MCPRole, role), track_work=True)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)
