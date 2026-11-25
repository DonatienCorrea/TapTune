#!/usr/bin/env bash
# Installs and starts the TapTune app as a system service, with this checkout's
# paths and this user's PipeWire as its audio output, plus the `taptune`
# command and persistent logs. Run as the normal user after install-go-librespot.sh.
# --dry-run prints the rendered unit without changing anything.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_DST="/etc/systemd/system/raspi-spotify-nfc.service"
source "$SCRIPT_DIR/install-common.sh"
parse_dry_run "$@"
require_normal_user
require_prepared

AUDIO_USER="$(id -un)"
printf '%s' "$AUDIO_USER" | grep -Eq '^[a-z_][a-z0-9_-]{0,31}$' ||
  die "user name '$AUDIO_USER' cannot be used as the audio user"

WIFI_SETUP=1
if [ "$DRY_RUN" -eq 0 ] && ! { command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager.service; }; then
  WIFI_SETUP=0
  echo "warning: NetworkManager is not running; the Wi-Fi setup hotspot will not be enabled." >&2
fi

# Escapes a path for a unit file; "exec" also quotes it for Exec*= lines.
unit_path() {
  local value="$1"
  value="${value//\\/\\\\}"
  value="${value//\"/\\\"}"
  value="${value// /\\x20}"
  value="${value//%/%%}"
  if [ "${2:-}" = "exec" ]; then
    value="${value//\$/\$\$}"
    printf '"%s"' "$value"
  else
    printf '%s' "$value"
  fi
}

PYTHON_EXEC="$(unit_path "$REPO_DIR/.venv/bin/python" exec)"
render_unit() {
  local line
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      WorkingDirectory=*) line="WorkingDirectory=$(unit_path "$REPO_DIR")" ;;
      EnvironmentFile=*) line="EnvironmentFile=$(unit_path "$REPO_DIR/.env")" ;;
      ExecStart=*) line="ExecStart=$PYTHON_EXEC -m app.main" ;;
      ExecStopPost=*) [ "$WIFI_SETUP" -eq 1 ] || continue; line="ExecStopPost=-$PYTHON_EXEC -m app.wifi_setup cleanup" ;;
      Environment=TAPTUNE_WIFI_SETUP=*) [ "$WIFI_SETUP" -eq 1 ] || continue ;;
      Environment=DESKTOP_AUDIO_USER=*) line="Environment=DESKTOP_AUDIO_USER=$AUDIO_USER" ;;
    esac
    printf '%s\n' "$line"
  done < "$SCRIPT_DIR/raspi-spotify-nfc.service"
}
RENDERED="$(render_unit)"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "# write $UNIT_DST:"
  printf '%s\n' "$RENDERED"
  echo "# install dnsmasq-base and nftables, then create the private TapTune-Setup Wi-Fi profile if missing"
  echo "# install journald-taptune.conf, link /usr/local/bin/taptune, enable and restart the service"
  exit 0
fi

SHOW_SETUP_WIFI=0
if [ "$WIFI_SETUP" -eq 1 ]; then
  [ -f /etc/NetworkManager/system-connections/taptune-setup.nmconnection ] || SHOW_SETUP_WIFI=1
  apt_install dnsmasq-base nftables
  (cd "$REPO_DIR" && sudo "$REPO_DIR/.venv/bin/python" -m app.wifi_setup provision)
fi

printf '%s\n' "$RENDERED" | sudo tee "$UNIT_DST" > /dev/null
sudo chmod 644 "$UNIT_DST"

# Keep logs across reboots so a failed boot can be inspected afterwards.
JOURNALD_DST="/etc/systemd/journald.conf.d/taptune.conf"
if ! cmp -s "$SCRIPT_DIR/journald-taptune.conf" "$JOURNALD_DST"; then
  sudo mkdir -p "$(dirname "$JOURNALD_DST")"
  sudo install -m 644 "$SCRIPT_DIR/journald-taptune.conf" "$JOURNALD_DST"
  sudo systemctl restart systemd-journald.service
fi

sudo ln -sfn "$REPO_DIR/taptune" /usr/local/bin/taptune
sudo systemctl daemon-reload
sudo systemctl enable raspi-spotify-nfc.service
sudo systemctl restart raspi-spotify-nfc.service

echo "TapTune service started from $REPO_DIR."
if [ "$SHOW_SETUP_WIFI" -eq 1 ]; then
  printf '\nThe TapTune-Setup Wi-Fi is ready. Note its password before moving the Pi:\n'
  "$REPO_DIR/taptune" setup-wifi || echo "Run 'taptune setup-wifi' to see it."
fi
