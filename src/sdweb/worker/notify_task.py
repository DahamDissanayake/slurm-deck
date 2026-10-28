"""Notify when free: when enough pods are free, mail the subscriber once and
delete the subscription in the same transaction as the mail row."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdweb.config import WebSettings
from sdweb.mail import enqueue, templates
from sdweb.models import Account, NotifySubscription

templates.register(
    "pods_free",
    lambda c: f"{c['free']} pods are free on {c['cluster']}",
    lambda c: [f"You asked to hear when {c['wanted']} pods are free. Right now {c['free']} of "
               f"{c['total']} are.",
               "This was a one-time notice; subscribe again if you want another.",
               templates.Button("Start a job", f"{c['site']}/new")])


def run_once(db: Session, agent: Any, now: datetime, settings: WebSettings) -> int:
    subs = db.scalars(select(NotifySubscription).with_for_update(skip_locked=True)).all()
    if not subs:
        return 0   # nobody is waiting: don't ask the cluster
    status = agent.call("cluster.status", {}, session=None)
    total = int(status.get("pods_total") or 0)
    free = total - int(status.get("pods_used") or 0)
    sent = 0
    for sub in subs:
        account = db.get(Account, sub.account_id)
        if account is None or sub.wanted_pods > free:
            continue
        enqueue(db, to=account.email, kind="pods_free", settings=settings, now=now,
                context={"free": str(free), "total": str(total), "wanted": str(sub.wanted_pods)})
        db.delete(sub)
        sent += 1
    return sent
