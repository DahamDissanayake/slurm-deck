"""Prebuilt env specs, Apptainer defs and the env build job.

The spec checks are ported from legacy/v1.4-tui tests/test_prebuilt_envs.py,
reading the pip block with sdcore.envspec instead of PyYAML and checking
requirement lines with a pattern instead of `packaging` (neither is a
dependency here).
"""

import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from sdcore.envspec import (
    VERIFY_SNIPPET,
    list_specs,
    parse_env_result,
    parse_pip_deps,
    render_env_build,
    top_level_names,
)

REPO = Path(__file__).resolve().parents[2]
SPECS = REPO / "deploy" / "cluster" / "envs"
IMAGES = REPO / "deploy" / "cluster" / "images"
EXPECTED = ["llm-finetune", "llm-serve", "vision", "diffusion", "data-science"]
FAST_MOVING = ("transformers", "trl")
REQUIREMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[^\]]+\])?([<>=!~]=?[^\s,]+(,[<>=!~]=?[^\s,]+)*)?$")


def _spec(name: str) -> str:
    return (SPECS / f"{name}.yml").read_text()


@pytest.mark.parametrize("name", EXPECTED)
def test_spec_basics(name):
    text = _spec(name)
    assert "cu128" in text and "python=3.11" in text
    assert "torch==2.7" in text
    for old in ("cu121", "cu124", "cu126"):
        assert old not in text


@pytest.mark.parametrize("name", EXPECTED)
def test_specs_bound_fast_moving_libraries(name):
    for dep in parse_pip_deps(_spec(name)):
        if re.split(r"[<>=!~\[]", dep, maxsplit=1)[0].lower() in FAST_MOVING:
            assert "<" in dep, f"{name}.yml: {dep} has no upper bound"


def test_the_llm_specs_actually_contain_the_bounded_libraries():
    deps = parse_pip_deps(_spec("llm-finetune"))
    assert "transformers>=4.40,<5" in deps and "trl>=0.8,<1" in deps


@pytest.mark.parametrize("name", EXPECTED)
def test_spec_pip_entries_are_single_requirements(name):
    """Each pip item must be one requirement or a flag; packing several onto a
    line made pip fail with 'Invalid requirement'."""
    tokens = parse_pip_deps(_spec(name))
    i = 0
    while i < len(tokens):
        if tokens[i].startswith("-"):
            i += 2 if "index-url" in tokens[i] else 1
            continue
        assert REQUIREMENT.match(tokens[i]), f"{name}.yml: bad requirement {tokens[i]!r}"
        i += 1


@pytest.mark.parametrize("name", EXPECTED)
def test_image_def_basics(name):
    text = (IMAGES / f"{name}.def").read_text()
    assert "Bootstrap:" in text and "From:" in text
    assert "cu128" in text and "torch==2.7" in text


@pytest.mark.parametrize("name", EXPECTED)
def test_image_def_quotes_version_specifiers(name):
    """Unquoted, `pip install transformers>=4.40` redirects to a file named
    `=4.40` and installs an unbounded package."""
    text = (IMAGES / f"{name}.def").read_text()
    # The pip install commands, continuation lines joined.
    blocks = re.findall(r"pip install(?:[^\n]*\\\n)*[^\n]*", text)
    assert blocks
    for block in blocks:
        for word in shlex.split(block.replace("\\\n", " "), posix=False):
            if re.search(r"[<>=*]", word) and not word.startswith(("--", "http")):
                assert word.startswith('"'), f"{name}.def: unquoted specifier {word!r}"
    for lib in FAST_MOVING:
        for m in re.finditer(rf'"{lib}[^"]*"', text):
            assert "<" in m.group(0), f"{name}.def: {m.group(0)} has no upper bound"


def test_list_specs_reads_names_and_descriptions():
    specs = {s.name: s for s in list_specs(str(SPECS))}
    assert sorted(specs) == sorted(EXPECTED)
    assert "trl" in specs["llm-finetune"].description
    assert specs["vision"].path.endswith("vision.yml")


def test_parse_pip_deps_and_top_level_names():
    text = ("dependencies:\n  - python=3.11\n  - pip:\n"
            "    - --extra-index-url https://x/cu128\n    - torch==2.7.*\n"
            "    - Pillow\n    - transformers[torch]>=4.40,<5\nother: 1\n  - not-pip\n")
    deps = parse_pip_deps(text)
    assert deps == ["--extra-index-url", "https://x/cu128", "torch==2.7.*", "Pillow",
                    "transformers[torch]>=4.40,<5"]
    assert top_level_names(deps) == ["torch", "Pillow", "transformers"]
    assert parse_pip_deps("name: x\n") == []


def _build(**kw) -> str:
    args = dict(kind="conda", name="my-env", dest="/shared/users/amasha/envs/my-env",
                packages="numpy 'pandas>=2' $(id)", requirements_path=None, spec_path=None)
    args.update(kw)
    return render_env_build("amasha", "/shared/jobs/amasha/env_build_1", "/home/amasha",
                            **args)


def test_build_script_has_no_user_site_install():
    for kw in ({}, {"kind": "venv"}, {"requirements_path": "/shared/users/amasha/req.txt"}):
        s = _build(**kw)
        assert "--user" not in s
        assert "pip install" in s


def test_build_is_a_cpu_job_with_tmp_beside_the_destination():
    s = _build()
    assert "--gres" not in s and "#SBATCH --cpus-per-task=8" in s
    assert "#SBATCH --mem=16G" in s and "#SBATCH --time=04:00:00" in s
    assert "export TMPDIR=/shared/users/amasha/envs/.tmp-my-env" in s
    assert "export PIP_CACHE_DIR=/shared/users/amasha/envs/.pip-cache" in s
    assert "/tmp" not in s


def test_build_quotes_user_packages():
    s = _build()
    assert "numpy 'pandas>=2' '$(id)'" in s


def test_build_from_spec_verifies_its_packages():
    spec = str(SPECS / "llm-finetune.yml")
    s = _build(spec_path=spec, packages="")
    assert f"conda env create -p /shared/users/amasha/envs/my-env -f {shlex.quote(spec)}" in s
    packages = re.search(r"export SD_ENV_PACKAGES=(.*)", s)
    assert packages and "trl" in shlex.split(packages.group(1))[0].split()


def test_venv_build_refuses_a_spec():
    with pytest.raises(ValueError):
        _build(kind="venv", spec_path=str(SPECS / "vision.yml"))


def test_build_scripts_are_valid_bash(tmp_path):
    if not shutil.which("bash"):
        pytest.skip("no bash")
    for kw in ({}, {"kind": "venv"}, {"requirements_path": "/r q.txt"},
               {"spec_path": str(SPECS / "vision.yml"), "packages": ""}):
        path = tmp_path / "build.sbatch"
        path.write_text(_build(**kw))
        assert subprocess.run(["bash", "-n", str(path)]).returncode == 0, kw


def test_verify_snippet_prints_the_markers():
    assert "SD_ENV_MISSING" in VERIFY_SNIPPET and "SD_ENV_OK" in VERIFY_SNIPPET


def test_parse_env_result():
    assert parse_env_result("Collecting x\nSD_ENV_MISSING torch\n") == (False, ["torch"])
    assert parse_env_result("ok\nSD_ENV_OK\n") == (True, [])
    assert parse_env_result("pip failed\n") == (False, [])
