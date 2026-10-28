"""deck-agent's local audit log: one JSON line per call, root-only file."""

import json
import os
import stat
import sys

import pytest

from deckagent.audit import audit
from deckagent.config import load_config


def _config(path):
    return load_config({"SD_WEB_UID": "1001", "SD_WORKER_UID": "1002", "SD_AUDIT_LOG": str(path)})


def test_audit_line_written_and_mode_0600(tmp_path):
    path = tmp_path / "log" / "agent-audit.jsonl"
    cfg = _config(path)
    audit(cfg, actor="amasha", acting_admin=None, verb="job.submit", target="12",
          detail={"partition": "gpu"}, result="ok")
    audit(cfg, actor=None, acting_admin=None, verb="cluster.status", result="no_session")
    lines = [json.loads(x) for x in path.read_text().splitlines()]
    assert [x["verb"] for x in lines] == ["job.submit", "cluster.status"]
    assert lines[0]["actor"] == "amasha" and lines[0]["detail"] == {"partition": "gpu"}
    assert lines[0]["ts"].endswith("+00:00") and lines[1]["result"] == "no_session"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_existing_wider_file_is_tightened(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text("")
    path.chmod(0o644)
    audit(_config(path), actor="a", acting_admin=None, verb="v", result="ok")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform != "linux", reason="symlink and O_NOFOLLOW semantics")
def test_never_raises_and_never_follows_a_symlink(tmp_path, caplog):
    target = tmp_path / "elsewhere"
    target.write_text("")
    link = tmp_path / "audit.jsonl"
    os.symlink(target, link)
    audit(_config(link), actor="a", acting_admin=None, verb="v", result="ok")
    assert target.read_text() == "" and "audit" in caplog.text
    (tmp_path / "file").write_text("")      # a parent that can't be made: logged, not raised
    audit(_config(tmp_path / "file" / "x"), actor="a", acting_admin=None, verb="v", result="ok")
