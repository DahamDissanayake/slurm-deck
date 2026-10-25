"""/api/admin cluster control: QoS limits, node drain and resume, the pod grid
and resize, shared assets and service health. Each route hands the admin's
session to the matching deck-agent verb, which does the work and the audit."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from sdweb.accounts.service import agent_call
from sdweb.deps import SessionCtx, require_admin, require_csrf

router = APIRouter(prefix="/api/admin")


def _admin_csrf(ctx: Annotated[SessionCtx, Depends(require_csrf)]) -> SessionCtx:
    return require_admin(ctx)


Admin = Annotated[SessionCtx, Depends(require_admin)]
AdminWrite = Annotated[SessionCtx, Depends(_admin_csrf)]


def _read(verb: str) -> Callable[..., Any]:
    def handler(ctx: Admin, request: Request) -> Any:
        return agent_call(request.app.state.agent, verb, {}, ctx.raw_token)
    return handler


def _write(verb: str) -> Callable[..., Any]:
    def handler(body: dict[str, Any], ctx: AdminWrite, request: Request) -> Any:
        return agent_call(request.app.state.agent, verb, body, ctx.raw_token)
    return handler


for method, path, verb in [
    ("GET", "/qos", "admin.qos_list"), ("POST", "/qos", "admin.qos_set"),
    ("POST", "/node/jobs", "admin.node_jobs"), ("POST", "/node/drain", "admin.drain"),
    ("POST", "/node/resume", "admin.resume"),
    ("GET", "/pods", "admin.pods"), ("POST", "/pods/resize", "admin.pods_resize"),
    ("POST", "/shared/publish", "admin.publish_shared"),
    ("POST", "/shared/unpublish", "admin.unpublish_shared"),
    ("GET", "/service-status", "admin.service_status"),
]:
    router.add_api_route(path, (_read if method == "GET" else _write)(verb), methods=[method])
