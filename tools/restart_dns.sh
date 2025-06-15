#!/bin/sh
#
# restart_dns.sh — unified macOS + FreeBSD DNS restart script

set -eu

OS=$(uname)

if [ "$OS" = "Darwin" ]; then
  export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

  echo "🔄 Restarting DNS services (macOS)"
  echo "➡️  doas port unload nsd"
  doas port unload nsd || true
  echo "➡️  doas killall nsd"
  doas killall nsd || true
  echo "➡️  doas port load nsd"
  doas port load nsd || true

  echo "➡️  doas port unload unbound"
  doas port unload unbound || true
  echo "➡️  doas killall unbound"
  doas killall unbound || true
  echo "➡️  doas port load unbound"
  doas port load unbound || true

  echo "🧹 Flushing DNS cache"
  doas dscacheutil -flushcache
  doas killall -HUP mDNSResponder

  sleep 5

  echo "🧪 Testing DNS"
  dig +short A xmcnetwork.com @127.0.0.1 -p53
  dig +short A xmcnetwork.com @127.0.0.1 -p5053

else
  echo "🔄 Restarting DNS services (FreeBSD)"
  doas bastille restart unbound_blocker || true

  echo "🛠 Setting nameserver and search base"
  # Optionally copy static resolv.conf if needed
  # doas cp ~/bin/conf/resolv.conf-10.122.123.53 /etc/resolv.conf
  doas resolvconf -u || true

  sleep 1
  echo "🧪 DNS Tests"
  echo "-------------------------------------------------------"
  echo "pfsense.xmcnetwork.com"
  /usr/local/bin/dig +short pfsense.xmcnetwork.com
  echo "-------------------------------------------------------"
  echo "freebsd.org"
  /usr/local/bin/dig +short freebsd.org
  echo "-------------------------------------------------------"
  echo "apple.com"
  /usr/local/bin/dig +short apple.com
fi

echo "✅ DNS restart complete"
exit 0
