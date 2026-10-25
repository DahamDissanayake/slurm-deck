"""Install progress, kept in a JSON file so a failed run resumes where it
stopped: the steps already done, the answers given and the values generated
(secrets, the sd-ops UID), so a rerun reuses them instead of making new ones."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_PATH = "/etc/slurm-deck-web/install-state.json"


class State:
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = Path(path)
        self.data: dict[str, Any] = {"done": [], "answers": {}, "generated": {}}
        if self.path.exists():
            self.data.update(json.loads(self.path.read_text()))

    def done(self, step: str) -> bool:
        return step in self.data["done"]

    def mark(self, step: str) -> None:
        self.data["done"].append(step)
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)   # it holds secrets
        with os.fdopen(fd, "w") as f:
            json.dump(self.data, f, indent=2)
        tmp.replace(self.path)
