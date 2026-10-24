"""Where a running session job can be reached, from the line it prints.

Session jobs print `SD_SESSION kind=<kind> node=<addr> port=<port> token=<hex>`
once their service accepts connections (see sdcore.sbatch).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SESSION_LINE = re.compile(
    r"^SD_SESSION kind=(notebook|terminal|tensorboard) node=(\S+) port=(\d+) "
    r"token=([0-9a-f]+)$")


@dataclass(frozen=True)
class SessionInfo:
    kind: str
    node: str
    port: int
    token: str


def parse_session_line(out_text: str) -> SessionInfo | None:
    """The job's session details; the last line wins if the service restarted."""
    found = None
    for line in out_text.splitlines():
        if m := _SESSION_LINE.match(line.strip()):
            found = SessionInfo(m.group(1), m.group(2), int(m.group(3)), m.group(4))
    return found
