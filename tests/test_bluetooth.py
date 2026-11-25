import subprocess
import unittest
from unittest.mock import Mock, patch

from app import bluetooth, config

MAC = "AA:BB:CC:DD:EE:FF"
SINK = "bluez_output.AA_BB_CC_DD_EE_FF.1"


def done(output="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, output, stderr)


class FakeSystem:
    """Answers bluetoothctl/pactl like a Pi, recording every command."""

    def __init__(self, connected=True, connect_works=True, sinks=None, default="alsa_output.hdmi",
                 inputs="5\t1\t42\n6\t2\t43\n", powered=True):
        self.connected = connected
        self.powered = powered
        self.connect_works = connect_works
        self.sinks = f"1\talsa_output.hdmi\n2\t{SINK}\n" if sinks is None else sinks
        self.default = default
        self.inputs = inputs
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if command[:2] == ["bluetoothctl", "info"]:
            return done(f"Connected: {'yes' if self.connected else 'no'}")
        if command[1:] == ["power", "on"]:
            self.powered = True
            return done("Changing power on succeeded")
        if command[0] == "bluetoothctl" and "connect" in command:
            if not self.powered:
                return done(code=1, stderr="org.bluez.Error.NotReady")
            self.connected = self.connect_works
            return done("Connection successful" if self.connect_works else "", 0 if self.connect_works else 1,
                        "" if self.connect_works else "org.bluez.Error.Failed")
        if command[0] == "bluetoothctl":
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
            done("Connected: no"), done(), done("Connection successful"),
            done("Connected: no"), done("Connected: yes"),
        ])
        sleep = Mock()
        self.assertTrue(bluetooth.ensure_speaker_connected(runner=runner, sleep=sleep))
        self.assertEqual(runner.call_args_list[1].args[0], ["bluetoothctl", "power", "on"])
        self.assertEqual(runner.call_args_list[2].args[0], ["bluetoothctl", "--timeout", "10", "connect", MAC])
        sleep.assert_called_once_with(1)

    def test_speaker_reconnecting_by_itself_can_succeed(self):
        runner = Mock(side_effect=[done("Connected: no"), done(), done("InProgress", 1), done("Connected: yes")])
        self.assertTrue(bluetooth.ensure_speaker_connected(runner=runner, sleep=Mock()))

    def test_retry_is_bounded_and_powers_adapter_before_each_attempt(self):
        system = FakeSystem(connected=False, connect_works=False)
        sleep = Mock()
        with self.assertRaisesRegex(bluetooth.BluetoothNotReady, "Turn it on and tap again.*Failed"):
            bluetooth.ensure_speaker_connected(runner=system, sleep=sleep)
        self.assertEqual(system.count("bluetoothctl", "--timeout"), bluetooth.CONNECT_ATTEMPTS)
        self.assertEqual(system.count("bluetoothctl", "power", "on"), bluetooth.CONNECT_ATTEMPTS)
        self.assertEqual(system.count("bluetoothctl", "info"), 1 + bluetooth.CONNECT_ATTEMPTS * bluetooth.LINK_CHECKS)
        self.assertEqual(sleep.call_count, bluetooth.CONNECT_ATTEMPTS * (bluetooth.LINK_CHECKS - 1))

    def test_single_attempt_for_boot(self):
        system = FakeSystem(connected=False, connect_works=False)
        with self.assertRaises(bluetooth.BluetoothNotReady):
            bluetooth.ensure_speaker_connected(runner=system, sleep=Mock(), attempts=1)
        self.assertEqual(system.count("bluetoothctl", "--timeout"), 1)
        self.assertEqual(system.count("bluetoothctl", "power", "on"), 1)

    def test_boot_attempt_powers_on_an_adapter_that_starts_off(self):
        system = FakeSystem(connected=False, powered=False)
        self.assertTrue(bluetooth.ensure_speaker_connected(runner=system, sleep=Mock(), attempts=1))
        power = system.commands.index(["bluetoothctl", "power", "on"])
        connect = system.commands.index(["bluetoothctl", "--timeout", "10", "connect", MAC])
        self.assertLess(power, connect)

    def test_connected_speaker_never_touches_the_adapter(self):
        system = FakeSystem(connected=True, powered=False)
        self.assertFalse(bluetooth.ensure_speaker_connected(runner=system, sleep=Mock()))
        self.assertEqual(system.commands, [["bluetoothctl", "info", MAC]])

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


class PipeWireOutputTests(unittest.TestCase):
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

    def test_volume_is_set_once_per_connection(self):
        system = FakeSystem(connected=False)
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        self.assertEqual(system.pactl_calls().count(["set-sink-volume", SINK, "100%"]), 1)
        system.connected = False
        bluetooth.prepare_speaker(runner=system, sleep=Mock())
        self.assertEqual(system.pactl_calls().count(["set-sink-volume", SINK, "100%"]), 2)

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


if __name__ == "__main__":
    unittest.main()
