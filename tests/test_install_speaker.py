import os
import stat
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

    def test_dry_run_reenables_credential_cache_so_login_survives_reboot(self):
        self.assertIn("#LIBRESPOT_DISABLE_CREDENTIAL_CACHE=", self.dry_run())

    def test_dry_run_installs_reconnect_service_for_this_checkout(self):
        output = self.dry_run()
        self.assertIn(f"ExecStart={REPO_ROOT}/systemd/taptune-bluetooth.sh", output)
        self.assertIn(f"EnvironmentFile={REPO_ROOT}/.env", output)
        self.assertIn("enable taptune-bluetooth.service", output)
        self.assertNotIn("/home/pi/TapTune", output)

    def test_rejects_unknown_argument(self):
        result = subprocess.run(["bash", str(INSTALLER), "--bogus"], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument", result.stderr)


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

    def run_once(self, mac, connected="no"):
        env = dict(os.environ, BLUETOOTHCTL=str(self.fake), BLUETOOTH_SPEAKER_MAC=mac, FAKE_CONNECTED=connected, AUDIO_BACKEND="alsa")
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
                    self.assertNotIn("bluealsa", result.stdout)
                    if version.startswith("0.4"):
                        self.assertIn('bluez_monitor.properties["with-logind"] = false', result.stdout)
                    else:
                        self.assertIn("monitor.bluez.seat-monitoring = disabled", result.stdout)


if __name__ == "__main__":
    unittest.main()
