import os
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GuidedInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="TapTune install ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "checkout with spaces"
        self.root.mkdir()
        self.bin = Path(self.temp.name) / "bin"
        self.bin.mkdir()
        self.log = Path(self.temp.name) / "commands"
        self.home = Path(self.temp.name) / "home"
        self.home.mkdir()
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}",
                        HOME=str(self.home), COMMAND_LOG=str(self.log))
        self.env.pop("BASH_ENV", None)
        shutil.copy2(ROOT / "install.sh", self.root)
        shutil.copy2(ROOT / ".env.example", self.root)
        for name in ("requirements.txt", "requirements-pi.txt"):
            shutil.copy2(ROOT / name, self.root)
        (self.root / "systemd").mkdir()
        shutil.copy2(ROOT / "systemd/install-common.sh", self.root / "systemd")
        for name in ("install-speaker.sh", "install-desktop-speaker.sh", "install-service.sh"):
            self.executable(self.root / "systemd" / name,
                            f'printf "{name} %s\\n" "$*" >> "$COMMAND_LOG"\n')
        self.command("id", 'echo "${TEST_UID:-1000}"\n')
        self.command("uname", 'echo "${TEST_OS:-Linux}"\n')
        self.command("systemctl", 'echo "unexpected systemctl" >> "$COMMAND_LOG"; exit 99\n')
        self.command("sudo", 'echo "unexpected sudo" >> "$COMMAND_LOG"; exit 99\n')
        self.command("bluetoothctl",
                     'printf "Paired: ${TEST_PAIRED:-yes}\\nTrusted: yes\\n"\n')
        self.command("python3", '''
printf 'python3 %s\\n' "$*" >> "$COMMAND_LOG"
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$MOCK_PYTHON" "$3/bin/python"
fi
''')
        mock_python = self.bin / "mock-python"
        self.executable(mock_python, 'printf "venv-python %s\\n" "$*" >> "$COMMAND_LOG"\n')
        self.env["MOCK_PYTHON"] = str(mock_python)

    def executable(self, path, text):
        path.write_text("#!/usr/bin/env bash\nset -eu\n" + text)
        path.chmod(0o755)

    def command(self, name, text):
        self.executable(self.bin / name, text)

    def run_install(self, *args, ok=True):
        result = subprocess.run(["bash", str(self.root / "install.sh"), *args],
                                cwd=self.home, env=self.env, text=True,
                                capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def commands(self):
        return self.log.read_text() if self.log.exists() else ""

    def live_config(self, **overrides):
        values = {
            "SPOTIFY_CLIENT_ID": "test-client",
            "SPOTIFY_CLIENT_SECRET": "secret-not-for-logs",
            "SPOTIFY_REFRESH_TOKEN": "refresh-not-for-logs",
            "NFC_READER_ENABLED": "true",
            "SPOTIFY_DEVICE_NAME": "TapTune",
            "BLUETOOTH_SPEAKER_MAC": "AA:BB:CC:DD:EE:FF",
        }
        values.update(overrides)
        path = self.root / ".env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
        path.chmod(0o600)
        (self.root / ".venv/bin").mkdir(parents=True, exist_ok=True)
        self.executable(self.root / ".venv/bin/python",
                        f'exec {shlex.quote(sys.executable)} "$@"\n')

    def test_help_is_read_only(self):
        self.assertIn("--configure", self.run_install("--help").stdout)
        self.assertFalse((self.root / ".env").exists())
        self.assertEqual(self.commands(), "")

    def test_mode_is_required(self):
        self.run_install(ok=False)

    def test_conflicting_modes_are_rejected(self):
        self.run_install("--lite", "--desktop", ok=False)
        self.assertEqual(self.commands(), "")

    def test_unknown_flag_is_rejected(self):
        self.run_install("--lite", "--typo", ok=False)

    def test_prepare_lite_creates_private_env_without_services(self):
        self.run_install("--lite")
        self.assertEqual((self.root / ".env").read_bytes(),
                         (self.root / ".env.example").read_bytes())
        self.assertEqual(stat.S_IMODE((self.root / ".env").stat().st_mode), 0o600)
        self.assertIn("requirements-pi.txt", self.commands())
        self.assertNotIn("install-speaker.sh", self.commands())
        self.assertNotIn("systemctl", self.commands())

    def test_prepare_rerun_preserves_env_permissions_and_reuses_venv(self):
        self.run_install("--desktop")
        path = self.root / ".env"
        path.write_text("# user's configuration\nSPOTIFY_CLIENT_ID=keep-me\n")
        path.chmod(0o640)
        self.log.unlink()
        self.run_install("--desktop")
        self.assertEqual(path.read_text(), "# user's configuration\nSPOTIFY_CLIENT_ID=keep-me\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertNotIn("-m venv", self.commands())

    def test_app_only_preparation_skips_hardware_packages(self):
        self.env["TEST_OS"] = "Darwin"
        self.run_install("--app-only")
        self.assertIn("requirements.txt", self.commands())
        self.assertNotIn("requirements-pi.txt", self.commands())

    def test_root_is_rejected_before_changes(self):
        self.env["TEST_UID"] = "0"
        self.assertIn("without sudo", self.run_install("--lite", ok=False).stderr)
        self.assertFalse((self.root / ".venv").exists())

    def test_pi_install_requires_linux(self):
        self.env["TEST_OS"] = "Darwin"
        self.run_install("--lite", ok=False)
        self.assertEqual(self.commands(), "")

    def test_dry_runs_have_no_side_effects_in_any_mode(self):
        self.env["TEST_UID"] = "0"
        for mode in ("--lite", "--desktop", "--app-only"):
            for options in ((), ("--configure",)):
                with self.subTest(mode=mode, options=options):
                    result = self.run_install(mode, *options, "--dry-run")
                    self.assertIn("nothing changed", result.stdout)
                    self.assertFalse((self.root / ".env").exists())
                    self.assertFalse((self.root / ".venv").exists())
                    self.assertEqual(self.commands(), "")

    def test_configure_dry_run_forwards_mode_and_dry_run(self):
        for mode, script, flag in (
            ("--lite", "install-speaker.sh", ""),
            ("--desktop", "install-desktop-speaker.sh", "--desktop"),
            ("--app-only", "install-service.sh", "--app-only"),
        ):
            result = self.run_install(mode, "--configure", "--dry-run")
            self.assertIn(script, result.stdout)
            self.assertIn("--dry-run", result.stdout)
            if flag:
                self.assertIn(flag, result.stdout)

    def test_configure_requires_preparation(self):
        self.run_install("--lite", "--configure", ok=False)
        self.assertEqual(self.commands(), "")

    def test_configure_rejects_fake_mode_without_logging_secrets(self):
        self.live_config(SPOTIFY_REFRESH_TOKEN="")
        result = self.run_install("--lite", "--configure", ok=False)
        self.assertIn("SPOTIFY_REFRESH_TOKEN", result.stderr)
        self.assertNotIn("secret-not-for-logs", result.stdout + result.stderr)
        self.assertEqual(self.commands(), "")

    def test_configure_requires_private_env(self):
        self.live_config()
        (self.root / ".env").chmod(0o644)
        result = self.run_install("--lite", "--configure", ok=False)
        self.assertIn("chmod 600", result.stderr)
        self.assertEqual(self.commands(), "")

    def test_configure_lite_requires_reader_and_valid_mac(self):
        self.live_config(NFC_READER_ENABLED="false")
        self.assertIn("first-card", self.run_install("--lite", "--configure", ok=False).stderr)
        (self.root / ".venv/bin/python").unlink()
        self.live_config(BLUETOOTH_SPEAKER_MAC="not-a-mac")
        self.assertIn("Bluetooth address", self.run_install("--lite", "--configure", ok=False).stderr)
        self.assertEqual(self.commands(), "")

    def test_configure_requires_paired_speaker(self):
        self.live_config()
        self.env["TEST_PAIRED"] = "no"
        self.assertIn("pair", self.run_install("--lite", "--configure", ok=False).stderr)
        self.assertEqual(self.commands(), "")

    def test_configure_lite_installs_speaker_before_app(self):
        self.live_config()
        result = self.run_install("--lite", "--configure")
        self.assertEqual(self.commands(), "install-speaker.sh \ninstall-service.sh --lite\n")
        self.assertNotIn("secret-not-for-logs", result.stdout + result.stderr)
        self.assertNotIn("-m pip", self.commands())

    def test_configure_app_only_does_not_require_reader_or_bluetooth(self):
        self.live_config(NFC_READER_ENABLED="false", BLUETOOTH_SPEAKER_MAC="")
        self.run_install("--app-only", "--configure")
        self.assertEqual(self.commands(), "install-service.sh --app-only\n")

    def test_failed_dependency_install_stops_without_creating_env(self):
        self.executable(Path(self.env["MOCK_PYTHON"]), '''
printf 'venv-python %s\\n' "$*" >> "$COMMAND_LOG"
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 23; fi
''')
        result = self.run_install("--lite", ok=False)
        self.assertEqual(result.returncode, 23)
        self.assertIn("-m pip install", self.commands())
        self.assertIn("installation stopped", result.stderr)
        self.assertFalse((self.root / ".env").exists())

    def test_failed_speaker_installer_does_not_start_app(self):
        self.live_config()
        self.executable(self.root / "systemd/install-speaker.sh", "exit 42\n")
        result = self.run_install("--lite", "--configure", ok=False)
        self.assertEqual(result.returncode, 42)
        self.assertEqual(self.commands(), "")
        self.assertNotIn("Configured", result.stdout)

    def test_env_is_not_executed_as_shell(self):
        self.live_config()
        path = self.root / ".env"
        path.write_text(path.read_text() + '\nUNUSED=$(touch unexpected-file)\n')
        self.run_install("--lite", "--configure")
        self.assertFalse((self.home / "unexpected-file").exists())


if __name__ == "__main__":
    unittest.main()
