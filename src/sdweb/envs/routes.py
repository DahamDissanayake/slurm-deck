"""/api/envs: prebuilt and personal environments and container images.

Builds are CPU jobs (sdcore.envspec.render_env_build) submitted like any
other job. A user build's result is read lazily: on GET, each finished build
gets its output read once (with the requesting user's session), its result
stored in env_builds, and the `.sd-env-ok` marker written when it passed. A
prebuilt install runs as sd-ops and marks the environment ready itself.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from sdcore.envspec import list_specs, parse_env_result, render_env_build
from sdcore.launchspec import LaunchSpec
from sdcore.sbatch import job_folder_name
from sdcore.validate import user_job_root, user_upload_root
from sdweb.accounts.service import agent_call
from sdweb.agent import AgentCallError
from sdweb.audit import record
from sdweb.deps import (
    ApiError,
    Db,
    Now,
    SessionCtx,
    Settings,
    require_admin,
    require_csrf,
    require_user,
)
from sdweb.models import EnvBuild, Job

router = APIRouter()
User = Annotated[SessionCtx, Depends(require_user)]
UserWrite = Annotated[SessionCtx, Depends(require_csrf)]
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
OPS_JOBS = "jobs-ops"   # deckagent.verbs.jobs.OPS_JOBS
LIVE = {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "SUSPENDED", "REQUEUED"}


def require_admin_csrf(ctx: Annotated[SessionCtx, Depends(require_csrf)]) -> SessionCtx:
    return require_admin(ctx)


class BuildIn(BaseModel):
    kind: str = "conda"
    name: str
    packages: str = ""
    requirements_path: str | None = None


class InstallIn(BaseModel):
    spec: str


def _call(request: Request, ctx: SessionCtx, verb: str, payload: dict[str, Any]) -> Any:
    return agent_call(request.app.state.agent, verb, payload, ctx.raw_token)


def _submit(request: Request, ctx: SessionCtx, db: Db, now: datetime, *, kind: str,
            name: str, path: str, folder_name: str, script: str, as_ops: bool = False) -> str:
    payload: dict[str, Any] = {"folder_name": folder_name, "script": script}
    if as_ops:
        payload["as_ops"] = True
    out = _call(request, ctx, "job.submit", payload)
    account = ctx.effective_account
    db.add(Job(job_id=out["job_id"], account_id=account.id, kind=f"env_{kind}",
               name=folder_name, folder=out["folder"],
               spec=asdict(LaunchSpec(intent=f"env_{kind}")), script=script, submitted_at=now))
    db.add(EnvBuild(job_id=out["job_id"], account_id=account.id, kind=kind, name=name,
                    path=path, created_at=now))
    record(db, actor_id=ctx.account.id, action=f"env.{kind}", target=path,
           detail={"job_id": out["job_id"]})
    db.commit()
    return str(out["job_id"])


def _log(request: Request, ctx: SessionCtx, job_id: str) -> str:
    try:
        _, body = request.app.state.agent.stream_with_headers(
            "joblog.read", {"job_id": job_id, "stream": "out"}, session=ctx.raw_token)
        return b"".join(body).decode(errors="replace")
    except AgentCallError:
        return ""


def _finalize(request: Request, ctx: SessionCtx, db: Db, rows: list[EnvBuild],
              now: datetime) -> None:
    pending = [b for b in rows if b.finished_at is None]
    if not pending:
        return
    live = {j["job_id"] for j in _call(request, ctx, "job.list", {}).get("jobs", [])}
    for b in pending:
        if b.job_id in live:
            continue
        if b.kind == "install":   # sd-ops's job: done when Slurm says so
            try:
                state = _call(request, ctx, "job.show", {"job_id": b.job_id}).get("state")
            except ApiError:
                state = ""
            if state in LIVE:
                continue
        else:
            b.ok, b.missing = parse_env_result(_log(request, ctx, b.job_id))
            if b.ok:
                _call(request, ctx, "fs.write", {"path": f"{b.path}/.sd-env-ok", "text": ""})
        b.finished_at = now
    db.commit()


def _state(b: EnvBuild) -> str:
    if b.finished_at is None:
        return "building"
    return "ended" if b.ok is None else "ok" if b.ok else "failed"


@router.get("/api/envs")
def list_envs(ctx: User, request: Request, db: Db, now: Now) -> dict:
    rows = list(db.scalars(select(EnvBuild).where(
        EnvBuild.account_id == ctx.effective_account.id).order_by(EnvBuild.created_at)))
    _finalize(request, ctx, db, rows, now)
    out = dict(_call(request, ctx, "env.list", {}))
    latest = {b.path: b for b in rows if b.finished_at is not None}
    for group in ("prebuilt", "mine"):
        for e in out.get(group, []):
            b = latest.get(e["path"])
            e["ready"] = bool(e["ready"] or (b is not None and b.ok))
            e["missing"] = list(b.missing) if b is not None and not e["ready"] else []
    out["builds"] = [{"job_id": b.job_id, "kind": b.kind, "name": b.name, "path": b.path,
                      "state": _state(b), "missing": list(b.missing)} for b in rows]
    return out


@router.post("/api/envs/build", status_code=201)
def build(body: BuildIn, ctx: UserWrite, request: Request, db: Db, settings: Settings,
          now: Now) -> dict:
    if not NAME_RE.fullmatch(body.name) or body.kind not in ("conda", "venv"):
        raise ApiError(422, "bad_input", message="Use letters, digits, '.', '_' or '-'.")
    account = ctx.effective_account
    user, nfs = account.username, settings.nfs_root
    dest = f"{user_upload_root(nfs, user)}/envs/{body.name}"
    folder_name = job_folder_name(f"env-{body.name}", now)
    try:
        shlex.split(body.packages)
    except ValueError:
        raise ApiError(422, "bad_input", message="The package list has an unclosed quote.") \
            from None
    script = render_env_build(user, f"{user_job_root(nfs, user)}/{folder_name}",
                              account.home or f"/home/{user}", kind=body.kind, name=body.name,
                              dest=dest, packages=body.packages,
                              requirements_path=body.requirements_path or None, spec_path=None,
                              partition=settings.partition, nfs_root=nfs)
    job_id = _submit(request, ctx, db, now, kind="build", name=body.name, path=dest,
                     folder_name=folder_name, script=script)
    return {"job_id": job_id}


@router.delete("/api/envs")
def delete_env(path: str, ctx: UserWrite, request: Request, shared: bool = False) -> dict:
    if shared and (ctx.account.role != "admin" or ctx.acting_as is not None):
        raise ApiError(403, "not_allowed", message="Only admins can delete shared environments.")
    return dict(_call(request, ctx, "env.delete", {"path": path, "as_admin": shared}))


@router.post("/api/admin/envs/install", status_code=201)
def install(body: InstallIn, ctx: Annotated[SessionCtx, Depends(require_admin_csrf)],
            request: Request, db: Db, settings: Settings, now: Now) -> dict:
    """Install a prebuilt environment into the shared area, as sd-ops. The
    spec is read from the copy shipped with the app; the job uses the
    cluster's copy at <SD_NFS_ROOT>/envs/.specs/<name>.yml."""
    spec = next((s for s in list_specs(settings.env_spec_dir) if s.name == body.spec), None)
    if spec is None:
        raise ApiError(404, "not_found", message="There is no such prebuilt environment.")
    nfs, admin = settings.nfs_root.rstrip("/"), ctx.account.username
    dest = f"{nfs}/envs/{spec.name}"
    folder_name = job_folder_name(f"install-{spec.name}", now)
    root = user_job_root(nfs, admin, OPS_JOBS)
    script = render_env_build(admin, f"{root}/{folder_name}", root, kind="conda",
                              name=spec.name, dest=dest, packages="", requirements_path=None,
                              spec_path=f"{nfs}/envs/.specs/{spec.name}.yml",
                              partition=settings.partition, nfs_root=nfs,
                              spec_text=open(spec.path, encoding="utf-8").read())
    script += (f'grep -qx SD_ENV_OK "slurm-$SLURM_JOB_ID.out" && '
               f"touch {shlex.quote(dest + '/.sd-env-ok')}\n")
    job_id = _submit(request, ctx, db, now, kind="install", name=spec.name, path=dest,
                     folder_name=folder_name, script=script, as_ops=True)
    return {"job_id": job_id}
