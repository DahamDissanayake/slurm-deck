"""admin.* verbs against fake Slurm, systemctl, runuser and ssh commands."""

import os
import subprocess

import pytest
from test_verbs_envs import _ident

from sdweb.agent import AgentCallError

FAKES = {
    "sacctmgr": r'''case "$*" in
*"format=Name,MaxWall"*) printf 'normal|08:00:00|gres/gpu=10,gres/shard=4|10\nlong||cpu=8|0\n';;
*"format=MaxTRESPerUser"*) echo "gres/gpu=10,gres/shard=4";;
esac''',
    "squeue": r'''case "$*" in
*nodelist*) printf '101|amasha|train-a|RUNNING\n';;
*states=RUNNING*) grep RUNNING "$FAKE_DIR/squeue.out";;
*) cat "$FAKE_DIR/squeue.out";;
esac''',
    "runuser": 'cat "$FAKE_DIR/runuser.out"; exit $(cat "$FAKE_DIR/runuser.rc")',
    "systemctl": '[ "$2" = mariadb ] && { echo failed; exit 3; }; echo active',
    "ssh": 'echo \'{"ok": true, "units": {"slurmd": "active", "munge": "inactive"}}\'',
}


@pytest.fixture
def admin(agent, monkeypatch):
    from deckagent.verbs import admin as admin_mod

    for name, body in FAKES.items():
        f = agent.dir / "bin" / name
        f.write_text(f'#!/bin/sh\necho "{name} $*" >> "$FAKE_DIR/fake.log"\n{body}\n')
        f.chmod(0o755)
    (agent.dir / "squeue.out").write_text(
        "101|train-a|amasha|RUNNING|gpu|1:00:00|8:00:00|1|gres/shard:2|7:00:00\n"
        "102|secret-b|hassan|RUNNING|gpu|0:10:00|2:00:00|1|gres/shard:1|1:50:00\n"
        "103|queued-c|hassan|PENDING|gpu|0:00|1:00:00|1|gres/shard:1|1:00:00\n")
    (agent.dir / "runuser.out").write_text("== resize applied: pod count is now 4\n")
    (agent.dir / "runuser.rc").write_text("0")

    def run(who, argv, *, input=None, timeout=60, cwd=None, env=None):
        return subprocess.run(argv, input=input, capture_output=True, timeout=timeout)

    monkeypatch.setattr(admin_mod, "_ops_identity", lambda ctx: _ident("sd-ops"))
    monkeypatch.setattr(admin_mod, "run_as", run)
    return agent


def call(agent, verb, payload=None, as_="admin:dinuka"):
    return agent.call(verb, payload, as_=as_)


def status(agent, verb, payload=None, as_="admin:dinuka"):
    with pytest.raises(AgentCallError) as e:
        agent.call(verb, payload, as_=as_)
    return e.value


def test_every_verb_is_admin_only(admin):
    for verb in ("admin.qos_list", "admin.pods", "admin.service_status"):
        assert status(admin, verb, as_="user:amasha").status == 403


def test_qos_list_reads_limits(admin):
    normal = call(admin, "admin.qos_list")["qos"][0]
    assert normal == {"name": "normal", "max_wall_s": 28800, "max_pods_per_user": 4,
                      "max_gpus_per_user": 10, "priority": 10}


def test_qos_edit_preserves_other_tres(admin):
    call(admin, "admin.qos_set", {"name": "normal", "field": "max_pods_per_user", "value": 6})
    assert "set MaxTRESPerUser=gres/gpu=10,gres/shard=6" in admin.calls()
    call(admin, "admin.qos_set", {"name": "normal", "field": "max_pods_per_user", "value": None})
    assert "set MaxTRESPerUser=gres/gpu=10\n" in admin.calls()
    call(admin, "admin.qos_set", {"name": "normal", "field": "max_wall", "value": 90000})
    assert "set MaxWall=1-01:00:00" in admin.calls()
    nope = {"name": "nope", "field": "priority", "value": 1}
    assert status(admin, "admin.qos_set", nope).status == 404
    assert status(admin, "admin.qos_set", {**nope, "name": "normal", "field": "x"}).status == 422


def test_drain_needs_a_reason_and_can_cancel_running_jobs(admin):
    assert status(admin, "admin.drain", {"node": "gpu1", "reason": "  "}).status == 422
    assert status(admin, "admin.drain", {"node": "other", "reason": "x"}).status == 422
    args = {"node": "gpu1", "reason": "driver update", "cancel_running": True}
    r = call(admin, "admin.drain", args)
    assert r["cancelled"] == ["101"]
    assert "scancel 101" in admin.calls()
    assert "scontrol update nodename=gpu1 state=drain reason=driver update" in admin.calls()
    call(admin, "admin.resume", {"node": "gpu1"})
    assert "state=resume" in admin.calls()


def test_pod_grid_shows_which_job_holds_each_pod(admin):
    r = call(admin, "admin.pods")
    assert r["pods_total"] == 8
    assert [(p["job_id"], p["user"]) for p in r["pods"][:4]] == [
        ("101", "amasha"), ("101", "amasha"), ("102", "hassan"), (None, None)]
    assert [f["n"] for f in r["fits"]] == list(range(1, 9))


def test_resize_is_refused_while_jobs_are_active_and_passes_the_scripts_words_through(admin):
    assert status(admin, "admin.pods_resize", {"n": 4}).code == "queue_busy"
    (admin.dir / "squeue.out").write_text("")
    assert call(admin, "admin.pods_resize", {"n": 4})["output"].endswith("pod count is now 4")
    assert "runuser -u slurmadmin -- " in admin.calls()
    refusal = "ERROR: GPU host reports 'shard:8', expected 'shard:4'\n"
    (admin.dir / "runuser.out").write_text(refusal)
    (admin.dir / "runuser.rc").write_text("1")
    e = status(admin, "admin.pods_resize", {"n": 4})
    assert e.code == "resize_failed" and "GPU host reports 'shard:8'" in str(e)
    assert e.data == {"exit_code": 1}
    assert status(admin, "admin.pods_resize", {"n": 0}).status == 422


def test_publish_refuses_an_existing_name_unless_replace_is_chosen(admin):
    src = admin.dir / "shared/users/amasha/llama"
    src.mkdir(parents=True)
    (admin.dir / "shared/models").mkdir()
    (src / "w.bin").write_text("one")
    args = {"src": str(src), "area": "models", "name": "llama"}
    out = call(admin, "admin.publish_shared", args)
    assert (admin.dir / "shared/models/llama/w.bin").read_text() == "one"
    assert out["path"].endswith("/shared/models/llama")
    (src / "w.bin").write_text("two")
    assert status(admin, "admin.publish_shared", args).status == 409
    call(admin, "admin.publish_shared", {**args, "replace": True})
    assert (admin.dir / "shared/models/llama/w.bin").read_text() == "two"
    call(admin, "admin.unpublish_shared", {"area": "models", "name": "llama"})
    assert not (admin.dir / "shared/models/llama").exists()


def test_publish_copies_without_setuid_or_setgid_bits(admin):
    # deck-agent runs with RestrictSUIDSGID=yes, so a copy that kept the setgid
    # bit of a user's folder (2770) would be refused; modes go through the umask.
    src = admin.dir / "shared/users/amasha/env"
    (src / "bin").mkdir(parents=True)
    (admin.dir / "shared/envs").mkdir()
    (src / "bin/run").write_text("#!/bin/sh\n")
    (src / "bin/run").chmod(0o4755)
    (src / "bin").chmod(0o2770)
    src.chmod(0o2770)
    call(admin, "admin.publish_shared", {"src": str(src), "area": "envs", "name": "env"})
    dest = admin.dir / "shared/envs/env"
    for path in (dest, dest / "bin", dest / "bin/run"):
        assert path.stat().st_mode & 0o6000 == 0, path
    assert (dest / "bin/run").stat().st_mode & 0o111 == 0o111   # still runnable


def test_publish_that_cannot_read_the_source_publishes_nothing(admin):
    if os.geteuid() == 0:
        pytest.skip("root reads everything")
    src = admin.dir / "shared/users/amasha/half"
    src.mkdir(parents=True)
    (admin.dir / "shared/models").mkdir()
    (src / "a").write_text("a")
    (src / "secret").write_text("b")
    (src / "secret").chmod(0)
    args = {"src": str(src), "area": "models", "name": "half"}
    assert status(admin, "admin.publish_shared", args).code == "publish_failed"
    assert not (admin.dir / "shared/models/half").exists()


def test_publish_rejects_a_source_outside_user_areas_and_bad_names(admin):
    ok = {"area": "models", "name": "x"}
    assert status(admin, "admin.publish_shared", {**ok, "src": "/etc/passwd"}).status == 422
    src = str(admin.dir / "shared/users/amasha/a")
    for area, name in (("users", "x"), ("models", "../x")):
        args = {"src": src, "area": area, "name": name}
        assert status(admin, "admin.publish_shared", args).status == 422


def test_publish_refuses_a_symlinked_folder_on_the_way(admin):
    """users/amasha/link -> users/hassan: publishing amasha/link/secret would copy
    hassan's data into a shared area (SLURM-49 finding 3)."""
    users = admin.dir / "shared/users"
    (users / "hassan/private").mkdir(parents=True)
    (users / "hassan/private/notes.txt").write_text("hassan's")
    (users / "amasha").mkdir(parents=True)
    (users / "amasha/link").symlink_to(users / "hassan")
    (admin.dir / "shared/datasets").mkdir()
    args = {"src": str(users / "amasha/link/private"), "area": "datasets", "name": "p"}
    e = status(admin, "admin.publish_shared", args)
    assert e.status == 422 and e.code == "bad_source"
    assert not (admin.dir / "shared/datasets/p").exists()
    assert not (admin.dir / "shared/datasets/p.new").exists()


def test_publish_refuses_a_source_that_is_itself_a_link(admin):
    users = admin.dir / "shared/users"
    (users / "hassan").mkdir(parents=True)
    (users / "hassan/data.csv").write_text("x")
    (users / "amasha").mkdir(parents=True)
    (users / "amasha/data.csv").symlink_to(users / "hassan/data.csv")
    (users / "amasha/etc").symlink_to("/etc")
    (admin.dir / "shared/datasets").mkdir()
    for src in ("amasha/data.csv", "amasha/etc"):
        args = {"src": str(users / src), "area": "datasets", "name": "d"}
        assert status(admin, "admin.publish_shared", args).code == "bad_source"
    assert not (admin.dir / "shared/datasets/d").exists()


def test_publish_refuses_the_users_folder_itself_or_a_missing_source(admin):
    users = admin.dir / "shared/users"
    users.mkdir(parents=True)
    (admin.dir / "shared/datasets").mkdir()
    for src in (str(users) + "/", str(users / "amasha/nothing-here")):
        args = {"src": src, "area": "datasets", "name": "d"}
        assert status(admin, "admin.publish_shared", args).status == 422


def test_service_status_reports_both_nodes(admin):
    r = call(admin, "admin.service_status")
    assert r["login"]["mariadb"] == "failed" and r["login"]["munge"] == "active"
    assert r["gpu"] == {"slurmd": "active", "munge": "inactive"} and r["gpu_error"] == ""


def test_audit_tail_returns_the_newest_entries_first_and_only_those_after_since(admin):
    log = admin.dir / "audit"
    lines = [f'{{"ts": "2020-01-01T10:0{i}:00+00:00", "verb": "v{i}"}}' for i in range(5)]
    log.write_text("half a line\n" + "\n".join(lines) + "\nnot json\n")

    def seeded(**payload):   # the agent also logs its own calls, which are newer than these
        events = call(admin, "admin.audit_tail", {"limit": 500, **payload})["events"]
        return [e["verb"] for e in events if e["verb"].startswith("v")]

    assert seeded() == ["v4", "v3", "v2", "v1", "v0"]
    assert seeded(since_ts="2020-01-01T10:02:00+00:00") == ["v4", "v3"]
    assert status(admin, "admin.audit_tail", {}, as_="user:amasha").status == 403
