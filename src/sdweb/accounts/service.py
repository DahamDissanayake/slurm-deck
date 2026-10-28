"""Account rules shared by the admin routes: lookups, the admin guards,
deck-agent calls, and creating an account only once deck-agent has made the
Linux side."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from sdweb.agent import AgentCallError
from sdweb.audit import record
from sdweb.auth.sessions import issue_password_token
from sdweb.config import WebSettings
from sdweb.deps import ApiError, Mailer
from sdweb.models import Account

LAST_ADMIN = "There must always be at least one active admin."


def get_account(db: Session, account_id: int, *, lock: bool = False) -> Account:
    account = db.get(Account, account_id, with_for_update=lock)
    if account is None or account.status == "deleted":
        raise ApiError(404, "not_found")
    return account


def agent_call(agent: Any, verb: str, payload: dict[str, Any], session: str) -> Any:
    if agent is None:
        raise ApiError(503, "agent_unavailable", message="deck-agent is not connected.")
    try:
        return agent.call(verb, payload, session=session)
    except AgentCallError as e:
        status = e.status if 400 <= e.status < 500 else 502
        raise ApiError(status, e.code, message=e.message) from None


def guard_admin_change(db: Session, actor: Account, target: Account) -> None:
    """Before disabling, deleting or demoting target: one active admin must
    remain, and admins don't do this to themselves."""
    if target.role == "admin" and target.status == "active":
        others = db.scalar(select(func.count()).select_from(Account).where(
            Account.role == "admin", Account.status == "active", Account.id != target.id))
        if not others:
            raise ApiError(409, "last_admin", message=LAST_ADMIN)
    if target.id == actor.id:
        raise ApiError(409, "self", message="You can't do that to your own account.")


def email_taken(db: Session, email: str, except_id: int | None = None) -> bool:
    q = select(Account.id).where(Account.email == email)
    if except_id is not None:
        q = q.where(Account.id != except_id)
    return db.scalar(q) is not None


def send_link(db: Session, account: Account, purpose: str, settings: WebSettings,
              now: datetime, mailer: Mailer, kind: str | None = None) -> None:
    """Mail a one-time set or reset link (as mail kind, default <purpose>_password)."""
    raw = issue_password_token(db, account, purpose, settings, now)
    page = "set-password" if purpose == "set" else "reset-password"
    mailer(db, to=account.email, kind=kind or f"{purpose}_password",
           context={"link": f"https://{settings.public_hostname}/{page}#token={raw}"})


def create_account(db: Session, *, admin: Account, session: str, agent: Any, email: str,
                   full_name: str, username: str, role: str, reconnect_folder: bool,
                   attach_shell: bool, settings: WebSettings, now: datetime,
                   mailer: Mailer, link_kind: str = "set_password") -> Account:
    """deck-agent first; the row only after it succeeds, so a failure leaves
    nothing behind and the same email and username can be tried again."""
    # Serialises creates of one username; released with the transaction.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"account:{username}"})
    if email_taken(db, email) or db.scalar(select(Account.id).where(
            Account.username == username)) is not None:
        raise ApiError(409, "account_exists", message="That email or username is already used.")
    kind, home = "hidden", None
    if attach_shell:
        shell = agent_call(agent, "account.attach_shell", {"username": username}, session)
        uid, kind, home = int(shell["uid"]), "shell", shell.get("home")
    elif reconnect_folder:
        info = agent_call(agent, "account.inspect_folder", {"username": username}, session)
        if not info.get("exists") or info.get("owner_uid") is None:
            raise ApiError(409, "no_folder", message=f"There is no folder for {username}.")
        uid = int(info["owner_uid"])
        agent_call(agent, "account.create",
                   {"username": username, "uid": uid, "link_existing": True}, session)
    else:
        uid = int(db.scalar(text("SELECT nextval('web_uid_seq')")) or 0)
        agent_call(agent, "account.create", {"username": username, "uid": uid}, session)

    account = Account(email=email, full_name=full_name, username=username, role=role,
                      status="active", linux_kind=kind, uid=uid, created_by_id=admin.id,
                      created_at=now, home=home)
    db.add(account)
    db.flush()
    send_link(db, account, "set", settings, now, mailer, kind=link_kind)
    others = db.scalars(select(Account).where(Account.role == "admin", Account.status == "active",
                                              Account.id != admin.id)).all()
    for other in others:
        mailer(db, to=other.email, kind="account_created_admin_notice",
               context={"username": username, "created_by": admin.username})
    record(db, actor_id=admin.id, action="account.create", target=username,
           detail={"uid": uid, "linux_kind": kind, "role": role})
    return account
