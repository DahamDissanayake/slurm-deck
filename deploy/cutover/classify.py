#!/usr/bin/env python3
"""Sort the login node's accounts for the cutover: classify.py <snapshot dir>

Reads <snapshot dir>/<node>/{passwd,group} and writes cutover-plan.json beside them:

  remove    in gpuusers or gpuadmins, uid >= 1000, not a sysadmin, not a shell user
  shell     real-shell people who keep their login (on the shell list, or in neither GPU group)
  sysadmin  the site's SYSADMINS: never touched
  service   system accounts and the web platform's own accounts (webusers): never touched
  flagged   in a GPU group *and* on the shell list: decided by a person, never removed
  uids      every classified user's uid, so admins can reconnect their folders afterwards

The shell list is the members of group `shellusers` plus SHELL_USERS (comma separated);
the sysadmins are SYSADMINS. Nothing is changed: this only reads the snapshot.
"""

from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

UID_MIN = 1000
GPU_GROUPS = ("gpuusers", "gpuadmins")
NOLOGIN = ("nologin", "false")


def _rows(path: Path) -> list[list[str]]:
    return [ln.split(":") for ln in path.read_text().splitlines() if ln and not ln.startswith("#")]


def classify(passwd: list[list[str]], group: list[list[str]], sysadmins: set[str],
             shell_list: set[str]) -> dict:
    members = {g[0]: set(filter(None, g[3].split(","))) | {p[0] for p in passwd if p[3] == g[2]}
               for g in group}
    gpu = set().union(*(members.get(g, set()) for g in GPU_GROUPS))
    shell_list = shell_list | members.get("shellusers", set())
    web = members.get("webusers", set())
    plan: dict = {"remove": [], "shell": [], "sysadmin": [], "service": [], "flagged": [],
                  "uids": {}}
    for name, _, uid, _, _, _, shell in (p[:7] for p in passwd):
        uid = int(uid)
        plan["uids"][name] = uid
        real_shell = bool(shell) and not shell.endswith(NOLOGIN)
        if name in sysadmins:
            plan["sysadmin"].append(name)
        elif uid < UID_MIN or name in web or uid >= 65534:
            plan["service"].append(name)
        elif name in gpu and name in shell_list:
            plan["flagged"].append({"user": name,
                                    "reason": "in a GPU group and also on the shell list"})
        elif name in shell_list or (real_shell and name not in gpu):
            plan["shell"].append(name)
        elif name in gpu:
            plan["remove"].append(name)
        else:
            plan["service"].append(name)   # no shell and not a GPU user: not ours to remove
    for key in ("remove", "shell", "sysadmin", "service"):
        plan[key].sort()
    return plan


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 64
    snap = Path(argv[1])
    node = os.environ.get("NODE") or socket.gethostname().split(".")[0]
    if not (snap / node).is_dir():
        nodes = [d for d in snap.iterdir() if (d / "passwd").exists()]
        if len(nodes) != 1:
            print(f"{snap / node} does not exist; set NODE to the login node's name", file=sys.stderr)
            return 1
        node = nodes[0].name
    split = lambda v: {u for u in v.replace(" ", "").split(",") if u}   # noqa: E731
    plan = classify(_rows(snap / node / "passwd"), _rows(snap / node / "group"),
                    split(os.environ.get("SYSADMINS", "")), split(os.environ.get("SHELL_USERS", "")))
    (snap / "cutover-plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    print(f"{snap / 'cutover-plan.json'}: remove {len(plan['remove'])}, shell {len(plan['shell'])}, "
          f"sysadmin {len(plan['sysadmin'])}, flagged {len(plan['flagged'])}")
    for f in plan["flagged"]:
        print(f"  flagged {f['user']}: {f['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
