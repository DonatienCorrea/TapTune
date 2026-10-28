import unittest
from unittest.mock import patch

from app.ndef import encode_spotify_ndef, extract_ndef_message
from app.nfc_reader import PN532Reader, TagWriteError
from app.tag_writer import TagWriter
from app.type4_ndef import Type4Error, Type4Ndef


VALUE = "spotify:album:123abc"


class Type4Tag:
    def __init__(self):
        self.uid = bytes.fromhex("9b883506")
        self.cc = bytearray.fromhex("000f20002000100406e10401000000")
        self.memory = bytearray(256)
        self.selected = None
        self.writes = []
        self.commands = []
        self.present = True
        self.fail_at = None
        self.corrupt = False
        self.swap = False
        self.denied = False

    def SAM_configuration(self):
        pass

    def read_passive_target(self, timeout):
        self.selected = None
        if not self.present:
            return None
        return b"\x01\x02\x03\x04" if self.swap and self.writes else self.uid

    def ntag2xx_read_block(self, page):
        return None

    def ntag2xx_write_block(self, page, data):
        raise AssertionError("Type 4 tags must never receive page writes")

    def call_function(self, command, params, response_length):
        if command == 0x42:
            return b"\x01"
        if command != 0x40 or bytes(params[:1]) != b"\x01":
            raise AssertionError("Expected InDataExchange with target 1")
        apdu = bytes(params[1:])
        self.commands.append(apdu)
        if apdu == bytes.fromhex("00a4040007d276000085010100"):
            return b"\x00\x6a\x82" if self.denied else b"\x00\x90\x00"
        if apdu[:4] == bytes.fromhex("00a4000c"):
            if apdu[4:] not in (bytes.fromhex("02e103"), bytes.fromhex("02e104")):
                raise AssertionError("Unexpected file")
            self.selected = apdu[-2:]
            return b"\x00\x90\x00"
        offset = int.from_bytes(apdu[2:4], "big")
        if apdu[:2] == b"\x00\xb0":
            initial_cc_read = self.selected == b"\xe1\x03" and offset == 0 and apdu[4] == 7
            if not initial_cc_read and apdu[4] > min(int.from_bytes(self.cc[3:5], "big"), 240):
                raise AssertionError("READ BINARY exceeds the transfer limit")
            data = self.cc if self.selected == b"\xe1\x03" else self.memory
            return b"\x00" + bytes(data[offset:offset + apdu[4]]) + b"\x90\x00"
        if apdu[:2] == b"\x00\xd6":
            if self.selected != b"\xe1\x04":
                raise AssertionError("Only the NDEF file may be written")
            block = apdu[5:]
            if len(block) != apdu[4] or len(block) > int.from_bytes(self.cc[5:7], "big"):
                raise AssertionError("Invalid UPDATE BINARY size")
            self.writes.append((offset, block))
            if offset == self.fail_at:
                return b"\x00\x65\x81"
            self.memory[offset:offset + len(block)] = b"\x00" * len(block) if self.corrupt else block
            return b"\x00\x90\x00"
        raise AssertionError("Unexpected APDU")


def make_reader(tag):
    return PN532Reader(i2c=object(), reader_factory=lambda i2c, debug: tag)


class Type4Tests(unittest.TestCase):
    def test_round_trip_all_music_types_and_publish_length_last(self):
        for kind in ("album", "playlist", "track"):
            with self.subTest(kind=kind):
                tag = Type4Tag()
                reader = make_reader(tag)
                value = f"spotify:{kind}:123abc"
                message = extract_ndef_message(encode_spotify_ndef(value))
                self.assertTrue(reader.write_tag(tag.uid.hex().upper(), value))
                self.assertEqual(tag.writes[0], (0, b"\x00\x00"))
                self.assertEqual(tag.writes[-1], (0, len(message).to_bytes(2, "big")))
                self.assertEqual(bytes(tag.memory[2:2 + len(message)]), message)
                self.assertEqual(reader.read_once().payload, value)
                self.assertTrue(all(offset + len(data) <= 256 for offset, data in tag.writes))

    def test_phone_written_link_is_read_without_a_uid_mapping(self):
        tag = Type4Tag()
        message = extract_ndef_message(encode_spotify_ndef(VALUE))
        tag.memory[:2] = len(message).to_bytes(2, "big")
        tag.memory[2:2 + len(message)] = message
        self.assertEqual(make_reader(tag).read_once().payload, VALUE)
        self.assertEqual(tag.writes, [])

    def test_unformatted_and_blank_tags_fall_back_to_uid(self):
        for denied in (False, True):
            tag = Type4Tag()
            tag.denied = denied
            with patch("app.db.get_tag_by_uid", return_value=None):
                self.assertEqual(make_reader(tag).read_once().payload, tag.uid.hex().upper())
            self.assertEqual(tag.writes, [])

    def test_rejects_unsafe_capabilities_without_writes(self):
        for offset, data, error in (
            (0, b"\x00\x0e", "unsupported_tag"),
            (0, b"\x01\x01", "unsupported_tag"),
            (2, b"\x30", "unsupported_tag"),
            (3, b"\x00\x00", "unsupported_tag"),
            (5, b"\x00\x00", "tag_locked"),
            (7, b"\x06", "unsupported_tag"),
            (8, b"\x05", "unsupported_tag"),
            (8, b"\xff", "unsupported_tag"),
            (9, b"\xe1\x03", "unsupported_tag"),
            (11, b"\xff\xff", "unsupported_tag"),
            (11, b"\x00\x10", "tag_too_small"),
            (13, b"\xff", "tag_locked"),
            (14, b"\xff", "tag_locked"),
            (14, b"\x80", "tag_locked"),
        ):
            with self.subTest(offset=offset, data=data):
                tag = Type4Tag()
                tag.cc[offset:offset + len(data)] = data
                with self.assertRaisesRegex(TagWriteError, error):
                    make_reader(tag).write_tag(tag.uid.hex().upper(), VALUE)
                self.assertEqual(tag.writes, [])

    def test_read_only_file_can_still_be_played(self):
        tag = Type4Tag()
        reader = make_reader(tag)
        reader.write_tag(tag.uid.hex().upper(), VALUE)
        tag.cc[14] = 0xFF
        self.assertEqual(reader.read_once().payload, VALUE)

    def test_failed_data_write_leaves_zero_length(self):
        tag = Type4Tag()
        tag.fail_at = 18
        with self.assertRaisesRegex(TagWriteError, "tag_write_failed"):
            make_reader(tag).write_tag(tag.uid.hex().upper(), VALUE)
        self.assertEqual(bytes(tag.memory[:2]), b"\x00\x00")
        self.assertEqual(tag.writes[-1][0], 18)

    def test_corruption_and_swapped_tag_cannot_report_success(self):
        for flag, error in (("corrupt", "tag_verify_failed"), ("swap", "tag_changed")):
            tag = Type4Tag()
            setattr(tag, flag, True)
            with self.subTest(flag=flag), self.assertRaisesRegex(TagWriteError, error):
                make_reader(tag).write_tag(tag.uid.hex().upper(), VALUE)

    def test_exact_capacity_and_rewriting_shorter_content(self):
        tag = Type4Tag()
        message = extract_ndef_message(encode_spotify_ndef(VALUE))
        tag.cc[11:13] = (len(message) + 2).to_bytes(2, "big")
        reader = make_reader(tag)
        reader.write_tag(tag.uid.hex().upper(), VALUE)
        reader.write_tag(tag.uid.hex().upper(), "spotify:track:a")
        self.assertEqual(reader.read_once().payload, "spotify:track:a")

    def test_bad_pn532_and_apdu_responses_are_explicit(self):
        for response, error in (
            (None, "tag_read_failed"), (b"", "tag_read_failed"),
            (b"\x01\x90\x00", "tag_read_failed"),
            (b"\x00\x69\x82", "tag_locked"),
            (b"\x00\x6a\x82", "tag_read_failed"),
        ):
            tag = Type4Tag()
            with patch.object(tag, "call_function", return_value=response):
                with self.subTest(response=response), self.assertRaisesRegex(Type4Error, error):
                    Type4Ndef(tag).exchange(b"\x00\xb0\x00\x00\x02")

    def test_invalid_length_and_short_read_are_rejected(self):
        tag = Type4Tag()
        protocol = Type4Ndef(tag)
        protocol.select()
        tag.memory[:2] = b"\xff\xff"
        with self.assertRaisesRegex(Type4Error, "tag_read_failed"):
            protocol.read_message()
        with patch.object(tag, "call_function", return_value=b"\x00\x90\x00"):
            with self.assertRaisesRegex(Type4Error, "tag_read_failed"):
                protocol.read(0, 2)

    def test_writer_consumes_type4_scan_without_playback(self):
        tag = Type4Tag()
        reader = make_reader(tag)
        writer = TagWriter()
        writer.start(VALUE)
        with patch("app.db.get_tag_by_uid", return_value=None):
            event = reader.read_once()
        self.assertTrue(writer.consume(reader, event))
        self.assertEqual(writer.snapshot()["status"], "success")
        self.assertTrue(writer.consume(reader, event))

    def test_transfer_limits_are_respected_for_small_and_large_advertised_sizes(self):
        for read_size, write_size in ((15, 2), (65535, 65535)):
            tag = Type4Tag()
            tag.cc[3:5] = read_size.to_bytes(2, "big")
            tag.cc[5:7] = write_size.to_bytes(2, "big")
            value = "spotify:album:" + "a" * 200
            with self.subTest(read_size=read_size):
                self.assertTrue(make_reader(tag).write_tag(tag.uid.hex().upper(), value))
                self.assertTrue(all(len(data) <= min(write_size, 240) for _, data in tag.writes))

    def test_other_capability_tlvs_are_skipped(self):
        tag = Type4Tag()
        tag.cc[7:7] = bytes.fromhex("0502abcd")
        tag.cc[:2] = len(tag.cc).to_bytes(2, "big")
        protocol = Type4Ndef(tag)
        protocol.select()
        self.assertEqual(protocol.capacity, 256)
        self.assertTrue(protocol.writable)

    def test_tag_swapped_during_detection_is_never_written(self):
        tag = Type4Tag()
        with patch.object(tag, "read_passive_target", side_effect=[tag.uid, b"\x01\x02"]):
            with self.assertRaisesRegex(TagWriteError, "tag_changed"):
                make_reader(tag).write_tag(tag.uid.hex().upper(), VALUE)
        self.assertEqual(tag.writes, [])

    def test_read_uid_swap_falls_back_instead_of_using_another_tags_message(self):
        tag = Type4Tag()
        with patch.object(tag, "read_passive_target", side_effect=[tag.uid, b"\x01\x02"]):
            with patch("app.db.get_tag_by_uid", return_value=None):
                with self.assertLogs("app.nfc_reader", level="WARNING"):
                    self.assertEqual(make_reader(tag).read_once().payload, tag.uid.hex().upper())
        self.assertEqual(tag.commands, [])
