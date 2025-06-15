#!/bin/sh
echo "Default Routes"
echo

# IPv4 default routes
echo "IPv4:"
netstat -rn | awk '$1 == "default" {printf "  Interface: %-10s  Gateway: %-16s  Flags: %s\n", $NF, $2, $4}'
echo

# IPv6 default routes
echo "IPv6:"
netstat -rn -f inet6 2>/dev/null | awk '$1 == "default" {printf "  Interface: %-10s  Gateway: %-40s  Flags: %s\n", $NF, $2, $4}'
echo

# Show which interface is currently up and has the default route
echo "Active Default Interface(s):"
route get default 2>/dev/null | awk '/interface: / {print "  " $2}'