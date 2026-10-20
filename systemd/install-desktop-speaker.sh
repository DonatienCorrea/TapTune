#!/usr/bin/env bash
# Run as the Spotifyd user, not with sudo. Keeps that user's audio stack alive at
# boot and runs Spotifyd as its only TapTune user service. The TapTune app
# (install-service.sh --desktop) connects the speaker, routes this user's
# PipeWire output to it and plays the ready sound: once at boot, then only
# when a tag starts or resumes music. Lite's Raspotify/BlueALSA are stopped.
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
source "$SCRIPT_DIR/install-common.sh"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
if [ "$CONFIG_DIR" != "$HOME/.config" ]; then
  echo "error: this installer requires the standard ~/.config location for its user unit" >&2
  exit 1
fi

if [ "$DRY_RUN" -eq 0 ]; then
  if [ "$(id -u)" -eq 0 ]; then
    echo "error: run as the user who authenticated Spotifyd, without sudo" >&2
    exit 1
  fi
  for command in wireplumber pactl pacat bluetoothctl; do
    if ! command -v "$command" >/dev/null 2>&1; then
      echo "error: $command missing; install wireplumber, pulseaudio-utils and bluez first" >&2
      exit 1
    fi
  done
  if [ ! -x "$REPO_DIR/.venv/bin/python" ] || [ ! -f "$REPO_DIR/.env" ]; then
    echo "error: prepare TapTune's .venv and .env first (docs/raspberry-pi-service.md)" >&2
    exit 1
  fi
  if [ ! -x /usr/local/bin/spotifyd ] || [ ! -f "$CONFIG_DIR/spotifyd/spotifyd.conf" ]; then
    echo "error: install, configure and authenticate Spotifyd first (docs/speaker-setup-desktop.md)" >&2
    exit 1
  fi
  if [ "$(grep -cE '^[[:space:]]*\[global\][[:space:]]*$' "$CONFIG_DIR/spotifyd/spotifyd.conf")" != "1" ] ||
      [ "$(grep -cE '^[[:space:]]*\[' "$CONFIG_DIR/spotifyd/spotifyd.conf")" != "1" ]; then
    echo "error: spotifyd.conf must contain only one [global] section (see docs/speaker-setup-desktop.md)" >&2
    exit 1
  fi
  if ! grep -Eq "^[[:space:]]*backend[[:space:]]*=[[:space:]]*[\"']pulseaudio[\"'][[:space:]]*(#.*)?$" "$CONFIG_DIR/spotifyd/spotifyd.conf"; then
    echo 'error: set backend = "pulseaudio" in spotifyd.conf for Desktop audio' >&2
    exit 1
  fi
fi

MAC="$(env_value BLUETOOTH_SPEAKER_MAC)"
if [ "$DRY_RUN" -eq 1 ] && [ -z "$MAC" ]; then
  MAC="AA:BB:CC:DD:EE:FF"
fi
VOLUME="$(initial_volume)"
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

run mkdir -p "$(dirname "$WP_FILE")" "$CONFIG_DIR/systemd/user"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "# write $WP_FILE:"
  printf '%s\n' "$WP_CONFIG"
else
  printf '%s\n' "$WP_CONFIG" > "$WP_FILE"
fi
run install -m 644 "$SCRIPT_DIR/taptune-spotifyd.user.service" "$CONFIG_DIR/systemd/user/taptune-spotifyd.service"
remove_legacy_user_units
run sed -i \
  -e '/^[[:space:]]*initial_volume[[:space:]]*=/d' \
  -e "/^[[:space:]]*\\[global\\][[:space:]]*$/a initial_volume = $VOLUME" \
  "$CONFIG_DIR/spotifyd/spotifyd.conf"
run sudo loginctl enable-linger "$(id -un)"
# BlueALSA and PipeWire both claim the speaker's A2DP link, and a Raspotify
# receiver with the same name makes a second "TapTune" in Spotify.
disable_system_unit raspotify.service "Desktop uses Spotifyd, not Raspotify"
disable_system_unit bluealsa.service "PipeWire handles Bluetooth audio on Desktop"
if [ "$DRY_RUN" -eq 1 ] || [ -f /etc/systemd/system/raspotify.service.d/taptune.conf ]; then
  run sudo rm -f /etc/systemd/system/raspotify.service.d/taptune.conf
  run sudo systemctl daemon-reload
fi
remove_legacy_system_units
run sudo systemctl enable --now bluetooth.service
run bluetoothctl trust "$MAC"
run systemctl --user daemon-reload
run systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
run systemctl --user restart wireplumber.service
run systemctl --user enable taptune-spotifyd.service
run systemctl --user restart taptune-spotifyd.service

echo "Desktop speaker configured for boot without login. Keep this Pi dedicated to this audio user."
echo "Match SPOTIFY_DEVICE_NAME to Spotifyd's device_name and install TapTune with 'systemd/install-service.sh --desktop' as this user."
echo "TapTune then plays the ready sound (READY_SOUND_ENABLED) through this user's Bluetooth output."
echo "Reboot, then check playback before logging in (see docs/speaker-setup-desktop.md)."
