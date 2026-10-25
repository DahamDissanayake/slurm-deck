#!/usr/bin/env bash
# On the GPU host: forward the web ports (80 and 443) from the LAN address to the login
# node the same way port 2225 (SSH) is already forwarded, and limit the session ports to
# the login node (sd-session-ports.nft, next to this script).
#
#   sd-web-forward.sh --check     say how 2225 is forwarded and what would change; change nothing
#   sd-web-forward.sh --apply
#   sd-web-forward.sh --remove
#
# Site values come from /etc/slurm-deck-web/gpu-helper.env (LAN_ADDR, LOGIN_ADDR, GPU_HOST,
# SESSION_PORT_RANGE), written by the installer. Exit 2: the 2225 forward wasn't found.
set -euo pipefail

ENV_FILE="${SD_ENV_FILE:-/etc/slurm-deck-web/gpu-helper.env}"
[ -f "$ENV_FILE" ] && . "$ENV_FILE"
HOOK="${LIBVIRT_HOOK:-/etc/libvirt/hooks/qemu}"
SESSION_NFT="${SD_SESSION_NFT:-$(cd "$(dirname "$0")" && pwd)/sd-session-ports.nft}"
TAG="sd-web-forward"
SSH_PORT=2225

case "${1:-}" in
    --check|--apply|--remove) mode="${1#--}" ;;
    *) echo "usage: $0 --check|--apply|--remove" >&2; exit 64 ;;
esac
for name in LAN_ADDR LOGIN_ADDR GPU_HOST; do
    [ -n "${!name:-}" ] || { echo "$name is not set in $ENV_FILE" >&2; exit 1; }
done

# Run a command, or in --check just show it.
act() {
    if [ "$mode" = check ]; then printf '  would run:'; printf ' %q' "$@"; echo; else "$@"; fi
}

detect() {
    if [ -f "$HOOK" ] && grep -q -- "--dport $SSH_PORT" "$HOOK"; then echo libvirt-hook
    elif command -v nft >/dev/null && nft -a list ruleset 2>/dev/null | grep -q "dport $SSH_PORT "; then echo nftables
    elif command -v iptables >/dev/null && iptables -t nat -S 2>/dev/null | grep -q -- "--dport $SSH_PORT"; then echo iptables
    fi
}

forward_nftables() {
    local rules fam tbl chain rule handle
    rules="$(nft -a list ruleset)"
    if [ "$mode" = remove ]; then
        read -r fam tbl chain handle < <(awk -v tag="$TAG" '$1=="table"{f=$2;t=$3} $1=="chain"{c=$2}
            index($0, tag) {print f, t, c, $NF; exit}' <<<"$rules") || true
        [ -n "${handle:-}" ] && act nft delete rule "$fam" "$tbl" "$chain" handle "$handle" || echo "  nothing to remove"
        return
    fi
    if grep -q "comment \"$TAG\"" <<<"$rules"; then echo "  already in place"; return; fi
    read -r fam tbl chain rule < <(awk -v port="$SSH_PORT" '$1=="table"{f=$2;t=$3} $1=="chain"{c=$2}
        $0 ~ ("dport " port " ") {sub(/^[ \t]+/, ""); sub(/ # handle [0-9]+$/, ""); print f, t, c, $0; exit}' <<<"$rules")
    rule="$(sed -E "s/dport $SSH_PORT /dport { 80, 443 } /; s/dnat( ip)? to [^ ]+/dnat\1 to $LOGIN_ADDR/; s/ comment \"[^\"]*\"//" <<<"$rule") comment \"$TAG\""
    read -ra words <<<"$rule"
    act nft add rule "$fam" "$tbl" "$chain" "${words[@]}"
}

forward_iptables() {
    local rule
    if [ "$mode" = remove ]; then
        rule="$(iptables -t nat -S | grep -- "--comment $TAG" | head -1 || true)"
        [ -n "$rule" ] && { read -ra words <<<"${rule/#-A/-D}"; act iptables -t nat "${words[@]}"; } || echo "  nothing to remove"
        return
    fi
    if iptables -t nat -S | grep -q -- "--comment $TAG"; then echo "  already in place"; return; fi
    rule="$(iptables -t nat -S | grep -m1 -- "--dport $SSH_PORT" |
        sed -E "s/-p tcp -m tcp --dport $SSH_PORT/-p tcp -m multiport --dports 80,443/; s/--dport $SSH_PORT/--dports 80,443/; s/--to-destination [^ ]+/--to-destination $LOGIN_ADDR/; s/ -j / -m comment --comment $TAG -j /")"
    read -ra words <<<"$rule"
    act iptables -t nat "${words[@]}"
}

# libvirt re-creates its rules from this hook each time the VM starts, so the new lines
# go beside the 2225 ones, between markers.
forward_hook() {
    local line port block=""
    sed -i "/# $TAG begin/,/# $TAG end/d" "$HOOK" 2>/dev/null || true
    [ "$mode" = remove ] && return
    line="$(grep -m1 -- "--dport $SSH_PORT" "$HOOK")"
    for port in 80 443; do
        block+="$(sed -E "s/--dport $SSH_PORT/--dport $port/; s/--to-destination [^ ]+/--to-destination $LOGIN_ADDR:$port/" <<<"$line")"$'\n'
    done
    if [ "$mode" = check ]; then printf '  would add to %s after the %s lines:\n%s' "$HOOK" "$SSH_PORT" "$block"; return; fi
    local last
    last="$(grep -n -- "--dport $SSH_PORT" "$HOOK" | tail -1 | cut -d: -f1)"
    printf '  # %s begin\n%s  # %s end\n' "$TAG" "$block" "$TAG" > "$HOOK.new"
    sed -i "${last}r $HOOK.new" "$HOOK" && rm -f "$HOOK.new"
    echo "  added; it takes effect the next time libvirt runs the hook (restart the VM)"
}

session_firewall() {
    echo "session ports (${SESSION_PORT_RANGE:-8800-8999} reachable only from $LOGIN_ADDR on $GPU_HOST): table inet sd_sessions"
    if [ "$mode" = remove ]; then act nft delete table inet sd_sessions; return; fi
    local rendered
    rendered="$(sed -E "s/^define LOGIN_ADDR = .*/define LOGIN_ADDR = $LOGIN_ADDR/; s/^define COMPUTE_ADDR = .*/define COMPUTE_ADDR = $GPU_HOST/; s/^define SESSION_PORTS = .*/define SESSION_PORTS = ${SESSION_PORT_RANGE:-8800-8999}/" "$SESSION_NFT")"
    if [ "$mode" = check ]; then echo "  would load $SESSION_NFT with those values"; return; fi
    nft delete table inet sd_sessions 2>/dev/null || true
    nft -f - <<<"$rendered"
}

mechanism="$(detect)"
if [ -z "$mechanism" ]; then
    echo "Couldn't find how port $SSH_PORT is forwarded; set up the 443 forward by hand." >&2
    exit 2
fi
echo "mechanism: $mechanism"
echo "forward 80 and 443 on $LAN_ADDR to $LOGIN_ADDR:"
case "$mechanism" in
    nftables) forward_nftables ;;
    iptables) forward_iptables ;;
    libvirt-hook) forward_hook ;;
esac
session_firewall
