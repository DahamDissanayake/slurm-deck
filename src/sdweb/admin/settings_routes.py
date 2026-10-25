"""GET/PUT /api/admin/settings: the few knobs an admin can change, validated
as a set (nothing is saved unless every value is good) and each change audited
with its old and new value."""

from __future__ import annotations

import re
from collections.abc import Callable
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


def _flag(v: Any, pmax: int | None) -> bool:
    if not isinstance(v, bool):
        raise ValueError("This must be on or off.")
    return v


def _whole(lo: int, hi: int) -> Callable[[Any, int | None], int]:
    def check(v: Any, pmax: int | None) -> int:
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise ValueError(f"Use a whole number from {lo} to {hi}.")
        return v
    return check


def _cap(v: Any, pmax: int | None) -> int:
    return _whole(1, max(pmax // 3600 if pmax else 24 * 30, 1))(v, pmax)   # <= the longest job


def _time_limit(v: Any, pmax: int | None) -> str:
    m = TIME.fullmatch(v) if isinstance(v, str) else None
    if not m:
        raise ValueError("Use HH:MM:SS, like 08:00:00.")
    secs = int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
    if secs < 60 or (pmax and secs > pmax):
        raise ValueError("The time limit must be between a minute and the partition's longest job.")
    return v


def _text(limit: int) -> Callable[[Any, int | None], str | None]:
    def check(v: Any, pmax: int | None) -> str | None:
        if not isinstance(v, str | None) or len(v or "") > limit:
            raise ValueError(f"Use at most {limit} characters.")
        return (v or "").strip() or None
    return check


# key: (default, validator)
SETTINGS: dict[str, tuple[Any, Callable[[Any, int | None], Any]]] = {
    "default_time_limit": ("08:00:00", _time_limit),
    "extension_cap_hours": (24, _cap),
    "submit_rate_per_hour": (20, _whole(0, 10_000)),   # 0 turns the limit off
    "mail_enabled": (True, _flag),
    "maintenance_banner": (None, _text(500)),
    "terminal_jobs_enabled": (True, _flag),
    "disk_alert_percent": (90, _whole(50, 99)),
    "cluster_location": (None, _text(100)),
}


def _partition_max(request: Request, ctx: SessionCtx) -> int | None:
    status = agent_call(request.app.state.agent, "cluster.status", {}, ctx.raw_token)
    return status.get("partition_max_s")


@router.get("/settings")
def read(ctx: Admin, request: Request, db: Db) -> dict:
    return {"settings": {k: setting(db, k, default) for k, (default, _) in SETTINGS.items()},
            "partition_max_s": _partition_max(request, ctx)}


@router.put("/settings")
def change(body: dict[str, Any], ctx: AdminWrite, request: Request, db: Db, now: Now) -> dict:
    pmax, clean, problems = _partition_max(request, ctx), {}, {}
    for key, value in body.items():
        if key not in SETTINGS:
            problems[key] = "That isn't a setting."
            continue
        try:
            clean[key] = SETTINGS[key][1](value, pmax)
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
