#!/bin/sh

# Wait a moment to allow utun cleanup
sleep 1

# Look for any remaining active full-tunnel
for intf in $(/usr/local/bin/wg show interfaces); do
    if /usr/local/bin/wg show "$intf" allowed-ips | grep -q "0.0.0.0/0"; then
        echo "🛣 Restoring default route via $intf"
        /sbin/route add default -interface "$intf"
        exit 0
    fi
done

echo "⚠️  No other full-tunnel interface found — default route not restored."
exit 1