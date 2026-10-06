from __future__ import annotations

import re
from typing import Any, Optional

try:
    from spotipy import Spotify, SpotifyException
    from spotipy.oauth2 import SpotifyOAuth
except ModuleNotFoundError:  # pragma: no cover - exercised when the optional dependency is absent.
    Spotify = None
    SpotifyOAuth = None
    SpotifyException = None

from .config import settings

SPOTIFY_URI_PATTERN = re.compile(r"^spotify:(track|playlist|album):([A-Za-z0-9]+)$")
SUPPORTED_ACTIONS = frozenset({"action:play_pause", "action:next", "action:next_track"})
_fake_spotify_client: Optional["FakeSpotifyClient"] = None


class FakeSpotifyClient:
    def __init__(self):
        self.is_playing = False
        self.current_uri = "spotify:track:demo"
        self.position_ms = 0

    def start_playback(self, uris=None, context_uri=None, position_ms=0):
        if uris:
            self.current_uri = uris[0]
        elif context_uri:
            self.current_uri = context_uri
        else:
            self.current_uri = "spotify:track:demo"
        self.position_ms = position_ms
        self.is_playing = True
        return {
            "status": "ok",
            "mode": "fake",
            "uri": self.current_uri,
            "position_ms": self.position_ms,
        }

    def pause_playback(self):
        self.is_playing = False
        return {"status": "ok", "mode": "fake", "paused": True}

    def next_track(self):
        self.is_playing = True
        return {"status": "ok", "mode": "fake", "action": "next"}

    def current_playback(self):
        return {
            "is_playing": self.is_playing,
            "item": {"uri": self.current_uri},
            "position_ms": self.position_ms,
            "mode": "fake",
        }


def is_live_spotify_configured() -> bool:
    return bool(settings.SPOTIFY_CLIENT_ID and settings.SPOTIFY_CLIENT_SECRET and settings.SPOTIFY_REFRESH_TOKEN)


def get_tag_type(value: str) -> Optional[str]:
    if SPOTIFY_URI_PATTERN.fullmatch(value):
        return "content"
    if value in SUPPORTED_ACTIONS:
        return "action"
    return None


def build_spotify_client() -> Any:
    global _fake_spotify_client

    if not is_live_spotify_configured():
        if _fake_spotify_client is None:
            _fake_spotify_client = FakeSpotifyClient()
        return _fake_spotify_client

    if Spotify is None or SpotifyOAuth is None:
        raise RuntimeError(
            "Spotify support requires the 'spotipy' dependency. "
            "Install it with 'pip install -r requirements.txt' or 'pip install -r requirements-pi.txt'."
        )

    auth_manager = SpotifyOAuth(
        client_id=settings.SPOTIFY_CLIENT_ID,
        client_secret=settings.SPOTIFY_CLIENT_SECRET,
        redirect_uri=settings.SPOTIFY_REDIRECT_URI,
        scope="user-modify-playback-state user-read-playback-state",
        cache_path=None,
    )
    auth_manager.refresh_access_token(settings.SPOTIFY_REFRESH_TOKEN)
    return Spotify(auth_manager=auth_manager)


def _spotify_error_response(error: "SpotifyException") -> dict:
    reason = getattr(error, "reason", None)
    if reason == "NO_ACTIVE_DEVICE":
        message = (
            "No active Spotify device found. Open Spotify on a device and start "
            "playback there once, then try again."
        )
    else:
        message = str(error)
    return {
        "status": "error",
        "error": "spotify_api_error",
        "http_status": getattr(error, "http_status", None),
        "reason": reason,
        "message": message,
    }


def play_content(uri: str, position_ms: int = 0) -> dict:
    match = SPOTIFY_URI_PATTERN.fullmatch(uri)
    if not match:
        return {"status": "unsupported_uri", "uri": uri}
    if isinstance(position_ms, bool) or not isinstance(position_ms, int) or position_ms < 0:
        return {"status": "invalid_position", "position_ms": position_ms}

    spotify = build_spotify_client()
    try:
        if match.group(1) == "track":
            return spotify.start_playback(uris=[uri], position_ms=position_ms)
        if match.group(1) in {"playlist", "album"}:
            return spotify.start_playback(context_uri=uri, position_ms=position_ms)
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        if SpotifyException is not None and isinstance(error, SpotifyException):
            return _spotify_error_response(error)
        raise
    raise AssertionError("Validated Spotify URI had an unsupported resource type")


def toggle_playback() -> dict:
    spotify = build_spotify_client()
    try:
        current = spotify.current_playback()
        if not current or not current.get("is_playing"):
            return spotify.start_playback()
        return spotify.pause_playback()
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        if SpotifyException is not None and isinstance(error, SpotifyException):
            return _spotify_error_response(error)
        raise


def next_track() -> dict:
    spotify = build_spotify_client()
    try:
        return spotify.next_track()
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        if SpotifyException is not None and isinstance(error, SpotifyException):
            return _spotify_error_response(error)
        raise


def get_current_playback() -> Optional[dict]:
    spotify = build_spotify_client()
    return spotify.current_playback()


def dispatch_tag_value(value: str) -> dict:
    if value.startswith("spotify:"):
        return play_content(value)
    if value == "action:play_pause":
        return toggle_playback()
    if value in {"action:next", "action:next_track"}:
        return next_track()
    return {"status": "unsupported_action", "value": value}
