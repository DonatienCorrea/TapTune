import os
import stat
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from app import config, setup
from app.web import create_app


def runner_for(outputs):
    def run(args, **kwargs):
        out = outputs.get(args[0])
        if out is None:
            return CompletedProcess(args, 1, "", "")
        return CompletedProcess(args, 0, out, "")
    return run


class EnvWriterTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.path = Path(self.dir.name) / ".env"

    def test_updates_known_keys_and_preserves_everything_else(self):
        self.path.write_text("# note\nAPP_PORT=5001\nSPOTIFY_CLIENT_ID=old\nSPOTIFY_CLIENT_ID=dup\nCUSTOM=\"a b\"\n")
        os.chmod(self.path, 0o640)
        setup.write_env({"SPOTIFY_CLIENT_ID": "new", "BLUETOOTH_SPEAKER_MAC": "aa:bb:cc:dd:ee:ff"}, self.path)
        self.assertEqual(
            self.path.read_text(),
            "# note\nAPP_PORT=5001\nSPOTIFY_CLIENT_ID=new\nCUSTOM=\"a b\"\nBLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF\n",
        )
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o640)
        self.assertEqual([p.name for p in Path(self.dir.name).iterdir()], [".env"])

    def test_rejects_unknown_keys_and_injection_without_touching_file(self):
        self.path.write_text("A=1\n")
        for bad in ({"APP_PORT": "1"}, {"SPOTIFY_CLIENT_ID": "x\nEVIL=1"}, {"BLUETOOTH_SPEAKER_MAC": "nope"}):
            with self.assertRaises(setup.InvalidSetting):
                setup.write_env(bad, self.path)
        self.assertEqual(self.path.read_text(), "A=1\n")

    def test_failed_write_keeps_original_and_cleans_temp_file(self):
        self.path.write_text("A=1\n")
        with patch("app.setup.os.replace", side_effect=OSError), self.assertRaises(OSError):
            setup.write_env({"SPOTIFY_CLIENT_ID": "x"}, self.path)
        self.assertEqual(self.path.read_text(), "A=1\n")
        self.assertEqual([p.name for p in Path(self.dir.name).iterdir()], [".env"])


class StatusTests(unittest.TestCase):
    def test_wifi(self):
        up = runner_for({"nmcli": "wifi:connected:Home\nethernet:unavailable:\n"})
        self.assertEqual(setup.wifi_status(up)["state"], "done")
        down = runner_for({"nmcli": "wifi:disconnected:\n"})
        self.assertEqual(setup.wifi_status(down)["reason"], "disconnected")
        self.assertEqual(setup.wifi_status(runner_for({}))["reason"], "unavailable")

    def test_bluetooth(self):
        mac = "AA:BB:CC:DD:EE:FF"
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", ""):
            self.assertEqual(setup.bluetooth_status()["reason"], "not_configured")
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", mac):
            self.assertEqual(setup.bluetooth_status(runner_for({"bluetoothctl": "\tConnected: yes\n"}))["state"], "done")
            self.assertEqual(setup.bluetooth_status(runner_for({"bluetoothctl": "\tConnected: no\n"}))["reason"], "not_connected")
            self.assertEqual(setup.bluetooth_status(runner_for({}))["reason"], "not_paired")


class RouteTests(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(config.settings, "SETUP_SKIP", False),
                  patch("app.setup.setup_steps", return_value=[
                      {"id": "wifi", "state": "done", "reason": "wired"},
                      {"id": "bluetooth", "state": "todo", "reason": "not_configured"},
                      {"id": "spotify", "state": "todo", "reason": "not_configured"}])):
            p.start()
            self.addCleanup(p.stop)
        self.client = create_app().test_client()

    def test_incomplete_setup_redirects_home_in_both_languages(self):
        self.assertEqual(self.client.get("/").headers["Location"], "/setup")
        self.assertEqual(self.client.get("/fr/").headers["Location"], "/fr/setup")

    def test_setup_pages_show_status_in_both_languages(self):
        en = self.client.get("/setup").get_data(as_text=True)
        fr = self.client.get("/fr/setup").get_data(as_text=True)
        self.assertIn('data-step="bluetooth" data-state="todo"', en)
        self.assertIn("No speaker chosen", en)
        self.assertIn("Aucune enceinte choisie", fr)
        self.assertEqual(self.client.get("/api/setup").get_json()["complete"], False)

    def test_complete_setup_serves_home(self):
        done = [{"id": i, "state": "done", "reason": "x"} for i in ("wifi", "bluetooth", "spotify")]
        with patch("app.setup.setup_steps", return_value=done):
            self.assertEqual(self.client.get("/").status_code, 200)

    def test_save_writes_env_and_restarts_and_rejects_cross_site(self):
        with patch("app.setup.write_env") as write, patch("app.setup.restart_service") as restart:
            response = self.client.post("/setup", data={"SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": ""})
            self.assertEqual(response.status_code, 303)
            write.assert_called_once_with({"SPOTIFY_CLIENT_ID": "id"})
            restart.assert_called_once()
            write.reset_mock()
            blocked = self.client.post("/setup", data={"SPOTIFY_CLIENT_ID": "id"}, headers={"Sec-Fetch-Site": "cross-site"})
            self.assertEqual(blocked.status_code, 403)
            write.assert_not_called()
        with patch("app.setup.restart_service") as restart:
            bad = self.client.post("/setup", data={"BLUETOOTH_SPEAKER_MAC": "zz"})
            self.assertEqual(bad.status_code, 400)
            restart.assert_not_called()


if __name__ == "__main__":
    unittest.main()
