#!/bin/sh
# Restore route to local DNS jail after full-tunnel hijack
LAN_GATEWAY=$(cat /tmp/wg-multi/original_lan_gateway 2>/dev/null)

if [ -n "$LAN_GATEWAY" ]; then
  echo "🛣 Restoring bypass route to jail DNS via $LAN_GATEWAY"
  route add -host 10.122.123.53 "$LAN_GATEWAY"
else
  echo "⚠️  No saved LAN gateway found; DNS route not added."
fi
