"""Plain-language explanations for failed jobs, from real .err lines."""

from sdcore.diagnose import explain_failure

OOM_KILL = ("slurmstepd: error: Detected 1 oom_kill event in StepId=518.batch. "
            "Some of the step tasks have been OOM Killed.")
GPU_OOM = ("RuntimeError: CUDA error: out of memory\n"
           "  File \"train.py\", line 40\n"
           "CUDACachingAllocator.cpp:1105] Tried to allocate 2.00 GiB "
           "(GPU 0; 23.64 GiB total capacity) out of memory")
TORCH_OOM = "torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.50 GiB."
NO_MODULE = ("Traceback (most recent call last):\n  File \"run.py\", line 3, in <module>\n"
             "ModuleNotFoundError: No module named 'tensorboard'")
TIME_LIMIT = ("slurmstepd: error: *** JOB 152 ON gpu-node CANCELLED AT "
              "2026-05-30T10:00:00 DUE TO TIME LIMIT ***")


def test_oom_kill_explained():
    assert explain_failure(OOM_KILL, mem_gb=14, pods=1) == (
        "Out of memory: the job used more than its 14 GB RAM. Try 2 pods for more memory.")


def test_gpu_oom_explained():
    msg = "The GPU ran out of memory. The card is shared, so other jobs' memory counts too."
    assert explain_failure(GPU_OOM, mem_gb=14, pods=1) == msg
    assert explain_failure(TORCH_OOM, mem_gb=14, pods=1) == msg


def test_missing_package_explained():
    assert explain_failure(NO_MODULE, mem_gb=14, pods=1) == (
        "Python package 'tensorboard' isn't in the chosen environment.")


def test_dotted_module_names_the_package():
    text = "ModuleNotFoundError: No module named 'torchvision.models'"
    assert "'torchvision'" in (explain_failure(text, mem_gb=8, pods=1) or "")


def test_time_limit_explained():
    assert explain_failure(TIME_LIMIT, mem_gb=14, pods=1) == "The job reached its time limit."


def test_unknown_failure_is_none():
    assert explain_failure("Traceback ...\nValueError: bad shape", mem_gb=14, pods=1) is None
    assert explain_failure("", mem_gb=14, pods=1) is None
