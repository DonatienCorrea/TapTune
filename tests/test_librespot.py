import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

from app import config, librespot, readiness, setup, spotify_service
from app.web import create_app


class FakeResponse(io.BytesIO):
    def __init__(self, status, body=b""):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class ClientTests(unittest.TestCase):
    def test_no_session_is_none_and_json_is_decoded(self):
        self.assertIsNone(librespot.status(opener=lambda req, timeout: FakeResponse(204)))
        body = json.dumps({"username": "ana"}).encode()
        self.assertEqual(librespot.status(opener=lambda req, timeout: FakeResponse(200, body)), {"username": "ana"})
        with self.assertRaises(librespot.NotLoggedIn):
            librespot.require_session(opener=lambda req, timeout: FakeResponse(204))

    def test_posts_json_to_the_local_api(self):
        seen = {}

        def opener(req, timeout):
            seen.update(url=req.full_url, method=req.get_method(), body=json.loads(req.data))
            return FakeResponse(200)

        with patch.object(config.settings, "LIBRESPOT_API_URL", "http://127.0.0.1:3678"):
            librespot.post("/player/play", {"uri": "spotify:album:a"}, opener=opener)
        self.assertEqual(seen, {"url": "http://127.0.0.1:3678/player/play", "method": "POST",
                                "body": {"uri": "spotify:album:a"}})

    def test_errors_and_unreachable_api(self):
        def http_error(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, None)

        with self.assertRaises(librespot.LibrespotError) as raised:
            librespot.post("/player/next", opener=http_error)
        self.assertEqual(raised.exception.status, 500)

        def refused(req, timeout):
            raise urllib.error.URLError(ConnectionRefusedError())

        with self.assertRaises(librespot.LibrespotUnavailable):
            librespot.status(opener=refused)

    def test_devices_before_a_cluster_exists_is_none(self):
        def not_found(req, timeout):
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, None)

        self.assertIsNone(librespot.devices(opener=not_found))

    def test_parse_receiver(self):
        self.assertEqual(config.parse_receiver(""), "legacy")
        self.assertEqual(config.parse_receiver(" Go-Librespot "), "go-librespot")
        with self.assertRaises(ValueError):
            config.parse_receiver("raspotify")


SELF = {"id": "pi", "name": "TapTune", "is_self": True, "volume": 0}
PHONE = {"id": "phone", "name": "Pixel", "is_self": False, "is_offline": False, "volume": 32768}


class FakeLibrespot:
    """Stands in for go-librespot's local API and records the calls."""

    def __init__(self, status=None, cluster=None, volume=None, token="tok"):
        self.state = status
        self.cluster = cluster if cluster is not None else {"active_device_id": None, "devices": [SELF]}
        self.volume = volume or {"value": 30, "max": 100}
        self.access_token = token
        self.posts = []

    def status(self):
        return self.state

    def require_session(self):
        if self.state is None:
            raise librespot.NotLoggedIn()
        return self.state

    def devices(self):
        return self.cluster

    def token(self):
        return self.access_token

    def post(self, path, body=None):
        self.posts.append((path, body))

    def request(self, method, path, body=None):
        assert (method, path) == ("GET", "/player/volume")
        return self.volume


class PlaybackTests(unittest.TestCase):
    def setUp(self):
        for p in (patch.multiple(config.settings, SPOTIFY_RECEIVER="go-librespot", SPOTIFY_DEVICE_NAME="TapTune",
                                 BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF", SPOTIFY_CLIENT_ID="",
                                 SPOTIFY_CLIENT_SECRET="", SPOTIFY_REFRESH_TOKEN=""),
                  patch("app.spotify_service.build_spotify_client", side_effect=AssertionError("Web API used"))):
            p.start()
            self.addCleanup(p.stop)
        self.prepare = patch("app.spotify_service.prepare_speaker").start()
        self.addCleanup(patch.stopall)

    def use(self, fake):
        for name in ("status", "require_session", "devices", "token", "post", "request"):
            p = patch.object(librespot, name, getattr(fake, name))
            p.start()
            self.addCleanup(p.stop)
        return fake

    def test_no_developer_app_is_needed(self):
        self.assertFalse(spotify_service.is_live_spotify_configured())
        self.assertTrue(spotify_service.is_playback_configured())

    def test_track_album_and_playlist_tags_play_on_the_pi(self):
        fake = self.use(FakeLibrespot(status={"username": "ana"}))
        for uri in ("spotify:track:t", "spotify:album:a", "spotify:playlist:p"):
            with self.subTest(uri=uri):
                result = spotify_service.dispatch_tag_value(uri)
                self.assertEqual(result, {"status": "ok", "mode": "go-librespot", "device": "TapTune"})
                self.assertEqual(fake.posts[-1], ("/player/play", {"uri": uri}))
        self.assertEqual(self.prepare.call_count, 3)

    def test_show_tag_starts_its_latest_episode_with_the_receivers_token(self):
        fake = self.use(FakeLibrespot(status={}))
        episode = {"uri": "spotify:episode:new", "name": "Latest"}
        with patch("app.spotify_service.Spotify") as client, \
                patch("app.spotify_service._latest_episode", return_value=episode) as latest:
            result = spotify_service.play_content("spotify:show:s")
        self.assertEqual(client.call_args.kwargs["auth"], "tok")
        self.assertEqual(latest.call_args.args[1], "s")
        self.assertEqual(fake.posts, [("/player/play", {"uri": "spotify:show:s", "skip_to_uri": "spotify:episode:new"})])
        self.assertEqual(result["episode_name"], "Latest")
        self.assertEqual(result["uri"], "spotify:episode:new")

    def test_show_lookup_failure_plays_the_show_and_empty_show_is_reported(self):
        fake = self.use(FakeLibrespot(status={}, token=None))
        result = spotify_service.play_content("spotify:show:s")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(fake.posts, [("/player/play", {"uri": "spotify:show:s"})])
        with patch("app.spotify_service.Spotify"), patch("app.spotify_service._latest_episode", return_value=None):
            fake.access_token = "tok"
            self.assertEqual(spotify_service.play_content("spotify:show:s")["error"], "show_no_episodes")

    def test_show_lookup_falls_back_between_developer_credentials_and_receiver_token(self):
        episode = {"uri": "spotify:episode:new", "name": "Latest"}
        creds = patch.multiple(config.settings, SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="s",
                               SPOTIFY_REFRESH_TOKEN="r")
        creds.start()
        self.addCleanup(creds.stop)
        dev_client, receiver_client = object(), object()
        lookups = {id(dev_client): episode, id(receiver_client): episode}

        def lookup(client, _show_id):
            return lookups[id(client)]

        # Receiver token missing: the developer-app credentials still find the newest episode.
        fake = self.use(FakeLibrespot(status={}, token=None))
        with patch("app.spotify_service.build_spotify_client", return_value=dev_client), \
                patch("app.spotify_service._latest_episode", side_effect=lookup):
            self.assertEqual(spotify_service.play_content("spotify:show:s")["uri"], "spotify:episode:new")
        # Developer credentials failing: the receiver's token is used instead.
        fake.access_token = "tok"
        with patch("app.spotify_service.build_spotify_client", side_effect=RuntimeError("revoked")), \
                patch("app.spotify_service.Spotify", return_value=receiver_client), \
                patch("app.spotify_service._latest_episode", side_effect=lookup):
            self.assertEqual(spotify_service.play_content("spotify:show:s")["uri"], "spotify:episode:new")
        self.assertEqual([body["skip_to_uri"] for _, body in fake.posts], ["spotify:episode:new"] * 2)

    def test_active_phone_receives_the_commands_instead_of_the_pi(self):
        cluster = {"active_device_id": "phone", "devices": [SELF, PHONE], "now_playing": {"playing": True}}
        fake = self.use(FakeLibrespot(status={}, cluster=cluster))
        self.assertEqual(spotify_service.play_content("spotify:album:a")["device"], "Pixel")
        spotify_service.toggle_playback()
        spotify_service.next_track()
        self.assertEqual(spotify_service.change_volume(10)["volume_percent"], 60)
        self.assertEqual([body for _, body in fake.posts], [
            {"device_id": "phone", "endpoint": "play", "uri": "spotify:album:a"},
            {"device_id": "phone", "endpoint": "pause"},
            {"device_id": "phone", "endpoint": "skip_next"},
            {"device_id": "phone", "endpoint": "set_volume", "volume": round(60 * 65535 / 100)},
        ])
        self.prepare.assert_not_called()

    def test_play_pause_on_the_pi(self):
        fake = self.use(FakeLibrespot(status={"stopped": False, "paused": False, "track": {}}))
        spotify_service.toggle_playback()
        fake.state = {"stopped": False, "paused": True, "track": {"uri": "x"}}
        spotify_service.toggle_playback()
        fake.state = {"stopped": True, "paused": False}
        spotify_service.toggle_playback()
        self.assertEqual(fake.posts, [("/player/pause", None), ("/player/resume", None),
                                      ("/connect/transfer", {"device_id": "pi"})])
        self.assertEqual(self.prepare.call_count, 2)

    def test_nothing_to_resume_before_any_cluster(self):
        self.use(FakeLibrespot(status={"stopped": True}, cluster={}))
        self.assertEqual(spotify_service.toggle_playback()["error"], "nothing_to_resume")

    def test_next_and_volume_on_the_pi_never_wake_the_speaker(self):
        fake = self.use(FakeLibrespot(status={}, volume={"value": 95, "max": 100}))
        spotify_service.next_track()
        self.assertEqual(spotify_service.change_volume(10)["volume_percent"], 100)
        self.assertEqual(fake.posts, [("/player/next", None), ("/player/volume", {"volume": 100})])
        self.prepare.assert_not_called()

    def test_not_signed_in_and_receiver_down_are_explained(self):
        self.use(FakeLibrespot(status=None))
        result = spotify_service.play_content("spotify:track:t")
        self.assertEqual(result["error"], "spotify_not_logged_in")
        self.assertIn("TapTune", result["message"])
        with patch.object(librespot, "require_session", side_effect=librespot.LibrespotUnavailable("down")):
            self.assertEqual(spotify_service.play_content("spotify:track:t")["error"], "speaker_not_ready")


class ReadinessTests(unittest.TestCase):
    def setUp(self):
        p = patch.multiple(config.settings, SPOTIFY_RECEIVER="go-librespot", SPOTIFY_DEVICE_NAME="TapTune",
                           SPOTIFY_CLIENT_ID="", READY_SOUND_ENABLED=True)
        p.start()
        self.addCleanup(p.stop)

    def test_speaker_is_ready_only_once_signed_in(self):
        with patch.object(librespot, "status", return_value=None):
            self.assertFalse(readiness.speaker_device_visible())
        with patch.object(librespot, "status", side_effect=librespot.LibrespotUnavailable("down")):
            self.assertFalse(readiness.speaker_device_visible())
        with patch.object(librespot, "status", return_value={"username": "ana"}):
            self.assertTrue(readiness.speaker_device_visible())
        self.assertTrue(readiness.should_announce_ready())


class SetupStepTests(unittest.TestCase):
    def setUp(self):
        p = patch.multiple(config.settings, SPOTIFY_RECEIVER="go-librespot", SPOTIFY_DEVICE_NAME="TapTune",
                           SPOTIFY_CLIENT_ID="", BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF")
        p.start()
        self.addCleanup(p.stop)

    def test_spotify_step_detects_the_sign_in(self):
        with patch.object(librespot, "status", return_value=None):
            self.assertEqual(setup.spotify_status(), {"id": "spotify", "state": "todo",
                                                      "reason": "not_logged_in", "detail": "TapTune"})
        with patch.object(librespot, "status", return_value={"username": "ana"}):
            self.assertEqual(setup.spotify_status()["state"], "done")
        with patch.object(librespot, "status", side_effect=librespot.LibrespotUnavailable("down")):
            self.assertEqual(setup.spotify_status()["reason"], "receiver_unavailable")

    def test_saved_sign_in_counts_as_manual_configuration(self):
        with tempfile.TemporaryDirectory() as home, \
                patch.object(config.settings, "DESKTOP_AUDIO_USER", ""), \
                patch("app.setup.Path.home", return_value=Path(home)):
            self.assertFalse(setup.configured_manually())
            credentials = Path(home) / ".config/go-librespot/credentials.json"
            credentials.parent.mkdir(parents=True)
            credentials.write_text("{}")
            self.assertTrue(setup.configured_manually())

    def test_wizard_tells_how_to_sign_in_in_both_languages(self):
        steps = [{"id": "wifi", "state": "done", "reason": "connected", "detail": ""},
                 {"id": "bluetooth", "state": "done", "reason": "connected", "detail": ""},
                 {"id": "spotify", "state": "todo", "reason": "not_logged_in", "detail": "TapTune"}]
        with tempfile.TemporaryDirectory() as directory, \
                patch.multiple(config.settings, SETUP_SKIP=False, DATABASE_PATH=str(Path(directory) / "t.db")), \
                patch("app.setup.setup_steps", return_value=steps):
            client = create_app().test_client()
            en = client.get("/setup").get_data(as_text=True)
            fr = client.get("/fr/setup").get_data(as_text=True)
        self.assertIn("open Spotify → Devices → TapTune", en)
        self.assertIn("ouvrez Spotify → Appareils → TapTune", fr)
        self.assertIn('http-equiv="refresh"', en)
        self.assertNotIn("SPOTIFY_*", en)


if __name__ == "__main__":
    unittest.main()
