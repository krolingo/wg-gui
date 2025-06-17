#!/bin/sh

doas route delete default
doas dscacheutil -flushcache
doas killall -HUP mDNSResponder
doas networksetup -setdnsservers Wi-Fi 127.0.0.1
doas route -n flush
doas ipconfig set en0 NONE
doas ipconfig set en0 DHCP