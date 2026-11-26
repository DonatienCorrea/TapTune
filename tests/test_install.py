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
                        HOME=str(self.home), COMMAND_LOG=str(self.log), TAPTUNE_RETRY_DELAY="0")
        self.env.pop("BASH_ENV", None)
        shutil.copy2(ROOT / "install.sh", self.root)
        shutil.copy2(ROOT / ".env.example", self.root)
        for name in ("requirements.txt", "requirements-pi.txt"):
            shutil.copy2(ROOT / name, self.root)
        (self.root / "systemd").mkdir()
        shutil.copy2(ROOT / "systemd/install-common.sh", self.root / "systemd")
        for name in ("install-go-librespot.sh", "install-service.sh"):
            self.executable(self.root / "systemd" / name,
                            f'printf "{name} %s\\n" "$*" >> "$COMMAND_LOG"\n')
        self.command("id", 'echo "${TEST_UID:-1000}"\n')
        self.command("uname", 'echo "${TEST_OS:-Linux}"\n')
        self.command("systemctl", 'echo "unexpected systemctl" >> "$COMMAND_LOG"; exit 99\n')
        self.command("sudo", 'echo "unexpected sudo" >> "$COMMAND_LOG"; exit 99\n')
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

    def test_unknown_or_removed_flags_are_rejected(self):
        for flag in ("--typo", "--lite", "--app-only"):
            with self.subTest(flag=flag):
                self.assertIn("unknown argument", self.run_install(flag, ok=False).stderr)
        self.assertEqual(self.commands(), "")

    def test_fresh_install_creates_private_env_and_starts_services_in_order(self):
        result = self.run_install()
        self.assertEqual((self.root / ".env").read_bytes(), (self.root / ".env.example").read_bytes())
        self.assertEqual(stat.S_IMODE((self.root / ".env").stat().st_mode), 0o600)
        self.assertIn("requirements.txt -r", self.commands())
        self.assertIn("requirements-pi.txt", self.commands())
        calls = self.commands()
        self.assertLess(calls.index("-m pip install"), calls.index("install-go-librespot.sh"))
        self.assertLess(calls.index("install-go-librespot.sh"), calls.index("install-service.sh"))
        self.assertIn(".local/setup on a phone", result.stdout)

    def test_install_rerun_preserves_private_env_and_reuses_venv(self):
        self.run_install()
        path = self.root / ".env"
        path.write_text("# user's configuration\nSPOTIFY_DEVICE_NAME=keep-me\n")
        self.log.unlink()
        self.assertIn("Keeping your existing .env", self.run_install().stdout)
        self.assertEqual(path.read_text(), "# user's configuration\nSPOTIFY_DEVICE_NAME=keep-me\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertNotIn("-m venv", self.commands())

    def test_root_is_rejected_before_changes(self):
        self.env["TEST_UID"] = "0"
        self.assertIn("without sudo", self.run_install(ok=False).stderr)
        self.assertFalse((self.root / ".venv").exists())

    def test_install_requires_linux(self):
        self.env["TEST_OS"] = "Darwin"
        self.run_install(ok=False)
        self.assertEqual(self.commands(), "")

    def test_dry_runs_have_no_side_effects(self):
        self.env["TEST_UID"] = "0"
        self.env["TEST_OS"] = "Darwin"
        for options in ((), ("--configure",)):
            with self.subTest(options=options):
                result = self.run_install(*options, "--dry-run")
                self.assertIn("nothing changed", result.stdout)
                self.assertFalse((self.root / ".env").exists())
                self.assertFalse((self.root / ".venv").exists())
                self.assertEqual(self.commands(), "")
                if options:
                    self.assertNotIn("-m pip install", result.stdout)

    def test_dry_run_previews_dependencies_and_services_in_order(self):
        out = self.run_install("--dry-run").stdout
        setup = "install-go-librespot.sh --dry-run"
        self.assertLess(out.index("-m pip install"), out.index(setup))
        self.assertLess(out.index(setup), out.index("install-service.sh --dry-run"))

    def test_configure_requires_preparation(self):
        self.assertIn("./install.sh first", self.run_install("--configure", ok=False).stderr)
        self.assertEqual(self.commands(), "")

    def test_configure_requires_private_env(self):
        self.live_config()
        (self.root / ".env").chmod(0o644)
        result = self.run_install("--configure", ok=False)
        self.assertIn("chmod 600", result.stderr)
        self.assertEqual(self.commands(), "")

    def test_configure_installs_speaker_before_app_without_a_paired_speaker(self):
        self.live_config(BLUETOOTH_SPEAKER_MAC="")
        result = self.run_install("--configure")
        self.assertEqual(self.commands(), "install-go-librespot.sh \ninstall-service.sh \n")
        self.assertIn(".local/setup on a phone", result.stdout)
        self.assertNotIn("-m pip", self.commands())

    def test_failed_dependency_install_is_retried_then_stops_without_creating_env(self):
        self.executable(Path(self.env["MOCK_PYTHON"]), '''
printf 'venv-python %s\\n' "$*" >> "$COMMAND_LOG"
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then exit 23; fi
''')
        result = self.run_install(ok=False)
        self.assertEqual(result.returncode, 23)
        self.assertEqual(self.commands().count("-m pip install"), 3)
        self.assertIn("retrying", result.stderr)
        self.assertIn("installation stopped", result.stderr)
        self.assertFalse((self.root / ".env").exists())
        self.assertNotIn("install-service.sh", self.commands())

    def test_failed_speaker_installer_does_not_start_app(self):
        self.live_config()
        self.executable(self.root / "systemd/install-go-librespot.sh", "exit 42\n")
        result = self.run_install("--configure", ok=False)
        self.assertEqual(result.returncode, 42)
        self.assertEqual(self.commands(), "")
        self.assertNotIn(".local/setup", result.stdout)

    def test_env_is_not_executed_as_shell(self):
        self.live_config()
        path = self.root / ".env"
        path.write_text(path.read_text() + '\nUNUSED=$(touch unexpected-file)\n')
        self.run_install("--configure")
        self.assertFalse((self.home / "unexpected-file").exists())


if __name__ == "__main__":
    unittest.main()
