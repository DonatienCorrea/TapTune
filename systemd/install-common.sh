#!/usr/bin/env bash
# Shared by the installers and the taptune command; never source .env as shell code.

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
# Seconds before the first retry (doubles each time); tests set 0.
RETRY_DELAY="${TAPTUNE_RETRY_DELAY:-5}"

die() { printf 'error: %s\n' "$*" >&2; exit 1; }

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '%q ' "$@"
    printf '\n'
  else
    LAST_RUN="$*"
    "$@"
  fi
}

# Network steps (apt, pip, git, downloads): 3 attempts, then the last error status.
retry() {
  local attempt=1 delay="$RETRY_DELAY" status
  while true; do
    run "$@" && return 0 || status=$?
    [ "$attempt" -lt 3 ] || return "$status"
    printf 'warning: "%s" failed; retrying in %s s\n' "$*" "$delay" >&2
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

apt_install() {
  retry sudo env DEBIAN_FRONTEND=noninteractive apt-get install -y "$@"
}

# The systemd/*.sh installers accept only --dry-run (preview without changes).
parse_dry_run() {
  local arg
  DRY_RUN=0
  for arg in "$@"; do
    [ "$arg" = --dry-run ] || die "unknown argument '$arg'"
    DRY_RUN=1
  done
}

require_normal_user() {
  if [ "$DRY_RUN" -eq 0 ] && [ "$(id -u)" -eq 0 ]; then
    die "run as your normal user, without sudo; it asks for sudo when needed"
  fi
}

# Real runs need what ./install.sh prepares: .venv and .env.
require_prepared() {
  [ "$DRY_RUN" -eq 0 ] || return 0
  [ -x "$REPO_DIR/.venv/bin/python" ] || die "$REPO_DIR/.venv not found; run ./install.sh first"
  [ -f "$REPO_DIR/.env" ] || die "$REPO_DIR/.env not found; run ./install.sh first"
}

env_value() {
  local value=""
  if [ -f "$REPO_DIR/.env" ]; then
    value="$(grep -E "^$1=" "$REPO_DIR/.env" | tail -n 1 | cut -d= -f2- || true)"
  fi
  value="${value%\"}"
  value="${value#\"}"
  value="${value%\'}"
  value="${value#\'}"
  printf '%s' "$value"
}

is_mac() {
  printf '%s' "$1" | grep -Eq '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$'
}

# go-librespot, this user's PipeWire, then the TapTune app service.
install_services() {
  run bash "$SCRIPT_DIR/install-go-librespot.sh" "$@"
  run bash "$SCRIPT_DIR/install-service.sh" "$@"
}

user_manager_available() {
  systemctl --user show-environment >/dev/null 2>&1
}

# One-time cleanup on Pis installed before go-librespot became the only receiver
# (Raspotify/BlueALSA, Spotifyd, periodic reconnect and ready-sound services).
# Only units that are actually installed are touched.
remove_legacy_units() {
  local unit
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "# stop and remove old Raspotify, Spotifyd, BlueALSA and TapTune helper units if present"
    return 0
  fi
  for unit in raspotify.service spotifyd.service bluealsa-aplay.service bluealsa.service taptune-bluetooth.service; do
    if systemctl list-unit-files --no-legend "$unit" 2>/dev/null | grep -q "^${unit}[[:space:]]"; then
      echo "Removing old service $unit (no longer used by TapTune)."
      run sudo systemctl disable --now "$unit"
    fi
  done
  run sudo rm -f /etc/systemd/system/raspotify.service.d/taptune.conf /etc/systemd/system/taptune-bluetooth.service
  for unit in spotifyd.service taptune-spotifyd.service taptune-bluetooth.service taptune-ready-sound.service; do
    local file="$CONFIG_DIR/systemd/user/$unit"
    [ "$unit" != spotifyd.service ] || file=""
    if ! user_manager_available; then
      if [ -n "$file" ] && [ -f "$file" ]; then
        die "log in as $(id -un) (not with sudo/su) and rerun: the old $unit must be stopped first"
      fi
      continue
    fi
    if systemctl --user list-unit-files --no-legend "$unit" 2>/dev/null | grep -q "^${unit}[[:space:]]"; then
      echo "Removing old user service $unit (no longer used by TapTune)."
      run systemctl --user disable --now "$unit"
    fi
    [ -z "$file" ] || run rm -f "$file"
  done
  run rm -f "$HOME/.local/lib/taptune/taptune-bluetooth.sh" "$CONFIG_DIR/taptune/bluetooth.env"
  rmdir "$HOME/.local/lib/taptune" "$CONFIG_DIR/taptune" 2>/dev/null || true
}
