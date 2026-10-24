"""The application allow-list: whole email domains and single addresses.
Matching ignores case; a domain matches only exactly (no subdomains). An empty
list switches the Apply form off."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from sdweb.audit import record
from sdweb.deps import ApiError, Db, Now, SessionCtx, require_admin, require_csrf
from sdweb.models import AllowEntry
from sdweb.security import normalize_email, valid_email

router = APIRouter()

_DOMAIN = re.compile(r"(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}")


def matches(entries: Iterable[AllowEntry], email: str) -> bool:
    email = normalize_email(email)
    domain = email.rpartition("@")[2]
    for e in entries:
        value = e.value.lower()
        if (e.kind == "domain" and domain == value) or (e.kind == "address" and email == value):
            return True
    return False


def apply_open(db: Db) -> bool:
    return db.scalar(select(AllowEntry.id).limit(1)) is not None


class AllowIn(BaseModel):
    value: str


def _admin_write(ctx: Annotated[SessionCtx, Depends(require_csrf)]) -> SessionCtx:
    return require_admin(ctx)


@router.get("/api/admin/allowlist")
def list_entries(ctx: Annotated[SessionCtx, Depends(require_admin)], db: Db) -> dict:
    rows = db.scalars(select(AllowEntry).order_by(AllowEntry.kind, AllowEntry.value))
    return {"entries": [{"id": e.id, "kind": e.kind, "value": e.value} for e in rows]}


@router.post("/api/admin/allowlist", status_code=201)
def add_entry(body: AllowIn, ctx: Annotated[SessionCtx, Depends(_admin_write)], db: Db,
              now: Now) -> dict:
    value = normalize_email(body.value).lstrip("@")
    if "@" in value:
        kind, ok = "address", valid_email(value)
    else:
        kind, ok = "domain", _DOMAIN.fullmatch(value) is not None
    if not ok:
        raise ApiError(422, "bad_value", message="Enter a domain (example.org) or an email.")
    if db.scalar(select(AllowEntry.id).where(AllowEntry.value == value)) is not None:
        raise ApiError(409, "exists", message="That is already on the list.")
    entry = AllowEntry(kind=kind, value=value, created_by_id=ctx.account.id, created_at=now)
    db.add(entry)
    record(db, actor_id=ctx.account.id, action="allowlist.add", target=value)
    db.commit()
    return {"id": entry.id, "kind": kind, "value": value}


@router.delete("/api/admin/allowlist/{entry_id}")
def remove_entry(entry_id: int, ctx: Annotated[SessionCtx, Depends(_admin_write)],
                 db: Db) -> dict:
    entry = db.get(AllowEntry, entry_id)
    if entry is None:
        raise ApiError(404, "not_found")
    record(db, actor_id=ctx.account.id, action="allowlist.remove", target=entry.value)
    db.delete(entry)
    db.commit()
    return {}
