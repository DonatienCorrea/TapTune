import unittest
from unittest.mock import patch

from app import config, spotify_service


class RecordingClient:
    """Minimal stand-in for spotipy.Spotify that records calls."""

    def __init__(self, current=None, devices=None):
        self.current = current
        self.device_list = devices if devices is not None else []
        self.calls = []

    def current_playback(self):
        return self.current

    def devices(self):
        return {"devices": self.device_list}

    def start_playback(self, **kwargs):
        self.calls.append(("start_playback", kwargs))
        return {"status": "ok"}

    def pause_playback(self, **kwargs):
        self.calls.append(("pause_playback", kwargs))
        return {"status": "ok"}

    def next_track(self, **kwargs):
        self.calls.append(("next_track", kwargs))
        return {"status": "ok"}

    def transfer_playback(self, device_id, force_play=True):
        self.calls.append(("transfer_playback", {"device_id": device_id, "force_play": force_play}))
        return {"status": "ok"}


PI_DEVICE = {"id": "pi-123", "name": "TapTune", "is_active": False}
PHONE_DEVICE = {"id": "phone-1", "name": "Pixel", "is_active": True}


class DeviceSelectionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(config.settings, "SPOTIFY_DEVICE_NAME", "TapTune")
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_with(self, client, function, *args):
        with patch.object(spotify_service, "build_spotify_client", return_value=client):
            return function(*args)

    def test_nothing_active_plays_on_the_pi(self):
        client = RecordingClient(current=None, devices=[PHONE_DEVICE | {"is_active": False}, PI_DEVICE])
        result = self.run_with(client, spotify_service.play_content, "spotify:playlist:abc123")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            client.calls,
            [("start_playback", {"device_id": "pi-123", "context_uri": "spotify:playlist:abc123", "position_ms": 0})],
        )

    def test_device_name_match_ignores_case_and_spaces(self):
        client = RecordingClient(current=None, devices=[{"id": "pi-9", "name": " taptune "}])
        self.run_with(client, spotify_service.play_content, "spotify:track:abc123")
        self.assertEqual(client.calls[0][1]["device_id"], "pi-9")

    def test_active_device_elsewhere_keeps_playing_there(self):
        client = RecordingClient(current={"is_playing": True, "device": PHONE_DEVICE}, devices=[PHONE_DEVICE, PI_DEVICE])
        self.run_with(client, spotify_service.play_content, "spotify:track:abc123")

        self.assertEqual(
            client.calls,
            [("start_playback", {"device_id": None, "uris": ["spotify:track:abc123"], "position_ms": 0})],
        )

    def test_pi_not_visible_reports_speaker_not_ready(self):
        client = RecordingClient(current=None, devices=[])
        result = self.run_with(client, spotify_service.play_content, "spotify:album:abc123")

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["reason"], "SPEAKER_NOT_READY")
        self.assertIn("TapTune", result["message"])
        self.assertEqual(client.calls, [])

    def test_empty_device_name_restores_active_device_only_behaviour(self):
        client = RecordingClient(current=None, devices=[PI_DEVICE])
        with patch.object(config.settings, "SPOTIFY_DEVICE_NAME", ""):
            self.run_with(client, spotify_service.play_content, "spotify:track:abc123")
        self.assertIsNone(client.calls[0][1]["device_id"])

    def test_play_pause_with_nothing_active_resumes_on_the_pi(self):
        client = RecordingClient(current=None, devices=[PI_DEVICE])
        self.run_with(client, spotify_service.toggle_playback)
        self.assertEqual(client.calls, [("transfer_playback", {"device_id": "pi-123", "force_play": True})])

    def test_play_pause_pauses_the_active_device(self):
        client = RecordingClient(current={"is_playing": True}, devices=[PI_DEVICE])
        self.run_with(client, spotify_service.toggle_playback)
        self.assertEqual(client.calls, [("pause_playback", {})])

    def test_play_pause_resumes_a_paused_active_device(self):
        client = RecordingClient(current={"is_playing": False}, devices=[PI_DEVICE])
        self.run_with(client, spotify_service.toggle_playback)
        self.assertEqual(client.calls, [("start_playback", {})])

    def test_next_with_nothing_active_targets_the_pi(self):
        client = RecordingClient(current=None, devices=[PI_DEVICE])
        self.run_with(client, spotify_service.next_track)
        self.assertEqual(client.calls, [("next_track", {"device_id": "pi-123"})])

    def test_dispatch_returns_502_when_speaker_not_ready(self):
        import tempfile
        from pathlib import Path

        from app.web import create_app

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        database = patch.object(config.settings, "DATABASE_PATH", str(Path(directory.name) / "t.db"))
        database.start()
        self.addCleanup(database.stop)
        client = RecordingClient(current=None, devices=[])
        with patch.object(spotify_service, "build_spotify_client", return_value=client):
            response = create_app().test_client().post("/dispatch", data={"value": "spotify:track:abc123"})
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["result"]["error"], "speaker_not_ready")


if __name__ == "__main__":
    unittest.main()
