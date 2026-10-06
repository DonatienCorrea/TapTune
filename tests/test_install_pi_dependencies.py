import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "systemd" / "install-pi-dependencies.sh"


class InstallPiDependenciesScriptTests(unittest.TestCase):
    def test_dry_run_installs_base_and_pn532_dependencies(self):
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--dry-run"],
            capture_output=True,
            text=True,
            check=True,
        )

        commands = result.stdout.splitlines()
        self.assertEqual(len(commands), 2)
        self.assertIn("requirements.txt", commands[0])
        self.assertIn("requirements-pi.txt", commands[1])

        requirements = (REPO_ROOT / "requirements-pi.txt").read_text()
        self.assertIn("Adafruit-Blinka", requirements)
        self.assertIn("adafruit-circuitpython-pn532", requirements)
        self.assertNotIn("mfrc522", requirements)

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
