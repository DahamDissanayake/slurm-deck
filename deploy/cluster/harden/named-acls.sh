#!/usr/bin/env bash
# Remove ACL entries that grant named people access to the share. Admin access
# goes only through the admin group (gpuadmins) and sd-ops, never a person
# (design §4.3, §10.8). Run on the GPU host (the NFS server): over NFSv4 the
# login node can't see POSIX ACLs.
#
#   named-acls.sh --check                  list the entries that would go
#   named-acls.sh --apply [--allow u1,u2]
#
# Covers $NFS_ROOT itself, users/ and jobs/ themselves, each users/<u> and
# jobs/<u> tree, and every other top-level entry (the shared areas). Every
# user: and default:user: entry is removed except:
#   - in users/<u> and jobs/<u>, the folder owner's own;
#   - $OPS_USER (sd-ops), and the names in NAMED_ACL_ALLOW and --allow.
# Group entries are never touched. Symlinks are never followed (-P).
set -euo pipefail

NFS_ROOT="${NFS_ROOT:-/shared}"
OPS_USER="${OPS_USER:-sd-ops}"

usage() { echo "usage: $0 --check|--apply [--allow user,...]" >&2; exit 2; }

mode=""
allow="$OPS_USER,${NAMED_ACL_ALLOW:-}"
while [ $# -gt 0 ]; do
    case "$1" in
        --check|--apply) mode="${1#--}"; shift ;;
        --allow) [ $# -ge 2 ] || usage; allow="$allow,$2"; shift 2 ;;
        *) usage ;;
    esac
done
[ -n "$mode" ] || usage
[ -d "$NFS_ROOT" ] || { echo "$NFS_ROOT is not a directory" >&2; exit 1; }
command -v getfacl >/dev/null && command -v setfacl >/dev/null ||
    { echo "getfacl and setfacl are needed (package acl)" >&2; exit 1; }

owner() {
    local u
    u="$(stat -c %U -- "$1")"
    [ "$u" = UNKNOWN ] && u="$(stat -c %u -- "$1")"
    echo "$u"
}

# "<access|default> <name>" for every named-user entry not in the keep list.
# $1 is the keep list (comma-separated), the rest are getfacl arguments.
named() {
    local keep="$1"; shift
    { getfacl -Pp --skip-base "$@" || true; } | awk -v keep=",$keep," '
        /^user:[^:]+:/         { split($0, f, ":"); k = "access";  n = f[2] }
        /^default:user:[^:]+:/ { split($0, f, ":"); k = "default"; n = f[3] }
        /^(default:)?user:[^:]+:/ { if (index(keep, "," n ",") == 0) print k, n }'
}

# Each line: <label> <keep list> <recursive: R or -> <path>
targets() {
    local p
    printf '%s\t%s\t-\t%s\n' "." "$allow" "$NFS_ROOT"
    for top in users jobs; do
        p="$NFS_ROOT/$top"
        [ -d "$p" ] && [ ! -L "$p" ] || continue
        printf '%s\t%s\t-\t%s\n' "$top" "$allow" "$p"
        find -P "$p" -mindepth 1 -maxdepth 1 -type d -print0 | sort -z |
            while IFS= read -r -d '' t; do
                printf '%s\t%s\tR\t%s\n' "${t#"$NFS_ROOT"/}" "$allow,$(owner "$t")" "$t"
            done
    done
    find -P "$NFS_ROOT" -mindepth 1 -maxdepth 1 ! -type l ! -name users ! -name jobs -print0 |
        sort -z | while IFS= read -r -d '' t; do
            printf '%s\t%s\tR\t%s\n' "${t#"$NFS_ROOT"/}" "$allow" "$t"
        done
}

scan() {   # label, keep, R|-, path -> "label: name (access N, default N)" lines
    local args=("$4")
    [ "$3" = R ] && args=(-R "$4")
    named "$2" "${args[@]}" | sort | uniq -c | awk -v label="$1" '
        { c[$3, $2] = $1; names[$3] = 1 }
        END { for (n in names)
                  printf "%s: user:%s (access %d, default %d)\n",
                         label, n, c[n, "access"] + 0, c[n, "default"] + 0 }' | sort
}

found=0
while IFS=$'\t' read -r label keep rec path; do
    lines="$(scan "$label" "$keep" "$rec" "$path")"
    [ -n "$lines" ] || continue
    found=$((found + 1))
    echo "$lines"
    [ "$mode" = apply ] || continue
    r=""; [ "$rec" = R ] && r="R"
    for n in $(echo "$lines" | sed -n 's/^.*: user:\([^ ]*\) .*/\1/p' | sort -u); do
        case "$n" in
            *[!A-Za-z0-9._-]*) echo "$label: skipped unexpected name '$n'" >&2; continue ;;
        esac
        # setfacl reports files that lack the entry (and default entries on
        # plain files); the rescan below is what decides success.
        setfacl -P${r} -x "u:$n" "$path" 2>/dev/null || true
        if [ -n "$r" ]; then
            find -P "$path" -type d -exec setfacl -P -x "d:u:$n" {} + 2>/dev/null || true
        else
            setfacl -P -x "d:u:$n" "$path" 2>/dev/null || true
        fi
    done
    left="$(scan "$label" "$keep" "$rec" "$path")"
    if [ -n "$left" ]; then
        echo "$label: still present after --apply:" >&2
        echo "$left" >&2
        exit 1
    fi
    echo "$label: removed"
done < <(targets)

if [ "$found" -eq 0 ]; then
    echo "no named-user ACL entries to remove (kept: ${allow%,}, and each users/ and jobs/ folder owner)"
elif [ "$mode" = check ]; then
    echo "would remove the entries above from $found path(s); kept: ${allow%,}, and each users/ and jobs/ folder owner"
fi
