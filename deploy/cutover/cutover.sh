#!/usr/bin/env bash
# The cutover from the SSH TUI to the web platform, on one node, from a cutover-plan.json
# made by classify.py:
#
#   cutover.sh --announce --check|--apply <plan>   days earlier: banner on the web app, and the
#                                                   old users' addresses to write to
#   cutover.sh --check <plan>                       show what would happen; run nothing
#   cutover.sh --apply <plan> [--no-sshd]           close TUI logins, then remove the accounts
#
# --apply on the login node: (1) disables the ForceCommand drop-in and limits ssh to
# $SHELL_GROUP and $SYSADMIN_GROUP (the plan's shell users are put in $SHELL_GROUP), checks
# sshd's config and reloads it; (2) removes the plan's `remove` accounts. Run it on the GPU
# host too, with --no-sshd. Home folders and /shared data are never touched: userdel runs
# without -r, so every /shared/users/<name> and /shared/jobs/<name> stays for reconnecting.
# Settings: SYSADMINS, SYSADMIN_GROUP (required), SHELL_GROUP (shellusers), CUTOVER_DATE
# and LEGACY_USERS_DB (for --announce), ETC_DIR.
set -euo pipefail

ETC="${ETC_DIR:-/etc}"
SHELL_GROUP="${SHELL_GROUP:-shellusers}"
DROPIN_D="$ETC/ssh/sshd_config.d"
CUTOVER_CONF="$DROPIN_D/10-slurm-deck-cutover.conf"
mode=check announce=0 sshd=1 plan=""
while [ $# -gt 0 ]; do
    case "$1" in
        --check|--apply) mode="${1#--}" ;;
        --announce) announce=1 ;;
        --no-sshd) sshd=0 ;;
        -*) echo "usage: $0 [--announce] --check|--apply <plan> [--no-sshd]" >&2; exit 64 ;;
        *) plan="$1" ;;
    esac
    shift
done
[ -f "$plan" ] || { echo "give the cutover-plan.json from classify.py" >&2; exit 64; }

act() { if [ "$mode" = check ]; then printf 'would run:'; printf ' %q' "$@"; echo; else "$@"; fi; }
listed() { python3 -c 'import json,sys; print(*json.load(open(sys.argv[1]))[sys.argv[2]], sep="\n")' "$plan" "$1"; }
uid_of() { awk -F: -v u="$1" '$1 == u {print $3}' "$ETC/passwd"; }
is_sysadmin() { case ",${SYSADMINS:-}," in *",$1,"*) return 0 ;; esac; return 1; }

if [ "$announce" = 1 ]; then
    : "${CUTOVER_DATE:?set CUTOVER_DATE, e.g. 2026-11-09}"
    banner="Slurm Deck moves to the new web platform on $CUTOVER_DATE. Your old login stops then; an admin will set up your new account."
    echo "banner: $banner"
    if [ "$mode" = apply ]; then
        docker compose exec -T db psql -U sdweb slurmdeck -v banner="$banner" <<<"INSERT INTO settings (key, value, updated_at) VALUES ('maintenance_banner', to_jsonb(:'banner'::text), now()) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
    else
        echo "would set the maintenance banner"
    fi
    out="$(dirname "$plan")/announce-recipients.txt"
    python3 - "${LEGACY_USERS_DB:-/var/lib/slurm-deck/users.db}" "$plan" "$out" <<'PY'
import json, os, sqlite3, sys
db, plan, out = sys.argv[1:]
users = json.load(open(plan))["remove"]
if not os.path.exists(db):
    print(f"no legacy users database at {db}; write to the old users yourself")
    sys.exit(0)
rows = sqlite3.connect(db).execute("SELECT username, email FROM users WHERE status = 'active'").fetchall()
lines = [f"{u} <{e}>" for u, e in sorted(rows) if u in users]
open(out, "w").write("\n".join(lines) + "\n")
print(f"{len(lines)} addresses written to {out}")
PY
    exit 0
fi

if [ "$sshd" = 1 ]; then
    : "${SYSADMIN_GROUP:?set SYSADMIN_GROUP, the group of people who must keep ssh}"
    echo "== close TUI logins"
    for f in $(grep -l ForceCommand "$DROPIN_D"/*.conf 2>/dev/null || true); do act mv -f "$f" "$f.disabled"; done
    act groupadd -f "$SHELL_GROUP"
    for u in $(listed shell); do act usermod -aG "$SHELL_GROUP" "$u"; done
    if [ "$mode" = apply ]; then
        printf 'AllowGroups %s %s\n' "$SHELL_GROUP" "$SYSADMIN_GROUP" > "$CUTOVER_CONF"
        sshd -t || { rm -f "$CUTOVER_CONF"; echo "sshd rejected the new config; undone" >&2; exit 1; }
    else
        echo "would write $CUTOVER_CONF: AllowGroups $SHELL_GROUP $SYSADMIN_GROUP"
    fi
    act systemctl reload sshd
fi

echo "== remove accounts (homes and /shared data stay)"
printf '%-24s %s\n' USER UID
for u in $(listed remove); do
    uid="$(uid_of "$u")"
    if [ -z "$uid" ] || [ "$uid" -lt 1000 ] || is_sysadmin "$u"; then echo "skipping $u"; continue; fi
    printf '%-24s %s\n' "$u" "$uid"
    act pkill -KILL -u "$u" || true
    act userdel "$u"
    command -v sacctmgr >/dev/null && act sacctmgr -i delete user name="$u"
done
echo "Recreate or reconnect these people in the admin pages (their folders are intact)."
