"""Launch specs: sizing from live pods, defaults per intent, templates, re-runs.

Ported from legacy/v1.4-tui tests/test_launchspec.py. The TUI-only wording
helpers (pod_label, availability lines) and the recent-scripts scan were not
ported, nor were their tests.
"""

from sdcore.launchspec import (
    LaunchSpec,
    apply_pods,
    default_spec,
    from_rerun,
    from_template,
    to_job_spec,
)
from sdcore.slurmparse import NodeStats

NODE_CPUS = 32
NODE_MEM_GB = 60


def _stats(free: int, shard_total: int = 4) -> NodeStats:
    return NodeStats(state="MIXED", cpu_load=0.0, cpu_total=32, cpu_alloc=0,
                     mem_total_mb=62000, mem_alloc_mb=0, gpu_total=1, gpu_alloc=0,
                     shard_total=shard_total, shard_alloc=shard_total - free)


def test_apply_pods_sizes_from_live_stats():
    ls = LaunchSpec(intent="batch")
    apply_pods(ls, 2, _stats(free=4))
    assert (ls.gpu_shards, ls.cpus, ls.mem_gb) == (2, 16, 28)


def test_apply_pods_clamps_to_pod_count():
    ls = LaunchSpec(intent="batch")
    apply_pods(ls, 9, _stats(free=4))
    assert ls.gpu_shards == 4


def test_apply_pods_keeps_sane_defaults_when_the_pod_count_is_unknown():
    ls = LaunchSpec(intent="batch")           # dataclass defaults: 8 CPU / 14 GB
    apply_pods(ls, 1, None)
    assert (ls.cpus, ls.mem_gb, ls.gpu_shards) == (8, 14, 1)
    ls2 = LaunchSpec(intent="batch", cpus=16, mem_gb=60)
    apply_pods(ls2, 2, _stats(free=0, shard_total=0))
    assert (ls2.cpus, ls2.mem_gb) == (16, 60)


def test_default_time_is_eight_hours():
    assert default_spec("notebook", None).time_limit == "08:00:00"
    assert LaunchSpec(intent="batch").time_limit == "08:00:00"


def test_default_spec_without_stats_is_pod_sized_not_degenerate():
    ls = default_spec("notebook", None)
    assert (ls.gpu_shards, ls.cpus, ls.mem_gb) == (1, 8, 14)


def test_default_spec_with_live_stats_uses_the_live_numbers():
    ls = default_spec("batch", _stats(free=4, shard_total=8))
    assert (ls.cpus, ls.mem_gb) == (4, 7)     # 32//8 CPU, (60-2)//8 GB


def test_a_full_cards_worth_of_one_pod_jobs_fits_the_node():
    stats = _stats(free=4)
    ls = LaunchSpec(intent="notebook")
    apply_pods(ls, 1, stats)
    n = stats.shard_total // ls.gpu_shards
    assert ls.cpus * n <= NODE_CPUS and ls.mem_gb * n <= NODE_MEM_GB


def test_default_specs_per_intent():
    stats = _stats(free=4)
    for intent in ("notebook", "batch", "terminal"):
        ls = default_spec(intent, stats)
        assert (ls.intent, ls.gpu_shards, ls.time_limit) == (intent, 1, "08:00:00")
    assert default_spec("batch", stats, default_time="04:00:00").time_limit == "04:00:00"
    smoke = default_spec("smoke", stats)
    assert (smoke.gpu_shards, smoke.time_limit) == (1, "00:10:00")


def test_apply_pods_then_change_pods_updates_sizing():
    ls = default_spec("batch", _stats(free=4))
    apply_pods(ls, 4, _stats(free=4))
    assert (ls.gpu_shards, ls.cpus, ls.mem_gb) == (4, 32, 56)
    apply_pods(ls, 1, _stats(free=4))
    assert (ls.gpu_shards, ls.cpus, ls.mem_gb) == (1, 8, 14)


def test_to_job_spec_maps_fields():
    ls = default_spec("batch", None)
    ls.conda_env = "/shared/envs/data-science"
    ls.data_path = "/shared/data/cifar10"
    ls.array = "0-3"
    ls.dependency = "afterok:12"
    js = to_job_spec(ls, user="u", partition="gpu", job_name="train",
                     run_command="python3 x.py")
    assert (js.gpu_shards, js.cpus, js.mem_gb) == (ls.gpu_shards, ls.cpus, ls.mem_gb)
    assert js.conda_env == ls.conda_env and js.data_path == ls.data_path
    assert js.array == "0-3" and js.dependency == "afterok:12"
    assert js.time_limit == "08:00:00" and js.user == "u" and js.task_type == "custom"
    assert to_job_spec(default_spec("smoke", None), user="u", partition="gpu",
                       job_name="smoke", run_command="true").task_type == "smoke"


def test_from_template_maps_task_type_and_nearest_size():
    ls = from_template({"task_type": "notebook", "gpu_shards": 1, "cpus": 8, "mem_gb": 14,
                        "time_limit": "06:00:00", "conda_env": "/shared/envs/data-science"},
                       None)
    assert ls.intent == "notebook"
    assert ls.time_limit == "06:00:00" and ls.conda_env.endswith("data-science")
    ls2 = from_template({"task_type": "train", "gpu_shards": 4, "cpus": 16, "mem_gb": 60}, None)
    assert ls2.intent == "batch" and ls2.gpu_shards == 4
    ls3 = from_template({"task_type": "custom", "gpu_shards": 1, "cpus": 6, "mem_gb": 20}, None)
    assert ls3.cpus == 6


def test_from_template_maps_an_interactive_template_to_a_terminal():
    ls = from_template({"task_type": "interactive", "gpu_shards": 1, "cpus": 8,
                        "mem_gb": 14, "time_limit": "02:00:00"}, None)
    assert ls.intent == "terminal" and ls.time_limit == "02:00:00"


def test_from_rerun_uses_parsed_resources():
    ls = from_rerun({"gpu_shards": 1, "cpus": 4, "mem_gb": 8,
                     "time_limit": "01:00:00", "array": "0-9"}, "/p/s.py", None)
    assert ls.intent == "batch" and ls.script == "/p/s.py"
    assert ls.cpus == 4 and ls.array == "0-9" and ls.time_limit == "01:00:00"


def test_from_rerun_carries_environment_data_and_args():
    ls = from_rerun({"gpu_shards": 4, "cpus": 16, "mem_gb": 60,
                     "conda_env": "/shared/envs/pytorch-cifar",
                     "data_path": "/shared/users/alice/data",
                     "extra_args": "--epochs 10 --lr 3e-4"},
                    "/shared/users/alice/train.py", None)
    assert ls.conda_env == "/shared/envs/pytorch-cifar" and ls.env_kind == "conda"
    assert ls.data_path == "/shared/users/alice/data"
    assert ls.args == "--epochs 10 --lr 3e-4"


def test_from_rerun_carries_a_container_image():
    ls = from_rerun({"container_image": "/shared/images/llm.sif"}, "/p/s.py", None)
    assert ls.container_image == "/shared/images/llm.sif"
    assert ls.env_kind == "container" and ls.conda_env == ""
