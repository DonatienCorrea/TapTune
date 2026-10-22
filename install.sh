#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage: ./install.sh --lite|--desktop|--app-only [--configure] [--dry-run]

Choose exactly one:
  --lite       Raspberry Pi OS Lite: PN532 + BlueALSA/Raspotify
  --desktop    Raspberry Pi OS Desktop: PN532 + PipeWire/Spotifyd
  --app-only   Base Python dependencies only; no local audio stack

Without --configure: create/reuse .venv, install dependencies, and create a
private .env ONLY if absent. Never starts TapTune or changes system services.
  --configure  Complete an already prepared live installation: check .env and
               prerequisites, then install/restart the selected services.
               App-only configures only TapTune (no Bluetooth/receiver).
  --dry-run    Print commands without writes, installs, sudo or service changes.
  --help       Show this help.

Run as your normal user, NOT with sudo. Desktop must use the Spotifyd audio
user. Preparation needs Python 3.10+, venv support and internet access.
Pi service configuration needs Linux/systemd and sudo access.
Read docs/raspberry-pi-service.md for wiring, pairing and both Spotify logins.
EOF
}

die() { printf 'error: %s\n' "$*" >&2; exit 1; }
MODE=""
CONFIGURE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --lite|--desktop|--app-only)
      [ -z "$MODE" ] || die "choose exactly one installation mode"
      MODE="${arg#--}"
      ;;
    --configure) CONFIGURE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    --help|-h) usage; exit 0 ;;
    *) die "unknown argument '$arg'; use --help" ;;
  esac
done
[ -n "$MODE" ] || { usage >&2; exit 1; }

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_DIR="$REPO_DIR/systemd"
PYTHON="$REPO_DIR/.venv/bin/python"
source "$SCRIPT_DIR/install-common.sh"
trap 'printf "error: installation stopped; read the command output above. No automatic rollback was performed.\n" >&2' ERR

if [ "$DRY_RUN" -eq 0 ]; then
  [ "$(id -u)" -ne 0 ] || die "run as your normal user, without sudo"
  if [ "$MODE" != "app-only" ] || [ "$CONFIGURE" -eq 1 ]; then
    [ "$(uname -s)" = Linux ] || die "Pi installation requires Linux; use --app-only for development"
  fi
fi

if [ "$CONFIGURE" -eq 0 ]; then
  if [ ! -x "$PYTHON" ]; then
    if [ "$DRY_RUN" -eq 0 ]; then
      command -v python3 >/dev/null || die "install Python 3.10+ and python3-venv first"
      python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Python 3.10+ required")'
    fi
    run python3 -m venv "$REPO_DIR/.venv"
  fi
  if [ "$DRY_RUN" -eq 0 ]; then
    "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else "Recreate .venv with Python 3.10+")'
  fi
  run "$PYTHON" -m pip install -r "$REPO_DIR/requirements.txt"
  if [ "$MODE" != "app-only" ]; then
    run "$PYTHON" -m pip install -r "$REPO_DIR/requirements-pi.txt"
  fi
  if [ ! -e "$REPO_DIR/.env" ]; then
    if [ "$DRY_RUN" -eq 1 ]; then
      printf '# Create private .env from .env.example only if absent (umask 077).\n'
    else
      (umask 077; set -o noclobber; cat "$REPO_DIR/.env.example" > "$REPO_DIR/.env")
      chmod 600 "$REPO_DIR/.env"
    fi
  else
    printf 'Keeping existing .env unchanged (including permissions).\n'
  fi
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '\nPreview only; nothing changed.\n'
  else
    printf '\nPrepared %s; no services started.\n' "$MODE"
  fi
  if [ "$MODE" = "app-only" ]; then
    printf 'Fake-mode instructions: docs/getting-started.md\n'
  else
    printf 'Next: docs/raspberry-pi-service.md (hardware, pairing, authorization), then:\n'
    printf '  ./install.sh --%s --configure\n' "$MODE"
  fi
  exit 0
fi

if [ "$DRY_RUN" -eq 0 ]; then
  [ -x "$PYTHON" ] && [ -f "$REPO_DIR/.env" ] || die "run ./install.sh --$MODE first"
  command -v sudo >/dev/null || die "sudo is required for service configuration"
  command -v systemctl >/dev/null || die "systemd is required for service configuration"
  "$PYTHON" - "$REPO_DIR/.env" "$MODE" <<'PY'
import re
import stat
import sys
from pathlib import Path

from dotenv import dotenv_values

path, mode = Path(sys.argv[1]), sys.argv[2]
if stat.S_IMODE(path.stat().st_mode) & 0o077:
    raise SystemExit("error: .env is accessible to other users; run chmod 600 .env")
values = dotenv_values(path)
required = ["SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN"]
if mode != "app-only":
    required += ["SPOTIFY_DEVICE_NAME", "BLUETOOTH_SPEAKER_MAC"]
missing = [name for name in required if not (values.get(name) or "").strip()]
if missing:
    raise SystemExit("error: complete .env first: " + ", ".join(missing))
if mode != "app-only":
    if (values.get("NFC_READER_ENABLED") or "").strip().lower() not in {"true", "1", "yes", "on"}:
        raise SystemExit("error: pass the first-card diagnostic, then set NFC_READER_ENABLED=true")
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", values["BLUETOOTH_SPEAKER_MAC"]):
        raise SystemExit("error: BLUETOOTH_SPEAKER_MAC must be a Bluetooth address")
print("Live configuration fields present (credentials are not verified online).")
PY
  if [ "$MODE" != "app-only" ]; then
    command -v bluetoothctl >/dev/null || die "install bluez and pair/trust the speaker first"
    SPEAKER_INFO="$(bluetoothctl info "$(env_value BLUETOOTH_SPEAKER_MAC)")"
    printf '%s\n' "$SPEAKER_INFO" | grep -Eq 'Paired: yes' || die "pair the Bluetooth speaker first"
    printf '%s\n' "$SPEAKER_INFO" | grep -Eq 'Trusted: yes' || die "trust the Bluetooth speaker first"
  fi
  if [ "$MODE" = desktop ]; then
    [ -x /usr/local/bin/spotifyd ] || die "install Spotifyd at /usr/local/bin/spotifyd; see docs/speaker-setup-desktop.md"
    /usr/local/bin/spotifyd --version
    [ -f "$HOME/.config/spotifyd/spotifyd.conf" ] || die "configure and authenticate Spotifyd as this user first"
  fi
else
  printf '# Would validate private .env, live credentials and selected-mode prerequisites.\n'
fi

installer() {
  if [ "$DRY_RUN" -eq 1 ]; then
    run bash "$@" --dry-run
  else
    run bash "$@"
  fi
}
case "$MODE" in
  lite)
    installer "$SCRIPT_DIR/install-speaker.sh"
    installer "$SCRIPT_DIR/install-service.sh" --lite
    ;;
  desktop)
    installer "$SCRIPT_DIR/install-desktop-speaker.sh"
    installer "$SCRIPT_DIR/install-service.sh" --desktop
    ;;
  app-only)
    installer "$SCRIPT_DIR/install-service.sh" --app-only
    ;;
esac
if [ "$DRY_RUN" -eq 1 ]; then
  printf '\nPreview only; nothing changed. Run the listed scripts with --dry-run to inspect their rendered units.\n'
else
  printf '\nConfigured %s. Inspect: taptune status; taptune logs\n' "$MODE"
  if [ "$MODE" = lite ]; then
    printf 'First install: choose TapTune in Spotify once to cache the receiver login (docs/speaker-setup.md).\n'
  fi
fi
