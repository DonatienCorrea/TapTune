#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF_USAGE'
Usage: ./install.sh [--configure] [--dry-run]

Step 1, ./install.sh: installs TapTune's Python packages and creates a private
  .env settings file (an existing .env is kept). Starts nothing.
Step 2, ./install.sh --configure: after editing .env, installs the Spotify
  speaker (go-librespot) and starts TapTune. Rerun it any time to repair.
  --dry-run   Show what would be done without changing anything.

Run as your normal user, not with sudo. Needs Raspberry Pi OS Lite, Python 3.10+
and internet access. Guide: docs/raspberry-pi-service.md
EOF_USAGE
}

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$REPO_DIR/systemd"
PYTHON="$REPO_DIR/.venv/bin/python"
source "$SCRIPT_DIR/install-common.sh"

CONFIGURE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --configure) CONFIGURE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument '$arg'; use --help" ;;
  esac
done
trap 'printf "error: installation stopped; see the message above, fix it and run the same command again.\n" >&2' ERR

if [ "$DRY_RUN" -eq 0 ]; then
  require_normal_user
  [ "$(uname -s)" = Linux ] || die "TapTune installs on Raspberry Pi OS (Linux) only"
fi

if [ "$CONFIGURE" -eq 0 ]; then
  if [ ! -x "$PYTHON" ]; then
    if [ "$DRY_RUN" -eq 0 ]; then
      python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null ||
        die "Python 3.10 or newer is required"
    fi
    run python3 -m venv "$REPO_DIR/.venv"
  fi
  retry "$PYTHON" -m pip install -r "$REPO_DIR/requirements.txt" -r "$REPO_DIR/requirements-pi.txt"
  if [ -e "$REPO_DIR/.env" ]; then
    echo "Keeping your existing .env."
  elif [ "$DRY_RUN" -eq 1 ]; then
    echo "# create a private .env from .env.example"
  else
    (umask 077; set -o noclobber; cat "$REPO_DIR/.env.example" > "$REPO_DIR/.env")
  fi
  [ "$DRY_RUN" -eq 0 ] || { printf '\nPreview only; nothing changed.\n'; exit 0; }
  printf '\nTapTune is prepared. Next: edit .env (see docs/raspberry-pi-service.md), then run:\n'
  printf '  ./install.sh --configure\n'
  exit 0
fi

if [ "$DRY_RUN" -eq 0 ]; then
  [ -x "$PYTHON" ] && [ -f "$REPO_DIR/.env" ] || die "run ./install.sh first"
  command -v sudo >/dev/null || die "sudo is required"
  command -v systemctl >/dev/null || die "systemd is required"
  [ "$(ls -ld "$REPO_DIR/.env" | cut -c5-10)" = ------ ] ||
    die ".env can be read by other users; run: chmod 600 .env"
  case "$(env_value NFC_READER_ENABLED | tr '[:upper:]' '[:lower:]')" in
    true|1|yes|on) ;;
    *) die "test the NFC reader with the first-card check, then set NFC_READER_ENABLED=true in .env" ;;
  esac
  install_services
else
  echo "# check .env (private, NFC_READER_ENABLED=true)"
  install_services --dry-run
fi

if [ "$DRY_RUN" -eq 1 ]; then
  printf '\nPreview only; nothing changed.\n'
  exit 0
fi
DEVICE_NAME="$(env_value SPOTIFY_DEVICE_NAME)"
cat <<EOF_DONE

TapTune is installed and running.
- First time only: on a phone on the same Wi-Fi, open Spotify, tap Devices and choose ${DEVICE_NAME:-TapTune}.
- Setup page: http://$(hostname).local/setup
- Wi-Fi setup name and password: taptune setup-wifi
- Check or troubleshoot: taptune status, taptune logs
EOF_DONE
