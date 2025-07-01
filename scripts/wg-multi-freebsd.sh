#!/bin/sh

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
  INTERFACE=$(get_interface_name "$PROFILE_NAME")

  mkdir -p "$(dirname "$MAPPING_FILE")"
  doas sh -c "grep -v '|$PROFILE_FILE\$' '$MAPPING_FILE' 2>/dev/null > '${MAPPING_FILE}.tmp'"
  doas sh -c "echo '${INTERFACE}|${PROFILE_FILE}' >> '${MAPPING_FILE}.tmp'"
  doas mv "${MAPPING_FILE}.tmp" "$MAPPING_FILE"

  echo "🔌 Bringing up $PROFILE_FILE as $INTERFACE"

  if doas ifconfig "$INTERFACE" >/dev/null 2>&1; then
    echo "⚠️  Interface $INTERFACE already exists. Destroying first..."
    doas ifconfig "$INTERFACE" destroy
  fi

  doas ifconfig "$INTERFACE" create || exit 1

  if grep -q "^PreUp" "$PROFILE_PATH" 2>/dev/null; then
    preup="$(grep '^PreUp' "$PROFILE_PATH" | cut -d'=' -f2- | xargs)"
    if [ -x "$preup" ]; then
      echo "🔧 Running PreUp hook: $preup"
      "$preup"
    fi
  fi

  CLEAN_CONF=$(mktemp)
  grep -Ev '^\s*(Address|DNS|MTU|PostUp|PreUp|PostDown|PreDown)\s*=' "$PROFILE_PATH" > "$CLEAN_CONF"
  doas wg setconf "$INTERFACE" "$CLEAN_CONF" || { rm -f "$CLEAN_CONF"; exit 1; }
  rm -f "$CLEAN_CONF"

  doas ifconfig "$INTERFACE" up

  IP_ADDR=$(grep -m1 '^Address' "$PROFILE_PATH" | cut -d= -f2 | xargs)
  if [ -n "$IP_ADDR" ]; then
    echo "🌐 Assigning IP $IP_ADDR to $INTERFACE"
    doas ifconfig "$INTERFACE" inet "$IP_ADDR" alias
  fi

  SERVER_IP=$(grep -m1 '^Endpoint' "$PROFILE_PATH" | cut -d= -f2 | cut -d: -f1 | xargs)
  LAN_GW=$(netstat -rn | awk '$1=="default" { print $2; exit }')
  if [ -n "$SERVER_IP" ] && [ -n "$LAN_GW" ]; then
    echo "🔌 Ensuring route to WG server $SERVER_IP via LAN gateway $LAN_GW"
    doas route add -host "$SERVER_IP" "$LAN_GW"
  fi

grep -A 10 '\[Peer\]' "$PROFILE_PATH" | grep '^AllowedIPs' | awk -F= '{print $2}' | tr ',' '\n' | while read ip; do
  ip=$(echo "$ip" | xargs)  # Trim whitespace
  [ -n "$ip" ] || continue  # Skip empty lines

  echo "🛣 Adding route for $ip via $INTERFACE"

  if [ "$ip" = "0.0.0.0/0" ]; then
    ORIGINAL_DEFAULT=$(netstat -rn | awk '$1=="default" { print $2; exit }')
    if [ -n "$ORIGINAL_DEFAULT" ]; then
      echo "$ORIGINAL_DEFAULT" | doas tee "$STATE_DIR/default.route.${INTERFACE}" > /dev/null
    fi
    doas route delete default
    doas route add -net "$ip" -interface "$INTERFACE"
  else
    doas route add -net "$ip" -interface "$INTERFACE"
  fi
done



  DNS_LINE=$(grep -m1 '^DNS[ 	]*=' "$PROFILE_PATH" | cut -d= -f2- | xargs)
  SEARCH_LINE=$(grep -m1 '^SearchDomains[ 	]*=' "$PROFILE_PATH" | cut -d= -f2- | xargs)
  [ -z "$SEARCH_LINE" ] && SEARCH_LINE="$DEFAULT_SEARCH_DOMAINS"
  if [ -n "$DNS_LINE" ]; then
    echo "🌐 Backing up /etc/resolv.conf and setting DNS: $DNS_LINE"
    doas cp /etc/resolv.conf "$STATE_DIR/resolv.conf.${INTERFACE}.bak"
    {
      echo "search $SEARCH_LINE"
      echo "$DNS_LINE" | tr ',' '
' | sed 's/^/nameserver /'
    } | doas tee /etc/resolv.conf > /dev/null
  fi

  # === PostUp hook (with %i expansion) ===
  if grep -q "^PostUp" "$PROFILE_PATH" 2>/dev/null; then
    # read raw command (everything after the '=')
    raw=$(grep '^PostUp' "$PROFILE_PATH" | cut -d'=' -f2-)

    # trim whitespace and expand %i to the actual interface
    raw=$(echo "$raw" \
      | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' \
            -e "s/%i/$INTERFACE/g")

    # split into executable and its args
    cmd=$(echo "$raw" | awk '{print $1}')
    args=$(echo "$raw" | cut -s -d' ' -f2-)

    if [ -x "$cmd" ]; then
      echo "🔧 Running PostUp hook: $cmd $args"
      "$cmd" $args
    else
      echo "⚠️ PostUp hook not executable or missing: $cmd"
    fi
  fi

  echo "$PROFILE_FILE" | doas tee "$STATE_DIR/${INTERFACE}.profile" > /dev/null
}


bring_down() {
  PROFILE_FILE="$1"
  PROFILE_PATH="$PROFILE_DIR/$PROFILE_FILE"

  PROFILE_NAME=$(basename "$PROFILE_FILE" .conf)
  INTERFACE=$(get_interface_name "$PROFILE_NAME")

  if grep -q "^PreDown" "$PROFILE_PATH" 2>/dev/null; then
    predscript="$(grep '^PreDown' "$PROFILE_PATH" | cut -d'=' -f2- | xargs)"
    if [ -x "$predscript" ]; then
      echo "🔧 Running PreDown hook: $predscript"
      "$predscript"
    fi
  fi

  echo "🛑 Bringing down $PROFILE_FILE on $INTERFACE"

  echo "[-] Removing interface $INTERFACE mapping from $MAPPING_FILE"
  if [ -f "$MAPPING_FILE" ]; then
    doas grep -v "^${INTERFACE}|" "$MAPPING_FILE" > "$MAPPING_FILE.tmp"
    doas mv "$MAPPING_FILE.tmp" "$MAPPING_FILE"
    sync
    echo "[-] Mapping file contents after forced removal and sync:"
    doas cat "$MAPPING_FILE"
  else
    echo "[-] Mapping file $MAPPING_FILE not found"
  fi

  grep -A 10 '\[Peer\]' "$PROFILE_PATH" | grep '^AllowedIPs' | awk '{print $3}' | tr ',' '\n' | while read ip; do
    echo "🗑 Removing route for $ip"
    doas route delete -net "$ip" -interface "$INTERFACE"
  done

  if [ -f "$STATE_DIR/resolv.conf.${INTERFACE}.bak" ]; then
    echo "🔄 Restoring /etc/resolv.conf"
    doas cp "$STATE_DIR/resolv.conf.${INTERFACE}.bak" /etc/resolv.conf
    doas rm -f "$STATE_DIR/resolv.conf.${INTERFACE}.bak"
  fi

  if [ -f "$STATE_DIR/default.route.${INTERFACE}" ]; then
    OLD_ROUTE=$(cat "$STATE_DIR/default.route.${INTERFACE}")
    echo "🔁 Restoring previous default route via $OLD_ROUTE"
    doas route add default "$OLD_ROUTE"
    doas rm -f "$STATE_DIR/default.route.${INTERFACE}"
  fi

  if doas ifconfig "$INTERFACE" >/dev/null 2>&1; then
    doas ifconfig "$INTERFACE" destroy
  else
    echo "⚠️  Interface $INTERFACE not found."
  fi

  doas rm -f "$STATE_DIR/${INTERFACE}.profile"

  if grep -q "^PostDown" "$PROFILE_PATH" 2>/dev/null; then
    postdown="$(grep '^PostDown' "$PROFILE_PATH" | cut -d'=' -f2- | xargs)"
    if [ -x "$postdown" ]; then
      echo "🔧 Running PostDown hook: $postdown"
      "$postdown"
    fi
  fi
}

list_active() {
  printf "%-10s %-25s %-20s %-20s %-25s\n" "Interface" "Profile" "Handshake" "AllowedIPs" "Endpoint"
  echo "----------------------------------------------------------------------------------------------------"

  doas wg show interfaces | tr ' ' '\n' | grep '^wg[0-9]\+$' | while read iface; do
    PROFILE_FILE=$(cat "$STATE_DIR/${iface}.profile" 2>/dev/null || echo "-")
    HANDSHAKE=$(doas wg show "$iface" latest-handshakes | awk '{print $2}')
    if [ "$HANDSHAKE" -eq 0 ]; then
      HANDSHAKE_STR="Never"
    else
      HANDSHAKE_STR="$(($(date +%s) - HANDSHAKE))s ago"
    fi
    ALLOWED=$(doas wg show "$iface" allowed-ips | awk '{print $2}' | paste -sd "," -)
    ENDPOINT=$(doas wg show "$iface" endpoints | awk '{print $2}')
    printf "%-10s %-25s %-20s %-20s %-25s\n" "$iface" "$PROFILE_FILE" "$HANDSHAKE_STR" "$ALLOWED" "$ENDPOINT"
  done
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
  list)
    list_active
    ;;
  *)
    usage
    ;;
esac
