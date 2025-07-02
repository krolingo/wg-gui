#!/bin/sh

# Determine OS
OS=$(uname)

if [ "$OS" = "FreeBSD" ]; then
    echo "🔧 Detected FreeBSD — running FreeBSD DNS switch script"

    /home/mcapella/bin/switch_jailed_dns.sh
    doas service routing restart

    echo "🌐 Testing DNS and connectivity..."
    ping -c 5 1.1.1.1
    dig apple.com
    dig +short TXT o-o.myaddr.l.google.com @ns1.google.com | tr -d \"

elif [ "$OS" = "Darwin" ]; then
    echo "🔧 Detected macOS — restarting NSD and Unbound using launchd"

    STATE_DIR="/tmp/wg-multi"
    if [ -f "$STATE_DIR/original_default_gateway" ]; then
        DEFAULT_GW=$(cat "$STATE_DIR/original_default_gateway")
        CURRENT_IF=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
        CURRENT_GW=$(route -n get default 2>/dev/null | awk '/gateway:/{print $2}')

        if [ -z "$CURRENT_GW" ] || echo "$CURRENT_IF" | grep -q "^utun"; then
            echo "🛣 [PostDown] Restoring original default route via $DEFAULT_GW"
            if route -n get default >/dev/null 2>&1; then
                route delete default 2>/dev/null
            fi
            route add default "$DEFAULT_GW"
            rm -f "$STATE_DIR/original_default_gateway"
        else
            echo "ℹ️ [PostDown] Default route already set correctly ($CURRENT_IF → $CURRENT_GW)"
        fi
    else
        echo "⚠️ [PostDown] No saved default gateway to restore"
    fi

    export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

    for svc in nsd unbound; do
        echo "🛑 Unloading $svc"
        doas port unload "$svc"
        doas killall "$svc"
        echo "🚀 Loading $svc"
        doas port load "$svc"
    done

    echo "🧹 Flushing DNS cache and resetting network stack"
    doas route delete default
    doas route -n flush
    doas dscacheutil -flushcache
    doas killall -HUP mDNSResponder
    doas networksetup -setdnsservers Wi-Fi 127.0.0.1
    doas ipconfig set en0 NONE
    doas ipconfig set en0 DHCP
    doas route -n flush
    doas service routing restart

    sleep 5

    echo "🔍 Querying xmcnetwork.com on local ports 53 and 5053"
    dig +short A xmcnetwork.com @127.0.0.1 -p53
    dig +short A xmcnetwork.com @127.0.0.1 -p5053

else
    echo "❌ Unsupported OS: $OS"
    exit 1
fi


echo "route delete -net 172.40.0.0/24 192.168.0.1"
doas route delete -net 172.40.0.0/24 192.168.0.1

echo "doas route delete -net 10.0.28.0/24 192.168.40.1"
doas route delete -net 10.0.28.0/24 192.168.40.1 

echo "doas route delete -net 10.0.87.0/24 192.168.40.1"
doas route delete -net 10.0.87.0/24 192.168.40.1 