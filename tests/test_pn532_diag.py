import unittest
from unittest.mock import patch

from app import pn532_diag
from app.nfc_reader import PN532_LIBRARY_UNAVAILABLE_MESSAGE, NFCEvent


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def __call__(self):
        self.value += 0.1
        return self.value


class PN532DiagnosticTests(unittest.TestCase):
    def test_wait_for_card_returns_detected_uid(self):
        class Reader:
            def __init__(self):
                self.calls = 0

            def read_once(self):
                self.calls += 1
                if self.calls == 2:
                    return NFCEvent(uid="04A7B2F1", payload="04A7B2F1")
                return None

        self.assertEqual(
            pn532_diag.wait_for_card(Reader(), seconds=1, clock=FakeClock()),
            "04A7B2F1",
        )

    def test_wait_for_card_times_out(self):
        class Reader:
            def read_once(self):
                return None

        with self.assertRaisesRegex(TimeoutError, "No NFC card detected"):
            pn532_diag.wait_for_card(Reader(), seconds=0.2, clock=FakeClock())

    def test_main_surfaces_missing_library_message_without_wiring_text(self):
        with patch(
            "app.pn532_diag.PN532Reader",
            side_effect=RuntimeError(PN532_LIBRARY_UNAVAILABLE_MESSAGE),
        ), patch("sys.argv", ["pn532_diag", "--seconds", "1"]):
            with self.assertRaises(SystemExit) as ctx:
                pn532_diag.main()
        self.assertEqual(str(ctx.exception), PN532_LIBRARY_UNAVAILABLE_MESSAGE)
        self.assertNotIn("wiring/power", str(ctx.exception))

    def test_main_surfaces_generic_wiring_message_for_other_runtime_errors(self):
        with patch(
            "app.pn532_diag.PN532Reader",
            side_effect=RuntimeError("I2C bus busy"),
        ), patch("sys.argv", ["pn532_diag", "--seconds", "1"]):
            with self.assertRaises(SystemExit) as ctx:
                pn532_diag.main()
        self.assertIn("wiring/power", str(ctx.exception))
        self.assertIn("I2C bus busy", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
