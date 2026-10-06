import threading
import unittest
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

    def test_reader_failure_interrupts_the_main_service(self):
        reader = object()
        with patch.object(main, "run_reader_loop", side_effect=OSError("I2C failed")):
            with patch.object(main._thread, "interrupt_main") as interrupt:
                main.run_reader_loop_or_stop(reader)

        interrupt.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
