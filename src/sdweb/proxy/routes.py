"""/notebook, /tensorboard and /terminal: HTTP and WebSocket proxy to the job.

A job's pages are the job owner's code, so they are never served from the
app's origin. Two hostnames are involved:

- **The app origin** (SD_PUBLIC_HOSTNAME). A GET of /<kind>/<job_id>/... checks
  the session and ownership, then redirects to the session origin with a
  one-time code. Nothing from the job is shown here, except the two terminal
  API calls the app's own terminal page makes (POST /terminal/<id>/api/terminals
  and its WebSocket), which come back as JSON or text frames only.
- **The session origin** (SD_SESSION_HOSTNAME). /_sd/enter swaps the code for a
  ticket cookie scoped to /<kind>/<job_id>/, and every request is checked again
  through that ticket. It serves nothing but sessions (see guard.py).

The job gets its own token, never the platform cookie, the ticket or the CSRF
header. Its Set-Cookie, Service-Worker-Allowed and Clear-Site-Data headers
are dropped, and a Location that names the job's own address is rewritten to
the session origin.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import re
import weakref
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode, urlsplit

import httpx
from fastapi import APIRouter, Request, WebSocket
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException
from websockets.typing import Origin, Subprotocol

from sdweb.auth.sessions import load_session, peek_session
from sdweb.deps import COOKIE, ApiError, SessionCtx, current_session
from sdweb.models import Account
from sdweb.proxy import pages
from sdweb.proxy.targets import KINDS, ProxyPage, Target, forget, resolve
from sdweb.proxy.tickets import Tickets

router = APIRouter()

PROXY_COOKIE = "sd_proxy"
METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te",
              "trailer", "trailers", "transfer-encoding", "upgrade"}
DROP_REQUEST = HOP_BY_HOP | {"host", "cookie", "x-csrf-token", "authorization", "x-sd-token",
                             "origin", "referer"}
DROP_WS = DROP_REQUEST | {"sec-websocket-key", "sec-websocket-version",
                          "sec-websocket-extensions", "sec-websocket-protocol",
                          "sec-websocket-accept"}
# Headers a job may not send to the browser: they reach beyond the job's own pages.
DROP_RESPONSE = HOP_BY_HOP | {"set-cookie", "set-cookie2", "service-worker-allowed",
                              "clear-site-data"}
UPSTREAM_TIMEOUT = httpx.Timeout(None, connect=10.0)
NOT_RESPONDING = (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError,
                  httpx.ReadError)
PATH_SAFE = "/:@!$&'()*+,;=-._~%"
NEXT_RE = re.compile(r"/(notebook|tensorboard|terminal)/([0-9]{1,12}(?:_[0-9]+)?)/[^\\]*")
TERMINAL_API = "api/terminals"
TERMINAL_WS = re.compile(r"terminals/websocket/[A-Za-z0-9_-]{1,64}")
JSON_ONLY = {"content-type": "application/json", "x-content-type-options": "nosniff",
             "content-security-policy": "sandbox; default-src 'none'",
             "cache-control": "no-store"}
# How often an open socket re-checks the session behind it, so sign-out, an
# account disable or expiry closes it within a minute.
RECHECK_S = 30.0


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


def tickets(app: Any) -> Tickets:
    found: Tickets = app.state.__dict__.setdefault("tickets", Tickets())
    return found


def request_host(headers: Any) -> str:
    """The Host a request was sent to, lower-cased, without a port."""
    host = str(headers.get("host", "")).strip().lower()
    return host.rsplit(":", 1)[0] if not host.endswith("]") else host


def on_session_origin(conn: Request | WebSocket) -> bool:
    return request_host(conn.headers) == conn.app.state.settings.session_hostname


def _app_origin(app: Any) -> str:
    return f"https://{app.state.settings.public_hostname}"


def _session_origin(app: Any) -> str:
    return f"https://{app.state.settings.session_hostname}"


def strip_cookies(header: str) -> str:
    """The Cookie header without the platform's session cookie or the ticket."""
    kept = [p.strip() for p in header.split(";")
            if p.strip() and p.strip().split("=", 1)[0] not in (COOKIE, PROXY_COOKIE)]
    return "; ".join(kept)


strip_session_cookie = strip_cookies   # the old name, kept for callers


def rewrite_location(location: str, target: Target, prefix: str, public_host: str) -> str:
    """A redirect from the job, kept under /<kind>/<job_id>/. An absolute URL
    to the job's own address becomes the session origin; other absolute URLs
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


def _page_response(page: ProxyPage, job_id: str, home: str = "") -> Response:
    if page.name == "not_responding":
        return pages.not_responding(job_id, home)
    return {"starting": pages.starting, "ended": pages.ended, "forbidden": pages.forbidden,
            "not_found": pages.not_found}[page.name](home)


def _upstream_headers(conn: Request | WebSocket, target: Target, drop: set[str]) -> list[
        tuple[str, str]]:
    headers = [(k, v) for k, v in conn.headers.items() if k.lower() not in drop]
    cookie = strip_cookies(conn.headers.get("cookie", ""))
    if cookie:
        headers.append(("cookie", cookie))
    return headers + [*target.auth_headers.items(),
                      ("origin", _session_origin(conn.app))]


# --- who is asking --------------------------------------------------------------------------

def _app_session(request: Request) -> SessionCtx | Response:
    """The session from the platform cookie; signed-out browsers go to sign in."""
    app = request.app
    with app.state.sessionmaker() as db:
        try:
            ctx = current_session(request, db, app.state.settings, app.state.clock())
        except ApiError:
            nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
            return RedirectResponse(f"/sign-in?next={quote(nxt, safe='')}", status_code=302)
        db.expunge_all()
    return ctx


def _ctx_for_token(app: Any, raw: str, *, refresh: bool) -> SessionCtx | None:
    """The session behind a raw token. refresh keeps it alive like any page
    view; a background socket only peeks."""
    with app.state.sessionmaker() as db:
        settings, now = app.state.settings, app.state.clock()
        found = load_session(db, raw, settings, now) if refresh else \
            peek_session(db, raw, settings, now)
        db.commit()
        if found is None:
            return None
        session, account = found
        acting = db.get(Account, session.acting_as_account_id) \
            if session.acting_as_account_id else None
        db.expunge_all()
        return SessionCtx(account, session, raw, acting)


def _ticket_ctx(conn: Request | WebSocket, kind: str, job_id: str, *,
                refresh: bool) -> SessionCtx | None:
    raw = tickets(conn.app).session_token(conn.cookies.get(PROXY_COOKIE, ""), kind, job_id)
    return _ctx_for_token(conn.app, raw, refresh=refresh) if raw else None


# --- HTTP ---------------------------------------------------------------------------------

async def _forward(request: Request, ctx: SessionCtx, target: Target, kind: str,
                   job_id: str, path: str) -> Response:
    has_body = request.method not in ("GET", "HEAD", "OPTIONS")
    client = _client()
    headers = [*_upstream_headers(request, target, DROP_REQUEST), ("host", target.netloc)]
    upstream_request = client.build_request(
        request.method, _upstream_url(target, kind, job_id, path, request.url.query),
        headers=headers, content=request.stream() if has_body else None)
    try:
        upstream = await client.send(upstream_request, stream=True)
    except NOT_RESPONDING:
        forget(request.app, ctx, job_id)
        return pages.not_responding(job_id, _app_origin(request.app))
    prefix, host = f"/{kind}/{job_id}/", request.app.state.settings.session_hostname
    out = [(k, rewrite_location(v, target, prefix, host) if k.lower() == "location" else v)
           for k, v in upstream.headers.multi_items() if k.lower() not in DROP_RESPONSE]
    response = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                 background=BackgroundTask(upstream.aclose))
    response.raw_headers = [(k.lower().encode(), v.encode()) for k, v in out]
    return response


async def _terminal_api(request: Request, job_id: str) -> Response:
    """The app's terminal page creating a terminal: JSON in, JSON out, nothing
    the browser could render or that could set state on the app origin."""
    def refused(status: int, code: str) -> Response:
        return Response(f'{{"error": "{code}"}}', status_code=status, headers=JSON_ONLY)

    auth = await run_in_threadpool(_app_session, request)
    if isinstance(auth, Response):
        return refused(401, "no_session")
    sent = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(sent.encode(), auth.session.csrf_token.encode()):
        return refused(403, "csrf")
    target = await run_in_threadpool(resolve, auth, "terminal", job_id, request.app)
    if isinstance(target, ProxyPage):
        return refused({"forbidden": 403, "not_found": 404}.get(target.name, 409), target.name)
    client = _client()
    headers = [*_upstream_headers(request, target, DROP_REQUEST), ("host", target.netloc)]
    try:
        r = await client.post(_upstream_url(target, "terminal", job_id, TERMINAL_API, ""),
                              headers=headers, content=await request.body())
    except NOT_RESPONDING:
        forget(request.app, auth, job_id)
        return refused(502, "not_responding")
    return Response(r.content, status_code=r.status_code, headers=JSON_ONLY)


def _handler(kind: str) -> Callable[..., Any]:
    async def proxy(job_id: str, path: str, request: Request) -> Response:
        app = request.app
        if on_session_origin(request):
            ctx = await run_in_threadpool(_ticket_ctx, request, kind, job_id, refresh=True)
            if ctx is None:   # no ticket, or the platform session is over: start again
                if request.method in ("GET", "HEAD"):
                    back = request.url.path + (f"?{request.url.query}" if request.url.query
                                               else "")
                    return RedirectResponse(f"{_app_origin(app)}{back}", status_code=302)
                return pages.reopen(_app_origin(app))
            target = await run_in_threadpool(resolve, ctx, kind, job_id, app)
            if isinstance(target, ProxyPage):
                return _page_response(target, job_id, _app_origin(app))
            return await _forward(request, ctx, target, kind, job_id, path)

        # The app origin: hand over to the session origin, serve nothing of the job.
        if kind == "terminal" and request.method == "POST" and path == TERMINAL_API:
            return await _terminal_api(request, job_id)
        if request.method not in ("GET", "HEAD"):
            return pages.not_found()
        auth = await run_in_threadpool(_app_session, request)
        if isinstance(auth, Response):
            return auth
        target = await run_in_threadpool(resolve, auth, kind, job_id, app)
        if isinstance(target, ProxyPage):
            return _page_response(target, job_id)
        settings = app.state.settings
        code = tickets(app).issue(auth.raw_token, kind, job_id,
                                  ttl_s=settings.session_max_hours * 3600)
        nxt = f"/{kind}/{job_id}/{path}" + (f"?{request.url.query}" if request.url.query
                                            else "")
        return RedirectResponse(
            f"{_session_origin(app)}/_sd/enter?{urlencode({'code': code, 'next': nxt})}",
            status_code=302)
    return proxy


@router.get("/_sd/enter", include_in_schema=False)
def enter(request: Request, code: str = "", next: str = "") -> Response:
    """The session origin's door: a one-time code becomes a ticket cookie for one job."""
    app = request.app
    if not on_session_origin(request):
        return pages.not_found()
    m = NEXT_RE.fullmatch(next.split("?", 1)[0])
    ticket = tickets(app).redeem(code)
    if ticket is None:   # spent or too old: the app origin issues a new one
        return RedirectResponse(f"{_app_origin(app)}{next if m else '/'}", status_code=302)
    if m is None or (m.group(1), m.group(2)) != (ticket.kind, ticket.job_id):
        return pages.bad_link(_app_origin(app))
    response = RedirectResponse(next, status_code=302)
    response.set_cookie(PROXY_COOKIE, ticket.id, path=f"/{ticket.kind}/{ticket.job_id}/",
                        httponly=True, secure=app.state.settings.secure_cookies,
                        samesite="strict")
    return response


def _bare(kind: str) -> Callable[..., Any]:
    async def bare(job_id: str) -> Response:
        return RedirectResponse(f"/{kind}/{job_id}/", status_code=308)
    return bare


# --- WebSocket ----------------------------------------------------------------------------

def _ws_ctx(app: Any, raw: str) -> SessionCtx | None:
    return _ctx_for_token(app, raw, refresh=False)


def _ws_handler(kind: str) -> Callable[..., Any]:
    async def socket(ws: WebSocket, job_id: str, path: str) -> None:
        app = ws.app
        # Browsers always send Origin on an upgrade; a page on any other origin
        # is refused rather than trusting SameSite alone.
        origin = ws.headers.get("origin")
        if on_session_origin(ws):
            ctx = await run_in_threadpool(_ticket_ctx, ws, kind, job_id, refresh=False) \
                if origin in (None, _session_origin(app)) else None
        elif kind == "terminal" and TERMINAL_WS.fullmatch(path) and \
                origin in (None, _app_origin(app)):
            ctx = await run_in_threadpool(_ws_ctx, app, ws.cookies.get(COOKIE, ""))
        else:   # nothing of a job is served on the app origin
            ctx = None
        target = await run_in_threadpool(resolve, ctx, kind, job_id, app) if ctx else None
        if ctx is None or not isinstance(target, Target):
            await ws.close(code=1008)   # before accept: the upgrade is answered 403
            return
        headers = _upstream_headers(ws, target, DROP_WS)
        headers = [(k, v) for k, v in headers if k != "origin"]
        wanted = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",")
                  if p.strip()]
        try:
            upstream = await ws_connect(
                _upstream_url(target, kind, job_id, path, ws.url.query, scheme="ws"),
                additional_headers=headers, origin=Origin(_session_origin(app)),
                subprotocols=[Subprotocol(p) for p in wanted] or None,
                open_timeout=10, max_size=None, ping_interval=None)
        except (OSError, TimeoutError, WebSocketException):
            forget(app, ctx, job_id)
            await ws.close(code=1011)
            return
        await ws.accept(subprotocol=upstream.subprotocol)
        raw = ctx.raw_token

        async def alive() -> bool:
            return await run_in_threadpool(_ws_ctx, app, raw) is not None

        interval = float(getattr(app.state, "proxy_recheck_s", RECHECK_S))
        code = 1000
        try:
            if not await _pump(ws, upstream, alive, interval):
                code = 1008   # the session ended: sign-out, disable or expiry
        finally:
            await _close_upstream(upstream)
            with contextlib.suppress(RuntimeError):
                await ws.close(code=code)
    return socket


async def _close_upstream(upstream: Any) -> None:
    """Close the job's socket. When this task is being cancelled (the browser
    went away mid-handshake, or the server is stopping) the close itself is
    cancelled, so the connection is dropped outright rather than leaked."""
    try:
        await upstream.close()
    except asyncio.CancelledError:
        upstream.transport.abort()
        raise


async def _pump(ws: WebSocket, upstream: Any, alive: Callable[[], Any],
                interval: float) -> bool:
    """Copy messages both ways until either side closes, then stop the other.
    Every interval seconds alive() is asked whether the session still holds;
    False from it ends the pump. Returns False when that is why it stopped."""
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

    async def watch() -> None:
        while True:
            await asyncio.sleep(interval)
            if not await alive():
                return

    watcher = asyncio.create_task(watch())
    tasks = [asyncio.create_task(to_job()), asyncio.create_task(to_browser()), watcher]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return not (watcher in done and watcher.exception() is None)


for _kind in KINDS:
    router.add_api_route(f"/{_kind}/{{job_id}}", _bare(_kind), methods=["GET"],
                         include_in_schema=False)
    router.add_api_route(f"/{_kind}/{{job_id}}/{{path:path}}", _handler(_kind), methods=METHODS,
                         include_in_schema=False)
    router.add_api_websocket_route(f"/{_kind}/{{job_id}}/{{path:path}}", _ws_handler(_kind))
