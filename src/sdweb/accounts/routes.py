"""/api/admin: account management and View as user (admins only; CSRF on writes)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import or_, select

from sdcore.names import RESERVED, suggest_username, valid_username
from sdweb.accounts.service import (
    agent_call,
    create_account,
    email_taken,
    get_account,
    guard_admin_change,
    send_link,
)
from sdweb.audit import record
from sdweb.auth.routes import AccountOut
from sdweb.auth.sessions import end_sessions
from sdweb.deps import ApiError, Db, Mailer, Now, SessionCtx, Settings, get_mailer, require_admin
from sdweb.deps import require_csrf as _csrf
from sdweb.models import Account
from sdweb.security import normalize_email, valid_email

router = APIRouter(prefix="/api/admin")

Admin = Annotated[SessionCtx, Depends(require_admin)]
Mail = Annotated[Mailer, Depends(get_mailer)]
ROLES = ("user", "admin")


def require_admin_csrf(ctx: Annotated[SessionCtx, Depends(_csrf)]) -> SessionCtx:
    return require_admin(ctx)


AdminWrite = Annotated[SessionCtx, Depends(require_admin_csrf)]


def _agent(request: Request) -> Any:
    return request.app.state.agent


class AccountRow(AccountOut):
    uid: int | None
    created_at: Any
    last_login_at: Any

    @classmethod
    def row(cls, a: Account) -> AccountRow:
        return cls(**AccountOut.of(a).model_dump(), uid=a.uid, created_at=a.created_at,
                   last_login_at=a.last_login_at)


class PreviewIn(BaseModel):
    email: str
    username: str | None = None


class CreateIn(BaseModel):
    email: str
    full_name: str
    username: str
    role: str = "user"
    reconnect_folder: bool = False
    attach_shell: bool = False


class EditIn(BaseModel):
    role: str | None = None
    email: str | None = None
    full_name: str | None = None


class DeleteIn(BaseModel):
    confirm: str = ""


def _username_ok(name: str) -> bool:
    return valid_username(name) and name not in RESERVED


@router.get("/accounts")
def list_accounts(ctx: Admin, db: Db, q: str = "", role: str = "", status: str = "") -> dict:
    query = select(Account).where(Account.status != "deleted").order_by(Account.username)
    if q:
        like = f"%{q}%"
        query = query.where(or_(Account.email.ilike(like), Account.username.ilike(like),
                                Account.full_name.ilike(like)))
    if role:
        query = query.where(Account.role == role)
    if status:
        query = query.where(Account.status == status)
    return {"accounts": [AccountRow.row(a) for a in db.scalars(query)]}


@router.post("/accounts/preview")
def preview(body: PreviewIn, ctx: AdminWrite, db: Db, request: Request) -> dict:
    email = normalize_email(body.email)
    taken = set(db.scalars(select(Account.username)))
    suggested = suggest_username(email, taken) if "@" in email else ""
    name = body.username or suggested
    folder = shell = None
    if _username_ok(name):
        info = agent_call(_agent(request), "account.inspect_folder", {"username": name},
                          ctx.raw_token)
        folder = info if info.get("exists") else None
        try:
            shell = agent_call(_agent(request), "account.attach_shell", {"username": name},
                               ctx.raw_token)
        except ApiError:
            shell = None
    return {"suggested_username": suggested, "email_valid": valid_email(email),
            "username_valid": _username_ok(name) and name not in taken,
            "existing_folder": folder, "shell_account": shell}


@router.post("/accounts")
def create(body: CreateIn, ctx: AdminWrite, db: Db, request: Request, settings: Settings,
           now: Now, mailer: Mail) -> AccountRow:
    email = normalize_email(body.email)
    if not valid_email(email) or not body.full_name.strip():
        raise ApiError(422, "bad_input", message="Enter a valid email and a name.")
    if not _username_ok(body.username) or body.role not in ROLES:
        raise ApiError(422, "bad_input", message="That username or role isn't allowed.")
    if body.reconnect_folder and body.attach_shell:
        raise ApiError(422, "bad_input", message="Choose reconnect or attach, not both.")
    account = create_account(
        db, admin=ctx.account, session=ctx.raw_token, agent=_agent(request), email=email,
        full_name=body.full_name.strip(), username=body.username, role=body.role,
        reconnect_folder=body.reconnect_folder, attach_shell=body.attach_shell,
        settings=settings, now=now, mailer=mailer)
    db.commit()
    return AccountRow.row(account)


def _set_status(ctx: SessionCtx, db: Db, account_id: int, status: str,
                action: str) -> AccountRow:
    target = get_account(db, account_id, lock=True)
    if status == "disabled":   # blocks sign-in and ends sessions; cancels nothing
        guard_admin_change(db, ctx.account, target)
        end_sessions(db, target.id)
    target.status = status
    record(db, actor_id=ctx.account.id, action=action, target=target.username)
    db.commit()
    return AccountRow.row(target)


@router.post("/accounts/{account_id}/disable")
def disable(account_id: int, ctx: AdminWrite, db: Db) -> AccountRow:
    return _set_status(ctx, db, account_id, "disabled", "account.disable")


@router.post("/accounts/{account_id}/enable")
def enable(account_id: int, ctx: AdminWrite, db: Db) -> AccountRow:
    return _set_status(ctx, db, account_id, "active", "account.enable")


@router.post("/accounts/{account_id}/reset-password")
def reset_password(account_id: int, ctx: AdminWrite, db: Db, settings: Settings, now: Now,
                   mailer: Mail) -> dict:
    target = get_account(db, account_id)
    send_link(db, target, "reset", settings, now, mailer)
    record(db, actor_id=ctx.account.id, action="account.reset_password", target=target.username)
    db.commit()
    return {}


@router.patch("/accounts/{account_id}")
def edit(account_id: int, body: EditIn, ctx: AdminWrite, db: Db) -> AccountRow:
    target = get_account(db, account_id, lock=True)
    changes: dict[str, str] = {}
    if body.role is not None and body.role != target.role:
        if body.role not in ROLES:
            raise ApiError(422, "bad_input", message="Unknown role.")
        if target.role == "admin":
            guard_admin_change(db, ctx.account, target)
        changes["role"] = target.role = body.role
    if body.email is not None:
        email = normalize_email(body.email)
        if not valid_email(email):
            raise ApiError(422, "bad_input", message="Enter a valid email.")
        if email_taken(db, email, except_id=target.id):
            raise ApiError(409, "account_exists", message="That email is already used.")
        changes["email"] = target.email = email
    if body.full_name is not None and body.full_name.strip():
        changes["full_name"] = target.full_name = body.full_name.strip()
    record(db, actor_id=ctx.account.id, action="account.edit", target=target.username,
           detail=changes)
    db.commit()
    return AccountRow.row(target)


@router.delete("/accounts/{account_id}")
def delete(account_id: int, ctx: AdminWrite, db: Db, request: Request, purge: bool = False,
           body: DeleteIn | None = None) -> dict:
    target = get_account(db, account_id, lock=True)
    guard_admin_change(db, ctx.account, target)
    if purge and (body is None or body.confirm != target.username):
        raise ApiError(400, "confirm_mismatch",
                       message="Type the username to confirm deleting their files.")
    if target.linux_kind == "hidden":
        agent_call(_agent(request), "account.delete",
                   {"username": target.username, "purge": purge}, ctx.raw_token)
    end_sessions(db, target.id)
    target.status = "deleted"
    # Frees the email for a new account; the row stays for the audit trail.
    target.email = f"deleted-{target.id}@deleted.invalid"
    record(db, actor_id=ctx.account.id, action="account.delete", target=target.username,
           detail={"purge": purge})
    db.commit()
    return {}


@router.post("/view-as/{account_id}")
def view_as(account_id: int, ctx: AdminWrite, db: Db) -> dict:
    target = get_account(db, account_id)
    if target.status != "active" or target.role != "user" or target.linux_kind != "hidden":
        raise ApiError(403, "not_allowed", message="You can't view as that account.")
    ctx.session.acting_as_account_id = target.id
    record(db, actor_id=ctx.account.id, action="admin.view_as", target=target.username)
    db.commit()
    return {"acting_as": AccountOut.of(target)}


@router.delete("/view-as")
def stop_view_as(ctx: AdminWrite, db: Db) -> dict:
    ctx.session.acting_as_account_id = None
    record(db, actor_id=ctx.account.id, action="admin.view_as_end")
    db.commit()
    return {}
