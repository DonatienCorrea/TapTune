"""Startup of the Pi's own speaker: volume, one bounded Bluetooth connection and
a short ready sound. Runs in the TapTune app for both Lite (BlueALSA) and
Desktop (the audio user's PipeWire), so there is no separate chime service."""

from __future__ import annotations

import argparse
import io
import json
import logging
import math
import struct
import subprocess
import threading
import time
import wave
from typing import Callable, Optional
from urllib.error import HTTPError
from urllib.request import urlopen

from .bluetooth import BluetoothNotReady, desktop_command, prepare_speaker, speaker_mac
from .config import settings
from .spotify_service import build_spotify_client, find_device_id, is_live_spotify_configured

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100
# Two rising notes (E5 then A5): short, friendly, and distinct from music.
CHIME_NOTES = ((659.25, 0.14), (880.0, 0.22))


# Boot tries to connect the speaker this many times (one `bluetoothctl connect`
# each, every 5 s), then stops: later connections only happen for a tag.
BOOT_SPEAKER_ATTEMPTS = 12


# Half of the original 0.35 amplitude: audible without startling anyone.
CHIME_VOLUME = 0.175


def build_chime_wav(sample_rate: int = SAMPLE_RATE, volume: float = CHIME_VOLUME) -> bytes:
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


class _WaitLog:
    """Log each waiting reason once (and again every minute), not every 5 seconds.

    The last reason is kept so a timeout says what was still wrong.
    """

    REPEAT_SECONDS = 60.0

    def __init__(self):
        self.reset()

    def reset(self):
        self.last = None
        self.last_logged_at = 0.0

    def __call__(self, message: str, *args) -> None:
        text = message % args if args else message
        now = time.monotonic()
        if text != self.last or now - self.last_logged_at >= self.REPEAT_SECONDS:
            logger.info("%s", text)
            self.last_logged_at = now
        else:
            logger.debug("%s", text)
        self.last = text


_wait_log = _WaitLog()


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
        _wait_log.last = f"Ready sound not played yet (speaker not connected?): {reason}"
        logger.log(level, "%s", _wait_log.last)
        return False
    return True


def _pcm_frames(wav: bytes) -> bytes:
    with wave.open(io.BytesIO(wav)) as sound:
        return sound.readframes(sound.getnframes())


def _play_pipewire(wav: bytes, sink: str, runner, user: Optional[str]) -> bool:
    """Play raw PCM to the exact Bluetooth sink: never the default/HDMI output."""
    command = desktop_command([
        "pacat", "--playback", f"--device={sink}", "--format=s16le",
        f"--rate={SAMPLE_RATE}", "--channels=2",
    ], user)
    result = runner(command, input=_pcm_frames(wav), capture_output=True, timeout=10)
    if result.returncode != 0:
        _wait_log("Ready sound not played yet: %s", (result.stderr or b"").decode(errors="replace").strip())
        return False
    return True


def play_ready_sound(
    wav: bytes,
    runner=subprocess.run,
    desktop: Optional[bool] = None,
    user: Optional[str] = None,
) -> bool:
    """Connect the speaker (one attempt), route audio to it, then play the chime."""
    desktop = bool(settings.DESKTOP_AUDIO_USER) if desktop is None else desktop
    if desktop and not settings.BLUETOOTH_SPEAKER_MAC:
        logger.warning("Desktop ready sound requires BLUETOOTH_SPEAKER_MAC.")
        return False
    try:
        output = prepare_speaker(runner=runner, connect_attempts=1, desktop=desktop, user=user)
        if desktop:
            return _play_pipewire(wav, output, runner, user)
    except (BluetoothNotReady, OSError, subprocess.SubprocessError) as error:
        _wait_log("Waiting for the Bluetooth speaker: %s", error)
        return False
    return play_sound(wav, runner=runner)


def play_desktop_sound(wav: bytes, runner=subprocess.run) -> bool:
    """`python -m app.readiness --desktop`: play in the current user's PipeWire session."""
    return play_ready_sound(wav, runner=runner, desktop=True, user="")


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
    except HTTPError as error:
        try:
            payload = json.load(error)
        except (OSError, ValueError):
            payload = {}
        if payload.get("spotify_mode") == "fake":
            _wait_log("Waiting for TapTune: it runs in fake Spotify mode; check the Spotify values in .env.")
        elif payload.get("reader_ready") is False:
            _wait_log("Waiting for TapTune: the NFC reader is not open yet (see the PN532 errors in the logs).")
        else:
            _wait_log("Waiting for TapTune: /ready answered %s.", error.code)
        return False
    except (OSError, ValueError) as error:
        _wait_log("Waiting for TapTune to answer on port %s: %s", settings.APP_PORT, error)
        return False


def speaker_device_visible() -> bool:
    try:
        visible = find_device_id(build_spotify_client()) is not None
    except Exception as error:  # noqa: BLE001 - network may not be up yet during boot.
        _wait_log("Waiting for Spotify: %r", error)
        return False
    if not visible:
        _wait_log(
            "Waiting for the Spotify receiver '%s' to appear in Spotify's device list "
            "(is Spotifyd/Raspotify running and logged in to the same account?).",
            settings.SPOTIFY_DEVICE_NAME,
        )
    return visible


def wait_until_ready_then_chime(
    is_device_visible: Callable[[], bool] = speaker_device_visible,
    play: Callable[[bytes], bool] = play_ready_sound,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 5.0,
    timeout_seconds: float = 600.0,
    stop_event: Optional[threading.Event] = None,
    is_app_ready: Callable[[], bool] = app_ready,
    max_play_attempts: Optional[int] = BOOT_SPEAKER_ATTEMPTS,
) -> bool:
    """Wait for TapTune and the Connect device, then try a bounded number of times
    to connect the speaker and play the chime once."""
    waited = 0.0
    play_attempts = 0
    device_seen = False
    wav = build_chime_wav()
    _wait_log.reset()
    while waited <= timeout_seconds:
        if stop_event is not None and stop_event.is_set():
            return False
        attempt_started = time.monotonic()
        if is_app_ready():
            visible = is_device_visible()
            if visible and not device_seen:
                logger.info("Spotify speaker '%s' is online.", settings.SPOTIFY_DEVICE_NAME)
            device_seen = visible
            if visible:
                if play(wav):
                    logger.info("TapTune is ready: played the ready sound.")
                    return True
                play_attempts += 1
                if max_play_attempts is not None and play_attempts >= max_play_attempts:
                    logger.warning(
                        "No ready sound: the speaker did not play after %d attempts (%s). TapTune stays "
                        "ready and connects the speaker when a tag starts or resumes music.",
                        play_attempts, _wait_log.last or "unknown",
                    )
                    return False
        waited += time.monotonic() - attempt_started
        if waited >= timeout_seconds:
            break
        sleep(interval_seconds)
        waited += interval_seconds
    logger.warning(
        "Readiness timed out after %.0f s; no ready sound. Last problem: %s",
        timeout_seconds, _wait_log.last or "unknown",
    )
    return False


def connect_speaker_at_boot(
    prepare: Callable[..., Optional[str]] = prepare_speaker,
    sleep: Callable[[float], None] = time.sleep,
    interval_seconds: float = 5.0,
    attempts: int = BOOT_SPEAKER_ATTEMPTS,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    """With the chime disabled, still connect the speaker once at boot (bounded)."""
    try:
        if not speaker_mac():
            return True
    except BluetoothNotReady as error:
        logger.warning("%s", error)
        return False
    for attempt in range(1, attempts + 1):
        if stop_event is not None and stop_event.is_set():
            return False
        try:
            prepare(connect_attempts=1)
            logger.info("Bluetooth speaker ready after boot.")
            return True
        except BluetoothNotReady as error:
            _wait_log("Waiting for the Bluetooth speaker: %s", error)
        if attempt < attempts:
            sleep(interval_seconds)
    logger.warning(
        "Bluetooth speaker not connected after %d boot attempts (%s). TapTune connects it when a "
        "tag starts or resumes music.", attempts, _wait_log.last or "unknown",
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
    """Set the Pi receiver's startup volume, then connect the speaker once (with the chime if enabled)."""
    waited = 0.0
    _wait_log.reset()
    while waited <= timeout_seconds:
        if stop_event is not None and stop_event.is_set():
            return False
        attempt_started = time.monotonic()
        try:
            spotify = build_spotify_client()
            device_id = find_device_id(spotify)
            if device_id is None:
                _wait_log(
                    "Waiting for the Spotify receiver '%s' before setting the startup volume "
                    "(is Spotifyd/Raspotify running and logged in?).",
                    settings.SPOTIFY_DEVICE_NAME,
                )
            else:
                spotify.volume(settings.SPOTIFY_INITIAL_VOLUME, device_id=device_id)
                logger.info("Set '%s' startup volume to %s%%.", settings.SPOTIFY_DEVICE_NAME, settings.SPOTIFY_INITIAL_VOLUME)
                remaining = max(0.0, timeout_seconds - waited - (time.monotonic() - attempt_started))
                if should_announce_ready():
                    return wait_until_ready_then_chime(stop_event=stop_event, timeout_seconds=remaining)
                return connect_speaker_at_boot(sleep=sleep, interval_seconds=interval_seconds, stop_event=stop_event)
        except Exception as error:  # noqa: BLE001 - the receiver/network may still be starting.
            _wait_log("Waiting to set startup volume: %r", error)
        waited += time.monotonic() - attempt_started
        if waited >= timeout_seconds:
            break
        sleep(interval_seconds)
        waited += interval_seconds
    logger.warning(
        "Could not set the startup volume after %.0f s. Last problem: %s",
        timeout_seconds, _wait_log.last or "unknown",
    )
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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not settings.READY_SOUND_ENABLED:
        logger.info("Ready sound disabled.")
        return 0
    if not should_announce_ready():
        logger.error("Ready sound requires live Spotify credentials and SPOTIFY_DEVICE_NAME.")
        # Configuration error: systemd must not retry it (RestartPreventExitStatus=2).
        return 2
    play = play_desktop_sound if args.desktop else play_ready_sound
    return 0 if wait_until_ready_then_chime(play=play) else 1


if __name__ == "__main__":
    raise SystemExit(main())
