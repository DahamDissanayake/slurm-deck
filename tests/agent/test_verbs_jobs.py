"""job.* verbs, qos.limits and joblog.read, with fake Slurm commands that keep
job state in files, and run_as replaced by a recorder (tests aren't root)."""

import subprocess
import threading

import pytest

from sdweb.agent import AgentCallError, AgentClient

SCONTROL = r'''#!/bin/sh
echo "scontrol $*" >> "$FAKE_DIR/fake.log"
case "$1 $2" in
"show job")
  [ -f "$FAKE_DIR/job.$3" ] || { echo "Invalid job id specified" >&2; exit 1; }
  . "$FAKE_DIR/job.$3"
  echo "JobId=$3 JobName=train UserId=$OWNER(2001) JobState=$STATE Partition=gpu" \
       "TimeLimit=$LIMIT RunTime=01:00:00 WorkDir=$OUT StdOut=$OUT/slurm-$3.out" \
       "StdErr=$OUT/slurm-$3.err NodeList=gpu1 ExitCode=0:0";;
"show partition") echo "PartitionName=gpu MaxTime=1-04:00:00 State=UP";;
update*)
  id=${2#JobId=}; limit=${3#TimeLimit=}
  sleep 0.2
  sed -i "s/^LIMIT=.*/LIMIT=$limit/" "$FAKE_DIR/job.$id";;
esac
'''
SACCTMGR = r'''#!/bin/sh
echo "sacctmgr $*" >> "$FAKE_DIR/fake.log"
case "$*" in *"show assoc"*) echo "normal";; *"show qos"*) echo "08:00:00|cpu=8,gres/shard=4";; esac
'''
SBATCH = '#!/bin/sh\necho "sbatch $*" >> "$FAKE_DIR/fake.log"\necho "512;cluster"\n'
GOOD = "#!/bin/bash\n#SBATCH --job-name=train\n#SBATCH --gres=shard:1\npython3 train.py\n"


@pytest.fixture
def jobs(agent, monkeypatch):
    from deckagent import slurmcmd
    from deckagent.identity import PosixIdentity
    from deckagent.verbs import files
    from deckagent.verbs import jobs as jobs_mod

    for name, body in (("scontrol", SCONTROL), ("sacctmgr", SACCTMGR), ("sbatch", SBATCH)):
        (agent.dir / "bin" / name).write_text(body)
    ran: list[tuple[str, str]] = []

    def ident(name):
        return PosixIdentity(name, 2001, 2001, (), f"/home/{name}")

    def fake_run_as(who, argv, *, input=None, timeout=60, cwd=None, env=None):
        ran.append((who.name, argv[0].rsplit("/", 1)[-1]))
        return subprocess.run(argv, input=input, capture_output=True, timeout=timeout)

    def fake_spawn(who, argv, **kw):
        ran.append((who.name, "fsops"))
        return subprocess.Popen(argv, **kw)

    monkeypatch.setattr(jobs_mod, "_identity", lambda caller, config: ident(caller.username))
    monkeypatch.setattr(jobs_mod, "_ops_identity", lambda caller, config: ident("sd-ops"))
    monkeypatch.setattr(jobs_mod, "run_as", fake_run_as)
    monkeypatch.setattr(slurmcmd, "run_as", fake_run_as)
    monkeypatch.setattr(files, "_spawn", fake_spawn)
    (agent.dir / "shared/jobs/amasha").mkdir(parents=True)
    agent.ran = ran
    return agent


def job(agent, job_id, owner="amasha", state="RUNNING", limit="22:00:00"):
    out = agent.dir / "shared/jobs" / owner / "train_1"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"slurm-{job_id}.out").write_text("epoch 1\nepoch 2\n")
    (agent.dir / f"job.{job_id}").write_text(
        f"OWNER={owner}\nSTATE={state}\nLIMIT={limit}\nOUT={out}\n")


def _err(agent, verb, payload, as_="user:amasha") -> AgentCallError:
    with pytest.raises(AgentCallError) as e:
        agent.call(verb, payload, as_=as_)
    return e.value


def test_submit_runs_sbatch_as_user_and_returns_id(jobs):
    r = jobs.call("job.submit", {"folder_name": "train_20261023_101500", "script": GOOD})
    assert r["job_id"] == "512" and r["folder"].endswith("jobs/amasha/train_20261023_101500")
    assert ("amasha", "sbatch") in jobs.ran
    assert (jobs.dir / "shared/jobs/amasha/train_20261023_101500/job.sbatch").read_text() == GOOD


@pytest.mark.parametrize("payload", [
    {"folder_name": "x", "script": "#!/bin/bash\n#SBATCH --uid=0\n"},
    {"folder_name": "x", "script": "#!/bin/bash\n#SBATCH --get-user-env\n"},
    {"folder_name": "../x", "script": GOOD},
    {"folder_name": "a b", "script": GOOD},
])
def test_submit_rejects_identity_directives_and_bad_folders(jobs, payload):
    assert _err(jobs, "job.submit", payload).status == 422
    assert "sbatch" not in jobs.calls()


def test_extend_over_cap_refused(jobs):
    job(jobs, "42", limit="22:00:00")
    e = _err(jobs, "job.extend", {"job_id": "42", "hours": 4})
    assert (e.code, e.status, e.data) == ("over_cap", 422, {"total_h": 26, "limit_h": 24})
    assert e.message == "This would take the job to 26 h; the limit is 24 h."
    assert jobs.call("job.extend", {"job_id": "42", "hours": 2}) == {"new_limit_s": 24 * 3600}
    assert _err(jobs, "job.extend", {"job_id": "42", "hours": 3}).status == 422   # not 1/2/4


def test_concurrent_extends_cannot_pass_cap(jobs):
    job(jobs, "43", limit="22:00:00")
    results: list[object] = []

    def extend():
        try:
            results.append(jobs.call("job.extend", {"job_id": "43", "hours": 2}))
        except AgentCallError as e:
            results.append(e.code)

    threads = [threading.Thread(target=extend) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(map(str, results)) == sorted(["over_cap", str({"new_limit_s": 86400})])


def test_admin_may_pass_cap_not_partition_max(jobs):
    job(jobs, "44", limit="22:00:00")
    assert jobs.call("job.extend", {"job_id": "44", "hours": 4}, as_="admin:dinuka") == {
        "new_limit_s": 26 * 3600}
    e = _err(jobs, "job.extend", {"job_id": "44", "hours": 4}, as_="admin:dinuka")
    assert e.data == {"total_h": 30, "limit_h": 28}           # partition MaxTime 1-04:00:00


def test_cancel_and_extend_ended_or_foreign_jobs(jobs):
    job(jobs, "45", state="COMPLETED")
    assert _err(jobs, "job.cancel", {"job_id": "45"}).status == 409
    assert _err(jobs, "job.extend", {"job_id": "99", "hours": 1}).code == "job_ended"
    job(jobs, "46", owner="hassan")
    assert _err(jobs, "job.cancel", {"job_id": "46"}).status == 404
    jobs.call("job.cancel", {"job_id": "46"}, as_="admin:dinuka")
    assert "scancel 46" in jobs.calls()


def test_show_and_list(jobs):
    job(jobs, "47")
    s = jobs.call("job.show", {"job_id": "47"})
    assert (s["owner"], s["state"], s["time_limit_s"], s["node"]) == ("amasha", "RUNNING",
                                                                     22 * 3600, "gpu1")
    assert _err(jobs, "job.show", {"job_id": "47"}, as_="user:hassan").status == 404
    assert jobs.call("job.list")["jobs"][0]["name"] == "train-a"
    assert "squeue --noheader" in jobs.calls() and "-u amasha" in jobs.calls()


def test_other_users_log_is_404(jobs):
    job(jobs, "48")
    assert _err(jobs, "joblog.read", {"job_id": "48", "stream": "out"},
                as_="user:hassan").status == 404


def test_owner_and_admin_read_logs(jobs):
    job(jobs, "49")
    client = AgentClient(jobs.path)
    out = b"".join(client.stream("joblog.read", {"job_id": "49", "stream": "out", "offset": 8},
                                 session="user:amasha"))
    assert out == b"epoch 2\n" and ("amasha", "fsops") in jobs.ran
    jobs.ran.clear()
    b"".join(client.stream("joblog.read", {"job_id": "49", "stream": "out"},
                           session="admin:dinuka"))
    assert ("sd-ops", "fsops") in jobs.ran


def test_history_and_qos(jobs):
    jobs.call("job.history", {"days": 7})
    assert "sacct" in jobs.calls() and ("amasha", "sacct") in jobs.ran
    assert _err(jobs, "job.history", {"days": 7, "all_users": True}).status == 403
    assert jobs.call("qos.limits") == {"max_wall_s": 8 * 3600, "max_pods_per_user": 4}
