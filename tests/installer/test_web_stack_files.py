"""The Compose stack and Caddyfile keep the web containers unprivileged."""

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")   # comes with uvicorn[standard]

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"


def _services() -> dict:
    return yaml.safe_load((DEPLOY / "compose.yaml").read_text())["services"]


def test_no_service_mounts_shared_docker_socket_or_munge():
    for name, svc in _services().items():
        for vol in svc.get("volumes", []):
            source = vol if isinstance(vol, str) else vol.get("source", "")
            source = source.split(":")[0]
            assert not source.startswith("/shared"), name
            assert "docker.sock" not in source, name
            assert "munge" not in source and "/etc/shadow" not in source, name


def test_web_and_worker_carry_the_agent_socket_group():
    # deck-agent's socket is root:sd-agent 0660; containers get no host groups.
    services = _services()
    for name in ("web", "worker"):
        assert services[name]["group_add"] == ["${SD_AGENT_GID:?set SD_AGENT_GID}"], name
    for name in ("migrate", "caddy", "db"):
        assert "group_add" not in services.get(name, {}), name


@pytest.mark.parametrize("name", ["web", "worker", "migrate"])
def test_app_containers_are_non_root_read_only_without_capabilities(name):
    svc = _services()[name]
    user = svc["user"]
    assert user.startswith("${SD_") and not user.startswith("0")
    assert svc["read_only"] is True
    assert svc["cap_drop"] == ["ALL"] and "cap_add" not in svc
    assert "no-new-privileges:true" in svc["security_opt"]


def test_only_caddy_publishes_public_ports():
    for name, svc in _services().items():
        for port in svc.get("ports", []):
            assert name == "caddy" or str(port).startswith("127.0.0.1:"), name


def test_caddy_serves_the_ca_and_redirects_http():
    text = (DEPLOY / "Caddyfile").read_text()
    assert "tls internal" in text
    assert "/ca.crt" in text and "root.crt" in text
    assert "redir https://{host}{uri}" in text


def test_caddy_serves_sessions_on_their_own_name():
    text = (DEPLOY / "Caddyfile").read_text()
    assert "http://{$SD_SESSION_HOSTNAME} {" in text
    block = text.split("\n{$SD_SESSION_HOSTNAME} {", 1)[1]
    assert "tls internal" in block and "reverse_proxy web:8000" in block
    assert "flush_interval -1" in block and "/ca.crt" not in block
    caddy_env = _services()["caddy"]["environment"]
    assert caddy_env["SD_SESSION_HOSTNAME"].startswith("${SD_SESSION_HOSTNAME:?")
