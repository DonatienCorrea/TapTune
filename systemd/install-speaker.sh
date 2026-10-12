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
source "$SCRIPT_DIR/install-common.sh"

if [ "$DRY_RUN" -eq 0 ] && [ ! -f "$ENV_FILE" ]; then
  echo "error: $ENV_FILE not found. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

DEVICE_NAME="$(env_value SPOTIFY_DEVICE_NAME)"
DEVICE_NAME="${DEVICE_NAME:-TapTune}"
MAC="$(env_value BLUETOOTH_SPEAKER_MAC)"
if [ "$DRY_RUN" -eq 1 ] && [ -z "$MAC" ]; then
  MAC="AA:BB:CC:DD:EE:FF"
fi
if ! printf '%s' "$MAC" | grep -Eq '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$'; then
  echo "error: set BLUETOOTH_SPEAKER_MAC in .env to the paired speaker's address" >&2
  exit 1
fi
VOLUME="$(initial_volume)"
AUDIO_DEVICE="$(env_value AUDIO_OUTPUT_DEVICE)"
AUDIO_DEVICE="${AUDIO_DEVICE:-bluealsa}"
if [ "$AUDIO_DEVICE" = "bluealsa" ]; then
  AUDIO_DEVICE="bluealsa:DEV=$MAC,PROFILE=a2dp"
fi

case "$DEVICE_NAME$AUDIO_DEVICE" in
  *[\"\\\$\`]*)
    echo "error: SPOTIFY_DEVICE_NAME and AUDIO_OUTPUT_DEVICE must not contain quotes, backslashes, \$ or backticks" >&2
    exit 1
    ;;
esac

# The block TapTune owns inside /etc/raspotify/conf. Rerunning replaces it.
RASPOTIFY_BLOCK="# >>> TapTune >>>
LIBRESPOT_NAME=\"$DEVICE_NAME\"
LIBRESPOT_BACKEND=alsa
LIBRESPOT_DEVICE=\"$AUDIO_DEVICE\"
LIBRESPOT_INITIAL_VOLUME=$VOLUME
# <<< TapTune <<<"

BT_UNIT="$(render_unit "$BT_UNIT_SRC" "$REPO_DIR/systemd/taptune-bluetooth.sh")"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "# Spotify Connect name: $DEVICE_NAME"
  echo "# Audio output: $AUDIO_DEVICE"
fi

run sudo apt-get update
run sudo apt-get install -y bluez bluez-alsa-utils libasound2-plugin-bluez alsa-utils curl

if [ "$DRY_RUN" -eq 1 ] || ! dpkg-query -W -f='${Status}' raspotify 2>/dev/null | grep -q '^install ok installed$'; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "curl -fsSL $RASPOTIFY_INSTALLER | sh"
  else
    curl -fsSL "$RASPOTIFY_INSTALLER" | sh
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
  -e '/^LIBRESPOT_INITIAL_VOLUME=/s/^/#/' \
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
run bluetoothctl trust "$MAC"
run sudo systemctl enable taptune-bluetooth.service
run sudo systemctl restart taptune-bluetooth.service
run sudo systemctl enable raspotify.service
run sudo systemctl restart raspotify.service

if [ "$DRY_RUN" -eq 0 ]; then
  echo "Installed the '$DEVICE_NAME' Spotify speaker."
  echo "Next: select '$DEVICE_NAME' once in the Spotify app, then restart TapTune (see docs/speaker-setup.md)."
fi
