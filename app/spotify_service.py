from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Optional

try:
    from spotipy import Spotify, SpotifyException
    from spotipy.cache_handler import MemoryCacheHandler
    from spotipy.oauth2 import SpotifyOAuth, SpotifyOauthError
except ModuleNotFoundError:  # pragma: no cover - exercised when the optional dependency is absent.
    Spotify = None
    SpotifyOAuth = None
    SpotifyException = None
    SpotifyOauthError = None
    MemoryCacheHandler = None

try:
    from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout
    NETWORK_ERRORS: tuple = (RequestsConnectionError, RequestsTimeout)
except ModuleNotFoundError:  # pragma: no cover - requests ships with spotipy.
    NETWORK_ERRORS = ()

from .config import settings
from .bluetooth import BluetoothNotReady, prepare_speaker

SPOTIFY_URI_PATTERN = re.compile(r"^spotify:(track|playlist|album):([A-Za-z0-9]+)$")
SUPPORTED_ACTIONS = frozenset({
    "action:play_pause", "action:next", "action:next_track",
    "action:volume_up", "action:volume_down",
})
_fake_spotify_client: Optional["FakeSpotifyClient"] = None
_volume_lock = threading.Lock()
logger = logging.getLogger(__name__)

SPOTIFY_REQUEST_TIMEOUT_SECONDS = 10
TOKEN_REFRESH_ATTEMPTS = 3
# Spotifyd/Raspotify can briefly drop out of Spotify's device list.
DEVICE_LOOKUP_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0
# Spotify's playback state lags a few seconds behind commands, so trust what
# TapTune just did over a stale report for this long.
STATE_MEMORY_SECONDS = 30.0
PLAYBACK_MEMORY_SECONDS = 10.0
_clock = time.monotonic
# device id -> (volume TapTune set, stale values Spotify may still report, when)
_volume_memory: dict = {}
# (is_playing TapTune set, when)
_playback_memory: Optional[tuple] = None


class FakeSpotifyClient:
    def __init__(self):
        self.is_playing = False
        self.current_uri = "spotify:track:demo"
        self.position_ms = 0
        self.device_id = None
        self.volume_percent = settings.SPOTIFY_INITIAL_VOLUME

    def volume(self, volume_percent, device_id=None):
        self.volume_percent = volume_percent
        return {"status": "ok", "mode": "fake", "volume_percent": volume_percent}

    def _device(self):
        return {
            "id": "fake-device",
            "name": settings.SPOTIFY_DEVICE_NAME or "TapTune",
            "is_active": self.device_id is not None,
            "volume_percent": self.volume_percent,
            "supports_volume": True,
        }

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
                self._device()
            ]
        }

    def current_playback(self):
        return {
            "is_playing": self.is_playing,
            "item": {"uri": self.current_uri},
            "position_ms": self.position_ms,
            "mode": "fake",
            "device": self._device(),
        }


class SpeakerNotReady(Exception):
    """No device is active and the Pi's own Spotify Connect receiver is not visible."""


def _is_transient_auth_error(error: Exception) -> bool:
    if NETWORK_ERRORS and isinstance(error, NETWORK_ERRORS):
        return True
    if SpotifyOauthError is not None and isinstance(error, SpotifyOauthError):
        # invalid_grant/invalid_client mean bad credentials: retrying cannot help.
        return getattr(error, "error", None) not in {"invalid_grant", "invalid_client"}
    return False


def _refresh_token_with_retries(auth_manager: Any, sleep=time.sleep) -> None:
    for attempt in range(1, TOKEN_REFRESH_ATTEMPTS + 1):
        try:
            auth_manager.refresh_access_token(settings.SPOTIFY_REFRESH_TOKEN)
            return
        except Exception as error:  # noqa: BLE001 - filtered by _is_transient_auth_error.
            if attempt == TOKEN_REFRESH_ATTEMPTS or not _is_transient_auth_error(error):
                raise
            logger.warning(
                "Spotify token refresh failed (attempt %d/%d): %s; retrying.",
                attempt, TOKEN_REFRESH_ATTEMPTS, error,
            )
            sleep(RETRY_DELAY_SECONDS * attempt)


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

    if Spotify is None or SpotifyOAuth is None or MemoryCacheHandler is None:
        raise RuntimeError(
            "Spotify support requires the 'spotipy' dependency. "
            "Install it with 'pip install -r requirements.txt'."
        )

    auth_manager = SpotifyOAuth(
        client_id=settings.SPOTIFY_CLIENT_ID,
        client_secret=settings.SPOTIFY_CLIENT_SECRET,
        redirect_uri=settings.SPOTIFY_REDIRECT_URI,
        scope="user-modify-playback-state user-read-playback-state",
        cache_handler=MemoryCacheHandler(),
        requests_timeout=SPOTIFY_REQUEST_TIMEOUT_SECONDS,
    )
    _refresh_token_with_retries(auth_manager)
    return Spotify(auth_manager=auth_manager, requests_timeout=SPOTIFY_REQUEST_TIMEOUT_SECONDS)


def find_device(spotify: Any, name: Optional[str] = None) -> Optional[dict]:
    """Return the Connect device called ``name`` (case-insensitive)."""
    name = (settings.SPOTIFY_DEVICE_NAME if name is None else name).strip()
    if not name:
        return None
    response = spotify.devices() or {}
    for device in response.get("devices") or []:
        if (device.get("name") or "").strip().casefold() == name.casefold() and device.get("id"):
            return device
    return None


def find_device_id(spotify: Any, name: Optional[str] = None) -> Optional[str]:
    device = find_device(spotify, name)
    return device["id"] if device else None


def find_device_with_retries(spotify: Any, sleep=time.sleep) -> Optional[dict]:
    for attempt in range(DEVICE_LOOKUP_ATTEMPTS):
        device = find_device(spotify)
        if device is not None:
            return device
        if attempt < DEVICE_LOOKUP_ATTEMPTS - 1:
            sleep(RETRY_DELAY_SECONDS)
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
    device = find_device_with_retries(spotify)
    if device is None:
        raise SpeakerNotReady(settings.SPOTIFY_DEVICE_NAME)
    return device["id"]


def _speaker_not_ready_response() -> dict:
    return {
        "status": "error",
        "error": "speaker_not_ready",
        "reason": "SPEAKER_NOT_READY",
        "device_name": settings.SPOTIFY_DEVICE_NAME,
        "message": (
            f"The '{settings.SPOTIFY_DEVICE_NAME}' speaker is not ready yet. Check that the "
            "Raspberry Pi is connected to the network and that Spotifyd or Raspotify is running, then try again."
        ),
    }


def _handle_error(error: Exception) -> dict:
    try:
        response = _error_response(error)
    except Exception:
        logger.exception("Unexpected Spotify playback error.")
        raise
    logger.warning(
        "Playback command failed (%s): %s", response.get("reason") or response["error"], response["message"],
        exc_info=response["error"] in {"network_error", "spotify_auth_error"},
    )
    return response


def _error_response(error: Exception) -> dict:
    if isinstance(error, BluetoothNotReady):
        return {"status": "error", "error": "bluetooth_not_ready", "message": str(error)}
    if isinstance(error, SpeakerNotReady):
        return _speaker_not_ready_response()
    if SpotifyException is not None and isinstance(error, SpotifyException):
        return _spotify_error_response(error)
    if SpotifyOauthError is not None and isinstance(error, SpotifyOauthError):
        return {
            "status": "error",
            "error": "spotify_auth_error",
            "message": f"Spotify authorization failed: {error}. Check the Spotify values in .env.",
        }
    if NETWORK_ERRORS and isinstance(error, NETWORK_ERRORS):
        return {
            "status": "error",
            "error": "network_error",
            "message": "Spotify could not be reached. Check the Raspberry Pi's network connection and tap again.",
        }
    raise error


def _spotify_error_response(error: "SpotifyException") -> dict:
    reason = getattr(error, "reason", None)
    if reason == "NO_ACTIVE_DEVICE":
        message = (
            "No active Spotify device found. Check that the TapTune speaker "
            "(Spotifyd or Raspotify) is running, or open Spotify on a device and start playback there once."
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

    try:
        spotify = build_spotify_client()
        current = spotify.current_playback()
        _prepare_local_speaker(current)
        device_id = resolve_target_device(spotify, current)
        if match.group(1) == "track":
            return spotify.start_playback(device_id=device_id, uris=[uri], position_ms=position_ms)
        if match.group(1) in {"playlist", "album"}:
            return spotify.start_playback(device_id=device_id, context_uri=uri, position_ms=position_ms)
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        return _handle_error(error)
    raise AssertionError("Validated Spotify URI had an unsupported resource type")


def reset_state_memory() -> None:
    global _playback_memory
    _playback_memory = None
    _volume_memory.clear()


def _remember_playback(is_playing: bool) -> None:
    global _playback_memory
    _playback_memory = (is_playing, _clock())


def _believed_playing(current: Optional[dict]) -> bool:
    reported = bool(current and current.get("is_playing"))
    if current and _playback_memory is not None:
        remembered, when = _playback_memory
        if _clock() - when < PLAYBACK_MEMORY_SECONDS and remembered != reported:
            logger.info(
                "Spotify still reports %s; using TapTune's last command (%s) as it was sent %.0f s ago.",
                "playing" if reported else "paused", "play" if remembered else "pause", _clock() - when,
            )
            return remembered
    return reported


def _resume(spotify: Any, current: Optional[dict], device_id: Optional[str]) -> dict:
    current_device = ((current or {}).get("device") or {}).get("id")
    target = device_id or current_device
    if device_id is not None or current is None:
        # Nothing is active: resume the account's last playback on the Pi.
        if target is not None:
            logger.info("Resuming playback by transferring it to device %s.", target)
            return spotify.transfer_playback(target, force_play=True)
        return spotify.start_playback()
    try:
        if target is None:
            return spotify.start_playback()
        return spotify.start_playback(device_id=target)
    except Exception as error:  # noqa: BLE001 - only Spotify's "device gone" errors are retried.
        status = getattr(error, "http_status", None)
        if SpotifyException is None or not isinstance(error, SpotifyException) or status not in {403, 404}:
            raise
        logger.warning("Spotify refused to resume on device %s (%s); transferring playback to the Pi.", target, error)
        if not settings.SPOTIFY_DEVICE_NAME:
            raise
        device = find_device_with_retries(spotify)
        if device is None:
            raise SpeakerNotReady(settings.SPOTIFY_DEVICE_NAME) from error
        return spotify.transfer_playback(device["id"], force_play=True)


def toggle_playback() -> dict:
    try:
        spotify = build_spotify_client()
        current = spotify.current_playback()
        if _believed_playing(current):
            logger.info("Play/pause: pausing.")
            result = spotify.pause_playback()
            _remember_playback(False)
            return result
        logger.info("Play/pause: resuming.")
        _prepare_local_speaker(current)
        device_id = resolve_target_device(spotify, current)
        result = _resume(spotify, current, device_id)
        _remember_playback(True)
        return result
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        return _handle_error(error)


def next_track() -> dict:
    try:
        spotify = build_spotify_client()
        current = spotify.current_playback()
        device_id = resolve_target_device(spotify, current)
        return spotify.next_track(device_id=device_id)
    except Exception as error:  # noqa: BLE001 - translate spotipy/network errors into a dict response.
        return _handle_error(error)


def get_current_playback() -> Optional[dict]:
    spotify = build_spotify_client()
    return spotify.current_playback()


def _prepare_local_speaker(current: Optional[dict]) -> None:
    """Before starting/resuming music on the Pi's receiver, connect and route its speaker.

    Pause, next and volume never reconnect: a speaker that went to sleep while
    nothing played is only woken when music should come out of it.
    """
    if not is_live_spotify_configured() or not settings.BLUETOOTH_SPEAKER_MAC:
        return
    device = (current or {}).get("device") or {}
    local_name = settings.SPOTIFY_DEVICE_NAME.casefold()
    if local_name and (not current or (device.get("name") or "").strip().casefold() == local_name):
        prepare_speaker()


def _believed_volume(device_id: str, reported: int) -> int:
    memory = _volume_memory.get(device_id)
    if memory is None:
        return reported
    remembered, stale_values, when = memory
    if _clock() - when < STATE_MEMORY_SECONDS and reported != remembered and reported in stale_values:
        logger.info(
            "Spotify still reports %d%% volume; using TapTune's last setting %d%%.", reported, remembered,
        )
        return remembered
    return reported


def _remember_volume(device_id: str, base: int, new_volume: int) -> None:
    memory = _volume_memory.get(device_id)
    stale_values = set()
    if memory is not None and _clock() - memory[2] < STATE_MEMORY_SECONDS and base == memory[0]:
        stale_values = set(memory[1])
    stale_values.update({base, new_volume})
    _volume_memory[device_id] = (new_volume, frozenset(stale_values), _clock())


def change_volume(step: int) -> dict:
    try:
        spotify = build_spotify_client()
        with _volume_lock:
            current = spotify.current_playback()
            device = current.get("device") if current else None
            if not device and not current:
                device = find_device_with_retries(spotify)
                if device is None:
                    raise SpeakerNotReady(settings.SPOTIFY_DEVICE_NAME)
            volume = device.get("volume_percent") if device else None
            if (
                not device or not device.get("id")
                or device.get("supports_volume") is False
                or device.get("is_restricted") is True
                or isinstance(volume, bool) or not isinstance(volume, int)
                or not 0 <= volume <= 100
            ):
                return {
                    "status": "error",
                    "error": "volume_unavailable",
                    "message": "Spotify cannot read or change this device's volume. Select a receiver that supports volume control.",
                }
            volume = _believed_volume(device["id"], volume)
            new_volume = max(0, min(100, volume + step))
            result = spotify.volume(new_volume, device_id=device["id"])
            _remember_volume(device["id"], volume, new_volume)
            logger.info("Volume %d%% -> %d%% on device %s.", volume, new_volume, device.get("name") or device["id"])
            return result if isinstance(result, dict) else {"status": "ok", "volume_percent": new_volume}
    except Exception as error:  # noqa: BLE001 - use the same API error translation as playback.
        return _handle_error(error)


def dispatch_tag_value(value: str) -> dict:
    if value.startswith("spotify:"):
        return play_content(value)
    if value == "action:play_pause":
        return toggle_playback()
    if value in {"action:next", "action:next_track"}:
        return next_track()
    if value in {"action:volume_up", "action:volume_down"}:
        return change_volume(10 if value == "action:volume_up" else -10)
    return {"status": "unsupported_action", "value": value}
