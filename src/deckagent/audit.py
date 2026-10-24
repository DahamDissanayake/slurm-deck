"""deck-agent's local audit log: one JSON line per call, in a root-only file.

This is deck-agent's own record, kept even when the web app's database is
down. A failure to write is logged and never fails the call.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

from deckagent.config import AgentConfig

log = logging.getLogger("deckagent.audit")

_FLAGS = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | getattr(
    os, "O_CLOEXEC", 0)


def audit(config: AgentConfig, *, actor: str | None, acting_admin: str | None, verb: str,
          target: str = "", detail: dict[str, Any] | None = None, result: str) -> None:
    line = json.dumps({"ts": datetime.now(UTC).isoformat(), "actor": actor,
                       "acting_admin": acting_admin, "verb": verb, "target": target,
                       "detail": detail or {}, "result": result}, default=str) + "\n"
    try:
        os.makedirs(os.path.dirname(config.audit_log) or ".", mode=0o700, exist_ok=True)
        fd = os.open(config.audit_log, _FLAGS, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, line.encode())   # one write per line: O_APPEND keeps lines whole
        finally:
            os.close(fd)
    except Exception:
        log.exception("could not write the audit log %s: %s", config.audit_log, line.strip())
