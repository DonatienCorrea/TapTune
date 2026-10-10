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
        self.device_id = None

    def start_playback(self, device_id=None, uris=None, context_uri=None, position_ms=0):
        if uris:
            self.current_uri = uris[0]
        elif context_uri:
            self.current_uri = context_uri
        else:
            self.current_uri = "spotify:track:demo"
        self.position_ms = position_ms
        self.is_playing = True
        self.device_id = device_id
        return {
            "status": "ok",
            "mode": "fake",
            "uri": self.current_uri,
            "position_ms": self.position_ms,
        }

    def pause_playback(self, device_id=None):
        self.is_playing = False
        return {"status": "ok", "mode": "fake", "paused": True}

    def next_track(self, device_id=None):
        self.is_playing = True
        return {"status": "ok", "mode": "fake", "action": "next"}

    def transfer_playback(self, device_id, force_play=True):
        self.device_id = device_id
        self.is_playing = bool(force_play)
        return {"status": "ok", "mode": "fake", "device_id": device_id}

    def devices(self):
        return {
            "devices": [
                {
                    "id": "fake-device",
                    "name": settings.SPOTIFY_DEVICE_NAME or "TapTune",
                    "is_active": self.device_id is not None,
                }
            ]
        }

    def current_playback(self):
        return {
            "is_playing": self.is_playing,
            "item": {"uri": self.current_uri},
            "position_ms": self.position_ms,
            "mode": "fake",
        }


class SpeakerNotReady(Exception):
    """No device is active and the Pi's own Spotify Connect receiver is not visible."""


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


def find_device_id(spotify: Any, name: Optional[str] = None) -> Optional[str]:
    """Return the Web API id of the Connect device called ``name`` (case-insensitive)."""
    name = (settings.SPOTIFY_DEVICE_NAME if name is None else name).strip()
    if not name:
        return None
    response = spotify.devices() or {}
    for device in response.get("devices") or []:
        if (device.get("name") or "").strip().casefold() == name.casefold() and device.get("id"):
            return device["id"]
    return None


def resolve_target_device(spotify: Any, current: Optional[dict]) -> Optional[str]:
    """Keep playback where it is active; otherwise target the Pi's own receiver.

    Returns ``None`` to let Spotify use the active device, a device id for the Pi,
    or raises ``SpeakerNotReady`` when nothing can play.
    """
    if current:
        return None
    if not settings.SPOTIFY_DEVICE_NAME:
        # Pi targeting disabled: let Spotify report NO_ACTIVE_DEVICE as before.
        return None
    device_id = find_device_id(spotify)
    if device_id is None:
        raise SpeakerNotReady(settings.SPOTIFY_DEVICE_NAME)
    return device_id


def _speaker_not_ready_response() -> dict:
    return {
        "status": "error",
        "error": "speaker_not_ready",
        "reason": "SPEAKER_NOT_READY",
        "device_name": settings.SPOTIFY_DEVICE_NAME,
        "message": (
            f"The '{settings.SPOTIFY_DEVICE_NAME}' speaker is not ready yet. Check that the "
            "Raspberry Pi is connected to the network and that raspotify is running, then try again."
        ),
    }


def _handle_error(error: Exception) -> dict:
    if isinstance(error, SpeakerNotReady):
        return _speaker_not_ready_response()
    if SpotifyException is not None and isinstance(error, SpotifyException):
        return _spotify_error_response(error)
    raise error


def _spotify_error_response(error: "SpotifyException") -> dict:
    reason = getattr(error, "reason", None)
    if reason == "NO_ACTIVE_DEVICE":
        message = (
            "No active Spotify device found. Check that the TapTune speaker "
            "(raspotify) is running, or open Spotify on a device and start playback there once."
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
        device_id = resolve_target_device(spotify, spotify.current_playback())
        if match.group(1) == "track":
            return spotify.start_playback(device_id=device_id, uris=[uri], position_ms=position_ms)
        if match.group(1) in {"playlist", "album"}:
            return spotify.start_playback(device_id=device_id, context_uri=uri, position_ms=position_ms)
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        return _handle_error(error)
    raise AssertionError("Validated Spotify URI had an unsupported resource type")


def toggle_playback() -> dict:
    spotify = build_spotify_client()
    try:
        current = spotify.current_playback()
        if current and current.get("is_playing"):
            return spotify.pause_playback()
        device_id = resolve_target_device(spotify, current)
        if device_id is not None:
            # Nothing is active: resume the account's last playback on the Pi.
            return spotify.transfer_playback(device_id, force_play=True)
        return spotify.start_playback()
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        return _handle_error(error)


def next_track() -> dict:
    spotify = build_spotify_client()
    try:
        device_id = resolve_target_device(spotify, spotify.current_playback())
        return spotify.next_track(device_id=device_id)
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        return _handle_error(error)


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
