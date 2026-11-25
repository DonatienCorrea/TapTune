#!/usr/bin/env bash
# Turns the Raspberry Pi (OS Lite or Desktop) into TapTune's Spotify speaker with
# go-librespot (https://github.com/devgianlu/go-librespot):
#   - go-librespot -> this user's PipeWire -> the Bluetooth speaker, on both editions;
#   - Spotify sign-in by choosing the receiver once in the Spotify app (zeroconf);
#     the sign-in is kept (persist_credentials) so tags play after a reboot with no phone;
#   - TapTune drives it through its local API (localhost only): no Spotify developer app.
# Raspotify/Spotifyd and BlueALSA are stopped (not removed): set SPOTIFY_RECEIVER=legacy
# in .env and rerun the edition's installer to go back.
# Run as the normal user (not with sudo) after .env exists. Use --dry-run to preview.
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
GLR_VERSION="0.10.7"
GLR_BIN="/usr/local/bin/go-librespot"
GLR_DIR="$CONFIG_DIR/go-librespot"
GLR_PORT=3678

if [ "$CONFIG_DIR" != "$HOME/.config" ]; then
  echo "error: this installer requires the standard ~/.config location for its user unit" >&2
  exit 1
fi
if [ "$DRY_RUN" -eq 0 ]; then
  if [ "$(id -u)" -eq 0 ]; then
    echo "error: run as the user who will play the audio, without sudo" >&2
    exit 1
  fi
  if [ ! -f "$REPO_DIR/.env" ]; then
    echo "error: $REPO_DIR/.env not found. Run ./install.sh --lite or --desktop first." >&2
    exit 1
  fi
fi

DEVICE_NAME="$(env_value SPOTIFY_DEVICE_NAME)"
DEVICE_NAME="${DEVICE_NAME:-TapTune}"
case "$DEVICE_NAME" in
  *[\"\\\$\`]*)
    echo "error: SPOTIFY_DEVICE_NAME must not contain quotes, backslashes, \$ or backticks" >&2
    exit 1
    ;;
esac
# go-librespot plays through PipeWire's default output, so the speaker address
# is only needed to trust it. After a reset (or before pairing), the setup page
# pairs and trusts the speaker later.
MAC="$(env_value BLUETOOTH_SPEAKER_MAC)"
if [ -n "$MAC" ] && ! printf '%s' "$MAC" | grep -Eq '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$'; then
  echo "error: BLUETOOTH_SPEAKER_MAC in .env is not a Bluetooth address (expected AA:BB:CC:DD:EE:FF)" >&2
  exit 1
fi
if [ -z "$MAC" ]; then
  echo "warning: no Bluetooth speaker yet; pair one from the TapTune setup page (/setup)." >&2
fi
VOLUME="$(initial_volume)"

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) ASSET=arm64; SHA256=1959a87033c5d8ff012e6f8acd1ca1994234104455d9796b688c8d2193e7f28b ;;
  armv6l|armv7l) ASSET=armv6_rpi; SHA256=b70abd694a897f4d8ffd3e9c1c44ff238fbf62c11b6b1a3215a0cb64bfcc2dfe ;;
  x86_64) ASSET=x86_64; SHA256=0712061edc269e935492c109c215c83d2998a240775789cb77d2a803f05fd816 ;;
  *)
    echo "error: no go-librespot $GLR_VERSION build for architecture $ARCH" >&2
    exit 1
    ;;
esac
GLR_URL="https://github.com/devgianlu/go-librespot/releases/download/v$GLR_VERSION/go-librespot_linux_$ASSET.tar.gz"

GLR_CONFIG="# Managed by TapTune (systemd/install-go-librespot.sh); rerunning it rewrites this file.
# The Spotify sign-in is kept separately in credentials.json.
log_level: info
device_name: \"$DEVICE_NAME\"
device_type: speaker
# The native PulseAudio backend ignores initial_volume when it opens a stream.
# Use software volume via ALSA's pulse PCM, still routed through PipeWire.
audio_backend: alsa
audio_device: pulse
bitrate: 320
volume_steps: 100
initial_volume: $VOLUME
ignore_last_volume: true
zeroconf_enabled: true
zeroconf_backend: avahi
credentials:
  type: zeroconf
  zeroconf:
    persist_credentials: true
server:
  enabled: true
  address: 127.0.0.1
  port: $GLR_PORT"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "# Spotify Connect name: $DEVICE_NAME"
  echo "# go-librespot $GLR_VERSION ($ASSET) -> PipeWire -> ${MAC:-no speaker yet}"
fi

run sudo apt-get update
run sudo apt-get install -y pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth \
  pulseaudio-utils bluez avahi-daemon libasound2 libasound2-plugins curl

GLR_STAMP="/usr/local/share/taptune/go-librespot.version"
if [ "$DRY_RUN" -eq 1 ] || [ "$(cat "$GLR_STAMP" 2>/dev/null || true)" != "$GLR_VERSION $ASSET" ] \
  || [ ! -x "$GLR_BIN" ]; then
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "# unless $GLR_STAMP already says '$GLR_VERSION $ASSET':"
    echo "# download $GLR_URL, check sha256 $SHA256, then:"
    run sudo install -m 755 go-librespot "$GLR_BIN"
  else
    tmp="$(mktemp -d)"
    trap 'rm -rf "$tmp"' EXIT
    curl -fsSL -o "$tmp/glr.tar.gz" "$GLR_URL"
    if ! printf '%s  %s\n' "$SHA256" "$tmp/glr.tar.gz" | sha256sum -c --status; then
      echo "error: go-librespot download does not match its pinned checksum" >&2
      exit 1
    fi
    tar -xzf "$tmp/glr.tar.gz" -C "$tmp" go-librespot
    run sudo install -m 755 "$tmp/go-librespot" "$GLR_BIN"
    run sudo mkdir -p "$(dirname "$GLR_STAMP")"
    printf '%s %s\n' "$GLR_VERSION" "$ASSET" | sudo tee "$GLR_STAMP" >/dev/null
  fi
fi

WP_VERSION="0.5"
if [ "$DRY_RUN" -eq 0 ]; then
  WP_VERSION="$(wireplumber --version)"
fi
case "$WP_VERSION" in
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
    echo "error: unsupported WirePlumber version: $WP_VERSION (expected 0.4 or 0.5)" >&2
    exit 1
    ;;
esac

run mkdir -p "$(dirname "$WP_FILE")" "$CONFIG_DIR/systemd/user" "$GLR_DIR"
if [ "$DRY_RUN" -eq 1 ]; then
  echo "# write $WP_FILE:"
  printf '%s\n' "$WP_CONFIG"
  echo "# write $GLR_DIR/config.yml:"
  printf '%s\n' "$GLR_CONFIG"
else
  printf '%s\n' "$WP_CONFIG" > "$WP_FILE"
  (umask 077; printf '%s\n' "$GLR_CONFIG" > "$GLR_DIR/config.yml")
fi
run install -m 644 "$SCRIPT_DIR/taptune-go-librespot.user.service" "$CONFIG_DIR/systemd/user/taptune-go-librespot.service"

# Only one "TapTune" receiver may advertise itself, and BlueALSA would fight
# PipeWire for the speaker's A2DP link.
disable_user_unit taptune-spotifyd.service "go-librespot replaces Spotifyd" \
  "$CONFIG_DIR/systemd/user/taptune-spotifyd.service"
disable_user_unit spotifyd.service "go-librespot replaces Spotifyd"
remove_legacy_user_units
disable_system_unit spotifyd.service "go-librespot replaces Spotifyd"
disable_system_unit raspotify.service "go-librespot replaces Raspotify"
disable_system_unit bluealsa-aplay.service "PipeWire plays to the speaker"
disable_system_unit bluealsa.service "PipeWire handles Bluetooth audio"
if [ "$DRY_RUN" -eq 1 ] || [ -f /etc/systemd/system/raspotify.service.d/taptune.conf ]; then
  run sudo rm -f /etc/systemd/system/raspotify.service.d/taptune.conf
  run sudo systemctl daemon-reload
fi
remove_legacy_system_units
exclude_desktop_greeter_audio

# Keep this user's PipeWire and go-librespot running at boot without a login.
run sudo loginctl enable-linger "$(id -un)"
run sudo systemctl enable --now bluetooth.service avahi-daemon.service
if [ -n "$MAC" ]; then
  run bluetoothctl trust "$MAC"
fi
run systemctl --user daemon-reload
run systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
run systemctl --user restart wireplumber.service
run systemctl --user enable taptune-go-librespot.service
run systemctl --user restart taptune-go-librespot.service

if [ "$DRY_RUN" -eq 0 ]; then
  echo "Installed the '$DEVICE_NAME' Spotify speaker (go-librespot $GLR_VERSION)."
  echo "Next: install TapTune with 'systemd/install-service.sh --lite' (or --desktop) as this user,"
  echo "then open Spotify on a phone on the same Wi-Fi, tap Devices and choose '$DEVICE_NAME' once."
fi
