"""`python -m deckagent`: run deck-agent with settings from the environment."""

from __future__ import annotations

import logging
import os
import signal
import threading

import deckagent.verbs.accounts  # noqa: F401  (each verb module registers its verbs)
import deckagent.verbs.cluster  # noqa: F401
import deckagent.verbs.files  # noqa: F401
import deckagent.verbs.jobs  # noqa: F401
from deckagent import janitor
from deckagent.config import load_config
from deckagent.server import AgentServer
from deckagent.sessions import PgSessionStore, resolve_caller


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    config = load_config(os.environ)
    if not config.db_ro_url:
        raise SystemExit("SD_DB_RO_URL is required: deck-agent reads sessions from it")
    server = AgentServer(config, store=PgSessionStore(config.db_ro_url), resolve=resolve_caller)

    def stop(signum: int, frame: object) -> None:
        # shutdown() waits for serve_forever, so it can't run on this thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    janitor.start(config)
    logging.getLogger("deckagent").info("listening on %s", server.config.socket_path)
    server.serve_forever()


if __name__ == "__main__":
    main()
