"""/api/templates: saved launch settings, private to each account; names are
unique per account."""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from sdweb.deps import ApiError, Db, Now, SessionCtx, require_csrf, require_user
from sdweb.jobs.service import spec_from
from sdweb.models import Template

router = APIRouter(prefix="/api/templates")

# Built-in presets come first and can't be changed (none ship yet).
PRESETS: list[dict[str, Any]] = []


class TemplateIn(BaseModel):
    name: str
    spec: dict[str, Any]


@router.get("")
def list_templates(ctx: Annotated[SessionCtx, Depends(require_user)], db: Db) -> dict:
    rows = db.scalars(select(Template).where(Template.account_id == ctx.effective_account.id)
                      .order_by(Template.name))
    return {"presets": PRESETS,
            "templates": [{"id": t.id, "name": t.name, "spec": t.spec} for t in rows]}


@router.post("", status_code=201)
def save(body: TemplateIn, ctx: Annotated[SessionCtx, Depends(require_csrf)], db: Db,
         now: Now) -> dict:
    name = body.name.strip()
    if not 1 <= len(name) <= 80:
        raise ApiError(422, "bad_name", message="Give the template a name.")
    account = ctx.effective_account
    if db.scalar(select(Template.id).where(Template.account_id == account.id,
                                           Template.name == name)) is not None:
        raise ApiError(409, "exists", message="You already have a template with that name.")
    try:
        spec = asdict(spec_from(body.spec))
    except TypeError:
        raise ApiError(422, "bad_spec", message="That isn't a launch spec.") from None
    t = Template(account_id=account.id, name=name, spec=spec, created_at=now)
    db.add(t)
    db.commit()
    return {"id": t.id, "name": name, "spec": spec}


@router.delete("/{template_id}")
def delete(template_id: int, ctx: Annotated[SessionCtx, Depends(require_csrf)], db: Db) -> dict:
    t = db.get(Template, template_id)
    if t is None or t.account_id != ctx.effective_account.id:
        raise ApiError(404, "not_found")
    db.delete(t)
    db.commit()
    return {}
