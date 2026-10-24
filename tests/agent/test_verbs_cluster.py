"""cluster.* and job.time_left_all verbs, against fake Slurm commands."""

import pytest

from sdweb.agent import AgentCallError


def test_queue_hides_names_from_other_users(agent):
    jobs = {j["job_id"]: j for j in agent.call("cluster.queue")["jobs"]}
    assert jobs["101"]["name"] == "train-a" and jobs["101"]["pods"] == 2
    assert "name" not in jobs["102"] and jobs["102"]["user"] == "hassan"
    assert jobs["102"]["time_left_s"] == 6600
    admin = agent.call("cluster.queue", as_="admin:dinuka")["jobs"]
    assert all("name" in j for j in admin)
    assert all("name" not in j for j in agent.call("cluster.queue", as_="worker")["jobs"])


def test_status_reads_node_partition_and_stats(agent):
    (agent.dir / "shared" / ".gpu_stats.json").write_text('{"gpu_util": 55}')
    s = agent.call("cluster.status")
    assert (s["pods_total"], s["pods_used"], s["partition_max_s"]) == (8, 3, 86400)
    assert s["node"]["state"] == "MIXED" and s["node"]["gpu_util"] == 55
    assert "scontrol show node gpu1 --oneliner" in agent.calls()


def test_disk_free_and_time_left(agent):
    d = agent.call("cluster.disk_free")
    assert all(isinstance(d[k], int) for k in ("total_bytes", "used_bytes", "free_bytes"))
    assert d["total_bytes"] >= d["free_bytes"] > 0
    jobs = agent.call("job.time_left_all", as_="worker")["jobs"]
    assert {j["job_id"] for j in jobs} == {"101", "102"}
    with pytest.raises(AgentCallError) as e:
        agent.call("job.time_left_all")
    assert e.value.status == 403
