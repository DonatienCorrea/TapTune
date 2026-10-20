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
  value="${value//%/%%}"
  if [ "${2:-}" = "exec" ]; then
    value="${value//\$/\$\$}"
  fi
  printf '"%s"' "$value"
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
