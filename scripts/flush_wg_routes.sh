#!/bin/sh
# flush_wg_routes.sh
# Safely flush all routes via a WireGuard interface, e.g. wg0

IFACE="${1:-wg0}"
ROUTES=$(netstat -rn -f inet | awk -v iface="$IFACE" '$NF == iface {print $1}')

if [ -z "$ROUTES" ]; then
  echo "[flush_wg_routes] No routes found for interface $IFACE"
  exit 0
fi

echo "[flush_wg_routes] Flushing routes for interface $IFACE:"
for r in $ROUTES; do
  echo "[flush_wg_routes] Deleting route: $r"
  /sbin/route delete "$r" > /dev/null 2>&1
done
