"""Where a session lives: ask deck-agent (session.info, which checks that the
caller owns the job or is an admin) and turn the answer into an upstream."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from sdweb.agent import AgentCallError
from sdweb.audit import record
from sdweb.deps import SessionCtx
from sdweb.models import Account, AuditEvent, Job

KINDS = ("notebook", "terminal", "tensorboard")
JOB_ID = re.compile(r"[0-9]{1,12}(_[0-9]+)?")
CACHE_S = 15
AUDIT_EVERY = timedelta(hours=1)
LIVE_STATES = {"PENDING", "CONFIGURING", "RUNNING", "SUSPENDED", "REQUEUED"}


@dataclass(frozen=True)
class Target:
    base: str                      # http://node:port
    auth_headers: dict[str, str]   # sent to the job on every request

    @property
    def netloc(self) -> str:
        return self.base.split("://", 1)[1]


@dataclass(frozen=True)
class ProxyPage:
    name: str   # starting | ended | forbidden | not_found | not_responding


def _headers(kind: str, token: str) -> dict[str, str]:
    return {"X-SD-Token": token} if kind == "tensorboard" else {"Authorization": f"token {token}"}


def forget(app: Any, ctx: SessionCtx, job_id: str) -> None:
    app.state.proxy_cache.pop((ctx.effective_account.id, job_id), None)


def resolve(ctx: SessionCtx, kind: str, job_id: str, app: Any) -> Target | ProxyPage:
    """Cached for CACHE_S seconds per (account, job). Only a ready session is
    cached, so a job that has just come up is found within a poll."""
    if kind not in KINDS or not JOB_ID.fullmatch(job_id):
        return ProxyPage("not_found")
    cache: dict[tuple[int, str], tuple[float, Target]] = app.state.__dict__.setdefault(
        "proxy_cache", {})
    key = (ctx.effective_account.id, job_id)
    hit = cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    try:
        info = app.state.agent.call("session.info", {"job_id": job_id}, session=ctx.raw_token)
    except AgentCallError as e:
        if e.status in (403, 404):
            return ProxyPage("forbidden")
        return ProxyPage("not_responding")
    if info.get("kind") != kind:
        return ProxyPage("not_found")
    state = info.get("state") or ""
    if state not in LIVE_STATES:
        return ProxyPage("ended")
    if state != "RUNNING" or not info.get("ready") or not (
            info.get("node") and info.get("port") and info.get("token")):
        return ProxyPage("starting")
    target = Target(f"http://{info['node']}:{info['port']}", _headers(kind, info["token"]))
    cache[key] = (time.monotonic(), target)
    _audit(ctx, kind, job_id, app)
    return target


def _audit(ctx: SessionCtx, kind: str, job_id: str, app: Any) -> None:
    """session_open, once per account and job per hour. An admin opening
    someone else's session is recorded with acting_admin_id."""
    now = app.state.clock()
    with app.state.sessionmaker() as db:
        actor = ctx.effective_account
        recent = db.scalar(select(AuditEvent.id).where(
            AuditEvent.action == "session_open", AuditEvent.target == job_id,
            AuditEvent.actor_id == ctx.account.id, AuditEvent.ts > now - AUDIT_EVERY).limit(1))
        if recent is not None:
            return
        job = db.get(Job, job_id)
        owner = db.get(Account, job.account_id) if job else None
        other = owner is not None and owner.id != actor.id
        record(db, actor_id=ctx.account.id, action="session_open", target=job_id,
               detail={"kind": kind, "owner": owner.username if owner else None},
               acting_admin_id=ctx.account.id if other else None)
        db.commit()
