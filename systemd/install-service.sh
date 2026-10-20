#!/usr/bin/env bash
# Installs the TapTune systemd unit, rewriting WorkingDirectory, ExecStart,
# and EnvironmentFile so they match this checkout's actual path instead of
# the hardcoded /home/pi/TapTune assumption baked into the checked-in unit
# file. Run it from anywhere inside the repository, as the normal user.
#   --lite      also start after Raspotify and BlueALSA (install-speaker.sh)
#   --desktop   play through this user's PipeWire (install-desktop-speaker.sh)
#   --app-only  (default) no local speaker services are pulled in
set -euo pipefail

DRY_RUN=0
MODE=app-only
for arg in "$@"; do
  case "$arg" in
    --dry-run)
      DRY_RUN=1
      ;;
    --lite|--desktop|--app-only)
      MODE="${arg#--}"
      ;;
    *)
      echo "error: unknown argument '$arg'" >&2
      exit 1
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
UNIT_SRC="$SCRIPT_DIR/raspi-spotify-nfc.service"
UNIT_DST="/etc/systemd/system/raspi-spotify-nfc.service"
source "$SCRIPT_DIR/install-common.sh"

if [ ! -f "$UNIT_SRC" ]; then
  echo "error: $UNIT_SRC not found" >&2
  exit 1
fi

if [ "$DRY_RUN" -eq 0 ]; then
  if [ ! -x "$REPO_DIR/.venv/bin/python" ]; then
    echo "error: $REPO_DIR/.venv/bin/python not found. Create the virtual environment first (python3 -m venv .venv)." >&2
    exit 1
  fi

  if [ ! -f "$REPO_DIR/.env" ]; then
    echo "error: $REPO_DIR/.env not found. Copy .env.example to .env and fill it in first." >&2
    exit 1
  fi
fi

RENDERED="$(render_unit "$UNIT_SRC" "$REPO_DIR/.venv/bin/python" " -m app.main")"

case "$MODE" in
  lite)
    RENDERED="$(printf '%s\n' "$RENDERED" | sed \
      -e 's/^Wants=.*/Wants=network-online.target raspotify.service/' \
      -e 's/^After=.*/After=network-online.target bluetooth.service bluealsa.service raspotify.service/')"
    ;;
  desktop)
    # The system app reaches this user's PipeWire with runuser; the user keeps
    # running at boot without login thanks to install-desktop-speaker.sh (linger).
    AUDIO_USER="$(id -un)"
    if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -eq 0 ]; then
      echo "error: run 'install-service.sh --desktop' as the Spotifyd audio user, without sudo" >&2
      exit 1
    fi
    if ! printf '%s' "$AUDIO_USER" | grep -Eq '^[a-z_][a-z0-9_-]{0,31}$'; then
      echo "error: user name '$AUDIO_USER' cannot be used as the Desktop audio user" >&2
      exit 1
    fi
    RENDERED="${RENDERED/Environment=PYTHONUNBUFFERED=1/Environment=PYTHONUNBUFFERED=1$'\n'Environment=DESKTOP_AUDIO_USER=$AUDIO_USER}"
    ;;
esac

if [ "$DRY_RUN" -eq 1 ]; then
  echo "# $MODE setup: $UNIT_DST"
  printf '%s\n' "$RENDERED"
  remove_legacy_system_units
  exit 0
fi

remove_legacy_system_units

printf '%s\n' "$RENDERED" | sudo tee "$UNIT_DST" > /dev/null
sudo chmod 644 "$UNIT_DST"

# Keep logs across reboots so an unreliable boot can be inspected afterwards.
JOURNALD_SRC="$SCRIPT_DIR/journald-taptune.conf"
JOURNALD_DST="/etc/systemd/journald.conf.d/taptune.conf"
if ! cmp -s "$JOURNALD_SRC" "$JOURNALD_DST"; then
  sudo mkdir -p "$(dirname "$JOURNALD_DST")"
  sudo install -m 644 "$JOURNALD_SRC" "$JOURNALD_DST"
  sudo systemctl restart systemd-journald.service
fi

# Make `taptune update|logs|status|restart` available from anywhere.
sudo ln -sfn "$REPO_DIR/taptune" /usr/local/bin/taptune

sudo systemctl daemon-reload
sudo systemctl enable raspi-spotify-nfc.service
sudo systemctl restart raspi-spotify-nfc.service

echo "Installed and started raspi-spotify-nfc.service ($MODE setup) for checkout: $REPO_DIR"
echo "Use 'taptune status', 'taptune logs -f' and 'taptune update' from now on."
