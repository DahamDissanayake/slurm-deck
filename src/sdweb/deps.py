"""FastAPI dependencies: the database, the clock, the mailer and the session.

Endpoints commit explicitly; nothing is written unless they do. Errors are
ApiError, sent as `{"error": code, ...}`.
"""

from __future__ import annotations

import hmac
import importlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from sdweb.auth.sessions import load_session
from sdweb.config import WebSettings
from sdweb.models import Account, WebSession

COOKIE = "sd_session"

Mailer = Callable[..., Any]   # mailer(db, *, to, kind, context)


class ApiError(Exception):
    def __init__(self, status: int, code: str, **extra: Any) -> None:
        super().__init__(code)
        self.status, self.code, self.extra = status, code, extra


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


def get_settings(request: Request) -> WebSettings:
    settings: WebSettings = request.app.state.settings
    return settings


def get_now(request: Request) -> datetime:
    now: datetime = request.app.state.clock()
    return now


def get_mailer(request: Request) -> Mailer:
    """Queues mail through sdweb.mail.enqueue (the outbox, SLURM-14)."""
    settings = request.app.state.settings
    enqueue = importlib.import_module("sdweb.mail").enqueue

    def mailer(db: Session, *, to: str, kind: str, context: dict[str, Any]) -> None:
        enqueue(db, to=to, kind=kind, context=context, settings=settings)
    return mailer


Db = Annotated[Session, Depends(get_db)]
Settings = Annotated[WebSettings, Depends(get_settings)]
Now = Annotated[datetime, Depends(get_now)]


@dataclass
class SessionCtx:
    account: Account
    session: WebSession
    raw_token: str
    acting_as: Account | None

    @property
    def effective_account(self) -> Account:
        return self.acting_as or self.account


def current_session(request: Request, db: Db, settings: Settings, now: Now) -> SessionCtx:
    raw = request.cookies.get(COOKIE, "")
    found = load_session(db, raw, settings, now)
    db.commit()   # the refreshed last_seen_at, or the deleted expired row
    if found is None:
        raise ApiError(401, "no_session")
    session, account = found
    acting_as = db.get(Account, session.acting_as_account_id) \
        if session.acting_as_account_id else None
    return SessionCtx(account, session, raw, acting_as)


def require_user(ctx: Annotated[SessionCtx, Depends(current_session)]) -> SessionCtx:
    return ctx


def require_admin(ctx: Annotated[SessionCtx, Depends(current_session)]) -> SessionCtx:
    if ctx.account.role != "admin":
        raise ApiError(403, "not_allowed")
    return ctx


def require_csrf(request: Request,
                 ctx: Annotated[SessionCtx, Depends(current_session)]) -> SessionCtx:
    sent = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(sent.encode(), ctx.session.csrf_token.encode()):
        raise ApiError(403, "csrf")
    return ctx
