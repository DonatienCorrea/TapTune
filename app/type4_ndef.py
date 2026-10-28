"""NFC Forum Type 4 NDEF files using short ISO 7816 APDUs."""

import logging

from .ndef import wrap_ndef_message

logger = logging.getLogger(__name__)


class Type4Error(RuntimeError):
    def __init__(self, code, detail=None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Type4Ndef:
    def __init__(self, reader):
        self.reader = reader
        self.read_size = 15
        self.write_size = 0
        self.capacity = 0
        self.writable = False

    def exchange(self, apdu, error="tag_read_failed"):
        response = self.reader.call_function(
            0x40, params=b"\x01" + apdu, response_length=243,
        )
        if response is None or len(response) < 3 or response[0] != 0:
            status = response[0] if response else None
            raise Type4Error(error, f"APDU {apdu[1]:02X}, PN532 status {status}")
        status = bytes(response[-2:])
        if status != b"\x90\x00":
            raise Type4Error(
                "tag_locked" if status == b"\x69\x82" else error,
                f"APDU {apdu[1]:02X}, status {status.hex()}",
            )
        return bytes(response[1:-2])

    def select(self):
        self.exchange(
            bytes.fromhex("00a4040007d276000085010100"), "unsupported_tag",
        )
        self.exchange(bytes.fromhex("00a4000c02e103"), "unsupported_tag")
        header = self.read(0, 7)
        cc_length = int.from_bytes(header[:2], "big")
        max_read = int.from_bytes(header[3:5], "big")
        max_write = int.from_bytes(header[5:7], "big")
        if not 15 <= cc_length <= 256 or header[2] >> 4 not in (1, 2) or max_read < 15:
            raise Type4Error("unsupported_tag")
        self.read_size = min(max_read, 240)
        self.write_size = min(max_write, 240)
        cc = header + self.read(7, cc_length - 7)
        index = 7
        while index < len(cc):
            kind = cc[index]
            if kind == 0:
                index += 1
                continue
            if kind == 0xFE:
                break
            if index + 2 > len(cc):
                raise Type4Error("unsupported_tag")
            length = cc[index + 1]
            end = index + 2 + length
            if end > len(cc):
                raise Type4Error("unsupported_tag")
            if kind == 4:
                if length != 6:
                    raise Type4Error("unsupported_tag")
                file_id = cc[index + 2:index + 4]
                capacity = int.from_bytes(cc[index + 4:index + 6], "big")
                read_access, write_access = cc[index + 6:index + 8]
                if file_id in (b"\x00\x00", b"\xe1\x02", b"\xe1\x03", b"\x3f\x00", b"\x3f\xff", b"\xff\xff"):
                    raise Type4Error("unsupported_tag")
                if not 2 <= capacity <= 0x7FFF:
                    raise Type4Error("unsupported_tag")
                if read_access != 0:
                    raise Type4Error("tag_locked")
                self.capacity = capacity
                self.writable = write_access == 0 and self.write_size >= 2
                self.exchange(b"\x00\xa4\x00\x0c\x02" + file_id, "unsupported_tag")
                logger.debug(
                    "Type 4 NDEF file %s: capacity=%d, writable=%s, read=%d, write=%d",
                    file_id.hex(), capacity, self.writable, self.read_size, self.write_size,
                )
                return
            index = end
        raise Type4Error("unsupported_tag")

    def read(self, offset, length):
        result = bytearray()
        while len(result) < length:
            size = min(self.read_size, length - len(result))
            position = offset + len(result)
            data = self.exchange(b"\x00\xb0" + position.to_bytes(2, "big") + bytes([size]))
            if len(data) != size:
                raise Type4Error("tag_read_failed")
            result.extend(data)
        return bytes(result)

    def read_message(self):
        length = int.from_bytes(self.read(0, 2), "big")
        if length > self.capacity - 2:
            raise Type4Error("tag_read_failed")
        return self.read(2, length)

    def read_memory(self):
        return wrap_ndef_message(self.read_message())

    def update(self, offset, data):
        for index in range(0, len(data), self.write_size):
            block = data[index:index + self.write_size]
            position = offset + index
            self.exchange(
                b"\x00\xd6" + position.to_bytes(2, "big") + bytes([len(block)]) + block,
                "tag_write_failed",
            )

    def write_message(self, message):
        if not self.writable:
            raise Type4Error("tag_locked")
        if len(message) > self.capacity - 2:
            raise Type4Error("tag_too_small")
        self.update(0, b"\x00\x00")
        self.update(2, message)
        self.update(0, len(message).to_bytes(2, "big"))
