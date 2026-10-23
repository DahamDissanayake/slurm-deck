#!/usr/bin/env bash
# Remove every member of the `docker` group except the sysadmins. Membership
# of `docker` is root on the node, so normal users and admins must not have it.
# Run on each node.
#
#   remove-docker-group.sh --check            list members and running containers
#   remove-docker-group.sh --apply [--keep u1,u2]
#
# SYSADMINS (comma-separated, from site values) and --keep are never removed.
# --apply refuses to run when both are empty, so it can't strip every admin.
set -euo pipefail

usage() { echo "usage: $0 --check|--apply [--keep user,...]" >&2; exit 2; }

mode=""
keep="${SYSADMINS:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        --check|--apply) mode="${1#--}"; shift ;;
        --keep) [ $# -ge 2 ] || usage; keep="$keep,$2"; shift 2 ;;
        *) usage ;;
    esac
done
[ -n "$mode" ] || usage

kept() {
    case ",$keep," in *",$1,"*) return 0 ;; esac
    return 1
}

members="$(getent group docker | cut -d: -f4 | tr ',' ' ')"
remove=()
for u in $members; do
    kept "$u" || remove+=("$u")
done

if [ "$mode" = check ]; then
    echo "docker group members: ${members:-none}"
    echo "would remove: ${remove[*]:-none}"
    echo "kept (sysadmins and --keep): ${keep#,}"
    echo "running containers (ID, name, image) — stop any a removed user still needs:"
    docker ps --format '{{.ID}}\t{{.Names}}\t{{.Image}}' 2>/dev/null || echo "  (docker not reachable)"
    exit 0
fi

if [ -z "${keep//,/}" ]; then
    echo "refusing to --apply with no SYSADMINS and no --keep: it would remove every admin" >&2
    exit 1
fi
for u in "${remove[@]}"; do
    gpasswd -d "$u" docker
    echo "removed $u from docker"
done
echo "done: ${#remove[@]} removed. Their open sessions keep the group until they log out."
