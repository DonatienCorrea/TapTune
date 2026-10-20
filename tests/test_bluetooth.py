import subprocess
import unittest
from unittest.mock import Mock, patch

from app import bluetooth, config, spotify_service
from test_device_selection import PI_DEVICE, PHONE_DEVICE, RecordingClient as BaseClient

MAC = "AA:BB:CC:DD:EE:FF"
SINK = "bluez_output.AA_BB_CC_DD_EE_FF.1"


class RecordingClient(BaseClient):
    def volume(self, volume_percent, device_id=None):
        self.calls.append(("volume", {"volume_percent": volume_percent, "device_id": device_id}))


def done(output="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, output, stderr)


class FakeSystem:
    """Answers bluetoothctl/pactl/amixer like a Pi, recording every command."""

    def __init__(self, connected=True, connect_works=True, sinks=None, default="alsa_output.hdmi",
                 inputs="5\t1\t42\n6\t2\t43\n", mixer=True):
        self.connected = connected
        self.connect_works = connect_works
        self.sinks = f"1\talsa_output.hdmi\n2\t{SINK}\n" if sinks is None else sinks
        self.default = default
        self.inputs = inputs
        self.mixer = mixer
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if command[:2] == ["bluetoothctl", "info"]:
            return done(f"Connected: {'yes' if self.connected else 'no'}")
        if command[0] == "bluetoothctl" and "connect" in command:
            self.connected = self.connect_works
            return done("Connection successful" if self.connect_works else "", 0 if self.connect_works else 1,
                        "" if self.connect_works else "org.bluez.Error.Failed")
        if command[0] == "bluetoothctl":
            return done()
        if command[0] == "amixer":
            if command[-1] == "scontrols":
                return done("Simple mixer control 'JBL Flip 5 A2DP',0\n") if self.mixer else done(code=1, stderr="no PCM")
            return done()
        args = command[command.index("pactl") + 1:]
        if args == ["list", "short", "sinks"]:
            return done(self.sinks)
        if args == ["get-default-sink"]:
            return done(self.default + "\n")
        if args == ["list", "short", "sink-inputs"]:
            return done(self.inputs)
        return done()

    def count(self, *prefix):
        return sum(1 for command in self.commands if command[:len(prefix)] == list(prefix))

    def pactl_calls(self):
        return [command[command.index("pactl") + 1:] for command in self.commands if "pactl" in command]


class EnsureConnectedTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC=MAC, DESKTOP_AUDIO_USER="")
        patcher.start()
        self.addCleanup(patcher.stop)
        bluetooth._output_volume_set[0] = False

    def test_connected_speaker_is_not_reconnected(self):
        runner = Mock(return_value=done("Connected: yes"))
        self.assertFalse(bluetooth.ensure_speaker_connected(runner=runner))
        self.assertEqual(runner.call_count, 1)

    def test_disconnected_speaker_reconnects_and_verifies_link(self):
        runner = Mock(side_effect=[
            done("Connected: no"), done("Connection successful"),
            done("Connected: no"), done("Connected: yes"),
        ])
        sleep = Mock()
        self.assertTrue(bluetooth.ensure_speaker_connected(runner=runner, sleep=sleep))
        self.assertEqual(runner.call_args_list[1].args[0], ["bluetoothctl", "--timeout", "10", "connect", MAC])
        sleep.assert_called_once_with(1)

    def test_speaker_reconnecting_by_itself_can_succeed(self):
        runner = Mock(side_effect=[done("Connected: no"), done("InProgress", 1), done("Connected: yes")])
        self.assertTrue(bluetooth.ensure_speaker_connected(runner=runner, sleep=Mock()))

    def test_retry_is_bounded_and_powers_adapter_between_attempts(self):
        system = FakeSystem(connected=False, connect_works=False)
        sleep = Mock()
        with self.assertRaisesRegex(bluetooth.BluetoothNotReady, "Turn it on and tap again.*Failed"):
            bluetooth.ensure_speaker_connected(runner=system, sleep=sleep)
        self.assertEqual(system.count("bluetoothctl", "--timeout"), bluetooth.CONNECT_ATTEMPTS)
        self.assertEqual(system.count("bluetoothctl", "power", "on"), bluetooth.CONNECT_ATTEMPTS - 1)
        self.assertEqual(system.count("bluetoothctl", "info"), 1 + bluetooth.CONNECT_ATTEMPTS * bluetooth.LINK_CHECKS)
        self.assertEqual(sleep.call_count, bluetooth.CONNECT_ATTEMPTS * (bluetooth.LINK_CHECKS - 1))

    def test_single_attempt_for_boot(self):
        system = FakeSystem(connected=False, connect_works=False)
        with self.assertRaises(bluetooth.BluetoothNotReady):
            bluetooth.ensure_speaker_connected(runner=system, sleep=Mock(), attempts=1)
        self.assertEqual(system.count("bluetoothctl", "--timeout"), 1)
        self.assertEqual(system.count("bluetoothctl", "power", "on"), 0)

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
            self.assertFalse(bluetooth.ensure_speaker_connected(runner=runner))
            self.assertIsNone(bluetooth.prepare_speaker(runner=runner))
        runner.assert_not_called()

    def test_lowercase_address_is_normalized(self):
        runner = Mock(return_value=done("Connected: yes"))
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", MAC.lower()):
            bluetooth.ensure_speaker_connected(runner=runner)
        self.assertEqual(runner.call_args.args[0], ["bluetoothctl", "info", MAC])


class LiteOutputTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(
            config.settings, BLUETOOTH_SPEAKER_MAC=MAC, DESKTOP_AUDIO_USER="", AUDIO_OUTPUT_DEVICE="bluealsa",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        bluetooth._output_volume_set[0] = False

    def test_new_connection_sets_bluealsa_output_to_full_volume_once(self):
        system = FakeSystem(connected=False)
        device = f"bluealsa:DEV={MAC},PROFILE=a2dp"
        self.assertEqual(bluetooth.prepare_speaker(runner=system, sleep=Mock()), device)
        self.assertIn(["amixer", "-q", "-D", device, "sset", "JBL Flip 5 A2DP", "100%", "unmute"], system.commands)
        system.commands.clear()
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        self.assertEqual(system.commands, [["bluetoothctl", "info", MAC]])

    def test_volume_is_set_again_after_the_speaker_dropped(self):
        system = FakeSystem(connected=True)
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        system.connected = False
        system.commands.clear()
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        self.assertEqual(system.count("amixer", "-q"), 1)

    def test_missing_bluealsa_output_is_bounded_and_not_success(self):
        system = FakeSystem(connected=False, mixer=False)
        sleep = Mock()
        with self.assertRaisesRegex(bluetooth.BluetoothNotReady, "BlueALSA has no output"):
            bluetooth.prepare_speaker(runner=system, sleep=sleep)
        self.assertEqual(system.count("amixer"), bluetooth.OUTPUT_CHECKS)


class DesktopOutputTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC=MAC, DESKTOP_AUDIO_USER="taptune")
        patcher.start()
        self.addCleanup(patcher.stop)
        bluetooth._output_volume_set[0] = False
        for name, value in (
            ("pwd", Mock(getpwnam=Mock(return_value=Mock(pw_uid=1000)))),
            ("getpass", Mock(getuser=Mock(return_value="root"))),
        ):
            patcher = patch.object(bluetooth, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(bluetooth.os.path, "isdir", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_system_app_runs_pactl_in_the_audio_users_session(self):
        system = FakeSystem()
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        pactl = next(command for command in system.commands if "pactl" in command)
        self.assertEqual(pactl[:6], ["runuser", "-u", "taptune", "--", "env", "XDG_RUNTIME_DIR=/run/user/1000"])

    def test_routes_default_output_and_existing_streams_to_the_exact_sink(self):
        system = FakeSystem(connected=False)
        self.assertEqual(bluetooth.prepare_speaker(runner=system, sleep=Mock()), SINK)
        calls = system.pactl_calls()
        self.assertIn(["set-sink-volume", SINK, "100%"], calls)
        self.assertIn(["set-sink-mute", SINK, "0"], calls)
        self.assertIn(["set-default-sink", SINK], calls)
        self.assertIn(["move-sink-input", "5", SINK], calls)
        self.assertNotIn(["move-sink-input", "6", SINK], calls)

    def test_already_routed_connected_speaker_keeps_its_volume(self):
        system = FakeSystem(default=SINK, inputs="6\t2\t43\n")
        bluetooth._output_volume_set[0] = True
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        self.assertEqual(system.pactl_calls(), [
            ["list", "short", "sinks"], ["get-default-sink"], ["list", "short", "sink-inputs"],
        ])

    def test_missing_sink_waits_a_bounded_time_and_never_falls_back_to_hdmi(self):
        system = FakeSystem(sinks="1\talsa_output.hdmi\n")
        with self.assertRaisesRegex(bluetooth.BluetoothNotReady, "PipeWire has no output"):
            bluetooth.prepare_speaker(runner=system, sleep=Mock())
        self.assertEqual(system.pactl_calls(), [["list", "short", "sinks"]] * bluetooth.OUTPUT_CHECKS)

    def test_routing_failure_is_an_error(self):
        def runner(command, **kwargs):
            if command[-2:] == ["set-default-sink", SINK]:
                return done(code=1, stderr="denied")
            return FakeSystem()(command)

        with self.assertRaisesRegex(bluetooth.BluetoothNotReady, "Could not route audio"):
            bluetooth.prepare_speaker(runner=runner, sleep=Mock())

    def test_audio_user_is_validated_and_needs_a_running_session(self):
        for user, message in (("root", "non-root"), ("bad user;x", "non-root")):
            with self.subTest(user=user), self.assertRaisesRegex(bluetooth.BluetoothNotReady, message):
                bluetooth.desktop_command(["pactl"], user)
        with patch.object(bluetooth.os.path, "isdir", return_value=False), \
                self.assertRaisesRegex(bluetooth.BluetoothNotReady, "enable-linger"):
            bluetooth.desktop_command(["pactl"], "taptune")
        bluetooth.pwd.getpwnam.side_effect = KeyError("nobody")
        with self.assertRaisesRegex(bluetooth.BluetoothNotReady, "does not exist"):
            bluetooth.desktop_command(["pactl"], "ghost")

    def test_same_user_runs_commands_directly(self):
        self.assertEqual(bluetooth.desktop_command(["pactl", "info"], ""), ["pactl", "info"])
        bluetooth.getpass.getuser.return_value = "taptune"
        self.assertEqual(bluetooth.desktop_command(["pactl", "info"], "taptune"), ["pactl", "info"])


class TagReconnectTests(unittest.TestCase):
    """The speaker is only woken when a tag starts or resumes music on the Pi."""

    def setUp(self):
        patcher = patch.multiple(
            config.settings, SPOTIFY_DEVICE_NAME="TapTune", BLUETOOTH_SPEAKER_MAC=MAC,
            SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        for name, value in (("RETRY_DELAY_SECONDS", 0),):
            patcher = patch.object(spotify_service, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        spotify_service.reset_state_memory()
        self.addCleanup(spotify_service.reset_state_memory)

    def dispatch(self, value, client, side_effect=None):
        with patch.object(spotify_service, "build_spotify_client", return_value=client), \
                patch.object(spotify_service, "prepare_speaker", side_effect=side_effect) as prepare:
            result = spotify_service.dispatch_tag_value(value)
        return result, prepare

    def test_content_tag_prepares_speaker_before_spotify_and_blocks_on_failure(self):
        client = RecordingClient(current=None, devices=[PI_DEVICE])
        result, prepare = self.dispatch("spotify:track:abc", client, bluetooth.BluetoothNotReady("Speaker is off"))
        prepare.assert_called_once_with()
        self.assertEqual(result["error"], "bluetooth_not_ready")
        self.assertEqual(client.calls, [])

    def test_content_tag_plays_after_the_speaker_is_ready(self):
        client = RecordingClient(current=None, devices=[PI_DEVICE])
        result, prepare = self.dispatch(
            "spotify:track:abc", client, lambda: self.assertEqual(client.calls, []),
        )
        prepare.assert_called_once_with()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(client.calls[0][0], "start_playback")

    def test_resume_on_the_pi_prepares_speaker(self):
        paused = {"is_playing": False, "device": PI_DEVICE}
        result, prepare = self.dispatch("action:play_pause", RecordingClient(current=paused))
        prepare.assert_called_once_with()
        self.assertEqual(result["status"], "ok")

    def test_resume_with_nothing_active_checks_speaker_before_missing_receiver(self):
        result, prepare = self.dispatch("action:play_pause", RecordingClient(current=None, devices=[]))
        prepare.assert_called_once_with()
        self.assertEqual(result["error"], "speaker_not_ready")

    def refusing_client(self):
        from spotipy import SpotifyException

        class RefusingClient(RecordingClient):
            def start_playback(self, **kwargs):
                self.calls.append(("start_playback", kwargs))
                raise SpotifyException(404, -1, "Device not found")

        return RefusingClient(current={"is_playing": False, "device": PHONE_DEVICE}, devices=[PI_DEVICE])

    def test_remote_resume_does_not_touch_bluetooth(self):
        client = RecordingClient(current={"is_playing": False, "device": PHONE_DEVICE}, devices=[PI_DEVICE])
        result, prepare = self.dispatch("action:play_pause", client)
        prepare.assert_not_called()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(client.calls, [("start_playback", {"device_id": "phone-1"})])

    def test_fallback_to_the_pi_after_remote_refusal_prepares_speaker_first(self):
        client = self.refusing_client()
        with self.assertLogs("app.spotify_service", "WARNING"):
            result, prepare = self.dispatch(
                "action:play_pause", client,
                lambda: self.assertNotIn("transfer_playback", [call[0] for call in client.calls]),
            )
        prepare.assert_called_once_with()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(client.calls[-1], ("transfer_playback", {"device_id": "pi-123", "force_play": True}))

    def test_fallback_is_blocked_when_the_speaker_cannot_connect(self):
        client = self.refusing_client()
        with self.assertLogs("app.spotify_service", "WARNING"):
            result, prepare = self.dispatch("action:play_pause", client, bluetooth.BluetoothNotReady("Speaker is off"))
        prepare.assert_called_once_with()
        self.assertEqual(result["error"], "bluetooth_not_ready")
        self.assertNotIn("transfer_playback", [call[0] for call in client.calls])

    def test_pause_next_and_volume_never_reconnect(self):
        playing = {"is_playing": True, "device": PI_DEVICE}
        for value in ("action:play_pause", "action:next", "action:volume_up", "action:volume_down"):
            with self.subTest(value=value):
                client = RecordingClient(current=dict(playing))
                result, prepare = self.dispatch(value, client)
                prepare.assert_not_called()
                self.assertNotEqual(result.get("error"), "bluetooth_not_ready")

    def test_other_active_device_and_fake_mode_do_not_touch_bluetooth(self):
        for live, device in ((True, PHONE_DEVICE), (False, PI_DEVICE)):
            with self.subTest(live=live), patch.object(config.settings, "SPOTIFY_CLIENT_ID", "id" if live else ""):
                client = RecordingClient(current={"is_playing": False, "device": device})
                _, prepare = self.dispatch("spotify:track:abc", client)
                prepare.assert_not_called()


if __name__ == "__main__":
    unittest.main()
