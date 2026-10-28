"""The login node's Postgres firewall (SLURM-66): only root (deck-agent) may open a TCP
connection to the database port, on loopback or a Docker bridge."""

import shutil
import subprocess
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
NFT = DEPLOY / "cluster" / "sd-db-port.nft"
UNIT = DEPLOY / "systemd" / "sd-db-firewall.service"


def _rules() -> list[str]:
    return [line.strip() for line in NFT.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")]


def test_root_is_let_through_before_anyone_is_refused():
    rules = _rules()
    accept = rules.index("tcp dport $DB_PORT meta skuid 0 accept")
    refused = [i for i, r in enumerate(rules) if r.endswith("reject with tcp reset")]
    assert refused and accept < min(refused)


@pytest.mark.parametrize("iface", ['"lo"', '"docker0"', '"br-*"'])
def test_other_users_are_refused_on_loopback_and_the_docker_bridges(iface):
    assert f"tcp dport $DB_PORT oifname {iface} reject with tcp reset" in _rules()


def test_the_hook_sees_the_address_before_docker_rewrites_it():
    text = NFT.read_text()
    assert "type filter hook output priority -150; policy accept;" in text   # before dstnat (-100)
    assert "table inet sd_db" in text and "define DB_PORT = 5432" in text


def test_loading_the_file_twice_replaces_the_table():
    rules = _rules()
    assert rules.index("table inet sd_db") < rules.index("delete table inet sd_db")


def test_the_nft_file_parses():
    if not shutil.which("nft"):
        pytest.skip("nft isn't installed here")
    r = subprocess.run(["nft", "-c", "-f", str(NFT)], capture_output=True, text=True)
    if "ermitted" in r.stderr:
        pytest.skip("nft -c needs privileges here")
    assert r.returncode == 0, r.stderr


def test_the_unit_loads_the_file_at_boot_and_again_after_nftables_reloads():
    unit = UNIT.read_text()
    assert "ExecStart=/usr/sbin/nft -f /usr/local/lib/slurm-deck/sd-db-port.nft" in unit
    assert "ExecStop=/usr/sbin/nft delete table inet sd_db" in unit
    assert "Type=oneshot" in unit and "RemainAfterExit=yes" in unit
    assert "Before=docker.service" in unit and "PartOf=nftables.service" in unit
    assert "WantedBy=multi-user.target" in unit
