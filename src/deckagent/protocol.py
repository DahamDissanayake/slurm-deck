"""deck-agent wire protocol: the caller, request context, errors and envelopes.

Requests are `POST /v1/<verb>` over the Unix socket. Replies are
`{"ok": true, "data": ...}` or `{"ok": false, "error": {"code", "message"}}`,
except streaming verbs, which return raw bytes (RawResponse).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deckagent.config import AgentConfig


class AgentError(Exception):
    """An expected failure, sent to the caller as `code` and a plain message."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Caller:
    """Who a request acts for, resolved from the session (deckagent.sessions).

    role is "user", "admin" or "worker". acting_admin is the admin's username
    when an admin is viewing as this user.
    """

    username: str | None
    role: str
    linux_kind: str | None
    is_worker: bool
    acting_admin: str | None


@dataclass(frozen=True)
class RequestContext:
    caller: Caller
    config: AgentConfig
    headers: Mapping[str, str]   # lower-cased names


@dataclass(frozen=True)
class RawResponse:
    """A non-JSON reply (file downloads, log reads). With chunks, the body is
    streamed piece by piece and ends when the connection closes."""

    body: bytes = b""
    content_type: str = "application/octet-stream"
    headers: Mapping[str, str] = field(default_factory=dict)
    chunks: Iterable[bytes] | None = None


REASONS = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
           404: "Not Found", 408: "Request Timeout", 409: "Conflict",
           411: "Length Required", 413: "Content Too Large", 422: "Unprocessable Content",
           500: "Internal Server Error"}


def error_body(code: str, message: str) -> bytes:
    return json.dumps({"ok": False, "error": {"code": code, "message": message}}).encode()


def json_response(data: Any) -> bytes:
    return json.dumps({"ok": True, "data": data}).encode()


def read_json_body(raw: bytes) -> dict[str, Any]:
    """Decode a request body that must be a JSON object."""
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, ValueError):
        raise AgentError("bad_json", "The request body is not valid JSON.", 400) from None
    if not isinstance(value, dict):
        raise AgentError("bad_json", "The request body must be a JSON object.", 400)
    return value
