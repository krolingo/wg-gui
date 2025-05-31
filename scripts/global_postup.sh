#!/bin/sh
# global_postup.sh - global PostUp hook for WireGuard

IFACE="${1:-wg0}"

echo "[global_postup] ✅ WireGuard up: $IFACE"
date

# Optional: log routes
echo "[global_postup] Routing table entries:"
netstat -rn -f inet | grep "$IFACE" || echo "  (no routes found)"

echo "[global_postup] Starting route monitor for $IFACE..."
/home/mcapella/scripts/wireguard_client/scripts/route_monitor.sh start "$IFACE"

echo "[global_postup] Done."
