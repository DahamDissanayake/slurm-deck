"""The 30-minute warning: one email per job before it reaches its time limit.

The job is marked warned in the same transaction as its mail row, so a worker
restarted mid-pass can't send the warning twice, and a failed pass leaves the
job unmarked to try again.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from sdweb.config import WebSettings
from sdweb.mail import enqueue, templates
from sdweb.models import Account, Job

WARN_S = 30 * 60

templates.register(
    "job_expiring",
    lambda c: f"Job {c['job_id']} on {c['cluster']} ends in {c['minutes_left']} minutes",
    lambda c: [f"Your job {c['name']} ({c['job_id']}) reaches its time limit in about "
               f"{c['minutes_left']} minutes.",
               "Extend it now if it needs longer; otherwise it will be stopped.",
               templates.Button("Extend the job", c["link"])])


def run_once(db: Session, agent: Any, now: datetime, settings: WebSettings) -> int:
    """Warn every running job with 30 minutes or less left, once; returns how many."""
    sent = 0
    for j in agent.call("job.time_left_all", {}, session=None).get("jobs", []):
        left = j.get("time_left_s")
        if j.get("state") != "RUNNING" or left is None or left > WARN_S:
            continue
        job = db.get(Job, str(j.get("job_id")), with_for_update={"skip_locked": True})
        if job is None or job.warned_at is not None:
            continue   # not submitted through the web, or already warned
        account = db.get(Account, job.account_id)
        if account is None or account.status != "active":
            continue
        job.warned_at = now
        enqueue(db, to=account.email, kind="job_expiring", settings=settings, now=now,
                context={"job_id": job.job_id, "name": job.name, "minutes_left": str(left // 60),
                         "link": f"https://{settings.public_hostname}/jobs/{job.job_id}?extend=1"})
        sent += 1
    return sent
