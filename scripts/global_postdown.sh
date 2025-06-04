#!/usr/bin/env bash
# global_postdown.sh — Handles post-down cleanup for WireGuard #####!/bin/bash

IFACE="${1:-wg0}"
echo "[global_postdown] 🔻 WireGuard down: $IFACE"

OS="$(uname)"

case "$OS" in
  Darwin)
    # macOS-specific cleanup
    DEF_ROUTE=$(netstat -rn | awk '/^default/{print $6}')
    if [[ "$DEF_ROUTE" == utun* ]]; then
        echo "[global_postdown] Removing default route via $DEF_ROUTE"
        sudo route delete default
    fi

    echo "[global_postdown] Flushing DNS cache"
    sudo dscacheutil -flushcache
    sudo killall -HUP mDNSResponder

    echo "[global_postdown] Remaining utun interfaces:"
    ifconfig | grep ^utun
    ;;
  FreeBSD)
    # FreeBSD-specific cleanup
    DEF_ROUTE=$(netstat -rn -f inet | awk '/^default/{print $7}')
    if [[ "$DEF_ROUTE" == wg* ]]; then
        echo "[global_postdown] Removing default route via $DEF_ROUTE"
        sudo route delete default
    fi

    echo "[global_postdown] Remaining wg interfaces:"
    ifconfig | grep ^wg
    ;;
  *)
    echo "[global_postdown] Unsupported OS: $OS"
    ;;
esac

echo "[global_postdown] Done."

# --- macOS-only DNS Validation & Conditional Restart ---
if [[ "$OS" == "Darwin" ]]; then
    echo "🔍 Testing local DNS server on port 53..."
    echo "dig +short A xmcnetwork.com -p53"
    if dig +short A xmcnetwork.com -p53 >/dev/null; then
        echo "✅ Port 53 responded."
    else
        echo "❌ Port 53 failed. Triggering DNS restart..."
        restart_dns=true
    fi

    echo "🔍 Testing local DNS server on port 5053..."
    if dig +short A xmcnetwork.com @127.0.0.1 -p5053 >/dev/null; then
        echo "✅ Port 5053 responded."
    else
        echo "❌ Port 5053 failed. Triggering DNS restart..."
        restart_dns=true
    fi

    if [[ "$restart_dns" == true ]]; then
        echo "Restarting NSD and Unbound..."

        doas killall nsd
        echo "NSD killed."

        doas port reload nsd
        echo "NSD reloaded."

        doas port reload unbound
        echo "Unbound reloaded."

        doas networksetup -setdnsservers Wi-Fi 127.0.0.1
        echo "DNS set to localhost."

        doas dscacheutil -flushcache
        doas killall -HUP mDNSResponder
        echo "DNS cache flushed."
        sleep 5

        echo " Retesting after DNS restart:"
        echo "dig +short A xmcnetwork.com @127.0.0.1 -p53"
        dig +short A xmcnetwork.com @127.0.0.1 -p53
        echo "dig +short A xmcnetwork.com @127.0.0.1 -p5053"
        dig +short A xmcnetwork.com @127.0.0.1 -p5053
    else
        echo "✅ Both DNS ports responded. No restart needed."
    fi
fi

echo ""

sleep 10
fortune