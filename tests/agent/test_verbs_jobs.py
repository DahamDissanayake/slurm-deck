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
  [ "$4" = "--json" ] || { echo "only --json is faked" >&2; exit 1; }
  mins=$(echo "$LIMIT" | awk -F'[-:]' '{ print (NF == 4) ? $1*1440 + $2*60 + $3 : $1*60 + $2 }')
  n() { printf '{"set":true,"infinite":false,"number":%s}' "$1"; }
  printf '{"jobs":[{"job_id":%s,"name":"train","user_name":"%s","user_id":2001,' "$3" "$OWNER"
  printf '"job_state":["%s"],"partition":"gpu","time_limit":%s,"start_time":%s,' \
         "$STATE" "$(n "$mins")" "$(n $(( $(date +%s) - 3600 )))"
  printf '"end_time":%s,"suspend_time":%s,"pre_sus_time":%s,' "$(n 0)" "$(n 0)" "$(n 0)"
  printf '"current_working_directory":"%s","standard_output":"%s/slurm-%%j.out",' \
         "${WORKDIR:-$OUT}" "$OUT"
  printf '"stdout_expanded":"%s/slurm-%s.out","standard_error":"%s/slurm-%%j.err",' \
         "$OUT" "$3" "$OUT"
  printf '"stderr_expanded":"%s/slurm-%s.err","nodes":"gpu1",' "$OUT" "$3"
  printf '"exit_code":{"status":["SUCCESS"],"return_code":%s,' "$(n 0)"
  printf '"signal":{"id":{"set":false,"infinite":false,"number":0},"name":""}}}]}\n';;
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


def job(agent, job_id, owner="amasha", state="RUNNING", limit="22:00:00", workdir=None):
    out = agent.dir / "shared/jobs" / owner / "train_1"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"slurm-{job_id}.out").write_text("epoch 1\nepoch 2\n")
    extra = f"WORKDIR='{workdir}'\n" if workdir else ""
    (agent.dir / f"job.{job_id}").write_text(
        f"OWNER={owner}\nSTATE={state}\nLIMIT={limit}\nOUT={out}\n{extra}")


def _err(agent, verb, payload, as_="user:amasha") -> AgentCallError:
    with pytest.raises(AgentCallError) as e:
        agent.call(verb, payload, as_=as_)
    return e.value


def test_submit_runs_sbatch_as_user_and_returns_id(jobs):
    r = jobs.call("job.submit", {"folder_name": "train_20261023_101500", "script": GOOD})
    assert r["job_id"] == "512" and r["folder"].endswith("jobs/amasha/train_20261023_101500")
    assert ("amasha", "sbatch") in jobs.ran
    assert (jobs.dir / "shared/jobs/amasha/train_20261023_101500/job.sbatch").read_text() == GOOD


def test_submit_writes_the_tbguard_extra_file(jobs):
    jobs.call("job.submit", {"folder_name": "tb_1", "script": GOOD,
                             "extra_files": {"tbguard.py": "print('guard')\n"}})
    assert (jobs.dir / "shared/jobs/amasha/tb_1/tbguard.py").read_text() == "print('guard')\n"


@pytest.mark.parametrize("extra", [{"evil.sh": "x"}, {"../tbguard.py": "x"},
                                   {"tbguard.py": 5}, {"tbguard.py": "x" * 70_000}])
def test_submit_refuses_other_extra_files(jobs, extra):
    e = _err(jobs, "job.submit", {"folder_name": "tb_2", "script": GOOD, "extra_files": extra})
    assert (e.status, e.code) == (422, "bad_extra_file")
    assert "sbatch" not in jobs.calls()


@pytest.mark.parametrize("payload", [
    {"folder_name": "x", "script": "#!/bin/bash\n#SBATCH --uid=0\n"},
    {"folder_name": "x", "script": "#!/bin/bash\n#SBATCH --get-user-env\n"},
    {"folder_name": "../x", "script": GOOD},
    {"folder_name": "a b", "script": GOOD},
])
def test_submit_rejects_identity_directives_and_bad_folders(jobs, payload):
    assert _err(jobs, "job.submit", payload).status == 422
    assert "sbatch" not in jobs.calls()


def _mail(address):
    return GOOD.replace("python3", f"#SBATCH --mail-user={address}\npython3")


def test_submit_accepts_mail_user_equal_to_the_account_email(jobs):
    r = jobs.call("job.submit", {"folder_name": "mail_1", "script": _mail("Amasha@Example.org")})
    assert r["job_id"] == "512" and ("amasha", "sbatch") in jobs.ran


def test_submit_refuses_mail_user_for_another_address(jobs):
    e = _err(jobs, "job.submit", {"folder_name": "mail_2", "script": _mail("eve@example.org")})
    assert (e.status, e.code) == (422, "bad_script")
    assert "registered address (amasha@example.org)" in e.message
    assert "sbatch" not in jobs.calls()


def test_submit_refuses_mail_user_when_the_account_has_no_email(jobs):
    jobs.store.emails["amasha"] = None
    e = _err(jobs, "job.submit", {"folder_name": "mail_3", "script": _mail("amasha@example.org")})
    assert (e.status, e.code) == (422, "bad_script") and "cannot be verified" in e.message
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


def test_show_reads_structured_json(jobs):
    job(jobs, "50")
    s = jobs.call("job.show", {"job_id": "50"})
    assert "scontrol show job 50 --json" in jobs.calls()
    assert s["std_out"].endswith("/train_1/slurm-50.out")      # the expanded path, not %j
    assert s["std_err"].endswith("/train_1/slurm-50.err")
    assert 3590 <= s["run_time_s"] <= 3700 and s["exit_code"] == "0:0"


def test_injected_workdir_keeps_the_real_owner(jobs):
    """A WorkDir that looks like more scontrol fields can't change the owner or state."""
    fake = "/tmp/x UserId=hassan(2002) JobState=COMPLETED NodeList=evil StdOut=/etc/shadow"
    job(jobs, "51", owner="amasha", workdir=fake)
    s = jobs.call("job.show", {"job_id": "51"})
    assert (s["owner"], s["state"], s["node"], s["work_dir"]) == ("amasha", "RUNNING", "gpu1",
                                                                 fake)
    assert s["std_out"].endswith("/train_1/slurm-51.out")
    assert _err(jobs, "job.show", {"job_id": "51"}, as_="user:hassan").status == 404
    assert _err(jobs, "job.cancel", {"job_id": "51"}, as_="user:hassan").status == 404


def test_job_fields_from_older_and_newer_json_shapes():
    from deckagent.verbs.jobs import _job_fields

    old = {"job_id": 7, "user_name": "amasha", "job_state": "SUSPENDED", "partition": "gpu",
           "time_limit": 90, "start_time": 1000, "end_time": 0, "suspend_time": 2000,
           "pre_sus_time": 600, "current_working_directory": "/w",
           "standard_output": "/w/slurm-%j.out", "standard_error": "/w/%x-%A_%a.err",
           "name": "train", "array_job_id": 7, "array_task_id": 3, "nodes": "gpu1",
           "exit_code": 256}
    f = _job_fields(old, now=5000)
    assert (f["owner"], f["state"], f["time_limit_s"], f["run_time_s"]) == (
        "amasha", "SUSPENDED", 5400, 600)
    assert f["std_out"] == "/w/slurm-7.out" and f["std_err"] == "/w/train-7_3.err"
    assert f["exit_code"] == "1:0"
    new = {"user_name": "amasha", "job_state": ["RUNNING", "COMPLETING"],
           "time_limit": {"set": True, "infinite": True, "number": 0},
           "start_time": {"set": True, "infinite": False, "number": 1000},
           "suspend_time": {"set": True, "infinite": False, "number": 0},
           "exit_code": {"status": ["SIGNALED"], "return_code": {"set": True, "number": 0},
                         "signal": {"id": {"set": True, "number": 9}, "name": "KILL"}}}
    f = _job_fields(new, now=4600)
    assert (f["state"], f["time_limit_s"], f["run_time_s"], f["exit_code"]) == (
        "RUNNING", None, 3600, "0:9")


def test_text_output_is_not_trusted(jobs):
    (jobs.dir / "bin" / "scontrol").write_text('#!/bin/sh\necho "JobId=52 UserId=amasha(1)"\n')
    assert _err(jobs, "job.show", {"job_id": "52"}).status == 404


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
