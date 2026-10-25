#!/usr/bin/env bash
# After the settling period: remove the old TUI from this node. There is no rollback after this.
#
#   retire-tui.sh --check     list what would be removed; change nothing
#   retire-tui.sh --apply
#
# Stops and disables slurm-deck-audit; removes /opt/slurm-deck, the /usr/local/bin/slurm-deck*
# gateway and launchers, the legacy sudoers files and the disabled ForceCommand drop-ins.
# The cutover snapshots (/var/backups/slurm-deck) and everything under /shared stay.
set -euo pipefail

ROOT="${CUTOVER_ROOT:-}"
case "${1:-}" in
    --check|--apply) mode="${1#--}" ;;
    *) echo "usage: $0 --check|--apply" >&2; exit 64 ;;
esac

targets=("$ROOT/opt/slurm-deck" "$ROOT"/usr/local/bin/slurm-deck* "$ROOT"/etc/sudoers.d/slurm-deck*
         "$ROOT"/etc/ssh/sshd_config.d/*.conf.disabled)
if command -v systemctl >/dev/null; then
    if [ "$mode" = check ]; then echo "would stop and disable slurm-deck-audit"
    else systemctl disable --now slurm-deck-audit || true; fi
fi
for t in "${targets[@]}"; do
    [ -e "$t" ] || continue
    if [ "$mode" = check ]; then echo "would remove ${t#"$ROOT"}"; else rm -rf -- "$t"; echo "removed ${t#"$ROOT"}"; fi
done
