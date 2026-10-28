"""sd-backup.sh against a fake docker, and the units that run it. Needs bash (Linux)."""

import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "deploy" / "cluster" / "sd-backup.sh"

pytestmark = pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bash"),
                                reason="the backup script runs on Linux")


@pytest.fixture
def box(tmp_path):
    """Directories, config files and a fake `docker`; returns a runner."""
    conf, backups, nfs = tmp_path / "conf", tmp_path / "backups", tmp_path / "shared"
    for d in (conf, nfs, tmp_path / "bin", tmp_path / "deploy"):
        d.mkdir()
    for name in ("web.env", "secrets.env", "agent.env", "install-state.json", "notes.txt"):
        (conf / name).write_text(f"{name}\n")
    audit = tmp_path / "agent-audit.jsonl"
    audit.write_text('{"verb": "x"}\n')
    docker = tmp_path / "bin" / "docker"
    docker.write_text('#!/bin/bash\necho "docker $*" >> "$T/docker.log"\n'
                      '[ -f "$T/dump.fail" ] && { echo "pg_dump: boom" >&2; exit 1; }\n'
                      'printf "DUMP-OF-THE-DATABASE"\n')
    docker.chmod(0o755)

    def run(*args, **env):
        full = {"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin", "T": str(tmp_path),
                "BACKUP_DIR": str(backups), "CONF_DIR": str(conf), "NFS_ROOT": str(nfs),
                "COMPOSE_DIR": str(tmp_path / "deploy"), "AUDIT_LOG": str(audit),
                "HOME": str(tmp_path), **env}
        return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                              env=full)
    run.backups, run.nfs, run.tmp = backups, nfs, tmp_path
    return run


def test_prune_keeps_fourteen(box):
    box.backups.mkdir()
    for day in range(1, 21):
        (box.backups / f"sd-202610{day:02d}.dump").write_text("d")
        (box.backups / f"sd-202610{day:02d}-config.tar.gz").write_text("c")
    assert box("--prune-only").returncode == 0
    kept = sorted(p.name for p in box.backups.glob("*.dump"))
    assert kept == [f"sd-202610{d:02d}.dump" for d in range(7, 21)]   # the 14 newest
    assert len(list(box.backups.glob("*-config.tar.gz"))) == 14       # their configs go with them
    assert box("--prune-only", BACKUP_KEEP="3").returncode == 0
    assert len(list(box.backups.glob("*.dump"))) == 3


def test_a_run_writes_a_private_dump_and_config_archive(box):
    r = box()
    assert r.returncode == 0, r.stderr
    (dump,) = box.backups.glob("sd-*.dump")
    assert dump.read_bytes() == b"DUMP-OF-THE-DATABASE"
    (conf,) = box.backups.glob("sd-*-config.tar.gz")
    for f in (dump, conf):
        assert stat.S_IMODE(f.stat().st_mode) == 0o600
    with tarfile.open(conf) as tar:
        names = tar.getnames()
    assert {"web.env", "secrets.env", "agent.env", "install-state.json",
            "agent-audit.jsonl"} <= set(names)
    assert "notes.txt" not in names   # only the *.env files and the installer state
    assert "exec -T db pg_dump -Fc -U sdweb slurmdeck" in (box.tmp / "docker.log").read_text()


def test_a_failed_dump_leaves_no_partial_file_and_deletes_no_old_backup(box):
    box.backups.mkdir()
    for day in range(1, 21):
        (box.backups / f"sd-202610{day:02d}.dump").write_text("d")
    (box.tmp / "dump.fail").write_text("")
    r = box()
    assert r.returncode != 0 and "pg_dump: boom" in r.stderr
    assert len(list(box.backups.glob("*.dump"))) == 20       # nothing pruned
    assert not list(box.backups.glob("*.part")) and not list(box.backups.glob("sd-2026102[6-9]*"))


def test_it_can_copy_to_the_admin_only_shared_folder(box):
    assert box().returncode == 0
    assert not (box.nfs / ".admin-backups").exists()
    assert box(BACKUP_COPY_TO_SHARED="1").returncode == 0
    shared = box.nfs / ".admin-backups"
    assert stat.S_IMODE(shared.stat().st_mode) == 0o700
    assert len(list(shared.glob("sd-*.dump"))) == len(list(shared.glob("sd-*-config.tar.gz"))) == 1


def test_the_units_run_nightly_as_slurmadmin_with_the_cluster_timezone():
    service = (REPO / "deploy/systemd/sd-backup.service").read_text()
    timer = (REPO / "deploy/systemd/sd-backup.timer").read_text()
    assert "User=slurmadmin" in service
    assert "ExecStart=@REPO@/deploy/cluster/sd-backup.sh" in service
    assert "EnvironmentFile=-/etc/slurm-deck-web/site.env" in service
    assert "OnCalendar=*-*-* 02:30:00 @CLUSTER_TZ@" in timer and "Persistent=true" in timer
