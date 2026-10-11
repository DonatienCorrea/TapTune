import subprocess
import unittest
from unittest.mock import Mock, patch

from app import bluetooth, config, spotify_service
from test_device_selection import PI_DEVICE, PHONE_DEVICE, RecordingClient


class BluetoothTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF")
        patcher.start()
        self.addCleanup(patcher.stop)

    def result(self, output="", code=0):
        return subprocess.CompletedProcess([], code, output, "")

    def test_connected_speaker_is_not_reconnected(self):
        runner = Mock(return_value=self.result("Connected: yes"))
        bluetooth.ensure_speaker_connected(runner=runner)
        self.assertEqual(runner.call_count, 1)

    def test_disconnected_speaker_reconnects_and_verifies_link(self):
        runner = Mock(side_effect=[
            self.result("Connected: no"), self.result("Connection successful"),
            self.result("Connected: no"), self.result("Connected: yes"),
        ])
        sleep = Mock()
        bluetooth.ensure_speaker_connected(runner=runner, sleep=sleep)
        self.assertEqual(runner.call_args_list[1].args[0], [
            "bluetoothctl", "--timeout", "10", "connect", "AA:BB:CC:DD:EE:FF",
        ])
        sleep.assert_called_once_with(1)

    def test_concurrent_background_connection_can_succeed(self):
        runner = Mock(side_effect=[
            self.result("Connected: no"), self.result("InProgress", 1),
            self.result("Connected: yes"),
        ])
        bluetooth.ensure_speaker_connected(runner=runner, sleep=Mock())

    def test_unreachable_speaker_returns_an_actionable_error(self):
        runner = Mock(return_value=self.result("Connected: no", 1))
        with self.assertRaisesRegex(bluetooth.BluetoothNotReady, "Turn it on and tap again"):
            bluetooth.ensure_speaker_connected(runner=runner, sleep=Mock())
        self.assertEqual(runner.call_count, 8)

    def test_missing_tool_and_timeouts_are_reported(self):
        for error in (FileNotFoundError("bluetoothctl"), subprocess.TimeoutExpired("bluetoothctl", 5)):
            with self.assertRaises(bluetooth.BluetoothNotReady):
                bluetooth.ensure_speaker_connected(runner=Mock(side_effect=error))

    def test_invalid_address_and_unconfigured_speaker(self):
        runner = Mock()
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "invalid"):
            with self.assertRaises(bluetooth.BluetoothNotReady):
                bluetooth.ensure_speaker_connected(runner=runner)
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", ""):
            bluetooth.ensure_speaker_connected(runner=runner)
        runner.assert_not_called()

    def test_local_tag_checks_connection_before_spotify_and_blocks_on_failure(self):
        client = RecordingClient(current=None, devices=[PI_DEVICE])
        with patch.multiple(
            config.settings, SPOTIFY_DEVICE_NAME="TapTune",
            SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        ), patch.object(spotify_service, "build_spotify_client", return_value=client), \
                patch.object(spotify_service, "ensure_speaker_connected") as ensure:
            ensure.side_effect = bluetooth.BluetoothNotReady("Speaker is off")
            result = spotify_service.dispatch_tag_value("spotify:track:abc")
        ensure.assert_called_once_with()
        self.assertEqual(result["error"], "bluetooth_not_ready")
        self.assertEqual(client.calls, [])

    def test_other_active_device_and_fake_mode_do_not_touch_bluetooth(self):
        for live, device in ((True, PHONE_DEVICE), (False, PI_DEVICE)):
            client = RecordingClient(current={"device": device})
            with patch.multiple(
                config.settings, SPOTIFY_DEVICE_NAME="TapTune",
                SPOTIFY_CLIENT_ID="id" if live else "",
                SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
            ), patch.object(spotify_service, "build_spotify_client", return_value=client), \
                    patch.object(spotify_service, "ensure_speaker_connected") as ensure:
                spotify_service.dispatch_tag_value("action:next")
            ensure.assert_not_called()

    def test_connection_is_checked_even_before_a_missing_receiver_is_resolved(self):
        client = RecordingClient(current=None, devices=[])
        with patch.multiple(
            config.settings, SPOTIFY_DEVICE_NAME="TapTune",
            SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        ), patch.object(spotify_service, "build_spotify_client", return_value=client), \
                patch.object(spotify_service, "ensure_speaker_connected") as ensure:
            result = spotify_service.dispatch_tag_value("action:play_pause")
        ensure.assert_called_once_with()
        self.assertEqual(result["error"], "speaker_not_ready")

    def test_connected_local_receiver_starts_playback_after_the_check(self):
        client = RecordingClient(current=None, devices=[PI_DEVICE])
        with patch.multiple(
            config.settings, SPOTIFY_DEVICE_NAME="TapTune",
            SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        ), patch.object(spotify_service, "build_spotify_client", return_value=client), \
                patch.object(spotify_service, "ensure_speaker_connected") as ensure:
            ensure.side_effect = lambda: self.assertEqual(client.calls, [])
            result = spotify_service.dispatch_tag_value("spotify:track:abc")
        ensure.assert_called_once_with()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(client.calls[0][0], "start_playback")
