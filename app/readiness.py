"""Play a short sound once the Pi's own Spotify speaker is ready after boot."""

from __future__ import annotations

import argparse
import io
import json
import logging
import math
import struct
import subprocess
import tempfile
import threading
import time
import wave
from typing import Callable, Optional
from urllib.request import urlopen

from .bluetooth import BluetoothNotReady, ensure_speaker_connected
from .config import settings
from .spotify_service import build_spotify_client, find_device_id, is_live_spotify_configured

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100
# Two rising notes (E5 then A5): short, friendly, and distinct from music.
CHIME_NOTES = ((659.25, 0.14), (880.0, 0.22))


def build_chime_wav(sample_rate: int = SAMPLE_RATE, volume: float = 0.35) -> bytes:
    frames = bytearray()
    for frequency, duration in CHIME_NOTES:
        count = int(sample_rate * duration)
        fade = max(1, int(sample_rate * 0.01))
        for index in range(count):
            envelope = min(1.0, index / fade, (count - index) / fade)
            sample = volume * envelope * math.sin(2 * math.pi * frequency * index / sample_rate)
            value = int(sample * 32767)
            # Stereo: Bluetooth A2DP sinks expect two channels.
            frames += struct.pack("<hh", value, value)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(bytes(frames))
    return buffer.getvalue()


_last_play_failure = [None]


def _summarize_aplay_error(stderr: str) -> str:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    # aplay's own error line is the useful one; BlueALSA debug lines are noise.
    for line in reversed(lines):
        if line.startswith("aplay:"):
            return line
    return lines[-1] if lines else "no error output"


def _aplay(wav: bytes, device: str, runner):
    command = ["aplay", "-q"]
    if device:
        command += ["-D", device]
    command.append("-")
    return runner(command, input=wav, capture_output=True, timeout=10)


def play_sound(wav: bytes, audio_device: Optional[str] = None, runner=subprocess.run) -> bool:
    device = settings.AUDIO_OUTPUT_DEVICE if audio_device is None else audio_device
    if device == "bluealsa" and settings.BLUETOOTH_SPEAKER_MAC:
        device = f"bluealsa:DEV={settings.BLUETOOTH_SPEAKER_MAC},PROFILE=a2dp"
    try:
        result = _aplay(wav, device, runner)
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Could not play the ready sound: %s", error)
        return False
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode(errors="replace").strip()
        reason = _summarize_aplay_error(stderr)
        # Retried every few seconds while the speaker connects: log each distinct reason once.
        level = logging.INFO if reason != _last_play_failure[0] else logging.DEBUG
        _last_play_failure[0] = reason
        logger.log(level, "Ready sound not played yet (speaker not connected?): %s", reason)
        return False
    return True


def play_desktop_sound(wav: bytes, runner=subprocess.run) -> bool:
    """Use the audio user's server, never a root/HDMI fallback."""
    mac = settings.BLUETOOTH_SPEAKER_MAC
    if not mac:
        logger.warning("Desktop ready sound requires BLUETOOTH_SPEAKER_MAC.")
        return False
    try:
        ensure_speaker_connected(runner=runner)
        result = runner(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            logger.info("Waiting for PipeWire sinks: %s", result.stderr.strip())
            return False
        prefix = "bluez_output." + mac.replace(":", "_").casefold()
        sink = next((
            fields[1] for line in result.stdout.splitlines()
            if len(fields := line.split()) >= 2
            and (fields[1].casefold() == prefix or fields[1].casefold().startswith(prefix + "."))
        ), None)
        default = runner(["pactl", "get-default-sink"], capture_output=True, text=True, timeout=5)
        if not sink or default.returncode != 0 or default.stdout.strip() != sink:
            logger.info("Waiting for the Bluetooth reconnect service to route audio to %s.", mac)
            return False
        with tempfile.NamedTemporaryFile(suffix=".wav") as sound:
            sound.write(wav)
            sound.flush()
            result = runner(
                ["paplay", "--device", sink, sound.name],
                capture_output=True, text=True, timeout=10,
            )
        if result.returncode != 0:
            logger.info("Desktop ready sound not played yet: %s", result.stderr.strip())
            return False
        return True
    except (BluetoothNotReady, OSError, subprocess.SubprocessError) as error:
        logger.info("Waiting for the desktop speaker: %s", error)
        return False


def app_ready() -> bool:
    host = settings.APP_HOST
    if host in {"0.0.0.0", "::"}:
        host = "127.0.0.1"
    if ":" in host:
        host = f"[{host}]"
    try:
        with urlopen(f"http://{host}:{settings.APP_PORT}/ready", timeout=3) as response:
            payload = json.load(response)
        return isinstance(payload, dict) and payload.get("app") == "TapTune" and payload.get("status") == "ready"
    except (OSError, ValueError) as error:
        logger.info("Waiting for TapTune and its enabled reader: %s", error)
        return False


def speaker_device_visible() -> bool:
    try:
        return find_device_id(build_spotify_client()) is not None
    except Exception as error:  # noqa: BLE001 - network may not be up yet during boot.
        logger.info("Waiting for Spotify: %s", error)
        return False


def wait_until_ready_then_chime(
    is_device_visible: Callable[[], bool] = speaker_device_visible,
    play: Callable[[bytes], bool] = play_sound,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 5.0,
    timeout_seconds: float = 600.0,
    stop_event: Optional[threading.Event] = None,
    is_app_ready: Callable[[], bool] = app_ready,
) -> bool:
    """Wait for TapTune, the Connect device and audio, then play once."""
    waited = 0.0
    device_seen = False
    wav = build_chime_wav()
    while waited <= timeout_seconds:
        if stop_event is not None and stop_event.is_set():
            return False
        attempt_started = time.monotonic()
        if is_app_ready():
            visible = is_device_visible()
            if visible and not device_seen:
                logger.info("Spotify speaker '%s' is online.", settings.SPOTIFY_DEVICE_NAME)
            device_seen = visible
            if visible and play(wav):
                logger.info("TapTune is ready: played the ready sound.")
                return True
        waited += time.monotonic() - attempt_started
        if waited >= timeout_seconds:
            break
        sleep(interval_seconds)
        waited += interval_seconds
    logger.warning(
        "Readiness timed out; check TapTune, its enabled reader, Spotifyd/Raspotify, "
        "the network and speaker audio (receiver: '%s').",
        settings.SPOTIFY_DEVICE_NAME,
    )
    return False


def should_announce_ready() -> bool:
    return bool(settings.READY_SOUND_ENABLED and settings.SPOTIFY_DEVICE_NAME and is_live_spotify_configured())


def initialize_speaker(
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 5.0,
    timeout_seconds: float = 600.0,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    """Set only the Pi receiver's startup volume, even when its chime is disabled."""
    waited = 0.0
    while waited <= timeout_seconds:
        if stop_event is not None and stop_event.is_set():
            return False
        attempt_started = time.monotonic()
        try:
            spotify = build_spotify_client()
            device_id = find_device_id(spotify)
            if device_id is not None:
                spotify.volume(settings.SPOTIFY_INITIAL_VOLUME, device_id=device_id)
                logger.info("Set '%s' startup volume to %s%%.", settings.SPOTIFY_DEVICE_NAME, settings.SPOTIFY_INITIAL_VOLUME)
                if should_announce_ready():
                    remaining = max(0.0, timeout_seconds - waited - (time.monotonic() - attempt_started))
                    return wait_until_ready_then_chime(stop_event=stop_event, timeout_seconds=remaining)
                return True
        except Exception as error:  # noqa: BLE001 - the receiver/network may still be starting.
            logger.info("Waiting to set startup volume: %s", error)
        waited += time.monotonic() - attempt_started
        if waited >= timeout_seconds:
            break
        sleep(interval_seconds)
        waited += interval_seconds
    logger.warning("Could not set startup volume; check Spotifyd/Raspotify and the network.")
    return False


def start_speaker_thread(target: Callable[[], bool] = initialize_speaker) -> Optional[threading.Thread]:
    if not settings.SPOTIFY_DEVICE_NAME or not is_live_spotify_configured():
        return None
    thread = threading.Thread(target=target, name="speaker-startup", daemon=True)
    thread.start()
    return thread


def start_readiness_thread(target: Callable[[], bool] = wait_until_ready_then_chime) -> Optional[threading.Thread]:
    if not should_announce_ready():
        return None
    return start_speaker_thread(target=target)


def main() -> int:
    parser = argparse.ArgumentParser(description="Play TapTune's startup ready sound once.")
    parser.add_argument("--desktop", action="store_true", help="Play through the current user's PipeWire session.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if not settings.READY_SOUND_ENABLED:
        logger.info("Ready sound disabled.")
        return 0
    if not should_announce_ready():
        logger.error("Ready sound requires live Spotify credentials and SPOTIFY_DEVICE_NAME.")
        return 1
    play = play_desktop_sound if args.desktop else play_sound
    return 0 if wait_until_ready_then_chime(play=play) else 1


if __name__ == "__main__":
    raise SystemExit(main())
