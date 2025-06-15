#!/bin/sh

# Attempt to restore default route after bringing down a 0.0.0.0/0 VPN tunnel on macOS

echo "🔻 [PostDown] Cleaning up default route for 0.0.0.0/0..."




# Retry loop to ensure all utun-bound default routes are removed
for attempt in 1 2 3; do
    echo "🔁 [PostDown] Attempt $attempt: Flushing utun-bound default routes..."
    for utun_iface in utun0 utun1 utun2 utun3 utun4 utun5; do
        if netstat -rn | grep -q "default.*${utun_iface}"; then
            echo "🗑 Deleting default route bound to $utun_iface..."
            sudo route delete -inet6 default -interface $utun_iface 2>/dev/null
            sudo route delete default -interface $utun_iface 2>/dev/null
        fi
    done

    # If no utun-bound default route remains, stop retrying
    if ! netstat -rn | grep -q "default.*utun"; then
        echo "✅ All utun-bound default routes removed."
        break
    fi

    echo "⏳ utun-bound default routes still exist, retrying in 1s..."
    sleep 1
done


# Attempt to restore default route via en0 (Wi-Fi)
if ifconfig en0 >/dev/null 2>&1 && ipconfig getifaddr en0 >/dev/null 2>&1; then
    LAN_GW=$(route -n get default | awk '/gateway/ {print $2}')
    if [ -z "$LAN_GW" ]; then
        LAN_GW=$(ipconfig getoption en0 router)
    fi
    if [ -n "$LAN_GW" ]; then
        echo "🛠 Restoring default route via en0 ($LAN_GW)"
        sudo route add default "$LAN_GW"
    else
        echo "❌ Could not determine LAN gateway via en0"
    fi
else
    echo "❌ en0 not available or has no IP address"
fi

# Check if internet is reachable again
if ping -c1 -t1 1.1.1.1 >/dev/null 2>&1; then
    echo "✅ Internet is reachable post PostDown."
else
    echo "❌ Internet still unreachable. You may need to disable and re-enable Wi-Fi."
fi
netstat -rn | grep default