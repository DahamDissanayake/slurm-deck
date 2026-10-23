"""Pure parsing of squeue / sacct / scontrol output and the GPU stats file."""

from sdcore.slurmparse import (
    SACCT_FORMAT,
    SQUEUE_FORMAT,
    NodeStats,
    merge_gpu_stats,
    parse_sacct,
    parse_scontrol_node,
    parse_slurm_duration,
    parse_squeue,
)


def base_stats() -> NodeStats:
    return NodeStats(state="MIXED", cpu_load=0.0, cpu_total=32, cpu_alloc=0,
                     mem_total_mb=62000, mem_alloc_mb=0, gpu_total=1, gpu_alloc=0,
                     shard_total=4, shard_alloc=0)


# ── squeue ───────────────────────────────────────────────────────────────────

def test_squeue_format_matches_the_parser():
    assert SQUEUE_FORMAT == "%i|%j|%u|%T|%P|%M|%l|%D|%b|%L"


def test_parse_squeue_reads_pods_and_time_left():
    line = "42|nb_1|amasha|RUNNING|gpu|1:00:00|8:00:00|1|gres/shard:2|7:00:00"
    e = parse_squeue(line)[0]
    assert (e.job_id, e.user, e.state, e.pods, e.time_left_s) == (
        "42", "amasha", "RUNNING", 2, 25200)
    assert (e.name, e.partition, e.time_used, e.time_limit, e.nodes) == (
        "nb_1", "gpu", "1:00:00", "8:00:00", 1)


def test_parse_squeue_no_gres_means_zero_pods():
    e = parse_squeue("7|cpu_job|u|PENDING|gpu|0:00|1:00:00|1|N/A|1:00:00")[0]
    assert e.pods == 0
    assert e.time_left_s == 3600


def test_parse_squeue_accepts_older_gres_spellings():
    a = parse_squeue("1|a|u|RUNNING|gpu|0:01|1:00:00|1|gres:shard:3|59:59")[0]
    b = parse_squeue("2|b|u|RUNNING|gpu|0:01|1:00:00|1|shard:1|59:59")[0]
    assert (a.pods, b.pods) == (3, 1)


def test_parse_squeue_unlimited_time_left_is_none():
    e = parse_squeue("3|a|u|RUNNING|gpu|0:01|UNLIMITED|1|gres/shard:1|UNLIMITED")[0]
    assert e.time_left_s is None


def test_parse_squeue_skips_short_and_blank_lines():
    text = "\n9|a|u|RUNNING\n4|b|u|RUNNING|gpu|0:01|1:00:00|1|N/A|59:59\n"
    assert [e.job_id for e in parse_squeue(text)] == ["4"]


# ── sacct ────────────────────────────────────────────────────────────────────

def _sacct_rows(*rows: tuple[str, str, str, str, str]) -> str:
    """parsable2 rows of (jobid, name, user, state, elapsed)."""
    return "\n".join(
        f"{jid}|{name}|{user}|{state}|{elapsed}|2026-05-30T10:00:00|2026-05-30T11:00:00"
        f"|gres/gpu=1|0:0"
        for jid, name, user, state, elapsed in rows
    )


def test_sacct_format_matches_the_parser():
    assert SACCT_FORMAT == "JobID,JobName,User,State,Elapsed,Start,End,AllocTRES,ExitCode"


def test_parse_sacct_strips_steps_and_suffixes():
    text = ("10|a|u|CANCELLED by 1500|0:05|...|...|...|0:0\n"
            "10.batch|batch|u|CANCELLED|0:05|...|...|...|0:15")
    rows = parse_sacct(text)
    assert [r.state for r in rows] == ["CANCELLED"]


def test_parse_sacct_parses_completed_jobs_newest_first():
    rows = parse_sacct(_sacct_rows(
        ("100", "train", "daham", "COMPLETED", "01:00:00"),
        ("101", "infer", "daham", "FAILED", "00:10:00"),
    ))
    assert [(r.job_id, r.state) for r in rows] == [("101", "FAILED"), ("100", "COMPLETED")]
    assert rows[1].name == "train" and rows[1].user == "daham"
    assert rows[1].time_used == "01:00:00"


def test_parse_sacct_keeps_terminal_states_only():
    rows = parse_sacct(_sacct_rows(
        ("10", "done", "daham", "COMPLETED", "00:05:00"),
        ("11", "run", "daham", "RUNNING", "00:01:00"),
        ("12", "wait", "daham", "PENDING", "00:00:00"),
        ("13", "oom", "daham", "OUT_OF_MEMORY", "00:02:00"),
    ))
    assert {r.job_id for r in rows} == {"10", "13"}


def test_parse_sacct_reads_pods_from_alloc_tres():
    text = "5|nb|u|COMPLETED|00:05:00|s|e|billing=8,cpu=8,gres/shard=2,mem=14G,node=1|0:0"
    assert parse_sacct(text)[0].pods == 2


def test_parse_sacct_does_not_invent_a_partition():
    # sacct output carries no partition; the legacy code hardcoded "gpu".
    assert parse_sacct(_sacct_rows(("1", "a", "u", "COMPLETED", "0:01")))[0].partition == ""


def test_parse_sacct_empty_name_falls_back_to_job_id():
    assert parse_sacct("8||u|COMPLETED|0:01|s|e||0:0")[0].name == "8"


# ── durations ────────────────────────────────────────────────────────────────

def test_parse_slurm_duration():
    assert parse_slurm_duration("1-02:03:04") == 93784
    assert parse_slurm_duration("03:04") == 184
    assert parse_slurm_duration("UNLIMITED") is None


def test_parse_slurm_duration_other_shapes():
    assert parse_slurm_duration("02:03:04") == 7384
    assert parse_slurm_duration("5") == 300          # bare minutes
    assert parse_slurm_duration("2-03") == 2 * 86400 + 3 * 3600
    assert parse_slurm_duration("2-03:04") == 2 * 86400 + 3 * 3600 + 4 * 60
    assert parse_slurm_duration(" 0:00 ") == 0


def test_parse_slurm_duration_rejects_junk():
    for text in ("INVALID", "NOT_SET", "N/A", "", "abc", "1:2:3:4", "1-", "-5:00", "1:xx"):
        assert parse_slurm_duration(text) is None, text


# ── scontrol show node ───────────────────────────────────────────────────────

SCONTROL = (
    "NodeName=gpu-node-1 Arch=x86_64 CoresPerSocket=16 CPUAlloc=8 CPUEfctv=32 CPUTot=32 "
    "CPULoad=1.50 AvailableFeatures=(null) Gres=gpu:rtx:1(S:0),shard:rtx:4(S:0) "
    "RealMemory=62000 AllocMem=14336 State=MIXED+DRAIN ThreadsPerCore=1 "
    "CfgTRES=cpu=32,mem=62000M,billing=32,gres/gpu=1,gres/shard=4 "
    "AllocTRES=cpu=8,mem=14G,gres/shard=1"
)


def test_parse_scontrol_node_reads_allocation():
    s = parse_scontrol_node(SCONTROL)
    assert s is not None
    assert (s.state, s.cpu_total, s.cpu_alloc, s.cpu_load) == ("MIXED", 32, 8, 1.5)
    assert (s.mem_total_mb, s.mem_alloc_mb) == (62000, 14 * 1024)
    assert (s.shard_total, s.shard_alloc, s.gpu_alloc) == (4, 1, 1)
    assert s.live_stats is False


def test_parse_scontrol_node_counts_gpus_with_socket_suffix():
    # The legacy parser read "gpu:rtx:1(S:0)" as 0 GPUs (it took the socket index).
    s = parse_scontrol_node(SCONTROL)
    assert s is not None and s.gpu_total == 1


def test_parse_scontrol_node_without_shards_reads_whole_gpus():
    text = ("NodeName=n1 CPUTot=16 CPUAlloc=0 CPULoad=0.00 Gres=gpu:2 RealMemory=1000 "
            "State=IDLE AllocTRES=gres/gpu=1,mem=512M")
    s = parse_scontrol_node(text)
    assert s is not None
    assert (s.gpu_total, s.gpu_alloc, s.shard_total, s.mem_alloc_mb) == (2, 1, 0, 512)


def test_parse_scontrol_node_none_for_empty_or_unknown_output():
    assert parse_scontrol_node("") is None
    assert parse_scontrol_node("Node gpu-x not found") is None


# ── GPU stats file ───────────────────────────────────────────────────────────

LIVE = {"gpu_util": 90, "gpu_mem_used_mb": 1000, "gpu_mem_total_mb": 24576,
        "gpu_temp": 60, "gpu_power_w": 120.5, "cpu_util": 30, "cpu_load5": 2.5,
        "mem_used_mb": 20000}


def test_stale_gpu_stats_ignored():
    s = merge_gpu_stats(base_stats(), {"gpu_util": 90}, now=1000.0, mtime=980.0)
    assert s.live_stats is False and s.gpu_util == 0


def test_fresh_gpu_stats_merged():
    s = merge_gpu_stats(base_stats(), LIVE, now=1000.0, mtime=995.0)
    assert s.live_stats is True
    assert (s.gpu_util, s.gpu_mem_total_mb, s.gpu_power_w, s.mem_used_mb) == (
        90, 24576, 120.5, 20000)


def test_merge_gpu_stats_does_not_mutate_its_input():
    stats = base_stats()
    merge_gpu_stats(stats, LIVE, now=1000.0, mtime=1000.0)
    assert stats.live_stats is False and stats.gpu_util == 0


def test_merge_gpu_stats_without_data_is_unchanged():
    assert merge_gpu_stats(base_stats(), None, now=1000.0).live_stats is False
    assert merge_gpu_stats(base_stats(), {}, now=1000.0).live_stats is False


def test_merge_gpu_stats_bad_values_fall_back_to_zero():
    s = merge_gpu_stats(base_stats(), {"gpu_util": "hot", "gpu_temp": None},
                        now=1000.0, mtime=1000.0)
    assert s.live_stats is True and s.gpu_util == 0 and s.gpu_temp == 0
