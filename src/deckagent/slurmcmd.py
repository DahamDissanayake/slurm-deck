"""Running Slurm and system commands from deck-agent: no shell, a timeout,
and a plain AgentError (502) carrying stderr when one fails."""

from __future__ import annotations

import os
import subprocess

from deckagent.config import AgentConfig
from deckagent.identity import PosixIdentity
from deckagent.protocol import AgentError
from deckagent.runas import run_as


def run(argv: list[str], *, timeout: float = 30, code: str = "command_failed") -> str:
    """Run a command as deck-agent itself (root); stdout on success."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AgentError(code, f"{argv[0]} could not run: {e}", 502) from None
    if r.returncode != 0:
        raise AgentError(code, f"{argv[0]} failed: {r.stderr.strip()[:500]}", 502)
    return r.stdout


def run_slurm(config: AgentConfig, args: list[str], *, as_ident: PosixIdentity | None = None,
              timeout: float = 15) -> str:
    """A Slurm command from SD_SLURM_BIN, as root or as as_ident."""
    argv = [os.path.join(config.slurm_bin, args[0]), *args[1:]]
    if as_ident is None:
        return run(argv, timeout=timeout, code="slurm_failed")
    try:
        r = run_as(as_ident, argv, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AgentError("slurm_failed", f"{args[0]} could not run: {e}", 502) from None
    if r.returncode != 0:
        stderr = r.stderr.decode(errors="replace").strip()[:500]
        raise AgentError("slurm_failed", f"{args[0]} failed: {stderr}", 502)
    return r.stdout.decode(errors="replace")
