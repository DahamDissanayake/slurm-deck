"""session.info: the SD_SESSION line from the owner's job output, returned
only when it points at the job's own node and a session port."""

import json

import pytest
from test_verbs_jobs import SCONTROL, _err, job, jobs  # noqa: F401  (jobs is a fixture)

NODE_ADDR = "192.168.122.10"
TOKEN = "ab" * 24


@pytest.fixture
def sess(jobs):  # noqa: F811
    scontrol = SCONTROL.replace(
        '"show partition")',
        f'"show node") echo "NodeName=gpu1 NodeAddr={NODE_ADDR} NodeHostName=gpu1 State=MIXED";;'
        '\n"show partition")')
    (jobs.dir / "bin" / "scontrol").write_text(scontrol)
    return jobs


def session_job(agent, job_id="600", node=NODE_ADDR, port=8801, ready=True, owner="amasha"):
    job(agent, job_id, owner=owner)
    out = agent.dir / "shared/jobs" / owner / "train_1"
    (out / f"slurm-{job_id}.out").write_text(
        "starting\n"
        f"SD_SESSION kind=notebook node={node} port={port} token={TOKEN}\n")
    if ready:
        (out / ".sd-ready").write_text("")


def test_owner_gets_the_session(sess):
    session_job(sess)
    r = sess.call("session.info", {"job_id": "600"})
    assert r == {"state": "RUNNING", "ready": True, "kind": "notebook", "node": NODE_ADDR,
                 "port": 8801, "token": TOKEN}


def test_not_ready_until_the_marker_exists(sess):
    session_job(sess, ready=False)
    r = sess.call("session.info", {"job_id": "600"})
    assert r["ready"] is False and r["port"] == 8801


def test_no_session_line_yet(sess):
    job(sess, "601")
    r = sess.call("session.info", {"job_id": "601"})
    assert (r["ready"], r["kind"], r["token"]) == (False, None, None)


def test_node_mismatch_refused(sess):
    session_job(sess, node="10.0.0.5")
    e = _err(sess, "session.info", {"job_id": "600"})
    assert (e.code, e.status) == ("session_mismatch", 409)


def test_port_22_refused(sess):
    session_job(sess, port=22)
    e = _err(sess, "session.info", {"job_id": "600"})
    assert e.code == "session_port_refused"


def test_another_user_gets_404(sess):
    session_job(sess)
    assert _err(sess, "session.info", {"job_id": "600"}, as_="user:kasun").status == 404


def test_admin_gets_it_as_sd_ops_and_is_audited(sess):
    session_job(sess)
    r = sess.call("session.info", {"job_id": "600"}, as_="admin:dinuka")
    assert r["token"] == TOKEN
    assert ("sd-ops", "fsops") in sess.ran and ("amasha", "fsops") not in sess.ran
    lines = [json.loads(x) for x in (sess.dir / "audit").read_text().splitlines()]
    admin = [x for x in lines if x["verb"] == "session.info" and x["target"] == "600"]
    assert admin and admin[0]["actor"] == "dinuka" and admin[0]["detail"]["owner"] == "amasha"
