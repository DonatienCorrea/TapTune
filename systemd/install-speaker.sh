#!/usr/bin/env bash
# Turns the Raspberry Pi into TapTune's own speaker:
#   - installs bluez-alsa so ALSA programs can play to a Bluetooth speaker;
#   - installs raspotify (librespot), a Spotify Connect receiver, and configures
#     it to play through the Bluetooth speaker and remember its Spotify login
#     so it is available right after every boot;
#   - installs taptune-bluetooth.service, which keeps the speaker connected.
# Run it from the repository after .env exists. Use --dry-run to preview.
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=1
      ;;
    *)
      echo "error: unknown argument '$arg'" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_DIR/.env"
BT_UNIT_SRC="$SCRIPT_DIR/taptune-bluetooth.service"
BT_UNIT_DST="/etc/systemd/system/taptune-bluetooth.service"
RASPOTIFY_CONF="/etc/raspotify/conf"
RASPOTIFY_INSTALLER="https://dtcooper.github.io/raspotify/install.sh"

if [ "$DRY_RUN" -eq 0 ] && [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE not found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

env_value() {
  local value=""
  if [ -f "$ENV_FILE" ]; then
    value="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)"
  fi
  value="${value%\"}"
  value="${value#\"}"
  printf '%s' "$value"
}

DEVICE_NAME="$(env_value SPOTIFY_DEVICE_NAME)"
DEVICE_NAME="${DEVICE_NAME:-TapTune}"
AUDIO_DEVICE="$(env_value AUDIO_OUTPUT_DEVICE)"
AUDIO_DEVICE="${AUDIO_DEVICE:-bluealsa}"

case "$DEVICE_NAME$AUDIO_DEVICE" in
  *[\"\\\$\`]*)
    echo "error: SPOTIFY_DEVICE_NAME and AUDIO_OUTPUT_DEVICE must not contain quotes, backslashes, \$ or backticks" >&2
    exit 1
    ;;
esac

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

# The block TapTune owns inside /etc/raspotify/conf. Rerunning replaces it.
RASPOTIFY_BLOCK="# >>> TapTune >>>
LIBRESPOT_NAME=\"$DEVICE_NAME\"
LIBRESPOT_BACKEND=alsa
LIBRESPOT_DEVICE=\"$AUDIO_DEVICE\"
# <<< TapTune <<<"

BT_UNIT=$(sed \
  -e "s#^ExecStart=.*#ExecStart=$REPO_DIR/systemd/taptune-bluetooth.sh#" \
  -e "s#^EnvironmentFile=.*#EnvironmentFile=$REPO_DIR/.env#" \
  "$BT_UNIT_SRC")

if [ "$DRY_RUN" -eq 1 ]; then
  echo "# Spotify Connect name: $DEVICE_NAME"
  echo "# Audio output: $AUDIO_DEVICE"
fi

run sudo apt-get update
run sudo apt-get install -y bluez bluez-alsa-utils libasound2-plugin-bluez alsa-utils curl

if [ "$DRY_RUN" -eq 1 ] || ! command -v librespot >/dev/null 2>&1; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "curl -sSL $RASPOTIFY_INSTALLER | sh"
  else
    curl -sSL "$RASPOTIFY_INSTALLER" | sh
  fi
fi

# Raspotify ships with credential caching disabled. Without the cache the Pi
# forgets the Spotify account at every reboot and TapTune cannot reach it.
run sudo sed -i \
  -e 's/^LIBRESPOT_DISABLE_CREDENTIAL_CACHE=/#LIBRESPOT_DISABLE_CREDENTIAL_CACHE=/' \
  -e '/^# >>> TapTune >>>$/,/^# <<< TapTune <<<$/d' \
  -e '/^LIBRESPOT_NAME=/s/^/#/' \
  -e '/^LIBRESPOT_BACKEND=/s/^/#/' \
  -e '/^LIBRESPOT_DEVICE=/s/^/#/' \
  "$RASPOTIFY_CONF"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "# append to $RASPOTIFY_CONF:"
  printf '%s\n' "$RASPOTIFY_BLOCK"
  echo "# install $BT_UNIT_DST:"
  printf '%s\n' "$BT_UNIT"
else
  printf '%s\n' "$RASPOTIFY_BLOCK" | sudo tee -a "$RASPOTIFY_CONF" > /dev/null
  chmod 755 "$SCRIPT_DIR/taptune-bluetooth.sh"
  printf '%s\n' "$BT_UNIT" | sudo tee "$BT_UNIT_DST" > /dev/null
  sudo chmod 644 "$BT_UNIT_DST"
fi

run sudo systemctl daemon-reload
run sudo systemctl enable --now bluetooth.service bluealsa.service
run sudo systemctl enable raspotify.service
run sudo systemctl restart raspotify.service
run sudo systemctl enable taptune-bluetooth.service
run sudo systemctl restart taptune-bluetooth.service

if [ "$DRY_RUN" -eq 0 ]; then
  echo "Installed the '$DEVICE_NAME' Spotify speaker."
  echo "Next: pair the Bluetooth speaker, then select '$DEVICE_NAME' once in the Spotify app (see docs/speaker-setup.md)."
fi
