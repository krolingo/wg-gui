#!/bin/sh

OS=$(uname)
if [ "$OS" = "Darwin" ]; then
    DIG="/usr/bin/dig"
elif [ "$OS" = "FreeBSD" ]; then
    DIG="/usr/local/bin/dig"
else
    DIG="dig"  # fallback
fi

# Servers to ping
servers="freebsd.org apple.com google.com amazon.com github.com"

echo "Pinging servers..."
online=0
offline=0

# Detect ping timeout flag
# macOS/BSD: -t (ttl), -W not supported. Linux: -W (timeout), -t (ttl).
if ping -c 1 -t 1 127.0.0.1 >/dev/null 2>&1; then
    ping_timeout="-t 1"
elif ping -c 1 -W 1 127.0.0.1 >/dev/null 2>&1; then
    ping_timeout="-W 1"
else
    ping_timeout=""
fi

for server in $servers; do
    if ping -c 1 $ping_timeout "$server" >/dev/null 2>&1; then
        echo "$server: Online"
        online=$((online+1))
    else
        echo "$server: Offline"
        offline=$((offline+1))
    fi
done

echo ""
echo "Summary: $online online, $offline offline."

sleep .5
echo "🧪 DNS Tests"
echo "-------------------------------------------------------"
echo "pfsense.xmcnetwork.com"
$DIG +short pfsense.xmcnetwork.com
echo "-------------------------------------------------------"
echo "freebsd.org"
$DIG +short freebsd.org
echo "-------------------------------------------------------"
echo "apple.com"
$DIG +short apple.com

echo "✅ DNS restart complete"
exit