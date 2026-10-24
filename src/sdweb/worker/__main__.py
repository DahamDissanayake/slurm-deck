"""Worker loop: every 10 seconds, drain the mail outbox. One failing pass is
logged and the loop carries on."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime

from sdweb import db
from sdweb.config import load_settings
from sdweb.mail.senders import sender_for
from sdweb.worker.mail_task import drain

log = logging.getLogger("sdweb.worker")

INTERVAL_S = 10


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    settings = load_settings(os.environ)
    db.configure(settings)
    sender = sender_for(settings)
    while True:
        try:
            with db.session_scope() as session:
                drain(session, sender, datetime.now(UTC))
        except Exception:
            log.exception("mail outbox pass failed")
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    main()
