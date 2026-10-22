#!/usr/bin/env bash
# Shared by the installers; never source .env as executable shell code.

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '%q ' "$@"
    printf '\n'
  else
    LAST_RUN="$*"
    "$@"
  fi
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

initial_volume() {
  local volume
  volume="$(env_value SPOTIFY_INITIAL_VOLUME)"
  volume="${volume:-30}"
  if ! printf '%s' "$volume" | grep -Eq '^(100|[1-9]?[0-9])$'; then
    echo "error: SPOTIFY_INITIAL_VOLUME must be an integer from 0 to 100" >&2
    return 1
  fi
  printf '%s' "$volume"
}

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

render_unit() {
  local line
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      WorkingDirectory=*) printf 'WorkingDirectory=%s\n' "$(unit_path "$REPO_DIR")" ;;
      EnvironmentFile=*) printf 'EnvironmentFile=%s\n' "$(unit_path "$REPO_DIR/.env")" ;;
      ExecStart=*) printf 'ExecStart=%s%s\n' "$(unit_path "$2" exec)" "${3:-}" ;;
      *) printf '%s\n' "$line" ;;
    esac
  done < "$1"
}

# Mode switches and upgrades: stop services that compete with this setup or that
# TapTune no longer uses. Only units that are actually installed are touched, and
# a failure to stop one stops the installer instead of leaving two stacks running.
system_unit_installed() {
  systemctl list-unit-files --no-legend "$1" 2>/dev/null | grep -q "^$1[[:space:]]"
}

user_unit_installed() {
  systemctl --user list-unit-files --no-legend "$1" 2>/dev/null | grep -q "^$1[[:space:]]"
}

disable_system_unit() {
  local unit="$1" reason="$2"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '# if %s is installed (%s):\n' "$unit" "$reason"
    run sudo systemctl disable --now "$unit"
  elif system_unit_installed "$unit"; then
    echo "Stopping and disabling $unit: $reason."
    run sudo systemctl disable --now "$unit"
  fi
}

user_manager_available() {
  systemctl --user show-environment >/dev/null 2>&1
}

# Stops a user unit; also deletes its file when TapTune installed it.
disable_user_unit() {
  local unit="$1" reason="$2" owned_file="${3:-}"
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '# if user unit %s is installed (%s):\n' "$unit" "$reason"
    run systemctl --user disable --now "$unit"
    [ -z "$owned_file" ] || run rm -f "$owned_file"
    return
  fi
  if ! user_manager_available; then
    if [ -n "$owned_file" ] && [ -f "$owned_file" ]; then
      echo "error: $owned_file exists but this user's systemd manager is not reachable to stop it." >&2
      echo "Log in as $(id -un) (not with sudo/su) and rerun, or run: systemctl --user disable --now $unit" >&2
      return 1
    fi
    return 0
  fi
  if user_unit_installed "$unit"; then
    echo "Stopping and disabling user service $unit: $reason."
    run systemctl --user disable --now "$unit"
  fi
  if [ -n "$owned_file" ] && [ -f "$owned_file" ]; then
    run rm -f "$owned_file"
  fi
}

# Before this version a reconnect loop ran every 10 s; TapTune now connects
# the speaker itself at boot and when a tag starts or resumes music.
remove_legacy_system_units() {
  local unit=/etc/systemd/system/taptune-bluetooth.service
  if [ "$DRY_RUN" -eq 1 ] || [ -f "$unit" ]; then
    [ "$DRY_RUN" -eq 0 ] || echo "# if $unit exists (replaced by on-demand reconnect in TapTune):"
    [ "$DRY_RUN" -eq 1 ] || echo "Removing the obsolete periodic Bluetooth reconnect service."
    run sudo systemctl disable --now taptune-bluetooth.service
    run sudo rm -f "$unit"
    run sudo systemctl daemon-reload
  fi
}

remove_legacy_user_units() {
  local config="${XDG_CONFIG_HOME:-$HOME/.config}"
  disable_user_unit taptune-bluetooth.service "replaced by on-demand reconnect in TapTune" \
    "$config/systemd/user/taptune-bluetooth.service" || return 1
  disable_user_unit taptune-ready-sound.service "the TapTune app now plays the ready sound" \
    "$config/systemd/user/taptune-ready-sound.service" || return 1
  run rm -f "$HOME/.local/lib/taptune/taptune-bluetooth.sh" "$config/taptune/bluetooth.env"
  if [ "$DRY_RUN" -eq 0 ]; then
    rmdir "$HOME/.local/lib/taptune" "$config/taptune" 2>/dev/null || true
  fi
}
