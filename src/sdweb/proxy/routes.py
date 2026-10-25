"""/notebook, /tensorboard and /terminal: HTTP and WebSocket proxy to the job.

The session is checked on every request and WebSocket upgrade. The job gets
its own token, never the platform cookie or CSRF header, and a Location that
names the job's own address is rewritten to the public one. CSRF is not
checked here: the app inside the job has its own XSRF/token handling, and the
cookie is SameSite=Strict.
"""

from __future__ import annotations

import asyncio
import contextlib
import weakref
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException
from websockets.typing import Origin, Subprotocol

from sdweb.auth.sessions import peek_session
from sdweb.deps import COOKIE, ApiError, SessionCtx, current_session
from sdweb.models import Account
from sdweb.proxy import pages
from sdweb.proxy.targets import KINDS, ProxyPage, Target, forget, resolve

router = APIRouter()

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
              "trailer", "trailers", "transfer-encoding", "upgrade"}
DROP_REQUEST = HOP_BY_HOP | {"host", "cookie", "x-csrf-token", "authorization", "x-sd-token"}
DROP_WS = DROP_REQUEST | {"origin", "sec-websocket-key", "sec-websocket-version",
                          "sec-websocket-extensions", "sec-websocket-protocol",
                          "sec-websocket-accept"}
UPSTREAM_TIMEOUT = httpx.Timeout(None, connect=10.0)
NOT_RESPONDING = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError,
                  httpx.ReadError)
PATH_SAFE = "/:@!$&'()*+,;=-._~%"


_CLIENTS: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    weakref.WeakKeyDictionary())


def _client() -> httpx.AsyncClient:
    """One pooled client per event loop (a single one when serving; tests run
    each request on its own loop)."""
    loop = asyncio.get_running_loop()
    client = _CLIENTS.get(loop)
    if client is None:
        client = _CLIENTS[loop] = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT,
                                                    follow_redirects=False)
    return client


def strip_session_cookie(header: str) -> str:
    """The Cookie header without the platform's own cookie."""
    kept = [p.strip() for p in header.split(";")
            if p.strip() and p.strip().split("=", 1)[0] != COOKIE]
    return "; ".join(kept)


def rewrite_location(location: str, target: Target, prefix: str, public_host: str) -> str:
    """A redirect from the job, kept under /<kind>/<job_id>/. An absolute URL
    to the job's own address becomes the public origin; other absolute URLs
    are left alone."""
    parts = urlsplit(location)
    if parts.netloc and parts.netloc != target.netloc:
        return location
    path = parts.path or "/"
    if not path.startswith(prefix):
        path = prefix.rstrip("/") + path
    out = path + (f"?{parts.query}" if parts.query else "") \
        + (f"#{parts.fragment}" if parts.fragment else "")
    return f"https://{public_host}{out}" if parts.netloc else out


def _upstream_url(target: Target, kind: str, job_id: str, path: str, query: str,
                  scheme: str = "http") -> str:
    base = target.base.replace("http://", f"{scheme}://", 1)
    url = f"{base}/{kind}/{job_id}/{quote(path, safe=PATH_SAFE)}"
    return f"{url}?{query}" if query else url


def _page_response(page: ProxyPage, job_id: str) -> Response:
    if page.name == "not_responding":
        return pages.not_responding(job_id)
    return {"starting": pages.starting, "ended": pages.ended, "forbidden": pages.forbidden,
            "not_found": pages.not_found}[page.name]()


def _authorize(request: Request, kind: str,
               job_id: str) -> tuple[SessionCtx, Target | ProxyPage] | Response:
    """Session and ownership, on a worker thread (the database and deck-agent
    clients are blocking). Signed-out browsers are sent to sign in."""
    app = request.app
    with app.state.sessionmaker() as db:
        try:
            ctx = current_session(request, db, app.state.settings, app.state.clock())
        except ApiError:
            nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/sign-in?next={quote(nxt, safe='')}", status_code=302)
        db.expunge_all()
    return ctx, resolve(ctx, kind, job_id, app)


def _handler(kind: str) -> Callable[..., Any]:
    async def proxy(job_id: str, path: str, request: Request) -> Response:
        auth = await run_in_threadpool(_authorize, request, kind, job_id)
        if isinstance(auth, Response):
            return auth
        ctx, target = auth
        if isinstance(target, ProxyPage):
            return _page_response(target, job_id)
        headers = [(k, v) for k, v in request.headers.items() if k.lower() not in DROP_REQUEST]
        cookie = strip_session_cookie(request.headers.get("cookie", ""))
        if cookie:
            headers.append(("cookie", cookie))
        headers += [*target.auth_headers.items(), ("host", target.netloc)]
        has_body = request.method not in ("GET", "HEAD", "OPTIONS")
        client = _client()
        upstream_request = client.build_request(
            request.method, _upstream_url(target, kind, job_id, path, request.url.query),
            headers=headers, content=request.stream() if has_body else None)
        try:
            upstream = await client.send(upstream_request, stream=True)
        except NOT_RESPONDING:
            forget(request.app, ctx, job_id)
            return pages.not_responding(job_id)
        prefix, public = f"/{kind}/{job_id}/", request.app.state.settings.public_hostname
        out = [(k, rewrite_location(v, target, prefix, public) if k.lower() == "location" else v)
               for k, v in upstream.headers.multi_items() if k.lower() not in HOP_BY_HOP]
        response = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                     background=BackgroundTask(upstream.aclose))
        response.raw_headers = [(k.lower().encode(), v.encode()) for k, v in out]
        return response
    return proxy


def _bare(kind: str) -> Callable[..., Any]:
    async def bare(job_id: str) -> Response:
        return RedirectResponse(f"/{kind}/{job_id}/", status_code=308)
    return bare


def _ws_ctx(app: Any, raw: str) -> SessionCtx | None:
    with app.state.sessionmaker() as db:
        found = peek_session(db, raw, app.state.settings, app.state.clock())
        if found is None:
            return None
        session, account = found
        acting = db.get(Account, session.acting_as_account_id) \
            if session.acting_as_account_id else None
        db.expunge_all()
        return SessionCtx(account, session, raw, acting)


def _ws_handler(kind: str) -> Callable[..., Any]:
    async def socket(ws: WebSocket, job_id: str, path: str) -> None:
        app = ws.app
        ctx = await run_in_threadpool(_ws_ctx, app, ws.cookies.get(COOKIE, ""))
        target = await run_in_threadpool(resolve, ctx, kind, job_id, app) if ctx else None
        if ctx is None or not isinstance(target, Target):
            await ws.close(code=1008)   # before accept: the upgrade is answered 403
            return
        headers = [(k, v) for k, v in ws.headers.items() if k.lower() not in DROP_WS]
        cookie = strip_session_cookie(ws.headers.get("cookie", ""))
        if cookie:
            headers.append(("cookie", cookie))
        headers += list(target.auth_headers.items())
        wanted = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",")
                  if p.strip()]
        try:
            upstream = await ws_connect(
                _upstream_url(target, kind, job_id, path, ws.url.query, scheme="ws"),
                additional_headers=headers,
                origin=Origin(f"https://{app.state.settings.public_hostname}"),
                subprotocols=[Subprotocol(p) for p in wanted] or None,
                open_timeout=10, max_size=None, ping_interval=None)
        except (OSError, TimeoutError, WebSocketException):
            forget(app, ctx, job_id)
            await ws.close(code=1011)
            return
        await ws.accept(subprotocol=upstream.subprotocol)
        try:
            await _pump(ws, upstream)
        finally:
            await upstream.close()
            with contextlib.suppress(RuntimeError):
                await ws.close()
    return socket


async def _pump(ws: WebSocket, upstream: Any) -> None:
    """Copy messages both ways until either side closes, then stop the other."""
    async def to_job() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            data = msg["text"] if msg.get("text") is not None else msg.get("bytes")
            if data is not None:
                await upstream.send(data)

    async def to_browser() -> None:
        async for data in upstream:
            if isinstance(data, str):
                await ws.send_text(data)
            else:
                await ws.send_bytes(data)

    tasks = [asyncio.create_task(to_job()), asyncio.create_task(to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


for _kind in KINDS:
    router.add_api_route(f"/{_kind}/{{job_id}}", _bare(_kind), methods=["GET"],
                         include_in_schema=False)
    router.add_api_route(f"/{_kind}/{{job_id}}/{{path:path}}", _handler(_kind), methods=METHODS,
                         include_in_schema=False)
    router.add_api_websocket_route(f"/{_kind}/{{job_id}}/{{path:path}}", _ws_handler(_kind))
