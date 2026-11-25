"""Small, credential-free response shapes for the local music picker."""

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import librespot
from .activity import list_activity
from .db import list_tags
from .spotify_service import get_tag_type


COLLECTIONS = frozenset({"albums", "playlists", "recent", "playing"})
PAGE_SIZE = 20
LINK_ID = re.compile(r"^[A-Za-z0-9]+$")
# Reopening a tab or reloading the page reuses recent answers instead of
# calling Spotify again.
CACHE_SECONDS = 300
CACHE_LIMIT = 64
_cache: dict = {}
_cache_lock = threading.Lock()


def clear_cache():
    with _cache_lock:
        _cache.clear()


def music_item(item):
    if not item or item.get("is_local"):
        return None
    uri = item.get("uri")
    if not isinstance(uri, str) or get_tag_type(uri) != "content":
        return None
    kind = uri.split(":")[1]
    images = item.get("images") or (item.get("album") or {}).get("images") or []
    image = next((image["url"] for image in images if image and (image.get("url") or "").startswith("https://")), None)
    if kind == "playlist":
        detail = (item.get("owner") or {}).get("display_name") or ""
    elif kind == "show":
        detail = item.get("publisher") or ""
    else:
        detail = ", ".join(artist.get("name") or "" for artist in item.get("artists") or [] if artist)
    return {
        "uri": item["uri"],
        "name": item.get("name") or item["uri"],
        "kind": kind,
        "detail": detail,
        "image": image,
        "url": "https://open.spotify.com/" + item["uri"][8:].replace(":", "/"),
    }


def browse_music(collection, offset=0):
    if collection not in COLLECTIONS:
        raise ValueError("Unsupported music collection")
    if not 0 <= offset <= 10000:
        raise ValueError("Invalid page")
    if collection == "recent":
        return _local_recent_music()
    if collection == "playing":
        return _currently_playing()
    return _cached((collection, offset), lambda: _fetch_librespot_library(collection, offset))


def _cached(key, fetch):
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    result = fetch()
    with _cache_lock:
        for stale in [k for k, (at, _) in _cache.items() if now - at >= CACHE_SECONDS]:
            del _cache[stale]
        if len(_cache) >= CACHE_LIMIT:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[key] = (now, result)
    return result


def _fetch_librespot_library(collection, offset):
    librespot.require_session()
    page = (
        librespot.library_albums(offset=offset, limit=PAGE_SIZE)
        if collection == "albums"
        else librespot.library_playlists(offset=offset, limit=PAGE_SIZE)
    ) or {}
    items = []
    for raw in page.get("items") or []:
        if not raw:
            continue
        normalized = music_item({
            "uri": raw.get("uri"), "name": raw.get("name"),
            "artists": [{"name": artist} for artist in raw.get("artist_names") or []],
            "owner": {"display_name": raw.get("owner_username") or ""},
            "images": [{"url": raw.get("image_url")}],
        })
        if normalized:
            items.append(normalized)
    total = page.get("total")
    next_page = {"offset": offset + PAGE_SIZE} if isinstance(total, int) and offset + len(page.get("items") or []) < total else None
    return {"items": items, "next": next_page}


def _local_recent_music():
    labels = {tag["uid"]: tag.get("label") for tag in list_tags()}
    rows, _ = list_activity(kind="playback", page=1)
    items, seen = [], set()
    for row in rows:
        if row.get("level") != "INFO":
            continue
        uri = row.get("value") or row.get("resolved_uri") or ""
        if get_tag_type(uri) != "content" or uri in seen:
            continue
        kind, identifier = uri.split(":")[1:]
        items.append({
            "uri": uri, "name": labels.get(row.get("uid")) or f"{kind.title()} · {identifier[:8]}",
            "kind": kind, "detail": "Played from TapTune",
            "image": None, "url": "https://open.spotify.com/" + kind + "/" + identifier,
        })
        seen.add(uri)
        if len(items) == PAGE_SIZE:
            break
    return {"items": items, "next": None}


def _currently_playing():
    librespot.require_session()
    status = librespot.status()
    track = (status or {}).get("track") or {}
    context_uri = (status or {}).get("context_uri")
    album_uri = track.get("album_uri")
    uri = context_uri if get_tag_type(context_uri or "") == "content" else album_uri
    if get_tag_type(uri or "") != "content":
        return {"items": [], "next": None}
    name = (status or {}).get("context_name") or track.get("album_name") or track.get("name")
    detail = ", ".join(track.get("artist_names") or [])
    item = music_item({
        "uri": uri, "name": name, "artists": [{"name": detail}] if detail else [],
        "images": [{"url": track.get("album_cover_url")}],
    })
    return {"items": [item] if item else [], "next": None}


def import_spotify_link(value, opener=urllib.request.urlopen):
    """Resolve a public Spotify share link through Spotify's unauthenticated oEmbed API."""
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("Enter a Spotify link")
    try:
        parsed = urllib.parse.urlsplit(value.strip())
        parts = [part for part in parsed.path.split("/") if part]
        if parts and re.fullmatch(r"intl-[a-zA-Z-]+", parts[0]):
            parts.pop(0)
        if parts and parts[0] == "embed":
            parts.pop(0)
        if (
            parsed.scheme != "https" or parsed.hostname != "open.spotify.com"
            or parsed.username or parsed.password or parsed.port
            or len(parts) != 2 or parts[0] not in {"album", "playlist", "track", "show"}
            or not LINK_ID.fullmatch(parts[1])
        ):
            raise ValueError("Enter a Spotify album, playlist, track, or podcast-show link")
    except (ValueError, UnicodeError) as error:
        raise ValueError("Enter a Spotify album, playlist, track, or podcast-show link") from error

    kind, identifier = parts
    share_url = f"https://open.spotify.com/{kind}/{identifier}"
    endpoint = "https://open.spotify.com/oembed?" + urllib.parse.urlencode({"url": share_url})
    try:
        with opener(endpoint, timeout=8) as response:
            payload = json.loads(response.read(1024 * 1024))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, UnicodeDecodeError) as error:
        raise LinkPreviewUnavailable("Spotify link preview is unavailable") from error

    if not isinstance(payload, dict):
        raise LinkPreviewUnavailable("Spotify link preview returned an invalid response")
    thumbnail = payload.get("thumbnail_url")
    try:
        thumbnail_host = urllib.parse.urlsplit(thumbnail).hostname if isinstance(thumbnail, str) else None
    except ValueError:
        thumbnail_host = None
    if (
        not isinstance(thumbnail, str) or not thumbnail.startswith("https://")
        or not thumbnail_host or not (thumbnail_host.endswith(".spotifycdn.com") or thumbnail_host.endswith(".scdn.co"))
    ):
        thumbnail = None
    uri = f"spotify:{kind}:{identifier}"
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        title = uri
    return {
        "uri": uri, "name": title, "kind": kind,
        "detail": "Spotify link", "image": thumbnail, "url": share_url,
    }


class LinkPreviewUnavailable(Exception):
    """Spotify's public link-preview service could not be reached."""
