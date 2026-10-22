import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from requests.exceptions import ConnectionError
from spotipy import SpotifyException
from spotipy.oauth2 import SpotifyOauthError

from app import config, spotify_browser, spotify_service
from app.nfc_reader import NFCEvent, SimulatedReader
from app.web import TRANSLATIONS, create_app


def album(identifier="abc", name="Album"):
    return {
        "uri": "spotify:album:" + identifier, "name": name,
        "artists": [{"name": "Artist"}], "images": [{"url": "https://i.scdn.co/example"}],
    }


class SpotifyBrowserTests(unittest.TestCase):
    def setUp(self):
        self.spotify = Mock()
        self.patches = [
            patch.object(spotify_browser, "is_live_spotify_configured", return_value=True),
            patch.object(spotify_browser, "build_spotify_client", return_value=self.spotify),
        ]
        for patcher in self.patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_saved_albums_are_normalized_and_paginated(self):
        self.spotify.current_user_saved_albums.return_value = {
            "items": [{"album": album()}, {"album": None}], "next": "next",
        }
        result = spotify_browser.browse_music("albums", offset=20)
        self.spotify.current_user_saved_albums.assert_called_once_with(limit=20, offset=20)
        self.assertEqual(result["next"], {"offset": 40})
        self.assertEqual(result["items"][0], {
            "uri": "spotify:album:abc", "name": "Album", "kind": "album", "detail": "Artist",
            "image": "https://i.scdn.co/example", "url": "https://open.spotify.com/album/abc",
        })
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["mode"], "spotify")

    def test_private_playlists_and_missing_artwork(self):
        self.spotify.current_user_playlists.return_value = {"items": [
            None, {"uri": "spotify:playlist:abc", "name": "Private", "owner": {"display_name": "Me"}},
        ]}
        result = spotify_browser.browse_music("playlists")
        self.spotify.current_user_playlists.assert_called_once_with(limit=20, offset=0)
        self.assertEqual(result["items"][0]["detail"], "Me")
        self.assertIsNone(result["items"][0]["image"])
        self.assertIsNone(result["next"])

    def test_recent_albums_are_deduplicated_in_listening_order_and_use_cursor(self):
        self.spotify.current_user_recently_played.return_value = {
            "items": [
                {"track": {"album": album("new")}},
                {"track": {"album": album("new")}},
                {"track": None},
                {"track": {"album": album("older")}},
            ],
            "next": "next", "cursors": {"before": "123"},
        }
        result = spotify_browser.browse_music("recent", before=456)
        self.spotify.current_user_recently_played.assert_called_once_with(limit=50, before=456)
        self.assertEqual([item["uri"] for item in result["items"]], ["spotify:album:new", "spotify:album:older"])
        self.assertEqual(result["next"], {"before": 123})

    def test_search_uses_supported_type_and_ten_result_limit(self):
        self.spotify.search.return_value = {"tracks": {
            "items": [
                {"uri": "spotify:track:xyz", "name": "Song", "album": album()},
                {"uri": "spotify:local:xyz", "is_local": True},
                None,
            ], "next": "next",
        }}
        result = spotify_browser.browse_music("search", query=" song ", kind="track", offset=10)
        self.spotify.search.assert_called_once_with(q="song", type="track", limit=10, offset=10)
        self.assertEqual(result["next"], {"offset": 20})
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["image"], "https://i.scdn.co/example")

    def test_invalid_input_does_not_build_client(self):
        for collection, params in [
            ("invalid", {}), ("search", {"query": ""}), ("search", {"query": "a" * 201}),
            ("albums", {"offset": -1}), ("albums", {"offset": 10001}),
            ("recent", {"before": 0}), ("search", {"query": "a", "kind": "artist"}),
        ]:
            with self.subTest(collection=collection, params=params), self.assertRaises(ValueError):
                spotify_browser.browse_music(collection, **params)
        spotify_browser.build_spotify_client.assert_not_called()

    def test_demo_is_explicit_and_never_calls_spotify(self):
        with patch.object(spotify_browser, "is_live_spotify_configured", return_value=False):
            for collection in ("albums", "playlists", "recent"):
                result = spotify_browser.browse_music(collection)
                self.assertEqual(result["mode"], "fake")
                self.assertIn("(demo)", result["items"][0]["name"])
                self.assertIsNone(result["next"])
            self.assertEqual(spotify_browser.browse_music("search", query="no match")["items"], [])
        spotify_browser.build_spotify_client.assert_not_called()

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
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        patcher = patch.multiple(
            config.settings, DATABASE_PATH=str(Path(temporary.name) / "tags.db"),
            NFC_READER_ENABLED=False, SPOTIFY_CLIENT_ID="", SPOTIFY_CLIENT_SECRET="", SPOTIFY_REFRESH_TOKEN="",
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
            for marker in (b'id="music-search"', b'id="write-tag"', b'id="assignment"', b'/static/music.js'):
                self.assertIn(marker, page.data)
            self.assertIn(b'<details id="advanced-options" class="advanced-options">', page.data)
            self.assertIn(b'id="music-search" class="music-search" role="search" hidden', page.data)
            self.assertIn(b'id="write-selection" class="write-panel" hidden', page.data)
            self.assertIn(b'class="spotify-browser" aria-labelledby="music-view-heading"', page.data)
            self.assertIn(b'id="music-view-heading"', page.data)
            self.assertIn(b'class="music-search-input"', page.data)

    def test_connection_context_distinguishes_demo_from_saved_spotify_credentials(self):
        demo = self.client.get("/")
        self.assertIn("Demo preview — not your Spotify library".encode(), demo.data)
        with patch.multiple(config.settings, SPOTIFY_CLIENT_ID="private-id", SPOTIFY_CLIENT_SECRET="private-secret",
                            SPOTIFY_REFRESH_TOKEN="private-token"), patch("app.web.browse_music") as browse:
            page = self.client.get("/")
            self.assertIn("Checking your saved Spotify connection".encode(), page.data)
            self.assertIn(b"TapTune uses the Spotify token already saved on this device", page.data)
            for secret in (b"private-id", b"private-secret", b"private-token"):
                self.assertNotIn(secret, page.data)
            # Rendering reports configuration, not a successful API connection.
            browse.assert_not_called()

    def test_saved_assignment_keeps_advanced_form_open(self):
        response = self.client.post("/assign", data={"uid": "040102", "value": "spotify:album:abc"},
                                    follow_redirects=True)
        self.assertIn(b'<details id="advanced-options" class="advanced-options" open>', response.data)
        self.assertIn(b"Tag saved successfully", response.data)

    def test_demo_and_invalid_page(self):
        response = self.client.get("/api/music")
        self.assertEqual(response.json["mode"], "fake")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        for params in ("offset=no", "offset=-1", "collection=search&q=", "before=0", "kind=artist"):
            self.assertEqual(self.client.get("/api/music?" + params).status_code, 400)

    def test_spotify_errors_are_actionable_and_do_not_return_secrets(self):
        for error, code, status in (
            (SpotifyException(403, -1, "secret"), "spotify_permissions", 403),
            (SpotifyException(401, -1, "secret"), "spotify_auth_error", 403),
            (SpotifyOauthError("secret", error="invalid_grant"), "spotify_auth_error", 403),
            (ConnectionError("secret"), "spotify_unavailable", 502),
            (SpotifyException(500, -1, "secret"), "spotify_unavailable", 502),
        ):
            with self.subTest(code=code), patch("app.web.browse_music", side_effect=error):
                response = self.client.get("/api/music")
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json, {"error": code})
                self.assertNotIn(b"secret", response.data)

    def test_rate_limit_preserves_retry_after(self):
        error = SpotifyException(429, -1, "limit", headers={"Retry-After": "10"})
        with patch("app.web.browse_music", side_effect=error):
            response = self.client.get("/api/music")
        self.assertEqual(response.status_code, 429)
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

    def test_oauth_requests_all_browser_permissions(self):
        with patch.multiple(config.settings, SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret",
                            SPOTIFY_REFRESH_TOKEN="refresh"), \
                patch.object(spotify_service, "SpotifyOAuth") as oauth, patch.object(spotify_service, "Spotify"):
            spotify_service.build_spotify_client()
        self.assertEqual(set(oauth.call_args.kwargs["scope"].split()), {
            "user-modify-playback-state", "user-read-playback-state", "user-library-read",
            "playlist-read-private", "playlist-read-collaborative", "user-read-recently-played",
        })
        oauth.return_value.refresh_access_token.assert_called_once_with("refresh")
