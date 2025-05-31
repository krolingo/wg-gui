#!/bin/sh

MONITOR_PIDFILE="/tmp/route-monitor-$2.pid"

start() {
    # Run route monitor in background, redirect output, store PID
    (while :; do netstat -rn | grep "$2"; sleep 10; done) > /dev/null 2>&1 &
        
#(while :; do echo "[route_monitor] $(date)"; netstat -rn | grep "$2"; sleep 10; done) &

    echo $! > "$MONITOR_PIDFILE"
}

stop() {
    if [ -f "$MONITOR_PIDFILE" ]; then
        kill "$(cat "$MONITOR_PIDFILE")" 2>/dev/null
        rm -f "$MONITOR_PIDFILE"
    fi
}

case "$1" in
    start) start ;;
    stop)  stop ;;
    *) echo "Usage: $0 {start|stop} INTERFACE" ;;
esac
