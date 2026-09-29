#!/usr/bin/env bash
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
PYTHON="$REPO_DIR/.venv/bin/python"

if [ "$DRY_RUN" -eq 0 ] && [ ! -x "$PYTHON" ]; then
  echo "error: $PYTHON not found. Create the virtual environment first (python3 -m venv .venv)." >&2
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

# mfrc522 declares the Pi 5-incompatible RPi.GPIO package as a dependency.
# Install it without dependencies after replacing that backend with rpi-lgpio.
run "$PYTHON" -m pip uninstall -y RPi.GPIO rpi-lgpio
run "$PYTHON" -m pip install -r "$REPO_DIR/requirements.txt"
run "$PYTHON" -m pip install -r "$REPO_DIR/requirements-pi.txt"
run "$PYTHON" -m pip install --no-deps mfrc522==0.0.7
