#!/opt/homebrew/bin/bash
set -eu

OPERATION="$1"
shift
CONF_PATH="$*"


# Auto down interface if it's already up
if ifconfig | grep -q "wg0: flags"; then
  echo "[wrapper] wg0 already up — bringing it down"
  /opt/homebrew/bin/wg-quick down wg0 || true
fi

if [ "$(realpath "$CONF_PATH")" != "/usr/local/etc/wireguard/wg0.conf" ]; then
  cp "$CONF_PATH" "/usr/local/etc/wireguard/wg0.conf"
fi

export BASH="/opt/homebrew/bin/bash"
exec /opt/homebrew/bin/bash /opt/homebrew/bin/wg-quick "$OPERATION" wg0