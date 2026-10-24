"""/api/notify: the signed-in account's "email me when N pods are free"."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from sdweb.accounts.service import agent_call
from sdweb.deps import ApiError, Db, Now, SessionCtx, require_csrf, require_user
from sdweb.models import NotifySubscription

router = APIRouter(prefix="/api/notify")


class NotifyIn(BaseModel):
    wanted_pods: int


@router.get("")
def get(ctx: Annotated[SessionCtx, Depends(require_user)], db: Db) -> dict:
    sub = db.get(NotifySubscription, ctx.effective_account.id)
    return {"wanted_pods": sub.wanted_pods if sub else None}


@router.put("")
def put(body: NotifyIn, ctx: Annotated[SessionCtx, Depends(require_csrf)], request: Request,
        db: Db, now: Now) -> dict:
    status = agent_call(request.app.state.agent, "cluster.status", {}, ctx.raw_token)
    total = int(status.get("pods_total") or 0)
    if not 1 <= body.wanted_pods <= max(total, 1):
        raise ApiError(422, "bad_pods", message=f"Choose between 1 and {max(total, 1)} pods.")
    sub = db.get(NotifySubscription, ctx.effective_account.id)
    if sub is None:
        db.add(NotifySubscription(account_id=ctx.effective_account.id,
                                  wanted_pods=body.wanted_pods, created_at=now))
    else:
        sub.wanted_pods = body.wanted_pods
    db.commit()
    return {"wanted_pods": body.wanted_pods}


@router.delete("")
def delete(ctx: Annotated[SessionCtx, Depends(require_csrf)], db: Db) -> dict:
    sub = db.get(NotifySubscription, ctx.effective_account.id)
    if sub is not None:
        db.delete(sub)
        db.commit()
    return {}
