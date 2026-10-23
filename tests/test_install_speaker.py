import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "systemd" / "install-speaker.sh"
COMMON = REPO_ROOT / "systemd" / "install-common.sh"


class InstallSpeakerScriptTests(unittest.TestCase):
    def dry_run(self):
        return subprocess.run(
            ["bash", str(INSTALLER), "--dry-run"], capture_output=True, text=True, check=True
        ).stdout

    def test_dry_run_configures_raspotify_for_the_bluetooth_speaker(self):
        output = self.dry_run()
        self.assertIn("bluez-alsa-utils", output)
        self.assertIn("raspotify/install.sh", output)
        self.assertIn("LIBRESPOT_BACKEND=alsa", output)
        self.assertRegex(output, r'LIBRESPOT_NAME="[^"]+"')
        self.assertRegex(output, r'LIBRESPOT_DEVICE="[^"]+"')
        self.assertIn("LIBRESPOT_INITIAL_VOLUME=30", output)
        self.assertIn("PROFILE=a2dp", output)

    def test_dry_run_reenables_credential_cache_so_login_survives_reboot(self):
        self.assertIn("#LIBRESPOT_DISABLE_CREDENTIAL_CACHE=", self.dry_run())

    def test_dry_run_has_no_reconnect_loop_and_stops_the_desktop_stack(self):
        output = self.dry_run()
        self.assertNotIn("systemd/taptune-bluetooth.sh", output)
        self.assertNotIn("enable taptune-bluetooth.service", output)
        self.assertIn("systemctl --user disable --now taptune-spotifyd.service", output)
        self.assertIn("sudo systemctl disable --now spotifyd.service", output)
        self.assertIn("sudo systemctl disable --now taptune-bluetooth.service", output)
        self.assertIn("sudo rm -f /etc/systemd/system/taptune-bluetooth.service", output)
        self.assertIn("systemctl --user disable --now taptune-ready-sound.service", output)
        self.assertLess(output.index("disable --now taptune-spotifyd.service"), output.index("restart raspotify.service"))
        self.assertNotIn("/home/pi/TapTune", output)

    def test_rejects_unknown_argument(self):
        result = subprocess.run(["bash", str(INSTALLER), "--bogus"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument", result.stderr)

    def test_both_installers_read_quoted_mac_and_custom_startup_volume(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "TapTune"
            shutil.copytree(REPO_ROOT / "systemd", repo / "systemd")
            (repo / ".env").write_text(
                "BLUETOOTH_SPEAKER_MAC='12:34:56:78:90:AB'\n"
                'SPOTIFY_INITIAL_VOLUME="42"\n'
                "SPOTIFY_DEVICE_NAME='My TapTune'\n"
            )
            for installer in ("install-speaker.sh", "install-desktop-speaker.sh"):
                with self.subTest(installer=installer):
                    env = dict(os.environ)
                    env.pop("XDG_CONFIG_HOME", None)
                    result = subprocess.run(
                        ["bash", str(repo / "systemd" / installer), "--dry-run"],
                        env=env, capture_output=True, text=True, check=True,
                    )
                    self.assertIn("12:34:56:78:90:AB", result.stdout)
                    if installer == "install-speaker.sh":
                        self.assertIn('LIBRESPOT_NAME="My TapTune"', result.stdout)
                        self.assertIn('LIBRESPOT_DEVICE="bluealsa:DEV=12:34:56:78:90:AB,PROFILE=a2dp"', result.stdout)
                        self.assertIn("LIBRESPOT_INITIAL_VOLUME=42", result.stdout)
                    else:
                        self.assertIn("initial_volume\\ =\\ 42", result.stdout)

    def test_invalid_mac_and_volume_fail_before_installing(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "TapTune"
            shutil.copytree(REPO_ROOT / "systemd", repo / "systemd")
            for content, message in (
                ("BLUETOOTH_SPEAKER_MAC=invalid\n", "paired speaker"),
                ("BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF\nSPOTIFY_INITIAL_VOLUME=101\n", "0 to 100"),
            ):
                (repo / ".env").write_text(content)
                for installer in ("install-speaker.sh", "install-desktop-speaker.sh"):
                    env = dict(os.environ)
                    env.pop("XDG_CONFIG_HOME", None)
                    result = subprocess.run(
                        ["bash", str(repo / "systemd" / installer), "--dry-run"],
                        env=env, capture_output=True, text=True,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn("apt-get", result.stdout)


class CleanupHelperTests(unittest.TestCase):
    """Mode switches and upgrades only stop units that are really installed."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.systemd_dir = self.root / "systemd"
        self.systemd_dir.mkdir()
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
        (bin_dir / "sudo").write_text('#!/usr/bin/env bash\n"$@"\n')
        for tool in bin_dir.iterdir():
            tool.chmod(0o755)
        self.env = dict(os.environ, PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}", HOME=str(self.root),
                        XDG_CONFIG_HOME=str(self.root / "config"), FAKE_USER_MANAGER="yes")

    def run_helpers(self, script, **env):
        result = subprocess.run(
            ["bash", "-c", f'DRY_RUN=0; source "{COMMON}"; {script}'],
            env={**self.env, **env}, capture_output=True, text=True,
        )
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return result, [call for call in calls if "list-unit-files" not in call and "show-environment" not in call]

    def test_only_installed_conflicting_units_are_disabled(self):
        result, calls = self.run_helpers(
            "disable_system_unit raspotify.service test; disable_system_unit bluealsa.service test; "
            "disable_user_unit spotifyd.service test; disable_user_unit taptune-spotifyd.service test",
            FAKE_INSTALLED="raspotify.service taptune-spotifyd.service",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [
            "systemctl disable --now raspotify.service",
            "systemctl --user disable --now taptune-spotifyd.service",
        ])

    def test_legacy_user_units_and_files_are_removed(self):
        units = self.root / "config/systemd/user"
        units.mkdir(parents=True)
        for name in ("taptune-bluetooth.service", "taptune-ready-sound.service"):
            (units / name).write_text("[Unit]\n")
        script = self.root / ".local/lib/taptune/taptune-bluetooth.sh"
        script.parent.mkdir(parents=True)
        script.write_text("")
        result, calls = self.run_helpers(
            "remove_legacy_user_units",
            FAKE_INSTALLED="taptune-bluetooth.service taptune-ready-sound.service",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("systemctl --user disable --now taptune-bluetooth.service", calls)
        self.assertIn("systemctl --user disable --now taptune-ready-sound.service", calls)
        self.assertEqual(list(units.iterdir()), [])
        self.assertFalse(script.parent.exists())

    def test_fresh_install_has_nothing_to_clean(self):
        result, calls = self.run_helpers(
            f'remove_legacy_user_units; remove_legacy_system_units "{self.systemd_dir}"', FAKE_INSTALLED=""
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_legacy_system_unit_is_removed_when_present(self):
        unit = self.systemd_dir / "taptune-bluetooth.service"
        unit.write_text("[Unit]\n")
        result, calls = self.run_helpers(f'remove_legacy_system_units "{self.systemd_dir}"')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(unit.exists())
        self.assertEqual(calls, [
            "systemctl disable --now taptune-bluetooth.service",
            "systemctl daemon-reload",
        ])

    def test_owned_unit_without_user_manager_fails_instead_of_staying_enabled(self):
        units = self.root / "config/systemd/user"
        units.mkdir(parents=True)
        (units / "taptune-bluetooth.service").write_text("[Unit]\n")
        result, calls = self.run_helpers("remove_legacy_user_units", FAKE_USER_MANAGER="no")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not reachable", result.stderr)
        self.assertTrue((units / "taptune-bluetooth.service").exists())


class DesktopInstallerTests(unittest.TestCase):
    def test_dry_run_starts_user_audio_at_boot_and_disables_seat_monitoring(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "wireplumber"
            for version in ("0.4.17", "0.5.8"):
                with self.subTest(version=version):
                    fake.write_text(f"#!/bin/sh\necho 'wireplumber {version}'\n")
                    fake.chmod(0o755)
                    env = dict(os.environ, PATH=directory + os.pathsep + os.environ["PATH"])
                    env.pop("XDG_CONFIG_HOME", None)
                    result = subprocess.run(
                        ["bash", str(REPO_ROOT / "systemd/install-desktop-speaker.sh"), "--dry-run"],
                        env=env, capture_output=True, text=True, check=True,
                    )
                    self.assertIn("loginctl enable-linger", result.stdout)
                    self.assertIn("pipewire.socket pipewire-pulse.socket wireplumber.service", result.stdout)
                    self.assertIn("taptune-spotifyd.user.service", result.stdout)
                    self.assertNotIn("taptune-bluetooth.user.service", result.stdout)
                    self.assertNotIn("app.readiness", result.stdout)
                    self.assertNotIn("restart taptune-ready-sound", result.stdout)
                    self.assertIn("systemctl --user disable --now taptune-bluetooth.service", result.stdout)
                    self.assertIn("systemctl --user disable --now taptune-ready-sound.service", result.stdout)
                    self.assertIn("sudo systemctl disable --now raspotify.service", result.stdout)
                    self.assertIn("sudo systemctl disable --now bluealsa.service", result.stdout)
                    self.assertIn("sudo rm -f /etc/systemd/system/raspotify.service.d/taptune.conf", result.stdout)
                    self.assertNotIn("apt-get", result.stdout)
                    self.assertNotIn("enable --now bluetooth.service bluealsa", result.stdout)
                    if version.startswith("0.4"):
                        self.assertIn('bluez_monitor.properties["with-logind"] = false', result.stdout)
                    else:
                        self.assertIn("monitor.bluez.seat-monitoring = disabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
