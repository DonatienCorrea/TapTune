import io
import subprocess
import unittest
import wave
from unittest.mock import patch

from app import config, readiness


class ReadySoundTests(unittest.TestCase):
    def test_chime_is_a_short_stereo_wav(self):
        with wave.open(io.BytesIO(readiness.build_chime_wav())) as sound:
            self.assertEqual(sound.getnchannels(), 2)
            self.assertEqual(sound.getsampwidth(), 2)
            duration = sound.getnframes() / sound.getframerate()
        self.assertGreater(duration, 0.2)
        self.assertLess(duration, 1.0)

    def test_waits_for_device_then_plays_once(self):
        visible = iter([False, False, True])
        played = []
        sleeps = []

        result = readiness.wait_until_ready_then_chime(
            is_device_visible=lambda: next(visible),
            play=lambda wav: played.append(wav) or True,
            sleep=sleeps.append,
            interval_seconds=1,
        )

        self.assertTrue(result)
        self.assertEqual(len(played), 1)
        self.assertEqual(len(sleeps), 2)

    def test_retries_sound_until_speaker_connects_without_rechecking_device(self):
        checks = []
        attempts = iter([False, False, True])

        result = readiness.wait_until_ready_then_chime(
            is_device_visible=lambda: checks.append(1) or True,
            play=lambda wav: next(attempts),
            sleep=lambda seconds: None,
        )

        self.assertTrue(result)
        self.assertEqual(len(checks), 1)

    def test_gives_up_after_timeout(self):
        played = []
        result = readiness.wait_until_ready_then_chime(
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

    def test_play_sound_falls_back_to_default_device(self):
        commands = []

        def runner(command, **kwargs):
            commands.append(command)
            code = 1 if "-D" in command else 0
            return subprocess.CompletedProcess(command, code, b"", b"aplay: PCM not found")

        self.assertTrue(readiness.play_sound(b"wav", audio_device="bluealsa", runner=runner))
        self.assertEqual(commands, [["aplay", "-q", "-D", "bluealsa", "-"], ["aplay", "-q", "-"]])

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
