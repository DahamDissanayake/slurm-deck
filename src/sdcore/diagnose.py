"""Plain-language explanations for common job failures, read from a job's .err."""

from __future__ import annotations

import re

_OOM_KILL = re.compile(r"oom[_-]kill", re.I)
_GPU_OOM = re.compile(r"CUDA out of memory|CUDACachingAllocator.*out of memory"
                      r"|CUDA error: out of memory")
_NO_MODULE = re.compile(r"ModuleNotFoundError: No module named '([^']+)'")
_TIME_LIMIT = re.compile(r"DUE TO TIME LIMIT")


def explain_failure(err_text: str, *, mem_gb: int, pods: int) -> str | None:
    """One sentence saying why the job failed, or None when it isn't one we know.

    mem_gb and pods are the job's request, used to suggest a bigger one.
    """
    if _OOM_KILL.search(err_text):
        return (f"Out of memory: the job used more than its {mem_gb} GB RAM. "
                f"Try {pods + 1} pods for more memory.")
    if _GPU_OOM.search(err_text):
        return "The GPU ran out of memory. The card is shared, so other jobs' memory counts too."
    if m := _NO_MODULE.search(err_text):
        package = m.group(1).split(".")[0]
        return f"Python package '{package}' isn't in the chosen environment."
    if _TIME_LIMIT.search(err_text):
        return "The job reached its time limit."
    return None
