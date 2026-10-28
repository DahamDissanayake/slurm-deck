"""/api/cluster: node status and the queue, from deck-agent (which hides other
users' job names)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from sdweb.accounts.service import agent_call
from sdweb.deps import SessionCtx, require_user

router = APIRouter(prefix="/api/cluster")

User = Annotated[SessionCtx, Depends(require_user)]


@router.get("/status")
def status(ctx: User, request: Request) -> Any:
    return agent_call(request.app.state.agent, "cluster.status", {}, ctx.raw_token)


@router.get("/queue")
def queue(ctx: User, request: Request) -> Any:
    return agent_call(request.app.state.agent, "cluster.queue", {}, ctx.raw_token)
