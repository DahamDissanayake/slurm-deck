"""Drain the outbox: send due mail, back off on failure, give up after 8 tries."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from sdweb.mail import MAIL_DISABLED, mail_enabled
from sdweb.mail.senders import Sender
from sdweb.models import OutboxMessage

log = logging.getLogger("sdweb.worker")

MAX_ATTEMPTS = 8
BATCH = 50


def backoff(attempts: int) -> timedelta:
    """+2 min after the first failure, then +4, +8 ... capped at 6 h."""
    return timedelta(minutes=min(2 ** attempts, 360))


def drain(db: Session, sender: Sender, now: datetime) -> int:
    """Send every due row; returns how many were sent. Rows are locked with
    SKIP LOCKED, so two workers never send the same mail."""
    if not mail_enabled(db):
        return 0
    rows = db.scalars(
        select(OutboxMessage)
        .where(OutboxMessage.sent_at.is_(None), OutboxMessage.attempts < MAX_ATTEMPTS,
               OutboxMessage.next_attempt_at <= now,
               or_(OutboxMessage.last_error.is_(None),
                   OutboxMessage.last_error != MAIL_DISABLED))
        .order_by(OutboxMessage.id).limit(BATCH).with_for_update(skip_locked=True)).all()
    sent = 0
    for row in rows:
        try:
            sender.send(row.to_addr, row.subject, row.html, row.text)
        except Exception as e:
            row.attempts += 1
            row.last_error = str(e)[:500] or type(e).__name__
            row.next_attempt_at = now + backoff(row.attempts)
            log.warning("mail %s to %s failed (attempt %s): %s", row.id, row.to_addr,
                        row.attempts, row.last_error)
        else:
            row.sent_at, row.last_error = now, None
            sent += 1
    return sent
