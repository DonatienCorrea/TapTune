import argparse
import time
from dataclasses import dataclass
from typing import Optional

try:
    from mfrc522 import MFRC522
except ImportError:  # pragma: no cover - hardware-specific library not installed in dev
    MFRC522 = None  # type: ignore

try:
    import RPi.GPIO as GPIO
except ImportError:  # pragma: no cover - hardware-specific library not installed in dev
    GPIO = None  # type: ignore


@dataclass
class NFCEvent:
    uid: str
    payload: str
    source: str = "nfc"


class ReaderBase:
    def read_once(self) -> Optional[NFCEvent]:
        raise NotImplementedError

    def write_tag(self, uid: str, payload: str) -> bool:
        raise NotImplementedError


class SimulatedReader(ReaderBase):
    def __init__(self, payload_map: Optional[dict] = None):
        self.payload_map = payload_map or {}

    def read_once(self) -> Optional[NFCEvent]:
        if not self.payload_map:
            return None
        uid, payload = next(iter(self.payload_map.items()))
        return NFCEvent(uid=uid, payload=payload, source="simulated")

    def write_tag(self, uid: str, payload: str) -> bool:
        self.payload_map[uid] = payload
        return True


class RC522Reader(ReaderBase):
    def __init__(self):
        if MFRC522 is None or GPIO is None:
            raise RuntimeError("mfrc522 library not available; install requirements-pi.txt on the Pi.")

        pin_mode = GPIO.getmode()
        if pin_mode is None:
            pin_mode = GPIO.BOARD
            GPIO.setmode(pin_mode)
        reset_pin = 22 if pin_mode == GPIO.BOARD else 25
        GPIO.setup(reset_pin, GPIO.OUT, initial=GPIO.HIGH)
        self.reader = MFRC522(pin_mode=pin_mode, pin_rst=reset_pin)

    def read_once(self) -> Optional[NFCEvent]:
        status, tag_type = self.reader.MFRC522_Request(self.reader.PICC_REQIDL)
        if status != self.reader.MI_OK:
            return None

        status, uid = self.reader.MFRC522_Anticoll()
        if status != self.reader.MI_OK:
            return None

        uid_hex = "".join(f"{byte:02X}" for byte in uid[:4])
        from .db import get_tag_by_uid

        tag = get_tag_by_uid(uid_hex)
        payload = tag["value"] if tag else uid_hex
        return NFCEvent(uid=uid_hex, payload=payload, source="nfc")

    def write_tag(self, uid: str, payload: str) -> bool:
        raise NotImplementedError("RC522 tag writing is not implemented in v1 scaffold; use simulated mode for now.")


def parse_tag_value(value: str) -> str:
    if value.startswith("spotify:") or value.startswith("action:"):
        return value
    return value.strip()


def read_uid_from_hardware(poll_interval_seconds: float = 0.2) -> str:
    """Poll the connected RC522 reader until a tag is present and return its UID.

    Requires the MFRC522 library and SPI to be enabled; intended for use on a
    Raspberry Pi with the reader wired up, not for local development.
    """
    reader = RC522Reader()
    while True:
        event = reader.read_once()
        if event is not None:
            return event.uid
        time.sleep(poll_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate an NFC tag scan or read a real tag's UID")
    parser.add_argument(
        "--read",
        action="store_true",
        help="Poll the connected RC522 reader and print the UID of the next tag presented, then exit.",
    )
    parser.add_argument("--uid", help="Simulated UID (ignored with --read)")
    parser.add_argument("--payload", help="Simulated payload (ignored with --read)")
    args = parser.parse_args()

    if args.read:
        print("Hold a tag near the reader...")
        uid = read_uid_from_hardware()
        print(f"uid={uid}")
        return

    if not args.uid or not args.payload:
        parser.error("--uid and --payload are required unless --read is given")

    reader = SimulatedReader({args.uid: parse_tag_value(args.payload)})
    event = reader.read_once()
    if event is None:
        raise SystemExit("No simulated event produced.")
    print(f"uid={event.uid} payload={event.payload} source={event.source}")


if __name__ == "__main__":
    main()
