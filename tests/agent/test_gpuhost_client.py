"""deck-agent's GPU-host client, against a fake ssh that logs its arguments."""

import sys
from pathlib import Path

import pytest

if sys.platform != "linux":
    pytest.skip("needs a POSIX shell for the fake ssh", allow_module_level=True)

from deckagent.config import load_config  # noqa: E402
from deckagent.gpuhost import FolderInfo, GpuHost  # noqa: E402
from deckagent.protocol import AgentError  # noqa: E402

CONFIG = load_config({"SD_WEB_UID": "1", "SD_WORKER_UID": "2",
                      "SD_GPU_HELPER_SSH": "sdprov@gpu-host", "SD_GPU_HELPER_KEY": "/k"})


def _host(tmp_path: Path, stdout: str, code: int = 0) -> tuple[GpuHost, Path]:
    log = tmp_path / "ssh.log"
    fake = tmp_path / "ssh"
    fake.write_text(f"#!/bin/sh\necho \"$@\" >> {log}\nprintf '%s' '{stdout}'\nexit {code}\n")
    fake.chmod(0o755)
    return GpuHost(CONFIG, ssh=str(fake)), log


def test_runs_the_forced_command_over_ssh(tmp_path):
    host, log = _host(tmp_path, '{"ok": true}')
    host.create_account("amasha", 20001)
    assert log.read_text().strip() == ("-i /k -o BatchMode=yes -o StrictHostKeyChecking=yes "
                                       "sdprov@gpu-host create-account amasha 20001")


def test_exit_2_is_403(tmp_path):
    host, _ = _host(tmp_path, '{"ok": false, "error": "refused"}', code=2)
    with pytest.raises(AgentError) as e:
        host.purge("amasha")
    assert (e.value.code, e.value.status) == ("gpuhost_refused", 403)


@pytest.mark.parametrize("code, out", [(1, '{"ok": false}'), (255, ""), (0, "not json")])
def test_other_failures_are_502(tmp_path, code, out):
    host, _ = _host(tmp_path, out, code=code)
    with pytest.raises(AgentError) as e:
        host.archive("amasha")
    assert (e.value.code, e.value.status) == ("gpuhost_failed", 502)


def test_folder_info_and_ping(tmp_path):
    host, _ = _host(tmp_path, '{"ok": true, "exists": true, "owner_uid": 20001, '
                              '"bytes": 4096, "mtime": "2026-10-24T10:00:00+00:00"}')
    assert host.folder_info("amasha") == FolderInfo(True, 20001, 4096,
                                                    "2026-10-24T10:00:00+00:00")
    pong, _ = _host(tmp_path, '{"ok": true, "pong": true}')
    assert pong.ping() is True
    down, _ = _host(tmp_path, "", code=255)
    assert down.ping() is False


@pytest.mark.parametrize("user", ["..", "a/b", "root", "x; id"])
def test_client_refuses_bad_usernames_before_ssh(tmp_path, user):
    host, log = _host(tmp_path, '{"ok": true}')
    with pytest.raises(AgentError) as e:
        host.purge(user)
    assert e.value.status == 400 and not log.exists()


def test_unconfigured_helper_is_502(tmp_path):
    host = GpuHost(load_config({"SD_WEB_UID": "1", "SD_WORKER_UID": "2"}))
    with pytest.raises(AgentError) as e:
        host.archive("amasha")
    assert e.value.status == 502
    assert host.ping() is False
