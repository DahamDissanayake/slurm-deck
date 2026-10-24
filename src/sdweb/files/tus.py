"""/api/uploads: tus 1.0.0 resumable uploads (creation and termination
extensions), streamed through deck-agent.

The web app never stores upload bytes. POST asks deck-agent for an upload
grant; each PATCH body is passed through to `fs.write_chunk` as it arrives,
so a 64 MB chunk never sits in memory; the last chunk finalizes the file. An
upload can be resumed for 24 hours (HEAD returns the staged size), and only
by the account that started it; anyone else gets 404.
"""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import timedelta
from typing import Annotated, Any

import anyio.from_thread
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from sdweb.accounts.service import agent_call
from sdweb.agent import AgentCallError
from sdweb.deps import ApiError, Db, Now, SessionCtx, require_csrf, require_user
from sdweb.models import Upload

router = APIRouter(prefix="/api/uploads")

User = Annotated[SessionCtx, Depends(require_user)]
UserWrite = Annotated[SessionCtx, Depends(require_csrf)]
TUS = {"Tus-Resumable": "1.0.0"}
GIB = 1024 ** 3
RESUME = timedelta(hours=24)
GRANT_LIFE = timedelta(hours=6)          # deckagent.grants.GRANT_SECONDS
REGRANT_BEFORE = timedelta(minutes=10)


def _agent(request: Request) -> Any:
    return request.app.state.agent


def _metadata(raw: str) -> dict[str, str]:
    """tus Upload-Metadata: comma-separated `key base64value` pairs."""
    out: dict[str, str] = {}
    for pair in raw.split(","):
        key, _, value = pair.strip().partition(" ")
        if not key:
            continue
        try:
            out[key] = base64.b64decode(value, validate=True).decode() if value else ""
        except (ValueError, UnicodeDecodeError):
            raise ApiError(400, "bad_metadata", message="Upload-Metadata isn't valid.") from None
    return out


def _own(db: Session, upload_id: str, ctx: SessionCtx, now: Any) -> Upload:
    """The caller's live upload, or 404 (also for other accounts' uploads)."""
    try:
        up = db.get(Upload, uuid.UUID(upload_id))
    except ValueError:
        up = None
    if (up is None or up.account_id != ctx.effective_account.id or up.finished_at
            or up.aborted_at or now >= up.expires_at):
        raise ApiError(404, "not_found", message="There is no such upload, or it has expired.")
    return up


def _finalize(request: Request, ctx: SessionCtx, up: Upload, now: Any) -> None:
    agent_call(_agent(request), "fs.upload_finalize",
               {"upload_id": str(up.id), "dest_dir": up.dest_dir, "filename": up.filename,
                "replace": up.replace}, ctx.raw_token)
    up.finished_at = now


@router.options("")
def options(ctx: User, request: Request) -> Response:
    free = int(agent_call(_agent(request), "fs.free_space", {}, ctx.raw_token)["free_bytes"])
    return Response(status_code=204, headers={
        **TUS, "Tus-Version": "1.0.0", "Tus-Extension": "creation,termination",
        "Tus-Max-Size": str(max(0, free - GIB))})


@router.post("")
def create(ctx: UserWrite, request: Request, db: Db, now: Now) -> Response:
    try:
        size = int(request.headers.get("upload-length", ""))
    except ValueError:
        size = -1
    if size < 0:
        raise ApiError(400, "bad_length", message="Upload-Length must be a number of bytes.")
    meta = _metadata(request.headers.get("upload-metadata", ""))
    upload_id = uuid.uuid4()
    out = agent_call(_agent(request), "fs.upload_begin",
                     {"upload_id": str(upload_id), "dest_dir": meta.get("dest_dir", ""),
                      "filename": meta.get("filename", ""), "size": size}, ctx.raw_token)
    up = Upload(id=upload_id, account_id=ctx.effective_account.id,
                dest_dir=meta.get("dest_dir", ""), filename=meta.get("filename", ""),
                replace=meta.get("replace", "").lower() in ("1", "true", "yes"), size=size,
                offset=int(out["offset"]), created_at=now, expires_at=now + RESUME,
                grant=out["grant"], grant_expires_at=now + GRANT_LIFE)
    db.add(up)
    if size == 0:   # nothing will be PATCHed
        _finalize(request, ctx, up, now)
    db.commit()
    return Response(status_code=201, headers={**TUS, "Location": f"/api/uploads/{upload_id}",
                                              "Upload-Offset": str(up.offset)})


@router.get("")
def active(ctx: User, db: Db, now: Now) -> dict:
    """The account's unfinished uploads, so the UI can offer Resume."""
    rows = db.scalars(select(Upload).where(
        Upload.account_id == ctx.effective_account.id, Upload.finished_at.is_(None),
        Upload.aborted_at.is_(None), Upload.expires_at > now).order_by(Upload.created_at))
    return {"uploads": [{"id": str(u.id), "filename": u.filename, "dest_dir": u.dest_dir,
                         "size": u.size, "offset": u.offset,
                         "expires_at": u.expires_at.isoformat()} for u in rows]}


@router.head("/{upload_id}")
def head(upload_id: str, ctx: User, request: Request, db: Db, now: Now) -> Response:
    """The staged size, read from deck-agent with a fresh grant."""
    up = _own(db, upload_id, ctx, now)
    out = agent_call(_agent(request), "fs.upload_regrant", {"upload_id": str(up.id)},
                     ctx.raw_token)
    up.offset, up.grant, up.grant_expires_at = int(out["offset"]), out["grant"], now + GRANT_LIFE
    db.commit()
    return Response(status_code=200, headers={**TUS, "Upload-Offset": str(up.offset),
                                              "Upload-Length": str(up.size),
                                              "Cache-Control": "no-store"})


def _body(request: Request) -> Iterator[bytes]:
    """The request body as a plain iterator, for use in a worker thread."""
    stream = request.stream().__aiter__()

    async def next_piece() -> bytes | None:
        try:
            return await stream.__anext__()
        except StopAsyncIteration:
            return None

    while (piece := anyio.from_thread.run(next_piece)) is not None:
        if piece:
            yield piece


@router.patch("/{upload_id}")
async def patch(upload_id: str, ctx: UserWrite, request: Request, db: Db, now: Now) -> Response:
    if request.headers.get("content-type") != "application/offset+octet-stream":
        raise ApiError(415, "bad_content_type",
                       message="Send chunks as application/offset+octet-stream.")
    try:
        offset = int(request.headers["upload-offset"])
        length = int(request.headers["content-length"])
    except (KeyError, ValueError):
        raise ApiError(400, "bad_headers",
                       message="Upload-Offset and Content-Length are required.") from None
    up = await run_in_threadpool(_own, db, upload_id, ctx, now)
    if offset != up.offset:
        raise ApiError(409, "offset_mismatch",
                       message=f"The upload is at byte {up.offset}, not {offset}.")
    if offset + length > up.size:
        raise ApiError(413, "too_long", message="That goes past the upload's length.")
    agent = _agent(request)

    def stream_chunk() -> int:   # runs in a worker thread
        if up.grant_expires_at - now < REGRANT_BEFORE:
            out = agent_call(agent, "fs.upload_regrant", {"upload_id": str(up.id)},
                             ctx.raw_token)
            up.grant, up.grant_expires_at = out["grant"], now + GRANT_LIFE
        try:
            up.offset = agent.upload_chunk(str(up.id), offset, _body(request), length=length,
                                           grant=up.grant)
        except AgentCallError as e:
            raise ApiError(e.status if 400 <= e.status < 500 else 502, e.code,
                           message=e.message) from None
        if up.offset == up.size:
            _finalize(request, ctx, up, now)
        db.commit()
        return up.offset

    new_offset = await run_in_threadpool(stream_chunk)
    return Response(status_code=204, headers={**TUS, "Upload-Offset": str(new_offset)})


@router.delete("/{upload_id}")
def abort(upload_id: str, ctx: UserWrite, request: Request, db: Db, now: Now) -> Response:
    up = _own(db, upload_id, ctx, now)
    agent_call(_agent(request), "fs.upload_abort", {"upload_id": str(up.id)}, ctx.raw_token)
    up.aborted_at = now
    db.commit()
    return Response(status_code=204, headers=TUS)
