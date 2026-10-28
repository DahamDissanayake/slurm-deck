from sdcore.usage import SacctRow, by_user, parse_usage, summarize

H = 3600


def test_gpu_hours_from_pods():
    # One pod is 1/pods_total of the GPU: 2 of 4 pods for 3 h is half a GPU for 3 h.
    rows = [SacctRow("amasha", "COMPLETED", 3 * H, cpus=8, pods=2)]
    s = summarize(rows, pods_total=4)
    assert s.gpu_hours == 1.5 and s.cpu_hours == 24.0
    assert summarize(rows, pods_total=0).gpu_hours == 0.0   # pod count unknown


def test_jobs_are_counted_by_state():
    rows = [SacctRow("a", "COMPLETED", H, 1, 0)] * 2 + [SacctRow("a", "FAILED", H, 1, 0)]
    assert summarize(rows, 4).jobs_by_state == {"COMPLETED": 2, "FAILED": 1}


def test_parse_usage_reads_sacct_lines():
    text = ("amasha|COMPLETED|10800|billing=8,cpu=8,gres/shard=2,mem=16G\n"
            "amasha|CANCELLED by 1001|60|cpu=1\n"
            "|COMPLETED|5|cpu=1\n"            # no user: skipped
            "hassan|RUNNING|abc|cpu=2\n"       # unreadable time: skipped
            "hassan|FAILED|7200|\n")
    assert parse_usage(text) == [
        SacctRow("amasha", "COMPLETED", 10800, cpus=8, pods=2),
        SacctRow("amasha", "CANCELLED", 60, cpus=1, pods=0),
        SacctRow("hassan", "FAILED", 7200, cpus=1, pods=0),   # at least one CPU
    ]


def test_by_user_groups_and_sorts_by_gpu_hours():
    rows = [SacctRow("amasha", "COMPLETED", H, 2, 1), SacctRow("hassan", "COMPLETED", 2 * H, 2, 4),
            SacctRow("amasha", "FAILED", H, 2, 1)]
    out = by_user(rows, pods_total=4)
    assert [u for u, _ in out] == ["hassan", "amasha"]
    assert out[0][1].gpu_hours == 2.0 and out[1][1].gpu_hours == 0.5
    assert out[1][1].jobs_by_state == {"COMPLETED": 1, "FAILED": 1}
