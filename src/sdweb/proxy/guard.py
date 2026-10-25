"""The session origin serves sessions and nothing else.

Requests whose Host is SD_SESSION_HOSTNAME may only reach /<kind>/<job_id>/...
and /_sd/...; the API, the live socket and the app's own pages answer 404 there,
so a job's page can never call the app on its own origin.
"""

from __future__ import annotations

from typing import Any

from starlette.types import ASGIApp, Receive, Scope, Send

from sdweb.proxy.targets import KINDS

ALLOWED_FIRST = frozenset((*KINDS, "_sd"))


def _host(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"host":
            host = value.decode("latin-1").strip().lower()
            return host.rsplit(":", 1)[0] if not host.endswith("]") else host
    return ""


class SessionOriginGuard:
    def __init__(self, app: ASGIApp, session_hostname: str) -> None:
        self.app, self.session_hostname = app, session_hostname

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] in ("http", "websocket") and _host(scope) == self.session_hostname:
            first = scope.get("path", "/").lstrip("/").split("/", 1)[0]
            if first not in ALLOWED_FIRST:
                await self._refuse(scope, send)
                return
        await self.app(scope, receive, send)

    @staticmethod
    async def _refuse(scope: Scope, send: Send) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        headers: list[Any] = [(b"content-type", b"text/plain; charset=utf-8"),
                              (b"cache-control", b"no-store")]
        await send({"type": "http.response.start", "status": 404, "headers": headers})
        await send({"type": "http.response.body", "body": b"Not found"})
