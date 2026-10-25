#!/usr/bin/env bash
# Nightly backup of the web app: a pg_dump of the database and an archive of the config
# (the *.env files and install-state.json in /etc/slurm-deck-web, and the agent's audit
# log). Run by sd-backup.timer as slurmadmin; every file is private (0600) to that account.
#
#   sd-backup.sh              dump, archive, then prune to the newest BACKUP_KEEP
#   sd-backup.sh --prune-only
#
# Settings (from /etc/slurm-deck-web/site.env or the environment):
#   COMPOSE_DIR            the deploy/ folder with compose.yaml (required)
#   BACKUP_DIR             /var/backups/slurm-deck
#   BACKUP_KEEP            14
#   BACKUP_COPY_TO_SHARED  1 also copies each night to $NFS_ROOT/.admin-backups (admin-only)
#   CONF_DIR, AUDIT_LOG, NFS_ROOT
#
# Old backups are only pruned after a new one was written completely, so a failing
# database never costs you the backups you have.
set -euo pipefail
umask 077

BACKUP_DIR="${BACKUP_DIR:-/var/backups/slurm-deck}"
KEEP="${BACKUP_KEEP:-14}"
CONF_DIR="${CONF_DIR:-/etc/slurm-deck-web}"
AUDIT_LOG="${AUDIT_LOG:-/var/log/slurm-deck-web/agent-audit.jsonl}"
NFS_ROOT="${NFS_ROOT:-/shared}"

[[ "$KEEP" =~ ^[0-9]+$ ]] && [ "$KEEP" -ge 1 ] || { echo "BACKUP_KEEP must be 1 or more" >&2; exit 1; }

# Keep the newest $KEEP dumps in a folder, and delete the older ones with their config archives.
prune() {
    local old
    ls -1 "$1"/sd-*.dump 2>/dev/null | sort | head -n "-$KEEP" | while read -r old; do
        rm -f -- "$old" "${old%.dump}-config.tar.gz"
    done
}

if [ "${1:-}" = "--prune-only" ]; then prune "$BACKUP_DIR"; exit 0; fi
[ -n "${COMPOSE_DIR:-}" ] || { echo "COMPOSE_DIR is not set" >&2; exit 1; }

mkdir -p "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"
stamp="$(date +%Y%m%d)"
dump="$BACKUP_DIR/sd-$stamp.dump"
conf="$BACKUP_DIR/sd-$stamp-config.tar.gz"
trap 'rm -f -- "$dump.part" "$conf.part"' EXIT   # never leave half a backup

(cd "$COMPOSE_DIR" && docker compose exec -T db pg_dump -Fc -U sdweb slurmdeck) > "$dump.part"
files=()
while IFS= read -r f; do files+=("$f"); done < <(cd "$CONF_DIR" && ls -1 ./*.env ./install-state.json 2>/dev/null | sed 's|^\./||')
extra=()
[ -f "$AUDIT_LOG" ] && extra=(-C "$(dirname "$AUDIT_LOG")" "$(basename "$AUDIT_LOG")")
tar -czf "$conf.part" -C "$CONF_DIR" "${files[@]}" "${extra[@]}"
mv -- "$dump.part" "$dump"
mv -- "$conf.part" "$conf"
echo "backup written: $dump"

prune "$BACKUP_DIR"
if [ "${BACKUP_COPY_TO_SHARED:-0}" = 1 ]; then
    shared="$NFS_ROOT/.admin-backups"
    install -d -m 0700 "$shared"
    cp -p -- "$dump" "$conf" "$shared/"
    prune "$shared"
    echo "copied to $shared"
fi
