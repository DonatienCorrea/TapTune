#!/usr/bin/env bash
# Run as the Spotifyd user, not with sudo. Keeps that user's audio stack alive at boot.
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *)
      echo "error: unknown argument '$arg'" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
if [ "$CONFIG_DIR" != "$HOME/.config" ]; then
  echo "error: this installer requires the standard ~/.config location for its user unit" >&2
  exit 1
fi

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '%q ' "$@"
    printf '\n'
  else
    "$@"
  fi
}

if [ "$DRY_RUN" -eq 0 ]; then
  if [ "$(id -u)" -eq 0 ]; then
    echo "error: run as the user who authenticated Spotifyd, without sudo" >&2
    exit 1
  fi
  for command in wireplumber pactl bluetoothctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
      echo "error: $command missing; install wireplumber, pulseaudio-utils and bluez first" >&2
      exit 1
    fi
  done
  if [ ! -x /usr/local/bin/spotifyd ] || [ ! -f "$CONFIG_DIR/spotifyd/spotifyd.conf" ]; then
    echo "error: install, configure and authenticate Spotifyd first (docs/speaker-setup-desktop.md)" >&2
    exit 1
  fi
  if [ "$(grep -cE '^[[:space:]]*\[global\][[:space:]]*$' "$CONFIG_DIR/spotifyd/spotifyd.conf")" != "1" ]; then
    echo "error: spotifyd.conf must contain one [global] section" >&2
    exit 1
  fi
fi

MAC=""
if [ -f "$REPO_DIR/.env" ]; then
  MAC="$(grep -E '^BLUETOOTH_SPEAKER_MAC=' "$REPO_DIR/.env" | tail -n 1 | cut -d= -f2- || true)"
  MAC="${MAC%\"}"
  MAC="${MAC#\"}"
  MAC="${MAC%\'}"
  MAC="${MAC#\'}"
fi
if [ "$DRY_RUN" -eq 1 ] && [ -z "$MAC" ]; then
  MAC="AA:BB:CC:DD:EE:FF"
fi
if ! printf '%s' "$MAC" | grep -Eq '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$'; then
  echo "error: set BLUETOOTH_SPEAKER_MAC in .env to the paired speaker's address" >&2
  exit 1
fi

VERSION="0.5"
if command -v wireplumber >/dev/null 2>&1; then
  VERSION="$(wireplumber --version)"
fi
case "$VERSION" in
  *0.4*)
    WP_FILE="$CONFIG_DIR/wireplumber/bluetooth.lua.d/90-taptune-headless.lua"
    WP_CONFIG='bluez_monitor.properties["with-logind"] = false'
    ;;
  *0.5*)
    WP_FILE="$CONFIG_DIR/wireplumber/wireplumber.conf.d/90-taptune-headless.conf"
    WP_CONFIG='wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}'
    ;;
  *)
    echo "error: unsupported WirePlumber version: $VERSION (expected 0.4 or 0.5)" >&2
    exit 1
    ;;
esac

run mkdir -p "$(dirname "$WP_FILE")" "$CONFIG_DIR/systemd/user" "$CONFIG_DIR/taptune" "$HOME/.local/lib/taptune"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "# write $WP_FILE:"
  printf '%s\n' "$WP_CONFIG"
  echo "# write $CONFIG_DIR/taptune/bluetooth.env:"
  printf 'BLUETOOTH_SPEAKER_MAC=%s\n' "$MAC"
else
  printf '%s\n' "$WP_CONFIG" > "$WP_FILE"
  printf 'BLUETOOTH_SPEAKER_MAC=%s\n' "$MAC" > "$CONFIG_DIR/taptune/bluetooth.env"
fi
run install -m 755 "$SCRIPT_DIR/taptune-bluetooth.sh" "$HOME/.local/lib/taptune/taptune-bluetooth.sh"
run install -m 644 "$SCRIPT_DIR/taptune-bluetooth.user.service" "$CONFIG_DIR/systemd/user/taptune-bluetooth.service"
run install -m 644 "$SCRIPT_DIR/taptune-spotifyd.user.service" "$CONFIG_DIR/systemd/user/taptune-spotifyd.service"
run sed -i \
  -e '/^[[:space:]]*initial_volume[[:space:]]*=/d' \
  -e '/^[[:space:]]*\[global\][[:space:]]*$/a initial_volume = 30' \
  "$CONFIG_DIR/spotifyd/spotifyd.conf"
run sudo loginctl enable-linger "$(id -un)"
run sudo systemctl enable --now bluetooth.service
run bluetoothctl trust "$MAC"
run systemctl --user daemon-reload
run systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
run systemctl --user restart wireplumber.service
run systemctl --user enable taptune-bluetooth.service taptune-spotifyd.service
run systemctl --user restart taptune-bluetooth.service taptune-spotifyd.service

echo "Desktop speaker configured for boot without login. Keep this Pi dedicated to this audio user."
echo "Reboot, then check playback before logging in (see docs/speaker-setup-desktop.md)."
