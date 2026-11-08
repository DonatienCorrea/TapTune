import logging
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import activity, config, main, spotify_service
from app.db import get_connection
from app.nfc_reader import NFCEvent
from app.simulate import dispatch_simulated_value
from app.web import create_app


class ActivityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        settings = patch.multiple(
            config.settings, DATABASE_PATH=str(Path(temporary.name) / "activity.db"),
            SPOTIFY_CLIENT_ID="", SPOTIFY_CLIENT_SECRET="", SPOTIFY_REFRESH_TOKEN="",
        )
        settings.start()
        self.addCleanup(settings.stop)
        self.client = create_app().test_client()

    def test_existing_database_gets_activity_table_without_losing_tags(self):
        with get_connection() as conn:
            conn.execute("INSERT INTO tags (uid, value, tag_type) VALUES ('old', 'action:next', 'action')")
            conn.execute("DROP TABLE activity")
        activity.record_activity("diagnostic", "INFO", "app.main", "Started")
        with get_connection() as conn:
            self.assertEqual(conn.execute("SELECT uid FROM tags").fetchone()["uid"], "old")
        self.assertEqual(len(activity.list_activity()[0]), 1)

    def test_search_filters_pagination_and_literal_wildcards(self):
        for i in range(55):
            activity.record_activity("playback", "INFO", "nfc", "Episode " + str(i), uid="CARD")
        activity.record_activity("diagnostic", "WARNING", "app.bluetooth", "Speaker 100% unavailable")
        rows, more = activity.list_activity()
        self.assertEqual(len(rows), 50)
        self.assertTrue(more)
        self.assertEqual(rows[0]["source"], "app.bluetooth")
        self.assertEqual(len(activity.list_activity(page=2)[0]), 6)
        self.assertEqual(len(activity.list_activity(query="CARD", kind="playback")[0]), 50)
        self.assertEqual(len(activity.list_activity(level="errors")[0]), 1)
        self.assertEqual(len(activity.list_activity(query="%")[0]), 1)
        self.assertEqual(activity.list_activity(query="' OR 1=1 --")[0], [])
        for filters in ({"page": 0}, {"kind": "other"}, {"query": "a" * 201}, {"level": "DEBUG"}):
            with self.assertRaises(ValueError):
                activity.list_activity(**filters)

    def test_retention_is_bounded(self):
        with patch.object(activity, "ACTIVITY_LIMIT", 3):
            for i in range(6):
                activity.record_activity("diagnostic", "INFO", "app.main", str(i))
        self.assertEqual([row["message"] for row in activity.list_activity()[0]], ["5", "4", "3"])

    def test_logging_redacts_credentials_and_does_not_store_tracebacks(self):
        with patch.multiple(config.settings, SPOTIFY_CLIENT_SECRET="knownsecret", SPOTIFY_REFRESH_TOKEN="knownrefresh"):
            handler = activity.ActivityHandler()
            record = logging.LogRecord(
                "app.spotify_service", logging.ERROR, "", 1,
                "knownsecret knownrefresh Bearer randomtoken access_token=anothersecret Basic encodedsecret", (), None,
            )
            handler.emit(record)
        message = activity.list_activity()[0][0]["message"]
        for secret in ("knownsecret", "knownrefresh", "randomtoken", "anothersecret", "encodedsecret"):
            self.assertNotIn(secret, message)
        self.assertIn("[redacted]", message)

    def test_logging_database_failure_is_reported_without_stopping_playback(self):
        with patch.object(activity, "get_connection", side_effect=sqlite3.OperationalError("locked")), \
                patch.object(activity.sys.stderr, "write") as write:
            activity.record_playback("CARD", "action:next", "nfc", {"status": "ok"})
        write.assert_called_once()

    def test_nfc_records_unknown_success_and_error_results(self):
        main.dispatch_nfc_event(NFCEvent("unknown", "unknown"))
        with patch.object(main, "dispatch_tag_value", return_value={"status": "ok"}):
            main.dispatch_nfc_event(NFCEvent("good", "action:next"))
        with patch.object(main, "dispatch_tag_value", return_value={
            "status": "error", "error": "speaker_not_ready", "message": "Turn on the speaker.",
        }):
            main.dispatch_nfc_event(NFCEvent("bad", "action:next"))
        rows = activity.list_activity(kind="playback")[0]
        self.assertEqual([row["level"] for row in rows], ["ERROR", "INFO", "WARNING"])
        self.assertEqual(rows[0]["uid"], "bad")

    def test_show_dispatch_records_resolved_episode_name_and_uri(self):
        spotify = Mock()
        spotify.show_episodes.return_value = {"items": [{
            "uri": "spotify:episode:newest", "name": "Morning news", "release_date": "2026-11-07",
        }]}
        spotify.current_playback.return_value = {"is_playing": True}
        spotify.start_playback.return_value = None
        with patch.object(spotify_service, "build_spotify_client", return_value=spotify):
            response = self.client.post("/dispatch", data={"value": "spotify:show:news"})
        self.assertEqual(response.status_code, 200)
        row = activity.list_activity()[0][0]
        self.assertEqual(row["value"], "spotify:show:news")
        self.assertEqual(row["resolved_uri"], "spotify:episode:newest")
        self.assertEqual(row["message"], "Morning news")

    def test_simulator_records_demo_and_error_results(self):
        with patch("app.simulate.dispatch_tag_value", return_value={"status": "ok", "mode": "fake"}):
            dispatch_simulated_value("demo", "action:next")
        row = activity.list_activity()[0][0]
        self.assertEqual(row["source"], "simulate")
        self.assertIn("Demo mode", row["message"])

    def test_unexpected_dispatch_failures_are_recorded_without_exception_secrets(self):
        with patch("app.web.dispatch_tag_value", side_effect=RuntimeError("secret")):
            self.assertEqual(self.client.post("/dispatch", data={"value": "action:next"}).status_code, 500)
        with patch("app.simulate.dispatch_tag_value", side_effect=RuntimeError("secret")), \
                self.assertRaises(RuntimeError):
            dispatch_simulated_value("sim", "action:next")
        rows = activity.list_activity(kind="playback")[0]
        self.assertEqual([row["level"] for row in rows], ["ERROR", "ERROR"])
        self.assertTrue(all("secret" not in row["message"] for row in rows))

    def test_bilingual_pages_search_escape_and_navigation(self):
        activity.record_activity("diagnostic", "ERROR", "app.reader", "<script>alert(1)</script>")
        for path in ("/logs", "/fr/logs"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertIn(b"&lt;script&gt;", response.data)
            self.assertNotIn(b"<script>alert", response.data)
            self.assertIn(b'name="q"', response.data)
            self.assertIn(b'name="kind"', response.data)
            self.assertIn(b'name="level"', response.data)
            self.assertIn(b'<details class="log-help">', response.data)
            self.assertIn(b'<details class="activity-details">', response.data)
        self.assertIn(b'href="/logs"', self.client.get("/").data)
        self.assertIn(b'href="/fr/logs"', self.client.get("/fr/").data)
        self.assertIn(b"No matching activity", self.client.get("/logs?q=absent").data)
        self.assertEqual(self.client.get("/logs?page=invalid").status_code, 400)

    def test_activity_logging_installation_is_idempotent(self):
        logger = logging.getLogger("app")
        original = logger.handlers[:]
        self.addCleanup(setattr, logger, "handlers", original)
        logger.handlers = []
        activity.install_activity_logging()
        activity.install_activity_logging()
        self.assertEqual(len(logger.handlers), 1)
        child = logging.getLogger("app.activity_test")
        old_level = child.level
        self.addCleanup(child.setLevel, old_level)
        child.setLevel(logging.INFO)
        child.info("Reader started.")
        self.assertEqual(activity.list_activity()[0][0]["message"], "Reader started.")


if __name__ == "__main__":
    unittest.main()
