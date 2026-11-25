"""Play Spotify tags on the Pi's go-librespot receiver through its local API."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Optional

from .config import settings
from .bluetooth import BluetoothNotReady, prepare_speaker
from . import librespot
from .librespot import LibrespotError, LibrespotUnavailable, NotLoggedIn

SPOTIFY_URI_PATTERN = re.compile(r"^spotify:(track|playlist|album|show):([A-Za-z0-9]+)$")
SPOTIFY_EPISODE_URI_PATTERN = re.compile(r"^spotify:episode:[A-Za-z0-9]+$")
SUPPORTED_ACTIONS = frozenset({
    "action:play_pause", "action:next", "action:next_track",
    "action:volume_up", "action:volume_down",
})
WEB_API_URL = "https://api.spotify.com/v1"
WEB_API_TIMEOUT_SECONDS = 10
WEB_API_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0
# Spotify limits Web API calls made with go-librespot's token. Remember the
# limit so nothing calls again during the wait, which only extends it.
DEFAULT_RATE_LIMIT_SECONDS = 30
LATEST_EPISODE_CACHE_SECONDS = 600
_rate_limited_until = 0.0
_latest_episodes: dict = {}
_web_api_lock = threading.Lock()
_volume_lock = threading.Lock()
_sleep = time.sleep
logger = logging.getLogger(__name__)


class RateLimited(Exception):
    def __init__(self, seconds: float):
        super().__init__(f"Spotify asked to wait {int(seconds)} s")
        self.seconds = max(1, int(seconds))


class WebApiError(Exception):
    def __init__(self, status: int, path: str):
        super().__init__(f"Spotify Web API returned HTTP {status} for {path}")
        self.status = status


def rate_limit_remaining() -> float:
    return max(0.0, _rate_limited_until - time.monotonic())


def check_rate_limit() -> None:
    remaining = rate_limit_remaining()
    if remaining > 0:
        raise RateLimited(remaining)


def _start_cooldown(retry_after: str) -> int:
    global _rate_limited_until
    seconds = int(retry_after) if retry_after.isdigit() else DEFAULT_RATE_LIMIT_SECONDS
    with _web_api_lock:
        _rate_limited_until = max(_rate_limited_until, time.monotonic() + seconds)
    logger.warning("Spotify asked to wait %s s before more Web API calls.", seconds)
    return seconds


def clear_web_api_state() -> None:
    global _rate_limited_until
    with _web_api_lock:
        _rate_limited_until = 0.0
        _latest_episodes.clear()


def web_api_get(path: str, opener=urllib.request.urlopen) -> dict:
    """GET a Spotify Web API path with go-librespot's token, retrying network and 5xx errors."""
    check_rate_limit()
    access_token = librespot.token()
    if not access_token:
        raise NotLoggedIn("no Spotify access token from go-librespot")
    request = urllib.request.Request(WEB_API_URL + path, headers={"Authorization": f"Bearer {access_token}"})
    for attempt in range(1, WEB_API_ATTEMPTS + 1):
        try:
            with opener(request, timeout=WEB_API_TIMEOUT_SECONDS) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            if error.code == 429:
                raise RateLimited(_start_cooldown(str((error.headers or {}).get("Retry-After") or ""))) from error
            if error.code < 500 or attempt == WEB_API_ATTEMPTS:
                raise WebApiError(error.code, path) from error
            problem = f"HTTP {error.code}"
        except (urllib.error.URLError, OSError) as error:
            if attempt == WEB_API_ATTEMPTS:
                raise
            problem = str(error)
        logger.info("Spotify Web API %s failed (%s, attempt %d/%d); retrying.", path, problem, attempt, WEB_API_ATTEMPTS)
        _sleep(RETRY_DELAY_SECONDS * attempt)
    raise AssertionError("unreachable")


def get_tag_type(value: str) -> Optional[str]:
    if SPOTIFY_URI_PATTERN.fullmatch(value):
        return "content"
    if value in SUPPORTED_ACTIONS:
        return "action"
    return None


def _latest_episode(page: dict) -> Optional[dict]:
    episodes = []
    for episode in page.get("items") or []:
        if not isinstance(episode, dict) or episode.get("is_playable") is False or episode.get("restrictions"):
            continue
        uri = episode.get("uri")
        if not isinstance(uri, str) or not SPOTIFY_EPISODE_URI_PATTERN.fullmatch(uri):
            continue
        release_date = episode.get("release_date") or ""
        try:
            if not isinstance(release_date, str):
                raise ValueError
            date_key = tuple(int(part) for part in release_date.split("-"))
            if not date_key or len(date_key) > 3 or not 1 <= date_key[0] <= 9999:
                date_key = (0, 0, 0)
        except (TypeError, ValueError):
            date_key = (0, 0, 0)
        episodes.append((date_key, episode))
    return max(episodes, key=lambda episode: episode[0])[1] if episodes else None


def latest_episode(show_id: str) -> Optional[dict]:
    cached = _latest_episodes.get(show_id)
    if cached and time.monotonic() - cached[0] < LATEST_EPISODE_CACHE_SECONDS:
        return cached[1]
    episode = _latest_episode(web_api_get(f"/shows/{show_id}/episodes?limit=50"))
    with _web_api_lock:
        _latest_episodes[show_id] = (time.monotonic(), episode)
    return episode


def _speaker_not_ready_response() -> dict:
    return {
        "status": "error",
        "error": "speaker_not_ready",
        "reason": "SPEAKER_NOT_READY",
        "device_name": settings.SPOTIFY_DEVICE_NAME,
        "message": (
            f"The '{settings.SPOTIFY_DEVICE_NAME}' speaker is not ready yet. Check that the "
            "Raspberry Pi is connected to the network and that go-librespot is running, then try again."
        ),
    }


def _handle_error(error: Exception) -> dict:
    try:
        response = _error_response(error)
    except Exception:
        logger.exception("Unexpected Spotify playback error.")
        raise
    logger.warning("Playback command failed (%s): %s", response.get("reason") or response["error"], response["message"])
    return response


def _error_response(error: Exception) -> dict:
    if isinstance(error, BluetoothNotReady):
        return {"status": "error", "error": "bluetooth_not_ready", "message": str(error)}
    if isinstance(error, LibrespotUnavailable):
        return _speaker_not_ready_response()
    if isinstance(error, NotLoggedIn):
        return {
            "status": "error",
            "error": "spotify_not_logged_in",
            "message": (
                f"The '{settings.SPOTIFY_DEVICE_NAME}' speaker is not signed in to Spotify. Open Spotify on a "
                f"phone on the same network, tap Devices and choose {settings.SPOTIFY_DEVICE_NAME} once."
            ),
        }
    if isinstance(error, LibrespotError):
        return {
            "status": "error",
            "error": "spotify_api_error",
            "http_status": error.status,
            "message": str(error),
        }
    raise error


def play_content(uri: str, position_ms: int = 0) -> dict:
    match = SPOTIFY_URI_PATTERN.fullmatch(uri)
    if not match:
        return {"status": "unsupported_uri", "uri": uri}
    if isinstance(position_ms, bool) or not isinstance(position_ms, int) or position_ms < 0:
        return {"status": "invalid_position", "position_ms": position_ms}
    return _librespot_call(_librespot_play, match.group(1), match.group(2), uri, position_ms)


def toggle_playback() -> dict:
    return _librespot_call(_librespot_toggle)


def next_track() -> dict:
    return _librespot_call(_librespot_next)


def change_volume(step: int) -> dict:
    return _librespot_call(_librespot_volume, step)


def _prepare_local_speaker() -> None:
    """Before starting/resuming music on the Pi, connect and route its speaker.

    Pause, next and volume never reconnect: a speaker that went to sleep while
    nothing played is only woken when music should come out of it.
    """
    if settings.BLUETOOTH_SPEAKER_MAC:
        prepare_speaker()


# When another Connect device (e.g. a phone) is the active one, commands are
# relayed to it; otherwise they act on the Pi's own player.

def _librespot_call(function, *args) -> dict:
    try:
        return function(*args)
    except Exception as error:  # noqa: BLE001 - translate receiver errors into a dict response.
        return _handle_error(error)


def _librespot_cluster() -> dict:
    try:
        return librespot.devices() or {}
    except LibrespotError as error:
        logger.warning("Could not read the Spotify Connect devices from go-librespot: %s", error)
        return {}


def _librespot_remote_active(cluster: dict) -> Optional[dict]:
    active = cluster.get("active_device_id")
    for device in cluster.get("devices") or []:
        if active and device.get("id") == active and not device.get("is_self") and not device.get("is_offline"):
            return device
    return None


def _librespot_self_id(cluster: dict) -> Optional[str]:
    return next((device.get("id") for device in cluster.get("devices") or [] if device.get("is_self")), None)


def _librespot_command(device: dict, endpoint: str, **fields) -> dict:
    logger.info("Sending %s to the active Spotify device %s.", endpoint, device.get("name") or device["id"])
    librespot.post("/connect/command", {"device_id": device["id"], "endpoint": endpoint, **fields})
    return {"status": "ok", "mode": "go-librespot", "device": device.get("name") or device["id"]}


def _librespot_play(kind: str, item_id: str, uri: str, position_ms: int) -> dict:
    librespot.require_session()
    body = {"uri": uri}
    episode = None
    if kind == "show":
        try:
            episode = latest_episode(item_id)
        except Exception as error:  # noqa: BLE001 - fall back to the show itself.
            logger.warning("Latest-episode lookup failed (%s); playing the show from its start.", error)
        else:
            if episode is None:
                return {
                    "status": "error",
                    "error": "show_no_episodes",
                    "message": "No playable episodes were found for this Spotify show.",
                }
            body["skip_to_uri"] = episode["uri"]
    remote = _librespot_remote_active(_librespot_cluster())
    if remote is not None:
        result = _librespot_command(remote, "play", **body)
    else:
        _prepare_local_speaker()
        if position_ms:
            body["position"] = position_ms
        librespot.post("/player/play", body)
        logger.info("Playing %s on %s.", body.get("skip_to_uri") or uri, settings.SPOTIFY_DEVICE_NAME)
        result = {"status": "ok", "mode": "go-librespot", "device": settings.SPOTIFY_DEVICE_NAME}
    if kind == "show" and episode is not None:
        result.update(uri=episode["uri"], episode_name=episode.get("name") or episode["uri"])
    return result


def _librespot_toggle() -> dict:
    cluster = _librespot_cluster()
    remote = _librespot_remote_active(cluster)
    if remote is not None:
        playing = (cluster.get("now_playing") or {}).get("playing")
        logger.info("Play/pause: %s.", "pausing" if playing else "resuming")
        return _librespot_command(remote, "pause" if playing else "resume")
    current = librespot.require_session()
    if not current.get("stopped") and not current.get("paused"):
        logger.info("Play/pause: pausing.")
        librespot.post("/player/pause")
    elif current.get("track"):
        logger.info("Play/pause: resuming.")
        _prepare_local_speaker()
        librespot.post("/player/resume")
    else:
        # Nothing loaded on the Pi: pull the account's last playback onto it.
        self_id = _librespot_self_id(cluster)
        if self_id is None:
            return {
                "status": "error",
                "error": "nothing_to_resume",
                "message": "Nothing to resume yet. Tap a music tag first.",
            }
        logger.info("Play/pause: resuming the account's last playback on the Pi.")
        _prepare_local_speaker()
        librespot.post("/connect/transfer", {"device_id": self_id})
    return {"status": "ok", "mode": "go-librespot", "device": settings.SPOTIFY_DEVICE_NAME}


def _librespot_next() -> dict:
    remote = _librespot_remote_active(_librespot_cluster())
    if remote is not None:
        return _librespot_command(remote, "skip_next")
    librespot.require_session()
    librespot.post("/player/next")
    return {"status": "ok", "mode": "go-librespot", "device": settings.SPOTIFY_DEVICE_NAME}


def _librespot_volume(step: int) -> dict:
    with _volume_lock:
        remote = _librespot_remote_active(_librespot_cluster())
        if remote is not None:
            volume = round((remote.get("volume") or 0) * 100 / 65535)
            new_volume = max(0, min(100, volume + step))
            _librespot_command(remote, "set_volume", volume=round(new_volume * 65535 / 100))
            name = remote.get("name") or remote["id"]
        else:
            current = librespot.request("GET", "/player/volume") or {}
            maximum = current.get("max") or 100
            volume = round((current.get("value") or 0) * 100 / maximum)
            new_volume = max(0, min(100, volume + step))
            librespot.post("/player/volume", {"volume": round(new_volume * maximum / 100)})
            name = settings.SPOTIFY_DEVICE_NAME
        logger.info("Volume %d%% -> %d%% on device %s.", volume, new_volume, name)
        return {"status": "ok", "mode": "go-librespot", "volume_percent": new_volume}


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
