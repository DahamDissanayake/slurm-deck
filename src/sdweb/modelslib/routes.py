"""/api/models: the model library and HuggingFace downloads as Slurm jobs.

A download is a CPU job (sdcore.hfdownload). A HuggingFace token, when the
repository needs one, is sent for that one download only: deck-agent writes it
as a 0600 file the job reads and deletes. The web app never stores it, and it
is never written to the audit trail or to the job script."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select

from sdcore.hfdownload import (
    REVISION,
    explain_hf_failure,
    parse_hf_result,
    render_hf_download,
    valid_repo_id,
)
from sdcore.launchspec import LaunchSpec
from sdcore.sbatch import job_folder_name
from sdcore.validate import user_job_root, user_upload_root
from sdweb.accounts.service import agent_call
from sdweb.agent import AgentCallError
from sdweb.audit import record
from sdweb.deps import ApiError, Db, Now, SessionCtx, Settings, require_csrf, require_user
from sdweb.models import Job

router = APIRouter(prefix="/api/models")
User = Annotated[SessionCtx, Depends(require_user)]
UserWrite = Annotated[SessionCtx, Depends(require_csrf)]
TOKEN = re.compile(r"[!-~]{1,512}")
RECENT = 10


class DownloadIn(BaseModel):
    repo_id: str
    revision: str | None = None
    token: str | None = None


def _call(request: Request, ctx: SessionCtx, verb: str, payload: dict[str, Any]) -> Any:
    return agent_call(request.app.state.agent, verb, payload, ctx.raw_token)


def _entries(request: Request, ctx: SessionCtx, folder: str) -> list[dict[str, Any]]:
    """What is in a models folder, with the size of each (none when it can't be read)."""
    try:
        listing = _call(request, ctx, "fs.list", {"path": folder})["entries"]
    except ApiError:
        return []   # the folder doesn't exist yet
    out = []
    for e in listing:
        size = e.get("size")
        if e.get("type") == "dir":
            try:
                size = _call(request, ctx, "fs.du", {"path": f"{folder}/{e['name']}"})["bytes"]
            except ApiError:
                size = None
        out.append({"name": e["name"], "type": e["type"], "bytes": size})
    return out


@router.get("")
def library(ctx: User, request: Request, settings: Settings) -> dict:
    nfs, user = settings.nfs_root.rstrip("/"), ctx.effective_account.username
    return {"shared": _entries(request, ctx, f"{nfs}/models"),
            "mine": _entries(request, ctx, f"{user_upload_root(nfs, user)}/models")}


@router.post("/download", status_code=201)
def download(body: DownloadIn, ctx: UserWrite, request: Request, db: Db, settings: Settings,
             now: Now) -> dict:
    repo_id, revision = body.repo_id.strip(), (body.revision or "").strip() or None
    token = (body.token or "").strip() or None
    if not valid_repo_id(repo_id):
        raise ApiError(422, "bad_repo", message="Use the form owner/name, "
                       "like meta-llama/Llama-3.1-8B.")
    if revision and not REVISION.fullmatch(revision):
        raise ApiError(422, "bad_revision", message="That isn't a branch, tag or commit name.")
    if token and not TOKEN.fullmatch(token):
        raise ApiError(422, "bad_token", message="That doesn't look like a HuggingFace token.")
    account, nfs = ctx.effective_account, settings.nfs_root.rstrip("/")
    name = repo_id.replace("/", "--")
    folder_name = job_folder_name(f"hf-{name}", now)
    script = render_hf_download(
        account.username, f"{user_job_root(nfs, account.username)}/{folder_name}",
        account.home or f"/home/{account.username}", repo_id=repo_id, revision=revision,
        dest=f"{user_upload_root(nfs, account.username)}/models/{name}",
        partition=settings.partition, nfs_root=nfs)
    payload: dict[str, Any] = {"folder_name": folder_name, "script": script}
    if token:
        payload["secret_file"] = {"name": ".hf_token", "content": token}
    out = _call(request, ctx, "job.submit", payload)
    db.add(Job(job_id=out["job_id"], account_id=account.id, kind="model_download",
               name=folder_name, folder=out["folder"],
               spec=asdict(LaunchSpec(intent="model_download", model_path=repo_id)),
               script=script, submitted_at=now))
    record(db, actor_id=ctx.account.id, action="model.download", target=repo_id,
           detail={"job_id": out["job_id"], "with_token": token is not None})
    db.commit()
    return {"job_id": str(out["job_id"])}


def _log(request: Request, ctx: SessionCtx, job_id: str) -> str:
    try:
        _, body = request.app.state.agent.stream_with_headers(
            "joblog.read", {"job_id": job_id, "stream": "out"}, session=ctx.raw_token)
        return b"".join(body).decode(errors="replace")
    except AgentCallError:
        return ""


@router.get("/downloads")
def downloads(ctx: User, request: Request, db: Db) -> dict:
    """My recent downloads: running, done (with size) or failed (with the reason)."""
    rows = db.scalars(select(Job).where(
        Job.account_id == ctx.effective_account.id, Job.kind == "model_download")
        .order_by(Job.submitted_at.desc()).limit(RECENT))
    live = {j["job_id"] for j in _call(request, ctx, "job.list", {}).get("jobs", [])}
    out = []
    for row in rows:
        state, size, message = parse_hf_result(_log(request, ctx, row.job_id))
        if state == "unknown":
            state = "running" if row.job_id in live else "failed"
            message = "" if state == "running" else explain_hf_failure("")
        out.append({"job_id": row.job_id, "repo_id": row.spec.get("model_path", ""),
                    "state": state, "bytes": size, "message": message})
    return {"downloads": out}
