"""`python -m deckagent`: run deck-agent with settings from the environment.

Session resolution (deckagent.sessions) is not wired in yet, so only the
worker account is admitted; user and admin requests get 401.
"""

from __future__ import annotations

import logging
import os
import signal
import threading

from deckagent.config import load_config
from deckagent.server import AgentServer, worker_only


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = AgentServer(load_config(os.environ), store=None, resolve=worker_only)

    def stop(signum: int, frame: object) -> None:
        # shutdown() waits for serve_forever, so it can't run on this thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    logging.getLogger("deckagent").info("listening on %s", server.config.socket_path)
    server.serve_forever()


if __name__ == "__main__":
    main()
