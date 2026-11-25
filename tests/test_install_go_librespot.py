import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMON = REPO_ROOT / "systemd" / "install-common.sh"


class GoLibrespotInstallerTests(unittest.TestCase):
    def dry_run(self, env_text):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "TapTune"
            shutil.copytree(REPO_ROOT / "systemd", repo / "systemd")
            (repo / ".env").write_text(env_text)
            env = dict(os.environ)
            env.pop("XDG_CONFIG_HOME", None)
            return subprocess.run(
                ["bash", str(repo / "systemd/install-go-librespot.sh"), "--dry-run"],
                env=env, capture_output=True, text=True,
            )

    def test_installs_go_librespot_with_a_persistent_zeroconf_login(self):
        result = self.dry_run("SPOTIFY_DEVICE_NAME='Salon TapTune'\n"
                              "BLUETOOTH_SPEAKER_MAC=\"12:34:56:78:90:AB\"\nSPOTIFY_INITIAL_VOLUME=25\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        out = result.stdout
        self.assertIn("go-librespot/releases/download/v0.10.7/", out)
        for line in ('device_name: "Salon TapTune"', "audio_backend: alsa", "audio_device: pulse",
                     "initial_volume: 25", "ignore_last_volume: true", "persist_credentials: true",
                     "address: 127.0.0.1", "port: 3678", "zeroconf_backend: avahi",
                     "libasound2-plugins", "pipewire-pulse", "enable-linger",
                     "bluetoothctl trust 12:34:56:78:90:AB", "seat"):
            self.assertIn(line, out)
        self.assertLess(out.index("old Raspotify"), out.index("restart taptune-go-librespot.service"))
        for removed in ("raspotify/install.sh", "bluez-alsa-utils", "qrencode"):
            self.assertNotIn(removed, out)

    def test_installs_before_a_speaker_is_paired_with_default_volume(self):
        result = self.dry_run("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/setup", result.stderr)
        self.assertIn("initial_volume: 10", result.stdout)
        self.assertNotIn("bluetoothctl trust", result.stdout)
        self.assertIn("restart taptune-go-librespot.service", result.stdout)

    def test_invalid_settings_fail_before_installing(self):
        for env_text, message in (
            ("BLUETOOTH_SPEAKER_MAC=not-a-mac\n", "BLUETOOTH_SPEAKER_MAC"),
            ("SPOTIFY_INITIAL_VOLUME=101\n", "0 to 100"),
            ('SPOTIFY_DEVICE_NAME=Bad"Name\n', "SPOTIFY_DEVICE_NAME"),
        ):
            with self.subTest(env_text=env_text):
                result = self.dry_run(env_text)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertNotIn("apt-get", result.stdout)

    def test_unit_runs_go_librespot_from_the_user_config_and_always_restarts(self):
        unit = (REPO_ROOT / "systemd" / "taptune-go-librespot.user.service").read_text()
        self.assertIn('ExecStart=/usr/local/bin/go-librespot --config_dir "%h/.config/go-librespot"', unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("StartLimitIntervalSec=0", unit)


class CommonHelperTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / "calls.log"
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        (bin_dir / "systemctl").write_text(
            "#!/usr/bin/env bash\n"
            f'echo "systemctl $*" >> "{self.log}"\n'
            'case "$*" in\n'
            '  *show-environment*) [ "$FAKE_USER_MANAGER" = yes ] ;;\n'
            '  *list-unit-files*)\n'
            '    unit="${@: -1}"\n'
            '    for installed in $FAKE_INSTALLED; do\n'
            '      [ "$installed" = "$unit" ] && echo "$unit enabled enabled"\n'
            '    done; exit 0 ;;\n'
            'esac\n'
        )
        (bin_dir / "sudo").write_text(f'#!/usr/bin/env bash\necho "sudo $*" >> "{self.log}"\n')
        for tool in bin_dir.iterdir():
            tool.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", HOME=str(self.root),
                        XDG_CONFIG_HOME=str(self.root / "config"), FAKE_USER_MANAGER="yes",
                        FAKE_INSTALLED="", TAPTUNE_RETRY_DELAY="0")

    def run_helpers(self, script, **env):
        result = subprocess.run(
            ["bash", "-c", f'set -eu; DRY_RUN=0; source "{COMMON}"; {script}'],
            env={**self.env, **env}, capture_output=True, text=True,
        )
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result, [call for call in calls if "list-unit-files" not in call and "show-environment" not in call]

    def test_retry_runs_three_times_and_keeps_the_last_status(self):
        counter = self.root / "count"
        result, _ = self.run_helpers(f'retry bash -c "echo x >> \\"{counter}\\"; exit 7"')
        self.assertEqual(result.returncode, 7)
        self.assertEqual(counter.read_text().count("x"), 3)
        self.assertEqual(result.stderr.count("retrying"), 2)

    def test_retry_stops_at_the_first_success(self):
        counter = self.root / "count"
        result, _ = self.run_helpers(
            f'retry bash -c "echo x >> \\"{counter}\\"; [ \\$(wc -l < \\"{counter}\\") -ge 2 ]"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(counter.read_text().count("x"), 2)

    def test_only_installed_legacy_units_are_disabled_and_owned_files_removed(self):
        units = self.root / "config/systemd/user"
        units.mkdir(parents=True)
        for name in ("taptune-spotifyd.service", "taptune-ready-sound.service"):
            (units / name).write_text("[Unit]\n")
        script = self.root / ".local/lib/taptune/taptune-bluetooth.sh"
        script.parent.mkdir(parents=True)
        script.write_text("")
        result, calls = self.run_helpers(
            "remove_legacy_units",
            FAKE_INSTALLED="raspotify.service taptune-spotifyd.service taptune-ready-sound.service",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("sudo systemctl disable --now raspotify.service", calls)
        self.assertNotIn("sudo systemctl disable --now bluealsa.service", calls)
        self.assertIn("systemctl --user disable --now taptune-spotifyd.service", calls)
        self.assertIn("systemctl --user disable --now taptune-ready-sound.service", calls)
        self.assertNotIn("systemctl --user disable --now spotifyd.service", calls)
        self.assertEqual(list(units.iterdir()), [])
        self.assertFalse(script.parent.exists())

    def test_fresh_install_only_removes_absent_files(self):
        result, calls = self.run_helpers("remove_legacy_units")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([call for call in calls if "disable" in call], [])

    def test_owned_unit_without_user_manager_fails_instead_of_staying_enabled(self):
        units = self.root / "config/systemd/user"
        units.mkdir(parents=True)
        (units / "taptune-spotifyd.service").write_text("[Unit]\n")
        result, _ = self.run_helpers("remove_legacy_units", FAKE_USER_MANAGER="no")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("log in as", result.stderr)
        self.assertTrue((units / "taptune-spotifyd.service").exists())


if __name__ == "__main__":
    unittest.main()
