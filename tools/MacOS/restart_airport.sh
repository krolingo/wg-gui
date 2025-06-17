#!/usr/bin/env bash
#
# restart_airport.sh — cycle the macOS Wi-Fi interface
# (ASCII-only; forces UTF-8 locale)

set -eu

# ensure all output is in UTF-8
export LC_ALL=en_US.UTF-8

# find the Wi-Fi device name (e.g. en0, en1)
INTERFACE=$(
  networksetup -listallhardwareports \
    | awk '/Hardware Port: Wi-Fi/{ getline; print $2 }'
)

if [ -z "$INTERFACE" ]; then
  echo "ERROR: Wi-Fi interface not found" >&2
  exit 1
fi

echo "Turning Wi-Fi off on $INTERFACE"
networksetup -setairportpower "$INTERFACE" off

sleep 2

echo "Turning Wi-Fi on on $INTERFACE"
networksetup -setairportpower "$INTERFACE" on

echo "Done"
exit 0