import os
import shutil
import socket
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "taptune"
SYSTEMD = REPO_ROOT / "systemd"


class ServiceUnitTests(unittest.TestCase):
    def test_every_unit_keeps_restarting_and_never_hits_the_start_limit(self):
        for name in ("raspi-spotify-nfc.service", "taptune-go-librespot.user.service"):
            with self.subTest(unit=name):
                text = (SYSTEMD / name).read_text()
                self.assertIn("StartLimitIntervalSec=0", text)
                self.assertRegex(text, r"\nRestart=(always|on-failure)\n")

    def test_logs_are_kept_across_reboots(self):
        self.assertIn("Storage=persistent", (SYSTEMD / "journald-taptune.conf").read_text())


class TaptuneCliTests(unittest.TestCase):
    def cli(self, *args, check=True):
        env = dict(os.environ)
        env.pop("XDG_CONFIG_HOME", None)
        return subprocess.run(
            ["bash", str(CLI), "--dry-run", *args], capture_output=True, text=True, check=check, env=env,
        )

    def test_update_backs_up_pulls_then_reinstalls_every_service_in_order(self):
        out = self.cli("update").stdout
        order = ["data/backups", "pull --ff-only", "requirements-pi.txt", "unittest discover -s tests -q --buffer",
                 "install-go-librespot.sh --dry-run", "install-service.sh --dry-run", "/health"]
        positions = [out.index(step) for step in order]
        self.assertEqual(positions, sorted(positions))

    def test_update_options_skip_the_download_and_tests(self):
        out = self.cli("update", "--no-pull", "--skip-tests").stdout
        self.assertNotIn("git -C", out)
        self.assertNotIn("unittest discover", out)
        self.assertIn("install-service.sh", out)

    def test_update_accepts_the_mode_flags_older_versions_pass_after_pulling(self):
        out = self.cli("--lite", "update", "--after-pull", "--skip-tests").stdout
        self.assertNotIn("data/backups", out)
        self.assertNotIn("pull --ff-only", out)
        self.assertIn("install-go-librespot.sh", out)

    def test_logs_merge_system_and_user_services_in_one_journal_query(self):
        out = self.cli("logs", "-b", "-1", "-n", "50", "--", "-p", "warning").stdout
        for match in (
            "_SYSTEMD_UNIT=raspi-spotify-nfc.service", "UNIT=taptune-web-update.service",
            "_SYSTEMD_USER_UNIT=taptune-go-librespot.service", "USER_UNIT=wireplumber.service",
        ):
            self.assertIn(match, out)
        for removed in ("raspotify", "spotifyd", "bluealsa"):
            self.assertNotIn(removed, out)
        self.assertIn("--boot -1", out)
        self.assertIn("--lines 50", out)
        self.assertTrue(out.rstrip().endswith("-p warning"))

    def test_restart_uses_the_go_librespot_audio_stack(self):
        out = self.cli("restart").stdout
        self.assertIn("systemctl --user restart wireplumber.service taptune-go-librespot.service", out)
        self.assertLess(out.index("taptune-go-librespot"), out.index("restart raspi-spotify-nfc.service"))

    def test_status_distinguishes_a2dp_from_other_or_missing_speaker_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            shutil.copy2(CLI, repo / "taptune")
            (repo / "systemd").mkdir()
            shutil.copy2(SYSTEMD / "install-common.sh", repo / "systemd")
            (repo / ".env").write_text("BLUETOOTH_SPEAKER_MAC=aa:bb:cc:dd:ee:ff\n")
            bin_dir = repo / "bin"
            bin_dir.mkdir()
            for tool, script in (
                ("systemctl", "echo active"),
                ("python3", "cat >/dev/null; echo '{}'"),
                ("bluetoothctl", "echo 'Connected: yes'"),
                ("pactl", '[ "$*" = "list cards" ] && [ "$LC_ALL" = C ] && printf "%s\\n" "$CARDS"'),
            ):
                executable = bin_dir / tool
                executable.write_text(f"#!/bin/sh\n{script}\n")
                executable.chmod(0o755)
            other_card = "Card #1\n\tName: bluez_card.00_11_22_33_44_55\n\tActive Profile: a2dp-sink\n"
            for profile, expected in (
                ("a2dp-sink-sbc_xq", "a2dp-sink-sbc_xq (A2DP)"),
                ("headset-head-unit", "headset-head-unit (not A2DP)"),
                ("", "unavailable (no active profile for this speaker)"),
            ):
                with self.subTest(profile=profile):
                    cards = other_card
                    if profile:
                        cards += ("Card #2\n\tName: bluez_card.AA_BB_CC_DD_EE_FF\n"
                                  "\tProfiles:\n\t\ta2dp-sink: High Fidelity Playback (A2DP Sink)\n"
                                  f"\tActive Profile: {profile}\n")
                    env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", CARDS=cards)
                    result = subprocess.run(
                        ["bash", str(repo / "taptune"), "--dry-run", "status"],
                        env=env, capture_output=True, text=True, check=True,
                    )
                    self.assertIn(f"Bluetooth audio profile: {expected}\n", result.stdout)

    def test_restart_and_update_fail_when_the_app_never_answers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "TapTune"
            shutil.copytree(SYSTEMD, repo / "systemd")
            shutil.copy(CLI, repo / "taptune")
            for name in ("install-go-librespot.sh", "install-service.sh"):
                (repo / "systemd" / name).write_text("exit 0\n")
            for name in ("requirements.txt", "requirements-pi.txt"):
                shutil.copy(REPO_ROOT / name, repo / name)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            (repo / ".env").write_text(f"APP_PORT={port}\n")
            python = repo / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            # Health probes run `python - URL`; make them fail, everything else succeed.
            python.write_text('#!/bin/sh\n[ "$1" = - ] && { cat >/dev/null; echo "not answering"; exit 1; }\nexit 0\n')
            bin_dir = root / "bin"
            bin_dir.mkdir()
            (bin_dir / "sudo").write_text('#!/bin/sh\n[ "$1" = tee ] && cat >/dev/null\nexit 0\n')
            (bin_dir / "systemctl").write_text("#!/bin/sh\nexit 0\n")
            for tool in (python, bin_dir / "sudo", bin_dir / "systemctl"):
                tool.chmod(0o755)
            env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", TAPTUNE_HEALTH_ATTEMPTS="1")
            env.pop("XDG_CONFIG_HOME", None)
            for args, message in (
                (["restart"], "restart failed"),
                (["update", "--no-pull", "--skip-tests"], "TapTune is not running"),
            ):
                with self.subTest(args=args):
                    result = subprocess.run(
                        ["bash", str(repo / "taptune"), *args],
                        env=env, capture_output=True, text=True, timeout=60,
                    )
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("did not answer", result.stderr)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn("Update finished", result.stdout)

    def test_logs_follow(self):
        self.assertIn("--follow", self.cli("logs", "-f").stdout)

    def test_unknown_command_fails(self):
        result = self.cli("bogus", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown command", result.stderr)


class TaptuneResetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        shutil.copy2(CLI, self.repo / "taptune")
        (self.repo / "systemd").mkdir()
        shutil.copy2(SYSTEMD / "install-common.sh", self.repo / "systemd")
        (self.repo / ".env").write_text("BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF\n")
        bin_dir = self.repo / "bin"
        bin_dir.mkdir()
        hotspot = "bed69db1-17dc-419b-bbac-3eff35e29389"
        (bin_dir / "nmcli").write_text(
            "#!/bin/sh\n"
            "if [ \"$1\" = --show-secrets ]; then echo 0123456789abcdef0123; "
            "else printf '%s\\n' "
            f"'{hotspot}:802-11-wireless' 'aaaa-1111:802-11-wireless' 'eeee-0000:802-3-ethernet' "
            "'bbbb-2222:802-11-wireless'; fi\n"
        )
        (bin_dir / "nmcli").chmod(0o755)
        (bin_dir / "sudo").write_text("#!/bin/sh\nexec \"$@\"\n")
        (bin_dir / "sudo").chmod(0o755)
        (bin_dir / "qrencode").write_text("#!/bin/sh\nprintf 'QR[%s]\\n' \"$(cat)\"\n")
        (bin_dir / "qrencode").chmod(0o755)
        for tool in ("systemctl", "bluetoothctl"):
            (bin_dir / tool).write_text("#!/bin/sh\nexit 0\n")
            (bin_dir / tool).chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", HOME=str(self.repo))
        self.env.pop("XDG_CONFIG_HOME", None)

    def reset(self, *flags, dry_run=True):
        args = ["bash", str(self.repo / "taptune"), *(["--dry-run"] if dry_run else []), "reset", *flags]
        return subprocess.run(args, env=self.env, capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_reset_signs_out_forgets_speaker_and_wifi_but_keeps_tags(self):
        result = self.reset()
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        steps = [
            "env.", "systemctl stop raspi-spotify-nfc.service", "go-librespot/state.json", "go-librespot/credentials.json",
            "bluetoothctl remove AA:BB:CC:DD:EE:FF", "write_env", "data/setup_complete", "nmcli\\ connection\\ delete",
        ]
        positions = [out.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        wifi = out[positions[-1]:]
        for uuid in ("aaaa-1111", "bbbb-2222"):
            self.assertIn(f"nmcli\\ connection\\ delete\\ uuid\\ {uuid}", wifi)
        for kept in ("bed69db1-17dc-419b-bbac-3eff35e29389", "eeee-0000"):
            self.assertNotIn(kept, wifi)
        self.assertIn("systemctl\\ start\\ raspi-spotify-nfc.service", wifi)
        self.assertNotIn("raspi_spotify_nfc.db", out)

    def test_hotspot_uuid_matches_the_app(self):
        from app.wifi_setup import HOTSPOT_UUID
        self.assertIn(f'HOTSPOT_UUID="{HOTSPOT_UUID}"', CLI.read_text())

    def test_reset_without_confirmation_changes_nothing(self):
        result = self.reset(dry_run=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirm", result.stderr)
        self.assertFalse((self.repo / "data").exists())
        self.assertIn("BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF", (self.repo / ".env").read_text())

    def test_reset_takes_no_options(self):
        self.assertIn("takes no options", self.reset("--wipe-tags").stderr)

    def test_setup_wifi_displays_a_wpa_qr_and_password(self):
        result = subprocess.run(
            ["bash", str(self.repo / "taptune"), "setup-wifi"],
            env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("QR[WIFI:T:WPA;S:TapTune-Setup;P:0123456789abcdef0123;;]", result.stdout)
        self.assertIn("Password: 0123456789abcdef0123", result.stdout)
        self.assertIn("Keep these credentials private", result.stdout)

    def test_setup_wifi_shows_password_without_the_qr_encoder(self):
        bin_dir = self.repo / "bin"
        (bin_dir / "qrencode").unlink()
        (bin_dir / "dirname").symlink_to(shutil.which("dirname"))
        result = subprocess.run(
            [shutil.which("bash"), str(self.repo / "taptune"), "setup-wifi"],
            env=dict(self.env, PATH=str(bin_dir)), capture_output=True, text=True, check=True,
        )
        self.assertIn("Password: 0123456789abcdef0123", result.stdout)
        self.assertNotIn("Scan this code", result.stdout)
        self.assertEqual(result.stderr, "")

    def test_setup_wifi_rejects_an_unexpected_or_missing_password(self):
        (self.repo / "bin/nmcli").write_text("#!/bin/sh\necho 'not-a-valid-key'\n")
        result = subprocess.run(
            ["bash", str(self.repo / "taptune"), "setup-wifi"],
            env=self.env, capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("expected per-Pi WPA2 password", result.stderr)


if __name__ == "__main__":
    unittest.main()
