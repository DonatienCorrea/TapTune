import unittest
from unittest.mock import patch

from app import config, spotify_service
from test_device_selection import PI_DEVICE, PHONE_DEVICE, RecordingClient


class VolumeClient(RecordingClient):
    def volume(self, volume_percent, device_id=None):
        self.calls.append(("volume", {"volume_percent": volume_percent, "device_id": device_id}))


class VolumeTests(unittest.TestCase):
    def setUp(self):
        delay = patch.object(spotify_service, "RETRY_DELAY_SECONDS", 0)
        delay.start()
        self.addCleanup(delay.stop)
        patcher = patch.multiple(
            config.settings, SPOTIFY_DEVICE_NAME="TapTune", SPOTIFY_INITIAL_VOLUME=30,
            SPOTIFY_CLIENT_ID="", SPOTIFY_CLIENT_SECRET="", SPOTIFY_REFRESH_TOKEN="",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def dispatch(self, client, value):
        with patch.object(spotify_service, "build_spotify_client", return_value=client):
            return spotify_service.dispatch_tag_value(value)

    def test_volume_changes_by_ten_percentage_points_and_clamps(self):
        for volume, action, expected in (
            (30, "up", 40), (30, "down", 20), (95, "up", 100),
            (5, "down", 0), (100, "up", 100), (0, "down", 0),
        ):
            with self.subTest(volume=volume, action=action):
                client = VolumeClient(current={"device": PI_DEVICE | {"volume_percent": volume}})
                result = self.dispatch(client, f"action:volume_{action}")
                self.assertEqual(result, {"status": "ok", "volume_percent": expected})
                self.assertEqual(client.calls, [("volume", {"volume_percent": expected, "device_id": "pi-123"})])

    def test_volume_targets_the_current_device_not_the_pi(self):
        client = VolumeClient(current={"device": PHONE_DEVICE | {"volume_percent": 50}})
        self.dispatch(client, "action:volume_down")
        self.assertEqual(client.calls[0][1], {"volume_percent": 40, "device_id": "phone-1"})

    def test_volume_can_change_on_an_idle_receiver_without_starting_music(self):
        client = VolumeClient(devices=[PI_DEVICE | {"volume_percent": 30}])
        self.dispatch(client, "action:volume_up")
        self.assertEqual(client.calls, [("volume", {"volume_percent": 40, "device_id": "pi-123"})])

    def test_unknown_or_unsupported_volume_does_not_guess_a_value(self):
        for device in (
            PI_DEVICE, PI_DEVICE | {"volume_percent": None},
            PI_DEVICE | {"volume_percent": True}, PI_DEVICE | {"volume_percent": 101},
            PI_DEVICE | {"volume_percent": 30, "supports_volume": False},
            PI_DEVICE | {"volume_percent": 30, "is_restricted": True},
        ):
            with self.subTest(device=device):
                client = VolumeClient(current={"device": device})
                self.assertEqual(self.dispatch(client, "action:volume_up")["error"], "volume_unavailable")
                self.assertEqual(client.calls, [])

    def test_missing_receiver_is_an_explicit_error(self):
        self.assertEqual(self.dispatch(VolumeClient(), "action:volume_up")["error"], "speaker_not_ready")

    def test_fake_client_starts_at_thirty_and_tracks_volume(self):
        client = spotify_service.FakeSpotifyClient()
        self.assertEqual(client.current_playback()["device"]["volume_percent"], 30)
        self.assertEqual(self.dispatch(client, "action:volume_up")["volume_percent"], 40)
        self.assertEqual(self.dispatch(client, "action:volume_down")["volume_percent"], 30)
        self.assertFalse(client.is_playing)

    def test_volume_configuration_boundaries_and_invalid_values(self):
        self.assertEqual(config.parse_volume("0"), 0)
        self.assertEqual(config.parse_volume("100"), 100)
        for value in ("-1", "101", "30.5", "", "loud"):
            with self.assertRaisesRegex(ValueError, "SPOTIFY_INITIAL_VOLUME"):
                config.parse_volume(value)
