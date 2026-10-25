#!/usr/bin/env bash
# Undo the cutover on one node, from the snapshot snapshot.sh took (and the cutover-plan.json
# beside it). Only possible before retire-tui.sh.
#
#   rollback.sh --check <snapshot dir>     list what would come back; change nothing
#   rollback.sh --apply <snapshot dir>
#
# Puts the removed accounts back from the snapshot's passwd, shadow, group and gshadow, restores
# the ssh drop-ins (the ForceCommand one) and takes the cutover's AllowGroups out, and on the
# login node reloads the Slurm associations from the dump. Exit 3, changing nothing, when a
# removed user's name or UID is now held by another account (a web account, say): reusing it
# would give someone else's files to the wrong person.
set -euo pipefail

ETC="${ETC_DIR:-/etc}"
node="${NODE:-$(hostname -s)}"
mode="${1#--}"
snap="${2:-}"
[[ "$mode" =~ ^(check|apply)$ ]] && [ -d "$snap/$node" ] && [ -f "$snap/cutover-plan.json" ] || {
    echo "usage: $0 --check|--apply <snapshot dir> (with cutover-plan.json, and a folder for node $node)" >&2; exit 64; }
cd "$snap/$node"

removed=($(python3 -c 'import json; print(*json.load(open("../cutover-plan.json"))["remove"])'))
conflicts=() restore=()
for u in "${removed[@]}"; do
    row="$(grep -m1 "^$u:" passwd || true)"
    [ -n "$row" ] || continue
    uid="$(cut -d: -f3 <<<"$row")"
    now_uid="$(awk -F: -v u="$u" '$1 == u {print $3}' "$ETC/passwd")"
    holder="$(awk -F: -v i="$uid" '$3 == i {print $1}' "$ETC/passwd" | head -1)"
    if [ "$now_uid" = "$uid" ]; then continue                        # already back
    elif [ -n "$now_uid" ]; then conflicts+=("$u: the name now has uid $now_uid")
    elif [ -n "$holder" ]; then conflicts+=("$u (uid $uid): the uid is now held by $holder")
    else restore+=("$u"); fi
done
if [ ${#conflicts[@]} -gt 0 ]; then
    echo "Refusing to roll back; these clash with accounts that exist now:"
    printf '  %s\n' "${conflicts[@]}"
    exit 3
fi

act() { if [ "$mode" = check ]; then printf 'would run:'; printf ' %q' "$@"; echo; else "$@"; fi; }
echo "restoring accounts: ${restore[*]:-none}"
if [ "$mode" = apply ] && [ ${#restore[@]} -gt 0 ]; then
    for f in passwd shadow group gshadow; do
        cp -p -- "$ETC/$f" "$ETC/$f.rollback"
        for u in "${restore[@]}"; do grep "^$u:" "$f" >> "$ETC/$f.rollback" || true; done
        mv -f -- "$ETC/$f.rollback" "$ETC/$f"
    done
fi
for u in "${restore[@]}"; do   # their other group memberships
    groups="$(awk -F: -v u="$u" 'NR == FNR {have[$1] = 1; next}
        have[$1] && $1 != u && ("," $4 ",") ~ ("," u ",") {printf "%s%s", s, $1; s = ","}' "$ETC/group" group)"
    [ -z "$groups" ] || act usermod -aG "$groups" "$u"
done

echo "restoring the ssh drop-ins"
if [ -d sshd_config.d ]; then
    for f in sshd_config.d/*; do [ -e "$f" ] && act cp -p -- "$f" "$ETC/ssh/sshd_config.d/"; done
fi
act rm -f -- "$ETC/ssh/sshd_config.d/10-slurm-deck-cutover.conf"
if [ "$mode" = apply ]; then sshd -t && systemctl reload sshd; else echo "would run: sshd -t, then reload sshd"; fi

if [ -f slurm-dump.txt ] && command -v sacctmgr >/dev/null; then
    act sacctmgr -i load file="$PWD/slurm-dump.txt"
fi
echo "rollback ${mode} done"
