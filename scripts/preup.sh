#!/bin/sh
# Save the current default gateway (LAN) before WG takes over
GATEWAY=$(route -n get default | awk '/gateway: / {print $2}')
[ -n "$GATEWAY" ] && echo "$GATEWAY" > /tmp/wg-multi/original_lan_gateway
