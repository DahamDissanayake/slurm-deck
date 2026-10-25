"""deck-agent's client for the GPU-host helper (gpuhost/sd-gpu-helper).

Runs `ssh -i <key> -o BatchMode=yes -o StrictHostKeyChecking=yes <target>
<op> <args>`; sdprov's key is restricted to the forced command, so the words
after the target arrive as SSH_ORIGINAL_COMMAND. Arguments are checked here as
well as on the host. Exit 2 (the helper refused) becomes 403; any other
failure, including SSH itself, becomes 502.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

from deckagent.config import AgentConfig
from deckagent.protocol import AgentError
from sdcore.names import valid_username

UID_MIN, UID_MAX = 1000, 60000


@dataclass(frozen=True)
class FolderInfo:
    exists: bool
    owner_uid: int | None = None
    bytes: int | None = None
    mtime: str | None = None


def _failed(message: str) -> AgentError:
    return AgentError("gpuhost_failed", message, 502)


class GpuHost:
    def __init__(self, config: AgentConfig, *, ssh: str = "ssh", timeout_s: int = 300) -> None:
        self.config = config
        self.ssh = ssh
        self.timeout_s = timeout_s

    def _call(self, op: str, *args: str) -> dict[str, Any]:
        if not self.config.gpu_helper_ssh:
            raise _failed("The GPU host helper is not configured.")
        cmd = [self.ssh, "-i", self.config.gpu_helper_key, "-o", "BatchMode=yes",
               "-o", "StrictHostKeyChecking=yes", self.config.gpu_helper_ssh, op, *args]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout_s)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise _failed(f"Could not reach the GPU host: {e}") from None
        try:
            out = json.loads(r.stdout)
        except ValueError:
            out = None
        if r.returncode == 2:
            reason = out.get("error") if isinstance(out, dict) else "refused"
            raise AgentError("gpuhost_refused", f"The GPU host refused: {reason}", 403)
        if r.returncode != 0 or not isinstance(out, dict) or out.get("ok") is not True:
            raise _failed(f"The GPU host step {op} failed.")
        return out

    @staticmethod
    def _user(user: str) -> str:
        if not valid_username(user):
            raise AgentError("bad_username", f"Invalid username: {user!r}", 400)
        return user

    @staticmethod
    def _uid(uid: int) -> str:
        if not UID_MIN <= uid <= UID_MAX:
            raise AgentError("bad_uid", f"UID out of range: {uid}", 400)
        return str(uid)

    def create_account(self, user: str, uid: int) -> None:
        self._call("create-account", self._user(user), self._uid(uid))

    def create_folders(self, user: str, uid: int) -> None:
        self._call("create-folders", self._user(user), self._uid(uid))

    def folder_info(self, user: str) -> FolderInfo:
        out = self._call("folder-info", self._user(user))
        if not out.get("exists"):
            return FolderInfo(False)
        return FolderInfo(True, int(out["owner_uid"]), int(out["bytes"]), str(out["mtime"]))

    def archive(self, user: str) -> None:
        self._call("archive", self._user(user))

    def purge(self, user: str) -> None:
        self._call("purge", self._user(user))

    def delete_account(self, user: str) -> None:
        self._call("delete-account", self._user(user))

    def service_status(self) -> dict[str, str]:
        units = self._call("service-status").get("units", {})
        return {str(k): str(v) for k, v in units.items()}

    def ping(self) -> bool:
        try:
            return self._call("ping").get("pong") is True
        except AgentError:
            return False
