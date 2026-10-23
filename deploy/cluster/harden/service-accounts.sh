#!/usr/bin/env bash
# Service accounts and units that replace the legacy ones running as people.
#
#   service-accounts.sh --check    report what would change; change nothing
#   service-accounts.sh --apply
#
# On the GPU host: creates the `sd-stats` system account, installs the stats
# writer to run as it (instead of root-daham), and retires the legacy
# slurm-deck-stats service. On the login node: disables the legacy
# pod-notify timer (it ran as dahamadmin; the web worker replaces it).
# Units that aren't installed on this node are skipped.
set -euo pipefail

NFS_ROOT="${NFS_ROOT:-/shared}"
STATS_USER="sd-stats"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
STATS_FILE="$NFS_ROOT/.gpu_stats.json"
LEGACY_UNITS="slurm-deck-stats.service slurm-deck-pod-notify.timer"

case "${1:-}" in
    --check|--apply) mode="${1#--}" ;;
    *) echo "usage: $0 --check|--apply" >&2; exit 2 ;;
esac

installed() { systemctl list-unit-files "$1" 2>/dev/null | grep -q "^$1"; }

if [ "$mode" = check ]; then
    if id "$STATS_USER" >/dev/null 2>&1; then echo "$STATS_USER: exists"
    else echo "$STATS_USER: missing (would create)"; fi
    for unit in $LEGACY_UNITS; do
        installed "$unit" && echo "$unit: installed (would disable)"
    done
    installed sd-stats-writer.service || echo "sd-stats-writer.service: not installed (would install)"
    exit 0
fi

if ! id "$STATS_USER" >/dev/null 2>&1; then
    useradd --system --no-create-home --shell /usr/sbin/nologin "$STATS_USER"
fi

for unit in $LEGACY_UNITS; do
    if installed "$unit"; then
        systemctl disable --now "$unit"
        echo "disabled $unit"
    fi
done

if [ -x /usr/bin/nvidia-smi ]; then
    install -m 0755 "$SRC/sd-stats-writer" /usr/local/bin/sd-stats-writer
    install -m 0644 "$SRC/../systemd/sd-stats-writer.service" /etc/systemd/system/
    # The writer can't create files in the share root; it rewrites this one in place.
    touch "$STATS_FILE"
    chown "$STATS_USER" "$STATS_FILE"
    chmod 0644 "$STATS_FILE"
    systemctl daemon-reload
    systemctl enable --now sd-stats-writer.service
    echo "sd-stats-writer running as $STATS_USER"
fi
