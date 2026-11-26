"""Find, pair and choose the Bluetooth speaker from the setup page.

Uses `bluetoothctl` as the TapTune service user (root). Trusting the speaker lets BlueZ accept it again after a reboot; TapTune's
existing boot connection (app.readiness) then connects it by its saved MAC.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import bluetooth
from . import setup as setup_state
from .config import settings

logger = logging.getLogger(__name__)

SCAN_SECONDS = 10
# A device found by a scan is forgotten by BlueZ ~30 s after the scan ends.
RESCAN_SECONDS = 8
PAIR_TIMEOUT_SECONDS = 25
MAX_DEVICES = 40
AUDIO_SINK_UUID = "0000110b"
_DEVICE_LINE = re.compile(r"^Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2})(?: (.*))?$")

_lock = threading.Lock()


class PairingBusy(Exception):
    pass


class PairingError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(code)
        self.code = code
        self.detail = detail


def normalize_mac(value) -> str:
    mac = value.strip().upper() if isinstance(value, str) else ""
    if not bluetooth.MAC_PATTERN.fullmatch(mac):
        raise PairingError("invalid_mac")
    return mac


def _bt(args: List[str], runner: Callable, timeout: float = 5):
    return runner(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout)


def _output(result) -> str:
    return ((result.stderr or "") + (result.stdout or "")).strip()


def device_info(mac: str, runner: Callable) -> Optional[Dict]:
    result = _bt(["info", mac], runner)
    if result.returncode != 0:
        return None
    info: Dict = {"UUIDs": []}
    for line in (result.stdout or "").splitlines():
        key, sep, value = line.strip().partition(": ")
        if not sep:
            continue
        if key == "UUID":
            info["UUIDs"].append(value)
        else:
            info.setdefault(key, value.strip())
    return info


def _flag(info: Optional[Dict], key: str) -> bool:
    return bool(info) and info.get(key) == "yes"


def is_audio_output(info: Dict) -> bool:
    if info.get("Icon", "").startswith("audio"):
        return True
    return any("audio sink" in uuid.casefold() or AUDIO_SINK_UUID in uuid.casefold() for uuid in info["UUIDs"])


def _power_on(runner: Callable) -> None:
    result = _bt(["power", "on"], runner)
    if result.returncode != 0:
        raise PairingError("adapter_unavailable", _output(result))


def _make_bondable(runner: Callable) -> None:
    # Without "pairable on" BlueZ pairs without bonding: the link key is not
    # stored and the speaker reads "Paired: no" as soon as the link drops.
    result = _bt(["pairable", "on"], runner)
    if result.returncode != 0:
        logger.warning("Could not make the Bluetooth adapter pairable: %s", _output(result))


def _scan(runner: Callable, seconds: int) -> None:
    _bt(["--timeout", str(seconds), "scan", "on"], runner, timeout=seconds + 5)


def _locked(function):
    def wrapper(*args, **kwargs):
        if not _lock.acquire(blocking=False):
            raise PairingBusy()
        try:
            return function(*args, **kwargs)
        except (OSError, subprocess.SubprocessError) as error:
            raise PairingError("bluetooth_unavailable", str(error)) from error
        finally:
            _lock.release()
    return wrapper


@_locked
def scan_speakers(runner: Callable = subprocess.run, seconds: int = SCAN_SECONDS) -> List[Dict]:
    """Scan, then list nearby (and already known) named audio outputs."""
    _power_on(runner)
    _scan(runner, seconds)
    result = _bt(["devices"], runner)
    if result.returncode != 0:
        raise PairingError("bluetooth_unavailable", _output(result))
    speakers = []
    for line in (result.stdout or "").splitlines()[:MAX_DEVICES]:
        match = _DEVICE_LINE.match(line.strip())
        if not match:
            continue
        mac = match.group(1)
        info = device_info(mac, runner)
        # Unnamed devices only show their address: not something a user can pick.
        name = (info or {}).get("Alias") or (info or {}).get("Name") or ""
        if not info or not is_audio_output(info) or not name or name.replace("-", ":").upper() == mac:
            continue
        speakers.append({
            "mac": mac, "name": name,
            "paired": _flag(info, "Paired"), "connected": _flag(info, "Connected"),
        })
    speakers.sort(key=lambda speaker: (not speaker["connected"], not speaker["paired"], speaker["name"].casefold()))
    return speakers


@_locked
def pair_speaker(mac: str, runner: Callable = subprocess.run, sleep: Callable = time.sleep) -> Dict:
    """Pair, trust and connect the speaker. Raises PairingError with a UI code."""
    mac = normalize_mac(mac)
    _power_on(runner)
    info = device_info(mac, runner)
    if info is None:
        _scan(runner, RESCAN_SECONDS)
        info = device_info(mac, runner)
        if info is None:
            raise PairingError("not_found")
    # Trust first so BlueZ accepts the speaker's own reconnection right after pairing.
    if not _flag(info, "Trusted"):
        result = _bt(["trust", mac], runner)
        info = device_info(mac, runner)
        if not _flag(info, "Trusted"):
            raise PairingError("trust_failed", _output(result))
    if not _flag(info, "Paired"):
        _make_bondable(runner)
        result = _bt(["--timeout", str(PAIR_TIMEOUT_SECONDS), "pair", mac], runner, timeout=PAIR_TIMEOUT_SECONDS + 5)
        info = device_info(mac, runner)
        if not _flag(info, "Paired"):
            raise PairingError("pair_failed", _output(result))
    if not _flag(info, "Connected"):
        result = _bt(
            ["--timeout", str(bluetooth.CONNECT_TIMEOUT_SECONDS), "connect", mac], runner,
            timeout=bluetooth.CONNECT_TIMEOUT_SECONDS + 2,
        )
        for check in range(bluetooth.LINK_CHECKS):
            info = device_info(mac, runner)
            if _flag(info, "Connected"):
                break
            if check < bluetooth.LINK_CHECKS - 1:
                sleep(1)
        else:
            raise PairingError("connect_failed", _output(result))
    return {"mac": mac, "name": (info or {}).get("Alias") or (info or {}).get("Name") or mac}


def save_speaker(mac: str, env_path: Path = setup_state.ENV_PATH, runner: Callable = subprocess.run) -> None:
    """Save the speaker's MAC in .env and use it now (only BLUETOOTH_SPEAKER_MAC is written)."""
    mac = normalize_mac(mac)
    previous = settings.BLUETOOTH_SPEAKER_MAC.strip().upper()
    setup_state.write_env({"BLUETOOTH_SPEAKER_MAC": mac}, env_path)
    with bluetooth._lock:
        settings.BLUETOOTH_SPEAKER_MAC = mac
        bluetooth._output_volume_set[0] = False
    if previous and previous != mac:
        # The old speaker would otherwise keep the audio link.
        try:
            _bt(["disconnect", previous], runner, timeout=10)
        except (OSError, subprocess.SubprocessError):
            pass
    logger.info("Bluetooth speaker set to %s from the setup page.", mac)
