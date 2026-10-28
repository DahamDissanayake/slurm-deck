"""Who a request acts for: session token (or the worker's peer UID) -> Caller.

deck-agent reads sessions from two read-only views the web app's database
provides, agent_sessions and agent_accounts, as the sd_agent_ro role. It
checks the session itself on every request, so an account disabled a second
ago, or a session past its idle or absolute limit, is refused even though web
still holds the token. View as user is the acting_as_username column on the
admin's own session row; web can't forge it with a header.

The database alone never makes an admin. A row with role admin counts only
when its username is also listed in the admins file (/etc/slurm-deck-web/admins,
root-owned, one name per line), which only root on the login node can change.
Otherwise the caller is a plain user, so an edited or forged row can't reach
the admin verbs or sd-ops.
"""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from deckagent.config import AgentConfig
from deckagent.protocol import AgentError, Caller
from sdcore.names import USERNAME_RE

ROLES = frozenset({"user", "admin"})


@dataclass(frozen=True)
class SessionRow:
    username: str
    role: str
    linux_kind: str
    uid: int | None
    status: str
    created_at: datetime
    last_seen_at: datetime
    acting_as_username: str | None


class SessionStore(Protocol):
    def lookup(self, token_hash: str) -> SessionRow | None: ...

    def account(self, username: str) -> SessionRow | None: ...


def hash_token(raw: str) -> str:
    """The stored form of a session token (the web app stores the same hash)."""
    return hashlib.sha256(raw.encode()).hexdigest()


_FIELDS = "username, role, linux_kind, uid, status, created_at, last_seen_at"


class PgSessionStore:
    """Reads the agent_sessions / agent_accounts views. One short connection
    per lookup: simple, thread-safe, and nothing cached between requests."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _one(self, sql: str, arg: str) -> tuple[Any, ...] | None:
        import psycopg

        with psycopg.connect(self.dsn, autocommit=True, connect_timeout=5) as conn:
            return conn.execute(sql, (arg,)).fetchone()

    def lookup(self, token_hash: str) -> SessionRow | None:
        row = self._one(f"SELECT {_FIELDS}, acting_as_username FROM agent_sessions "
                        "WHERE token_hash = %s", token_hash)
        return _to_row(row, row[7]) if row else None

    def account(self, username: str) -> SessionRow | None:
        row = self._one(f"SELECT {_FIELDS} FROM agent_accounts WHERE username = %s", username)
        return _to_row(row, None) if row else None

    def setting(self, key: str) -> Any:
        """An admin setting from the agent_settings view (None when unset)."""
        row = self._one("SELECT value FROM agent_settings WHERE key = %s", key)
        return row[0] if row else None


def _to_row(v: tuple[Any, ...], acting_as: str | None) -> SessionRow:
    return SessionRow(username=v[0], role=v[1], linux_kind=v[2], uid=v[3], status=v[4],
                      created_at=v[5], last_seen_at=v[6], acting_as_username=acting_as)


def read_admins(path: str, owner_uid: int = 0) -> frozenset[str]:
    """The usernames in the admins file, read fresh on every call.

    The file must be a regular file (not a symlink) owned by owner_uid (root)
    and not writable by group or others; anything else counts as no admins.
    Blank lines, # comments and lines that aren't valid usernames are skipped.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return frozenset()
    with os.fdopen(fd, encoding="utf-8", errors="replace") as f:
        st = os.fstat(f.fileno())
        if (not stat.S_ISREG(st.st_mode) or st.st_uid != owner_uid
                or st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)):
            return frozenset()
        names = (line.strip() for line in f.read(1024 * 1024).splitlines())
        return frozenset(n for n in names if USERNAME_RE.fullmatch(n))


def _no_session() -> AgentError:
    return AgentError("no_session", "Your session has ended. Sign in again.", 401)


def resolve_caller(peer_uid: int, headers: Mapping[str, str], store: SessionStore,
                   config: AgentConfig, now: datetime | None = None,
                   idle_minutes: int = 30, max_hours: int = 12,
                   admins: Callable[[], frozenset[str]] | None = None) -> Caller:
    """The Caller for one request. headers have lower-cased names.

    The worker account is the worker, whatever header it sends. Anyone else
    needs an X-SD-Session token for an active account whose session is within
    idle_minutes of its last use and max_hours of its start. An admin viewing
    as a user becomes that user, with acting_admin set; the target must be an
    active, non-admin web account (never a shell account).

    role admin also needs the username in the admins file (admins() reads it;
    by default config.admins_file); without it the caller is a user.
    """
    if peer_uid == config.worker_uid:
        return Caller(None, "worker", None, True, None)

    token = headers.get("x-sd-session", "")
    if not token:
        raise _no_session()
    row = store.lookup(hash_token(token))
    if row is None or row.status != "active" or row.role not in ROLES:
        raise _no_session()
    now = now or datetime.now(UTC)
    if (now - row.last_seen_at > timedelta(minutes=idle_minutes)
            or now - row.created_at > timedelta(hours=max_hours)):
        raise _no_session()

    role = row.role
    if role == "admin":
        listed = admins() if admins else read_admins(config.admins_file)
        if row.username not in listed:
            role = "user"

    if row.acting_as_username is None:
        return Caller(row.username, role, row.linux_kind, False, None)

    if role != "admin":
        raise AgentError("not_allowed", "Only admins can view as another user.", 403)
    target = store.account(row.acting_as_username)
    if (target is None or target.status != "active" or target.role != "user"
            or target.linux_kind == "shell"):
        raise AgentError("not_allowed", "You can't view as that account.", 403)
    return Caller(target.username, target.role, target.linux_kind, False, row.username)
