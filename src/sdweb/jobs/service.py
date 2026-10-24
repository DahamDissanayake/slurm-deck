"""Turning a LaunchSpec into a job script, and the checks around submitting."""

from __future__ import annotations

from dataclasses import fields
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from sdcore.launchspec import LaunchSpec, to_job_spec
from sdcore.sbatch import (
    EnvChoice,
    EnvKind,
    job_folder_name,
    render_batch,
    render_smoke,
    run_command_for,
)
from sdcore.slurmparse import NodeStats
from sdcore.validate import clean_job_name, user_job_root
from sdweb.config import WebSettings
from sdweb.mail import templates
from sdweb.models import Account, Setting

INTENTS = ("batch", "smoke")
SPEC_FIELDS = {f.name for f in fields(LaunchSpec)}


def setting(db: Session, key: str, default: Any) -> Any:
    value = db.scalar(select(Setting.value).where(Setting.key == key))
    return default if value is None else value


def spec_from(data: dict[str, Any]) -> LaunchSpec:
    """A LaunchSpec from client data, ignoring unknown keys."""
    return LaunchSpec(**{k: v for k, v in data.items() if k in SPEC_FIELDS})


def node_stats(status: dict[str, Any] | None) -> NodeStats | None:
    node = (status or {}).get("node")
    if not node:
        return None
    return NodeStats(**{k: v for k, v in node.items()
                        if k in NodeStats.__dataclass_fields__})


def _env(ls: LaunchSpec) -> EnvChoice:
    path = {"prebuilt": ls.conda_env, "conda": ls.conda_env, "venv": ls.venv_path,
            "container": ls.container_image}.get(ls.env_kind, "")
    return EnvChoice(cast(EnvKind, ls.env_kind), path) if path else EnvChoice("none", "")


def build_script(account: Account, ls: LaunchSpec, settings: WebSettings,
                 now: datetime) -> tuple[str, str]:
    """(script, folder_name) for a launch, dispatching on its intent."""
    if ls.intent not in INTENTS:
        raise ValueError(f"unknown intent {ls.intent!r}")
    user = account.username
    home = account.home or f"/home/{user}"
    base = "smoke-test" if ls.intent == "smoke" else (
        clean_job_name(PurePosixPath(ls.script).stem) or "job")
    folder_name = job_folder_name(base, now)
    folder = f"{user_job_root(settings.nfs_root, user)}/{folder_name}"
    if ls.intent == "smoke":
        return render_smoke(user, folder, home, _env(ls), settings.partition,
                            nfs_root=settings.nfs_root), folder_name
    spec = to_job_spec(ls, user=user, partition=settings.partition, job_name=base,
                       run_command=run_command_for(ls.script, ls.args))
    env_fields = _env(ls).as_fields()
    spec.conda_env, spec.venv_path = env_fields["conda_env"], env_fields["venv_path"]
    spec.container_image = env_fields["container_image"]
    if ls.mail:
        spec.mail_user = account.email
    return render_batch(spec, folder, home, "END,FAIL", nfs_root=settings.nfs_root), folder_name


templates.register(
    "job_extended",
    lambda c: f"Job {c['job_id']} on {c['cluster']} was extended",
    lambda c: [f"Your job {c['name']} ({c['job_id']}) was given {c['hours']} more hour(s).",
               f"Its time limit is now {c['new_limit']}.",
               templates.Button("Open the job", f"{c['site']}/jobs/{c['job_id']}")])
