import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env", override=False)


def parse_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise ValueError(f"APP_PORT must be an integer between 1 and 65535; got {value!r}") from error

    if not 1 <= port <= 65535:
        raise ValueError(f"APP_PORT must be between 1 and 65535; got {port}")
    return port


class Settings:
    APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT = parse_port(os.getenv("APP_PORT", "5000"))
    DATABASE_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "data" / "raspi_spotify_nfc.db"))
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
    SPOTIFY_REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback")
    SPOTIFY_REFRESH_TOKEN = os.getenv("SPOTIFY_REFRESH_TOKEN", "")


settings = Settings()
