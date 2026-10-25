"""The forced-command GPU-host helper, run with --root <tmp> --dry-run so
privileged commands are printed instead of run. Renames under the root happen."""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("the GPU-host helper runs on Linux", allow_module_level=True)

from sdcore.names import RESERVED, USERNAME_RE  # noqa: E402

HELPER = Path(__file__).resolve().parents[2] / "gpuhost" / "sd-gpu-helper"


def run_helper(cmd: str, root: Path | None = None) -> subprocess.CompletedProcess:
    args = [sys.executable, str(HELPER), "--dry-run"]
    if root is not None:
        args += ["--root", str(root)]
    env = {**os.environ, "SSH_ORIGINAL_COMMAND": cmd}
    return subprocess.run(args, capture_output=True, text=True, env=env)


def _json(r: subprocess.CompletedProcess) -> dict:
    return json.loads(r.stdout)


@pytest.mark.parametrize("cmd", ["purge ..", "purge .", "purge a/b", "archive root",
                                 "create-account x 0", "create-account x abc",
                                 "create-account x 70000", "rm -rf /", "purge amasha; id",
                                 "purge amasha extra", "ping now", "", "folder-info Root",
                                 "delete-account slurmadmin", "create-folders sdweb 20001",
                                 "service-status slurmd"])
def test_refuses_bad_commands(tmp_path, cmd):
    r = run_helper(cmd, tmp_path)
    assert r.returncode == 2, (cmd, r.stdout, r.stderr)
    assert _json(r)["ok"] is False


def test_ping():
    r = run_helper("ping")
    assert r.returncode == 0 and _json(r) == {"ok": True, "pong": True}


def test_service_status_reports_only_the_allowed_units():
    r = run_helper("service-status")
    assert r.returncode == 0 and set(_json(r)["units"]) == {"slurmd", "munge", "sd-stats-writer"}


def test_uid_of_another_account_refused(tmp_path):
    import pwd

    me = pwd.getpwuid(os.getuid())
    if os.getuid() < 1000:
        pytest.skip("needs a non-system test user")
    assert run_helper(f"create-account other-name {me.pw_uid}", tmp_path).returncode == 2


def test_create_account_commands(tmp_path):
    r = run_helper("create-account amasha 23456", tmp_path)
    assert r.returncode == 0, r.stderr
    assert "+ groupadd -g 23456 amasha" in r.stderr
    assert ("+ useradd -u 23456 -g 23456 -m -d /home/amasha -s /usr/sbin/nologin "
            "-G webusers,gpuusers amasha") in r.stderr
    assert "+ passwd -l amasha" in r.stderr and "+ chown -R 23456:23456 /home/amasha" in r.stderr


def test_create_folders_commands(tmp_path):
    r = run_helper("create-folders amasha 23456", tmp_path)
    assert r.returncode == 0, r.stderr
    for sub in ("users", "jobs"):
        path = tmp_path / sub / "amasha"
        assert f"+ chown 23456:gpuadmins {path}" in r.stderr
        assert f"+ chmod 2770 {path}" in r.stderr
        assert f"+ setfacl -R -m g:gpuadmins:rwX -m d:g:gpuadmins:rwx {path}" in r.stderr


def test_purge_refuses_symlinked_user_dir(tmp_path):
    (tmp_path / "users").mkdir()
    (tmp_path / "jobs" / "amasha").mkdir(parents=True)
    (tmp_path / "users" / "amasha").symlink_to("/etc")
    r = run_helper("purge amasha", tmp_path)
    assert r.returncode == 2
    assert "rm " not in r.stderr          # nothing removed, not even jobs/amasha


def test_purge_removes_both_folders(tmp_path):
    for sub in ("users", "jobs"):
        (tmp_path / sub / "amasha").mkdir(parents=True)
    r = run_helper("purge amasha", tmp_path)
    assert r.returncode == 0, r.stderr
    assert f"+ rm -rf --one-file-system {tmp_path / 'users' / 'amasha'}" in r.stderr
    assert f"+ rm -rf --one-file-system {tmp_path / 'jobs' / 'amasha'}" in r.stderr


def test_archive_never_deletes_previous_archive(tmp_path):
    users = tmp_path / "users"
    (users / "amasha").mkdir(parents=True)
    (users / "amasha" / "new.txt").write_text("new")
    (users / "amasha.offboarded").mkdir()
    (users / "amasha.offboarded" / "old.txt").write_text("old")
    r = run_helper("archive amasha", tmp_path)
    assert r.returncode == 0, r.stderr
    assert (users / "amasha.offboarded" / "new.txt").read_text() == "new"
    older = [p for p in users.iterdir() if p.name.startswith("amasha.offboarded.")]
    assert len(older) == 1 and (older[0] / "old.txt").read_text() == "old"
    assert not (users / "amasha").exists()


def test_archive_refuses_a_symlink(tmp_path):
    (tmp_path / "users").mkdir()
    (tmp_path / "users" / "amasha").symlink_to(tmp_path)
    assert run_helper("archive amasha", tmp_path).returncode == 2


def test_folder_info_reports_owner_and_size(tmp_path):
    d = tmp_path / "users" / "amasha"
    d.mkdir(parents=True)
    (d / "f.bin").write_bytes(b"x" * 5000)
    info = _json(run_helper("folder-info amasha", tmp_path))
    assert info["ok"] and info["exists"] is True
    assert info["owner_uid"] == os.getuid() and info["bytes"] >= 5000 and info["mtime"]
    assert _json(run_helper("folder-info nobody-here", tmp_path)) == {"ok": True,
                                                                     "exists": False}


def test_delete_account_commands(tmp_path):
    r = run_helper("delete-account amasha", tmp_path)
    assert r.returncode == 0, r.stderr
    assert "+ pkill -KILL -u amasha" in r.stderr and "+ userdel amasha" in r.stderr
    assert "+ groupdel amasha" in r.stderr


def test_username_rule_matches_sdcore():
    loader = importlib.machinery.SourceFileLoader("sd_gpu_helper", str(HELPER))
    spec = importlib.util.spec_from_loader("sd_gpu_helper", loader)
    assert spec is not None
    helper = importlib.util.module_from_spec(spec)
    loader.exec_module(helper)
    assert helper.USERNAME_RE.pattern == USERNAME_RE.pattern
    assert helper.RESERVED == RESERVED
