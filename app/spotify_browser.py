"""Small, credential-free response shapes for the local music picker."""

from .spotify_service import build_spotify_client, get_tag_type, is_live_spotify_configured


COLLECTIONS = frozenset({"albums", "playlists", "recent", "search"})
SEARCH_TYPES = frozenset({"album", "playlist", "track"})
PAGE_SIZE = 20


def music_item(item):
    if not item or item.get("is_local"):
        return None
    uri = item.get("uri")
    if not isinstance(uri, str) or get_tag_type(uri) != "content":
        return None
    kind = uri.split(":")[1]
    images = item.get("images") or (item.get("album") or {}).get("images") or []
    image = next((image["url"] for image in images if image and (image.get("url") or "").startswith("https://")), None)
    return {
        "uri": item["uri"],
        "name": item.get("name") or item["uri"],
        "kind": kind,
        "detail": ", ".join(artist.get("name") or "" for artist in item.get("artists") or [] if artist)
        if kind != "playlist" else (item.get("owner") or {}).get("display_name") or "",
        "image": image,
        "url": "https://open.spotify.com/" + item["uri"][8:].replace(":", "/"),
    }


def _demo_items():
    return [
        {"uri": "spotify:album:demoalbum", "name": "Workshop sessions (demo)", "artists": [{"name": "TapTune demo"}]},
        {"uri": "spotify:playlist:demoplaylist", "name": "Morning mix (demo)", "owner": {"display_name": "TapTune demo"}},
        {"uri": "spotify:track:demotrack", "name": "First tap (demo)", "artists": [{"name": "TapTune demo"}]},
    ]


def browse_music(collection, *, query="", kind="album", offset=0, before=None):
    if collection not in COLLECTIONS or kind not in SEARCH_TYPES:
        raise ValueError("Unsupported music collection or search type")
    if offset < 0 or offset > 10000 or (before is not None and before <= 0):
        raise ValueError("Invalid page")
    query = query.strip()
    if collection == "search" and not 1 <= len(query) <= 200:
        raise ValueError("Enter a search between 1 and 200 characters")

    live = is_live_spotify_configured()
    if not live:
        target_kind = {"albums": "album", "playlists": "playlist", "recent": "album", "search": kind}[collection]
        items = [music_item(item) for item in _demo_items() if item["uri"].split(":")[1] == target_kind]
        if collection == "search":
            items = [item for item in items if query.casefold() in (item["name"] + " " + item["detail"]).casefold()]
        return {"items": items if not offset and not before else [], "next": None, "mode": "fake"}

    spotify = build_spotify_client()
    if collection == "albums":
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
        page = spotify.search(q=query, type=kind, limit=10, offset=offset)[kind + "s"]
        raw_items = page.get("items", [])

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
