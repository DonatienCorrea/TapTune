#!/usr/bin/env bash
# Keeps the Bluetooth speaker named by BLUETOOTH_SPEAKER_MAC connected.
# BlueZ does not reliably reconnect an audio sink after boot or after the
# speaker is switched off and on again, so this loop retries every few seconds.
set -euo pipefail

ONCE=0
for arg in "$@"; do
  case "$arg" in
    --once)
      ONCE=1
      ;;
    *)
      echo "error: unknown argument '$arg'" >&2
      exit 2
      ;;
  esac
done

MAC="${BLUETOOTH_SPEAKER_MAC:-}"
INTERVAL="${BLUETOOTH_RECONNECT_INTERVAL:-10}"
BLUETOOTHCTL="${BLUETOOTHCTL:-bluetoothctl}"

if [ -z "$MAC" ]; then
  echo "BLUETOOTH_SPEAKER_MAC is empty in .env; nothing to keep connected."
  exit 0
fi

MAC="$(printf '%s' "$MAC" | tr '[:lower:]' '[:upper:]')"
if ! printf '%s' "$MAC" | grep -Eq '^([0-9A-F]{2}:){5}[0-9A-F]{2}$'; then
  echo "error: BLUETOOTH_SPEAKER_MAC '$MAC' is not a Bluetooth address like AA:BB:CC:DD:EE:FF" >&2
  exit 2
fi

was_connected=""
while true; do
  if "$BLUETOOTHCTL" info "$MAC" 2>/dev/null | grep -q 'Connected: yes'; then
    if [ "$was_connected" != "yes" ]; then
      echo "Speaker $MAC connected."
      was_connected="yes"
    fi
  else
    if [ "$was_connected" = "yes" ]; then
      echo "Speaker $MAC disconnected; retrying."
    fi
    was_connected="no"
    "$BLUETOOTHCTL" connect "$MAC" >/dev/null 2>&1 || true
  fi

  if [ "$ONCE" -eq 1 ]; then
    exit 0
  fi
  sleep "$INTERVAL"
done
