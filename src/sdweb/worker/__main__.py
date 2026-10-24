"""Worker loop: drain the mail outbox every 10 seconds, and every minute send
expiry warnings and notify-when-free mail. One failing pass is logged and the
loop carries on."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sdweb import db
from sdweb.agent import AgentClient
from sdweb.config import load_settings
from sdweb.mail.senders import sender_for
from sdweb.worker import expiry_task, notify_task
from sdweb.worker.mail_task import drain

log = logging.getLogger("sdweb.worker")

INTERVAL_S = 10
EVERY_MINUTE = 6   # ticks


def _pass(name: str, fn: Callable[..., Any], *args: Any) -> None:
    """fn(session, *args) in one transaction."""
    try:
        with db.session_scope() as session:
            fn(session, *args)
    except Exception:
        log.exception("%s pass failed", name)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = load_settings(os.environ)
    db.configure(settings)
    sender = sender_for(settings)
    # The worker reaches deck-agent as itself (its peer UID), with no session.
    agent = AgentClient(settings.agent_socket)
    tick = 0
    while True:
        now = datetime.now(UTC)
        if tick % EVERY_MINUTE == 0:
            _pass("expiry", expiry_task.run_once, agent, now, settings)
            _pass("notify", notify_task.run_once, agent, now, settings)
        _pass("mail outbox", drain, sender, now)
        tick += 1
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
