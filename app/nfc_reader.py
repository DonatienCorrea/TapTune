import argparse
import time
from dataclasses import dataclass
from typing import Optional

from .ndef import NdefError, ndef_block_end, tag_value_from_ndef

CAPABILITY_CONTAINER_PAGE = 3
USER_MEMORY_FIRST_PAGE = 4
NDEF_MAGIC_NUMBER = 0xE1

try:
    import board
    from adafruit_pn532.i2c import PN532_I2C
except (ImportError, NotImplementedError):  # pragma: no cover - Pi-only dependencies
    board = None  # type: ignore
    PN532_I2C = None  # type: ignore

PN532_I2C_ADDRESS = 0x24

PN532_LIBRARY_UNAVAILABLE_MESSAGE = (
    "PN532 support is not available; install requirements-pi.txt on the Pi."
)


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


class PN532Reader(ReaderBase):
    def __init__(self, i2c=None, reader_factory=None):
        factory = reader_factory or PN532_I2C
        if factory is None or (i2c is None and board is None):
            raise RuntimeError(PN532_LIBRARY_UNAVAILABLE_MESSAGE)

        self.i2c = i2c or board.I2C()
        self.reader = factory(self.i2c, debug=False)
        self.reader.SAM_configuration()

        self._last_uid = None
        self._last_payload = None

    def read_ndef_memory(self) -> Optional[bytes]:
        """Read the NDEF area of a Type 2 tag such as an NTAG21x.

        Returns None when the tag is not Type 2, holds no NDEF block, or a page
        read fails, so the caller can fall back to the UID mapping.
        """
        try:
            capability = self.reader.ntag2xx_read_block(CAPABILITY_CONTAINER_PAGE)
            if capability is None or capability[0] != NDEF_MAGIC_NUMBER:
                return None
            capacity = capability[2] * 8
            data = bytearray()
            for page in range(USER_MEMORY_FIRST_PAGE, USER_MEMORY_FIRST_PAGE + capacity // 4):
                block = self.reader.ntag2xx_read_block(page)
                if block is None:
                    return None
                data.extend(block)
                try:
                    end = ndef_block_end(bytes(data))
                except NdefError:
                    return None
                if end is not None and end <= len(data):
                    return bytes(data)
        except (RuntimeError, OSError):
            return None
        return None

    def read_once(self) -> Optional[NFCEvent]:
        uid = self.reader.read_passive_target(timeout=0.1)
        if uid is None:
            self._last_uid = None
            return None

        uid_hex = "".join(f"{byte:02X}" for byte in uid)
        if uid_hex != self._last_uid:
            self._last_payload = payload_for_tag(uid_hex, self.read_ndef_memory())
            self._last_uid = uid_hex
        return NFCEvent(uid=uid_hex, payload=self._last_payload, source="nfc")

    def write_tag(self, uid: str, payload: str) -> bool:
        raise NotImplementedError(
            "PN532 tag writing is not implemented; write NDEF values with a phone or assign the UID in TapTune."
        )


def parse_tag_value(value: str) -> str:
    if value.startswith("spotify:") or value.startswith("action:"):
        return value
    return value.strip()


def payload_for_tag(uid: str, ndef_bytes: Optional[bytes] = None, lookup=None) -> str:
    """Choose what a scanned tag should play.

    A self-describing tag carries its own value in an NDEF message, so that wins
    when it is present and readable. Tags written before NDEF support, or tags a
    phone has not written, still fall back to the registered UID mapping and
    finally to the raw UID.
    """
    if ndef_bytes:
        value = tag_value_from_ndef(ndef_bytes)
        if value:
            return parse_tag_value(value)
    if lookup is None:
        from .db import get_tag_by_uid as lookup  # noqa: N813
    tag = lookup(uid)
    return tag["value"] if tag else uid


def read_uid_from_hardware(poll_interval_seconds: float = 0.2) -> str:
    """Poll the connected PN532 reader until a tag is present and return its UID.

    Requires the PN532 library and I2C to be enabled; intended for use on a
    Raspberry Pi with the reader wired up, not for local development.
    """
    reader = PN532Reader()
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
        help="Poll the connected PN532 reader and print the UID of the next tag presented, then exit.",
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
