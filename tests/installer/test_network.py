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


def _setup(tmp_path, *, nft="", ipt="", ipt_filter="", hook=None):
    """A bin dir of fakes that log `name args` and print the given rulesets."""
    bindir, log = tmp_path / "bin", tmp_path / "calls.log"
    bindir.mkdir()
    (tmp_path / "nft.out").write_text(nft)
    (tmp_path / "ipt.out").write_text(ipt)
    (tmp_path / "ipt-filter.out").write_text(ipt_filter)
    drain = "[ -t 0 ] || cat >/dev/null"   # a script may pipe rules in
    fakes = {"nft": f'case "$*" in *"list ruleset"*) cat "$T/nft.out";; esac; {drain}',
             "iptables": 'case "$*" in *"-t filter -S"*) cat "$T/ipt-filter.out";; '
                         '*" -S"*) cat "$T/ipt.out";; *" -C "*) exit 1;; esac',
             "iptables-restore": 'cat > "$T/restored"; '
                                 'exit "$(cat "$T/restore.code" 2>/dev/null || echo 0)"'}
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
            "LIBVIRT_HOOK": str(tmp_path / "hook"),
            "SD_IPTABLES_RULES": str(tmp_path / "rules.v4"), **env}
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


# The live GPU host (SLURM-50): libvirt's LIBVIRT_FWI rejects new connections into virbr0,
# so the 2225 forward also has FORWARD accept rules, an OUTPUT -o lo DNAT, and is saved in
# /etc/iptables/rules.v4.
SSH_PRE = "-A PREROUTING -p tcp -m tcp --dport 2225 -j DNAT --to-destination 192.168.122.10:22"
SSH_OUT = "-A OUTPUT -o lo -p tcp -m tcp --dport 2225 -j DNAT --to-destination 192.168.122.10:22"
SSH_FWD = ("-A FORWARD -d 192.168.122.10/32 -o virbr0 -p tcp -m tcp --dport 22 "
           "-m conntrack --ctstate NEW,RELATED,ESTABLISHED -j ACCEPT")
SSH_BACK = ("-A FORWARD -s 192.168.122.10/32 -i virbr0 -p tcp -m tcp --sport 22 "
            "-m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT")
LIBVIRT_JUMPS = ["-A FORWARD -j LIBVIRT_FWX", "-A FORWARD -j LIBVIRT_FWI",
                 "-A FORWARD -j LIBVIRT_FWO"]
POSTROUTING = "-A POSTROUTING -s 192.168.122.0/24 -j LIBVIRT_PRT"
WEB = {
    "fwd": "-A FORWARD -d 192.168.122.20/32 -o virbr0 -p tcp -m multiport --dports 80,443 "
           "-m conntrack --ctstate NEW,RELATED,ESTABLISHED -m comment --comment sd-web-forward "
           "-j ACCEPT",
    "back": "-A FORWARD -s 192.168.122.20/32 -i virbr0 -p tcp -m multiport --sports 80,443 "
            "-m conntrack --ctstate RELATED,ESTABLISHED -m comment --comment sd-web-forward "
            "-j ACCEPT",
    "pre": "-A PREROUTING -p tcp -m multiport --dports 80,443 -m comment --comment sd-web-forward "
           "-j DNAT --to-destination 192.168.122.20",
    "out": "-A OUTPUT -o lo -p tcp -m multiport --dports 80,443 "
           "-m comment --comment sd-web-forward -j DNAT --to-destination 192.168.122.20",
}


def _lines(*rules):
    return "".join(f"{r}\n" for r in rules)


def _live_nat(*, output=True, web=False):
    rules = ["-P PREROUTING ACCEPT", "-P OUTPUT ACCEPT", SSH_PRE]
    rules += [WEB["pre"]] if web else []
    rules += [SSH_OUT] if output else []
    rules += [WEB["out"]] if web and output else []
    return _lines(*rules, POSTROUTING)


def _live_filter(*, web=False):
    return _lines("-P FORWARD ACCEPT", *([WEB["fwd"], WEB["back"]] if web else []),
                  SSH_FWD, SSH_BACK, *LIBVIRT_JUMPS)


def _rules_v4(*, web=False):
    """/etc/iptables/rules.v4 as iptables-save writes it; with web, the 80/443 lines sit
    right after the 2225 lines they mirror."""
    nat = [SSH_PRE, *([WEB["pre"]] if web else []), SSH_OUT, *([WEB["out"]] if web else []),
           POSTROUTING]
    flt = [SSH_FWD, *([WEB["fwd"]] if web else []), SSH_BACK, *([WEB["back"]] if web else []),
           *LIBVIRT_JUMPS]
    return _lines("*nat", ":PREROUTING ACCEPT [0:0]", ":OUTPUT ACCEPT [0:0]", *nat, "COMMIT",
                  "*filter", ":FORWARD ACCEPT [0:0]", *flt, "COMMIT")


def test_iptables_apply_mirrors_the_2225_forward_accept_and_output_rules(tmp_path):
    bindir = _setup(tmp_path, ipt=_live_nat(), ipt_filter=_live_filter())
    r = _run(tmp_path, bindir, "--apply")
    assert r.returncode == 0, r.stderr
    calls = _calls(tmp_path)
    assert "iptables -t nat " + WEB["pre"] in calls
    assert "iptables -t nat " + WEB["out"] in calls
    # Inserted at the top of FORWARD, so before the LIBVIRT_* jumps.
    for key in ("fwd", "back"):
        assert "iptables -t filter -I FORWARD 1 " + WEB[key][len("-A FORWARD "):] in calls
    assert "MASQUERADE" not in calls   # the app needs the clients' addresses


def test_iptables_output_dnat_only_when_2225_has_one(tmp_path):
    bindir = _setup(tmp_path, ipt=_live_nat(output=False), ipt_filter=_live_filter())
    assert _run(tmp_path, bindir, "--apply").returncode == 0
    assert "-A OUTPUT" not in _calls(tmp_path)
    assert WEB["pre"] in _calls(tmp_path)


def test_iptables_apply_saves_the_rules_next_to_the_2225_lines(tmp_path):
    bindir = _setup(tmp_path, ipt=_live_nat(), ipt_filter=_live_filter())
    (tmp_path / "rules.v4").write_text(_rules_v4())
    r = _run(tmp_path, bindir, "--apply")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "rules.v4").read_text() == _rules_v4(web=True)
    assert "iptables-restore --test" in _calls(tmp_path)
    assert (tmp_path / "restored").read_text() == _rules_v4(web=True)
    assert [p.read_text() for p in tmp_path.glob("rules.v4.*.bak")] == [_rules_v4()]


def test_iptables_rules_file_left_alone_when_the_restore_test_fails(tmp_path):
    bindir = _setup(tmp_path, ipt=_live_nat(), ipt_filter=_live_filter())
    (tmp_path / "rules.v4").write_text(_rules_v4())
    (tmp_path / "restore.code").write_text("1")
    r = _run(tmp_path, bindir, "--apply")
    assert r.returncode != 0
    assert (tmp_path / "rules.v4").read_text() == _rules_v4()


def test_iptables_check_lists_the_rules_in_place_and_remove_deletes_them_all(tmp_path):
    bindir = _setup(tmp_path, ipt=_live_nat(web=True), ipt_filter=_live_filter(web=True))
    (tmp_path / "rules.v4").write_text(_rules_v4(web=True))
    r = _run(tmp_path, bindir, "--check")
    assert r.returncode == 0, r.stderr
    for rule in WEB.values():
        assert rule in r.stdout
    changes = [c for c in _calls(tmp_path).splitlines()
               if c.startswith("iptables") and not c.endswith(" -S")]
    assert changes == []   # --check changes nothing
    assert (tmp_path / "rules.v4").read_text() == _rules_v4(web=True)
    (tmp_path / "calls.log").unlink()
    assert _run(tmp_path, bindir, "--remove").returncode == 0
    calls = _calls(tmp_path)
    for key, table in (("pre", "nat"), ("out", "nat"), ("fwd", "filter"), ("back", "filter")):
        assert f"iptables -t {table} -D" + WEB[key][2:] in calls, key
    assert (tmp_path / "rules.v4").read_text() == _rules_v4()


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


def test_the_sessions_mdns_unit_publishes_the_session_name():
    unit = (GPUHOST / "sd-mdns-sessions.service").read_text()
    assert "ExecStart=/usr/bin/avahi-publish -a -R ${SESSION_HOSTNAME} ${LAN_ADDR}" in unit
    assert "EnvironmentFile=/etc/slurm-deck-web/gpu-helper.env" in unit
    assert "Restart=always" in unit
