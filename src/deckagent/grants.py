"""Upload grants: deck-agent checks the session once when an upload starts and
hands back a grant, so each chunk is authorised without a database lookup.

A grant is `username:upload_id:expires:sig`, sig being base64url
HMAC-SHA256 over `username|upload_id|expires` with the key in
SD_GRANT_KEY_FILE (32 random bytes, root 0600, made by the installer).
"""

from __future__ import annotations

import base64
import hashlib
import hmac

from deckagent.protocol import AgentError

GRANT_SECONDS = 6 * 3600


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
