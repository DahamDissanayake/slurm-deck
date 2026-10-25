"""Access applications: the public Apply form and the admin decision.

The form is open only while the allow-list has entries. An email the list
doesn't match is refused and nothing is kept; the honeypot field quietly
drops bots. Approve creates the account exactly as an admin would (deck-agent
first), and the row lock means two admins approving at once make one account.
"""

from __future__ import annotations

import ipaddress
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from sdweb.accounts.allowlist import apply_open, matches
from sdweb.accounts.routes import ROLES, _username_ok
from sdweb.accounts.service import create_account
from sdweb.audit import record
from sdweb.deps import (
    ApiError,
    Db,
    Mailer,
    Now,
    SessionCtx,
    Settings,
    get_mailer,
    require_admin,
    require_csrf,
)
from sdweb.models import Account, AllowEntry, Application
from sdweb.security import normalize_email, valid_email

router = APIRouter()

REFUSED = "Applications from this email aren't open — contact the cluster admin."
RECEIVED = "Application received — you'll get an email once an admin reviews it."
PENDING = "You already have an application waiting for review."
PER_IP_PER_HOUR = 5

Mail = Annotated[Mailer, Depends(get_mailer)]


def _admin_write(ctx: Annotated[SessionCtx, Depends(require_csrf)]) -> SessionCtx:
    return require_admin(ctx)


AdminWrite = Annotated[SessionCtx, Depends(_admin_write)]


class ApplyIn(BaseModel):
    email: str
    full_name: str
    role_title: str
    contact_number: str
    organisation: str | None = None
    reason: str | None = None
    website: str = ""   # honeypot: people never see it, bots fill it in


class ApproveIn(BaseModel):
    username: str
    role: str = "user"
    reconnect_folder: bool = False


class RejectIn(BaseModel):
    note: str | None = None


def _ip(request: Request) -> str | None:
    host = request.client.host if request.client else ""
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return None


@router.get("/api/public/apply-open")
def is_open(db: Db) -> dict:
    return {"open": apply_open(db)}


@router.get("/api/public/site")
def site(settings: Settings) -> dict:
    """What the sign-in page needs to help someone whose network can't resolve the name."""
    return {"hostname": settings.public_hostname, "lan_addr": settings.lan_addr}


@router.post("/api/public/applications", status_code=201)
def apply(body: ApplyIn, request: Request, db: Db, now: Now, mailer: Mail) -> JSONResponse:
    if body.website:
        return JSONResponse({"message": RECEIVED}, status_code=201)
    email = normalize_email(body.email)
    fields = (body.full_name, body.role_title, body.contact_number)
    if not valid_email(email) or not all(f.strip() for f in fields):
        raise ApiError(422, "bad_input", message="Fill in every required field.")
    if not matches(db.scalars(select(AllowEntry)), email):
        raise ApiError(403, "not_allowed", message=REFUSED)
    ip = _ip(request)
    if ip is not None and (db.scalar(select(func.count()).select_from(Application).where(
            Application.ip == ip, Application.created_at > now - timedelta(hours=1))) or 0
            ) >= PER_IP_PER_HOUR:
        raise ApiError(429, "rate_limited", message="Too many applications. Try again later.")
    if db.scalar(select(Application.id).where(Application.email == email,
                                              Application.status == "pending")) is not None:
        raise ApiError(409, "pending", message=PENDING)
    app = Application(email=email, full_name=body.full_name.strip(),
                      role_title=body.role_title.strip(), organisation=body.organisation,
                      contact_number=body.contact_number.strip(), reason=body.reason,
                      status="pending", created_at=now, ip=ip)
    db.add(app)
    db.flush()
    details = {"email": email, "full_name": app.full_name, "role_title": app.role_title,
               "organisation": app.organisation or "", "contact_number": app.contact_number,
               "reason": app.reason or ""}
    for admin in db.scalars(select(Account).where(Account.role == "admin",
                                                  Account.status == "active")):
        mailer(db, to=admin.email, kind="application_received_admin",
               context={"application": details})
    record(db, actor_id=None, action="application.submit", target=email)
    db.commit()
    return JSONResponse({"message": RECEIVED}, status_code=201)


@router.get("/api/admin/applications")
def list_applications(ctx: Annotated[SessionCtx, Depends(require_admin)], db: Db,
                      status: str = "pending") -> dict:
    rows = db.scalars(select(Application).where(Application.status == status)
                      .order_by(Application.created_at))
    return {"applications": [
        {"id": a.id, "email": a.email, "full_name": a.full_name, "role_title": a.role_title,
         "organisation": a.organisation, "contact_number": a.contact_number,
         "reason": a.reason, "status": a.status, "created_at": a.created_at,
         "decided_at": a.decided_at, "note": a.note, "account_id": a.account_id}
        for a in rows]}


def _pending(db: Db, app_id: int) -> Application:
    app = db.get(Application, app_id, with_for_update=True)   # one decision at a time
    if app is None:
        raise ApiError(404, "not_found")
    if app.status != "pending":
        raise ApiError(409, "already_decided", message="This application was already decided.")
    return app


@router.post("/api/admin/applications/{app_id}/approve")
def approve(app_id: int, body: ApproveIn, ctx: AdminWrite, db: Db, request: Request,
            settings: Settings, now: Now, mailer: Mail) -> dict:
    app = _pending(db, app_id)
    if not _username_ok(body.username) or body.role not in ROLES:
        raise ApiError(422, "bad_input", message="That username or role isn't allowed.")
    account = create_account(
        db, admin=ctx.account, session=ctx.raw_token, agent=request.app.state.agent,
        email=app.email, full_name=app.full_name, username=body.username, role=body.role,
        reconnect_folder=body.reconnect_folder, attach_shell=False, settings=settings,
        now=now, mailer=mailer, link_kind="application_approved")
    app.status, app.account_id = "approved", account.id
    app.decided_by_id, app.decided_at = ctx.account.id, now
    record(db, actor_id=ctx.account.id, action="application.approve", target=app.email,
           detail={"username": account.username})
    db.commit()
    return {"account_id": account.id}


@router.post("/api/admin/applications/{app_id}/reject")
def reject(app_id: int, body: RejectIn, ctx: AdminWrite, db: Db, now: Now,
           mailer: Mail) -> dict:
    app = _pending(db, app_id)
    note = (body.note or "").strip() or None
    app.status, app.note = "rejected", note
    app.decided_by_id, app.decided_at = ctx.account.id, now
    mailer(db, to=app.email, kind="application_rejected", context={"note": note or ""})
    record(db, actor_id=ctx.account.id, action="application.reject", target=app.email)
    db.commit()
    return {}
