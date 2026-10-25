"""/api/usage and the admin reports: deck-agent does the work, as the right account."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from sdweb.accounts.service import agent_call
from sdweb.deps import SessionCtx, require_admin, require_user

router = APIRouter()
User = Annotated[SessionCtx, Depends(require_user)]
Admin = Annotated[SessionCtx, Depends(require_admin)]


@router.get("/api/usage")
def personal(ctx: User, request: Request, days: int = 30) -> Any:
    return agent_call(request.app.state.agent, "usage.personal", {"days": days}, ctx.raw_token)


@router.get("/api/admin/usage")
def cluster(ctx: Admin, request: Request, days: int = 30) -> Any:
    return agent_call(request.app.state.agent, "usage.cluster", {"days": days}, ctx.raw_token)


@router.get("/api/admin/disk-usage")
def disk_usage(ctx: Admin, request: Request) -> Any:
    return agent_call(request.app.state.agent, "admin.disk_usage", {}, ctx.raw_token)
