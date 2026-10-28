"""The staging janitor: once an hour, remove staged uploads nobody has touched
for UPLOAD_RESUME_HOURS, running fsops stage-sweep as each folder's owner."""

from __future__ import annotations

import logging
import os
import threading

from deckagent.config import AgentConfig
from deckagent.protocol import AgentError, Caller
from deckagent.verbs import files
from sdcore.names import valid_username

log = logging.getLogger("deckagent.janitor")

INTERVAL_S = 3600


def sweep(config: AgentConfig) -> int:
    """One pass over every user's staging area; the number of files removed."""
    try:
        names = sorted(os.listdir(os.path.join(config.nfs_root, "users")))
    except OSError as e:
        log.warning("janitor can't list users: %s", e)
        return 0
    removed = 0
    for name in names:
        if not valid_username(name):
            continue
        try:
            ident = files._identity(Caller(name, "user", "shell", False, None), config)
            argv = files._argv(config, "stage-sweep", ["--user", name],
                               opts=("--max-age-h", str(config.upload_resume_hours)))
            removed += int(files._run(ident, argv).get("removed", 0))
        except AgentError as e:   # no such account any more, or refused: skip it
            log.info("janitor skipped %s: %s", name, e.message)
    return removed


def start(config: AgentConfig) -> threading.Thread:
    def loop() -> None:
        stop = threading.Event()
        while not stop.wait(INTERVAL_S):
            try:
                n = sweep(config)
                if n:
                    log.info("janitor removed %d stale upload(s)", n)
            except Exception:
                log.exception("janitor pass failed")

    thread = threading.Thread(target=loop, name="janitor", daemon=True)
    thread.start()
    return thread
