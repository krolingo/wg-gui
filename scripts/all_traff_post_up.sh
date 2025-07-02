# This script is executed after a WireGuard interface is brought up.
# It ensures the correct interface is patched into /etc/pf.conf,
# reloads PF firewall rules, and optionally restarts a jail.
# Additionally, it restores custom local routes using another helper script.
#!/bin/sh
#
# all_traff_post_up.sh — robust PostUp for PF patching
# Always exits 0 so GUI won’t loop on failure

# Set PATH to ensure required system tools are available.
# ensure we can find route, pfctl, bastille, etc.
export PATH="/sbin:/usr/sbin:/bin:/usr/bin:$PATH"

# Log file to record all script actions.
LOG="/tmp/wg-postup.log"

# Map file that may contain the last used WireGuard interface name.
MAP="/tmp/wg-multi/wg-utun.map"

# Simple logging function that timestamps messages and appends them to the log.
log() {
    echo "[$(date '+%F %T')] $*" >> "$LOG"
}

log "---- START PostUp ----"
log "Script invoked: $0 $*"
# Determine the WireGuard interface name from the most reliable source:
# - Argument $1
# - Environment variable INTERFACE
# - Map file (if available)
# - Fallback to `wg show interfaces`
# 1) Pick up interface from $1 or $INTERFACE
if [ -n "$1" ]; then
    WG_IF="$1"
    log "Picked up from \$1: $WG_IF"
elif [ -n "$INTERFACE" ]; then
    WG_IF="$INTERFACE"
    log "Picked up from \$INTERFACE: $WG_IF"
else
    # 2) Try the map file
    if [ -f "$MAP" ] && tail -n1 "$MAP" | grep -q ':'; then
        WG_IF=$(tail -n1 "$MAP" | awk -F: '{print $2}')
        log "Picked up from map: $WG_IF"
    else
        # 3) LAST RESORT: use wg show interfaces
        if wg show interfaces >/dev/null 2>&1; then
            WG_IF=$(wg show interfaces | awk '{print $NF}')
            log "Picked up from 'wg show interfaces': $WG_IF"
        else
            log "⚠️ Could not determine WireGuard interface; skipping PF patch."
            exit 0
        fi
    fi
fi

# Abort if we still couldn't determine the interface name.
# sanity check
if [ -z "$WG_IF" ]; then
    log "⚠️ WG_IF empty after all attempts; nothing to do."
    exit 0
fi

if [ ! -f "$PF_CONF" ]; then
    log "⚠️ $PF_CONF not found; skipping PF patching."
else
    # Read and log the current wg_if setting in pf.conf before patching.
    # show before
    PRE=$(grep '^wg_if=' "$PF_CONF" 2>/dev/null || echo "<none>")
    log "Before patch: $PRE"

    # Patch pf.conf by replacing any existing wg_if assignment with the actual interface name.
    # patch pf.conf
    TMP=$(mktemp /tmp/pfconf.XXXXXX)
    if ! awk -v new="$WG_IF" '
      /^wg_if=/ { print "wg_if=\"" new "\""; next }
      { print }
    ' "$PF_CONF" > "$TMP"; then
        log "⚠️ Failed to build patched pf.conf; skipping."
        rm -f "$TMP"
    else
        # install
        if mv "$TMP" "$PF_CONF"; then
            log "✅ Patched pf.conf to wg_if=\"$WG_IF\""
        else
            log "⚠️ Failed to install patched pf.conf; skipping."
            rm -f "$TMP"
        fi

        # show after
        POST=$(grep '^wg_if=' "$PF_CONF" 2>/dev/null || echo "<none>")
        log "After patch:  $POST"

        # Reload PF with the new configuration file.
        # reload PF
        if pfctl -f "$PF_CONF" >>"$LOG" 2>&1; then
            log "✅ PF reloaded"
        else
            log "⚠️ PF reload failed; continuing anyway."
        fi
    fi
fi

# On FreeBSD, optionally restart a specific jail after PF reload.
# restart jail on FreeBSD only
if [ "$(uname)" = "FreeBSD" ]; then
    if bastille restart unbound_blocker >>"$LOG" 2>&1; then
        log "✅ Jail restarted"
    else
        log "⚠️ Jail restart failed; continuing anyway."
    fi
fi

# Restore user-defined local routes lost when adding a default route via WireGuard.
# Restore user-defined local routes lost when adding a default route via WireGuard.
/usr/local/etc/wireguard/scripts/restore_local_routes.sh
echo "I reinstated your custom routes"

# Log the final PATH value for debugging.
log "DEBUG: PATH is $PATH"

log "---- END PostUp ----"
exit 0
