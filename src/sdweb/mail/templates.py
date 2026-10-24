"""Mail templates. Each kind is a subject function and a body function over its
context; render() escapes every context value for the HTML part, so a body
function can't forget to. No template takes a password: mail carries one-time
links only."""

from __future__ import annotations

import html
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sdweb.config import WebSettings


@dataclass(frozen=True)
class Button:
    label: str
    url: str


Body = list[str | Button]
SubjectFn = Callable[[Mapping[str, Any]], str]
BodyFn = Callable[[Mapping[str, Any]], Body]

_REGISTRY: dict[str, tuple[SubjectFn, BodyFn]] = {}


def register(kind: str, subject_fn: SubjectFn, body_fn: BodyFn) -> None:
    if kind in _REGISTRY:
        raise ValueError(f"mail kind {kind} is already registered")
    _REGISTRY[kind] = (subject_fn, body_fn)


def _plain(value: Any, tz: ZoneInfo) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(tz).strftime("%Y-%m-%d %H:%M %Z")
    if isinstance(value, Mapping):
        return {k: _plain(v, tz) for k, v in value.items()}
    return "" if value is None else str(value)


def _escaped(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {k: _escaped(v) for k, v in value.items()}
    return html.escape(value)


def render(kind: str, context: Mapping[str, Any], settings: WebSettings) -> tuple[str, str, str]:
    """(subject, html, text) for one mail."""
    if any("password" in key.lower() for key in context):
        raise ValueError("mail never carries a password; send a set/reset link instead")
    subject_fn, body_fn = _REGISTRY[kind]
    tz = ZoneInfo(settings.cluster_tz)
    plain = {"cluster": settings.cluster_name, "site": f"https://{settings.public_hostname}",
             "set_hours": str(settings.set_link_hours),
             "reset_hours": str(settings.reset_link_hours),
             **{k: _plain(v, tz) for k, v in context.items()}}
    safe = {k: _escaped(v) for k, v in plain.items()}

    subject = " ".join(subject_fn(plain).split())   # one line: no header injection
    text = "\n\n".join(p if isinstance(p, str) else f"{p.label}: {p.url}"
                       for p in body_fn(plain))
    parts = [f"<p>{p}</p>" if isinstance(p, str)
             else f'<p><a href="{p.url}" style="font-weight:600">{p.label}</a></p>'
             for p in body_fn(safe)]
    page = ("<!doctype html><html><body style=\"font-family:sans-serif;line-height:1.5\">"
            + "".join(parts)
            + f"<p style=\"color:#666\">{html.escape(settings.cluster_name)}</p></body></html>")
    return subject, page, text + f"\n\n{settings.cluster_name}\n"


register("set_password",
         lambda c: f"Set your password for {c['cluster']}",
         lambda c: [f"An account on {c['cluster']} has been created for you.",
                    f"Choose your password with this link. It works once, within "
                    f"{c['set_hours']} hours.",
                    Button("Set your password", c["link"])])

register("reset_password",
         lambda c: f"Reset your {c['cluster']} password",
         lambda c: ["Someone asked to reset the password for your account.",
                    f"This link works once, within {c['reset_hours']} hour(s). If it wasn't "
                    "you, ignore this email: your password stays the same.",
                    Button("Reset your password", c["link"])])

register("lockout",
         lambda c: f"Your {c['cluster']} account is locked for now",
         lambda c: ["There were too many failed sign-ins to your account, so it is locked.",
                    f"You can sign in again after {c['until']}. If that wasn't you, reset "
                    "your password from the sign-in page.",
                    Button("Go to sign-in", c["site"])])

_APPLICATION_FIELDS = (("full_name", "Name"), ("email", "Email"), ("role_title", "Role"),
                       ("organisation", "Organisation"), ("contact_number", "Contact number"),
                       ("reason", "Reason"))

register("application_received_admin",
         lambda c: f"New access request for {c['cluster']}",
         lambda c: ["Someone has applied for an account:",
                    *[f"{label}: {c['application'][key]}" for key, label in _APPLICATION_FIELDS
                      if c["application"].get(key)],
                    Button("Review requests", f"{c['site']}/admin/requests")])

register("application_approved",
         lambda c: f"Your {c['cluster']} access is approved",
         lambda c: [f"Your application for {c['cluster']} was approved.",
                    f"Choose your password with this link. It works once, within "
                    f"{c['set_hours']} hours.",
                    Button("Set your password", c["link"])])

register("application_rejected",
         lambda c: f"Your {c['cluster']} application",
         lambda c: ["Thank you for applying. An admin reviewed your application and "
                    "couldn't approve it this time.",
                    *([f"Note from the admin: {c['note']}"] if c.get("note") else [])])

register("account_created_admin_notice",
         lambda c: f"New account on {c['cluster']}: {c['username']}",
         lambda c: [f"{c['created_by']} created the account {c['username']}."])
