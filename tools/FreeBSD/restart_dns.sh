#!/bin/sh
doas bastille restart unbound_blocker
echo "Setting name server to 10.122.123.53 and pertinent search base information"
#doas cp ~/bin/conf/resolv.conf-10.122.123.53 /etc/resolv.conf
doas resolvconf -u
sleep 0
echo "-------------------------------------------------------"

echo "pfsense.xmcnetwork.com"
/usr/local/bin/dig +short pfsense.xmcnetwork.com
echo "-------------------------------------------------------"

echo freebsd.org
/usr/local/bin/dig +short freebsd.org
echo "-------------------------------------------------------"

echo "apple.com"
/usr/local/bin/dig +short apple.com
