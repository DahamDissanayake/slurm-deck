"""Input validation ported from legacy/v1.4-tui tests/test_validate.py.

The legacy tests set env vars and reloaded the module, and mocked the daemon
for --mail-user and scontrol for the pod ceiling. sdcore reads no env and does
no I/O beyond resolving paths, so the same cases now pass those values in.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from sdcore.validate import (
    clamp_int,
    clean_array_spec,
    clean_dependency,
    clean_job_name,
    clean_modules,
    clean_run_command,
    clean_time_limit,
    in_user_browse_jail,
    in_user_job_jail,
    in_user_upload_jail,
    parse_hms,
    pod_ceiling,
    user_browse_roots,
    user_job_root,
    user_upload_root,
    validate_against_qos,
    validate_sbatch,
)

# ── clamp_int ────────────────────────────────────────────────────────────────


def test_clamp_int_within_range():
    assert clamp_int("5", 1, 10, 3) == 5


def test_clamp_int_caps_high():
    assert clamp_int(99, 1, 10, 3) == 10


def test_clamp_int_floors_low():
    assert clamp_int(-4, 1, 10, 3) == 1


def test_clamp_int_uses_default_on_bad_type():
    assert clamp_int("abc", 1, 10, 3) == 3
    assert clamp_int(None, 1, 10, 3) == 3


# ── clean_time_limit / parse_hms ─────────────────────────────────────────────


def test_clean_time_limit_valid():
    assert clean_time_limit("12:30:00", max_hours=72) == "12:30:00"


def test_clean_time_limit_clamps_over_max():
    assert clean_time_limit("999:00:00", max_hours=72) == "72:00:00"


def test_clean_time_limit_caps_to_given_max():
    assert clean_time_limit("30:00:00", max_hours=24) == "24:00:00"


def test_clean_time_limit_caps_minutes_past_the_max_hour():
    # Legacy compared hours only, so 24:30:00 slipped past a 24 h cap.
    assert clean_time_limit("24:30:00", max_hours=24) == "24:00:00"
    assert clean_time_limit("24:00:00", max_hours=24) == "24:00:00"


def test_clean_time_limit_pads_hours():
    assert clean_time_limit("1:05:00", max_hours=24) == "01:05:00"


def test_clean_time_limit_rejects_garbage():
    assert clean_time_limit("not-a-time", max_hours=72) is None


def test_clean_time_limit_rejects_bad_minutes():
    assert clean_time_limit("01:99:00", max_hours=72) is None


def test_parse_hms():
    assert parse_hms("01:02:03") == 3723
    assert parse_hms(" 100:00:00 ") == 360000
    assert parse_hms("01:60:00") is None
    assert parse_hms("1-00:00:00") is None
    assert parse_hms("") is None


# ── clean_job_name / clean_run_command / clean_modules ───────────────────────


def test_clean_job_name_strips_bad_chars():
    assert clean_job_name("my job!@#") == "myjob"


def test_clean_job_name_allows_safe_chars():
    assert clean_job_name("train_v1.2-run") == "train_v1.2-run"


def test_clean_job_name_truncates_at_64():
    assert len(clean_job_name("a" * 100)) == 64


def test_clean_run_command_removes_newlines():
    result = clean_run_command("python train.py\nrm -rf /")
    assert "\n" not in result


def test_clean_run_command_removes_control_chars():
    result = clean_run_command("python\x00train.py\x1b[31m")
    assert "\x00" not in result
    assert "\x1b" not in result


def test_clean_run_command_truncates_at_1000():
    assert len(clean_run_command("x" * 2000)) == 1000


def test_clean_modules_keeps_safe_tokens_only():
    assert clean_modules("cuda/12.1 python/3.11; rm -rf /") == [
        "cuda/12.1", "python/3.11", "rm", "-rf", "/"]
    assert len(clean_modules(" ".join(["m"] * 30))) == 20


# ── array / dependency specs ─────────────────────────────────────────────────


@pytest.mark.parametrize("spec", ["0-9", "1-100%4", "1,3,5", "0-15:4", "7"])
def test_clean_array_spec_accepts(spec):
    assert clean_array_spec(spec) == spec


@pytest.mark.parametrize("spec", ["", "a-b", "1-", "1;rm", "-5", "1,,2"])
def test_clean_array_spec_rejects(spec):
    assert clean_array_spec(spec) is None


@pytest.mark.parametrize("dep", ["afterok:12345", "afterany:1:2", "singleton", "after:5_3"])
def test_clean_dependency_accepts(dep):
    assert clean_dependency(dep) == dep


@pytest.mark.parametrize("dep", ["", "afterok", "afterok:", "before:1", "afterok:1;id"])
def test_clean_dependency_rejects(dep):
    assert clean_dependency(dep) is None


# ── per-user jails ───────────────────────────────────────────────────────────


def test_browse_roots_include_shared_datasets():
    """File manager and notebook must expose the same boundary."""
    roots = user_browse_roots("/shared", "yenuli")
    assert str(Path("/shared/users/yenuli").resolve()) in roots
    for shared in ("/shared/models", "/shared/envs", "/shared/data", "/shared/datasets"):
        assert str(Path(shared).resolve()) in roots, f"{shared} must be browsable"


def test_browse_roots_exclude_other_users_and_jobs():
    roots = user_browse_roots("/shared", "yenuli")
    assert str(Path("/shared/users").resolve()) not in roots
    assert str(Path("/shared/jobs").resolve()) not in roots


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "root", "slurmadmin"])
def test_roots_refuse_usernames_that_resolve_elsewhere(bad):
    with pytest.raises(ValueError):
        user_browse_roots("/shared", bad)
    with pytest.raises(ValueError):
        user_upload_root("/shared", bad)
    with pytest.raises(ValueError):
        user_job_root("/shared", bad)


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "root"])
def test_jails_are_closed_for_invalid_usernames(tmp_path, bad):
    (tmp_path / "users").mkdir()
    target = str(tmp_path / "users")
    assert not in_user_browse_jail(target, str(tmp_path), bad)
    assert not in_user_upload_jail(target, str(tmp_path), bad)
    assert not in_user_job_jail(str(tmp_path / "jobs"), str(tmp_path), bad)


def test_upload_jail_accepts_own_area_only(tmp_path):
    own = tmp_path / "users" / "alice" / "sub"
    own.mkdir(parents=True)
    (tmp_path / "users" / "bob").mkdir()
    assert in_user_upload_jail(str(own), str(tmp_path), "alice")
    assert not in_user_upload_jail(str(tmp_path / "users" / "bob"), str(tmp_path), "alice")
    assert not in_user_upload_jail(str(tmp_path / "models"), str(tmp_path), "alice")


def test_jail_rejects_dotdot_escape(tmp_path):
    (tmp_path / "users" / "alice").mkdir(parents=True)
    escape = str(tmp_path / "users" / "alice" / ".." / "bob")
    assert not in_user_browse_jail(escape, str(tmp_path), "alice")


def test_jail_rejects_prefix_sibling(tmp_path):
    # /shared/users/alice2 must not count as inside /shared/users/alice.
    (tmp_path / "users" / "alice2").mkdir(parents=True)
    assert not in_user_upload_jail(str(tmp_path / "users" / "alice2"), str(tmp_path), "alice")


def test_browse_jail_rejects_symlink_escape(tmp_path):
    alice = tmp_path / "users" / "alice"
    bob = tmp_path / "users" / "bob"
    alice.mkdir(parents=True)
    bob.mkdir(parents=True)
    link = alice / "to_bob"
    try:
        link.symlink_to(bob, target_is_directory=True)
    except OSError:
        pytest.skip("cannot create symlinks here")
    assert not in_user_browse_jail(str(link), str(tmp_path), "alice")
    assert not in_user_upload_jail(str(link / "x.txt"), str(tmp_path), "alice")


def test_job_jail(tmp_path):
    jd = tmp_path / "jobs" / "alice" / "train_1"
    jd.mkdir(parents=True)
    (tmp_path / "jobs" / "bob").mkdir()
    assert in_user_job_jail(str(jd), str(tmp_path), "alice")
    assert not in_user_job_jail(str(tmp_path / "jobs" / "bob"), str(tmp_path), "alice")
    assert in_user_job_jail(str(tmp_path / "work" / "alice"), str(tmp_path), "alice",
                            jobs_subdir="work")


# ── validate_sbatch ──────────────────────────────────────────────────────────


def _user_dir(tmp_path, user="alice"):
    d = tmp_path / "users" / user
    d.mkdir(parents=True, exist_ok=True)
    return d


def _job_dir(tmp_path, user="alice"):
    d = tmp_path / "jobs" / user
    d.mkdir(parents=True, exist_ok=True)
    return d


def _v(text, tmp_path, username="alice", email="alice@iit.lk", **limits):
    return validate_sbatch(text, username, nfs_root=str(tmp_path), registered_email=email,
                           **limits)


def _stats(shard_total):
    # Stands in for sdcore.slurmparse.NodeStats; only shard_total is read.
    return SimpleNamespace(shard_total=shard_total)


def test_validate_sbatch_clean_script_passes(tmp_path):
    ud = _user_dir(tmp_path)
    script = f"""#!/bin/bash
#SBATCH --job-name=test
#SBATCH --output={ud}/slurm-%j.out
#SBATCH --error={ud}/slurm-%j.err
#SBATCH --chdir={ud}
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
python train.py
"""
    assert _v(script, tmp_path) == []


def test_validate_sbatch_rejects_output_outside_jail(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --output=/etc/malicious.out\n", tmp_path)
    assert any("--output" in e for e in errors)


def test_validate_sbatch_rejects_chdir_outside_jail(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --chdir=/etc\n", tmp_path)
    assert any("--chdir" in e for e in errors)


def test_validate_sbatch_rejects_cross_user_output(tmp_path):
    _user_dir(tmp_path, "alice")
    bob = _user_dir(tmp_path, "bob")
    errors = _v(f"#SBATCH --output={bob}/stolen.out\n", tmp_path, username="alice")
    assert any("--output" in e for e in errors)


def test_validate_sbatch_accepts_user_job_dir(tmp_path):
    _user_dir(tmp_path, "alice")
    jd = _job_dir(tmp_path, "alice") / "train_123"
    jd.mkdir(parents=True, exist_ok=True)
    script = f"""#!/bin/bash
#SBATCH --output={jd}/slurm-%j.out
#SBATCH --error={jd}/slurm-%j.err
#SBATCH --chdir={jd}
#SBATCH --gres=gpu:1
"""
    assert _v(script, tmp_path) == []


def test_validate_sbatch_rejects_cross_user_job_dir(tmp_path):
    _job_dir(tmp_path, "alice")
    bob = _job_dir(tmp_path, "bob") / "train_x"
    bob.mkdir(parents=True, exist_ok=True)
    errors = _v(f"#SBATCH --chdir={bob}\n", tmp_path, username="alice")
    assert any("--chdir" in e for e in errors)


def test_validate_sbatch_multiflag_bypass_blocked(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --nice=100 --output=/etc/cron.d/evil\n", tmp_path)
    assert any("--output" in e for e in errors)


def test_validate_sbatch_multiflag_uid_blocked(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --job-name=ok --uid=0\n", tmp_path)
    assert any("--uid" in e for e in errors)


def test_validate_sbatch_rejects_uid_directive(tmp_path):
    _user_dir(tmp_path)
    assert any("--uid" in e for e in _v("#SBATCH --uid=0\n", tmp_path))


def test_validate_sbatch_rejects_gid_directive(tmp_path):
    _user_dir(tmp_path)
    assert any("--gid" in e for e in _v("#SBATCH --gid=0\n", tmp_path))


def test_validate_sbatch_rejects_get_user_env(tmp_path):
    _user_dir(tmp_path)
    assert any("--get-user-env" in e for e in _v("#SBATCH --get-user-env\n", tmp_path))


def test_validate_sbatch_mail_user_fail_closed_without_registered_email(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --mail-user=attacker@evil.com\n", tmp_path, email=None)
    assert any("mail-user" in e for e in errors)


def test_validate_sbatch_mail_user_own_address_ok(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --mail-user=Alice@IIT.lk\n", tmp_path, email="alice@iit.lk")
    assert errors == []


def test_validate_sbatch_mail_user_foreign_rejected(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --mail-user=someone@else.com\n", tmp_path, email="alice@iit.lk")
    assert any("mail-user" in e for e in errors)


def test_validate_sbatch_rejects_excess_gpus(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --gres=gpu:8\n", tmp_path, max_gpus=2)
    assert any("GPU" in e for e in errors)


def test_validate_sbatch_rejects_excess_cpus(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --cpus-per-task=32\n", tmp_path, max_cpus=4)
    assert any("cpus" in e.lower() for e in errors)


def test_validate_sbatch_rejects_excess_mem(tmp_path):
    _user_dir(tmp_path)
    assert any("--mem" in e for e in _v("#SBATCH --mem=2T\n", tmp_path, max_mem_gb=256))
    assert _v("#SBATCH --mem=16384\n", tmp_path, max_mem_gb=16) == []


def test_validate_sbatch_no_false_positives_on_comments(tmp_path):
    _user_dir(tmp_path)
    script = "# This is a comment mentioning --uid and --gid\npython x.py\n"
    assert _v(script, tmp_path) == []


def test_validate_sbatch_ignores_indented_sbatch(tmp_path):
    _user_dir(tmp_path)
    assert _v("   #SBATCH --output=/etc/x\n", tmp_path) == []


def test_validate_sbatch_rejects_excess_shards_against_live_pod_count(tmp_path):
    _user_dir(tmp_path)
    errors = _v("#SBATCH --gres=shard:5\n", tmp_path, node_stats=_stats(4))
    assert any("pod" in e.lower() for e in errors)


def test_validate_sbatch_ceiling_tracks_a_resized_pod_count(tmp_path):
    _user_dir(tmp_path)
    assert _v("#SBATCH --gres=shard:5\n", tmp_path, node_stats=_stats(8)) == []


def test_shard_ceiling_falls_back_to_the_configured_max_when_shards_report_zero(tmp_path):
    _user_dir(tmp_path)
    zero = _stats(0)
    assert pod_ceiling(zero, fallback=4) == 4
    assert pod_ceiling(None, fallback=4) == 4
    assert pod_ceiling(_stats(6), fallback=4) == 6
    assert _v("#SBATCH --gres=shard:4\n", tmp_path, node_stats=zero, max_gpu_shards=4) == []
    over = _v("#SBATCH --gres=shard:5\n", tmp_path, node_stats=zero, max_gpu_shards=4)
    assert any("pod" in e.lower() for e in over), over


def test_validate_sbatch_refuses_an_invalid_username(tmp_path):
    errors = validate_sbatch("#!/bin/bash\n", "..", nfs_root=str(tmp_path))
    assert errors and "username" in errors[0].lower()


# ── validate_against_qos ─────────────────────────────────────────────────────


def test_qos_rejects_too_many_pods():
    ok, msg = validate_against_qos(3, "01:00:00", max_pods=2, max_hours=None)
    assert not ok and "3" in msg


def test_qos_rejects_too_long():
    ok, msg = validate_against_qos(1, "30:00:00", max_pods=2, max_hours=24)
    assert not ok and "24h" in msg


def test_qos_rejects_minutes_past_the_hour_cap():
    ok, _ = validate_against_qos(1, "24:30:00", max_pods=None, max_hours=24)
    assert not ok


def test_qos_none_means_no_cap():
    assert validate_against_qos(99, "999:00:00", max_pods=None, max_hours=None) == (True, "ok")


def test_qos_accepts_within_limits():
    assert validate_against_qos(2, "24:00:00", max_pods=2, max_hours=24) == (True, "ok")
