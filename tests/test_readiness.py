import io
import subprocess
import unittest
import wave
from unittest.mock import Mock
from unittest.mock import patch

from app import config, librespot, readiness


class ReadySoundTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="", DESKTOP_AUDIO_USER="")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_startup_sets_volume_before_announcing_readiness(self):
        post = Mock()
        with patch.multiple(config.settings, SPOTIFY_DEVICE_NAME="TapTune", SPOTIFY_INITIAL_VOLUME=10,
                            READY_SOUND_ENABLED=True), \
                patch.object(librespot, "request", return_value={"value": 30000, "max": 65535}), \
                patch.object(librespot, "post", post), \
                patch.object(readiness, "wait_until_ready_then_chime") as chime:
            chime.side_effect = lambda **kwargs: post.assert_called_once_with(
                "/player/volume", {"volume": round(10 * 65535 / 100)}) or True
            self.assertTrue(readiness.initialize_speaker(sleep=Mock()))
        chime.assert_called_once()
        self.assertIsNone(chime.call_args.kwargs["stop_event"])
        self.assertGreater(chime.call_args.kwargs["timeout_seconds"], 0)
        self.assertLessEqual(chime.call_args.kwargs["timeout_seconds"], 600)

    def test_startup_volume_waits_for_receiver_then_connects_speaker_without_chime(self):
        post = Mock()
        with patch.multiple(config.settings, SPOTIFY_DEVICE_NAME="TapTune", SPOTIFY_INITIAL_VOLUME=10,
                            READY_SOUND_ENABLED=False), \
                patch.object(librespot, "request", side_effect=[librespot.LibrespotUnavailable("starting"), None]), \
                patch.object(librespot, "post", post), \
                patch.object(readiness, "connect_speaker_at_boot", return_value=True) as connect, \
                patch.object(readiness, "wait_until_ready_then_chime") as chime:
            self.assertTrue(readiness.initialize_speaker(sleep=Mock()))
        post.assert_called_once_with("/player/volume", {"volume": 10})
        connect.assert_called_once()
        chime.assert_not_called()

    def test_startup_thread_runs_with_ready_sound_disabled(self):
        target = Mock()
        with patch.multiple(config.settings, SPOTIFY_DEVICE_NAME="TapTune", READY_SOUND_ENABLED=False):
            thread = readiness.start_speaker_thread(target=target)
            thread.join(timeout=2)
        target.assert_called_once_with()
        with patch.object(config.settings, "SPOTIFY_DEVICE_NAME", ""):
            self.assertIsNone(readiness.start_speaker_thread(target=target))

    def test_startup_volume_timeout_is_reported(self):
        with patch.object(config.settings, "SPOTIFY_DEVICE_NAME", "TapTune"), \
                patch.object(librespot, "request", side_effect=librespot.LibrespotUnavailable("down")), \
                patch.object(librespot, "post") as post, \
                self.assertLogs(readiness.logger, level="WARNING"):
            self.assertFalse(readiness.initialize_speaker(sleep=Mock(), timeout_seconds=0))
        post.assert_not_called()

    def test_chime_is_a_short_stereo_wav(self):
        with wave.open(io.BytesIO(readiness.build_chime_wav())) as sound:
            self.assertEqual(sound.getnchannels(), 2)
            self.assertEqual(sound.getsampwidth(), 2)
            duration = sound.getnframes() / sound.getframerate()
        self.assertGreater(duration, 0.2)
        self.assertLess(duration, 1.0)

    def test_chime_plays_as_loud_as_spotify_at_ten_percent(self):
        import array
        with wave.open(io.BytesIO(readiness.build_chime_wav())) as sound:
            samples = array.array("h", sound.readframes(sound.getnframes()))
        peak = max(abs(sample) for sample in samples)
        # go-librespot scales samples by volume², so 10% is 1% of full scale.
        self.assertLessEqual(peak, int(0.01 * 32767))
        self.assertGreater(peak, int(0.01 * 32767 * 0.9))

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

    def test_chime_plays_raw_audio_to_the_exact_sink_as_the_audio_user(self):
        sink = "bluez_output.AA_BB_CC_DD_EE_FF.1"
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, b"", b""))
        wav = readiness.build_chime_wav()
        with patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF", DESKTOP_AUDIO_USER="taptune"), \
                patch.object(readiness, "prepare_speaker", return_value=sink) as prepare, \
                patch.object(readiness, "desktop_command", side_effect=lambda args, user: ["runuser", *args]):
            self.assertTrue(readiness.play_ready_sound(wav, runner=runner))
        prepare.assert_called_once_with(runner=runner, connect_attempts=1, user=None)
        command = runner.call_args.args[0]
        self.assertEqual(command[:3], ["runuser", "pacat", "--playback"])
        self.assertIn(f"--device={sink}", command)
        self.assertEqual(runner.call_args.kwargs["input"], readiness._pcm_frames(wav))
        self.assertTrue(runner.call_args.kwargs["input"])

    def test_chime_failures_are_reported_not_rerouted(self):
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
        runner = Mock()
        with patch.multiple(config.settings, BLUETOOTH_SPEAKER_MAC="", DESKTOP_AUDIO_USER="taptune"):
            self.assertTrue(readiness.play_ready_sound(wav, runner=runner))
        runner.assert_not_called()

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
            runner=system, sleep=Mock(), connect_attempts=connect_attempts,
        )
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", "AA:BB:CC:DD:EE:FF"):
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


if __name__ == "__main__":
    unittest.main()
