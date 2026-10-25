"""usage.* and admin.disk_usage verbs, against fake sacct and du."""

import subprocess

import pytest
from test_verbs_envs import _ident

from sdweb.agent import AgentCallError

SACCT = r'''#!/bin/sh
echo "sacct $*" >> "$FAKE_DIR/fake.log"
case "$*" in *" -a"*) cat "$FAKE_DIR/sacct.all";; *) cat "$FAKE_DIR/sacct.me";; esac
'''
DU = r'''#!/bin/sh
echo "du $*" >> "$FAKE_DIR/fake.log"
cat "$FAKE_DIR/du.$(basename "$3")"
'''


@pytest.fixture
def usage(agent, monkeypatch):
    from deckagent import slurmcmd
    from deckagent.verbs import usage as usage_mod

    def run_as(who, argv, *, input=None, timeout=60, cwd=None, env=None):
        agent.ran.append((who.name, argv[0].rsplit("/", 1)[-1]))
        return subprocess.run(argv, input=input, capture_output=True, timeout=timeout)

    agent.ran = []
    for name, body in (("sacct", SACCT), ("du", DU)):
        (agent.dir / "bin" / name).write_text(body)
        (agent.dir / "bin" / name).chmod(0o755)
    (agent.dir / "sacct.me").write_text(
        "amasha|COMPLETED|10800|cpu=8,gres/shard=4\namasha|FAILED|3600|cpu=2\n")
    (agent.dir / "sacct.all").write_text(
        "amasha|COMPLETED|10800|cpu=8,gres/shard=4\nhassan|COMPLETED|7200|cpu=4,gres/shard=8\n")
    monkeypatch.setattr(usage_mod, "_identity", lambda caller, config: _ident(caller.username))
    monkeypatch.setattr(usage_mod, "_ops_identity", lambda caller, config: _ident("sd-ops"))
    monkeypatch.setattr(usage_mod, "run_as", run_as)
    monkeypatch.setattr(slurmcmd, "run_as", run_as)
    usage_mod._disk_cache.clear()
    return agent


def _status(agent, verb, payload=None, as_="user:amasha"):
    with pytest.raises(AgentCallError) as e:
        agent.call(verb, payload, as_=as_)
    return e.value.status


def test_personal_usage_is_computed_as_the_user(usage):
    # The node has 8 pods: 4 pods for 3 h is 1.5 GPU-hours.
    r = usage.call("usage.personal", {"days": 30})
    assert r["gpu_hours"] == 1.5 and r["cpu_hours"] == 8 * 3 + 2 * 1
    assert r["jobs_by_state"] == {"COMPLETED": 1, "FAILED": 1} and r["days"] == 30
    assert ("amasha", "sacct") in usage.ran
    assert "now-30days" in usage.calls()


def test_days_must_be_7_30_or_90(usage):
    assert _status(usage, "usage.personal", {"days": 10}) == 422
    assert _status(usage, "usage.personal", {}) == 422


def test_cluster_usage_is_admin_only_and_grouped_by_user(usage):
    assert _status(usage, "usage.cluster", {"days": 30}) == 403
    r = usage.call("usage.cluster", {"days": 7}, as_="admin:dinuka")
    assert [u["user"] for u in r["users"]] == ["hassan", "amasha"]   # heaviest GPU user first
    assert r["users"][0]["gpu_hours"] == 2.0 and r["total"]["gpu_hours"] == 3.5
    assert "-a" in usage.calls()


def test_disk_usage_counts_both_trees_and_is_cached(usage):
    (usage.dir / "du.users").write_text(
        f"900\t{usage.dir}/shared/users/amasha\n300\t{usage.dir}/shared/users/hassan\n"
        f"1300\t{usage.dir}/shared/users\n")
    (usage.dir / "du.jobs").write_text(
        f"100\t{usage.dir}/shared/jobs/amasha\n50\t{usage.dir}/shared/jobs/kasun\n"
        f"160\t{usage.dir}/shared/jobs\n")
    assert _status(usage, "admin.disk_usage") == 403
    r = usage.call("admin.disk_usage", as_="admin:dinuka")
    assert r["users"] == [
        {"user": "amasha", "bytes": 1000, "users_bytes": 900, "jobs_bytes": 100},
        {"user": "hassan", "bytes": 300, "users_bytes": 300, "jobs_bytes": 0},
        {"user": "kasun", "bytes": 50, "users_bytes": 0, "jobs_bytes": 50}]
    assert r["total_bytes"] == 1350 and ("sd-ops", "du") in usage.ran
    usage.call("admin.disk_usage", as_="admin:dinuka")
    assert usage.calls().count("du -b") == 2   # one per tree, not per call
