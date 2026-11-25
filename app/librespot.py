"""Minimal client for go-librespot's local HTTP API (bound to localhost on the Pi)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Optional

from .config import settings

TIMEOUT_SECONDS = 10


class LibrespotError(Exception):
    """go-librespot answered with an error status."""

    def __init__(self, status: int, path: str):
        super().__init__(f"go-librespot returned HTTP {status} for {path}")
        self.status = status


class LibrespotUnavailable(Exception):
    """go-librespot is not running or not reachable on its local API."""


class NotLoggedIn(Exception):
    """go-librespot runs but no Spotify account has selected it yet."""


def request(method: str, path: str, body: Optional[dict] = None, opener=urllib.request.urlopen) -> Any:
    """Return the decoded JSON body, or ``None`` for go-librespot's 204 "no session"."""
    data = json.dumps(body).encode() if body is not None else (b"" if method == "POST" else None)
    req = urllib.request.Request(settings.LIBRESPOT_API_URL + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with opener(req, timeout=TIMEOUT_SECONDS) as response:
            if response.status == 204:
                return None
            raw = response.read()
    except urllib.error.HTTPError as error:
        raise LibrespotError(error.code, path) from error
    except (urllib.error.URLError, OSError) as error:
        raise LibrespotUnavailable(f"go-librespot API unreachable at {settings.LIBRESPOT_API_URL}: {error}") from error
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
    current = status(opener)
    if current is None:
        raise NotLoggedIn()
    return current


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


def post(path: str, body: Optional[dict] = None, opener=urllib.request.urlopen) -> Any:
    return request("POST", path, body, opener=opener)
