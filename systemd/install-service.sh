#!/usr/bin/env bash
# Installs the TapTune systemd unit, rewriting WorkingDirectory, ExecStart,
# and EnvironmentFile so they match this checkout's actual path instead of
# the hardcoded /home/pi/TapTune assumption baked into the checked-in unit
# file. Run it from anywhere inside the repository.
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
UNIT_SRC="$SCRIPT_DIR/raspi-spotify-nfc.service"
UNIT_DST="/etc/systemd/system/raspi-spotify-nfc.service"

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

RENDERED=$(sed \
  -e "s#^WorkingDirectory=.*#WorkingDirectory=$REPO_DIR#" \
  -e "s#^ExecStart=.*#ExecStart=$REPO_DIR/.venv/bin/python -m app.main#" \
  -e "s#^EnvironmentFile=.*#EnvironmentFile=$REPO_DIR/.env#" \
  "$UNIT_SRC")

if [ "$DRY_RUN" -eq 1 ]; then
  printf '%s\n' "$RENDERED"
  exit 0
fi

printf '%s\n' "$RENDERED" | sudo tee "$UNIT_DST" > /dev/null
sudo chmod 644 "$UNIT_DST"
sudo systemctl daemon-reload
sudo systemctl enable --now raspi-spotify-nfc.service

echo "Installed and started raspi-spotify-nfc.service for checkout: $REPO_DIR"
