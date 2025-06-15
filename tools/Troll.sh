#!/bin/sh

OS="$(uname -s)"

get_uptime() {
    case "$OS" in
        Darwin|FreeBSD)
            boot=$(sysctl -n kern.boottime | awk -F'[=,]' '{print $2}')
            now=$(date +%s)
            s=$((now - boot))
            ;;
        *)
            # Fallback: uptime in seconds
            s=$(awk '{print int($1)}' /proc/uptime 2>/dev/null || echo 0)
            ;;
    esac

    d=$((s / 86400))
    h=$((s % 86400 / 3600))
    m=$((s % 3600 / 60))

    # Pluralize
    [ "$d" -eq 1 ] && d="1 day" || d="$d days"
    [ "$h" -eq 1 ] && h="1 hour" || h="$h hours"
    [ "$m" -eq 1 ] && m="1 minute" || m="$m minutes"

    # Omit zero units
    [ "$d" = "0 days" ] && unset d
    [ "$h" = "0 hours" ] && unset h
    [ "$m" = "0 minutes" ] && unset m

    uptime="${d:+$d, }${h:+$h, }${m:-0 minutes}"
    echo "${uptime%, }"
}

get_memory() {
    case "$OS" in
        Darwin)
            mem_total=$(( $(sysctl -n hw.memsize) / 1048576 ))
            wired=$(vm_stat | awk '/ wired:/ {gsub("\\.","",$4); print $4}')
            active=$(vm_stat | awk '/ active:/ {gsub("\\.","",$3); print $3}')
            compressed=$(vm_stat | awk '/ occupied:/ {gsub("\\.","",$5); print $5}')
            ;;
        FreeBSD)
            mem_total=$(( $(sysctl -n hw.physmem) / 1048576 ))
            # pages are 4096 bytes
            wired=$(vmstat -m | awk '/wired/ {print $2}')
            active=$(vmstat -m | awk '/active/ {print $2}')
            compressed=0
            ;;
        *)
            echo "Memory info not supported on $OS"
            return
            ;;
    esac

    # if variables empty
    wired=${wired:-0}; active=${active:-0}; compressed=${compressed:-0}

    # convert pages→MiB (Darwin vm_stat pages are 4096 bytes, FreeBSD vmstat -m units vary—approx pages)
    used=$(( (wired + active + compressed) * 4096 / 1048576 ))
    echo "${used} MiB / ${mem_total} MiB"
}

get_battery() {
    case "$OS" in
        Darwin)
            batt=$(pmset -g batt | awk '/%/ {print $3 $4}')
            [ -z "$batt" ] && batt="N/A"
            if pmset -g batt | grep -q "AC Power"; then
                batt="${batt} (charging)"
            else
                rem=$(pmset -g batt | awk '/remaining/ {print $NF}')
                batt="${batt} (${rem:-unknown})"
            fi
            ;;
        FreeBSD)
            if command -v apm >/dev/null 2>&1; then
                pct=$(apm -l)
                state=$(apm -a)
                case "$state" in
                    0) status="charging" ;;
                    1) status="on battery" ;;
                    *) status="unknown" ;;
                esac
                batt="${pct}% (${status})"
            else
                batt="N/A"
            fi
            ;;
        *)
            batt="N/A"
            ;;
    esac
    echo "$batt"
}

get_default_route() {
    case "$OS" in
        Darwin|FreeBSD)
            route -n get default 2>/dev/null | awk '/gateway:/ {print $2}'
            ;;
        *)
            ip route get 1.1.1.1 2>/dev/null | awk '/via/ {print $3}'
            ;;
    esac
}

get_ssid() {
    case "$(uname -s)" in
        Darwin)
            ssid=$(python3 ./get_ssid.py 2>/dev/null)
            ;;
        FreeBSD)
            ssid=$(
              ifconfig wlan0 2>/dev/null \
                | sed -n 's/.*ssid "\([^"]*\)".*/\1/p' \
                | head -n1
            )
            ;;
        *)
            ssid=""
            ;;
    esac

    [ -z "$ssid" ] && echo "N/A" || echo "$ssid"
}

echo "System Information"
echo
echo "Uptime:       $(get_uptime)"
echo "Memory:       $(get_memory)"
echo "Battery:      $(get_battery)"
echo

echo "Date:         $(date +'%a %d. %b %Y')"
echo "Local IP:     $(ifconfig | awk '/inet / && !/127.0.0.1/ {print $2; exit}' )"
echo "Gateway:      $(get_default_route)"
echo "WiFi SSID:    $(get_ssid)"
echo
echo "Public IP:    $(curl -s https://ipinfo.io/ip 2>/dev/null || echo 'Unavailable')"
echo "DNS lookup:   $(dig +short google.com | head -1 2>/dev/null || echo 'Unavailable')"
echo "DNS server:   $(dig google.com +noall +stats +nocomments | awk '/SERVER:/ {print $3}' )"
