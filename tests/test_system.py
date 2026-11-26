import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, system
from app.web import create_app

SAME_ORIGIN = {"Origin": "http://localhost"}


def runner_reporting(active_state):
    def runner(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout=active_state + "\n", stderr="")
    return runner


class UpdateStatusTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        p = patch.object(config.settings, "DATABASE_PATH", str(Path(directory.name) / "taptune.db"))
        p.start()
        self.addCleanup(p.stop)
        self.log = Path(directory.name) / "update.log"

    def test_exit_marker_decides_success_and_is_hidden_from_the_log(self):
        idle = runner_reporting("inactive")
        self.assertEqual(system.update_status(idle), {"state": "idle", "finished_at": None, "log": ""})
        self.log.write_text("==> Updating\n==> Update finished.\nTAPTUNE_UPDATE_EXIT=0\n")
        status = system.update_status(idle)
        self.assertEqual(status["state"], "succeeded")
        self.assertEqual(status["log"], "==> Updating\n==> Update finished.")
        self.assertIsNotNone(status["finished_at"])
        self.log.write_text("error: download failed\nTAPTUNE_UPDATE_EXIT=1\n")
        self.assertEqual(system.update_status(idle)["state"], "failed")
        self.log.write_text("==> Updating\n")
        self.assertEqual(system.update_status(idle)["state"], "failed")

    def test_running_unit_reports_running(self):
        self.log.write_text("==> Updating\n")
        status = system.update_status(runner_reporting("active"))
        self.assertEqual((status["state"], status["finished_at"]), ("running", None))


class SystemRouteTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        for p in (patch.multiple(config.settings, SETUP_SKIP=True,
                                 DATABASE_PATH=str(Path(directory.name) / "taptune.db")),
                  patch.object(system, "code_version", return_value="abc1234"),
                  patch.object(system, "update_status",
                               return_value={"state": "idle", "finished_at": None, "log": "last update log"})):
            p.start()
            self.addCleanup(p.stop)
        self.client = create_app().test_client()

    def test_status_reports_version_and_update_state(self):
        response = self.client.get("/api/system")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {
            "version": "abc1234", "update": {"state": "idle", "finished_at": None, "log": "last update log"},
        })

    def test_actions_need_a_same_origin_json_request(self):
        with patch.object(system, "restart_app") as restart:
            self.assertEqual(self.client.post("/api/system/restart").status_code, 403)
            self.assertEqual(self.client.post("/api/system/restart", json={},
                                              headers={"Origin": "http://evil.example"}).status_code, 403)
            restart.assert_not_called()
            response = self.client.post("/api/system/restart", json={}, headers=SAME_ORIGIN)
        self.assertEqual(response.status_code, 202)
        restart.assert_called_once_with()

    def test_update_already_running_is_a_conflict(self):
        with patch.object(system, "start_update", side_effect=system.UpdateRunning()):
            response = self.client.post("/api/system/update", json={}, headers=SAME_ORIGIN)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json(), {"error": "update_running"})

    def test_diagnostics_download_includes_the_update_log_and_journal(self):
        with patch.object(system, "journal", return_value="journal line"), \
                patch("app.setup.setup_steps", return_value=[]):
            response = self.client.get("/api/system/diagnostics")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content_type.startswith("text/plain"))
        self.assertIn("attachment", response.headers["Content-Disposition"])
        text = response.get_data(as_text=True)
        self.assertIn("TapTune abc1234", text)
        self.assertIn("last update log", text)
        self.assertIn("journal line", text)


if __name__ == "__main__":
    unittest.main()
