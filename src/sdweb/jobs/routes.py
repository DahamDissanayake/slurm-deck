"""/api/jobs: defaults, preview, submit, list, history, detail, logs, cancel,
extend and rerun. Every call goes to deck-agent with the caller's session, so
deck-agent decides whose jobs these are; a job row is stored only once
deck-agent has a job id for it."""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select

from sdcore.diagnose import explain_failure
from sdcore.launchspec import default_spec
from sdcore.sbatch import parse_smoke
from sdcore.validate import validate_against_qos, validate_sbatch
from sdweb.accounts.service import agent_call
from sdweb.agent import AgentCallError
from sdweb.audit import record
from sdweb.deps import (
    ApiError,
    Db,
    Mailer,
    Now,
    SessionCtx,
    Settings,
    get_mailer,
    require_csrf,
    require_user,
)
from sdweb.jobs.service import build_script, node_stats, setting, spec_from
from sdweb.models import Account, Job

router = APIRouter(prefix="/api/jobs")

User = Annotated[SessionCtx, Depends(require_user)]
UserWrite = Annotated[SessionCtx, Depends(require_csrf)]
FAILED = frozenset({"FAILED", "OUT_OF_MEMORY", "TIMEOUT", "CANCELLED", "NODE_FAIL"})
TAIL = 64 * 1024


class LaunchIn(BaseModel):
    model_config = {"extra": "allow"}
    intent: str = "batch"


class ExtendIn(BaseModel):
    hours: int


def _call(request: Request, ctx: SessionCtx, verb: str, payload: dict[str, Any] | None = None
          ) -> Any:
    return agent_call(request.app.state.agent, verb, payload or {}, ctx.raw_token)


def _qos(request: Request, ctx: SessionCtx) -> dict[str, Any]:
    return dict(_call(request, ctx, "qos.limits"))


def _check(ls: Any, script: str, qos: dict[str, Any], ctx: SessionCtx,
           settings: Settings) -> list[str]:
    max_s = qos.get("max_wall_s")
    ok, why = validate_against_qos(ls.gpu_shards, ls.time_limit, qos.get("max_pods_per_user"),
                                   max_s // 3600 if max_s else None)
    problems = [] if ok else [why]
    account = ctx.effective_account
    return problems + validate_sbatch(script, account.username, nfs_root=settings.nfs_root,
                                      registered_email=account.email)


@router.get("/defaults")
def defaults(ctx: User, request: Request, db: Db, intent: str = "batch") -> dict:
    stats = node_stats(_call(request, ctx, "cluster.status"))
    ls = default_spec(intent, stats, setting(db, "default_time_limit", "08:00:00"))
    return {"spec": asdict(ls), "qos": _qos(request, ctx),
            "terminal_enabled": bool(setting(db, "terminal_jobs_enabled", True))}


@router.post("/preview")
def preview(body: LaunchIn, ctx: UserWrite, request: Request, settings: Settings,
            now: Now) -> dict:
    ls = spec_from(body.model_dump())
    try:
        script, _ = build_script(ctx.effective_account, ls, settings, now)
    except ValueError as e:
        raise ApiError(422, "bad_spec", message=str(e)) from None
    return {"script": script, "problems": _check(ls, script, _qos(request, ctx), ctx, settings),
            "warnings": []}


@router.post("", status_code=201)
def submit(body: LaunchIn, ctx: UserWrite, request: Request, db: Db, settings: Settings,
           now: Now) -> dict:
    account = ctx.effective_account
    limit = int(setting(db, "submit_rate_per_hour", 20))
    recent = db.scalar(select(func.count()).select_from(Job).where(
        Job.account_id == account.id, Job.submitted_at > now - timedelta(hours=1))) or 0
    if recent >= limit:
        raise ApiError(429, "rate_limited", message=f"You've submitted {recent} jobs in the "
                       f"last hour; the limit is {limit}.")
    ls = spec_from(body.model_dump())
    try:
        script, folder_name = build_script(account, ls, settings, now)
    except ValueError as e:
        raise ApiError(422, "bad_spec", message=str(e)) from None
    problems = _check(ls, script, _qos(request, ctx), ctx, settings)
    if problems:
        raise ApiError(422, "bad_spec", message="; ".join(problems), problems=problems)
    out = _call(request, ctx, "job.submit", {"folder_name": folder_name, "script": script})
    db.add(Job(job_id=out["job_id"], account_id=account.id, kind=ls.intent,
               name=folder_name, folder=out["folder"], spec=asdict(ls), script=script,
               submitted_at=now))
    record(db, actor_id=ctx.account.id, acting_admin_id=ctx.account.id if ctx.acting_as else None,
           action="job.submit", target=out["job_id"])
    db.commit()
    return {"job_id": out["job_id"]}


def _rows(db: Db, account: Account) -> dict[str, Job]:
    return {j.job_id: j for j in db.scalars(select(Job).where(Job.account_id == account.id))}


@router.get("")
def list_jobs(ctx: User, request: Request, db: Db) -> dict:
    rows = _rows(db, ctx.effective_account)
    jobs = _call(request, ctx, "job.list")["jobs"]
    for j in jobs:
        row = rows.get(j["job_id"])
        j["kind"], j["folder"] = (row.kind, row.folder) if row else ("batch", None)
    return {"jobs": jobs}


@router.get("/history")
def history(ctx: User, request: Request, days: int = 30, state: str = "") -> dict:
    jobs = _call(request, ctx, "job.history", {"days": days})["jobs"]
    return {"jobs": [j for j in jobs if not state or j["state"] == state]}


def _read(request: Request, ctx: SessionCtx, job_id: str, stream: str) -> bytes:
    try:
        _, body = request.app.state.agent.stream_with_headers(
            "joblog.read", {"job_id": job_id, "stream": stream}, session=ctx.raw_token)
        return b"".join(body)
    except AgentCallError:
        return b""


@router.get("/{job_id}")
def detail(job_id: str, ctx: User, request: Request, db: Db) -> dict:
    info = _call(request, ctx, "job.show", {"job_id": job_id})
    row = db.get(Job, job_id)
    spec = row.spec if row else {}
    out: dict[str, Any] = {**info, "kind": row.kind if row else "batch",
                           "folder": row.folder if row else None, "explanation": None,
                           "smoke": None}
    if info.get("state") in FAILED:
        err = _read(request, ctx, job_id, "err")[-TAIL:].decode(errors="replace")
        out["explanation"] = explain_failure(err, mem_gb=int(spec.get("mem_gb", 0)),
                                             pods=int(spec.get("gpu_shards", 1)))
    if row is not None and row.kind == "smoke":
        out["smoke"] = parse_smoke(_read(request, ctx, job_id, "out").decode(errors="replace"))
    return out


@router.get("/{job_id}/log")
def log(job_id: str, ctx: User, request: Request, stream: str = "out",
        offset: int = 0) -> StreamingResponse:
    try:
        headers, body = request.app.state.agent.stream_with_headers(
            "joblog.read", {"job_id": job_id, "stream": stream, "offset": offset},
            session=ctx.raw_token)
    except AgentCallError as e:
        raise ApiError(e.status if 400 <= e.status < 500 else 502, e.code,
                       message=e.message) from None
    return StreamingResponse(body, media_type="text/plain; charset=utf-8",
                             headers={"X-SD-Size": headers.get("x-sd-size", "")})


@router.post("/{job_id}/cancel")
def cancel(job_id: str, ctx: UserWrite, request: Request, db: Db) -> dict:
    _call(request, ctx, "job.cancel", {"job_id": job_id})
    record(db, actor_id=ctx.account.id, action="job.cancel", target=job_id)
    db.commit()
    return {}


@router.post("/{job_id}/extend")
def extend(job_id: str, body: ExtendIn, ctx: UserWrite, request: Request, db: Db,
           mailer: Annotated[Mailer, Depends(get_mailer)]) -> dict:
    out = _call(request, ctx, "job.extend", {"job_id": job_id, "hours": body.hours})
    info = _call(request, ctx, "job.show", {"job_id": job_id})
    owner = db.scalar(select(Account).where(Account.username == info.get("owner")))
    row = db.get(Job, job_id)
    if owner is not None:
        h, rest = divmod(int(out["new_limit_s"]), 3600)
        mailer(db, to=owner.email, kind="job_extended",
               context={"job_id": job_id, "name": row.name if row else job_id,
                        "hours": str(body.hours), "new_limit": f"{h}:{rest // 60:02d}:00"})
    record(db, actor_id=ctx.account.id, action="job.extend", target=job_id,
           detail={"hours": body.hours})
    db.commit()
    return out


@router.get("/{job_id}/rerun")
def rerun(job_id: str, ctx: User, db: Db) -> dict:
    row = db.get(Job, job_id)
    if row is None or row.account_id != ctx.effective_account.id:
        raise ApiError(404, "not_found", message="There is no such job.")
    return {"spec": asdict(spec_from(row.spec))}
