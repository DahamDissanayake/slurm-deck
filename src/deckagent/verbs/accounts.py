"""Account verbs (admin only): create, attach a shell account, inspect an old
folder, delete.

A new web account is a hidden Linux account on both nodes with the same UID,
plus a Slurm association. Create runs the steps in order and, if one fails,
undoes the ones already done, so a retry starts clean. The GPU-host account is
undone even when its own step failed, since the helper may have created it
before failing.
"""

from __future__ import annotations

import grp
import logging
import pwd
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from deckagent.gpuhost import GpuHost
from deckagent.identity import PRIVILEGED_GROUPS, PosixIdentity, lookup_account
from deckagent.protocol import AgentError, RequestContext
from deckagent.slurmcmd import run, run_slurm
from deckagent.verbs import verb
from sdcore.names import RESERVED, valid_username

log = logging.getLogger("deckagent.accounts")

ADMIN = frozenset({"admin"})
UID_FLOOR = 1000


def _username(payload: dict[str, Any]) -> str:
    name = payload.get("username")
    if not isinstance(name, str) or not valid_username(name) or name in RESERVED:
        raise AgentError("bad_username", "That username isn't allowed.", 422)
    return name


def _uid_in_use(uid: int) -> bool:
    try:
        pwd.getpwuid(uid)
        return True
    except KeyError:
        return False


def _exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def _group_exists(name: str) -> bool:
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def _groups(name: str) -> set[str]:
    return {g.gr_name for g in grp.getgrall() if name in g.gr_mem}


def _lookup(name: str) -> tuple[PosixIdentity, frozenset[str]]:
    return lookup_account(name, pwd, grp)


@verb("account.inspect_folder", allow=ADMIN)
def inspect_folder(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    info = GpuHost(ctx.config).folder_info(_username(payload))
    in_use = info.owner_uid is not None and _uid_in_use(info.owner_uid)
    return {**asdict(info), "uid_in_use": in_use}


def _check_uid(ctx: RequestContext, name: str, uid: Any, link_existing: bool) -> int:
    cfg = ctx.config
    if not isinstance(uid, int) or isinstance(uid, bool):
        raise AgentError("bad_uid", "The UID must be a number.", 422)
    if _exists(name):
        raise AgentError("username_taken", f"{name} already exists on the cluster.", 409)
    if _uid_in_use(uid):
        raise AgentError("uid_taken", f"UID {uid} already belongs to an account.", 409)
    if cfg.web_uid_min <= uid <= cfg.web_uid_max and not link_existing:
        return uid
    # Outside the web range only to reconnect an old folder that this UID owns.
    info = GpuHost(cfg).folder_info(name) if link_existing else None
    if info is None or not info.exists or info.owner_uid != uid or uid < UID_FLOOR:
        raise AgentError("uid_not_allowed",
                         f"UID {uid} is outside the web range and doesn't own {name}'s folder.",
                         409)
    return uid


@verb("account.create", allow=ADMIN)
def create(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.config
    name = _username(payload)
    link_existing = payload.get("link_existing") is True
    uid = _check_uid(ctx, name, payload.get("uid"), link_existing)
    host = GpuHost(cfg)
    groups = f"{cfg.webusers_group},{cfg.gpuusers_group}"

    def drop_group() -> None:
        if _group_exists(name):   # userdel removes the user's private group itself
            run(["groupdel", name])

    # (action, undo, undo it even when the action itself failed)
    steps: list[tuple[Callable[[], Any], Callable[[], Any] | None, bool]] = [
        (lambda: run(["groupadd", "-g", str(uid), name]), drop_group, False),
        (lambda: run(["useradd", "-u", str(uid), "-g", str(uid), "-M", "-d", f"/home/{name}",
                      "-s", "/usr/sbin/nologin", "-G", groups, name]),
         lambda: run(["userdel", name]), False),
        (lambda: run(["passwd", "-l", name]), None, False),
        (lambda: run_slurm(cfg, ["sacctmgr", "-i", "add", "user", name,
                                 f"account={cfg.slurm_account}", f"qos={cfg.slurm_qos}"]),
         lambda: run_slurm(cfg, ["sacctmgr", "-i", "delete", "user", name]), False),
        # delete-account is safe on a missing account.
        (lambda: host.create_account(name, uid), lambda: host.delete_account(name), True),
    ]
    if not link_existing:
        steps.append((lambda: host.create_folders(name, uid), None, False))
    done: list[Callable[[], Any]] = []
    for action, undo, undo_on_failure in steps:
        try:
            action()
        except AgentError as e:
            if undo is not None and undo_on_failure:
                done.append(undo)
            for u in reversed(done):
                try:
                    u()
                except AgentError as rollback:
                    log.error("rollback step failed for %s: %s", name, rollback.message)
            raise AgentError("account_create_failed",
                             f"Creating {name} failed and was undone: {e.message}", 502) from None
        if undo is not None:
            done.append(undo)
    return {"username": name, "uid": uid}


@verb("account.attach_shell", allow=ADMIN)
def attach_shell(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    """Check an existing shell account may be used from the web; changes nothing."""
    name = _username(payload)
    try:
        ident, groups = _lookup(name)
    except AgentError:
        raise AgentError("not_attachable", f"There is no Linux account {name}.", 403) from None
    blocked = PRIVILEGED_GROUPS | {ctx.config.admin_group, ctx.config.webusers_group}
    if ident.uid < UID_FLOOR or groups & blocked:
        raise AgentError("not_attachable", f"{name} can't be attached to the web.", 403)
    return {"uid": ident.uid, "home": ident.home}


@verb("account.delete", allow=ADMIN)
def delete(ctx: RequestContext, payload: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.config
    name = _username(payload)
    if cfg.webusers_group not in _groups(name):
        raise AgentError("not_web_account", f"{name} isn't a web account.", 403)
    host = GpuHost(cfg)
    run_slurm(cfg, ["scancel", "-u", name])
    run_slurm(cfg, ["sacctmgr", "-i", "delete", "user", name])
    if payload.get("purge") is True:
        host.purge(name)
    else:
        host.archive(name)
    host.delete_account(name)
    for argv in (["pkill", "-KILL", "-u", name], ["userdel", name], ["groupdel", name]):
        try:
            run(argv)
        except AgentError as e:   # pkill: no processes; already gone: fine
            log.info("%s: %s", argv[0], e.message)
    return {}
