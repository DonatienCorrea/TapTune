import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .bluetooth import BluetoothNotReady, speaker_mac
from .config import BASE_DIR, settings
from .spotify_service import is_live_spotify_configured

SERVICE_NAME = "raspi-spotify-nfc.service"
ENV_PATH = BASE_DIR / ".env"
MAC_PATTERN = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

# Keys the setup UI may write; anything else in .env is preserved untouched.
EDITABLE_KEYS = (
    "BLUETOOTH_SPEAKER_MAC",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REFRESH_TOKEN",
    "SPOTIFY_DEVICE_NAME",
)
_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_PLAIN_VALUE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]*$")


class InvalidSetting(ValueError):
    pass


def validate_updates(updates: Dict[str, str]) -> Dict[str, str]:
    clean = {}
    for key, value in updates.items():
        if key not in EDITABLE_KEYS:
            raise InvalidSetting(key)
        if not isinstance(value, str):
            raise InvalidSetting(key)
        value = value.strip()
        if len(value) > 500 or any(c in value for c in '\r\n\0"\\$`'):
            raise InvalidSetting(key)
        if key == "BLUETOOTH_SPEAKER_MAC" and value and not MAC_PATTERN.fullmatch(value):
            raise InvalidSetting(key)
        clean[key] = value.upper() if key == "BLUETOOTH_SPEAKER_MAC" else value
    return clean


def _format_line(key: str, value: str) -> str:
    return f"{key}={value}" if _PLAIN_VALUE.fullmatch(value) else f'{key}="{value}"'


def write_env(updates: Dict[str, str], path: Path = ENV_PATH) -> None:
    """Atomically update known keys in a .env file, keeping every other line."""
    updates = validate_updates(updates)
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(updates)
    output = []
    for line in lines:
        match = _ENV_LINE.match(line)
        key = match.group(1) if match else None
        if key in pending:
            output.append(_format_line(key, pending.pop(key)))
        elif key in updates:
            continue  # drop duplicate definitions of an updated key
        else:
            output.append(line)
    output.extend(_format_line(key, value) for key, value in pending.items())

    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write("\n".join(output) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def restart_service(runner: Callable = subprocess.Popen) -> bool:
    """Restart after the HTTP response has been sent; best effort."""
    try:
        runner(
            ["sh", "-c", f"sleep 1; sudo -n systemctl restart {SERVICE_NAME}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
        )
        return True
    except OSError:
        return False


def _run(args: List[str], runner: Callable) -> Optional[str]:
    try:
        result = runner(args, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def wifi_status(runner: Callable = subprocess.run) -> dict:
    output = _run(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "device"], runner)
    if output is None:
        return {"id": "wifi", "state": "todo", "reason": "unavailable"}
    wired = False
    for line in output.splitlines():
        kind, _, rest = line.partition(":")
        state, _, name = rest.partition(":")
        if state != "connected":
            continue
        if kind == "wifi":
            return {"id": "wifi", "state": "done", "reason": "connected", "detail": name}
        if kind == "ethernet":
            wired = True
    if wired:
        return {"id": "wifi", "state": "done", "reason": "wired"}
    return {"id": "wifi", "state": "todo", "reason": "disconnected"}


def bluetooth_status(runner: Callable = subprocess.run) -> dict:
    try:
        mac = speaker_mac()
    except BluetoothNotReady:
        return {"id": "bluetooth", "state": "attention", "reason": "invalid_mac"}
    if not mac:
        return {"id": "bluetooth", "state": "todo", "reason": "not_configured"}
    output = _run(["bluetoothctl", "info", mac], runner)
    if output is None:
        return {"id": "bluetooth", "state": "attention", "reason": "not_paired", "detail": mac}
    if any(line.strip() == "Connected: yes" for line in output.splitlines()):
        return {"id": "bluetooth", "state": "done", "reason": "connected", "detail": mac}
    return {"id": "bluetooth", "state": "attention", "reason": "not_connected", "detail": mac}


def spotify_status() -> dict:
    if is_live_spotify_configured():
        return {"id": "spotify", "state": "done", "reason": "configured"}
    return {"id": "spotify", "state": "todo", "reason": "not_configured"}


def setup_steps() -> List[dict]:
    return [wifi_status(), bluetooth_status(), spotify_status()]


def setup_complete(steps: Optional[List[dict]] = None) -> bool:
    if settings.SETUP_SKIP:
        return True
    return all(step["state"] == "done" for step in (steps if steps is not None else setup_steps()))
