"""/api/auth: sign in and out, who am I, and the password flows."""

from __future__ import annotations

import ipaddress
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel
from sqlalchemy import select

from sdweb.audit import record
from sdweb.auth.sessions import (
    LinkError,
    check_password_token,
    create_session,
    end_sessions,
    ip_limited,
    issue_password_token,
    locked_until,
    record_attempt,
    revoke_password_tokens,
)
from sdweb.config import WebSettings
from sdweb.deps import (
    COOKIE,
    ApiError,
    Db,
    Mailer,
    Now,
    SessionCtx,
    Settings,
    current_session,
    get_mailer,
    require_csrf,
)
from sdweb.models import Account
from sdweb.security import (
    hash_password,
    normalize_email,
    password_problems,
    verify_password,
)

router = APIRouter(prefix="/api/auth")

_dummy_hash: str | None = None


def _dummy() -> str:
    """A real hash to verify against when there is no account, so an unknown
    email takes as long as a wrong password."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("no account has this password")
    return _dummy_hash


class AccountOut(BaseModel):
    id: int
    email: str
    full_name: str
    username: str
    role: str
    status: str
    linux_kind: str

    @classmethod
    def of(cls, a: Account) -> AccountOut:
        return cls(id=a.id, email=a.email, full_name=a.full_name, username=a.username,
                   role=a.role, status=a.status, linux_kind=a.linux_kind)


class LoginIn(BaseModel):
    email: str
    password: str


class SetPasswordIn(BaseModel):
    token: str
    password: str


class ForgotIn(BaseModel):
    email: str


class ChangeIn(BaseModel):
    current: str
    new: str


def _client_ip(request: Request) -> str | None:
    """The peer address (Caddy passes the real one through), or None when the
    peer isn't an IP address."""
    host = request.client.host if request.client else ""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


def _set_cookie(response: Response, raw: str, settings: WebSettings) -> None:
    response.set_cookie(COOKIE, raw, httponly=True, secure=settings.secure_cookies,
                        samesite="strict", path="/")


def _check_strength(account: Account, password: str) -> None:
    problems = password_problems(password, email=account.email, username=account.username)
    if problems:
        raise ApiError(422, "weak_password", problems=problems)


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Db, settings: Settings,
          now: Now, mailer: Annotated[Mailer, Depends(get_mailer)]) -> dict:
    email, ip = normalize_email(body.email), _client_ip(request)
    if ip_limited(db, ip, settings, now):
        raise ApiError(429, "rate_limited")
    until = locked_until(db, email, settings, now)
    if until is not None:
        raise ApiError(423, "locked", retry_after_s=int((until - now).total_seconds()) + 1)

    account = db.scalar(select(Account).where(Account.email == email))
    stored = account.password_hash if account is not None and account.status == "active" \
        else None
    ok = verify_password(stored or _dummy(), body.password) and stored is not None
    record_attempt(db, email, ip, ok, now)
    if not ok or account is None:
        record(db, actor_id=account.id if account else None, action="auth.login",
               target=email, result="failed")
        db.flush()
        # Attempts while locked are refused above, so this failure is the one
        # that starts the lock: tell the owner once.
        until = locked_until(db, email, settings, now)
        if account is not None and until is not None:
            mailer(db, to=account.email, kind="lockout", context={"until": until})
        db.commit()
        raise ApiError(401, "bad_credentials")

    raw, session = create_session(db, account, ip=ip,
                                  user_agent=request.headers.get("user-agent", ""), now=now)
    record(db, actor_id=account.id, action="auth.login", target=email)
    db.commit()
    _set_cookie(response, raw, settings)
    return {"account": AccountOut.of(account), "csrf_token": session.csrf_token}


@router.post("/logout")
def logout(ctx: Annotated[SessionCtx, Depends(require_csrf)], response: Response,
           db: Db, settings: Settings) -> dict:
    db.delete(ctx.session)
    record(db, actor_id=ctx.account.id, action="auth.logout")
    db.commit()
    response.delete_cookie(COOKIE, httponly=True, secure=settings.secure_cookies,
                           samesite="strict", path="/")
    return {}


@router.get("/me")
def me(ctx: Annotated[SessionCtx, Depends(current_session)]) -> dict:
    return {"account": AccountOut.of(ctx.account),
            "acting_as": AccountOut.of(ctx.acting_as) if ctx.acting_as else None,
            "csrf_token": ctx.session.csrf_token}


@router.post("/password/set")
def set_password(body: SetPasswordIn, request: Request, response: Response, db: Db,
                 settings: Settings, now: Now) -> dict:
    """Set or reset a password from a one-time link, then sign in."""
    try:
        token, account = check_password_token(db, body.token, now)
    except LinkError as e:
        raise ApiError(400, e.code) from None
    _check_strength(account, body.password)   # a weak password doesn't spend the link
    account.password_hash = hash_password(body.password)
    revoke_password_tokens(db, account.id, now)
    end_sessions(db, account.id)
    raw, session = create_session(db, account, ip=_client_ip(request),
                                  user_agent=request.headers.get("user-agent", ""), now=now)
    record(db, actor_id=account.id, action=f"password.{token.purpose}")
    db.commit()
    _set_cookie(response, raw, settings)
    return {"account": AccountOut.of(account), "csrf_token": session.csrf_token}


@router.post("/password/forgot", status_code=202)
def forgot(body: ForgotIn, db: Db, settings: Settings, now: Now,
           mailer: Annotated[Mailer, Depends(get_mailer)]) -> dict:
    """Always 202, so the reply never says whether an account exists."""
    email = normalize_email(body.email)
    account = db.scalar(select(Account).where(Account.email == email))
    if account is not None and account.status == "active":
        raw = issue_password_token(db, account, "reset", settings, now)
        # The token rides in the fragment, so it never reaches a server log.
        link = f"https://{settings.public_hostname}/reset-password#token={raw}"
        mailer(db, to=account.email, kind="reset_password", context={"link": link})
        record(db, actor_id=account.id, action="password.forgot")
        db.commit()
    return {}


@router.post("/password/change")
def change_password(body: ChangeIn, ctx: Annotated[SessionCtx, Depends(require_csrf)],
                    db: Db, now: Now) -> dict:
    account = ctx.account
    if not account.password_hash or not verify_password(account.password_hash, body.current):
        raise ApiError(400, "wrong_password")
    _check_strength(account, body.new)
    account.password_hash = hash_password(body.new)
    revoke_password_tokens(db, account.id, now)
    end_sessions(db, account.id, keep=ctx.session.token_hash)
    record(db, actor_id=account.id, action="password.change")
    db.commit()
    return {}
