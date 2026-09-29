import subprocess
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

        self.assertIn(f"WorkingDirectory={REPO_ROOT}", output)
        self.assertIn(f"ExecStart={REPO_ROOT}/.venv/bin/python -m app.main", output)
        self.assertIn(f"EnvironmentFile={REPO_ROOT}/.env", output)
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


if __name__ == "__main__":
    unittest.main()
