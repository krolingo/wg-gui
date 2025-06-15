#!/bin/sh
#
# restart_wifi.sh — cross-platform Wi-Fi interface restarter
# Supports macOS (using networksetup) and FreeBSD/Linux (via custom script)

set -eu

OS=$(uname)

if [ "$OS" = "Darwin" ]; then
  # macOS logic
  export LC_ALL=en_US.UTF-8

  INTERFACE=$(
    networksetup -listallhardwareports \
      | awk '/Hardware Port: Wi-Fi/{ getline; print $2 }'
  )

  if [ -z "$INTERFACE" ]; then
    echo "❌ ERROR: Wi-Fi interface not found" >&2
    exit 1
  fi

  echo "🔌 Turning Wi-Fi off on $INTERFACE"
  networksetup -setairportpower "$INTERFACE" off
  sleep 2
  echo "🔌 Turning Wi-Fi on on $INTERFACE"
  networksetup -setairportpower "$INTERFACE" on
  echo "✅ Done (macOS)"
else
  # Assume FreeBSD/Linux
  echo "🔄 Restarting Wi-Fi using network.sh"
  /home/mcapella/scripts/network.sh wlan restart
  echo "✅ Done (FreeBSD/Linux)"
fi

exit 0
