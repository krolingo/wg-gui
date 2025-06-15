#!/bin/sh

MIN_SAFE_UTUN_INDEX=10
AS_ROOT="/opt/local/bin/doas"
WGGO="/opt/local/bin/wireguard-go"
PROFILE_DIR="/usr/local/etc/wireguard/profiles"
STATE_DIR="/tmp/wg-multi"
BASE_IFNUM=2
MAPPING_FILE="/tmp/wg-multi/wg-utun.map"

mkdir -p "$STATE_DIR"

usage() {
  echo "Usage: $0 up|down|list profile.conf"
  exit 1
}

get_interface_name() {
  PROFILE="$1"
  echo "wg$((BASE_IFNUM + $(echo "$PROFILE" | cksum | awk '{print $1 % 100}')))"
}

bring_up() {
  PROFILE_FILE="$1"
  PROFILE_PATH="$PROFILE_DIR/$PROFILE_FILE"
  [ ! -f "$PROFILE_PATH" ] && echo "❌ Profile not found: $PROFILE_PATH" && exit 1
  PROFILE_NAME=$(basename "$PROFILE_FILE" .conf)

  mkdir -p "$(dirname "$MAPPING_FILE")"

  MAX_UTUN_INDEX=32
  for (( i=$MIN_SAFE_UTUN_INDEX; i<=MAX_UTUN_INDEX; i++ )); do
    utun_iface="utun$i"
    if ! ifconfig "$utun_iface" >/dev/null 2>&1; then
      NEXT_UTUN="$utun_iface"
      break
    fi
  done

  [ -z "$NEXT_UTUN" ] && echo "❌ No available utun interface" && exit 1
  UTUN_IFACE="$NEXT_UTUN"

  if echo "$UTUN_IFACE" | grep -Eq '^utun[0-4]$'; then
    echo "❌ Refusing to use reserved utun device $UTUN_IFACE"
    exit 1
  fi

  "${AS_ROOT}" "$WGGO" "$NEXT_UTUN"
  if ! ifconfig "$UTUN_IFACE" >/dev/null 2>&1; then
    echo "❌ Interface $UTUN_IFACE not created"
    exit 1
  fi

  "${AS_ROOT}" sh -c "grep -v '|$PROFILE_FILE\$' '$MAPPING_FILE' 2>/dev/null > '${MAPPING_FILE}.tmp'"
  "${AS_ROOT}" sh -c "echo '${UTUN_IFACE}|${PROFILE_FILE}' >> '${MAPPING_FILE}.tmp'"
  "${AS_ROOT}" mv "${MAPPING_FILE}.tmp" "$MAPPING_FILE"

  if grep -q 'AllowedIPs *=.*0.0.0.0/0' "$PROFILE_PATH"; then
    grep '|' "$MAPPING_FILE" | while IFS='|' read -r other_iface other_conf; do
      if [ "$other_iface" != "$UTUN_IFACE" ] && grep -q 'AllowedIPs *=.*0.0.0.0/0' "$PROFILE_DIR/$other_conf"; then
        echo "🔄 Tearing down existing full-tunnel: $other_iface ($other_conf)"
        "${AS_ROOT}" "$0" down "$other_conf"
      fi
    done
  fi

  echo "🔌 Bringing up $PROFILE_FILE as $UTUN_IFACE"
  CLEAN_CONF=$(mktemp)
  grep -Ev '^\s*(Address|DNS|MTU|PostUp|PreUp|PostDown|PreDown)\s*=' "$PROFILE_PATH" > "$CLEAN_CONF"
  "${AS_ROOT}" wg setconf "$UTUN_IFACE" "$CLEAN_CONF" || { rm -f "$CLEAN_CONF"; exit 1; }
  rm -f "$CLEAN_CONF"

  "${AS_ROOT}" ifconfig "$UTUN_IFACE" up

  IP_ADDR=$(grep -m1 '^Address' "$PROFILE_PATH" | cut -d= -f2 | xargs)
  if [ -n "$IP_ADDR" ]; then
    echo "🌐 Assigning IP $IP_ADDR to $UTUN_IFACE"
    WG_PEER="10.0.0.1"
    "${AS_ROOT}" ifconfig "$UTUN_IFACE" "$IP_ADDR" "$WG_PEER" netmask 255.255.255.255 up
  fi

  SERVER_IP=$(grep -m1 '^Endpoint' "$PROFILE_PATH" | cut -d= -f2 | cut -d: -f1 | xargs)
  LAN_GW=$(netstat -rn | awk '$1=="default" { print $2; exit }')
  if [ -n "$SERVER_IP" ] && [ -n "$LAN_GW" ]; then
    echo "🔌 Ensuring route to WG server $SERVER_IP via LAN gateway $LAN_GW"
    "${AS_ROOT}" route add -host "$SERVER_IP" "$LAN_GW"
  fi

  grep -A 10 '\[Peer\]' "$PROFILE_PATH" | grep '^AllowedIPs' | awk '{print $3}' | tr ',' '
' | while read ip; do
    echo "🛣 Adding route for $ip via $UTUN_IFACE"
    if [ "$ip" = "0.0.0.0/0" ]; then
      if [ ! -f /var/run/wg-multi/original_default_gateway ]; then
        ORIGINAL_DEFAULT_GW=$(route -n get default 2>/dev/null | awk '/gateway/ {print $2}')
        echo "$ORIGINAL_DEFAULT_GW" > /var/run/wg-multi/original_default_gateway
      fi
      "${AS_ROOT}" route delete default 2>/dev/null
      "${AS_ROOT}" route add -net "$ip" -interface "$UTUN_IFACE"
    else
      "${AS_ROOT}" route add -net "$ip" -interface "$UTUN_IFACE"
    fi
  done

  DNS_LINE=$(grep -m1 '^DNS[ 	]*=' "$PROFILE_PATH" | cut -d= -f2 | xargs)
  if [ -n "$DNS_LINE" ]; then
    echo "🌐 Backing up /etc/resolv.conf and setting DNS: $DNS_LINE"
    "${AS_ROOT}" cp /etc/resolv.conf "$STATE_DIR/resolv.conf.${UTUN_IFACE}.bak"
    echo "nameserver $DNS_LINE" | "${AS_ROOT}" tee /etc/resolv.conf > /dev/null
  fi

  echo "$PROFILE_FILE" | "${AS_ROOT}" tee "$STATE_DIR/${UTUN_IFACE}.profile" > /dev/null
}

bring_down() {
  PROFILE_FILE="$1"
  PROFILE_PATH="$PROFILE_DIR/$PROFILE_FILE"
  PROFILE_NAME=$(basename "$PROFILE_FILE" .conf)
  INTERFACE=$(grep "|$PROFILE_FILE" "$MAPPING_FILE" 2>/dev/null | cut -d'|' -f1)

  [ -z "$INTERFACE" ] && echo "❌ Could not find interface for $PROFILE_FILE" && exit 1

  echo "🛑 Bringing down $PROFILE_FILE on $INTERFACE"

  "${AS_ROOT}" grep -v "^${INTERFACE}|" "$MAPPING_FILE" > "$MAPPING_FILE.tmp"
  "${AS_ROOT}" mv "$MAPPING_FILE.tmp" "$MAPPING_FILE"

  grep -A 10 '\[Peer\]' "$PROFILE_PATH" | grep '^AllowedIPs' | awk '{print $3}' | tr ',' '
' | while read ip; do
    echo "🗑 Removing route for $ip"
    "${AS_ROOT}" route delete -net "$ip" -interface "$INTERFACE" 2>/dev/null
  done

  if [ -f "$STATE_DIR/resolv.conf.${INTERFACE}.bak" ]; then
    echo "🔄 Restoring /etc/resolv.conf"
    "${AS_ROOT}" cp "$STATE_DIR/resolv.conf.${INTERFACE}.bak" /etc/resolv.conf
    "${AS_ROOT}" rm -f "$STATE_DIR/resolv.conf.${INTERFACE}.bak"
  fi

  current_default_if=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
  if echo "$current_default_if" | grep -q "^utun"; then
    echo "🧹 Deleting dead utun default route"
    "${AS_ROOT}" route delete default
  fi

  ORIG_GATEWAY_FILE="/var/run/wg-multi/original_default_gateway"
  if [ -f "$ORIG_GATEWAY_FILE" ]; then
    DEFAULT_GW=$(cat "$ORIG_GATEWAY_FILE")
    echo "🛣 Restoring original default route via $DEFAULT_GW"
    "${AS_ROOT}" route add default "$DEFAULT_GW"
    rm -f "$ORIG_GATEWAY_FILE"
  else
    LAN_GW=$(ipconfig getoption en0 router 2>/dev/null || netstat -rn | awk '$1=="default"{print $2; exit}')
    if [ -n "$LAN_GW" ]; then
      echo "🛣 Restoring guessed default route via $LAN_GW"
      "${AS_ROOT}" route add default "$LAN_GW"
    else
      echo "⚠️ Could not determine LAN gateway for restoring default route."
    fi
  fi

  "${AS_ROOT}" ifconfig "$INTERFACE" destroy
  "${AS_ROOT}" rm -f "$STATE_DIR/${INTERFACE}.profile"
}

CMD="$1"
PROFILE="$2"

case "$CMD" in
  up)
    [ -z "$PROFILE" ] && usage
    bring_up "$PROFILE"
    ;;
  down)
    [ -z "$PROFILE" ] && usage
    bring_down "$PROFILE"
    ;;
  *)
    usage
    ;;
esac
