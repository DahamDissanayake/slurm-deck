"""AgentClient against a real deck-agent on a Unix socket."""

import os
import sys
import threading

import pytest

from sdweb.agent import AgentCallError, AgentClient

if sys.platform != "linux":
    pytest.skip("deck-agent needs Linux (AF_UNIX + SO_PEERCRED)", allow_module_level=True)


@pytest.fixture
def socket_path(tmp_path):
    from deckagent.config import load_config
    from deckagent.protocol import Caller
    from deckagent.server import AgentServer
    from deckagent.verbs import VerbRegistry
    from deckagent.verbs.cluster import disk_free

    registry = VerbRegistry()
    registry.verb("cluster.disk_free", allow=frozenset({"user"}))(disk_free)

    @registry.verb("fs.write_chunk", allow=frozenset({"user"}), body="raw")
    def _chunk(ctx, stream):
        assert ctx.headers["x-sd-grant"] == "g" and ctx.headers["x-sd-upload"] == "upl12345"
        return {"offset": int(ctx.headers["x-sd-offset"]) + len(stream.read())}

    env = {"SD_AGENT_SOCKET": str(tmp_path / "a.sock"), "SD_WEB_UID": str(os.getuid()),
           "SD_WORKER_UID": "1", "SD_NFS_ROOT": str(tmp_path), "SD_AUDIT_LOG": str(tmp_path / "x")}
    server = AgentServer(load_config(env), store=None, verbs=registry,
                         resolve=lambda p, h, s, c: Caller("amasha", "user", "hidden", False, None))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield env["SD_AGENT_SOCKET"]
    server.shutdown()


def test_agent_client_roundtrip(socket_path):
    client = AgentClient(socket_path)
    d = client.call("cluster.disk_free", session="tok")
    assert all(isinstance(d[k], int) for k in ("total_bytes", "used_bytes", "free_bytes"))
    with pytest.raises(AgentCallError) as e:
        client.call("no.such.verb", session="tok")
    assert (e.value.code, e.value.status) == ("unknown_verb", 404)
    assert b"".join(client.stream("cluster.disk_free", {}, session="tok")).startswith(b'{"ok"')


def test_upload_chunk_streams_a_sized_body(socket_path):
    client = AgentClient(socket_path)
    assert client.upload_chunk("upl12345", 7, [b"ab", b"cde"], length=5, grant="g") == 12
