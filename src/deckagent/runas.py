"""Run a command as a PosixIdentity: its uid, gid and supplementary groups,
a clean environment, no inherited file descriptors and no shell."""

from __future__ import annotations

import subprocess
from typing import Any

from deckagent.identity import PosixIdentity

SAFE_PATH = "/usr/local/bin:/usr/bin:/bin"
# deck-agent itself runs with UMask=0077; files made as the user get the usual modes.
USER_UMASK = 0o022


def _env(ident: PosixIdentity, env: dict[str, str] | None) -> dict[str, str]:
    return env or {"HOME": ident.home, "USER": ident.name, "PATH": SAFE_PATH}


def run_as(ident: PosixIdentity, argv: list[str], *, input: bytes | None = None,
           timeout: float = 60, cwd: str | None = None,
           env: dict[str, str] | None = None) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        argv, user=ident.uid, group=ident.gid, extra_groups=list(ident.groups),
        env=_env(ident, env), cwd=cwd, umask=USER_UMASK, timeout=timeout, capture_output=True,
        input=input, stdin=None if input is not None else subprocess.DEVNULL, close_fds=True)


def popen_as(ident: PosixIdentity, argv: list[str], *, cwd: str | None = None,
             env: dict[str, str] | None = None, **kw: Any) -> subprocess.Popen[bytes]:
    """For streaming output; the caller owns the process and its pipes."""
    kw.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.Popen(argv, user=ident.uid, group=ident.gid,
                            extra_groups=list(ident.groups), env=_env(ident, env), cwd=cwd,
                            umask=USER_UMASK, close_fds=True, **kw)
