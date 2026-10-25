"""Tickets that let the session origin act for a signed-in browser.

The platform cookie never goes to the session origin, but deck-agent needs the
caller's session token to check ownership. So the app origin, after its own
checks, keeps the token here and hands the browser a one-time code (60 s) in
the redirect. The session origin swaps the code for a ticket id, which goes in
an HttpOnly cookie scoped to /<kind>/<job_id>/. Every request then looks the
token up again and runs the normal session and ownership checks, so a ticket
ends with the platform session.

Kept in memory: the web app runs one process. A restart drops every ticket and
the browser is sent back to the app origin to get a new one.
"""

from __future__ import annotations

import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Ticket:
    id: str
    kind: str
    job_id: str


@dataclass
class _Entry:
    raw_token: str
    kind: str
    job_id: str
    expires: float


class Tickets:
    CODE_TTL_S = 60

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._codes: dict[str, tuple[str, float]] = {}   # code -> (ticket id, expires)
        self._tickets: dict[str, _Entry] = {}

    def issue(self, raw_token: str, kind: str, job_id: str, *, ttl_s: float) -> str:
        """A one-time code for a new ticket for this session, kind and job."""
        now = self._clock()
        ticket_id, code = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self._lock:
            self._prune(now)
            self._tickets[ticket_id] = _Entry(raw_token, kind, job_id, now + ttl_s)
            self._codes[code] = (ticket_id, now + self.CODE_TTL_S)
        return code

    def redeem(self, code: str) -> Ticket | None:
        """The ticket a code stands for; a code works once and only for 60 s."""
        now = self._clock()
        with self._lock:
            found = self._codes.pop(code, None)
            if found is None or found[1] < now:
                return None
            entry = self._tickets.get(found[0])
            if entry is None or entry.expires < now:
                return None
            return Ticket(found[0], entry.kind, entry.job_id)

    def session_token(self, ticket_id: str, kind: str, job_id: str) -> str | None:
        """The platform session token behind a ticket, if it is live and for this job."""
        with self._lock:
            entry = self._tickets.get(ticket_id)
        if (entry is None or entry.expires < self._clock() or entry.kind != kind
                or entry.job_id != job_id):
            return None
        return entry.raw_token

    def _prune(self, now: float) -> None:
        for code in [c for c, (_, exp) in self._codes.items() if exp < now]:
            del self._codes[code]
        for tid in [t for t, e in self._tickets.items() if e.expires < now]:
            del self._tickets[tid]
