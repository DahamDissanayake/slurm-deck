"""run_as really becomes the user: uid, gid and groups (needs root)."""

import os
import pwd
import secrets
import subprocess
import sys

import pytest

if sys.platform != "linux":
    pytest.skip("run_as needs Linux", allow_module_level=True)

from deckagent.identity import PosixIdentity  # noqa: E402
from deckagent.runas import popen_as, run_as  # noqa: E402


@pytest.fixture
def tmp_user():
    name = f"sdt{secrets.token_hex(4)}"
    subprocess.run(["useradd", "-M", "-s", "/usr/sbin/nologin", name], check=True)
    try:
        p = pwd.getpwnam(name)
        yield PosixIdentity(name, p.pw_uid, p.pw_gid, (p.pw_gid,), "/nonexistent")
    finally:
        subprocess.run(["userdel", name], check=False)


@pytest.mark.root
def test_run_as_really_drops_privileges(tmp_user):
    r = run_as(tmp_user, ["id", "-u"])
    assert r.stdout.strip() == str(tmp_user.uid).encode()
    groups = run_as(tmp_user, ["id", "-G"]).stdout.split()
    assert groups == [str(tmp_user.gid).encode()]          # root's groups are gone
    env = run_as(tmp_user, ["env"]).stdout.decode().splitlines()
    assert sorted(env) == sorted([f"HOME={tmp_user.home}", f"USER={tmp_user.name}",
                                  "PATH=/usr/local/bin:/usr/bin:/bin"])


@pytest.mark.root
def test_run_as_input_and_popen(tmp_user):
    assert run_as(tmp_user, ["cat"], input=b"hello").stdout == b"hello"
    assert run_as(tmp_user, ["cat"]).stdout == b""            # stdin is /dev/null
    with popen_as(tmp_user, ["id", "-un"], stdout=subprocess.PIPE) as p:
        assert p.stdout is not None and p.stdout.read().strip() == tmp_user.name.encode()


def test_run_as_needs_root_when_not_root():
    if os.geteuid() == 0:
        pytest.skip("only meaningful as a normal user")
    me = pwd.getpwuid(os.getuid())
    other = PosixIdentity("x", me.pw_uid + 1, me.pw_gid + 1, (), "/")
    with pytest.raises(PermissionError):
        run_as(other, ["true"])
