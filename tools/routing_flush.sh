#!/bin/sh

set -e


# Expand PATH so all tools are found
export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# Choose doas or sudo
if command -v doas >/dev/null 2>&1; then
    DOAS_OR_SUDO="doas"
elif command -v sudo >/dev/null 2>&1; then
    DOAS_OR_SUDO="sudo"
else
    echo "Error: neither doas nor sudo found in PATH."
    exit 1
fi

OS=$(uname -s)

echo "Detected OS: $OS"

if [ "$OS" = "FreeBSD" ]; then
    echo "=== FreeBSD Routing Reset ==="
    # Optional: uncomment to force full route flush or re-DHCP
    # doas /sbin/route delete default
    # doas /sbin/route -n flush
    ${DOAS_OR_SUDO} /usr/sbin/service netif restart
    ${DOAS_OR_SUDO} /etc/rc.d/routing restart

elif [ "$OS" = "Darwin" ]; then
    echo "=== macOS Routing Reset ==="

    # Try to reacquire DHCP if interface can be found
    IFACE=$(netstat -rn | awk '$1 == "default" && $6 != "" { print $6; exit }')
    if [ -z "$IFACE" ]; then
        IFACE=$(route get default 2>/dev/null | awk '/interface: / { print $2 }')
    fi

    # Set temporary DNS to loopback (for internal resolvers like unbound)
    SERVICE=$(/usr/sbin/networksetup -listallhardwareports | awk -v iface="$IFACE" '
        BEGIN { RS="\n\n"; FS="\n" }
        {
            for (i=1; i<=NF; i++) {
                if ($i ~ "Device: "iface"$") {
                    print $1
                    exit
                }
            }
        }' | sed 's/Hardware Port: //')

    if [ -n "$SERVICE" ]; then
        echo "Setting DNS for: $SERVICE"
        ${DOAS_OR_SUDO} networksetup -setdnsservers "$SERVICE" 127.0.0.1
    else
        echo "⚠️ Could not determine network service for $IFACE"
    fi

    # Flush routes
    ${DOAS_OR_SUDO} route -n flush || true  # Allow failure if routes already gone

    if [ -n "$IFACE" ] && ifconfig "$IFACE" >/dev/null 2>&1; then
        echo "Reacquiring DHCP on $IFACE"
        ${DOAS_OR_SUDO} ipconfig set "$IFACE" NONE
        ${DOAS_OR_SUDO} ipconfig set "$IFACE" DHCP
    else
        echo "⚠️ Could not determine default interface; skipping DHCP reset"
    fi
else
    echo "Unsupported OS: $OS"
    exit 1
fi

echo "✅ Routing reset complete"