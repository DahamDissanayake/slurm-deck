"""Prebuilt environment specs and the environment build job.

Ported from legacy/v1.4-tui slurmdeck/setup.py (_parse_spec_pip_deps,
_verify_spec_packages) and slurmdeck/envbuilder.py. A build runs as a CPU-only
Slurm job as the user, installs into the environment itself (never the user
site), keeps its temp and pip cache beside the destination, and finishes by
checking that every requested package is really installed: `conda env create`
can exit 0 with the pip stage skipped.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from sdcore.sbatch import EnvChoice, _activate, _clean_env, _directive

BUILD_CPUS = 8
BUILD_MEM_GB = 16
BUILD_TIME = "04:00:00"


@dataclass(frozen=True)
class EnvSpecInfo:
    name: str
    description: str
    path: str


def list_specs(spec_dir: str) -> list[EnvSpecInfo]:
    """The prebuilt specs in spec_dir; descriptions come from `# description:`."""
    specs = []
    for path in sorted(Path(spec_dir).glob("*.yml")):
        description = ""
        for line in path.read_text().splitlines():
            if line.startswith("# description:"):
                description = line.split(":", 1)[1].strip()
                break
        specs.append(EnvSpecInfo(path.stem, description, str(path)))
    return specs


def parse_pip_deps(spec_text: str) -> list[str]:
    """The pip arguments in a conda spec's `- pip:` block, one token each.

    `--extra-index-url URL` comes back as two tokens, so pip parses it.
    """
    args: list[str] = []
    pip_indent = -1
    for raw in spec_text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if stripped.replace(" ", "") == "-pip:":
            pip_indent = indent
            continue
        if pip_indent >= 0:
            # Items are nested deeper than `- pip:`; anything else ends the block.
            if indent <= pip_indent:
                pip_indent = -1
                continue
            if stripped.startswith("- "):
                args.extend(stripped[2:].split())
    return args


_VALUE_FLAGS = {"--extra-index-url", "--index-url", "-f", "--find-links"}


def top_level_names(deps: list[str]) -> list[str]:
    """Distribution names from pip args: flags (and their values) and version
    pins or extras dropped. `torch==2.7.*` -> `torch`."""
    names = []
    skip = False
    for tok in deps:
        if skip:
            skip = False
            continue
        if tok.startswith("-"):
            skip = tok in _VALUE_FLAGS
            continue
        if name := re.split(r"[<>=!~\[;@ ]", tok, maxsplit=1)[0].strip():
            names.append(name)
    return names


# Run with the environment's python. Names come from SD_ENV_PACKAGES and from
# the requirements file in SD_ENV_REQUIREMENTS, read here as the user.
VERIFY_SNIPPET = """python - <<'PYEOF'
import importlib.metadata as md
import os
import re

names = os.environ.get("SD_ENV_PACKAGES", "").split()
req = os.environ.get("SD_ENV_REQUIREMENTS", "")
if req:
    with open(req) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if line and not line.startswith("-"):
                names.append(re.split(r"[<>=!~\\[;@ ]", line, maxsplit=1)[0])
missing = []
for name in names:
    try:
        md.version(name)
    except md.PackageNotFoundError:
        missing.append(name)
for name in missing:
    print("SD_ENV_MISSING", name)
if not missing:
    print("SD_ENV_OK")
PYEOF"""


def render_env_build(user: str, folder: str, home: str, *, kind: Literal["conda", "venv"],
                     name: str, dest: str, packages: str, requirements_path: str | None,
                     spec_path: str | None, partition: str = "",
                     nfs_root: str = "/shared", spec_text: str | None = None) -> str:
    """The sbatch script that builds an environment at dest.

    A conda build starts from spec_path when given (the file is read here for
    the names to verify, so it must be an admin-owned prebuilt spec) or from a
    bare python. spec_text, when given, is that spec's content, for a caller
    that can't read the cluster's copy at spec_path. A venv build can't take a
    spec. packages are shell-split and each word quoted.
    """
    if kind == "venv" and spec_path:
        raise ValueError("a venv can't be built from a conda spec")
    q = shlex.quote
    parent = str(PurePosixPath(dest).parent)
    words = shlex.split(packages)
    names = top_level_names(words)
    if spec_path:
        text = spec_text if spec_text is not None else Path(spec_path).read_text()
        names = top_level_names(parse_pip_deps(text)) + names

    lines = ["#!/bin/bash", _directive("job-name", PurePosixPath(folder).name)]
    if partition:
        lines.append(_directive("partition", partition))
    lines += [
        _directive("cpus-per-task", BUILD_CPUS),
        _directive("mem", f"{BUILD_MEM_GB}G"),
        _directive("time", BUILD_TIME),
        _directive("output", f"{folder}/slurm-%j.out"),
        _directive("error", f"{folder}/slurm-%j.err"),
        _directive("chdir", folder),
        *_clean_env(home, user, gpu=False),
        "set -e",
        # Not /tmp: a node's /tmp is small, and big wheels fill it.
        f"export TMPDIR={q(parent + '/.tmp-' + name)}",
        f"export PIP_CACHE_DIR={q(parent + '/.pip-cache')}",
        'mkdir -p "$TMPDIR" "$PIP_CACHE_DIR"',
        "",
    ]
    if not spec_path:
        # A user build never reuses a name that exists, whoever owns it.
        lines += [f"if [ -e {q(dest)} ]; then",
                  f'    echo "ERROR: an environment named {name} already exists '
                  f'and can't be replaced. Pick another name." >&2',
                  "    exit 1", "fi"]
    if kind == "conda":
        # Just the line that sources conda.sh, so `conda` works in this shell.
        lines += _activate(EnvChoice("conda", "base"), nfs_root)[:1]
        if spec_path:
            lines.append(f"conda env create -p {q(dest)} -f {q(spec_path)}")
        else:
            lines.append(f"conda create -y -p {q(dest)} python=3.11 pip")
        lines.append(f"conda activate {q(dest)}")
    else:
        lines += [f"python3 -m venv {q(dest)}", f"source {q(dest + '/bin/activate')}"]
    if words:
        lines.append("python -m pip install " + " ".join(q(w) for w in words))
    if requirements_path:
        lines.append(f"python -m pip install -r {q(requirements_path)}")
    lines += [
        "set +e",
        "",
        f"export SD_ENV_PACKAGES={q(' '.join(names))}",
        f"export SD_ENV_REQUIREMENTS={q(requirements_path or '')}",
        VERIFY_SNIPPET,
        'rm -rf "$TMPDIR"',
    ]
    return "\n".join(lines) + "\n"


def parse_env_result(out_text: str) -> tuple[bool, list[str]]:
    """(ok, missing packages) from a build job's output. A build that stopped
    before the check reports (False, [])."""
    missing = []
    ok = False
    for line in out_text.splitlines():
        line = line.strip()
        if line.startswith("SD_ENV_MISSING "):
            missing.append(line.split(None, 1)[1])
        elif line == "SD_ENV_OK":
            ok = True
    return ok and not missing, missing
