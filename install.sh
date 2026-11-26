#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF_USAGE'
Usage: ./install.sh [--configure] [--dry-run]

Installs TapTune and starts its services. Creates a private .env if missing.
  --configure   Reapply settings and restart an existing installation.
  --dry-run     Show what would be done without changing anything.

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
  command -v sudo >/dev/null || die "sudo is required"
  command -v systemctl >/dev/null || die "systemd is required"
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
fi

if [ "$DRY_RUN" -eq 0 ]; then
  require_prepared
  [ "$(ls -ld "$REPO_DIR/.env" | cut -c5-10)" = ------ ] ||
    die ".env can be read by other users; run: chmod 600 .env"
  install_services
else
  echo "# check .env is private"
  install_services --dry-run
fi

if [ "$DRY_RUN" -eq 1 ]; then
  printf '\nPreview only; nothing changed.\n'
  exit 0
fi
printf '\nNext: open http://%s.local/setup on a phone on the same Wi-Fi.\n' "$(hostname)"
