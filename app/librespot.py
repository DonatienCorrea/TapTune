"""Minimal client for go-librespot's local HTTP API (bound to localhost on the Pi)."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from .config import settings

TIMEOUT_SECONDS = 10
# go-librespot can still be starting (boot, restart): retry refused connections
# and a missing session a few times before giving up.
ATTEMPTS = 3
RETRY_DELAY_SECONDS = 1.0
_sleep = time.sleep
logger = logging.getLogger(__name__)


class LibrespotError(Exception):
    """go-librespot answered with an error status."""

    def __init__(self, status: int, path: str):
        super().__init__(f"go-librespot returned HTTP {status} for {path}")
        self.status = status


class LibrespotUnavailable(Exception):
    """go-librespot is not running or not reachable on its local API."""


class NotLoggedIn(Exception):
    """go-librespot runs but no Spotify account has selected it yet."""


def _refused(error: Exception) -> bool:
    reason = getattr(error, "reason", error)
    return isinstance(reason, (ConnectionRefusedError, ConnectionResetError, FileNotFoundError))


def request(method: str, path: str, body: Optional[dict] = None, opener=urllib.request.urlopen) -> Any:
    """Return the decoded JSON body, or ``None`` for go-librespot's 204 "no session"."""
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(settings.LIBRESPOT_API_URL + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for attempt in range(1, ATTEMPTS + 1):
        try:
            with opener(req, timeout=TIMEOUT_SECONDS) as response:
                if response.status == 204:
                    return None
                raw = response.read()
            break
        except urllib.error.HTTPError as error:
            raise LibrespotError(error.code, path) from error
        except (urllib.error.URLError, OSError) as error:
            # A refused connection never reached go-librespot, so even a POST is safe to resend.
            if attempt == ATTEMPTS or not (_refused(error) or method == "GET"):
                raise LibrespotUnavailable(
                    f"go-librespot API unreachable at {settings.LIBRESPOT_API_URL}: {error}"
                ) from error
            logger.info("go-librespot %s %s failed (%s, attempt %d/%d); retrying.", method, path, error, attempt, ATTEMPTS)
            _sleep(RETRY_DELAY_SECONDS * attempt)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except ValueError:
        return {}


def status(opener=urllib.request.urlopen) -> Optional[dict]:
    """Player status, or ``None`` when no Spotify account is logged in."""
    return request("GET", "/status", opener=opener)


def require_session(opener=urllib.request.urlopen) -> dict:
    """Player status; waits briefly while go-librespot restores its saved sign-in."""
    for attempt in range(1, ATTEMPTS + 1):
        current = status(opener)
        if current is not None:
            return current
        if attempt < ATTEMPTS:
            _sleep(RETRY_DELAY_SECONDS)
    raise NotLoggedIn()


def devices(opener=urllib.request.urlopen) -> Optional[dict]:
    """The account's Spotify Connect cluster, or ``None`` before one is known."""
    try:
        return request("GET", "/connect/devices", opener=opener)
    except LibrespotError as error:
        if error.status == 404:
            return None
        raise


def token(opener=urllib.request.urlopen) -> Optional[str]:
    """A Web API access token for the logged-in account (no developer app needed)."""
    result = request("POST", "/token", opener=opener)
    return (result or {}).get("token") or None


def library_albums(offset: int = 0, limit: int = 20, opener=urllib.request.urlopen) -> Optional[dict]:
    """Saved albums from go-librespot's internal collection service."""
    return request("GET", f"/library/albums?offset={offset}&limit={limit}", opener=opener)


def library_playlists(offset: int = 0, limit: int = 20, opener=urllib.request.urlopen) -> Optional[dict]:
    """Playlists from go-librespot's internal playlist service."""
    return request("GET", f"/library/playlists?offset={offset}&limit={limit}", opener=opener)


def post(path: str, body: Optional[dict] = None, opener=urllib.request.urlopen) -> Any:
    return request("POST", path, body, opener=opener)
