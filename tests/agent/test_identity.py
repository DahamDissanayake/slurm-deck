"""Which Linux identity a caller may use, against fake pwd/grp databases."""

from types import SimpleNamespace

import pytest

from deckagent.config import load_config
from deckagent.identity import PosixIdentity, identity_for_user, ops_identity
from deckagent.protocol import AgentError, Caller

CONFIG = load_config({"SD_WEB_UID": "1001", "SD_WORKER_UID": "1002"})


def _pw(name, uid, gid=None, home=None):
    return SimpleNamespace(pw_name=name, pw_uid=uid, pw_gid=gid if gid is not None else uid,
                           pw_dir=home or f"/home/{name}")


def _gr(name, gid, members=()):
    return SimpleNamespace(gr_name=name, gr_gid=gid, gr_mem=list(members))


class FakePwd:
    def __init__(self, *entries):
        self.entries = {e.pw_name: e for e in entries}

    def getpwnam(self, name):
        return self.entries[name]


class FakeGrp:
    def __init__(self, *groups):
        self.groups = groups

    def getgrall(self):
        return list(self.groups)


PW = FakePwd(_pw("amasha", 20001), _pw("rootish", 0), _pw("kamal", 1500),
             _pw("sudoer", 1600), _pw("labadmin", 1700), _pw("nimal", 1800),
             _pw("daemonish", 999), _pw("loner", 20002), _pw("sd-ops", 1900, 1950),
             _pw("bossy", 1950))
GR = FakeGrp(_gr("webusers", 3000, ["amasha", "rootish", "daemonish"]),
             _gr("gpuusers", 3001, ["amasha", "kamal", "sudoer"]),
             _gr("sudo", 27, ["sudoer"]), _gr("gpuadmins", 3002, ["labadmin", "sd-ops"]),
             _gr("admin", 3003, ["nimal"]))


def _user(name, kind="hidden", role="user"):
    return Caller(name, role, kind, False, None)


def _refused(caller, pw=PW, gr=GR):
    with pytest.raises(AgentError) as e:
        identity_for_user(caller, CONFIG, pw=pw, gr=gr)
    assert (e.value.code, e.value.status) == ("identity_refused", 403)


def test_root_never_allowed():
    _refused(_user("rootish"))                  # in webusers, but uid 0
    _refused(_user("rootish", kind="shell"))


@pytest.mark.parametrize("name", ["slurmadmin", "root", "sd-ops", "sdweb"])
def test_reserved_name_refused(name):
    pw = FakePwd(_pw(name, 20500))
    _refused(_user(name), pw=pw, gr=FakeGrp(_gr("webusers", 3000, [name])))


def test_webuser_allowed():
    ident = identity_for_user(_user("amasha"), CONFIG, pw=PW, gr=GR)
    assert ident == PosixIdentity("amasha", 20001, 20001, (3000, 3001), "/home/amasha")


def test_shell_user_allowed_when_unprivileged():
    ident = identity_for_user(_user("kamal", kind="shell"), CONFIG, pw=PW, gr=GR)
    assert (ident.uid, ident.groups) == (1500, (3001,))


@pytest.mark.parametrize("name", ["sudoer", "labadmin", "nimal"])
def test_shell_user_in_sudo_refused(name):
    _refused(_user(name, kind="shell"))


@pytest.mark.parametrize("caller", [
    _user("daemonish"),                        # webusers member below UID 1000
    _user("loner"),                            # hidden account missing from webusers
    _user("ghost", kind="shell"),              # no such Linux account
    _user("Bad Name", kind="shell"),
    Caller(None, "worker", None, True, None),  # the worker has no Linux identity
])
def test_other_identities_refused(caller):
    _refused(caller)


def test_ops_identity_for_admins_only():
    admin = Caller("dinuka", "admin", "hidden", False, None)
    ident = ops_identity(admin, CONFIG, pw=PW, gr=GR)
    assert (ident.name, ident.uid, ident.gid, ident.groups) == ("sd-ops", 1900, 1950, (3002,))
    with pytest.raises(AgentError) as e:
        ops_identity(_user("amasha"), CONFIG, pw=PW, gr=GR)
    assert e.value.status == 403
