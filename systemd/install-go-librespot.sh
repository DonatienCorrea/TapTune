#!/usr/bin/env bash
# Turns the Pi into TapTune's Spotify speaker with go-librespot
# (https://github.com/devgianlu/go-librespot), played through this user's
# PipeWire to the Bluetooth speaker. Spotify sign-in: choose the receiver once
# in the Spotify app; the sign-in is kept across reboots. TapTune drives it
# through its local API (localhost only).
# Run as the normal user (not with sudo) after ./install.sh. --dry-run previews.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/install-common.sh"
parse_dry_run "$@"
GLR_VERSION="0.10.7"
GLR_BIN="/usr/local/bin/go-librespot"
GLR_DIR="$CONFIG_DIR/go-librespot"
GLR_STAMP="/usr/local/share/taptune/go-librespot.version"

# The user unit reads %h/.config, so a custom XDG_CONFIG_HOME would be ignored.
[ "$CONFIG_DIR" = "$HOME/.config" ] || die "this installer requires the standard ~/.config location"
require_normal_user
require_prepared

DEVICE_NAME="$(env_value SPOTIFY_DEVICE_NAME)"
DEVICE_NAME="${DEVICE_NAME:-TapTune}"
case "$DEVICE_NAME" in
  *[\"\\\$\`]*) die "SPOTIFY_DEVICE_NAME must not contain quotes, backslashes, \$ or backticks" ;;
esac
# Only needed to trust the speaker; the setup page pairs one later if empty.
MAC="$(env_value BLUETOOTH_SPEAKER_MAC)"
if [ -n "$MAC" ] && ! is_mac "$MAC"; then
  die "BLUETOOTH_SPEAKER_MAC in .env is not a Bluetooth address (expected AA:BB:CC:DD:EE:FF)"
fi
[ -n "$MAC" ] || echo "warning: no Bluetooth speaker yet; pair one from the TapTune setup page (/setup)." >&2
VOLUME="$(env_value SPOTIFY_INITIAL_VOLUME)"
VOLUME="${VOLUME:-10}"
printf '%s' "$VOLUME" | grep -Eq '^(100|[1-9]?[0-9])$' ||
  die "SPOTIFY_INITIAL_VOLUME must be an integer from 0 to 100"

case "$(uname -m)" in
  aarch64|arm64) ASSET=arm64; SHA256=1959a87033c5d8ff012e6f8acd1ca1994234104455d9796b688c8d2193e7f28b ;;
  armv6l|armv7l) ASSET=armv6_rpi; SHA256=b70abd694a897f4d8ffd3e9c1c44ff238fbf62c11b6b1a3215a0cb64bfcc2dfe ;;
  x86_64) ASSET=x86_64; SHA256=0712061edc269e935492c109c215c83d2998a240775789cb77d2a803f05fd816 ;;
  *) die "no go-librespot $GLR_VERSION build for architecture $(uname -m)" ;;
esac
GLR_URL="https://github.com/devgianlu/go-librespot/releases/download/v$GLR_VERSION/go-librespot_linux_$ASSET.tar.gz"

GLR_CONFIG="# Managed by TapTune (systemd/install-go-librespot.sh); rerunning it rewrites this file.
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
  port: 3678"

[ "$DRY_RUN" -eq 0 ] || echo "# Spotify Connect name: $DEVICE_NAME; go-librespot $GLR_VERSION ($ASSET) -> PipeWire -> ${MAC:-no speaker yet}"

retry sudo apt-get update
apt_install pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth pulseaudio-utils \
  bluez avahi-daemon libasound2-plugins curl

if [ "$DRY_RUN" -eq 1 ]; then
  echo "# unless $GLR_STAMP already says '$GLR_VERSION $ASSET': download $GLR_URL, check sha256 $SHA256"
elif [ "$(cat "$GLR_STAMP" 2>/dev/null || true)" != "$GLR_VERSION $ASSET" ] || [ ! -x "$GLR_BIN" ]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  retry curl -fsSL -o "$tmp/glr.tar.gz" "$GLR_URL"
  printf '%s  %s\n' "$SHA256" "$tmp/glr.tar.gz" | sha256sum -c --status ||
    die "go-librespot download does not match its pinned checksum"
  tar -xzf "$tmp/glr.tar.gz" -C "$tmp" go-librespot
  run sudo install -m 755 "$tmp/go-librespot" "$GLR_BIN"
  run sudo mkdir -p "$(dirname "$GLR_STAMP")"
  printf '%s %s\n' "$GLR_VERSION" "$ASSET" | sudo tee "$GLR_STAMP" >/dev/null
fi

# Lets WirePlumber use Bluetooth without a logged-in seat (headless Pi).
# Checked after apt-get, which installs WirePlumber on a fresh Pi.
WP_VERSION="0.5"
if command -v wireplumber >/dev/null 2>&1; then
  WP_VERSION="$(wireplumber --version)"
fi
case "$WP_VERSION" in
  *0.4*)
    WP_FILE="$CONFIG_DIR/wireplumber/bluetooth.lua.d/90-taptune-headless.lua"
    WP_CONFIG='bluez_monitor.properties["with-logind"] = false'
    ;;
  *)
    WP_FILE="$CONFIG_DIR/wireplumber/wireplumber.conf.d/90-taptune-headless.conf"
    WP_CONFIG='wireplumber.profiles = {
  main = {
    monitor.bluez.seat-monitoring = disabled
  }
}'
    ;;
esac

run mkdir -p "$(dirname "$WP_FILE")" "$CONFIG_DIR/systemd/user" "$GLR_DIR"
if [ "$DRY_RUN" -eq 1 ]; then
  printf '# write %s:\n%s\n# write %s:\n%s\n' "$WP_FILE" "$WP_CONFIG" "$GLR_DIR/config.yml" "$GLR_CONFIG"
else
  printf '%s\n' "$WP_CONFIG" > "$WP_FILE"
  (umask 077; printf '%s\n' "$GLR_CONFIG" > "$GLR_DIR/config.yml")
fi
run install -m 644 "$SCRIPT_DIR/taptune-go-librespot.user.service" "$CONFIG_DIR/systemd/user/taptune-go-librespot.service"
remove_legacy_units

# Keep this user's PipeWire and go-librespot running at boot without a login.
run sudo loginctl enable-linger "$(id -un)"
run sudo systemctl enable --now bluetooth.service avahi-daemon.service
[ -z "$MAC" ] || run bluetoothctl trust "$MAC"
run systemctl --user daemon-reload
run systemctl --user enable --now pipewire.socket pipewire-pulse.socket wireplumber.service
run systemctl --user restart wireplumber.service
run systemctl --user enable taptune-go-librespot.service
run systemctl --user restart taptune-go-librespot.service

[ "$DRY_RUN" -eq 1 ] || echo "Spotify speaker '$DEVICE_NAME' is ready (go-librespot $GLR_VERSION)."
