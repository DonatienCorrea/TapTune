import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "systemd" / "install-service.sh"


class InstallServiceScriptTests(unittest.TestCase):
    def run_dry_run(self, script=SCRIPT_PATH, *args, check=True):
        return subprocess.run(
            ["bash", str(script), *args, "--dry-run"], capture_output=True, text=True, check=check,
        )

    def test_dry_run_rewrites_paths_and_needs_no_venv_or_env(self):
        output = self.run_dry_run().stdout
        path = str(REPO_ROOT).replace(" ", "\\x20")
        self.assertIn(f"WorkingDirectory={path}", output)
        self.assertIn(f'ExecStart="{path}/.venv/bin/python" -m app.main', output)
        self.assertIn(f"EnvironmentFile={path}/.env", output)
        self.assertNotIn("/home/pi/TapTune", output)

    def test_app_plays_through_the_users_pipewire_with_port_80_and_wifi_setup(self):
        output = self.run_dry_run().stdout
        path = str(REPO_ROOT).replace(" ", "\\x20")
        self.assertIn("Wants=network-online.target\n", output)
        self.assertIn("After=network-online.target bluetooth.service\n", output)
        self.assertRegex(output, r"\nEnvironment=DESKTOP_AUDIO_USER=[a-z_][a-z0-9_-]*\n")
        self.assertIn("Environment=TAPTUNE_HTTP_PORT_80=true", output)
        self.assertIn("Environment=TAPTUNE_WIFI_SETUP=true", output)
        self.assertIn(f'ExecStopPost=-"{path}/.venv/bin/python" -m app.wifi_setup cleanup', output)
        for removed in ("raspotify", "bluealsa", "spotifyd", "qrencode"):
            self.assertNotIn(removed, output)

    def test_installer_does_not_touch_hostname_or_hosts(self):
        script = SCRIPT_PATH.read_text()
        self.assertNotIn("hostnamectl", script)
        self.assertNotIn("/etc/hosts", script)

    def test_rejects_unknown_or_removed_arguments(self):
        for arg in ("--bogus", "--lite", "--desktop"):
            with self.subTest(arg=arg):
                result = self.run_dry_run(SCRIPT_PATH, arg, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unknown argument", result.stderr)

    def test_paths_escape_systemd_specifiers_and_exec_environment_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / 'Pi music & # 100% $HOME "quotes" \\path'
            shutil.copytree(REPO_ROOT / "systemd", repo / "systemd")
            output = self.run_dry_run(repo / "systemd/install-service.sh").stdout
            path = (
                str(repo).replace("\\", "\\\\").replace('"', '\\"')
                .replace(" ", "\\x20").replace("%", "%%")
            )
            self.assertIn(f"WorkingDirectory={path}", output)
            self.assertIn(f"EnvironmentFile={path}/.env", output)
            exec_path = path.replace("$", "$$")
            self.assertIn(f'ExecStart="{exec_path}/.venv/bin/python"', output)

    def test_real_install_enables_wifi_setup_only_with_network_manager(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "TapTune"
            shutil.copytree(REPO_ROOT / "systemd", repo / "systemd")
            python = repo / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o755)
            (repo / ".env").write_text("NFC_READER_ENABLED=true\n")
            log = Path(directory) / "calls"
            bin_dir = Path(directory) / "bin"
            bin_dir.mkdir()
            for tool in ("cat", "cmp", "cut", "dirname", "grep", "sed", "tail"):
                (bin_dir / tool).symlink_to(shutil.which(tool))
            for tool, script in (
                ("id", 'if [ "$1" = -u ]; then echo 1000; else echo pi; fi'),
                ("nmcli", "exit 0"),
                ("systemctl", 'exit "$NM_STATUS"'),
                ("sudo", 'printf "%s\\n" "$*" >> "$CALL_LOG"\n'
                         'if [ "$1" = tee ]; then cat >/dev/null; fi'),
            ):
                executable = bin_dir / tool
                executable.write_text(f"#!/bin/sh\n{script}\n")
                executable.chmod(0o755)
            for nm_status, wifi in (("3", False), ("0", True)):
                with self.subTest(network_manager_active=wifi):
                    log.write_text("")
                    env = dict(os.environ, PATH=str(bin_dir), CALL_LOG=str(log), NM_STATUS=nm_status,
                               TAPTUNE_RETRY_DELAY="0")
                    result = subprocess.run(
                        [shutil.which("bash"), str(repo / "systemd/install-service.sh")],
                        env=env, capture_output=True, text=True, check=True,
                    )
                    calls = log.read_text()
                    self.assertEqual("apt-get install -y dnsmasq-base nftables" in calls, wifi)
                    self.assertEqual("-m app.wifi_setup provision" in calls, wifi)
                    self.assertEqual("NetworkManager is not running" in result.stderr, not wifi)
                    self.assertNotIn("qrencode", calls)
                    self.assertIn("systemctl enable raspi-spotify-nfc.service", calls)
                    self.assertIn("systemctl restart raspi-spotify-nfc.service", calls)
                    self.assertIn("ln -sfn", calls)


if __name__ == "__main__":
    unittest.main()
