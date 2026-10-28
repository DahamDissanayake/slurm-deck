"""Sessions, password links and sign-in throttling, on the database.

Only hashes of session and link tokens are stored. A session ends after
SESSION_IDLE_MINUTES without use or SESSION_MAX_HOURS after sign-in, whichever
comes first. Ten failed sign-ins for one email in LOCKOUT_WINDOW_MIN lock it for
LOCKOUT_MIN; one IP gets IP_ATTEMPTS attempts per window.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.orm import Session

from sdweb.config import WebSettings
from sdweb.models import Account, LoginAttempt, PasswordToken, WebSession
from sdweb.security import hash_token, new_token

IP_ATTEMPTS = 30


def create_session(db: Session, account: Account, *, ip: str | None, user_agent: str,
                   now: datetime) -> tuple[str, WebSession]:
    raw = new_token()
    row = WebSession(token_hash=hash_token(raw), account_id=account.id, csrf_token=new_token(),
                     created_at=now, last_seen_at=now, ip=ip, user_agent=user_agent[:500])
    db.add(row)
    account.last_login_at = now
    return raw, row


def load_session(db: Session, raw: str, settings: WebSettings,
                 now: datetime) -> tuple[WebSession, Account] | None:
    """The live session for a raw token, its last use refreshed; an expired one
    is deleted. None if there is no usable session."""
    row = db.get(WebSession, hash_token(raw)) if raw else None
    if row is None:
        return None
    account = db.get(Account, row.account_id)
    if (account is None or account.status != "active"
            or now - row.last_seen_at > timedelta(minutes=settings.session_idle_minutes)
            or now - row.created_at > timedelta(hours=settings.session_max_hours)):
        db.delete(row)
        return None
    row.last_seen_at = now
    return row, account


def peek_session(db: Session, raw: str, settings: WebSettings,
                 now: datetime) -> tuple[WebSession, Account] | None:
    """Like load_session, but changes nothing: a background check (the live
    socket) mustn't keep an idle session alive."""
    row = db.get(WebSession, hash_token(raw)) if raw else None
    account = db.get(Account, row.account_id) if row else None
    if (row is None or account is None or account.status != "active"
            or now - row.last_seen_at > timedelta(minutes=settings.session_idle_minutes)
            or now - row.created_at > timedelta(hours=settings.session_max_hours)):
        return None
    return row, account


def end_sessions(db: Session, account_id: int, *, keep: str | None = None) -> None:
    """Delete every session of an account, except the one with token hash keep."""
    q = delete(WebSession).where(WebSession.account_id == account_id)
    if keep is not None:
        q = q.where(WebSession.token_hash != keep)
    db.execute(q)


def issue_password_token(db: Session, account: Account, purpose: str, settings: WebSettings,
                         now: datetime) -> str:
    """A one-time set or reset link token (raw); earlier unused ones stop working."""
    hours = settings.set_link_hours if purpose == "set" else settings.reset_link_hours
    revoke_password_tokens(db, account.id, now)
    raw = new_token()
    db.add(PasswordToken(token_hash=hash_token(raw), account_id=account.id, purpose=purpose,
                         created_at=now, expires_at=now + timedelta(hours=hours)))
    return raw


def revoke_password_tokens(db: Session, account_id: int, now: datetime) -> None:
    db.execute(update(PasswordToken)
               .where(PasswordToken.account_id == account_id, PasswordToken.used_at.is_(None))
               .values(used_at=now))


def check_password_token(db: Session, raw: str, now: datetime) -> tuple[PasswordToken, Account]:
    """The token and its account, or LinkError with link_invalid, link_used or link_expired."""
    token = db.get(PasswordToken, hash_token(raw), with_for_update=True) if raw else None
    account = db.get(Account, token.account_id) if token else None
    if token is None or account is None or account.status != "active":
        raise LinkError("link_invalid")
    if token.used_at is not None:
        raise LinkError("link_used")
    if now >= token.expires_at:
        raise LinkError("link_expired")
    return token, account


class LinkError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _count(db: Session, *where: ColumnElement[bool], since: datetime) -> int:
    return db.scalar(select(func.count()).select_from(LoginAttempt)
                     .where(LoginAttempt.at > since, *where)) or 0


def ip_limited(db: Session, ip: str | None, settings: WebSettings, now: datetime) -> bool:
    since = now - timedelta(minutes=settings.lockout_window_min)
    return ip is not None and _count(db, LoginAttempt.ip == ip, since=since) >= IP_ATTEMPTS


def locked_until(db: Session, email: str, settings: WebSettings,
                 now: datetime) -> datetime | None:
    """When the email's lock ends, or None if it isn't locked."""
    since = now - timedelta(minutes=settings.lockout_window_min + settings.lockout_min)
    fails = db.scalars(select(LoginAttempt.at)
                       .where(LoginAttempt.email == email, LoginAttempt.success.is_(False),
                              LoginAttempt.at > since)
                       .order_by(LoginAttempt.at.desc())).all()
    window = timedelta(minutes=settings.lockout_window_min)
    # Locked when LOCKOUT_FAILS failures fit in one window; it lasts LOCKOUT_MIN
    # from the failure that completed it.
    for i in range(len(fails) - settings.lockout_fails + 1):
        newest, oldest = fails[i], fails[i + settings.lockout_fails - 1]
        until = newest + timedelta(minutes=settings.lockout_min)
        if newest - oldest <= window and until > now:
            return until
    return None


def record_attempt(db: Session, email: str, ip: str | None, success: bool,
                   now: datetime) -> None:
    db.add(LoginAttempt(email=email, ip=ip, at=now, success=success))
