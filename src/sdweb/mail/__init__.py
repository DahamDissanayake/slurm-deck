"""Outgoing mail goes through the outbox: a request only writes a row, and the
worker sends it (sdweb.worker.mail_task), so a slow provider never blocks a
request."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdweb.config import WebSettings, load_settings
from sdweb.mail import templates
from sdweb.models import OutboxMessage, Setting

MAIL_DISABLED = "mail disabled"


def mail_enabled(db: Session) -> bool:
    """The admin's mail kill-switch (setting mail_enabled, on unless set false)."""
    value = db.scalar(select(Setting.value).where(Setting.key == "mail_enabled"))
    return value is not False


def enqueue(db: Session, *, to: str, kind: str, context: dict[str, Any],
            settings: WebSettings | None = None, now: datetime | None = None) -> int:
    """Render and queue one mail; returns the outbox id. With mail turned off
    the row is kept as a record, marked so it is never sent."""
    settings = settings or load_settings(os.environ)
    subject, html, text = templates.render(kind, context, settings)
    now = now or datetime.now(UTC)
    row = OutboxMessage(to_addr=to, subject=subject, html=html, text=text, kind=kind,
                        created_at=now, next_attempt_at=now,
                        last_error=None if mail_enabled(db) else MAIL_DISABLED)
    db.add(row)
    db.flush()
    return row.id
