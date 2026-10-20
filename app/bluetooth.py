"""Connect the Bluetooth speaker and route audio to it only when TapTune needs it.

There is no background reconnect loop. TapTune connects the speaker once at
boot (a bounded number of attempts, for the ready sound) and afterwards only
when a tag starts or resumes music on the Pi's own receiver. A speaker that
switches itself off while nothing plays is left alone.
"""

from __future__ import annotations

import getpass
import logging
import os
import pwd
import re
import subprocess
import threading
import time
from typing import Optional

from .config import settings

logger = logging.getLogger(__name__)

MAC_PATTERN = re.compile(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}")
USER_PATTERN = re.compile(r"[a-z_][a-z0-9_-]{0,31}")
CONNECT_ATTEMPTS = 2
CONNECT_TIMEOUT_SECONDS = 10
# BlueZ reports the link a moment after `connect` returns.
LINK_CHECKS = 6
# After connecting, BlueALSA/PipeWire need a moment to publish the audio output.
OUTPUT_CHECKS = 5
# Spotify (softvol) sets the music level, so the Pi's own output stays at 100%.
OUTPUT_VOLUME = "100%"

_lock = threading.Lock()
# Output volume is set once per connection TapTune makes, so a manual change lasts.
_output_volume_set = [False]


class BluetoothNotReady(Exception):
    pass


def speaker_mac() -> Optional[str]:
    mac = settings.BLUETOOTH_SPEAKER_MAC.strip().upper()
    if not mac:
        return None
    if not MAC_PATTERN.fullmatch(mac):
        raise BluetoothNotReady("BLUETOOTH_SPEAKER_MAC must be an address like AA:BB:CC:DD:EE:FF.")
    return mac


def desktop_command(args: list, user: Optional[str] = None) -> list:
    """Run an audio command in the Desktop audio user's PipeWire session.

    The TapTune app is a system service; PipeWire belongs to the user that runs
    Spotifyd, so the command is run as that user with its runtime directory.
    """
    user = settings.DESKTOP_AUDIO_USER if user is None else user
    if not user:
        return list(args)
    if not USER_PATTERN.fullmatch(user) or user == "root":
        raise BluetoothNotReady(f"DESKTOP_AUDIO_USER '{user}' is not a valid non-root user name.")
    if user == getpass.getuser():
        return list(args)
    try:
        uid = pwd.getpwnam(user).pw_uid
    except KeyError as error:
        raise BluetoothNotReady(f"DESKTOP_AUDIO_USER '{user}' does not exist on this Pi.") from error
    if uid == 0:
        raise BluetoothNotReady("DESKTOP_AUDIO_USER must not be root.")
    runtime_dir = f"/run/user/{uid}"
    if not os.path.isdir(runtime_dir):
        # Without lingering the user's PipeWire only exists after a login.
        raise BluetoothNotReady(
            f"{user}'s audio session is not running ({runtime_dir} missing); "
            f"run 'sudo loginctl enable-linger {user}' (install-desktop-speaker.sh does this)."
        )
    return ["runuser", "-u", user, "--", "env", f"XDG_RUNTIME_DIR={runtime_dir}", *args]


def _is_connected(mac: str, runner) -> bool:
    result = runner(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=5)
    return result.returncode == 0 and any(
        line.strip() == "Connected: yes" for line in (result.stdout or "").splitlines()
    )


def ensure_speaker_connected(runner=subprocess.run, sleep=time.sleep, attempts: int = CONNECT_ATTEMPTS) -> bool:
    """Connect the speaker if it is not connected. Returns True if TapTune connected it."""
    mac = speaker_mac()
    if not mac:
        return False
    try:
        if _is_connected(mac, runner):
            return False
        _output_volume_set[0] = False
        detail = ""
        for attempt in range(1, attempts + 1):
            logger.info("Bluetooth speaker %s is disconnected; connecting (attempt %d/%d).", mac, attempt, attempts)
            result = runner(
                ["bluetoothctl", "--timeout", str(CONNECT_TIMEOUT_SECONDS), "connect", mac],
                capture_output=True, text=True, timeout=CONNECT_TIMEOUT_SECONDS + 2,
            )
            # BlueZ can report InProgress when the speaker itself is reconnecting.
            for check in range(LINK_CHECKS):
                if _is_connected(mac, runner):
                    logger.info("Bluetooth speaker %s connected.", mac)
                    return True
                if check < LINK_CHECKS - 1:
                    sleep(1)
            detail = ((result.stderr or "") + (result.stdout or "")).strip()
            if attempt < attempts:
                # After boot or rfkill the adapter can be off; power it on for the next try.
                runner(["bluetoothctl", "power", "on"], capture_output=True, text=True, timeout=5)
        raise BluetoothNotReady(
            f"Bluetooth speaker {mac} is disconnected. Turn it on and tap again."
            + (f" Bluetooth reported: {detail}" if detail else "")
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BluetoothNotReady(f"Could not check/connect Bluetooth speaker {mac}: {error}") from error


def bluealsa_device(mac: str) -> str:
    device = settings.AUDIO_OUTPUT_DEVICE
    return f"bluealsa:DEV={mac},PROFILE=a2dp" if device == "bluealsa" else device


def _prepare_bluealsa(mac: str, runner, sleep, set_volume: bool) -> tuple:
    device = bluealsa_device(mac)
    if not set_volume or not device.startswith("bluealsa"):
        return device, True
    controls = None
    for check in range(OUTPUT_CHECKS):
        result = runner(["amixer", "-D", device, "scontrols"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            controls = result.stdout or ""
            break
        detail = (result.stderr or result.stdout or "").strip()
        if check < OUTPUT_CHECKS - 1:
            sleep(1)
    if controls is None:
        raise BluetoothNotReady(f"Speaker {mac} is connected but BlueALSA has no output for it yet: {detail}")
    names = re.findall(r"^Simple mixer control '(.*)',\d+$", controls, flags=re.MULTILINE)
    if not names:
        logger.info("BlueALSA has no volume control for speaker %s; it keeps its own level.", mac)
        return device, True
    for name in names:
        result = runner(
            ["amixer", "-q", "-D", device, "sset", name, OUTPUT_VOLUME, "unmute"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            logger.warning(
                "Could not set BlueALSA control '%s' to %s: %s", name, OUTPUT_VOLUME,
                (result.stderr or "").strip(),
            )
            return device, False
    logger.info("Pi output for speaker %s set to %s.", mac, OUTPUT_VOLUME)
    return device, True


def _route_pipewire(mac: str, runner, sleep, set_volume: bool, user: Optional[str]) -> tuple:
    def pactl(*args):
        return runner(desktop_command(["pactl", *args], user), capture_output=True, text=True, timeout=5)

    prefix = "bluez_output." + mac.replace(":", "_").casefold()
    sink = sink_id = None
    detail = "no Bluetooth output yet"
    for check in range(OUTPUT_CHECKS):
        result = pactl("list", "short", "sinks")
        if result.returncode == 0:
            for line in (result.stdout or "").splitlines():
                fields = line.split()
                if len(fields) >= 2 and (
                    fields[1].casefold() == prefix or fields[1].casefold().startswith(prefix + ".")
                ):
                    sink_id, sink = fields[0], fields[1]
                    break
            if sink:
                break
        else:
            detail = (result.stderr or "").strip() or "audio server not answering"
        if check < OUTPUT_CHECKS - 1:
            sleep(1)
    if not sink:
        raise BluetoothNotReady(f"Speaker {mac} is connected but PipeWire has no output for it ({detail}).")

    volume_ok = True
    if set_volume:
        if pactl("set-sink-volume", sink, OUTPUT_VOLUME).returncode == 0 and pactl("set-sink-mute", sink, "0").returncode == 0:
            logger.info("Pi output %s set to %s.", sink, OUTPUT_VOLUME)
        else:
            logger.warning("Could not set %s to %s.", sink, OUTPUT_VOLUME)
            volume_ok = False

    default = pactl("get-default-sink")
    if default.returncode != 0:
        raise BluetoothNotReady(f"Could not read the default audio output: {(default.stderr or '').strip()}")
    if (default.stdout or "").strip() != sink:
        result = pactl("set-default-sink", sink)
        if result.returncode != 0:
            raise BluetoothNotReady(f"Could not route audio to {sink}: {(result.stderr or '').strip()}")
        logger.info("Default audio output is now %s.", sink)

    inputs = pactl("list", "short", "sink-inputs")
    if inputs.returncode != 0:
        raise BluetoothNotReady(f"Could not list playback streams: {(inputs.stderr or '').strip()}")
    for line in (inputs.stdout or "").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] != sink_id:
            result = pactl("move-sink-input", fields[0], sink)
            if result.returncode != 0:
                raise BluetoothNotReady(
                    f"Could not move playback stream {fields[0]} to {sink}: {(result.stderr or '').strip()}"
                )
            logger.info("Moved playback stream %s to %s.", fields[0], sink)
    return sink, volume_ok


def prepare_speaker(
    runner=subprocess.run,
    sleep=time.sleep,
    connect_attempts: int = CONNECT_ATTEMPTS,
    desktop: Optional[bool] = None,
    user: Optional[str] = None,
) -> Optional[str]:
    """Connect the speaker if needed and make it the audio output.

    Returns the ALSA device (Lite) or PipeWire sink (Desktop), or None when no
    speaker is configured. Raises BluetoothNotReady when it cannot play.
    """
    mac = speaker_mac()
    if not mac:
        return None
    desktop = bool(settings.DESKTOP_AUDIO_USER) if desktop is None else desktop
    with _lock:
        connected_now = ensure_speaker_connected(runner=runner, sleep=sleep, attempts=connect_attempts)
        set_volume = connected_now or not _output_volume_set[0]
        try:
            if desktop:
                output, volume_ok = _route_pipewire(mac, runner, sleep, set_volume, user)
            else:
                output, volume_ok = _prepare_bluealsa(mac, runner, sleep, set_volume)
        except (OSError, subprocess.SubprocessError) as error:
            raise BluetoothNotReady(f"Could not prepare audio output for speaker {mac}: {error}") from error
        if set_volume and volume_ok:
            _output_volume_set[0] = True
        return output
