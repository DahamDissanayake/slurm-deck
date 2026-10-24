"""Which Linux identity deck-agent may use for a caller.

User work runs as the caller's own account: a hidden web account (a member of
webusers), or an attached shell account acting as itself. Never root, a
system account (UID below 1000), a reserved name, the ops account, or anyone
in a privileged group. Admin file work runs as the ops account (sd-ops), and
only for an admin caller.
"""

from __future__ import annotations

import grp
import pwd
from dataclasses import dataclass
from typing import Any

from deckagent.config import AgentConfig
from deckagent.protocol import AgentError, Caller
from sdcore.names import RESERVED, USERNAME_RE

UID_MIN = 1000
PRIVILEGED_GROUPS = frozenset({"sudo", "wheel", "admin"})


@dataclass(frozen=True)
class PosixIdentity:
    name: str
    uid: int
    gid: int
    groups: tuple[int, ...]   # supplementary groups
    home: str


def _refused(message: str) -> AgentError:
    return AgentError("identity_refused", message, 403)


def _lookup(name: str, pw: Any, gr: Any) -> tuple[PosixIdentity, frozenset[str]]:
    """The account's identity and the names of every group it is in."""
    try:
        entry = pw.getpwnam(name)
    except KeyError:
        raise _refused("There is no Linux account for this user.") from None
    member_of = [g for g in gr.getgrall() if name in g.gr_mem or g.gr_gid == entry.pw_gid]
    ident = PosixIdentity(name, entry.pw_uid, entry.pw_gid,
                          tuple(sorted(g.gr_gid for g in member_of if name in g.gr_mem)),
                          entry.pw_dir)
    return ident, frozenset(g.gr_name for g in member_of)


def identity_for_user(caller: Caller, config: AgentConfig, pw: Any = pwd,
                      gr: Any = grp) -> PosixIdentity:
    name = caller.username
    if (name is None or caller.is_worker or not USERNAME_RE.fullmatch(name)
            or name in RESERVED or name == config.ops_user):
        raise _refused("This account can't run work on the cluster.")
    ident, groups = _lookup(name, pw, gr)
    if ident.uid < UID_MIN or ident.gid == 0:
        raise _refused("This account can't run work on the cluster.")
    if groups & (PRIVILEGED_GROUPS | {config.admin_group}):
        raise _refused("Privileged accounts can't run work through the web.")
    if config.webusers_group not in groups and caller.linux_kind != "shell":
        raise _refused("This account isn't set up for the web yet.")
    return ident


def ops_identity(caller: Caller, config: AgentConfig, pw: Any = pwd,
                 gr: Any = grp) -> PosixIdentity:
    """The ops account, for admin file work."""
    if caller.role != "admin" or caller.is_worker:
        raise AgentError("not_allowed", "Only admins can do that.", 403)
    ident, _ = _lookup(config.ops_user, pw, gr)
    if ident.uid < UID_MIN or ident.gid == 0:
        raise _refused("The ops account is misconfigured.")
    return ident
