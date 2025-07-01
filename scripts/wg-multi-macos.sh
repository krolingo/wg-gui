#!/usr/bin/env bash

MIN_SAFE_UTUN_INDEX=10
# Determine escalation command: prefer doas, fallback to sudo
if command -v doas >/dev/null 2>&1; then
    AS_ROOT="doas"
elif command -v sudo >/dev/null 2>&1; then
    AS_ROOT="sudo"
else
    echo "Error: no privilege escalation command found (doas or sudo)" >&2
    exit 1
fi

# If running as root (e.g. via AppleScript elevation), skip prefixing with AS_ROOT
if [ "$(id -u)" -eq 0 ]; then
    ESC_CMD=""
else
    ESC_CMD="$AS_ROOT"
fi

### Determine bundle-relative bin directory for included binaries
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_RESOURCES="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$BUNDLE_RESOURCES/bin"

# Ensure wg binary is found (bundle first, then system paths)
WG_CMD=""
if [ -x "$BIN_DIR/wg" ]; then
    WG_CMD="$BIN_DIR/wg"
elif command -v wg >/dev/null 2>&1; then
    WG_CMD="$(command -v wg)"
elif command -v /opt/homebrew/bin/wg >/dev/null 2>&1; then
    WG_CMD="/opt/homebrew/bin/wg"
elif command -v /usr/local/bin/wg >/dev/null 2>&1; then
    WG_CMD="/usr/local/bin/wg"
elif command -v /opt/local/bin/wg >/dev/null 2>&1; then
    WG_CMD="/opt/local/bin/wg"
fi
if [ -z "$WG_CMD" ]; then
  echo "Error: 'wg' binary not found in bundle or system paths" >&2
  exit 1
fi

if [ "$(uname)" = "Darwin" ]; then
  DNS_SWITCH_SCRIPT="/Users/mcapella/bin/switch_jailed_dns.sh"
else
  DNS_SWITCH_SCRIPT="/home/mcapella/bin/switch_jailed_dns.sh"
fi

### Determine bundle-relative bin directory for included binaries
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_RESOURCES="$(dirname "$SCRIPT_DIR")"
BIN_DIR="$BUNDLE_RESOURCES/bin"

# Locate wireguard-go binary, preferring bundled copy
if [ -x "$BIN_DIR/wireguard-go" ]; then
    WGGO="$BIN_DIR/wireguard-go"
elif command -v wireguard-go >/dev/null 2>&1; then
    WGGO="$(command -v wireguard-go)"
elif command -v /opt/homebrew/bin/wireguard-go >/dev/null 2>&1; then
    WGGO="/opt/homebrew/bin/wireguard-go"
elif command -v /usr/local/bin/wireguard-go >/dev/null 2>&1; then
    WGGO="/usr/local/bin/wireguard-go"
elif command -v /opt/local/bin/wireguard-go >/dev/null 2>&1; then
    WGGO="/opt/local/bin/wireguard-go"
else
    echo "Error: 'wireguard-go' binary not found in bundle or system paths" >&2
    exit 1
fi
PROFILE_DIR="/usr/local/etc/wireguard/profiles"
STATE_DIR="/tmp/wg-multi"
mkdir -p "$STATE_DIR"
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
  PROFILE_NAME=$(basename -- "$PROFILE_FILE" .conf)

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

  ${ESC_CMD} "$WGGO" "$NEXT_UTUN"
  if ! ifconfig "$UTUN_IFACE" >/dev/null 2>&1; then
    echo "❌ Interface $UTUN_IFACE not created"
    exit 1
  fi

  ${ESC_CMD} sh -c "grep -v '|$PROFILE_FILE\$' '$MAPPING_FILE' 2>/dev/null > '${MAPPING_FILE}.tmp'"
  ${ESC_CMD} sh -c "echo '${UTUN_IFACE}|${PROFILE_FILE}' >> '${MAPPING_FILE}.tmp'"
  ${ESC_CMD} mv "${MAPPING_FILE}.tmp" "$MAPPING_FILE"

  if grep -q 'AllowedIPs *=.*0.0.0.0/0' "$PROFILE_PATH"; then
    grep '|' "$MAPPING_FILE" | while IFS='|' read -r other_iface other_conf; do
      if [ "$other_iface" != "$UTUN_IFACE" ] && grep -q 'AllowedIPs *=.*0.0.0.0/0' "$PROFILE_DIR/$other_conf"; then
        echo "🔄 Tearing down existing full-tunnel: $other_iface ($other_conf)"
        ${ESC_CMD} "$0" down "$other_conf"
      fi
    done
  fi

  echo "🔌 Bringing up $PROFILE_FILE as $UTUN_IFACE"
  CLEAN_CONF=$(mktemp)
  grep -Ev '^\s*(Address|DNS|MTU|PostUp|PreUp|PostDown|PreDown)\s*=' "$PROFILE_PATH" > "$CLEAN_CONF"
  ${ESC_CMD} "$WG_CMD" setconf "$UTUN_IFACE" "$CLEAN_CONF" || { rm -f "$CLEAN_CONF"; exit 1; }
  rm -f "$CLEAN_CONF"

  ${ESC_CMD} ifconfig "$UTUN_IFACE" up

  IP_ADDR=$(grep -m1 '^Address' "$PROFILE_PATH" | cut -d= -f2 | xargs)
  if [ -n "$IP_ADDR" ]; then
    echo "🌐 Assigning IP $IP_ADDR to $UTUN_IFACE"
    WG_PEER="10.0.0.1"
    ${ESC_CMD} ifconfig "$UTUN_IFACE" "$IP_ADDR" "$WG_PEER" netmask 255.255.255.255 up
  fi

  SERVER_IP=$(grep -m1 '^Endpoint' "$PROFILE_PATH" | cut -d= -f2 | cut -d: -f1 | xargs)
  LAN_GW=$(netstat -rn | awk '$1=="default" { print $2; exit }')
  if [ -n "$SERVER_IP" ] && [ -n "$LAN_GW" ]; then
    echo "🔌 Ensuring route to WG server $SERVER_IP via LAN gateway $LAN_GW"
    ${ESC_CMD} route add -host "$SERVER_IP" "$LAN_GW"
  fi

  grep -A 10 '\[Peer\]' "$PROFILE_PATH" \
    | grep '^AllowedIPs' \
    | cut -d= -f2 \
    | tr ',' '\n' \
    | while read -r ip; do
      # Trim whitespace and skip empty lines
      ip=$(echo "$ip" | xargs)
      [ -z "$ip" ] && continue
      echo "🛣 Adding route for $ip via $UTUN_IFACE"
      if [ "$ip" = "0.0.0.0/0" ]; then
        if [ ! -f "$STATE_DIR/original_default_gateway" ]; then
          # Preserve all directly-connected local networks dynamically
          if [ ! -f "$STATE_DIR/original_default_gateway" ]; then
            ORIGINAL_DEFAULT_GW=$(route -n get default 2>/dev/null | awk '/gateway/ {print $2}')
            echo "$ORIGINAL_DEFAULT_GW" > "$STATE_DIR/original_default_gateway"
          fi
          echo "🛣 Preserving directly-connected local subnets"
          # Detect and preserve each subnet whose gateway is link#*
          ${ESC_CMD} netstat -rn -f inet | awk '$2 ~ /^link#/ {print $1}' | while read -r subnet; do
            echo "  ↳ $subnet via $ORIGINAL_DEFAULT_GW"
            ${ESC_CMD} route add -net "$subnet" "$ORIGINAL_DEFAULT_GW" 2>/dev/null || true
          done
        fi
        ${ESC_CMD} route delete default 2>/dev/null
        ${ESC_CMD} route add -net "$ip" -interface "$UTUN_IFACE"
      else
        ${ESC_CMD} route add -net "$ip" -interface "$UTUN_IFACE"
      fi
    done

  DNS_LINE=$(grep -m1 '^DNS[ 	]*=' "$PROFILE_PATH" | cut -d= -f2- | tr -d '\r' | xargs)
  if [ -n "$DNS_LINE" ]; then
      echo "🌐 Backing up /etc/resolv.conf and setting DNS entries: $DNS_LINE"
      ${ESC_CMD} cp /etc/resolv.conf "$STATE_DIR/resolv.conf.${UTUN_IFACE}.bak"
      DNS_OUTPUT=""
      SEARCH_OUTPUT=""
      IFS=',' read -r -a dns_array <<< "$DNS_LINE"
      for entry in "${dns_array[@]}"; do
          trimmed=$(echo "$entry" | tr -d '\r' | xargs)
          if echo "$trimmed" | grep -Eq '^([0-9]{1,3}\.){3}[0-9]{1,3}$'; then
              DNS_OUTPUT+="nameserver $trimmed"$'\n'
          else
              SEARCH_OUTPUT+="search $trimmed"$'\n'
          fi
      done
      echo -n "$SEARCH_OUTPUT$DNS_OUTPUT" | ${ESC_CMD} tee /etc/resolv.conf > /dev/null
  fi

  # ▶ Execute any PostUp commands defined in the profile
  grep '^PostUp' "$PROFILE_PATH" | cut -d= -f2- | while IFS= read -r cmd; do
    echo "⚙️ Running PostUp: $cmd"
    ${ESC_CMD} sh -c "$cmd"
  done
  echo "$PROFILE_FILE" | ${ESC_CMD} tee "$STATE_DIR/${UTUN_IFACE}.profile" > /dev/null
}

bring_down() {
  PROFILE_FILE="$1"
  PROFILE_PATH="$PROFILE_DIR/$PROFILE_FILE"
  PROFILE_NAME=$(basename -- "$PROFILE_FILE" .conf)
  INTERFACE=$(grep "|$PROFILE_FILE" "$MAPPING_FILE" 2>/dev/null | cut -d'|' -f1)

  [ -z "$INTERFACE" ] && echo "❌ Could not find interface for $PROFILE_FILE" && exit 1

  echo "🛑 Bringing down $PROFILE_FILE on $INTERFACE"
  # Kill wireguard-go process for this interface
  if pgrep -f "$WGGO $INTERFACE" >/dev/null 2>&1; then
    echo "🗡️ Killing wireguard-go for $INTERFACE"
    ${ESC_CMD} pkill -f "$WGGO $INTERFACE"
  fi

  ${ESC_CMD} grep -v "^${INTERFACE}|" "$MAPPING_FILE" > "$MAPPING_FILE.tmp"
  ${ESC_CMD} mv "$MAPPING_FILE.tmp" "$MAPPING_FILE"

  grep -A 10 '\[Peer\]' "$PROFILE_PATH" \
    | grep '^AllowedIPs' \
    | cut -d= -f2 \
    | tr ',' '\n' \
    | while read -r ip; do
      # Trim whitespace and skip empty lines
      ip=$(echo "$ip" | xargs)
      [ -z "$ip" ] && continue
      echo "🗑 Removing route for $ip"
      ${ESC_CMD} route delete -net "$ip" -interface "$INTERFACE" 2>/dev/null
    done

  if [ -f "$STATE_DIR/resolv.conf.${INTERFACE}.bak" ]; then
    echo "🔄 Restoring /etc/resolv.conf"
    ${ESC_CMD} cp "$STATE_DIR/resolv.conf.${INTERFACE}.bak" /etc/resolv.conf
    ${ESC_CMD} rm -f "$STATE_DIR/resolv.conf.${INTERFACE}.bak"
  fi

  current_default_if=$(route -n get default 2>/dev/null | awk '/interface:/{print $2}')
  if echo "$current_default_if" | grep -q "^utun"; then
    echo "🧹 Deleting dead utun default route"
    ${ESC_CMD} route delete default
  fi

  ORIG_GATEWAY_FILE="$STATE_DIR/original_default_gateway"
  if [ -f "$ORIG_GATEWAY_FILE" ]; then
    DEFAULT_GW=$(cat "$ORIG_GATEWAY_FILE")
    echo "🛣 Restoring original default route via $DEFAULT_GW"
    ${ESC_CMD} route add default "$DEFAULT_GW"
    rm -f "$ORIG_GATEWAY_FILE"
  else
    LAN_GW=$(ipconfig getoption en0 router 2>/dev/null || netstat -rn | awk '$1=="default"{print $2; exit}')
    if [ -n "$LAN_GW" ]; then
      echo "🛣 Restoring guessed default route via $LAN_GW"
      ${ESC_CMD} route add default "$LAN_GW"
    else
      echo "⚠️ Could not determine LAN gateway for restoring default route."
    fi
  fi

  ${ESC_CMD} ifconfig "$INTERFACE" destroy
  ${ESC_CMD} rm -f "$STATE_DIR/${INTERFACE}.profile"
}

list_active() {
  printf "%-10s %-25s %-20s %-20s %-25s\n" "Interface" "Profile" "Handshake" "AllowedIPs" "Endpoint"
  echo "-------------------------------------------------------------------------------------------------------"

  for iface in $(ls "$STATE_DIR" | grep '\.profile$' | sed 's/\.profile$//'); do
    if ! ifconfig "$iface" >/dev/null 2>&1; then
      continue
    fi
    PROFILE_FILE=$(cat "$STATE_DIR/${iface}.profile" 2>/dev/null || echo "-")
    HANDSHAKE=$(${ESC_CMD} "$WG_CMD" show "$iface" latest-handshakes | awk '{print $2}')
    if [ -z "$HANDSHAKE" ] || { printf '%s' "$HANDSHAKE" | grep -Eq '^0+$'; }; then
      HANDSHAKE_STR="Never"
    else
      HANDSHAKE_STR="$(($(date +%s) - HANDSHAKE))s ago"
    fi
    ALLOWED=$(${ESC_CMD} "$WG_CMD" show "$iface" allowed-ips | awk '{print $2}' | paste -sd "," -)
    ENDPOINT=$(${ESC_CMD} "$WG_CMD" show "$iface" endpoints | awk '{print $2}')
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
    exit 0
    ;;
  *)
    usage
    ;;
esac
