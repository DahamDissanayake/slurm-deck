"""Upload grants: deck-agent checks the session once when an upload starts and
hands back a grant, so each chunk is authorised without a session lookup.

A grant is `username:upload_id:expires:sig`, sig being base64url
HMAC-SHA256 over `username|upload_id|expires` with the key in
SD_GRANT_KEY_FILE (32 random bytes, root 0600, made by the installer).

A grant lasts 30 minutes; web asks for a fresh one (fs.upload_regrant, which
needs a live session) before it runs out, so a grant outlives sign-out by at
most that long. Each chunk also checks that the account is still active
(ActiveAccounts, one cached lookup per username a minute), so a disabled
account's upload stops within a minute.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
from collections.abc import Callable
from typing import Any

from deckagent.protocol import AgentError

GRANT_SECONDS = 30 * 60


def _sig(key: bytes, username: str, upload_id: str, expires: int) -> str:
    mac = hmac.new(key, f"{username}|{upload_id}|{expires}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).rstrip(b"=").decode()


def issue(key: bytes, *, username: str, upload_id: str, expires: int) -> str:
    return f"{username}:{upload_id}:{expires}:{_sig(key, username, upload_id, expires)}"


def verify(key: bytes, grant: str, *, upload_id: str, now: int) -> str:
    """The grant's username; AgentError bad_grant (403) if it is forged,
    expired or for another upload."""
    parts = grant.split(":")
    if len(parts) == 4 and parts[2].isdigit():
        username, gid, expires, sig = parts[0], parts[1], int(parts[2]), parts[3]
        good = hmac.compare_digest(sig.encode(), _sig(key, username, gid, expires).encode())
        if good and gid == upload_id and now <= expires:
            return username
    raise AgentError("bad_grant", "This upload link is no longer valid. Start the upload again.",
                     403)


def load_key(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            key = f.read()
    except OSError:
        key = b""
    if len(key) < 32:
        raise AgentError("grant_key_missing", "Uploads aren't set up on this cluster.", 500)
    return key


class ActiveAccounts:
    """Whether a grant's account is still active, read from the session
    store's account() and cached for ttl seconds per username. Fails closed:
    no store, no row, or any status but active is refused."""

    def __init__(self, ttl: float = 60, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl, self.clock = ttl, clock
        self._seen: dict[str, tuple[float, bool]] = {}
        self._lock = threading.Lock()

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()

    def check(self, store: Any, username: str) -> None:
        now = self.clock()
        with self._lock:
            hit = self._seen.get(username)
        if hit is not None and now - hit[0] < self.ttl:
            active = hit[1]
        else:
            row = store.account(username) if store is not None else None
            active = row is not None and row.status == "active"
            with self._lock:
                self._seen[username] = (now, active)
        if not active:
            raise AgentError("account_inactive",
                             "This account isn't active, so the upload was stopped.", 403)
