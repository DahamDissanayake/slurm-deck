"""Disk-full alert: if /shared is over the admin's percentage, mail the admins, then wait 24 h."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdweb.config import WebSettings
from sdweb.jobs.service import setting
from sdweb.mail import enqueue, templates
from sdweb.models import Account, Setting

QUIET = timedelta(hours=24)

templates.register(
    "disk_alert",
    lambda c: f"The shared disk on {c['cluster']} is {c['percent']}% full",
    lambda c: [f"The shared storage on {c['cluster']} is {c['percent']}% full "
               f"({c['free']} free of {c['total']}). Uploads and job output fail when it fills.",
               "You'll get this reminder at most once a day.",
               templates.Button("See disk use by user", c["link"])])


def run_once(db: Session, agent: Any, now: datetime, settings: WebSettings) -> int:
    """Mail the active admins if the disk is over the threshold and no alert went
    out in the last 24 hours; returns how many were queued."""
    disk = agent.call("cluster.disk_free", {}, session=None)
    total, used = int(disk["total_bytes"]), int(disk["used_bytes"])
    percent, gb = used * 100 // max(total, 1), 1024 ** 3
    if percent < int(setting(db, "disk_alert_percent", 90)):
        return 0
    last = setting(db, "last_disk_alert_at", None)
    if last and now - datetime.fromisoformat(last) < QUIET:
        return 0
    admins = db.scalars(select(Account).where(Account.role == "admin",
                                              Account.status == "active")).all()
    for admin in admins:
        enqueue(db, to=admin.email, kind="disk_alert", settings=settings, now=now,
                context={"cluster": settings.cluster_name, "percent": str(percent),
                         "free": f"{(total - used) / gb:.0f} GB", "total": f"{total / gb:.0f} GB",
                         "link": f"https://{settings.public_hostname}/admin/usage"})
    db.merge(Setting(key="last_disk_alert_at", value=now.isoformat(), updated_at=now))
    return len(admins)
