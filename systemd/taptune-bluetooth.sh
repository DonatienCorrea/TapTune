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
PACTL="${PACTL:-pactl}"
AUDIO_BACKEND="${AUDIO_BACKEND:-alsa}"

if ! printf '%s' "$INTERVAL" | grep -Eq '^[1-9][0-9]*$'; then
  echo "error: BLUETOOTH_RECONNECT_INTERVAL must be a positive integer" >&2
  exit 2
fi
case "$AUDIO_BACKEND" in
  alsa|pulseaudio) ;;
  *)
    echo "error: AUDIO_BACKEND must be alsa or pulseaudio" >&2
    exit 2
    ;;
esac

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
route_speaker() {
  local sinks sink sink_id inputs input_id input_sink rest default_sink
  if ! sinks="$("$PACTL" list short sinks)"; then
    echo "Audio server is not ready; will retry." >&2
    return
  fi
  sink="$(printf '%s\n' "$sinks" | awk -v mac="${MAC//:/_}" \
    '$2 ~ "^bluez_output\\." mac "([.]|$)" { print $2; exit }')"
  if [ -z "$sink" ]; then
    echo "Speaker $MAC has no Bluetooth audio sink yet; will retry." >&2
    return
  fi
  sink_id="$(printf '%s\n' "$sinks" | awk -v name="$sink" '$2 == name { print $1; exit }')"
  if ! default_sink="$("$PACTL" get-default-sink)"; then
    echo "Could not read the default audio sink; will retry." >&2
    return
  fi
  if [ "$default_sink" != "$sink" ]; then
    if ! "$PACTL" set-default-sink "$sink"; then
      echo "Could not route audio to $sink; will retry." >&2
      return
    fi
    echo "Default audio output is now $sink."
  fi
  if ! inputs="$("$PACTL" list short sink-inputs)"; then
    echo "Could not list playback streams; will retry." >&2
    return
  fi
  while read -r input_id input_sink rest; do
    if [ -n "$input_id" ] && [ "$input_sink" != "$sink_id" ]; then
      if ! "$PACTL" move-sink-input "$input_id" "$sink"; then
        echo "Could not move playback stream $input_id to the speaker; will retry." >&2
      fi
    fi
  done <<< "$inputs"
}

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
    if ! "$BLUETOOTHCTL" --timeout 10 connect "$MAC"; then
      echo "Could not connect speaker $MAC; will retry." >&2
      # At boot the adapter can still be off or blocked; power it on for the next try.
      "$BLUETOOTHCTL" power on >/dev/null 2>&1 || true
    fi
  fi

  if [ "$AUDIO_BACKEND" = "pulseaudio" ]; then
    route_speaker
  fi

  if [ "$ONCE" -eq 1 ]; then
    exit 0
  fi
  sleep "$INTERVAL"
done
