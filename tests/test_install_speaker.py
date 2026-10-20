import os
import stat
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTALLER = REPO_ROOT / "systemd" / "install-speaker.sh"
RECONNECT = REPO_ROOT / "systemd" / "taptune-bluetooth.sh"


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

    def test_dry_run_installs_reconnect_service_for_this_checkout(self):
        output = self.dry_run()
        unit_path = str(REPO_ROOT).replace(" ", "\\x20")
        self.assertIn(f'ExecStart="{unit_path}/systemd/taptune-bluetooth.sh"', output)
        self.assertIn(f"EnvironmentFile={unit_path}/.env", output)
        self.assertIn("enable taptune-bluetooth.service", output)
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


class BluetoothReconnectScriptTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.log = Path(self.directory.name) / "calls.log"
        fake = Path(self.directory.name) / "bluetoothctl"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$@" >> "{self.log}"\n'
            'if [ "$1" = info ]; then echo "Connected: ${FAKE_CONNECTED:-no}"; fi\n'
        )
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        self.fake = fake
        self.amixer_log = Path(self.directory.name) / "amixer.log"
        amixer = Path(self.directory.name) / "amixer"
        amixer.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$@" >> "{self.amixer_log}"\n'
            'case "$*" in *scontrols) echo "Simple mixer control \'JBL Flip 5 A2DP\',0" ;; esac\n'
        )
        amixer.chmod(0o755)
        self.amixer = amixer

    def run_once(self, mac, connected="no"):
        env = dict(
            os.environ, BLUETOOTHCTL=str(self.fake), AMIXER=str(self.amixer),
            BLUETOOTH_SPEAKER_MAC=mac, FAKE_CONNECTED=connected, AUDIO_BACKEND="alsa",
        )
        return subprocess.run(["bash", str(RECONNECT), "--once"], env=env, capture_output=True, text=True)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_connects_when_speaker_is_disconnected(self):
        result = self.run_once("aa:bb:cc:dd:ee:ff")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["info AA:BB:CC:DD:EE:FF", "--timeout 10 connect AA:BB:CC:DD:EE:FF"])

    def test_does_nothing_when_already_connected(self):
        result = self.run_once("AA:BB:CC:DD:EE:FF", connected="yes")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["info AA:BB:CC:DD:EE:FF"])

    def test_connected_lite_speaker_output_is_set_to_full_volume(self):
        result = self.run_once("AA:BB:CC:DD:EE:FF", connected="yes")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "-q -D bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp sset JBL Flip 5 A2DP 100% unmute",
            self.amixer_log.read_text().splitlines(),
        )
        self.assertIn("set to 100%", result.stdout)

    def test_disconnected_lite_speaker_volume_is_not_touched(self):
        self.run_once("AA:BB:CC:DD:EE:FF", connected="no")
        self.assertFalse(self.amixer_log.exists())

    def test_empty_mac_exits_cleanly(self):
        result = self.run_once("")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_invalid_mac_fails(self):
        result = self.run_once("not-a-mac")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not a Bluetooth address", result.stderr)

    def test_desktop_routes_default_output_and_existing_streams(self):
        fake = Path(self.directory.name) / "pactl"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "$@" >> "{self.log}"\n'
            'case "$*" in\n'
            '  "list short sinks") printf "1\\talsa_output.hdmi\\n2\\tbluez_output.AA_BB_CC_DD_EE_FF.1\\n" ;;\n'
            '  "get-default-sink") echo alsa_output.hdmi ;;\n'
            '  "list short sink-inputs") printf "5\\t1\\t42\\n6\\t2\\t43\\n" ;;\n'
            'esac\n'
        )
        fake.chmod(0o755)
        env = dict(
            os.environ, BLUETOOTHCTL=str(self.fake), PACTL=str(fake),
            BLUETOOTH_SPEAKER_MAC="AA:BB:CC:DD:EE:FF",
            FAKE_CONNECTED="yes", AUDIO_BACKEND="pulseaudio",
        )
        result = subprocess.run(["bash", str(RECONNECT), "--once"], env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("set-default-sink bluez_output.AA_BB_CC_DD_EE_FF.1", self.calls())
        self.assertIn("move-sink-input 5 bluez_output.AA_BB_CC_DD_EE_FF.1", self.calls())
        self.assertNotIn("move-sink-input 6 bluez_output.AA_BB_CC_DD_EE_FF.1", self.calls())
        self.assertIn("set-sink-volume bluez_output.AA_BB_CC_DD_EE_FF.1 100%", self.calls())
        self.assertIn("set-sink-mute bluez_output.AA_BB_CC_DD_EE_FF.1 0", self.calls())

    def test_invalid_interval_fails_instead_of_spinning(self):
        with patch.dict(os.environ, BLUETOOTH_RECONNECT_INTERVAL="0"):
            result = self.run_once("AA:BB:CC:DD:EE:FF")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("positive integer", result.stderr)


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
                    self.assertIn("taptune-bluetooth.user.service", result.stdout)
                    self.assertIn("taptune-spotifyd.user.service", result.stdout)
                    self.assertIn("taptune-ready-sound.service", result.stdout)
                    unit_path = str(REPO_ROOT).replace(" ", "\\x20")
                    self.assertIn(f"WorkingDirectory={unit_path}", result.stdout)
                    self.assertIn(f"EnvironmentFile={unit_path}/.env", result.stdout)
                    self.assertIn(f'ExecStart="{unit_path}/.venv/bin/python" -m app.readiness --desktop', result.stdout)
                    self.assertIn("--no-block restart taptune-ready-sound.service", result.stdout)
                    self.assertNotIn("bluealsa", result.stdout)
                    if version.startswith("0.4"):
                        self.assertIn('bluez_monitor.properties["with-logind"] = false', result.stdout)
                    else:
                        self.assertIn("monitor.bluez.seat-monitoring = disabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
