"""Check the Pi's Bluetooth link before dispatching a local playback command."""

import logging
import re
import subprocess
import time

from .config import settings

logger = logging.getLogger(__name__)


class BluetoothNotReady(Exception):
    pass


def ensure_speaker_connected(runner=subprocess.run, sleep=time.sleep) -> None:
    mac = settings.BLUETOOTH_SPEAKER_MAC
    if not mac:
        return
    if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
        raise BluetoothNotReady("BLUETOOTH_SPEAKER_MAC must be an address like AA:BB:CC:DD:EE:FF.")

    def connected():
        result = runner(["bluetoothctl", "info", mac], capture_output=True, text=True, timeout=5)
        return result.returncode == 0 and any(
            line.strip() == "Connected: yes" for line in result.stdout.splitlines()
        )

    try:
        if connected():
            return
        logger.info("Bluetooth speaker %s disconnected; reconnecting before tag dispatch.", mac)
        result = runner(
            ["bluetoothctl", "--timeout", "10", "connect", mac],
            capture_output=True, text=True, timeout=12,
        )
        # BlueZ can report InProgress if the background reconnect service got there first.
        for attempt in range(6):
            if connected():
                return
            if attempt < 5:
                sleep(1)
        detail = (result.stderr or result.stdout).strip()
        raise BluetoothNotReady(
            f"Bluetooth speaker {mac} is disconnected. Turn it on and tap again."
            + (f" Bluetooth reported: {detail}" if detail else "")
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BluetoothNotReady(f"Could not check/reconnect Bluetooth speaker {mac}: {error}") from error
