import unittest

from app import pn532_diag
from app.nfc_reader import NFCEvent


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


if __name__ == "__main__":
    unittest.main()
