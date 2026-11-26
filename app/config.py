import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env(path: Path) -> None:
    """Read simple KEY=value lines into os.environ without overriding real variables."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    for line in lines:
        line = line.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


load_env(BASE_DIR / ".env")


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError(f"APP_PORT must be an integer between 1 and 65535; got {value!r}") from error

    if not 1 <= port <= 65535:
        raise ValueError(f"APP_PORT must be between 1 and 65535; got {port}")
    return port


def parse_bool(value: str, name: str = "NFC_READER_ENABLED") -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(
        f"{name} must be one of true/false, yes/no, on/off, or 1/0; "
        f"got {value!r}"
    )


def parse_volume(value: str) -> int:
    try:
        volume = int(value)
    except ValueError as error:
        raise ValueError(f"SPOTIFY_INITIAL_VOLUME must be an integer from 0 to 100; got {value!r}") from error
    if not 0 <= volume <= 100:
        raise ValueError(f"SPOTIFY_INITIAL_VOLUME must be from 0 to 100; got {volume}")
    return volume


class Settings:
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT = parse_port(os.getenv("APP_PORT", "5000"))
    TAPTUNE_HTTP_PORT_80 = parse_bool(os.getenv("TAPTUNE_HTTP_PORT_80", "false"), "TAPTUNE_HTTP_PORT_80")
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "raspi_spotify_nfc.db"))
    NFC_READER_ENABLED = parse_bool(os.getenv("NFC_READER_ENABLED", "false"))
    # Name of the go-librespot Spotify Connect receiver running on the Pi.
    SPOTIFY_DEVICE_NAME = os.getenv("SPOTIFY_DEVICE_NAME", "TapTune").strip()
    LIBRESPOT_API_URL = os.getenv("LIBRESPOT_API_URL", "http://127.0.0.1:3678").strip().rstrip("/")
    SPOTIFY_INITIAL_VOLUME = parse_volume(os.getenv("SPOTIFY_INITIAL_VOLUME", "10"))
    BLUETOOTH_SPEAKER_MAC = os.getenv("BLUETOOTH_SPEAKER_MAC", "").strip()
    # Set by install-service.sh in the systemd unit (not in .env): the user whose
    # PipeWire session plays go-librespot and the ready sound.
    DESKTOP_AUDIO_USER = os.getenv("DESKTOP_AUDIO_USER", "").strip()
    # Set to true to disable the first-run redirect from / to /setup.
    SETUP_SKIP = parse_bool(os.getenv("SETUP_SKIP", "false"), "SETUP_SKIP")
    TAPTUNE_WIFI_SETUP = parse_bool(os.getenv("TAPTUNE_WIFI_SETUP", "false"), "TAPTUNE_WIFI_SETUP")
    READY_SOUND_ENABLED = parse_bool(os.getenv("READY_SOUND_ENABLED", "true"), "READY_SOUND_ENABLED")


settings = Settings()
