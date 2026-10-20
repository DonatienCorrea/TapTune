import threading
import unittest
import unittest.mock
from unittest.mock import patch

from app import main
from app.nfc_reader import NFCEvent


class ReaderLoopTests(unittest.TestCase):
    def test_dispatch_nfc_event_records_and_dispatches_assigned_value(self):
        event = NFCEvent(uid="04A7B2F1", payload="action:next")

        with patch.object(main, "record_event") as record:
            with patch.object(main, "dispatch_tag_value", return_value={"status": "ok"}) as dispatch:
                result = main.dispatch_nfc_event(event)

        record.assert_called_once_with("04A7B2F1", "action", "action:next", source="nfc")
        dispatch.assert_called_once_with("action:next")
        self.assertEqual(result, {"status": "ok"})

    def test_reader_loop_dispatches_once_until_card_is_removed(self):
        stop = threading.Event()
        card = NFCEvent(uid="04A7B2F1", payload="action:next")

        class Reader:
            def __init__(self):
                self.events = iter([card, card, None, card])

            def read_once(self):
                try:
                    return next(self.events)
                except StopIteration:
                    stop.set()
                    return None

        with patch.object(main, "dispatch_nfc_event") as dispatch:
            main.run_reader_loop(Reader(), stop_event=stop, idle_sleep_seconds=0)

        self.assertEqual(dispatch.call_count, 2)

    def test_unassigned_card_is_not_dispatched(self):
        event = NFCEvent(uid="04A7B2F1", payload="04A7B2F1")

        with patch.object(main, "record_event") as record:
            with patch.object(main, "dispatch_tag_value") as dispatch:
                result = main.dispatch_nfc_event(event)

        self.assertIsNone(result)
        record.assert_not_called()
        dispatch.assert_not_called()

    def test_reader_is_reopened_after_startup_failures(self):
        stop = threading.Event()
        ready = threading.Event()
        attempts = []

        def factory():
            attempts.append(1)
            if len(attempts) < 3:
                raise OSError("I2C not ready")
            return object()

        def loop(reader, stop_event=None):
            self.assertTrue(ready.is_set())
            stop.set()

        sleep = unittest.mock.Mock()
        with patch.object(main, "run_reader_loop", side_effect=loop), \
                patch.object(main._thread, "interrupt_main") as interrupt, \
                self.assertLogs(main.logger, level="WARNING"):
            main.run_reader_supervisor(factory, stop_event=stop, ready_event=ready, sleep=sleep)

        self.assertEqual(len(attempts), 3)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [2.0, 4.0])
        interrupt.assert_not_called()

    def test_reader_failure_interrupts_the_main_service_after_repeated_errors(self):
        factory = unittest.mock.Mock(side_effect=OSError("I2C failed"))
        with patch.object(main._thread, "interrupt_main") as interrupt, \
                self.assertLogs(main.logger, level="ERROR"):
            main.run_reader_supervisor(factory, sleep=unittest.mock.Mock(), max_failures=3)

        self.assertEqual(factory.call_count, 3)
        interrupt.assert_called_once_with()

    def test_dispatch_failure_does_not_stop_the_reader(self):
        event = NFCEvent(uid="04A7B2F1", payload="action:next")
        with patch.object(main, "record_event"), \
                patch.object(main, "dispatch_tag_value", side_effect=RuntimeError("boom")), \
                self.assertLogs(main.logger, level="ERROR"):
            self.assertIsNone(main.dispatch_nfc_event(event))

    def test_ready_endpoint_waits_for_reader_to_open(self):
        from app import config
        from app.web import app

        thread = unittest.mock.Mock()
        thread.is_alive.return_value = True
        thread.reader_ready = threading.Event()
        app.config["NFC_READER_THREAD"] = thread
        self.addCleanup(app.config.pop, "NFC_READER_THREAD", None)
        with patch.multiple(
            config.settings, NFC_READER_ENABLED=True,
            SPOTIFY_CLIENT_ID="id", SPOTIFY_CLIENT_SECRET="secret", SPOTIFY_REFRESH_TOKEN="token",
        ):
            client = app.test_client()
            self.assertEqual(client.get("/ready").status_code, 503)
            thread.reader_ready.set()
            self.assertEqual(client.get("/ready").status_code, 200)

if __name__ == "__main__":
    unittest.main()
