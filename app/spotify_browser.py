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
from .spotify_service import (
    build_web_api_client, check_rate_limit, get_tag_type, is_live_spotify_configured,
    is_web_api_configured, uses_librespot,
)


COLLECTIONS = frozenset({"albums", "playlists", "recent", "playing", "search"})
SEARCH_ORDER = ("album", "playlist", "track", "show")
SEARCH_TYPES = frozenset(SEARCH_ORDER + ("all",))
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


def _demo_items():
    return [
        {"uri": "spotify:album:demoalbum", "name": "Workshop sessions (demo)", "artists": [{"name": "TapTune demo"}]},
        {"uri": "spotify:playlist:demoplaylist", "name": "Morning mix (demo)", "owner": {"display_name": "TapTune demo"}},
        {"uri": "spotify:track:demotrack", "name": "First tap (demo)", "artists": [{"name": "TapTune demo"}]},
        {"uri": "spotify:show:demoshow", "name": "Workshop podcast (demo)", "publisher": "TapTune demo"},
    ]


def browse_music(collection, *, query="", kind="all", offset=0, before=None):
    if collection not in COLLECTIONS or kind not in SEARCH_TYPES:
        raise ValueError("Unsupported music collection or search type")
    if offset < 0 or offset > 10000 or (before is not None and before <= 0):
        raise ValueError("Invalid page")
    query = query.strip()
    if collection == "search" and not 1 <= len(query) <= 200:
        raise ValueError("Enter a search between 1 and 200 characters")

    if uses_librespot():
        if collection == "search" and not is_live_spotify_configured():
            raise ValueError("Search by Spotify link instead")
        if collection != "search":
            if collection == "recent":
                return _local_recent_music()
            if collection == "playing":
                return _currently_playing()
            return _browse_librespot_library(collection, offset)

    live = is_web_api_configured()
    if not live:
        if collection == "playing":
            return {"items": [], "next": None, "mode": "fake"}
        target_kind = {"albums": "album", "playlists": "playlist", "recent": "album", "search": kind}[collection]
        items = [music_item(item) for item in _demo_items()
                 if target_kind == "all" or item["uri"].split(":")[1] == target_kind]
        if collection == "search":
            items = [item for item in items if query.casefold() in (item["name"] + " " + item["detail"]).casefold()]
        return {"items": items if not offset and not before else [], "next": None, "mode": "fake"}

    key = (collection, query.casefold(), kind, offset, before)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]
    check_rate_limit()
    result = _fetch(collection, query, kind, offset, before)
    with _cache_lock:
        for stale in [k for k, (at, _) in _cache.items() if now - at >= CACHE_SECONDS]:
            del _cache[stale]
        if len(_cache) >= CACHE_LIMIT:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[key] = (now, result)
    return result


def _browse_librespot_library(collection, offset):
    key = ("go-librespot", collection, "", "", offset, None)
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1]

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
        if collection == "albums":
            artists = raw.get("artist_names") or []
            item = {
                "uri": raw.get("uri"), "name": raw.get("name"),
                "artists": [{"name": artist} for artist in artists],
                "images": [{"url": raw.get("image_url")}],
            }
        else:
            item = {
                "uri": raw.get("uri"), "name": raw.get("name"),
                "owner": {"display_name": raw.get("owner_username") or ""},
                "images": [{"url": raw.get("image_url")}],
            }
        normalized = music_item(item)
        if normalized:
            items.append(normalized)
    total = page.get("total")
    next_page = {"offset": offset + PAGE_SIZE} if isinstance(total, int) and offset + len(page.get("items") or []) < total else None
    result = {"items": items, "next": next_page, "mode": "spotify"}
    _cache_result(key, now, result)
    return result


def _cache_result(key, now, result):
    with _cache_lock:
        for stale in [k for k, (at, _) in _cache.items() if now - at >= CACHE_SECONDS]:
            del _cache[stale]
        if len(_cache) >= CACHE_LIMIT:
            del _cache[min(_cache, key=lambda k: _cache[k][0])]
        _cache[key] = (now, result)


def _local_recent_music():
    labels = {tag["uid"]: tag.get("label") for tag in list_tags()}
    rows, _ = list_activity(kind="playback", page=1)
    items, seen = [], set()
    for row in rows:
        if row.get("level") != "INFO" or row.get("message", "").startswith("Demo mode:"):
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
    return {"items": items, "next": None, "mode": "spotify"}


def _currently_playing():
    librespot.require_session()
    status = librespot.status()
    track = (status or {}).get("track") or {}
    context_uri = (status or {}).get("context_uri")
    album_uri = track.get("album_uri")
    uri = context_uri if get_tag_type(context_uri or "") == "content" else album_uri
    if get_tag_type(uri or "") != "content":
        return {"items": [], "next": None, "mode": "spotify"}
    name = (status or {}).get("context_name") or track.get("album_name") or track.get("name")
    detail = ", ".join(track.get("artist_names") or [])
    item = music_item({
        "uri": uri, "name": name, "artists": [{"name": detail}] if detail else [],
        "images": [{"url": track.get("album_cover_url")}],
    })
    return {"items": [item] if item else [], "next": None, "mode": "spotify"}


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


def _fetch(collection, query, kind, offset, before):
    spotify = build_web_api_client()
    if collection == "playing":
        current = spotify.current_playback() or {}
        track = current.get("item") or {}
        album = track.get("album") or {}
        uri = current.get("context", {}).get("uri") or album.get("uri")
        raw_items = [{
            "uri": uri, "name": current.get("context", {}).get("name") or album.get("name"),
            "artists": track.get("artists") or [], "images": album.get("images") or [],
        }] if uri else []
        page = {}
    elif collection == "albums":
        page = spotify.current_user_saved_albums(limit=PAGE_SIZE, offset=offset)
        raw_items = [(item or {}).get("album") for item in page.get("items", [])]
    elif collection == "playlists":
        page = spotify.current_user_playlists(limit=PAGE_SIZE, offset=offset)
        raw_items = page.get("items", [])
    elif collection == "recent":
        page = spotify.current_user_recently_played(limit=50, before=before)
        raw_items = [((item or {}).get("track") or {}).get("album") for item in page.get("items", [])]
    else:
        # Ten also works with Spotify's development-mode search limit.
        kinds = SEARCH_ORDER if kind == "all" else (kind,)
        response = spotify.search(q=query, type=",".join(kinds), limit=10, offset=offset) or {}
        pages = [response.get(name + "s") or {} for name in kinds]
        raw_items = [item for result in pages for item in result.get("items") or []]
        page = {"next": any(result.get("next") for result in pages)}

    items = []
    seen = set()
    for raw in raw_items:
        item = music_item(raw)
        if item and item["uri"] not in seen:
            items.append(item)
            seen.add(item["uri"])
    next_page = None
    if page.get("next"):
        if collection == "recent":
            cursor = (page.get("cursors") or {}).get("before")
            if cursor and str(cursor).isdigit() and int(cursor) != before:
                next_page = {"before": int(cursor)}
        else:
            next_page = {"offset": offset + (10 if collection == "search" else PAGE_SIZE)}
    return {"items": items, "next": next_page, "mode": "spotify"}
