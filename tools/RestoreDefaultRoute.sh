#!/bin/sh

# === Ensure root privileges via doas or sudo ===
if [ "$(id -u)" -ne 0 ]; then
    if command -v doas >/dev/null 2>&1; then
        exec doas "$0" "$@"
    elif command -v sudo >/dev/null 2>&1; then
        exec sudo "$0" "$@"
    else
        echo "❌ This script must be run as root, and neither doas nor sudo was found."
        exit 1
    fi
fi

# === Continue as root ===

sleep 1
OS="$(uname)"

# Hardcoded wg paths for macOS and FreeBSD
if [ "$OS" = "Darwin" ]; then
    WG_BIN="/opt/homebrew/bin/wg"
elif [ "$OS" = "FreeBSD" ]; then
    WG_BIN="/usr/local/bin/wg"
else
    echo "❌ Unsupported OS: $OS"
    exit 1
fi

# Verify wg exists
if [ ! -x "$WG_BIN" ]; then
    echo "❌ wg binary not found at $WG_BIN"
    exit 1
fi

echo "🔎 Scanning interfaces for full-tunnel routes..."

for intf in $($WG_BIN show interfaces); do
    echo "🔍 Checking $intf..."
    if $WG_BIN show "$intf" allowed-ips 2>/dev/null | grep -q "0.0.0.0/0"; then
        echo "🛣 Restoring default route via $intf"
        if [ "$OS" = "Darwin" ]; then
            /sbin/route add default -interface "$intf"
        elif [ "$OS" = "FreeBSD" ]; then
            /sbin/route add -net default -interface "$intf"
        fi
        exit 0
    fi
done

echo "⚠️  No other full-tunnel interface found — default route not restored."
exit 1