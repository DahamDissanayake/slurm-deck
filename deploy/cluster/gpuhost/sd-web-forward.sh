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
# With iptables, rules saved in /etc/iptables/rules.v4 (SD_IPTABLES_RULES) are updated too.
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

# The rule only matches traffic for the LAN address: without that it would catch all
# HTTP/HTTPS passing through the host, the login node's own outbound HTTPS included.
# A tagged rule without that match (older runs added those) is deleted and re-added.
forward_nftables() {
    local rules fam tbl chain rule handle old found="" current=""
    rules="$(nft -a list ruleset)"
    while read -r fam tbl chain handle old; do
        [ -n "${handle:-}" ] || continue
        found=1
        if [ "$mode" != remove ] && [[ "$old" == *"ip daddr $LAN_ADDR "* ]]; then current=1; continue; fi
        act nft delete rule "$fam" "$tbl" "$chain" handle "$handle"
    done < <(awk -v tag="comment \"$TAG\"" '$1=="table"{f=$2;t=$3} $1=="chain"{c=$2}
        index($0, tag) {print f, t, c, $NF, $0}' <<<"$rules")
    if [ "$mode" = remove ]; then [ -n "$found" ] || echo "  nothing to remove"; return; fi
    if [ -n "$current" ]; then echo "  already in place"; return; fi
    read -r fam tbl chain rule < <(awk -v port="$SSH_PORT" '$1=="table"{f=$2;t=$3} $1=="chain"{c=$2}
        $0 ~ ("dport " port " ") {sub(/^[ \t]+/, ""); sub(/ # handle [0-9]+$/, ""); print f, t, c, $0; exit}' <<<"$rules")
    rule="$(sed -E "s/ip daddr [^ ]+ //; s/^/ip daddr $LAN_ADDR /; s/dport $SSH_PORT /dport { 80, 443 } /; s/dnat( ip)? to [^ ]+/dnat\1 to $LOGIN_ADDR/; s/ comment \"[^\"]*\"//" <<<"$rule") comment \"$TAG\""
    read -ra words <<<"$rule"
    act nft add rule "$fam" "$tbl" "$chain" "${words[@]}"
}

# Each 2225 rule and the 80/443 rule that mirrors it, as "2225 rule<TAB>new rule" lines:
# the PREROUTING DNAT, the OUTPUT -o lo DNAT when there is one, and the FORWARD accept
# rules to and from the login node (libvirt's LIBVIRT_FWI rejects new connections into
# virbr0 without them). No MASQUERADE: the app needs the clients' addresses. The DNATs
# match the LAN address (-d), whether or not the 2225 ones do.
iptables_plan() {
    local nat="$1" filter="$2" dnat dest inner line
    dnat="$(grep -m1 -E -- "^-A PREROUTING .*--dport $SSH_PORT( |$)" <<<"$nat" || true)"
    [ -n "$dnat" ] || { echo "No PREROUTING rule for port $SSH_PORT; set up the 443 forward by hand." >&2; exit 2; }
    dest="$(sed -nE 's/.*--to-destination ([^ :]+).*/\1/p' <<<"$dnat")"
    inner="$(sed -nE 's/.*--to-destination [^ :]+:([0-9]+).*/\1/p' <<<"$dnat")"
    inner="${inner:-$SSH_PORT}"
    local web_dnat="s#^(-A [A-Z]+ (-s [^ ]+ )?)(-d [^ ]+ )?#\1-d $LAN_ADDR/32 #; s/-m tcp --dport $SSH_PORT /-m multiport --dports 80,443 /; s/--dport $SSH_PORT /-m multiport --dports 80,443 /; s/--to-destination [^ ]+/--to-destination $LOGIN_ADDR/; s/ -j / -m comment --comment $TAG -j /"
    local web_accept="s/-m tcp --(d|s)port $inner /-m multiport --\1ports 80,443 /; s/--(d|s)port $inner /-m multiport --\1ports 80,443 /; s#-([ds]) $dest/32 #-\1 $LOGIN_ADDR/32 #; s/ -j / -m comment --comment $TAG -j /"
    printf '%s\t%s\n' "$dnat" "$(sed -E "$web_dnat" <<<"$dnat")"
    line="$(grep -m1 -E -- "^-A OUTPUT .*-o lo .*--dport $SSH_PORT .*-j DNAT" <<<"$nat" || true)"
    [ -z "$line" ] || printf '%s\t%s\n' "$line" "$(sed -E "$web_dnat" <<<"$line")"
    while read -r line; do
        [ -z "$line" ] || printf '%s\t%s\n' "$line" "$(sed -E "$web_accept" <<<"$line")"
    done < <(grep -E -- "^-A FORWARD (-d $dest/32 .*--dport|-s $dest/32 .*--sport) $inner .*-j ACCEPT" <<<"$filter" || true)
}

# Delete the tagged rules that aren't in the plan: all of them for --remove, and on
# --apply the ones an older run added (80/443 DNATs with no -d).
iptables_drop_tagged() {
    local nat="$1" filter="$2" plan="$3" table old found=""
    for table in nat filter; do
        while read -r old; do
            [ -n "$old" ] || continue
            if [ -n "$plan" ] && grep -qxF -- "$old" <<<"$(cut -f2 <<<"$plan")"; then continue; fi
            found=1
            read -ra words <<<"${old/#-A/-D}"
            act iptables -t "$table" "${words[@]}"
        done < <(if [ "$table" = nat ]; then echo "$nat"; else echo "$filter"; fi | grep -- "--comment $TAG" || true)
    done
    [ -n "$found" ] || [ -n "$plan" ] || echo "  nothing to remove"
}

forward_iptables() {
    local nat filter plan src new
    nat="$(iptables -t nat -S)"
    filter="$(iptables -t filter -S)"
    if [ "$mode" = remove ]; then
        iptables_drop_tagged "$nat" "$filter" ""
        persist_iptables ""
        return
    fi
    plan="$(iptables_plan "$nat" "$filter")"
    iptables_drop_tagged "$nat" "$filter" "$plan"
    while IFS=$'\t' read -r src new; do
        if grep -qxF -- "$new" <<<"$nat"$'\n'"$filter"; then echo "  in place: $new"; continue; fi
        if [[ "$new" == "-A FORWARD "* ]]; then
            # At the top of FORWARD, so before the LIBVIRT_* jumps.
            read -ra words <<<"-I FORWARD 1 ${new#-A FORWARD }"
            act iptables -t filter "${words[@]}"
        else
            read -ra words <<<"$new"
            act iptables -t nat "${words[@]}"
        fi
    done <<<"$plan"
    persist_iptables "$plan"
}

# When the rules are saved for boot (netfilter-persistent), save the new ones too, each
# right after the 2225 line it mirrors; --remove takes them out again.
persist_iptables() {
    local plan="$1" rules="${SD_IPTABLES_RULES:-/etc/iptables/rules.v4}" tmp planfile backup
    [ -f "$rules" ] || return 0
    tmp="$(mktemp)" planfile="$(mktemp)"
    printf '%s\n' "$plan" > "$planfile"
    if ! awk -v tag="--comment $TAG" -v planfile="$planfile" '
        BEGIN { while ((getline l < planfile) > 0) { i = index(l, "\t"); if (i) add[substr(l, 1, i - 1)] = add[substr(l, 1, i - 1)] substr(l, i + 1) "\n" } }
        index($0, tag) { next }
        { print; if ($0 in add) { printf "%s", add[$0]; delete add[$0] } }
        END { for (k in add) { print "not in the saved rules: " k > "/dev/stderr"; bad = 1 } exit bad }' "$rules" > "$tmp"; then
        rm -f "$tmp" "$planfile"
        echo "Couldn't place the 80/443 rules in $rules; add them there by hand." >&2
        [ "$mode" = check ] && return 0
        exit 1
    fi
    rm -f "$planfile"
    if cmp -s "$tmp" "$rules"; then rm -f "$tmp"; echo "  $rules: up to date"; return 0; fi
    if [ "$mode" = check ]; then
        echo "  would update $rules:"
        diff "$rules" "$tmp" | sed -nE 's/^([<>]) /    \1 /p' || true
        rm -f "$tmp"
        return 0
    fi
    if ! iptables-restore --test < "$tmp"; then
        rm -f "$tmp"
        echo "iptables-restore --test rejected the new $rules; it was left as it was." >&2
        exit 1
    fi
    backup="$rules.$(date +%Y%m%d%H%M%S).bak"
    cp -p "$rules" "$backup"
    cat "$tmp" > "$rules"   # in place, so its owner and mode stay
    rm -f "$tmp"
    echo "  saved in $rules (the old one is $backup)"
}

# libvirt re-creates its rules from this hook each time the VM starts, so the new lines
# go beside the 2225 ones, between markers, each matching the LAN address. --apply
# rewrites the whole block, so lines an older run added without -d are replaced.
forward_hook() {
    local line port block=""
    sed -i "/# $TAG begin/,/# $TAG end/d" "$HOOK" 2>/dev/null || true
    [ "$mode" = remove ] && return
    line="$(grep -m1 -- "--dport $SSH_PORT" "$HOOK")"
    for port in 80 443; do
        block+="$(sed -E "s/ -d [^ ]+//; s/(-[AI] [A-Za-z_]+( [0-9]+)?) /\1 -d $LAN_ADDR /; s/--dport $SSH_PORT/--dport $port/;s/--to-destination [^ ]+/--to-destination $LOGIN_ADDR:$port/" <<<"$line")"$'\n'
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
