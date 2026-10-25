"""sd-web-forward.sh against fake nft, iptables and a fake libvirt hook; the nft file and the
mDNS unit. Needs bash, so these run on Linux (CI)."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

GPUHOST = Path(__file__).resolve().parents[2] / "deploy" / "cluster" / "gpuhost"
SCRIPT = GPUHOST / "sd-web-forward.sh"

pytestmark = pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bash"),
                                reason="the network scripts run on Linux")

ENV = ("LAN_ADDR=10.35.4.100\nLOGIN_ADDR=192.168.122.20\nGPU_HOST=192.168.122.1\n"
       "PUBLIC_HOSTNAME=slurmdeck.local\n")
NFT_RULESET = """table ip nat {
\tchain prerouting {
\t\ttype nat hook prerouting priority dstnat; policy accept;
\t\tip daddr 10.35.4.100 tcp dport 2225 dnat to 192.168.122.10:22 # handle 7
\t}
}
"""
IPT_RULESET = ("-P PREROUTING ACCEPT\n-A PREROUTING -d 10.35.4.100/32 -p tcp -m tcp --dport 2225 "
               "-j DNAT --to-destination 192.168.122.10:22\n")
HOOK = ('if [ "$1" = "guest" ]; then\n  iptables -t nat -A PREROUTING -p tcp --dport 2225 '
        '-j DNAT --to-destination 192.168.122.10:22\nfi\n')


def _setup(tmp_path, *, nft="", ipt="", hook=None):
    """A bin dir of fakes that log `name args` and print the given rulesets."""
    bindir, log = tmp_path / "bin", tmp_path / "calls.log"
    bindir.mkdir()
    (tmp_path / "nft.out").write_text(nft)
    (tmp_path / "ipt.out").write_text(ipt)
    drain = "[ -t 0 ] || cat >/dev/null"   # a script may pipe rules in
    fakes = {"nft": f'case "$*" in *"list ruleset"*) cat "$T/nft.out";; esac; {drain}',
             "iptables": 'case "$*" in *" -S"*) cat "$T/ipt.out";; *" -C "*) exit 1;; esac'}
    for name, body in fakes.items():
        f = bindir / name
        f.write_text(f'#!/bin/bash\necho "{name} $*" >> "{log}"\n{body}\n')
        f.chmod(0o755)
    (tmp_path / "gpu-helper.env").write_text(ENV)
    if hook is not None:
        (tmp_path / "hook").write_text(hook)
    return bindir


def _run(tmp_path, bindir, mode, **env):
    full = {"PATH": f"{bindir}:/usr/bin:/bin", "T": str(tmp_path), "HOME": str(tmp_path),
            "SD_ENV_FILE": str(tmp_path / "gpu-helper.env"),
            "LIBVIRT_HOOK": str(tmp_path / "hook"), **env}
    return subprocess.run(["bash", str(SCRIPT), mode], capture_output=True, text=True, env=full)


def _calls(tmp_path):
    log = tmp_path / "calls.log"
    return log.read_text() if log.exists() else ""


def test_check_detects_nftables_forward(tmp_path):
    bindir = _setup(tmp_path, nft=NFT_RULESET)
    r = _run(tmp_path, bindir, "--check")
    assert r.returncode == 0, r.stderr
    assert "mechanism: nftables" in r.stdout
    assert 'nft add rule ip nat prerouting ip daddr 10.35.4.100 tcp dport { 80, 443 } ' \
           'dnat to 192.168.122.20 comment' in r.stdout.replace("\\", "")
    assert "nft add" not in _calls(tmp_path)   # --check changes nothing


def test_apply_adds_the_rule_once_and_remove_deletes_it(tmp_path):
    bindir = _setup(tmp_path, nft=NFT_RULESET)
    assert _run(tmp_path, bindir, "--apply").returncode == 0
    assert "nft add rule ip nat prerouting" in _calls(tmp_path)
    assert "sd-web-forward" in _calls(tmp_path)
    tagged = NFT_RULESET.replace("}\n}\n", '\t\ttcp dport { 80, 443 } dnat to 192.168.122.20 '
                                 'comment "sd-web-forward" # handle 9\n\t}\n}\n')
    (tmp_path / "nft.out").write_text(tagged)
    (tmp_path / "calls.log").unlink()
    assert "already" in _run(tmp_path, bindir, "--apply").stdout
    assert "nft add rule" not in _calls(tmp_path)
    assert _run(tmp_path, bindir, "--remove").returncode == 0
    assert "nft delete rule ip nat prerouting handle 9" in _calls(tmp_path)


def test_check_detects_an_iptables_forward(tmp_path):
    bindir = _setup(tmp_path, ipt=IPT_RULESET)
    r = _run(tmp_path, bindir, "--check")
    assert r.returncode == 0 and "mechanism: iptables" in r.stdout
    plan = r.stdout.replace("\\", "")   # the plan shows each argument shell-quoted
    assert "multiport --dports 80,443" in plan and "--to-destination 192.168.122.20" in plan
    assert "iptables -t nat -A" not in _calls(tmp_path)


def test_check_detects_a_libvirt_hook_and_apply_adds_lines_next_to_the_2225_rule(tmp_path):
    bindir = _setup(tmp_path, hook=HOOK)
    assert "mechanism: libvirt-hook" in _run(tmp_path, bindir, "--check").stdout
    assert _run(tmp_path, bindir, "--apply").returncode == 0
    text = (tmp_path / "hook").read_text()
    assert "--dport 443 -j DNAT --to-destination 192.168.122.20:443" in text
    assert text.index("--dport 2225") < text.index("--dport 443") < text.index("\nfi\n")
    assert _run(tmp_path, bindir, "--remove").returncode == 0
    assert (tmp_path / "hook").read_text() == HOOK


def test_no_detectable_forward_exits_2_with_the_plain_message(tmp_path):
    bindir = _setup(tmp_path)
    r = _run(tmp_path, bindir, "--check")
    assert r.returncode == 2
    assert "Couldn't find how port 2225 is forwarded; set up the 443 forward by hand." in r.stderr


def test_missing_site_values_are_reported(tmp_path):
    bindir = _setup(tmp_path, nft=NFT_RULESET)
    (tmp_path / "gpu-helper.env").write_text("LAN_ADDR=10.35.4.100\n")
    r = _run(tmp_path, bindir, "--check")
    assert r.returncode == 1 and "LOGIN_ADDR" in r.stderr


def test_the_session_port_firewall_is_loaded_with_the_site_values(tmp_path):
    bindir = _setup(tmp_path, nft=NFT_RULESET)
    r = _run(tmp_path, bindir, "--check")
    assert "sd_sessions" in r.stdout and "192.168.122.20" in r.stdout and "8800-8999" in r.stdout


def test_the_nft_file_only_lets_the_login_node_reach_the_session_ports():
    path = GPUHOST / "sd-session-ports.nft"
    text = path.read_text()
    assert "table inet sd_sessions" in text and "ip saddr $LOGIN_ADDR accept" in text
    assert text.rstrip().count("drop") == 1
    if shutil.which("nft"):
        r = subprocess.run(["nft", "-c", "-f", str(path)], capture_output=True, text=True)
        if "ermitted" in r.stderr:
            pytest.skip("nft -c needs privileges here")
        assert r.returncode == 0, r.stderr


def test_the_mdns_alias_unit_publishes_the_site_name_and_address():
    unit = (GPUHOST / "sd-mdns-alias.service").read_text()
    assert "ExecStart=/usr/bin/avahi-publish -a -R ${PUBLIC_HOSTNAME} ${LAN_ADDR}" in unit
    assert "EnvironmentFile=/etc/slurm-deck-web/gpu-helper.env" in unit
    assert "Restart=always" in unit
