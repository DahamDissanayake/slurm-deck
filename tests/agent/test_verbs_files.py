"""fs.* verbs: fsops as the caller, admin access through sd-ops, uploads with
grants, the free-space rule, streaming, and the staging janitor."""

import os
import pwd
import subprocess
import time
import tracemalloc
from collections import namedtuple

import pytest

from sdweb.agent import AgentCallError, AgentClient

ME = pwd.getpwuid(os.getuid())
UPLOAD = "upl-0001-amasha"


@pytest.fixture
def fsagent(agent, monkeypatch):
    """fsops runs as the test user (no setuid outside root); the areas exist."""
    from deckagent.identity import PosixIdentity
    from deckagent.verbs import files

    me = PosixIdentity(ME.pw_name, ME.pw_uid, ME.pw_gid, (), ME.pw_dir)
    monkeypatch.setattr(files, "_identity", lambda caller, config: me)
    monkeypatch.setattr(files, "_ops_identity", lambda caller, config: me)
    monkeypatch.setattr(files, "_spawn", lambda ident, argv, **kw: subprocess.Popen(argv, **kw))
    shared = agent.dir / "shared"
    for d in ("users/amasha", "users/bob", "datasets"):
        (shared / d).mkdir(parents=True)
    (shared / "users/bob/b.txt").write_text("bob")
    return agent


def _err(agent, verb, payload, as_="user:amasha") -> AgentCallError:
    with pytest.raises(AgentCallError) as e:
        agent.call(verb, payload, as_=as_)
    return e.value


def test_list_write_read_and_download(fsagent):
    a = fsagent
    client = AgentClient(a.path)
    assert a.call("fs.list", {"path": "users/amasha"}) == {"entries": []}
    a.call("fs.mkdir", {"path": "users/amasha/proj"})
    assert [e["name"] for e in a.call("fs.list", {"path": "users/amasha"})["entries"]] == ["proj"]
    assert _err(a, "fs.list", {"path": "users/bob"}).status == 403
    (a.dir / "shared/users/amasha/proj/x.txt").write_text("hello world")
    got = b"".join(client.stream("fs.read", {"path": "users/amasha/proj/x.txt", "offset": 6},
                                 session="user:amasha"))
    assert got == b"world"
    zipped = b"".join(client.stream("fs.download_stream", {"path": "users/amasha/proj"},
                                    session="user:amasha"))
    assert zipped[:2] == b"PK"


def test_as_admin_needs_admin(fsagent):
    a = fsagent
    assert _err(a, "fs.list", {"path": "users/bob", "as_admin": True}).status == 403
    entries = a.call("fs.list", {"path": "users/bob", "as_admin": True}, as_="admin:dinuka")
    assert [e["name"] for e in entries["entries"]] == ["b.txt"]


def test_free_space_refusal_uses_the_exact_copy(fsagent, monkeypatch):
    from deckagent.verbs import files

    st = namedtuple("st", "f_bavail f_frsize f_blocks f_bfree")
    monkeypatch.setattr(files.os, "statvfs", lambda p: st(2 * 10**9, 1, 5 * 10**9, 2 * 10**9))
    e = _err(fsagent, "fs.upload_begin", {"upload_id": UPLOAD, "dest_dir": "users/amasha",
                                          "filename": "big.bin", "size": 1_500_000_000})
    assert e.status == 507
    assert e.message == ("There isn't enough free space on the cluster for this upload "
                         "(2.0 GB free, 2.6 GB needed).")


def _begin(a, upload_id=UPLOAD, as_="user:amasha") -> str:
    out = a.call("fs.upload_begin", {"upload_id": upload_id, "dest_dir": "users/amasha",
                                     "filename": "data.bin", "size": 5 * 2**20}, as_=as_)
    assert out["offset"] == 0
    return out["grant"]


def test_upload_chunks_finalize_and_offsets(fsagent):
    a = fsagent
    client = AgentClient(a.path)
    grant = _begin(a)
    assert client.upload_chunk(UPLOAD, 0, [b"abc"], length=3, grant=grant) == 3
    with pytest.raises(AgentCallError) as e:
        client.upload_chunk(UPLOAD, 0, [b"abc"], length=3, grant=grant)
    assert e.value.status == 409
    regrant = a.call("fs.upload_regrant", {"upload_id": UPLOAD})
    assert regrant["offset"] == 3
    assert client.upload_chunk(UPLOAD, 3, [b"de"], length=2, grant=regrant["grant"]) == 5
    out = a.call("fs.upload_finalize", {"upload_id": UPLOAD, "dest_dir": "users/amasha",
                                        "filename": "data.bin", "replace": False})
    assert (a.dir / "shared/users/amasha/data.bin").read_bytes() == b"abcde"
    assert out["path"].endswith("users/amasha/data.bin")


def test_upload_chunk_audit_names_grant_user_and_upload(fsagent):
    import json

    a = fsagent
    client = AgentClient(a.path)
    grant = _begin(a)
    client.upload_chunk(UPLOAD, 0, [b"abc"], length=3, grant=grant)
    with pytest.raises(AgentCallError):
        client.upload_chunk(UPLOAD, 0, [b"abc"], length=3, grant=grant)
    with pytest.raises(AgentCallError):
        client.upload_chunk(UPLOAD, 3, [b"x"], length=1, grant="not-a-grant")
    lines = [json.loads(x) for x in (a.dir / "audit").read_text().splitlines()]
    got = [(x["actor"], x["target"], x["result"]) for x in lines
           if x["verb"] == "fs.write_chunk"]
    assert got == [("amasha", UPLOAD, "ok"), ("amasha", UPLOAD, "offset_mismatch"),
                   (None, "", "bad_grant")]


def test_grant_for_one_user_cannot_write_another_upload(fsagent):
    a = fsagent
    client = AgentClient(a.path)
    grant = _begin(a)
    with pytest.raises(AgentCallError) as e:
        client.upload_chunk("upl-0002-bob", 0, [b"x"], length=1, grant=grant)
    assert (e.value.code, e.value.status) == ("bad_grant", 403)
    with pytest.raises(AgentCallError) as e:
        client.upload_chunk(UPLOAD, 0, [b"x"], length=1, grant=grant[:-1] + "x")
    assert e.value.status == 403


def test_a_5mb_chunk_streams_without_memory_growth(fsagent):
    a = fsagent
    client = AgentClient(a.path)
    grant = _begin(a)
    piece = b"z" * 65536

    tracemalloc.start()
    try:
        size = client.upload_chunk(UPLOAD, 0, (piece for _ in range(80)), length=80 * 65536,
                                   grant=grant)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert size == 5 * 2**20
    assert peak < 3 * 2**20, peak      # never the whole 5 MB at once


def test_janitor_sweeps_old_parts(fsagent):
    from deckagent import janitor

    a = fsagent
    _begin(a)
    part = a.dir / "shared/users/amasha/.sd-uploads" / f"{UPLOAD}.part"
    part.write_bytes(b"old")
    fresh = part.with_name("upl-0003-fresh.part")
    fresh.write_bytes(b"new")
    old = time.time() - 25 * 3600
    os.utime(part, (old, old))
    janitor.sweep(a.config)
    assert not part.exists() and fresh.exists()
