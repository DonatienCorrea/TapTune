import os
import stat
import subprocess
import tempfile
import unittest
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
        env = dict(os.environ, BLUETOOTHCTL=str(self.fake), BLUETOOTH_SPEAKER_MAC=mac, FAKE_CONNECTED=connected)
        return subprocess.run(["bash", str(RECONNECT), "--once"], env=env, capture_output=True, text=True)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_connects_when_speaker_is_disconnected(self):
        result = self.run_once("aa:bb:cc:dd:ee:ff")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.calls(), ["info AA:BB:CC:DD:EE:FF", "connect AA:BB:CC:DD:EE:FF"])

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


if __name__ == "__main__":
    unittest.main()
