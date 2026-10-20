import io
import subprocess
import unittest
import wave
from unittest.mock import Mock
from unittest.mock import patch

from app import config, readiness


class ReadySoundTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_startup_sets_volume_before_announcing_readiness(self):
        client = Mock()
        client.devices.return_value = {"devices": [{"id": "pi", "name": "TapTune"}]}
        with patch.multiple(
            config.settings, SPOTIFY_DEVICE_NAME="TapTune", SPOTIFY_INITIAL_VOLUME=30,
            READY_SOUND_ENABLED=True, SPOTIFY_CLIENT_ID="id",
            SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        ), patch.object(readiness, "build_spotify_client", return_value=client), \
                patch.object(readiness, "wait_until_ready_then_chime") as chime:
            chime.side_effect = lambda **kwargs: client.volume.assert_called_once_with(30, device_id="pi") or True
            self.assertTrue(readiness.initialize_speaker(sleep=Mock()))
        chime.assert_called_once()
        self.assertIsNone(chime.call_args.kwargs["stop_event"])
        self.assertGreater(chime.call_args.kwargs["timeout_seconds"], 0)
        self.assertLessEqual(chime.call_args.kwargs["timeout_seconds"], 600)

    def test_startup_volume_targets_only_the_pi_and_does_not_need_the_chime(self):
        client = Mock()
        client.devices.return_value = {"devices": [{"id": "pi", "name": "TapTune"}]}
        with patch.multiple(config.settings, SPOTIFY_DEVICE_NAME="TapTune", SPOTIFY_INITIAL_VOLUME=30, READY_SOUND_ENABLED=False), \
                patch.object(readiness, "build_spotify_client", return_value=client):
            self.assertTrue(readiness.initialize_speaker(sleep=Mock()))
        client.volume.assert_called_once_with(30, device_id="pi")
        client.start_playback.assert_not_called()

    def test_startup_volume_waits_for_receiver_and_retries_api_failures(self):
        client = Mock()
        client.devices.side_effect = [
            {"devices": []},
            {"devices": [{"id": "pi", "name": "TapTune"}]},
            {"devices": [{"id": "pi", "name": "TapTune"}]},
        ]
        client.volume.side_effect = [RuntimeError("network unavailable"), None]
        with patch.multiple(config.settings, SPOTIFY_DEVICE_NAME="TapTune", READY_SOUND_ENABLED=False), \
                patch.object(readiness, "build_spotify_client", return_value=client):
            self.assertTrue(readiness.initialize_speaker(sleep=Mock()))
        self.assertEqual(client.volume.call_count, 2)

    def test_startup_thread_runs_with_ready_sound_disabled(self):
        target = Mock()
        with patch.multiple(
            config.settings, SPOTIFY_DEVICE_NAME="TapTune", READY_SOUND_ENABLED=False,
            SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        ):
            thread = readiness.start_speaker_thread(target=target)
            thread.join(timeout=2)
        target.assert_called_once_with()

    def test_startup_volume_timeout_is_reported(self):
        client = Mock()
        client.devices.return_value = {"devices": []}
        with patch.object(config.settings, "SPOTIFY_DEVICE_NAME", "TapTune"), \
                patch.object(readiness, "build_spotify_client", return_value=client), \
                self.assertLogs(readiness.logger, level="WARNING"):
            self.assertFalse(readiness.initialize_speaker(sleep=Mock(), timeout_seconds=0))
        client.volume.assert_not_called()

    def test_chime_is_a_short_stereo_wav(self):
        with wave.open(io.BytesIO(readiness.build_chime_wav())) as sound:
            self.assertEqual(sound.getnchannels(), 2)
            self.assertEqual(sound.getsampwidth(), 2)
            duration = sound.getnframes() / sound.getframerate()
        self.assertGreater(duration, 0.2)
        self.assertLess(duration, 1.0)

    def test_chime_plays_at_half_its_original_volume(self):
        import array
        with wave.open(io.BytesIO(readiness.build_chime_wav())) as sound:
            samples = array.array("h", sound.readframes(sound.getnframes()))
        peak = max(abs(sample) for sample in samples)
        self.assertLessEqual(peak, int(0.35 / 2 * 32767))
        self.assertGreater(peak, int(0.35 / 2 * 32767 * 0.9))

    def test_waits_for_device_then_plays_once(self):
        visible = iter([False, False, True])
        played = []
        sleeps = []

        result = readiness.wait_until_ready_then_chime(
            is_app_ready=lambda: True,
            is_device_visible=lambda: next(visible),
            play=lambda wav: played.append(wav) or True,
            sleep=sleeps.append,
            interval_seconds=1,
        )

        self.assertTrue(result)
        self.assertEqual(len(played), 1)
        self.assertEqual(len(sleeps), 2)

    def test_retries_sound_and_rechecks_spotify_until_speaker_connects(self):
        checks = []
        attempts = iter([False, False, True])

        result = readiness.wait_until_ready_then_chime(
            is_app_ready=lambda: True,
            is_device_visible=lambda: checks.append(1) or True,
            play=lambda wav: next(attempts),
            sleep=lambda seconds: None,
        )

        self.assertTrue(result)
        self.assertEqual(len(checks), 3)

    def test_gives_up_after_timeout(self):
        played = []
        result = readiness.wait_until_ready_then_chime(
            is_app_ready=lambda: True,
            is_device_visible=lambda: False,
            play=played.append,
            sleep=lambda seconds: None,
            interval_seconds=5,
            timeout_seconds=20,
        )
        self.assertFalse(result)
        self.assertEqual(played, [])

    def test_play_sound_uses_aplay_with_configured_device(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, b"", b"")

        self.assertTrue(readiness.play_sound(b"wav", audio_device="bluealsa", runner=runner))
        self.assertEqual(calls[0][0], ["aplay", "-q", "-D", "bluealsa", "-"])
        self.assertEqual(calls[0][1]["input"], b"wav")

    def test_play_sound_reports_failure_without_raising(self):
        def failing(command, **kwargs):
            return subprocess.CompletedProcess(command, 1, b"", b"no such device")

        def missing(command, **kwargs):
            raise FileNotFoundError("aplay")

        self.assertFalse(readiness.play_sound(b"wav", audio_device="bluealsa", runner=failing))
        self.assertFalse(readiness.play_sound(b"wav", audio_device="bluealsa", runner=missing))

    def test_play_sound_does_not_falsely_announce_readiness_on_hdmi(self):
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            code = 1 if "-D" in command else 0
            return subprocess.CompletedProcess(command, code, b"", b"aplay: PCM not found")

        self.assertFalse(readiness.play_sound(b"wav", audio_device="bluealsa", runner=runner))
        self.assertEqual(commands, [["aplay", "-q", "-D", "bluealsa", "-"]])

    def test_lite_chime_targets_configured_speaker(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, b"", b""))
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF"):
            self.assertTrue(readiness.play_sound(b"wav", audio_device="bluealsa", runner=runner))
        self.assertEqual(runner.call_args.args[0], [
            "aplay", "-q", "-D", "bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp", "-",
        ])

    def test_no_chime_until_app_and_reader_are_ready(self):
        app_checks = iter([False, False, True])
        visible = Mock(return_value=True)
        play = Mock(return_value=True)
        self.assertTrue(readiness.wait_until_ready_then_chime(
            is_app_ready=lambda: next(app_checks), is_device_visible=visible,
            play=play, sleep=Mock(),
        ))
        visible.assert_called_once_with()
        play.assert_called_once()

    def test_receiver_disappearing_cannot_trigger_a_chime(self):
        visible = iter([True, False])
        play = Mock(return_value=False)
        self.assertFalse(readiness.wait_until_ready_then_chime(
            is_app_ready=lambda: True, is_device_visible=lambda: next(visible),
            play=play, sleep=Mock(), timeout_seconds=5,
        ))
        play.assert_called_once()

    def test_app_probe_requires_live_ready_response_and_handles_failures(self):
        for payload, expected in (
            (b'{"app":"TapTune","status":"ready"}', True),
            (b'{"app":"TapTune","status":"not_ready"}', False),
            (b'{"app":"Other","status":"ready"}', False),
            (b'[]', False), (b'not json', False),
        ):
            with self.subTest(payload=payload), patch.object(readiness, "urlopen", return_value=io.BytesIO(payload)):
                self.assertEqual(readiness.app_ready(), expected)
        with patch.object(readiness, "urlopen", side_effect=ConnectionRefusedError()):
            self.assertFalse(readiness.app_ready())

    def test_desktop_sound_checks_link_and_routes_to_exact_bluetooth_sink(self):
        sink = "bluez_output.AA_BB_CC_DD_EE_FF.1"
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            output = {
                "bluetoothctl": "Connected: yes\n",
                "list": f"1 alsa_output.hdmi\n2 {sink}\n",
                "get-default-sink": sink + "\n",
            }.get(command[0] if command[0] == "bluetoothctl" else command[1], "")
            if command[0] == "paplay":
                with open(command[-1], "rb") as sound:
                    self.assertEqual(sound.read(), b"wav")
            return subprocess.CompletedProcess(command, 0, output, "")

        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF"):
            self.assertTrue(readiness.play_desktop_sound(b"wav", runner=runner))
        self.assertEqual(commands[0], ["bluetoothctl", "info", "AA:BB:CC:DD:EE:FF"])
        self.assertEqual(commands[-1][:3], ["paplay", "--device", sink])

    def test_desktop_chime_waits_for_routing_and_reports_audio_failures(self):
        sink = "bluez_output.AA_BB_CC_DD_EE_FF.1"
        for default, audio_code in (("alsa_output.hdmi", 0), (sink, 1)):
            with self.subTest(default=default, code=audio_code):
                runner = Mock(side_effect=[
                    subprocess.CompletedProcess([], 0, f"2 {sink}\n", ""),
                    subprocess.CompletedProcess([], 0, default, ""),
                    subprocess.CompletedProcess([], audio_code, "", "Audio unavailable"),
                ])
                with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF"), \
                        patch.object(readiness, "ensure_speaker_connected"):
                    self.assertFalse(readiness.play_desktop_sound(b"wav", runner=runner))
                if default != sink:
                    self.assertEqual(runner.call_count, 2)

    def test_desktop_sound_missing_tools_or_disconnected_speaker_are_not_ready(self):
        for error in (FileNotFoundError("pactl"), readiness.BluetoothNotReady("Speaker off")):
            with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF"), \
                    patch.object(readiness, "ensure_speaker_connected", side_effect=error):
                self.assertFalse(readiness.play_desktop_sound(b"wav", runner=Mock()))

    def test_desktop_command_selects_user_audio_and_reports_readiness_failure(self):
        with patch.multiple(
            config.settings, READY_SOUND_ENABLED=True, SPOTIFY_DEVICE_NAME="TapTune",
            SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        ), patch("sys.argv", ["readiness", "--desktop"]), \
                patch.object(readiness, "wait_until_ready_then_chime", return_value=False) as wait:
            self.assertEqual(readiness.main(), 1)
        wait.assert_called_once_with(play=readiness.play_desktop_sound)

    def test_sound_command_skips_only_explicit_disable_not_missing_credentials(self):
        with patch("sys.argv", ["readiness", "--desktop"]), \
                patch.object(readiness, "wait_until_ready_then_chime") as wait:
            with patch.object(config.settings, "READY_SOUND_ENABLED", False):
                self.assertEqual(readiness.main(), 0)
            with patch.multiple(config.settings, READY_SOUND_ENABLED=True, SPOTIFY_CLIENT_ID=""), \
                    self.assertLogs(readiness.logger, level="ERROR"):
                self.assertEqual(readiness.main(), 2)
        wait.assert_not_called()

    def test_aplay_error_summary_drops_bluealsa_noise(self):
        noise = "D: bluealsa-pcm.c:475: Closing\naplay: main:850: erreur\nALSA lib x: PCM not found"
        self.assertEqual(readiness._summarize_aplay_error(noise), "aplay: main:850: erreur")
        self.assertEqual(readiness._summarize_aplay_error(""), "no error output")

    def test_thread_is_skipped_in_fake_mode_or_when_disabled(self):
        started = []
        with patch.multiple(config.settings, SPOTIFY_CLIENT_ID="", READY_SOUND_ENABLED=True):
            self.assertIsNone(readiness.start_readiness_thread(target=lambda: started.append(1)))
        with patch.multiple(
            config.settings,
            SPOTIFY_CLIENT_ID="id",
            SPOTIFY_CLIENT_SECRET="secret",
            SPOTIFY_REFRESH_TOKEN="token",
            READY_SOUND_ENABLED=False,
        ):
            self.assertIsNone(readiness.start_readiness_thread(target=lambda: started.append(1)))
        self.assertEqual(started, [])

    def test_thread_starts_when_live_and_enabled(self):
        started = []
        with patch.multiple(
            config.settings,
            SPOTIFY_CLIENT_ID="id",
            SPOTIFY_CLIENT_SECRET="secret",
            SPOTIFY_REFRESH_TOKEN="token",
            READY_SOUND_ENABLED=True,
            SPOTIFY_DEVICE_NAME="TapTune",
        ):
            thread = readiness.start_readiness_thread(target=lambda: started.append(1))
            thread.join(timeout=2)
        self.assertEqual(started, [1])


if __name__ == "__main__":
    unittest.main()
