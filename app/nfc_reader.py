import argparse
import logging
import time
from dataclasses import dataclass
from typing import Optional

from .ndef import NdefError, encode_spotify_ndef, extract_ndef_message, ndef_block_end, tag_value_from_ndef
from .type4_ndef import Type4Error, Type4Ndef

logger = logging.getLogger(__name__)

CAPABILITY_CONTAINER_PAGE = 3
USER_MEMORY_FIRST_PAGE = 4
NDEF_MAGIC_NUMBER = 0xE1
TYPE2_TRANSFER_DELAY_SECONDS = 0.02
TYPE2_WRITE_MAX_ATTEMPTS = 3
TYPE2_WRITE_RETRY_DELAY_SECONDS = 0.1


class TargetProtocolMixin:
    """Keep the SAK byte that the upstream UID-only polling API discards."""

    target_sak = None

    def process_response(self, command, response_length=0, timeout=1):
        response = super().process_response(command, response_length=response_length, timeout=timeout)
        if command == 0x4A:
            self.target_sak = None
            if response is not None:
                if (len(response) < 6 or response[0] != 1
                        or response[5] not in (4, 7) or len(response) < 6 + response[5]):
                    raise RuntimeError("Invalid PN532 target discovery response")
                self.target_sak = response[4]
        return response


try:
    import board
    from adafruit_pn532.i2c import PN532_I2C as AdafruitPN532I2C

    class PN532_I2C(TargetProtocolMixin, AdafruitPN532I2C):
        pass

except (ImportError, NotImplementedError):  # pragma: no cover - Pi-only dependencies
    board = None  # type: ignore
    PN532_I2C = None  # type: ignore

PN532_I2C_ADDRESS = 0x24

PN532_LIBRARY_UNAVAILABLE_MESSAGE = (
    "PN532 support is not available; install requirements-pi.txt on the Pi."
)


class TagWriteError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


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
        if self.reader.target_sak is None:
            logger.warning("NFC protocol unavailable; using UID mapping.")
            return None
        if not self.reader.target_sak & 0x20:
            return self.read_type2_memory()
        try:
            tag = Type4Ndef(self.reader)
            tag.select()
            return tag.read_memory()
        except (Type4Error, RuntimeError, OSError) as error:
            logger.debug("Type 4 NDEF read unavailable: %s", error)
            return None

    def read_type2_memory(self) -> Optional[bytes]:
        """Read the NDEF area of a Type 2 tag such as an NTAG21x.

        Returns None when the tag is not Type 2, holds no NDEF block, or a page
        read fails, so the caller can fall back to the UID mapping.
        """
        try:
            capability = self.reader.ntag2xx_read_block(CAPABILITY_CONTAINER_PAGE)
            if capability is None or len(capability) != 4 or capability[0] != NDEF_MAGIC_NUMBER:
                return None
            capacity = capability[2] * 8
            if capacity < 16:
                logger.warning("Type 2 NDEF capacity is too small for a bounded READ.")
                return None
            data = bytearray()
            while len(data) < capacity:
                # READ returns four pages. Keep the final window inside user
                # memory even when capacity is not a multiple of 16 bytes.
                offset = min(len(data), capacity - 16)
                page = USER_MEMORY_FIRST_PAGE + offset // 4
                time.sleep(TYPE2_TRANSFER_DELAY_SECONDS)
                response = self.reader.call_function(
                    0x40, params=bytes([1, 0x30, page]), response_length=17,
                )
                if response is None or len(response) != 17 or response[0] != 0:
                    status = response[0] if response else None
                    logger.warning("Type 2 READ failed at page %d (PN532 status %s).", page, status)
                    return None
                data.extend(response[1 + len(data) - offset:])
                try:
                    end = ndef_block_end(bytes(data))
                except NdefError:
                    return None
                if end is not None and end <= len(data):
                    return bytes(data)
        except (RuntimeError, OSError) as error:
            logger.warning("Type 2 NDEF read failed: %s", error)
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
        data = encode_spotify_ndef(payload)
        present = self.reader.read_passive_target(timeout=0.1)
        if present is None or bytes(present).hex().upper() != uid:
            raise TagWriteError("tag_changed")
        if self.reader.target_sak is None:
            raise TagWriteError("unsupported_tag")
        if self.reader.target_sak & 0x20:
            return self.write_type4_tag(uid, payload, extract_ndef_message(data))

        # Accept only known layouts, never infer writable pages from capacity alone.
        # InDataExchange interprets 0x60 as MIFARE authentication. Send the
        # NTAG GET_VERSION command raw, without an InDataExchange target byte.
        try:
            version = self.reader.call_function(0x42, params=[0x60], response_length=9)
        except (RuntimeError, OSError) as error:
            raise TagWriteError("tag_read_failed") from error
        feiju_144 = version is not None and bytes(version) == bytes.fromhex("000053040201000f03")
        if not feiju_144 and (version is None or len(version) != 9
                or bytes(version[:7]) != b"\x00\x00\x04\x04\x02\x01\x00"
                or version[7] not in (0x0F, 0x11, 0x13) or version[8] != 3):
            raise TagWriteError("unsupported_tag")
        physical_capacity = {0x0F: 144, 0x11: 504, 0x13: 888}[version[7]]
        capability = self.reader.ntag2xx_read_block(3)
        if capability is None or len(capability) < 4 or capability[0] != NDEF_MAGIC_NUMBER:
            raise TagWriteError("unsupported_tag")
        if capability[1] >> 4 != 1 or capability[3] != 0:
            raise TagWriteError("tag_locked")
        first_page = USER_MEMORY_FIRST_PAGE
        empty_header = b"\x03\x00\xfe\x00"
        if feiju_144:
            if bytes(capability) != b"\xe1\x10\x12\x00":
                raise TagWriteError("unsupported_tag")
            prefix = bytearray()
            for page in (4, 5):
                block = self.reader.ntag2xx_read_block(page)
                if block is None or len(block) != 4:
                    raise TagWriteError("tag_read_failed")
                prefix.extend(block)
            # Lock Control TLV advertises 12 lock bits at byte 160 (page 40).
            if prefix[:5] != b"\x01\x03\xa0\x0c\x34":
                raise TagWriteError("unsupported_tag")
            data = bytes(prefix[:5]) + data
            first_page = 5
            empty_header = b"\x34\x03\x00\xfe"
            logger.info("Using Feiju 144-byte Type 2 profile; preserving Lock Control TLV.")
        capacity = min(capability[2] * 8, physical_capacity)
        padded = data + b"\x00" * (-len(data) % 4)
        if len(padded) > capacity:
            raise TagWriteError("tag_too_small")
        static = self.reader.ntag2xx_read_block(2)
        dynamic = self.reader.ntag2xx_read_block(4 + physical_capacity // 4)
        if static is None or dynamic is None or len(static) != 4 or len(dynamic) != 4:
            raise TagWriteError("tag_read_failed")
        if any(static[2:4]) or any(dynamic[:3]):
            raise TagWriteError("tag_locked")

        def write(page, block):
            for attempt in range(1, TYPE2_WRITE_MAX_ATTEMPTS + 1):
                try:
                    if attempt > 1:
                        time.sleep(TYPE2_WRITE_RETRY_DELAY_SECONDS)
                        self.check_uid(uid)
                    if feiju_144:
                        time.sleep(TYPE2_TRANSFER_DELAY_SECONDS)
                    response = self.reader.call_function(
                        0x40, params=bytes([1, 0xA2, page]) + bytes(block), response_length=1,
                    )
                except TagWriteError:
                    raise
                except (RuntimeError, OSError) as error:
                    logger.warning("Type 2 WRITE failed at page %d: %s", page, error)
                    raise TagWriteError("tag_write_failed") from error
                if response is not None and len(response) == 1 and response[0] == 0:
                    return
                status = response[0] if response else None
                if response is not None and len(response) == 1 and status == 0x0B and attempt < TYPE2_WRITE_MAX_ATTEMPTS:
                    logger.warning(
                        "Type 2 WRITE protocol error at page %d (attempt %d/%d); "
                        "rechecking UID before retry.",
                        page, attempt, TYPE2_WRITE_MAX_ATTEMPTS,
                    )
                    continue
                logger.warning("Type 2 WRITE failed at page %d (PN532 status %s).", page, status)
                raise TagWriteError("tag_write_failed")

        # Publish the length last. An interrupted write must not expose a
        # partially updated record as a valid NDEF message.
        first_offset = (first_page - USER_MEMORY_FIRST_PAGE) * 4
        write(first_page, empty_header)
        for index in range(first_offset + 4, len(padded), 4):
            write(4 + index // 4, padded[index:index + 4])
        write(first_page, padded[first_offset:first_offset + 4])
        present = self.reader.read_passive_target(timeout=0.1)
        if present is None or bytes(present).hex().upper() != uid:
            raise TagWriteError("tag_changed")
        memory = self.read_type2_memory()
        if memory is None or memory[:len(data) - 1] != data[:-1] or tag_value_from_ndef(memory) != payload:
            raise TagWriteError("tag_verify_failed")
        self._last_payload = payload
        self._last_uid = uid
        return True

    def write_type4_tag(self, uid, payload, message):
        self.check_uid(uid)
        try:
            tag = Type4Ndef(self.reader)
            tag.select()
            tag.write_message(message)
            self.check_uid(uid)
            tag.select()
            memory = tag.read_memory()
            if extract_ndef_message(memory) != message or tag_value_from_ndef(memory) != payload:
                raise TagWriteError("tag_verify_failed")
        except Type4Error as error:
            raise TagWriteError(error.code) from error
        self._last_payload = payload
        self._last_uid = uid
        return True

    def check_uid(self, uid):
        present = self.reader.read_passive_target(timeout=0.1)
        if present is None or bytes(present).hex().upper() != uid:
            raise TagWriteError("tag_changed")


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
