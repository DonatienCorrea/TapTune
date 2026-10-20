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

    def test_desktop_chime_plays_raw_audio_to_the_exact_sink_as_the_audio_user(self):
        sink = "bluez_output.AA_BB_CC_DD_EE_FF.1"
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, b"", b""))
        wav = readiness.build_chime_wav()
        with patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF", DESKTOP_AUDIO_USER="taptune"), \
                patch.object(readiness, "prepare_speaker", return_value=sink) as prepare, \
                patch.object(readiness, "desktop_command", side_effect=lambda args, user: ["runuser", *args]):
            self.assertTrue(readiness.play_ready_sound(wav, runner=runner))
        prepare.assert_called_once_with(runner=runner, connect_attempts=1, desktop=True, user=None)
        command = runner.call_args.args[0]
        self.assertEqual(command[:3], ["runuser", "pacat", "--playback"])
        self.assertIn(f"--device={sink}", command)
        self.assertEqual(runner.call_args.kwargs["input"], readiness._pcm_frames(wav))
        self.assertTrue(runner.call_args.kwargs["input"])

    def test_desktop_chime_failures_are_reported_not_rerouted(self):
        sink = "bluez_output.AA_BB_CC_DD_EE_FF.1"
        wav = readiness.build_chime_wav()
        with patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF", DESKTOP_AUDIO_USER="taptune"), \
                patch.object(readiness, "desktop_command", side_effect=lambda args, user: list(args)):
            runner = Mock(return_value=subprocess.CompletedProcess([], 1, b"", b"Connection refused"))
            with patch.object(readiness, "prepare_speaker", return_value=sink):
                self.assertFalse(readiness.play_ready_sound(wav, runner=runner))
            runner.assert_called_once()
            for error in (FileNotFoundError("pacat"), readiness.BluetoothNotReady("PipeWire has no output")):
                runner = Mock()
                with self.subTest(error=error), patch.object(readiness, "prepare_speaker", side_effect=error):
                    self.assertFalse(readiness.play_ready_sound(wav, runner=runner))
                runner.assert_not_called()
        with patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="", DESKTOP_AUDIO_USER="taptune"), \
                self.assertLogs(readiness.logger, level="WARNING"):
            self.assertFalse(readiness.play_ready_sound(wav, runner=Mock()))

    def test_lite_chime_connects_speaker_then_uses_aplay(self):
        with patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF", DESKTOP_AUDIO_USER=""), \
                patch.object(readiness, "prepare_speaker") as prepare, \
                patch.object(readiness, "play_sound", return_value=True) as play:
            self.assertTrue(readiness.play_ready_sound(b"wav"))
        self.assertFalse(prepare.call_args.kwargs["desktop"])
        play.assert_called_once()

    def test_boot_chime_stops_after_bounded_speaker_attempts(self):
        attempts = []
        with self.assertLogs(readiness.logger, level="WARNING") as logs:
            result = readiness.wait_until_ready_then_chime(
                is_app_ready=lambda: True,
                is_device_visible=lambda: True,
                play=lambda wav: attempts.append(1) and False,
                sleep=lambda seconds: None,
                max_play_attempts=4,
            )
        self.assertFalse(result)
        self.assertEqual(len(attempts), 4)
        self.assertIn("starts or resumes music", "\n".join(logs.output))

    def test_boot_connection_without_chime_is_bounded(self):
        prepare = Mock(side_effect=readiness.BluetoothNotReady("off"))
        sleep = Mock()
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF"), \
                self.assertLogs(readiness.logger, level="WARNING"):
            self.assertFalse(readiness.connect_speaker_at_boot(prepare=prepare, sleep=sleep, attempts=3))
        self.assertEqual(prepare.call_count, 3)
        prepare.assert_called_with(connect_attempts=1)
        self.assertEqual(sleep.call_count, 2)

    def test_boot_connects_speaker_when_the_adapter_starts_off(self):
        from test_bluetooth import FakeSystem

        system = FakeSystem(connected=False, powered=False)
        prepare = lambda connect_attempts: readiness.prepare_speaker(  # noqa: E731
            runner=system, sleep=Mock(), connect_attempts=connect_attempts, desktop=False,
        )
        with patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF", AUDIO_OUTPUT_DEVICE="hw:0"):
            self.assertTrue(readiness.connect_speaker_at_boot(prepare=prepare, sleep=Mock()))
        self.assertTrue(system.connected)
        self.assertEqual(system.count("bluetoothctl", "power", "on"), 1)

    def test_boot_connection_stops_once_connected_or_unconfigured(self):
        prepare = Mock(side_effect=[readiness.BluetoothNotReady("off"), "device"])
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF"):
            self.assertTrue(readiness.connect_speaker_at_boot(prepare=prepare, sleep=Mock()))
        self.assertEqual(prepare.call_count, 2)
        prepare = Mock()
        self.assertTrue(readiness.connect_speaker_at_boot(prepare=prepare, sleep=Mock()))
        prepare.assert_not_called()

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
