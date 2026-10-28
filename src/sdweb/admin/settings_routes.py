"""GET/PUT /api/admin/settings: validated as a set (all or nothing), each change audited."""

from __future__ import annotations

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from sdweb.accounts.service import agent_call
from sdweb.audit import record
from sdweb.deps import ApiError, Db, Now, SessionCtx, require_admin, require_csrf
from sdweb.jobs.service import setting
from sdweb.models import Setting

router = APIRouter()


def _admin_csrf(ctx: Annotated[SessionCtx, Depends(require_csrf)]) -> SessionCtx:
    return require_admin(ctx)


Admin = Annotated[SessionCtx, Depends(require_admin)]
AdminWrite = Annotated[SessionCtx, Depends(_admin_csrf)]
TIME = re.compile(r"(\d{1,3}):([0-5]\d):([0-5]\d)")

# key: (default, kind, low, high). kind: "flag", "whole" (low..high), "text" (up to
# high characters), "time" (HH:MM:SS up to the partition's longest job).
SETTINGS: dict[str, tuple[Any, str, int, int]] = {
    "default_time_limit": ("08:00:00", "time", 60, 0),
    "extension_cap_hours": (24, "whole", 1, 0),   # high: the partition's longest job, in hours
    "submit_rate_per_hour": (20, "whole", 0, 10_000),   # 0 turns the limit off
    "mail_enabled": (True, "flag", 0, 0),
    "maintenance_banner": (None, "text", 0, 500),
    "terminal_jobs_enabled": (True, "flag", 0, 0),
    "disk_alert_percent": (90, "whole", 50, 99),
    "cluster_location": (None, "text", 0, 100),
}


def _clean(key: str, v: Any, pmax: int | None) -> Any:
    _, kind, low, high = SETTINGS[key]
    if key == "extension_cap_hours":
        high = max(pmax // 3600 if pmax else 24 * 30, 1)   # never above the longest job
    if kind == "flag" and not isinstance(v, bool):
        raise ValueError("This must be on or off.")
    if kind == "whole" and (isinstance(v, bool) or not isinstance(v, int) or not low <= v <= high):
        raise ValueError(f"Use a whole number from {low} to {high}.")
    if kind == "text":
        if not isinstance(v, str | None) or len(v or "") > high:
            raise ValueError(f"Use at most {high} characters.")
        return (v or "").strip() or None
    if kind == "time":
        m = TIME.fullmatch(v) if isinstance(v, str) else None
        secs = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3]) if m else 0
        if not m or secs < low or (pmax and secs > pmax):
            raise ValueError("Use HH:MM:SS, from a minute to the partition's longest job.")
    return v


def _partition_max(request: Request, ctx: SessionCtx) -> int | None:
    status = agent_call(request.app.state.agent, "cluster.status", {}, ctx.raw_token)
    return status.get("partition_max_s")


@router.get("/settings")
def read(ctx: Admin, request: Request, db: Db) -> dict:
    return {"settings": {k: setting(db, k, spec[0]) for k, spec in SETTINGS.items()},
            "partition_max_s": _partition_max(request, ctx)}


@router.put("/settings")
def change(body: dict[str, Any], ctx: AdminWrite, request: Request, db: Db, now: Now) -> dict:
    pmax, clean, problems = _partition_max(request, ctx), {}, {}
    for key, value in body.items():
        try:
            if key not in SETTINGS:
                raise ValueError("That isn't a setting.")
            clean[key] = _clean(key, value, pmax)
        except ValueError as e:
            problems[key] = str(e)
    if problems:
        raise ApiError(422, "bad_setting", message=next(iter(problems.values())), problems=problems)
    for key, new in clean.items():
        old = setting(db, key, SETTINGS[key][0])
        if old == new:
            continue
        row = db.get(Setting, key)
        if row is None:
            row = Setting(key=key)
            db.add(row)
        row.value, row.updated_by_id, row.updated_at = new, ctx.account.id, now
        record(db, actor_id=ctx.account.id, action="settings.change", target=key,
               detail={"old": old, "new": new})
    db.commit()
    return read(ctx, request, db)
