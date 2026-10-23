"""Cluster hardening scripts, run against fake system commands on PATH.

Each fake logs its arguments to calls.log, so a test can prove --check made no
change. The scripts need bash and run on Linux (CI); they are skipped elsewhere.
"""

import importlib.machinery
import importlib.util
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CLUSTER = REPO / "deploy" / "cluster"

pytestmark = pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bash"),
                                reason="hardening scripts run on Linux")


def _fake_bin(tmp_path: Path, scripts: dict[str, str]) -> Path:
    """Fake commands that log `name args...` to calls.log, then run their body."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    log = tmp_path / "calls.log"
    for name, body in scripts.items():
        f = bindir / name
        f.write_text(f'#!/bin/bash\necho "{name} $*" >> "{log}"\n{body}\n')
        f.chmod(0o755)
    return bindir


def _run(script: str, args: list[str], bindir: Path, **env: str) -> subprocess.CompletedProcess:
    full_env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(bindir.parent), **env}
    return subprocess.run(["bash", str(CLUSTER / "harden" / script), *args],
                          capture_output=True, text=True, env=full_env)


def _calls(tmp_path: Path) -> str:
    log = tmp_path / "calls.log"
    return log.read_text() if log.exists() else ""


DOCKER_FAKES = {
    "getent": 'echo "docker:x:998:alice,bob,root-daham"',
    "docker": 'printf "abc123\\tjupyter\\tpytorch:latest\\n"',
    "gpasswd": "",
}


# ── remove-docker-group.sh ───────────────────────────────────────────────────

def test_docker_check_changes_nothing(tmp_path):
    bindir = _fake_bin(tmp_path, DOCKER_FAKES)
    r = _run("remove-docker-group.sh", ["--check"], bindir, SYSADMINS="root-daham")
    assert r.returncode == 0, r.stderr
    assert "alice" in r.stdout and "bob" in r.stdout
    assert "jupyter" in r.stdout                      # running containers listed
    assert "gpasswd" not in _calls(tmp_path)


def test_docker_apply_removes_all_but_sysadmins_and_keep(tmp_path):
    bindir = _fake_bin(tmp_path, DOCKER_FAKES)
    r = _run("remove-docker-group.sh", ["--apply", "--keep", "bob"], bindir,
             SYSADMINS="root-daham,iit")
    assert r.returncode == 0, r.stderr
    calls = _calls(tmp_path)
    assert "gpasswd -d alice docker" in calls
    assert "gpasswd -d bob" not in calls
    assert "gpasswd -d root-daham" not in calls


def test_docker_apply_refuses_without_a_sysadmin_list(tmp_path):
    bindir = _fake_bin(tmp_path, DOCKER_FAKES)
    r = _run("remove-docker-group.sh", ["--apply"], bindir)
    assert r.returncode != 0
    assert "gpasswd" not in _calls(tmp_path)


def test_docker_needs_a_mode(tmp_path):
    bindir = _fake_bin(tmp_path, DOCKER_FAKES)
    assert _run("remove-docker-group.sh", [], bindir).returncode != 0


# ── shared-areas.sh ──────────────────────────────────────────────────────────

def _share(tmp_path: Path) -> Path:
    root = tmp_path / "shared"
    for d in ("users/alice", "jobs/alice", "models/llm", "envs"):
        (root / d).mkdir(parents=True)
    for f in ("users/alice/notes.txt", "jobs/alice/out.log", "models/llm/w.bin"):
        (root / f).write_text("x")
        (root / f).chmod(0o666)
    (root / "models" / "to_alice").symlink_to(root / "users" / "alice")
    return root


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.lstat().st_mode)


def _area_env(root: Path) -> dict[str, str]:
    # The test user stands in for sd-ops and its primary group for gpuadmins.
    return {"NFS_ROOT": str(root), "OPS_USER": _whoami(), "ADMIN_GROUP": _group()}


def _whoami() -> str:
    return subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()


def _group() -> str:
    return subprocess.run(["id", "-gn"], capture_output=True, text=True).stdout.strip()


def test_shared_areas_check_counts_and_never_lists_users_or_jobs(tmp_path):
    root = _share(tmp_path)
    bindir = _fake_bin(tmp_path, {"getfacl": "", "setfacl": ""})
    r = _run("shared-areas.sh", ["--check"], bindir, **_area_env(root))
    assert r.returncode == 0, r.stderr
    reported = {line.split(":")[0] for line in r.stdout.splitlines()}
    assert "models" in reported
    assert reported <= {"envs", "models", "datasets", "data", "images", "scripts"}
    assert "users/" not in r.stdout and "jobs/" not in r.stdout
    assert _mode(root / "models" / "llm" / "w.bin") == 0o666   # unchanged
    assert "setfacl" not in _calls(tmp_path)


def test_shared_areas_apply_fixes_assets_and_leaves_users_and_jobs(tmp_path):
    root = _share(tmp_path)
    bindir = _fake_bin(tmp_path, {"getfacl": "", "setfacl": ""})
    r = _run("shared-areas.sh", ["--apply"], bindir, **_area_env(root))
    assert r.returncode == 0, r.stderr
    assert _mode(root / "models" / "llm" / "w.bin") == 0o644
    assert _mode(root / "models" / "llm") == 0o2775
    assert _mode(root / "users" / "alice" / "notes.txt") == 0o666
    assert _mode(root / "jobs" / "alice" / "out.log") == 0o666
    calls = _calls(tmp_path)
    assert f"{root}/users" not in calls and f"{root}/jobs" not in calls


# ── service-accounts.sh ──────────────────────────────────────────────────────

def test_service_accounts_check_changes_nothing(tmp_path):
    bindir = _fake_bin(tmp_path, {"id": "exit 1", "useradd": "", "systemctl": "exit 0"})
    r = _run("service-accounts.sh", ["--check"], bindir, NFS_ROOT=str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "sd-stats" in r.stdout
    calls = _calls(tmp_path)
    assert "useradd" not in calls
    assert "systemctl disable" not in calls and "systemctl enable" not in calls


# ── slurm-deck-mailer ────────────────────────────────────────────────────────

def _mailer():
    loader = importlib.machinery.SourceFileLoader("sd_mailer", str(CLUSTER / "slurm-deck-mailer"))
    spec = importlib.util.spec_from_loader("sd_mailer", loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_mailer_escapes_job_names(monkeypatch):
    monkeypatch.setenv("CLUSTER_NAME", "<i>Lab</i>")
    m = _mailer()
    info = m.parse_slurm_subject("Slurm Job_id=42 Name=<b>evil</b> Ended, Run time 00:01:00")
    page = m.build_html(info, {"WorkDir": "/shared/jobs/a/<script>"})
    assert "&lt;b&gt;evil&lt;/b&gt;" in page and "<b>evil" not in page
    assert "&lt;script&gt;" in page and "<script>" not in page
    assert "&lt;i&gt;Lab&lt;/i&gt;" in page


def test_mailer_labels_times_in_the_cluster_timezone(monkeypatch):
    monkeypatch.setenv("CLUSTER_TZ", "Asia/Colombo")
    m = _mailer()
    page = m.build_html(m.parse_slurm_subject("Slurm Job_id=1 Name=a Began"), {})
    assert "Asia/Colombo" in page


def test_mailer_subject_has_no_line_breaks():
    m = _mailer()
    info = m.parse_slurm_subject("Slurm Job_id=7 Name=a Began")
    info["job_name"] = "a\r\nBcc: x@evil.com"
    assert "\n" not in m.build_subject(info, {}) and "\r" not in m.build_subject(info, {})
