#!/usr/bin/env bash
# Run on each node (as root) before the cutover: keep a private copy of the account files and
# the ssh drop-ins, and on the login node a dump of the Slurm accounting associations.
#
#   snapshot.sh [<snapshot dir>]      default /var/backups/slurm-deck/cutover-<time>
#
# Files go to <snapshot dir>/<node>/, readable by root only. Prints the snapshot dir, which
# classify.py and rollback.sh take as their argument.
set -euo pipefail
umask 077

ETC="${ETC_DIR:-/etc}"
node="${NODE:-$(hostname -s)}"
dir="${1:-${SNAPSHOT_BASE:-/var/backups/slurm-deck}/cutover-$(date +%Y%m%d-%H%M%S)}"
out="$dir/$node"
mkdir -p "$out"

for f in passwd shadow group gshadow; do cp -p -- "$ETC/$f" "$out/$f"; done
[ -d "$ETC/ssh/sshd_config.d" ] && cp -rp -- "$ETC/ssh/sshd_config.d" "$out/sshd_config.d"
if command -v sacctmgr >/dev/null; then
    cluster="$(sacctmgr -n -P show cluster format=Cluster | head -1)"
    [ -n "$cluster" ] && sacctmgr -i dump "$cluster" file="$out/slurm-dump.txt" >/dev/null
fi
chmod -R go-rwx "$dir"
echo "$dir"
