"""GET /ws/live: one WebSocket per browser tab. The session cookie is checked
when it opens and again every tick, without refreshing it; an invalid or
expired session closes the socket with 4401."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from sdweb.auth.sessions import peek_session
from sdweb.deps import COOKIE
from sdweb.live.poller import Poller

router = APIRouter()

INTERVAL_S = 5.0
NO_SESSION = 4401


def _poller(app: Any) -> Poller:
    if getattr(app.state, "poller", None) is None or app.state.poller.agent is not app.state.agent:
        app.state.poller = Poller(app.state.agent, app.state.sessionmaker)
    poller: Poller = app.state.poller
    return poller


def _account_for(app: Any, raw: str) -> int | None:
    """The effective account id (the viewed-as user for an admin), or None."""
    with app.state.sessionmaker() as db:
        found = peek_session(db, raw, app.state.settings, app.state.clock())
        if found is None:
            return None
        session, account = found
        return session.acting_as_account_id or account.id


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    app = ws.app
    raw = ws.cookies.get(COOKIE, "")
    await ws.accept()
    account_id = await run_in_threadpool(_account_for, app, raw)
    if account_id is None:
        await ws.close(code=NO_SESSION)
        return
    poller = _poller(app)
    interval = float(getattr(app.state, "live_interval_s", INTERVAL_S))
    closed = asyncio.Event()

    async def watch_close() -> None:   # notice the browser leaving between ticks
        try:
            while True:
                await ws.receive_text()
        except WebSocketDisconnect:
            closed.set()

    watcher = asyncio.create_task(watch_close())
    try:
        while not closed.is_set():
            if await run_in_threadpool(_account_for, app, raw) != account_id:
                await ws.close(code=NO_SESSION)
                return
            cluster = await run_in_threadpool(poller.cluster, raw)
            messages = ([cluster] if cluster else []) + await run_in_threadpool(
                poller.jobs, account_id, raw)
            for msg in messages:
                await ws.send_json(msg)
            try:
                await asyncio.wait_for(closed.wait(), timeout=interval)
            except TimeoutError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        watcher.cancel()
