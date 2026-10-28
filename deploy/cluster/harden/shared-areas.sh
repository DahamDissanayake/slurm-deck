#!/usr/bin/env bash
# Make the shared asset areas admin-writable through sd-ops and read-only for
# users. Run on the GPU host (the NFS server), where the share is local.
#
#   shared-areas.sh --check    count paths that would change; change nothing
#   shared-areas.sh --apply
#
# For each of $NFS_ROOT/{envs,models,datasets,data,images,scripts,templates,
# miniforge3,training-scripts}:
#   owner $OPS_USER:$ADMIN_GROUP, directories 2775, no group/other write on
#   files, access + default ACL g:$ADMIN_GROUP:rwx, $USER_GROUP ACL entries
#   (which granted users write) removed, and on every directory the default
#   ACL's owning-group and other entries set to r-x, so files created there
#   later aren't group- or world-writable. Only $ADMIN_GROUP keeps write.
# miniforge3 matters most: every job script sources its conda.sh.
# users/ and jobs/ are per-user areas and are never touched. Symlinks are
# never followed, so a link inside an area can't lead the changes elsewhere.
#
# tmp/ is not an area: nothing uses it any more (env builds use their own
# temp folder beside the env). It is reported when present so an admin
# removes it by hand once its contents have been checked; this script never
# changes or deletes it.
set -euo pipefail

NFS_ROOT="${NFS_ROOT:-/shared}"
OPS_USER="${OPS_USER:-sd-ops}"
ADMIN_GROUP="${ADMIN_GROUP:-gpuadmins}"
USER_GROUP="${USER_GROUP:-gpuusers}"
AREAS="envs models datasets data images scripts templates miniforge3 training-scripts"

case "${1:-}" in
    --check|--apply) mode="${1#--}" ;;
    *) echo "usage: $0 --check|--apply" >&2; exit 2 ;;
esac

if ! id "$OPS_USER" >/dev/null 2>&1; then
    echo "$OPS_USER does not exist yet; create it first (installer)" >&2
    exit 1
fi

count() { find -P "$@" 2>/dev/null | wc -l; }

# Default ACL entries that let a group or other write, except $ADMIN_GROUP's.
writable_defaults() {
    getfacl -RPp --skip-base "$1" 2>/dev/null | awk -F: -v admin="$ADMIN_GROUP" '
        /^default:(group|other):/ {
            split($4, perms, /[ \t]/)
            if (perms[1] ~ /w/ && !($2 == "group" && $3 == admin)) n++
        }
        END { print n + 0 }'
}

for area in $AREAS; do
    dir="$NFS_ROOT/$area"
    [ -d "$dir" ] && [ ! -L "$dir" ] || continue
    if [ "$mode" = check ]; then
        owner=$(count "$dir" ! -type l \( ! -user "$OPS_USER" -o ! -group "$ADMIN_GROUP" \))
        dirs=$(count "$dir" -type d ! -perm 2775)
        files=$(count "$dir" -type f -perm /022)
        acls=$(getfacl -RPp --skip-base "$dir" 2>/dev/null | grep -c "^group:$USER_GROUP:" || true)
        defaults=$(writable_defaults "$dir")
        echo "$area: owner=$owner dir-mode=$dirs writable-files=$files $USER_GROUP-acl=$acls default-acl=$defaults"
        continue
    fi
    find -P "$dir" ! -type l -exec chown -h "$OPS_USER:$ADMIN_GROUP" {} +
    find -P "$dir" -type d -exec chmod 2775 {} +
    find -P "$dir" -type f -exec chmod go-w {} +
    setfacl -RP -x "g:$USER_GROUP" -x "d:g:$USER_GROUP" "$dir" 2>/dev/null || true
    setfacl -RP -m "g:$ADMIN_GROUP:rwX" "$dir"
    find -P "$dir" -type d -exec setfacl -m "d:g::r-x,d:o::r-x,d:g:$ADMIN_GROUP:rwx" {} +
    echo "$area: fixed"
done

if [ -d "$NFS_ROOT/tmp" ] && [ ! -L "$NFS_ROOT/tmp" ]; then
    echo "tmp: unused; check its contents and remove it by hand (rm -r $NFS_ROOT/tmp)"
fi
