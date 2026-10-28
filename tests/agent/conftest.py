"""A real deck-agent on a temp socket with the production verbs, fake system
commands on PATH (each logs `name args` to fake.log), and an AgentClient."""

import grp
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

SQUEUE = ("101|train-a|amasha|RUNNING|gpu|1:00:00|8:00:00|1|gres/shard:2|7:00:00\n"
          "102|secret-b|hassan|RUNNING|gpu|0:10:00|2:00:00|1|gres/shard:1|1:50:00\n"
          "103|queued-c|hassan|PENDING|gpu|0:00|1:00:00|1|gres/shard:1|1:00:00\n")
NODE = ("NodeName=gpu1 State=MIXED CPULoad=1.5 CPUTot=32 CPUAlloc=6 RealMemory=128000 "
        "Gres=gpu:1,shard:8 AllocTRES=cpu=6,mem=16G,gres/shard=3\n")
PARTITION = "PartitionName=gpu MaxTime=1-00:00:00 State=UP\n"

FAKES = {
    "squeue": f"printf '%s' '{SQUEUE}'",
    "scontrol": f'case "$2" in node) printf "%s" "{NODE}";; *) printf "%s" "{PARTITION}";; esac',
    # ssh: the GPU-host helper; fails on any op named in ssh.failon.
    "ssh": 'f=$(cat "$FAKE_DIR/ssh.failon" 2>/dev/null); '
           'if [ -n "$f" ] && echo "$*" | grep -q -- "$f"; then echo \'{"ok":false}\'; exit 1; fi; '
           'echo \'{"ok": true, "exists": false}\'',
}
PLAIN = ("sacct", "sacctmgr", "scancel", "sbatch", "useradd", "groupadd", "userdel",
         "groupdel", "passwd", "pkill")


class FakeStore:
    """Every account is an active user unless its name is in disabled."""

    def __init__(self) -> None:
        self.disabled: set[str] = set()

    def account(self, username: str) -> Any:
        from types import SimpleNamespace

        status = "disabled" if username in self.disabled else "active"
        return SimpleNamespace(username=username, role="user", status=status)


@dataclass
class Agent:
    path: str
    log: Path
    dir: Path
    config: Any
    store: FakeStore

    def calls(self) -> str:
        return self.log.read_text() if self.log.exists() else ""

    def call(self, verb: str, payload: dict | None = None, *, as_: str = "user:amasha"):
        from sdweb.agent import AgentClient

        return AgentClient(self.path).call(verb, payload, session=as_)


@pytest.fixture
def agent(tmp_path, monkeypatch):
    if sys.platform != "linux":
        pytest.skip("deck-agent needs Linux (AF_UNIX + SO_PEERCRED)")
    import deckagent.verbs.accounts  # noqa: F401  (registers the verbs)
    import deckagent.verbs.cluster  # noqa: F401
    import deckagent.verbs.files  # noqa: F401
    import deckagent.verbs.jobs  # noqa: F401
    from deckagent.config import load_config
    from deckagent.protocol import AgentError, Caller
    from deckagent.server import AgentServer

    bindir, log = tmp_path / "bin", tmp_path / "fake.log"
    bindir.mkdir()
    for name in (*FAKES, *PLAIN):
        body = FAKES.get(name, "")
        (bindir / name).write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n{body}\n')
        (bindir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    monkeypatch.setenv("FAKE_DIR", str(tmp_path))
    (tmp_path / "shared").mkdir()
    (tmp_path / "grant.key").write_bytes(os.urandom(32))

    def resolve(peer, headers, store, config):
        token = headers.get("x-sd-session", "")
        if token == "worker":
            return Caller(None, "worker", None, True, None)
        role, _, name = token.partition(":")
        if not name:
            raise AgentError("no_session", "Sign in again.", 401)
        return Caller(name, role, "hidden", False, None)

    env = {"SD_AGENT_SOCKET": str(tmp_path / "agent.sock"), "SD_WEB_UID": str(os.getuid()),
           "SD_WORKER_UID": "1", "SD_SLURM_BIN": str(bindir), "SD_COMPUTE_NODE": "gpu1",
           "SD_NFS_ROOT": str(tmp_path / "shared"), "SD_AUDIT_LOG": str(tmp_path / "audit"),
           "SD_GPU_HELPER_SSH": "sdprov@gpu-host", "SD_GPU_HELPER_KEY": "/k",
           "SD_GRANT_KEY_FILE": str(tmp_path / "grant.key"),
           "SD_AGENT_SOCKET_GROUP": grp.getgrgid(os.getgid()).gr_name}
    from deckagent.verbs.files import ACTIVE_ACCOUNTS

    ACTIVE_ACCOUNTS.clear()
    store = FakeStore()
    server = AgentServer(load_config(env), store=store, resolve=resolve)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield Agent(env["SD_AGENT_SOCKET"], log, tmp_path, server.config, store)
    finally:
        server.shutdown()
        thread.join(5)
