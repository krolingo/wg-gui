#!/bin/bash
export PATH="/usr/local/bin:/opt/homebrew/bin:/opt/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
echo "doas port unload nsd"
doas port unload nsd
echo "doas killall nsd"
doas killall nsd
echo "doas port load nsd"
doas port load nsd
echo "doas port unload unbound"
doas port unload unbound
echo "doas killall unbound"
doas killall unbound
echo "doas port load unbound"
doas port load unbound
echo "doas dscacheutil -flushcache; doas killall -HUP mDNSResponder"
doas dscacheutil -flushcache; doas killall -HUP mDNSResponder
sleep 5
echo "dig +short A xmcnetwork.com @127.0.0.1 -p53"
dig +short A xmcnetwork.com @127.0.0.1 -p53
echo "dig +short A xmcnetwork.com @127.0.0.1 -p5053"
dig +short A xmcnetwork.com @127.0.0.1 -p5053
