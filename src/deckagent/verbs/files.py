"""File verbs: each runs `python -m deckagent.fsops` as the caller (admins
with as_admin: true, as sd-ops), so the kernel enforces the user's own
permissions on top of the fsops jail.

Uploads: fs.upload_begin checks the session, the free-space rule and the
destination, and returns an upload grant; fs.write_chunk needs only that
grant and streams the body into the user's staging file.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from typing import IO, Any
from urllib.parse import quote

from deckagent import grants
from deckagent.config import AgentConfig
from deckagent.fsops import CHUNK, Refused, check_name
from deckagent.identity import PosixIdentity, identity_for_user, ops_identity
from deckagent.protocol import AgentError, Caller, RawResponse, RequestContext
from deckagent.runas import popen_as
from deckagent.verbs import verb

PEOPLE = frozenset({"user", "admin"})
GIB = 2**30
SPACE_COPY = ("There isn't enough free space on the cluster for this upload "
              "({free} free, {needed} needed).")
EDIT_MAX = 1024 * 1024
LONG_S = 3600


# Seams for tests: who fsops runs as, and how it is started.
def _identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return identity_for_user(caller, config)


def _ops_identity(caller: Caller, config: AgentConfig) -> PosixIdentity:
    return ops_identity(caller, config)


def _spawn(ident: PosixIdentity, argv: list[str], **kw: Any) -> subprocess.Popen[bytes]:
    return popen_as(ident, argv, **kw)


def _who(ctx: RequestContext, payload: dict[str, Any],
         admin_ok: bool = False) -> tuple[PosixIdentity, list[str]]:
    """The identity to run as and fsops' --user/--admin arguments."""
    caller = ctx.caller
    if payload.get("as_admin") is True:
        if not admin_ok or caller.role != "admin" or caller.acting_admin:
            raise AgentError("not_allowed", "Only admins can do that.", 403)
        return _ops_identity(caller, ctx.config), ["--user", str(caller.username), "--admin"]
    return _identity(caller, ctx.config), ["--user", str(caller.username)]


def _argv(config: AgentConfig, op: str, who: list[str], *positional: str,
          opts: tuple[str, ...] = ()) -> list[str]:
    # "--" ends the options, so a path starting with "-" stays a path.
    return [sys.executable, "-m", "deckagent.fsops", op, *who, "--nfs-root", config.nfs_root,
            *opts, *(("--", *positional) if positional else ())]


def _exec(ident: PosixIdentity, argv: list[str], stdin: IO[bytes] | bytes | None = None,
          timeout: float = 60) -> tuple[int, dict[str, Any]]:
    """Run fsops; (exit code, its JSON). A stream on stdin goes in 1 MiB pieces."""
    proc = _spawn(ident, argv, stdin=subprocess.PIPE if stdin is not None else
                  subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        if proc.stdin is not None:
            if isinstance(stdin, bytes):
                proc.stdin.write(stdin)
            elif stdin is not None:
                while piece := stdin.read(CHUNK):
                    proc.stdin.write(piece)
        out, _ = proc.communicate(timeout=timeout)   # closes stdin: end of input
    except (subprocess.TimeoutExpired, BrokenPipeError):
        proc.kill()
        proc.communicate()
        raise AgentError("fs_failed", "The file operation didn't finish.", 500) from None
    try:
        data = json.loads(out or b"{}")
    except ValueError:
        data = {}
    return proc.returncode, data


def _run(ident: PosixIdentity, argv: list[str], **kw: Any) -> dict[str, Any]:
    code, data = _exec(ident, argv, **kw)
    if code == 2:
        raise AgentError("fs_refused", str(data.get("error", "Not allowed.")), 403)
    if code != 0:
        raise AgentError("fs_failed", str(data.get("error", "The file operation failed.")), 400)
    data.pop("ok", None)
    return data


def _simple(op: str, *keys: str, admin_ok: bool = False, flag: str = "",
            timeout: float = 60) -> Any:
    def handler(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
        ident, who = _who(ctx, payload, admin_ok)
        args = [str(payload.get(k, "")) for k in keys]
        opts = (f"--{flag}",) if flag and payload.get(flag) is True else ()
        return _run(ident, _argv(ctx.config, op, who, *args, opts=opts), timeout=timeout)
    return handler


verb("fs.list", allow=PEOPLE)(_simple("list", "path", admin_ok=True))
verb("fs.stat", allow=PEOPLE)(_simple("stat", "path", admin_ok=True))
verb("fs.du", allow=PEOPLE)(_simple("du", "path", admin_ok=True, timeout=LONG_S))
verb("fs.mkdir", allow=PEOPLE)(_simple("mkdir", "path"))
verb("fs.rename", allow=PEOPLE)(_simple("rename", "src", "dst"))
verb("fs.delete", allow=PEOPLE)(_simple("delete", "path", admin_ok=True, flag="recursive",
                                        timeout=LONG_S))
verb("fs.extract", allow=PEOPLE)(_simple("extract", "archive", "dest_dir", timeout=LONG_S))


@verb("fs.write", allow=PEOPLE)
def write(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Save a text file edited in the browser (UTF-8, at most 1 MiB)."""
    ident, who = _who(ctx, payload)
    data = str(payload.get("text", "")).encode()
    argv = _argv(ctx.config, "write", who, str(payload.get("path", "")),
                 opts=("--max", str(EDIT_MAX)))
    return _run(ident, argv, stdin=data)


def _stream(ident: PosixIdentity, argv: list[str]) -> Iterator[bytes]:
    proc = _spawn(ident, argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                  stderr=subprocess.DEVNULL)
    try:
        assert proc.stdout is not None
        while piece := proc.stdout.read(CHUNK):
            yield piece
    finally:   # also when the client goes away part way
        proc.kill()
        proc.wait()


@verb("fs.read", allow=PEOPLE)
def read(ctx: RequestContext, payload: dict[str, Any]) -> RawResponse:
    ident, who = _who(ctx, payload, admin_ok=True)
    path = str(payload.get("path", ""))
    _run(ident, _argv(ctx.config, "stat", who, path))      # jail check before streaming
    opts: tuple[str, ...] = ("--offset", str(int(payload.get("offset") or 0)))
    if payload.get("limit") is not None:
        opts += ("--limit", str(int(payload["limit"])))
    return RawResponse(chunks=_stream(ident, _argv(ctx.config, "read", who, path, opts=opts)))


@verb("fs.download_stream", allow=PEOPLE)
def download_stream(ctx: RequestContext, payload: dict[str, Any]) -> RawResponse:
    """A file as is, a folder as a zip streamed with no size limit."""
    ident, who = _who(ctx, payload, admin_ok=True)
    path = str(payload.get("path", ""))
    info = _run(ident, _argv(ctx.config, "stat", who, path))
    is_dir = info.get("type") == "dir"
    name = str(info.get("name") or "download") + (".zip" if is_dir else "")
    argv = _argv(ctx.config, "zipstream" if is_dir else "read", who, path)
    return RawResponse(content_type="application/zip" if is_dir else "application/octet-stream",
                       headers={"Content-Disposition":
                                f"attachment; filename*=UTF-8''{quote(name, safe='')}"},
                       chunks=_stream(ident, argv))


@verb("fs.free_space", allow=PEOPLE)
def free_space(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, int]:
    st = os.statvfs(ctx.config.nfs_root)
    return {"free_bytes": st.f_bavail * st.f_frsize, "total_bytes": st.f_blocks * st.f_frsize}


def _gb(n: int) -> str:
    return f"{n / 1e9:.1f} GB"


def _grant(ctx: RequestContext, upload_id: str, ident: PosixIdentity,
           who: list[str]) -> dict[str, Any]:
    offset = _run(ident, _argv(ctx.config, "stage-size", who, upload_id))["size"]
    grant = grants.issue(grants.load_key(ctx.config.grant_key_file),
                         username=str(ctx.caller.username), upload_id=upload_id,
                         expires=int(time.time()) + grants.GRANT_SECONDS)
    return {"grant": grant, "offset": offset}


@verb("fs.upload_begin", allow=PEOPLE)
def upload_begin(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    size = payload.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise AgentError("bad_size", "The upload size must be a number of bytes.", 422)
    try:
        check_name(str(payload.get("filename", "")))
    except Refused as e:
        raise AgentError("bad_name", str(e), 422) from None
    free = free_space(ctx, {})["free_bytes"]
    if size + GIB > free:
        raise AgentError("no_space", SPACE_COPY.format(free=_gb(free), needed=_gb(size + GIB)),
                         507)
    ident, who = _who(ctx, payload)
    dest = _run(ident, _argv(ctx.config, "stat", who, str(payload.get("dest_dir", ""))))
    if dest.get("type") != "dir" or dest.get("readonly"):
        raise AgentError("not_writable", "You can only upload into your own folders.", 403)
    return _grant(ctx, str(payload.get("upload_id", "")), ident, who)


@verb("fs.upload_regrant", allow=PEOPLE)
def upload_regrant(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """A fresh grant for an upload this user started (resume after expiry)."""
    ident, who = _who(ctx, payload)
    return _grant(ctx, str(payload.get("upload_id", "")), ident, who)


# One status lookup per username a minute for fs.write_chunk.
ACTIVE_ACCOUNTS = grants.ActiveAccounts()


@verb("fs.write_chunk", allow=PEOPLE, body="raw", session=False)
def write_chunk(ctx: RequestContext, body: IO[bytes]) -> dict[str, Any]:
    h = ctx.headers
    upload_id = h.get("x-sd-upload", "")
    username = grants.verify(grants.load_key(ctx.config.grant_key_file), h.get("x-sd-grant", ""),
                             upload_id=upload_id, now=int(time.time()))
    ctx.audit.update(actor=username, target=upload_id)
    ACTIVE_ACCOUNTS.check(ctx.store, username)
    try:
        offset = int(h.get("x-sd-offset", ""))
    except ValueError:
        raise AgentError("bad_offset", "X-SD-Offset must be a number.", 400) from None
    # The grant was issued after a full session check for this username, and
    # identity_for_user still refuses system, reserved and privileged accounts.
    caller = Caller(username, "user", "shell", False, None)
    ident = _identity(caller, ctx.config)
    argv = _argv(ctx.config, "stage-append", ["--user", username], upload_id,
                 opts=("--offset", str(offset)))
    code, data = _exec(ident, argv, stdin=body, timeout=LONG_S)
    if code == 2 and "size" in data:
        raise AgentError("offset_mismatch",
                         f"The upload is at byte {data['size']}, not {offset}.", 409)
    if code != 0:
        raise AgentError("fs_refused" if code == 2 else "fs_failed",
                         str(data.get("error", "The chunk wasn't saved.")),
                         403 if code == 2 else 400)
    return {"offset": data["size"]}


@verb("fs.upload_finalize", allow=PEOPLE)
def upload_finalize(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    ident, who = _who(ctx, payload)
    dest, name = str(payload.get("dest_dir", "")), str(payload.get("filename", ""))
    opts = ("--replace",) if payload.get("replace") is True else ()
    _run(ident, _argv(ctx.config, "stage-finalize", who, str(payload.get("upload_id", "")),
                      dest, name, opts=opts))
    return {"path": f"{dest.rstrip('/')}/{name}"}


verb("fs.upload_abort", allow=PEOPLE)(_simple("stage-abort", "upload_id"))
