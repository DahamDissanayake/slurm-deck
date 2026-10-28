"""HuggingFace model downloads as CPU jobs.

The token is never part of the script. A gated or private download is given
the token as a 0600 file beside job.sbatch (deck-agent writes it as the user);
the job reads it into HF_TOKEN and deletes the file before anything else runs.
Nothing about a token is stored anywhere: it is used for one download. Ported
from legacy/v1.4-tui slurmdeck/models.py.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

from sdcore.sbatch import EnvChoice, _activate, _clean_env, _directive

TOKEN_FILE = ".hf_token"
AUTH_MESSAGE = "HuggingFace refused the token for this repository."
HF_CPUS, HF_MEM_GB, HF_TIME = 4, 8, "08:00:00"
REPO_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*")
REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,99}")
REASONS = {"auth": AUTH_MESSAGE,
           "not_found": "HuggingFace has no repository with that name."}

# Reads its inputs from the environment, so none of them is ever Python source.
_DOWNLOAD = """\
import os, sys
from huggingface_hub import snapshot_download
try:
    path = snapshot_download(repo_id=os.environ["SD_HF_REPO"], local_dir=os.environ["SD_HF_DEST"],
                             revision=os.environ.get("SD_HF_REVISION") or None, max_workers=4)
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(path) for f in fs)
    print("SD_HF_DONE", size)
except Exception as e:
    code = getattr(getattr(e, "response", None), "status_code", None)
    kind = type(e).__name__
    reason = ("auth" if code in (401, 403) or "Gated" in kind
              else "not_found" if code == 404 or "NotFound" in kind else "failed")
    print("SD_HF_FAIL", reason)
    sys.exit(1)
"""


def valid_repo_id(repo_id: str) -> bool:
    return REPO_ID.fullmatch(repo_id) is not None


def render_hf_download(user: str, folder: str, home: str, *, repo_id: str, dest: str,
                       revision: str | None = None, partition: str = "",
                       nfs_root: str = "/shared") -> str:
    """The sbatch script that downloads repo_id into dest. If a token file
    sits in the job folder it becomes HF_TOKEN, and is deleted first."""
    if not valid_repo_id(repo_id):
        raise ValueError(f"not a HuggingFace repository id: {repo_id!r}")
    if revision and not REVISION.fullmatch(revision):
        raise ValueError(f"not a revision: {revision!r}")
    q = shlex.quote
    lines = ["#!/bin/bash", _directive("job-name", PurePosixPath(folder).name)]
    if partition:
        lines.append(_directive("partition", partition))
    lines += [
        _directive("cpus-per-task", HF_CPUS),
        _directive("mem", f"{HF_MEM_GB}G"),
        _directive("time", HF_TIME),
        _directive("output", f"{folder}/slurm-%j.out"),
        _directive("error", f"{folder}/slurm-%j.err"),
        _directive("chdir", folder),
        *_clean_env(home, user, gpu=False),
        "set +x",   # nothing below may be traced into a log
        f"if [ -f {TOKEN_FILE} ]; then HF_TOKEN=\"$(cat {TOKEN_FILE})\"; export HF_TOKEN; fi",
        f"rm -f {TOKEN_FILE}",
        "export HF_HUB_DISABLE_XET=1",
        f"export SD_HF_REPO={q(repo_id)}",
        f"export SD_HF_DEST={q(dest)}",
        f"export SD_HF_REVISION={q(revision or '')}",
        f"mkdir -p {q(dest)}",
        *_activate(EnvChoice("prebuilt", f"{nfs_root.rstrip('/')}/envs/data-science"), nfs_root),
        "python3 - <<'PYEOF'",
        _DOWNLOAD + "PYEOF",
    ]
    return "\n".join(lines) + "\n"


def explain_hf_failure(reason: str) -> str:
    return REASONS.get(reason, "The download failed. The job log has the details.")


def parse_hf_result(out_text: str) -> tuple[str, int | None, str]:
    """(state, bytes, message) from a download job's output: state is done,
    failed or unknown (not finished, or it stopped without saying)."""
    for line in out_text.splitlines():
        parts = line.strip().split()
        if len(parts) == 2 and parts[0] == "SD_HF_DONE" and parts[1].isdigit():
            return "done", int(parts[1]), ""
        if len(parts) == 2 and parts[0] == "SD_HF_FAIL":
            return "failed", None, explain_hf_failure(parts[1])
    return "unknown", None, ""
