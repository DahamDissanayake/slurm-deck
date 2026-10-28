"""deck-agent's systemd unit keeps its hardening (SLURM-49 finding 10)."""

import shutil
import subprocess
from pathlib import Path

import pytest

UNIT = Path(__file__).resolve().parents[2] / "deploy/systemd/deck-agent.service"


def _service() -> dict[str, str]:
    section, out = "", {}
    for line in UNIT.read_text().splitlines():
        line = line.strip()
        if line.startswith("["):
            section = line
        elif section == "[Service]" and line and not line.startswith("#"):
            key, _, value = line.partition("=")
            out[key] = value
    return out


def test_the_unit_keeps_only_the_capabilities_deck_agent_uses():
    caps = set(_service()["CapabilityBoundingSet"].split())
    assert caps == {"CAP_SETUID", "CAP_SETGID", "CAP_CHOWN", "CAP_DAC_OVERRIDE",
                    "CAP_DAC_READ_SEARCH", "CAP_FOWNER", "CAP_KILL", "CAP_AUDIT_WRITE"}


def test_the_unit_is_sandboxed():
    s = _service()
    for key in ("NoNewPrivileges", "ProtectKernelTunables", "ProtectKernelModules",
                "ProtectKernelLogs", "ProtectControlGroups", "RestrictNamespaces",
                "LockPersonality", "PrivateTmp"):
        assert s[key] == "yes", key
    # Left out on purpose: it breaks copies inside setgid user folders (see the unit).
    assert "RestrictSUIDSGID" not in s
    assert s["ProtectSystem"] == "strict"
    assert s["ProtectHome"] == "read-only"
    assert s["UMask"] == "0077"
    # Writable: /etc for useradd and resize-pods.sh, the NFS root, useradd's logs.
    assert s["ReadWritePaths"].split() == ["/etc", "-/shared", "-/var/log/lastlog",
                                           "-/var/log/faillog", "-/var/mail"]
    assert s["RuntimeDirectory"] == s["LogsDirectory"] == "slurm-deck-web"


def test_the_unit_runs_as_root_without_a_user_line():
    # SLURM-74: User= with NoNewPrivileges and the sandbox makes systemd drop
    # CAP_SETUID from the permitted set, so every run-as-user call fails.
    assert "User" not in _service()


@pytest.mark.skipif(shutil.which("systemd-analyze") is None, reason="needs systemd-analyze")
def test_systemd_accepts_the_unit():
    r = subprocess.run(["systemd-analyze", "verify", "--man=no", str(UNIT)],
                       capture_output=True, text=True)
    # The venv and env file only exist on an installed host.
    noise = ("agent-venv", "agent.env", "Command ", "is not executable")
    errors = [ln for ln in r.stderr.splitlines() if ln and not any(n in ln for n in noise)]
    assert errors == []
