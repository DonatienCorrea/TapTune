import tempfile
import threading
import io
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import config, librespot, spotify_browser, spotify_service
from app.nfc_reader import NFCEvent, SimulatedReader
from app.web import TRANSLATIONS, create_app


def album(identifier="abc", name="Album"):
    return {
        "uri": "spotify:album:" + identifier, "name": name,
        "artists": [{"name": "Artist"}], "images": [{"url": "https://i.scdn.co/example"}],
    }


class SpotifyBrowserTests(unittest.TestCase):
    def setUp(self):
        spotify_browser.clear_cache()
        self.addCleanup(spotify_browser.clear_cache)
        for name in ("require_session", "library_albums", "library_playlists", "status"):
            patcher = patch.object(librespot, name)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_repeated_requests_reuse_the_recent_answer(self):
        self.library_playlists.return_value = {"items": [], "total": 0}
        spotify_browser.browse_music("playlists")
        spotify_browser.browse_music("playlists")
        self.library_playlists.assert_called_once()
        spotify_browser.browse_music("playlists", offset=20)
        self.assertEqual(self.library_playlists.call_count, 2)

    def test_saved_albums_are_normalized_and_paginated(self):
        self.library_albums.return_value = {"total": 41, "items": [
            {"uri": "spotify:album:abc", "name": "Album", "artist_names": ["Artist"],
             "image_url": "https://i.scdn.co/example"},
            None,
        ]}
        result = spotify_browser.browse_music("albums", offset=20)
        self.require_session.assert_called_once_with()
        self.library_albums.assert_called_once_with(offset=20, limit=20)
        self.assertEqual(result, {"items": [{
            "uri": "spotify:album:abc", "name": "Album", "kind": "album", "detail": "Artist",
            "image": "https://i.scdn.co/example", "url": "https://open.spotify.com/album/abc",
        }], "next": {"offset": 40}})

    def test_private_playlists_and_missing_artwork(self):
        self.library_playlists.return_value = {"total": 1, "items": [
            {"uri": "spotify:playlist:abc", "name": "Private", "owner_username": "Me"},
        ]}
        result = spotify_browser.browse_music("playlists")
        self.assertEqual(result["items"][0]["detail"], "Me")
        self.assertIsNone(result["items"][0]["image"])
        self.assertIsNone(result["next"])

    def test_currently_playing_becomes_a_tag_selectable_context(self):
        self.status.return_value = {
            "context_uri": "spotify:playlist:mix", "context_name": "Evening Mix",
            "track": {"name": "Song", "artist_names": ["Artist"], "album_cover_url": "https://i.scdn.co/song"},
        }
        result = spotify_browser.browse_music("playing")
        self.assertEqual(result["items"][0]["uri"], "spotify:playlist:mix")
        self.assertEqual(result["items"][0]["name"], "Evening Mix")
        self.status.return_value = None
        self.assertEqual(spotify_browser.browse_music("playing"), {"items": [], "next": None})

    def test_taptune_history_uses_successful_tag_playbacks(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(config.settings, "DATABASE_PATH", str(Path(directory) / "tags.db")):
            from app.activity import record_activity
            from app.db import upsert_tag
            upsert_tag("CARD", "spotify:album:abc", "content", "Morning music")
            record_activity("playback", "INFO", "nfc", "Playback command sent.", uid="CARD",
                            value="spotify:album:abc")
            record_activity("playback", "ERROR", "nfc", "Failed.", uid="CARD",
                            value="spotify:album:bad")
            result = spotify_browser.browse_music("recent")
        self.assertEqual([item["name"] for item in result["items"]], ["Morning music"])
        self.assertEqual(result["items"][0]["uri"], "spotify:album:abc")

    def test_spotify_link_import_supports_podcast_shows_without_a_token(self):
        payload = json.dumps({
            "title": "Podcast show", "thumbnail_url": "https://image-cdn-fa.spotifycdn.com/cover",
        }).encode()
        calls = []

        def opener(url, timeout):
            calls.append((url, timeout))
            return io.BytesIO(payload)

        item = spotify_browser.import_spotify_link(
            "https://open.spotify.com/intl-en/show/abc?si=private", opener=opener,
        )
        self.assertEqual(item["uri"], "spotify:show:abc")
        self.assertEqual(item["name"], "Podcast show")
        self.assertEqual(item["image"], "https://image-cdn-fa.spotifycdn.com/cover")
        self.assertIn("oembed", calls[0][0])
        self.assertEqual(calls[0][1], 8)

    def test_spotify_link_import_rejects_non_spotify_urls(self):
        for value in ("https://evil.example/album/abc", "http://open.spotify.com/album/abc",
                      "https://open.spotify.com/episode/abc", "https://open.spotify.com/album/a/b"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                spotify_browser.import_spotify_link(value, opener=Mock())

    def test_invalid_input_does_not_call_go_librespot(self):
        for collection, offset in (("invalid", 0), ("search", 0), ("albums", -1), ("albums", 10001)):
            with self.subTest(collection=collection, offset=offset), self.assertRaises(ValueError):
                spotify_browser.browse_music(collection, offset=offset)
        self.require_session.assert_not_called()

    def test_unsafe_image_and_unsupported_uri_are_not_exposed(self):
        item = album()
        item["images"] = [{"url": "javascript:alert(1)"}]
        self.assertIsNone(spotify_browser.music_item(item)["image"])
        self.assertIsNone(spotify_browser.music_item({"uri": "spotify:artist:abc"}))
        self.assertIsNone(spotify_browser.music_item({"uri": None}))
        item["images"] = [None, {"url": None}]
        item["artists"] = None
        self.assertIsNone(spotify_browser.music_item(item)["image"])
        self.assertEqual(spotify_browser.music_item(item)["detail"], "")


class MusicWebTests(unittest.TestCase):
    def setUp(self):
        spotify_browser.clear_cache()
        spotify_service.clear_web_api_state()
        self.addCleanup(spotify_browser.clear_cache)
        self.addCleanup(spotify_service.clear_web_api_state)
        skip_setup = patch.object(config.settings, "SETUP_SKIP", True)
        skip_setup.start()
        self.addCleanup(skip_setup.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.multiple(
            config.settings, DATABASE_PATH=str(Path(temporary.name) / "tags.db"),
            NFC_READER_ENABLED=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = create_app()
        self.client = self.app.test_client()

    def test_bilingual_picker_and_manual_assignment_are_present(self):
        self.assertEqual(set(TRANSLATIONS["en"]), set(TRANSLATIONS["fr"]))
        for path in ("/", "/fr/"):
            page = self.client.get(path)
            self.assertEqual(page.status_code, 200)
            for marker in (b'id="link-view"', b'id="music-link-import"', b'id="spotify-external-search"',
                           b'data-collection="playing"', b'id="write-tag"', b'id="assignment"',
                           b'/static/music.js'):
                self.assertIn(marker, page.data)
            self.assertIn(b'<details id="advanced-options" class="advanced-options">', page.data)
            self.assertIn(b'data-collection="link"', page.data)
            self.assertNotIn(b'id="music-search"', page.data)
            self.assertIn(b'id="write-selection" class="write-panel" hidden', page.data)
            self.assertIn(b'class="spotify-browser" aria-labelledby="music-view-heading"', page.data)
            self.assertIn(b'id="music-view-heading"', page.data)

    def test_connection_context_is_checked_by_the_browser_not_while_rendering(self):
        with patch("app.web.browse_music") as browse:
            page = self.client.get("/")
        self.assertIn("Checking Spotify".encode(), page.data)
        self.assertIn("Uses this device’s saved Spotify connection".encode(), page.data)
        browse.assert_not_called()

    def test_saved_assignment_keeps_advanced_form_open(self):
        response = self.client.post("/assign", data={"uid": "040102", "value": "spotify:album:abc"},
                                    follow_redirects=True)
        self.assertIn(b'<details id="advanced-options" class="advanced-options" open>', response.data)
        self.assertIn(b"Tag saved.", response.data)

    def test_write_feedback_is_structured_and_accessible_in_both_languages(self):
        for path in ("/", "/fr/"):
            page = self.client.get(path).data
            for marker in (
                b'id="write-status" class="write-feedback" hidden',
                b'role="status" aria-live="polite" aria-atomic="true"',
                b'id="write-status-title"', b'id="write-status-detail"',
                b'id="write-icon-path"', b'id="retry-write"', b'id="check-write"',
                b'id="write-status-uid"', b'<details class="tag-help">',
                b'<details id="spotify-connection"',
            ):
                self.assertIn(marker, page)
            self.assertNotIn(b'class="subtitle"', page)
            self.assertNotIn(b'id="connection-help"', page)
            self.assertIn(b'for="music-link" class="sr-only"', page)

    def test_show_uri_can_be_assigned_and_written(self):
        response = self.client.post("/assign", data={"uid": "SHOW-001", "value": "spotify:show:abc"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.app.config["TAG_WRITER"].start("spotify:show:abc")["value"], "spotify:show:abc")
        for path, label in (("/", b'"show": "Podcast show"'), ("/fr/", b'"show": "Podcast"')):
            page = self.client.get(path).data
            self.assertIn(label, page)
            self.assertNotIn(b'id="music-kind"', page)

    def test_music_page_is_not_cached_and_invalid_requests_are_rejected(self):
        with patch("app.web.browse_music", return_value={"items": [], "next": None}) as browse:
            response = self.client.get("/api/music?collection=playlists&offset=20")
        browse.assert_called_once_with("playlists", offset=20)
        self.assertEqual(response.json, {"items": [], "next": None})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for params in ("offset=no", "offset=-1", "collection=search"):
            self.assertEqual(self.client.get("/api/music?" + params).status_code, 400)

    def test_spotify_link_endpoint_returns_preview_and_rejects_cross_origin(self):
        item = {"uri": "spotify:show:abc", "name": "Podcast", "kind": "show"}
        with patch("app.web.import_spotify_link", return_value=item) as import_link:
            response = self.client.post("/api/music/link", json={"url": "https://open.spotify.com/show/abc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"item": item, "mode": "preview"})
        import_link.assert_called_once_with("https://open.spotify.com/show/abc")
        response = self.client.post("/api/music/link", json={"url": "https://open.spotify.com/show/abc"},
                                    headers={"Origin": "https://evil.example"})
        self.assertEqual(response.status_code, 403)

    def test_go_librespot_errors_are_actionable_and_do_not_return_secrets(self):
        for error, code, status in (
            (librespot.NotLoggedIn("secret"), "spotify_not_signed_in", 409),
            (librespot.LibrespotUnavailable("secret"), "spotify_unavailable", 502),
            (librespot.LibrespotError(500, "/secret"), "spotify_unavailable", 502),
        ):
            with self.subTest(code=code), patch("app.web.browse_music", side_effect=error):
                response = self.client.get("/api/music")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json, {"error": code})
                self.assertNotIn(b"secret", response.data)

    def test_rate_limit_preserves_retry_after(self):
        with patch("app.web.browse_music", side_effect=spotify_service.RateLimited(10)):
            response = self.client.get("/api/music")
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json, {"error": "spotify_rate_limit"})
        self.assertEqual(response.headers["Retry-After"], "10")

    def test_writer_requires_running_initialized_reader(self):
        response = self.client.post("/api/tag-writes", json={"value": "spotify:album:abc"})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(self.client.get("/api/tag-writes").json["available"])
        thread = Mock()
        thread.reader_ready = threading.Event()
        thread.is_alive.return_value = True
        self.app.config["NFC_READER_THREAD"] = thread
        with patch.object(config.settings, "NFC_READER_ENABLED", True):
            self.assertEqual(self.client.post("/api/tag-writes", json={"value": "spotify:album:abc"}).status_code, 503)
            thread.reader_ready.set()
            response = self.client.post("/api/tag-writes", json={"value": "spotify:album:abc"})
            self.assertEqual(response.status_code, 202)
            job_id = response.json["id"]
            self.assertEqual(self.client.get("/api/tag-writes/" + job_id).json["status"], "waiting")
            self.assertEqual(self.client.post("/api/tag-writes", json={"value": "spotify:album:def"}).status_code, 409)
            cancelled = self.client.post("/api/tag-writes/" + job_id + "/cancel", json={})
            self.assertEqual(cancelled.json["status"], "cancelled")

    def test_writer_rejects_invalid_inputs_and_cross_origin_requests(self):
        for value in (None, [], {}, "action:next", "https://open.spotify.com/album/abc", "spotify:album:" + "a" * 201):
            self.assertEqual(self.client.post("/api/tag-writes", json={"value": value}).status_code, 400)
        self.assertEqual(self.client.post("/api/tag-writes", json=[]).status_code, 400)
        self.assertEqual(self.client.post("/api/tag-writes", data={"value": "spotify:album:abc"}).status_code, 403)
        self.assertEqual(self.client.post("/api/tag-writes", json={"value": "spotify:album:abc"},
                                         headers={"Origin": "https://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post("/api/tag-writes/none/cancel", json={},
                                         headers={"Sec-Fetch-Site": "cross-site"}).status_code, 403)
        self.assertEqual(self.client.get("/api/tag-writes/missing").status_code, 404)

    def test_web_write_is_consumed_by_reader_and_reported_back_without_playback(self):
        thread = Mock()
        thread.reader_ready = threading.Event()
        thread.reader_ready.set()
        thread.is_alive.return_value = True
        self.app.config["NFC_READER_THREAD"] = thread
        with patch.object(config.settings, "NFC_READER_ENABLED", True):
            started = self.client.post("/api/tag-writes", json={"value": "spotify:album:abc"},
                                       headers={"Origin": "http://localhost"})
        self.assertEqual(started.status_code, 202)
        reader = SimulatedReader()
        self.assertTrue(self.app.config["TAG_WRITER"].consume(reader, NFCEvent("040102", "unassigned")))
        status = self.client.get("/api/tag-writes/" + started.json["id"])
        self.assertEqual(status.json["status"], "success")
        self.assertEqual(status.json["uid"], "040102")
        self.assertEqual(reader.payload_map["040102"], "spotify:album:abc")
        self.assertEqual(self.client.get("/api/tag-writes").json["job"]["id"], started.json["id"])
