"""account.* verbs: who may call them, the UID rules, and rollback."""

import pytest

from sdweb.agent import AgentCallError

ADMIN = "admin:dinuka"


def _err(agent, verb, payload, as_=ADMIN) -> AgentCallError:
    with pytest.raises(AgentCallError) as e:
        agent.call(verb, payload, as_=as_)
    return e.value


def test_create_runs_every_step(agent):
    agent.call("account.create", {"username": "kasun", "uid": 20005}, as_=ADMIN)
    calls = agent.calls()
    for line in ("groupadd -g 20005 kasun",
                 "useradd -u 20005 -g 20005 -M -d /home/kasun -s /usr/sbin/nologin "
                 "-G webusers,gpuusers kasun", "passwd -l kasun",
                 "sacctmgr -i add user kasun account=default qos=normal",
                 "create-account kasun 20005", "create-folders kasun 20005"):
        assert line in calls, line


def test_create_rolls_back_on_gpuhost_failure(agent):
    (agent.dir / "ssh.failon").write_text("create-folders")
    e = _err(agent, "account.create", {"username": "x", "uid": 20006})
    assert (e.code, e.status) == ("account_create_failed", 502)
    calls = agent.calls()
    assert "userdel x" in calls and "groupdel x" in calls
    assert "sacctmgr -i delete user x" in calls and "delete-account x" in calls


@pytest.mark.parametrize("as_", ["worker", "user:amasha"])
def test_worker_and_users_cannot_call_account_verbs(agent, as_):
    for verb in ("account.create", "account.delete", "account.attach_shell",
                 "account.inspect_folder"):
        assert _err(agent, verb, {"username": "kasun", "uid": 20005}, as_=as_).status == 403
    assert agent.calls() == ""


def test_create_refuses_uid_outside_range(agent):
    e = _err(agent, "account.create", {"username": "kasun", "uid": 1500})
    assert e.status == 409 and agent.calls() == ""


def test_create_link_existing_requires_matching_owner(agent, monkeypatch):
    from deckagent.gpuhost import FolderInfo, GpuHost

    monkeypatch.setattr(GpuHost, "folder_info", lambda self, u: FolderInfo(True, 2014, 1, "t"))
    e = _err(agent, "account.create", {"username": "kasun", "uid": 2015, "link_existing": True})
    assert e.status == 409 and "groupadd" not in agent.calls()
    agent.call("account.create", {"username": "kasun", "uid": 2014, "link_existing": True},
               as_=ADMIN)
    assert "create-account kasun 2014" in agent.calls()
    assert "create-folders" not in agent.calls()


@pytest.mark.parametrize("name", ["root", "sdweb", "Bad Name", "../x"])
def test_create_refuses_bad_names(agent, name):
    assert _err(agent, "account.create", {"username": name, "uid": 20007}).status == 422


def test_delete_refuses_non_webuser(agent):
    e = _err(agent, "account.delete", {"username": "shelly", "purge": False})
    assert e.status == 403 and agent.calls() == ""


def test_delete_runs_every_step(agent, monkeypatch):
    from deckagent.verbs import accounts

    monkeypatch.setattr(accounts, "_groups", lambda name: {"webusers", "gpuusers"})
    agent.call("account.delete", {"username": "kasun", "purge": True}, as_=ADMIN)
    calls = agent.calls().splitlines()
    order = ["scancel -u kasun", "sacctmgr -i delete user kasun", "purge kasun",
             "delete-account kasun", "pkill -KILL -u kasun", "userdel kasun", "groupdel kasun"]
    found = [next(i for i, c in enumerate(calls) if want in c) for want in order]
    assert found == sorted(found)


def test_attach_shell_refuses_webusers_and_unknown(agent, monkeypatch):
    from deckagent.verbs import accounts

    assert _err(agent, "account.attach_shell", {"username": "nobody-here"}).status == 403
    monkeypatch.setattr(accounts, "_lookup",
                        lambda name: (accounts.PosixIdentity(name, 1500, 1500, (), "/h"),
                                      frozenset({"gpuusers"})))
    assert agent.call("account.attach_shell", {"username": "kamal"}, as_=ADMIN) == {"uid": 1500}
    monkeypatch.setattr(accounts, "_lookup",
                        lambda name: (accounts.PosixIdentity(name, 1500, 1500, (), "/h"),
                                      frozenset({"webusers"})))
    assert _err(agent, "account.attach_shell", {"username": "kamal"}).status == 403
