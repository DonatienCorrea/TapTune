"""Play a short sound once the Pi's own Spotify speaker is ready after boot."""

from __future__ import annotations

import io
import logging
import math
import struct
import subprocess
import threading
import time
import wave
from typing import Callable, Optional

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


def play_sound(wav: bytes, audio_device: Optional[str] = None, runner=subprocess.run) -> bool:
    device = settings.AUDIO_OUTPUT_DEVICE if audio_device is None else audio_device
    command = ["aplay", "-q"]
    if device:
        command += ["-D", device]
    command.append("-")
    try:
        result = runner(command, input=wav, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Could not play the ready sound: %s", error)
        return False
    if result.returncode != 0:
        stderr = (result.stderr or b"").decode(errors="replace").strip()
        logger.info("Ready sound not played yet (aplay exit %s): %s", result.returncode, stderr)
        return False
    return True


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
) -> bool:
    """Wait for the Connect device, then play the chime once. Returns True if it played."""
    waited = 0.0
    device_seen = False
    wav = build_chime_wav()
    while waited <= timeout_seconds:
        if stop_event is not None and stop_event.is_set():
            return False
        if not device_seen:
            device_seen = is_device_visible()
            if device_seen:
                logger.info("Spotify speaker '%s' is online.", settings.SPOTIFY_DEVICE_NAME)
        if device_seen and play(wav):
            logger.info("TapTune is ready: played the ready sound.")
            return True
        sleep(interval_seconds)
        waited += interval_seconds
    if device_seen:
        logger.warning("Spotify speaker is online but the ready sound could not be played; check the speaker.")
    else:
        logger.warning(
            "Spotify speaker '%s' did not appear; check raspotify and the network.",
            settings.SPOTIFY_DEVICE_NAME,
        )
    return False


def should_announce_ready() -> bool:
    return bool(settings.READY_SOUND_ENABLED and settings.SPOTIFY_DEVICE_NAME and is_live_spotify_configured())


def start_readiness_thread(target: Callable[[], bool] = wait_until_ready_then_chime) -> Optional[threading.Thread]:
    if not should_announce_ready():
        return None
    thread = threading.Thread(target=target, name="ready-sound", daemon=True)
    thread.start()
    return thread
