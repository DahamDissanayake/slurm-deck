"""/api/admin monitoring: the audit trail, deck-agent's own log, the mail log
and service health. Lists are paged on the server (one extra row says whether
there is a next page) and filtered on indexed columns, so the first page of a
very large audit trail is quick."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import aliased

from sdweb.accounts.service import agent_call
from sdweb.deps import ApiError, Db, SessionCtx, require_admin
from sdweb.mail import MAIL_DISABLED
from sdweb.models import Account, AuditEvent, OutboxMessage

router = APIRouter()
Admin = Annotated[SessionCtx, Depends(require_admin)]
MAX_PAGE = 200


def _when(text: str | None, what: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text) if text else None
    except ValueError:
        raise ApiError(422, "bad_date", message=f"{what} must be a date and time.") from None


@router.get("/audit")
def audit(ctx: Admin, db: Db, actor: str = "", action: str = "",
          from_: Annotated[str | None, Query(alias="from")] = None, to: str | None = None,
          page: int = 1, page_size: int = 50) -> dict:
    page, size = max(page, 1), min(max(page_size, 1), MAX_PAGE)
    who, admin = aliased(Account), aliased(Account)
    q = (select(AuditEvent, who.username, admin.username)
         .outerjoin(who, AuditEvent.actor_id == who.id)
         .outerjoin(admin, AuditEvent.acting_admin_id == admin.id))
    if actor:
        q = q.where(AuditEvent.actor_id == select(Account.id).where(
            Account.username == actor).scalar_subquery())
    if action:
        q = q.where(AuditEvent.action.startswith(action, autoescape=True))
    if start := _when(from_, "From"):
        q = q.where(AuditEvent.ts >= start)
    if end := _when(to, "To"):
        q = q.where(AuditEvent.ts <= end)
    rows = db.execute(q.order_by(AuditEvent.ts.desc(), AuditEvent.id.desc())
                      .limit(size + 1).offset((page - 1) * size)).all()
    return {"page": page, "has_more": len(rows) > size,
            "events": [{"id": e.id, "ts": e.ts.isoformat(), "actor": u, "acting_admin": a,
                        "action": e.action, "target": e.target, "detail": e.detail,
                        "result": e.result, "source": e.source} for e, u, a in rows[:size]]}


@router.get("/agent-audit")
def agent_audit(ctx: Admin, request: Request, since: str | None = None, limit: int = 100) -> Any:
    """deck-agent's own log of what it did, newest first."""
    return agent_call(request.app.state.agent, "admin.audit_tail",
                      {"since_ts": since, "limit": limit}, ctx.raw_token)


@router.get("/mail-log")
def mail_log(ctx: Admin, db: Db, status: str = "", page: int = 1, page_size: int = 50) -> dict:
    page, size = max(page, 1), min(max(page_size, 1), MAX_PAGE)
    m = OutboxMessage
    unsent = [m.sent_at.is_(None)]
    filters: dict[str, list[Any]] = {"": [], "sent": [m.sent_at.is_not(None)],
               "disabled": [*unsent, m.last_error == MAIL_DISABLED],
               "failed": [*unsent, m.last_error.is_not(None), m.last_error != MAIL_DISABLED],
               "pending": [*unsent, m.last_error.is_(None)]}
    if status not in filters:
        raise ApiError(422, "bad_status", message="Use sent, pending, failed or disabled.")
    rows = db.scalars(select(m).where(*filters[status]).order_by(m.id.desc())
                      .limit(size + 1).offset((page - 1) * size)).all()
    return {"page": page, "has_more": len(rows) > size,
            "mail": [{"id": r.id, "to": r.to_addr, "subject": r.subject, "kind": r.kind,
                      "created_at": r.created_at.isoformat(), "attempts": r.attempts,
                      "status": ("sent" if r.sent_at else "failed" if r.last_error else "pending")
                      if r.last_error != MAIL_DISABLED else "disabled",
                      "error": r.last_error} for r in rows[:size]]}


@router.get("/services")
def services(ctx: Admin, request: Request) -> Any:
    return agent_call(request.app.state.agent, "admin.service_status", {}, ctx.raw_token)
