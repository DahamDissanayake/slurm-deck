"""The web audit trail: one audit_events row per action, written in the
caller's transaction so it commits or rolls back with the action itself."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from sdweb.models import AuditEvent


def record(db: Session, *, actor_id: int | None, action: str, target: str = "",
           detail: dict[str, Any] | None = None, result: str = "ok",
           acting_admin_id: int | None = None, source: str = "web") -> None:
    db.add(AuditEvent(actor_id=actor_id, acting_admin_id=acting_admin_id, action=action,
                      target=target, detail=detail or {}, result=result, source=source))
