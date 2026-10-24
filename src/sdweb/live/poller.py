"""The live poller: what /ws/live sends, fetched from deck-agent at most once
per cache window however many browsers are watching.

`web` has no identity of its own at deck-agent, so each fetch uses the
session of a client that is watching: the cluster picture isn't
user-specific and is shared by everyone; a job list is fetched once per
account with that account's session. Nothing is fetched while nobody watches.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sdweb.agent import AgentCallError
from sdweb.models import Job, Setting

log = logging.getLogger("sdweb.live")

CACHE_S = 2.0


class Poller:
    def __init__(self, agent: Any, factory: sessionmaker[Session],
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self.agent, self.factory, self.monotonic = agent, factory, monotonic
        self._lock = threading.Lock()
        self._cache: dict[Any, tuple[float, Any]] = {}

    def _cached(self, key: Any, fetch: Callable[[], Any]) -> Any:
        with self._lock:   # one fetch per key per window, even with many sockets
            hit = self._cache.get(key)
            if hit is not None and self.monotonic() - hit[0] < CACHE_S:
                return hit[1]
            value = fetch()
            self._cache[key] = (self.monotonic(), value)
            return value

    def cluster(self, session: str) -> dict[str, Any] | None:
        def fetch() -> dict[str, Any]:
            status = self.agent.call("cluster.status", {}, session=session)
            queue = self.agent.call("cluster.queue", {}, session=session)
            disk = self.agent.call("cluster.disk_free", {}, session=session)
            with self.factory() as db:
                banner = db.scalar(select(Setting.value).where(
                    Setting.key == "maintenance_banner"))
            return {"type": "cluster", **status, "queue": queue.get("jobs", []), "disk": disk,
                    "maintenance": banner}
        try:
            return dict(self._cached("cluster", fetch))
        except AgentCallError as e:
            log.warning("live cluster fetch failed: %s", e.message)
            return None

    def jobs(self, account_id: int, session: str) -> list[dict[str, Any]]:
        """The account's own messages: its job list, then a banner for each
        running job the worker has warned about."""
        try:
            jobs = self._cached(("jobs", account_id), lambda: self.agent.call(
                "job.list", {}, session=session).get("jobs", []))
        except AgentCallError as e:
            log.warning("live job fetch failed: %s", e.message)
            return []
        with self.factory() as db:
            warned = set(db.scalars(select(Job.job_id).where(Job.account_id == account_id,
                                                             Job.warned_at.is_not(None))))
        out: list[dict[str, Any]] = [{"type": "jobs", "jobs": jobs}]
        for j in jobs:
            if j.get("job_id") in warned and j.get("state") == "RUNNING":
                left = j.get("time_left_s")
                out.append({"type": "banner", "job_id": j["job_id"],
                            "minutes_left": int(left) // 60 if left is not None else None})
        return out
