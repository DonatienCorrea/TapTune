import os
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from requests.exceptions import ConnectionError as RequestsConnectionError
from spotipy.oauth2 import SpotifyOauthError

from app import config, spotify_service

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "taptune"
SYSTEMD = REPO_ROOT / "systemd"


class SpotifyRetryTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(
            config.settings, SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret",
            SPOTIFY_REFRESH_TOKEN="token", BLUETOOTH_SPEAKER_MAC="",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_token_refresh_retries_network_errors(self):
        auth = Mock()
        auth.refresh_access_token.side_effect = [RequestsConnectionError("dns"), None]
        sleep = Mock()
        with self.assertLogs(spotify_service.logger, level="WARNING"):
            spotify_service._refresh_token_with_retries(auth, sleep=sleep)
        self.assertEqual(auth.refresh_access_token.call_count, 2)
        sleep.assert_called_once()

    def test_token_refresh_does_not_retry_revoked_credentials(self):
        auth = Mock()
        auth.refresh_access_token.side_effect = SpotifyOauthError("bad", error="invalid_grant")
        with self.assertRaises(SpotifyOauthError):
            spotify_service._refresh_token_with_retries(auth, sleep=Mock())
        auth.refresh_access_token.assert_called_once()

    def test_network_failure_while_connecting_returns_an_error_instead_of_raising(self):
        with patch.object(spotify_service, "build_spotify_client", side_effect=RequestsConnectionError("down")):
            for value in ("spotify:track:abc", "action:play_pause", "action:next", "action:volume_up"):
                with self.subTest(value=value):
                    result = spotify_service.dispatch_tag_value(value)
                    self.assertEqual(result["error"], "network_error")

    def test_auth_failure_returns_an_error_instead_of_raising(self):
        with patch.object(spotify_service, "build_spotify_client", side_effect=SpotifyOauthError("bad", error="invalid_grant")):
            self.assertEqual(spotify_service.toggle_playback()["error"], "spotify_auth_error")

    def test_receiver_missing_from_device_list_is_retried(self):
        client = Mock()
        client.current_playback.return_value = None
        client.devices.side_effect = [{"devices": []}, {"devices": [{"id": "pi", "name": "TapTune"}]}]
        with patch.object(config.settings, "SPOTIFY_DEVICE_NAME", "TapTune"), \
                patch.object(spotify_service, "build_spotify_client", return_value=client), \
                patch.object(spotify_service, "RETRY_DELAY_SECONDS", 0):
            spotify_service.play_content("spotify:playlist:abc")
        client.start_playback.assert_called_once_with(device_id="pi", context_uri="spotify:playlist:abc", position_ms=0)


class ServiceUnitTests(unittest.TestCase):
    def test_every_unit_keeps_restarting_and_never_hits_the_start_limit(self):
        for name in (
            "raspi-spotify-nfc.service", "taptune-spotifyd.user.service", "raspotify-taptune.conf",
        ):
            with self.subTest(unit=name):
                text = (SYSTEMD / name).read_text()
                self.assertIn("StartLimitIntervalSec=0", text)
                self.assertRegex(text, r"\nRestart=(always|on-failure)\n")

    def test_periodic_reconnect_and_chime_services_are_gone(self):
        units = sorted(path.name for path in SYSTEMD.iterdir() if path.suffix in {".service", ".conf"})
        self.assertEqual(units, [
            "journald-taptune.conf", "raspi-spotify-nfc.service", "raspotify-taptune.conf",
            "taptune-spotifyd.user.service",
        ])
        self.assertFalse((SYSTEMD / "taptune-bluetooth.sh").exists())

    def test_spotifyd_waits_for_network_and_restarts_after_clean_exit(self):
        text = (SYSTEMD / "taptune-spotifyd.user.service").read_text()
        self.assertIn("ExecStartPre=", text)
        self.assertIn("getent hosts", text)
        self.assertIn("Restart=always", text)

    def test_logs_are_kept_across_reboots(self):
        self.assertIn("Storage=persistent", (SYSTEMD / "journald-taptune.conf").read_text())


class TaptuneCliTests(unittest.TestCase):
    def cli(self, *args, check=True):
        env = dict(os.environ)
        env.pop("XDG_CONFIG_HOME", None)
        return subprocess.run(
            ["bash", str(CLI), "--dry-run", *args], capture_output=True, text=True, check=check, env=env,
        )

    def test_update_desktop_reinstalls_every_service_in_order(self):
        out = self.cli("--desktop", "update", "--no-pull").stdout
        self.assertNotIn("git -C", out)
        self.assertIn("requirements.txt", out)
        self.assertIn("unittest discover", out)
        self.assertLess(out.index("install-desktop-speaker.sh"), out.index("install-service.sh --desktop"))
        self.assertNotIn("taptune-ready-sound", out)
        self.assertNotIn("install-speaker.sh ", out)

    def test_update_lite_backs_up_pulls_then_reinstalls(self):
        out = self.cli("--lite", "update", "--skip-tests").stdout
        self.assertLess(out.index("data/backups"), out.index("pull --ff-only"))
        self.assertLess(out.index("pull --ff-only"), out.index("install-speaker.sh"))
        self.assertIn("install-service.sh --lite", out)
        self.assertNotIn("unittest discover", out)
        self.assertNotIn("install-desktop-speaker.sh", out)

    def test_logs_merge_system_and_user_services_in_one_journal_query(self):
        out = self.cli("logs", "-b", "-1", "-n", "50", "--", "-p", "warning").stdout
        for match in (
            "_SYSTEMD_UNIT=raspi-spotify-nfc.service", "UNIT=raspotify.service",
            "_SYSTEMD_USER_UNIT=taptune-spotifyd.service", "USER_UNIT=taptune-ready-sound.service",
        ):
            self.assertIn(match, out)
        self.assertIn("--boot -1", out)
        self.assertIn("--lines 50", out)
        self.assertTrue(out.rstrip().endswith("-p warning"))

    def test_update_app_only_never_installs_a_receiver(self):
        out = self.cli("--app-only", "update", "--no-pull", "--skip-tests").stdout
        self.assertIn("install-service.sh --app-only", out)
        self.assertNotIn("install-speaker.sh", out)
        self.assertNotIn("install-desktop-speaker.sh", out)

    def test_restart_and_status_do_not_use_removed_services(self):
        for mode in ("--lite", "--desktop"):
            with self.subTest(mode=mode):
                out = self.cli(mode, "restart").stdout
                self.assertNotIn("taptune-bluetooth", out)
                self.assertNotIn("taptune-ready-sound", out)

    def test_logs_follow(self):
        self.assertIn("--follow", self.cli("logs", "-f").stdout)

    def test_unknown_command_fails(self):
        result = self.cli("bogus", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown command", result.stderr)


if __name__ == "__main__":
    unittest.main()
