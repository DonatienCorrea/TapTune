import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "systemd" / "install-pi-dependencies.sh"


class InstallPiDependenciesScriptTests(unittest.TestCase):
    def test_dry_run_replaces_rpi_gpio_before_installing_mfrc522(self):
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--dry-run"],
            capture_output=True,
            text=True,
            check=True,
        )

        commands = result.stdout.splitlines()
        self.assertIn("pip uninstall -y RPi.GPIO rpi-lgpio", commands[0])
        self.assertIn("requirements-pi.txt", commands[2])
        self.assertIn("pip install --no-deps mfrc522==0.0.7", commands[3])

        requirements = (REPO_ROOT / "requirements-pi.txt").read_text()
        self.assertIn("rpi-lgpio==0.6", requirements)
        self.assertNotIn("RPi.GPIO", requirements)

    def test_rejects_unknown_argument(self):
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--bogus"],
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unknown argument", result.stderr)


if __name__ == "__main__":
    unittest.main()
