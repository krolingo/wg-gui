#!/bin/sh

set -e

OS=$(uname -s)

echo "Detected OS: $OS"

if [ "$OS" = "FreeBSD" ]; then
    echo "=== FreeBSD Routing Reset ==="
    # Uncomment as needed:
    # doas route delete default
    # doas route -n flush
    doas service routing restart
elif [ "$OS" = "Darwin" ]; then
    echo "=== macOS Routing Reset ==="
    doas route delete default
    doas dscacheutil -flushcache
    doas killall -HUP mDNSResponder
    doas networksetup -setdnsservers Wi-Fi 127.0.0.1
    doas route -n flush
    doas ipconfig set en0 NONE
    doas ipconfig set en0 DHCP
else
    echo "Unsupported OS: $OS"
    exit 1
fi
