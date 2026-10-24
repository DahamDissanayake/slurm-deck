"""/api/files: browse, preview, edit, download and manage files through
deck-agent, which runs each operation as the user (or as sd-ops for an admin
looking at someone else's files with ?user=).

Downloads stream from deck-agent to the browser; if the browser goes away
the agent stream is closed so the work behind it stops.
"""

from __future__ import annotations

import csv
import io
import posixpath
from collections.abc import AsyncIterator, Iterator
from itertools import islice
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from sdcore.validate import user_browse_roots, user_job_root, user_upload_root
from sdweb.accounts.service import agent_call
from sdweb.agent import AgentCallError
from sdweb.deps import ApiError, SessionCtx, Settings, require_csrf, require_user

router = APIRouter(prefix="/api/files")

User = Annotated[SessionCtx, Depends(require_user)]
UserWrite = Annotated[SessionCtx, Depends(require_csrf)]
EDIT_MAX = 1024 * 1024
TEXT_PREVIEW = 64 * 1024
TABLE_READ = 256 * 1024
TABLE_ROWS = 50
IMAGE_MAX = 20 * 1024 * 1024
IMAGES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".gif": "image/gif", ".webp": "image/webp"}


def _as_admin(ctx: SessionCtx, user: str) -> bool:
    """?user= is for admins looking at another account's files."""
    if not user:
        return False
    if ctx.account.role != "admin" or ctx.acting_as is not None:
        raise ApiError(403, "not_allowed", message="Only admins can open other users' files.")
    return True


def _call(request: Request, ctx: SessionCtx, verb: str, payload: dict[str, Any]) -> Any:
    return agent_call(request.app.state.agent, verb, payload, ctx.raw_token)


def _open(request: Request, ctx: SessionCtx, verb: str,
          payload: dict[str, Any]) -> Iterator[bytes]:
    try:
        _, body = request.app.state.agent.stream_with_headers(verb, payload,
                                                              session=ctx.raw_token)
    except AgentCallError as e:
        raise ApiError(e.status if 400 <= e.status < 500 else 502, e.code,
                       message=e.message) from None
    return body


def _read(request: Request, ctx: SessionCtx, path: str, limit: int, admin: bool) -> bytes:
    body = _open(request, ctx, "fs.read", {"path": path, "offset": 0, "limit": limit,
                                           "as_admin": admin})
    try:
        return b"".join(body)
    finally:
        body.close()   # type: ignore[attr-defined]


def _relay(chunks: Iterator[bytes]) -> AsyncIterator[bytes]:
    """Pull agent chunks in a worker thread; closing this closes the agent stream,
    also when a pull is still running at the time (it closes when it returns)."""
    stopped = False

    def pull() -> bytes | None:
        piece = next(chunks, None)
        if stopped:
            chunks.close()   # type: ignore[attr-defined]
            return None
        return piece

    async def gen() -> AsyncIterator[bytes]:
        nonlocal stopped
        try:
            while (piece := await run_in_threadpool(pull)) is not None:
                yield piece
        finally:
            stopped = True
            try:
                chunks.close()   # type: ignore[attr-defined]
            except ValueError:   # a pull is in flight; it closes the stream itself
                pass
    return gen()


class _Stream(StreamingResponse):
    """Closes the body however the response ends, client disconnect included."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.body_iterator.aclose()   # type: ignore[attr-defined]


def content_disposition(name: str) -> str:
    """attachment with an ASCII fallback and the RFC 5987 UTF-8 name."""
    ascii_name = "".join(c if 32 <= ord(c) < 127 and c not in '"\\%' else "_" for c in name)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


@router.get("/roots")
def roots(ctx: User, settings: Settings, user: str = "") -> dict:
    username = user if _as_admin(ctx, user) else ctx.effective_account.username
    own, models, envs, data, datasets = user_browse_roots(settings.nfs_root, username)
    rows = [("My files", user_upload_root(settings.nfs_root, username), True),
            ("My job outputs", user_job_root(settings.nfs_root, username), True),
            ("Shared datasets", datasets, False), ("Shared models", models, False),
            ("Shared environments", envs, False), ("Shared data", data, False)]
    return {"roots": [{"label": label, "path": path, "writable": w} for label, path, w in rows]}


@router.get("")
def list_dir(ctx: User, request: Request, path: str, user: str = "") -> dict:
    return dict(_call(request, ctx, "fs.list", {"path": path, "as_admin": _as_admin(ctx, user)}))


@router.get("/stat")
def stat(ctx: User, request: Request, path: str, user: str = "") -> dict:
    return dict(_call(request, ctx, "fs.stat", {"path": path, "as_admin": _as_admin(ctx, user)}))


@router.get("/download")
def download(ctx: User, request: Request, path: str, user: str = "") -> Response:
    admin = _as_admin(ctx, user)
    info = _call(request, ctx, "fs.stat", {"path": path, "as_admin": admin})
    name = str(info.get("name") or posixpath.basename(path.rstrip("/")) or "download")
    if info.get("type") == "dir":
        name += ".zip"
    chunks = _open(request, ctx, "fs.download_stream", {"path": path, "as_admin": admin})
    return _Stream(_relay(chunks), media_type="application/octet-stream",
                   headers={"Content-Disposition": content_disposition(name)})


@router.get("/preview")
def preview(ctx: User, request: Request, path: str, user: str = "") -> Any:
    """Images inline (up to 20 MB); CSV/TSV as the first 50 rows; else the
    first 64 KiB of text."""
    admin = _as_admin(ctx, user)
    ext = posixpath.splitext(path)[1].lower()
    if ext in IMAGES:
        size = int(_call(request, ctx, "fs.stat", {"path": path, "as_admin": admin})["size"])
        if size > IMAGE_MAX:
            raise ApiError(413, "too_big", message="Images over 20 MB aren't previewed.")
        return Response(_read(request, ctx, path, size, admin), media_type=IMAGES[ext])
    if ext in (".csv", ".tsv"):
        text = _read(request, ctx, path, TABLE_READ, admin).decode(errors="replace")
        reader = csv.reader(io.StringIO(text), delimiter="\t" if ext == ".tsv" else ",")
        return {"kind": "table", "rows": list(islice(reader, TABLE_ROWS))}
    raw = _read(request, ctx, path, TEXT_PREVIEW + 1, admin)
    return {"kind": "text", "text": raw[:TEXT_PREVIEW].decode(errors="replace"),
            "truncated": len(raw) > TEXT_PREVIEW}


@router.get("/text")
def get_text(ctx: User, request: Request, path: str) -> dict:
    raw = _read(request, ctx, path, EDIT_MAX + 1, False)
    if len(raw) > EDIT_MAX:
        raise ApiError(413, "too_big", message="Files over 1 MiB can't be edited here.")
    try:
        return {"text": raw.decode()}
    except UnicodeDecodeError:
        raise ApiError(415, "not_text", message="This file isn't UTF-8 text.") from None


@router.put("/text")
async def put_text(ctx: UserWrite, request: Request, path: str) -> dict:
    if int(request.headers.get("content-length") or 0) > EDIT_MAX:
        raise ApiError(413, "too_big", message="Files over 1 MiB can't be edited here.")
    raw = b""
    async for piece in request.stream():
        raw += piece
        if len(raw) > EDIT_MAX:
            raise ApiError(413, "too_big", message="Files over 1 MiB can't be edited here.")
    try:
        text = raw.decode()
    except UnicodeDecodeError:
        raise ApiError(415, "not_text", message="Send UTF-8 text.") from None
    await run_in_threadpool(_call, request, ctx, "fs.write", {"path": path, "text": text})
    return {}


class PathIn(BaseModel):
    path: str


class RenameIn(BaseModel):
    src: str
    dst: str


class DeleteIn(BaseModel):
    path: str
    recursive: bool = False


class ExtractIn(BaseModel):
    archive: str
    dest_dir: str


@router.post("/mkdir")
def mkdir(body: PathIn, ctx: UserWrite, request: Request) -> dict:
    return dict(_call(request, ctx, "fs.mkdir", body.model_dump()))


@router.post("/rename")
def rename(body: RenameIn, ctx: UserWrite, request: Request) -> dict:
    return dict(_call(request, ctx, "fs.rename", body.model_dump()))


@router.post("/delete")
def delete(body: DeleteIn, ctx: UserWrite, request: Request, user: str = "") -> dict:
    return dict(_call(request, ctx, "fs.delete",
                      {**body.model_dump(), "as_admin": _as_admin(ctx, user)}))


@router.post("/extract")
def extract(body: ExtractIn, ctx: UserWrite, request: Request) -> dict:
    return dict(_call(request, ctx, "fs.extract", body.model_dump()))
