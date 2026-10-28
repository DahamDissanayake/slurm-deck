"""The verb registry. Verb modules register handlers with the `verb` decorator:

    @verb("cluster.status", allow=frozenset({"user", "admin", "worker"}))
    def status(ctx: RequestContext, payload: dict) -> Any: ...

`allow` lists the caller roles that may call it. body="raw" hands the handler
the request body as a stream instead of a decoded JSON object. session=False
skips session resolution (the handler authorises the request itself, e.g. an
upload grant); `allow` is then not checked.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ROLES = frozenset({"user", "admin", "worker"})

Handler = Callable[..., Any]


@dataclass(frozen=True)
class Verb:
    name: str
    allow: frozenset[str]
    body: str
    handler: Handler
    session: bool = True


class VerbRegistry:
    def __init__(self) -> None:
        self._verbs: dict[str, Verb] = {}

    def verb(self, name: str, *, allow: frozenset[str], body: str = "json",
             session: bool = True) -> Callable[[Handler], Handler]:
        if not allow or not allow <= ROLES:
            raise ValueError(f"{name}: allow must be a non-empty subset of {sorted(ROLES)}")
        if body not in ("json", "raw"):
            raise ValueError(f"{name}: body must be 'json' or 'raw'")
        if name in self._verbs:
            raise ValueError(f"verb {name} is already registered")

        def register(handler: Handler) -> Handler:
            self._verbs[name] = Verb(name, allow, body, handler, session)
            return handler
        return register

    def get(self, name: str) -> Verb | None:
        return self._verbs.get(name)


REGISTRY = VerbRegistry()
verb = REGISTRY.verb
