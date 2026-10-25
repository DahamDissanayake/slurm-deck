"""deck-agent's HTTP/1.1 server on a Unix socket.

One request per connection. A connection is refused (403) unless its peer
UID, from SO_PEERCRED, is the web or the worker account. The whole request,
from the first byte to the end of the body, must arrive within the request
deadline: the budget is re-checked before every read, so a client trickling
bytes can't hold a worker. At most max_workers requests run at once; others
wait in the listen backlog. Nothing a client sends, and no handler bug, can
end the process: every failure becomes a JSON error reply.
"""

from __future__ import annotations

import io
import logging
import os
import socket
import socketserver
import stat
import struct
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from deckagent.audit import audit
from deckagent.config import AgentConfig
from deckagent.protocol import (
    REASONS,
    AgentError,
    Caller,
    RawResponse,
    RequestContext,
    error_body,
    json_response,
    read_json_body,
)
from deckagent.verbs import REGISTRY, VerbRegistry

log = logging.getLogger("deckagent")

MAX_HEADER_LINE = 8192
MAX_HEADERS = 64

Resolver = Callable[[int, Mapping[str, str], Any, AgentConfig], Caller]


def worker_only(peer_uid: int, headers: Mapping[str, str], store: Any,
                config: AgentConfig) -> Caller:
    """Admit the worker account only; used until session resolution is wired in."""
    if peer_uid == config.worker_uid:
        return Caller(None, "worker", None, True, None)
    raise AgentError("no_session", "Sign in again.", 401)


class _Timeout(Exception):
    pass


class _Reader:
    """Buffered reads from a socket against one overall deadline."""

    def __init__(self, sock: socket.socket, deadline: float) -> None:
        self.sock = sock
        self.deadline = deadline
        self.buf = b""

    def _fill(self) -> None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _Timeout
        self.sock.settimeout(remaining)
        try:
            chunk = self.sock.recv(65536)
        except TimeoutError:
            raise _Timeout from None
        if not chunk:
            raise AgentError("bad_request", "The request ended early.", 400)
        self.buf += chunk

    def readline(self) -> bytes:
        while b"\r\n" not in self.buf:
            if len(self.buf) > MAX_HEADER_LINE:
                raise AgentError("bad_request", "A header line is too long.", 400)
            self._fill()
        line, _, self.buf = self.buf.partition(b"\r\n")
        return line

    def read(self, n: int) -> bytes:
        while len(self.buf) < n:
            self._fill()
        data, self.buf = self.buf[:n], self.buf[n:]
        return data


class _Body(io.RawIOBase):
    """A raw request body read straight from the socket, never more than
    Content-Length and never all at once."""

    def __init__(self, reader: _Reader, length: int) -> None:
        self.reader, self.left = reader, length

    def readable(self) -> bool:
        return True

    def readinto(self, out: Any) -> int:
        if self.left <= 0:
            return 0
        if not self.reader.buf:
            self.reader._fill()
        n = min(len(out), self.left, len(self.reader.buf))
        out[:n] = self.reader.buf[:n]
        self.reader.buf = self.reader.buf[n:]
        self.left -= n
        return n


def _peer_uid(sock: socket.socket) -> int:
    creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    return int(struct.unpack("3i", creds)[1])


def _read_head(reader: _Reader) -> tuple[str, dict[str, str], int]:
    """(verb name, lower-cased headers, Content-Length) of a `POST /v1/<verb>`."""
    parts = reader.readline().decode("latin-1").split()
    if len(parts) != 3 or not parts[2].startswith("HTTP/1."):
        raise AgentError("bad_request", "Malformed request line.", 400)
    method, path, _ = parts
    if method != "POST":
        raise AgentError("bad_request", "Only POST is supported.", 400)
    if not path.startswith("/v1/") or len(path) == 4:
        raise AgentError("unknown_verb", "No such verb.", 404)
    headers: dict[str, str] = {}
    while line := reader.readline():
        if len(headers) >= MAX_HEADERS:
            raise AgentError("bad_request", "Too many headers.", 400)
        name, sep, value = line.decode("latin-1").partition(":")
        if not sep:
            raise AgentError("bad_request", "Malformed header.", 400)
        headers[name.strip().lower()] = value.strip()
    if "transfer-encoding" in headers:
        raise AgentError("length_required", "Send a Content-Length body.", 411)
    try:
        length = int(headers["content-length"])
    except (KeyError, ValueError):
        raise AgentError("length_required", "Content-Length is required.", 411) from None
    if length < 0:
        raise AgentError("bad_request", "Bad Content-Length.", 400)
    return path[len("/v1/"):], headers, length


class _Handler(socketserver.BaseRequestHandler):
    server: AgentServer

    # Filled in by _dispatch as far as it gets, for the audit line.
    peer: int | None = None
    verb_name = ""
    caller: Caller | None = None
    reported: Mapping[str, str] = {}   # RequestContext.audit, as the handler left it

    def handle(self) -> None:
        sock: socket.socket = self.request
        config = self.server.config
        deadline = time.monotonic() + config.request_deadline_s
        result = "ok"
        extra: Mapping[str, str] = {}
        chunks: Iterable[bytes] | None = None
        try:
            status, ctype, body = 200, "application/json", self._dispatch(sock, deadline)
            if isinstance(body, RawResponse):
                ctype, extra, chunks, body = (body.content_type, body.headers, body.chunks,
                                              body.body)
        except _Timeout:
            status, ctype, result = 408, "application/json", "timeout"
            body = error_body("timeout", "The request took too long to arrive.")
        except AgentError as e:
            status, ctype, result = e.status, "application/json", e.code
            body = error_body(e.code, e.message, e.data)
        except Exception:
            log.exception("unhandled error in deck-agent request")
            status, ctype, result = 500, "application/json", "internal"
            body = error_body("internal", "Something went wrong.")
        caller = self.caller
        reported = self.reported
        actor = caller.username if caller and caller.username else reported.get("actor")
        audit(config, actor=actor, acting_admin=caller.acting_admin if caller else None, verb=self.verb_name,
              target=reported.get("target", ""),
              detail={"peer_uid": self.peer, "role": caller.role if caller else None},
              result=result)
        lines = [f"HTTP/1.1 {status} {REASONS.get(status, 'Error')}", f"Content-Type: {ctype}"]
        if chunks is None:   # a streamed body has no length: it ends when we close
            lines.append(f"Content-Length: {len(body)}")
        lines += [*(f"{k}: {v}" for k, v in extra.items()), "Connection: close", "", ""]
        try:
            sock.settimeout(5)
            sock.sendall("\r\n".join(lines).encode("latin-1") + body)
            if chunks is not None:
                self._send_chunks(sock, chunks)
            # Closing with unread input resets the connection, and the client
            # would see the reset instead of this reply (an early 403 or 413).
            # End our side, then drain a little of what is left.
            sock.shutdown(socket.SHUT_WR)
            sock.settimeout(0.5)
            drained = 0
            while drained < 1024 * 1024 and (chunk := sock.recv(65536)):
                drained += len(chunk)
        except OSError:
            pass   # the client went away; nothing to tell it

    @staticmethod
    def _send_chunks(sock: socket.socket, chunks: Iterable[bytes]) -> None:
        sock.settimeout(60)
        try:
            for piece in chunks:
                sock.sendall(piece)
        except OSError:
            raise
        except Exception:
            log.exception("streamed reply failed part way")   # the client sees a short body

    def _dispatch(self, sock: socket.socket, deadline: float) -> bytes | RawResponse:
        server = self.server
        config = server.config
        peer = self.peer = _peer_uid(sock)
        if peer not in (config.web_uid, config.worker_uid):
            raise AgentError("peer_not_allowed", "This account may not use deck-agent.", 403)

        reader = _Reader(sock, deadline)
        name, headers, length = _read_head(reader)
        self.verb_name = name
        verb = server.verbs.get(name)
        if verb is None:
            raise AgentError("unknown_verb", f"No such verb: {name}", 404)
        if verb.body == "json" and length > config.max_json_bytes:
            raise AgentError("too_large", "The request body is too large.", 413)

        if verb.session:
            caller = self.caller = server.resolve(peer, headers, server.store, config)
            if caller.role not in verb.allow:
                raise AgentError("not_allowed", "You are not allowed to do that.", 403)
        else:   # the handler authorises the request itself (an upload grant)
            caller = self.caller = Caller(None, "grant", None, False, None)

        payload: Any = (read_json_body(reader.read(length)) if verb.body == "json"
                        else _Body(reader, length))
        ctx = RequestContext(caller, config, headers, server.store)
        self.reported = ctx.audit   # read even when the handler raises
        result = verb.handler(ctx, payload)
        return result if isinstance(result, RawResponse) else json_response(result)


class AgentServer(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, config: AgentConfig, store: Any, resolve: Resolver = worker_only,
                 verbs: VerbRegistry = REGISTRY) -> None:
        self.config = config
        self.store = store
        self.resolve = resolve
        self.verbs = verbs
        self._slots = threading.BoundedSemaphore(config.max_workers)
        path = config.socket_path
        if os.path.exists(path) and stat.S_ISSOCK(os.lstat(path).st_mode):
            os.unlink(path)   # a stale socket from a previous run
        super().__init__(path, _Handler)
        # Group (sdweb's group) is set by the installer; nobody else gets in.
        os.chmod(path, 0o660)

    def process_request(self, request: Any, client_address: Any) -> None:
        self._slots.acquire()
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def server_close(self) -> None:
        super().server_close()
        try:
            os.unlink(self.config.socket_path)
        except OSError:
            pass

    def shutdown(self) -> None:
        super().shutdown()
        self.server_close()
