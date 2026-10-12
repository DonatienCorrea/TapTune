import subprocess
import os
import shutil
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "systemd" / "install-service.sh"


class InstallServiceScriptTests(unittest.TestCase):
    def run_dry_run(self, cwd: Path) -> str:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--dry-run"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def test_dry_run_rewrites_paths_to_repo_root(self):
        output = self.run_dry_run(REPO_ROOT)

        self.assertIn(f'WorkingDirectory="{REPO_ROOT}"', output)
        self.assertIn(f'ExecStart="{REPO_ROOT}/.venv/bin/python" -m app.main', output)
        self.assertIn(f'EnvironmentFile="{REPO_ROOT}/.env"', output)
        self.assertNotIn("/home/pi/TapTune", output)

    def test_dry_run_does_not_require_venv_or_env_file(self):
        # --dry-run must work even before `.venv`/`.env` exist so it can be
        # used to preview the unit ahead of installing.
        output = self.run_dry_run(REPO_ROOT)
        self.assertIn("[Service]", output)

    def test_rejects_unknown_argument(self):
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--bogus"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument", result.stderr)

    def test_desktop_does_not_start_competing_lite_audio_services(self):
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--desktop", "--dry-run"],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("Wants=network-online.target\n", result.stdout)
        self.assertIn("After=network-online.target bluetooth.service\n", result.stdout)
        self.assertNotIn("raspotify", result.stdout)
        self.assertNotIn("bluealsa", result.stdout)
        self.assertIn("Environment=READY_SOUND_ENABLED=false", result.stdout)

    def test_paths_escape_systemd_specifiers_and_exec_environment_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'Pi music & # 100% $HOME "quotes" \\path'
            shutil.copytree(REPO_ROOT / "systemd", repo / "systemd")
            result = subprocess.run(
                ["bash", str(repo / "systemd/install-service.sh"), "--dry-run"],
                capture_output=True, text=True, check=True,
            )
            path = str(repo).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
            self.assertIn(f'WorkingDirectory="{path}"', result.stdout)
            self.assertIn(f'EnvironmentFile="{path}/.env"', result.stdout)
            self.assertIn(f'ExecStart="{path.replace("$", "$$")}/.venv/bin/python"', result.stdout)

    def test_reinstall_restarts_existing_service_without_real_system_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "TapTune"
            shutil.copytree(REPO_ROOT / "systemd", repo / "systemd")
            python = repo / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o755)
            (repo / ".env").write_text("NFC_READER_ENABLED=false\n")
            log = Path(directory) / "calls"
            sudo = Path(directory) / "sudo"
            sudo.write_text(
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALL_LOG"\n'
                'if [ "$1" = tee ]; then cat >/dev/null; fi\n'
            )
            sudo.chmod(0o755)
            env = dict(os.environ, PATH=directory + os.pathsep + os.environ["PATH"], CALL_LOG=str(log))
            subprocess.run(
                ["bash", str(repo / "systemd/install-service.sh")],
                env=env, capture_output=True, text=True, check=True,
            )
            calls = log.read_text().splitlines()
            self.assertIn("systemctl enable raspi-spotify-nfc.service", calls)
            self.assertIn("systemctl restart raspi-spotify-nfc.service", calls)


if __name__ == "__main__":
    unittest.main()
