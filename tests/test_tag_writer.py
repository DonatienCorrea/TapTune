import threading
import unittest
from unittest.mock import Mock, patch

from app import main, ndef
from app.nfc_reader import NFCEvent, PN532Reader, TagWriteError
from app.tag_writer import TagWriter, WriterBusy


class WritableTag:
    def __init__(self, size=144):
        self.uid = b"\x04\x01\x02\x03\x04\x05\x06"
        self.pages = {page: b"\x00" * 4 for page in range(2, 5 + size // 4)}
        self.pages[3] = bytes([0xE1, 0x10, min(size // 8, 255), 0])
        self.version = b"\x00\x00\x04\x04\x02\x01\x00" + bytes([{144: 0x0F, 504: 0x11, 888: 0x13}[size], 3])
        self.writes = []
        self.present = True
        self.fail_page = None
        self.corrupt = False
        self.swap_after_write = False

    def SAM_configuration(self):
        pass

    def call_function(self, command, params, response_length):
        if command != 0x40 or params != [1, 0x60] or response_length < 9:
            raise AssertionError("Unexpected version command")
        return self.version

    def read_passive_target(self, timeout):
        if not self.present:
            return None
        return b"\x04\xff" if self.swap_after_write and self.writes else self.uid

    def ntag2xx_read_block(self, page):
        return self.pages.get(page)

    def ntag2xx_write_block(self, page, data):
        if len(data) != 4:
            raise AssertionError("Writes must use four-byte pages")
        self.writes.append((page, bytes(data)))
        if page == self.fail_page:
            return False
        self.pages[page] = b"\x00" * 4 if self.corrupt else bytes(data)
        return True


def reader_for(tag):
    return PN532Reader(i2c=object(), reader_factory=lambda i2c, debug: tag)


class PhysicalTagWriteTests(unittest.TestCase):
    def test_all_supported_tags_and_music_types_round_trip(self):
        for size in (144, 504, 888):
            for kind in ("track", "album", "playlist"):
                with self.subTest(size=size, kind=kind):
                    tag = WritableTag(size)
                    reader = reader_for(tag)
                    value = f"spotify:{kind}:123abc"
                    self.assertTrue(reader.write_tag(tag.uid.hex().upper(), value))
                    memory = reader.read_ndef_memory()
                    self.assertEqual(ndef.tag_value_from_ndef(memory), value)
                    self.assertIn(f"open.spotify.com/{kind}/123abc".encode(), memory)
                    self.assertTrue(all(4 <= page < 4 + size // 4 for page, data in tag.writes))
                    self.assertEqual(tag.writes[0], (4, b"\x03\x00\xfe\x00"))
                    self.assertEqual(tag.writes[-1], (4, ndef.encode_spotify_ndef(value)[:4]))
                    self.assertEqual(reader.read_once().payload, value)

    def test_rewriting_a_longer_message_with_a_shorter_one(self):
        tag = WritableTag()
        reader = reader_for(tag)
        uid = tag.uid.hex().upper()
        reader.write_tag(uid, "spotify:playlist:" + "a" * 50)
        reader.write_tag(uid, "spotify:track:short")
        self.assertEqual(ndef.tag_value_from_ndef(reader.read_ndef_memory()), "spotify:track:short")

    def test_unsupported_locked_small_and_missing_tags_are_not_written(self):
        for scenario, code in (
            ("version", "unsupported_tag"), ("cc", "unsupported_tag"),
            ("cc_locked", "tag_locked"), ("static", "tag_locked"),
            ("dynamic", "tag_locked"), ("small", "tag_too_small"),
            ("missing", "tag_changed"), ("read_failed", "tag_read_failed"),
        ):
            with self.subTest(scenario=scenario):
                tag = WritableTag()
                if scenario == "version":
                    tag.version = b"\x01"
                elif scenario == "cc":
                    tag.pages[3] = b"\x00" * 4
                elif scenario == "cc_locked":
                    tag.pages[3] = b"\xe1\x10\x12\x0f"
                elif scenario == "static":
                    tag.pages[2] = b"\x00\x00\x01\x00"
                elif scenario == "dynamic":
                    tag.pages[40] = b"\x01\x00\x00\x00"
                elif scenario == "small":
                    tag.pages[3] = b"\xe1\x10\x01\x00"
                elif scenario == "missing":
                    tag.present = False
                else:
                    del tag.pages[2]
                with self.assertRaises(TagWriteError) as raised:
                    reader_for(tag).write_tag(tag.uid.hex().upper(), "spotify:album:abc")
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(tag.writes, [])

    def test_failed_page_keeps_ndef_unpublished(self):
        tag = WritableTag()
        tag.fail_page = 6
        reader = reader_for(tag)
        with self.assertRaisesRegex(TagWriteError, "tag_write_failed"):
            reader.write_tag(tag.uid.hex().upper(), "spotify:album:abc")
        self.assertEqual(tag.pages[4], b"\x03\x00\xfe\x00")
        self.assertIsNone(ndef.tag_value_from_ndef(reader.read_ndef_memory()))

    def test_verification_and_uid_changes_never_report_success(self):
        for scenario, error in (("corrupt", "tag_verify_failed"), ("swap_after_write", "tag_changed")):
            tag = WritableTag()
            setattr(tag, scenario, True)
            with self.subTest(scenario=scenario), self.assertRaisesRegex(TagWriteError, error):
                reader_for(tag).write_tag(tag.uid.hex().upper(), "spotify:album:abc")

    def test_encode_rejects_non_music_and_overlong_values(self):
        for value in ("action:next", "spotify:artist:abc", "spotify:album:a-b", "spotify:album:" + "a" * 300):
            with self.subTest(value=value), self.assertRaises(ndef.NdefError):
                ndef.encode_spotify_ndef(value)

    def test_exact_capacity_is_allowed_but_a_padded_page_past_capacity_is_not(self):
        value = "spotify:album:"
        while len(ndef.encode_spotify_ndef(value + "a")) < 144:
            value += "a"
        value += "a"
        self.assertEqual(len(ndef.encode_spotify_ndef(value)), 144)
        tag = WritableTag()
        self.assertTrue(reader_for(tag).write_tag(tag.uid.hex().upper(), value))
        self.assertEqual(max(page for page, block in tag.writes), 39)
        other = WritableTag()
        with self.assertRaisesRegex(TagWriteError, "tag_too_small"):
            reader_for(other).write_tag(other.uid.hex().upper(), value + "a")
        self.assertEqual(other.writes, [])


class TagWriterTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.writer = TagWriter(clock=lambda: self.now)
        self.reader = Mock()
        self.reader.write_tag.return_value = True
        self.event = NFCEvent("040102", "spotify:album:old")

    def test_write_is_exclusive_and_only_reader_thread_touches_hardware(self):
        job = self.writer.start("spotify:album:abc")
        with self.assertRaises(WriterBusy):
            self.writer.start("spotify:album:def")
        self.reader.write_tag.assert_not_called()
        self.assertTrue(self.writer.consume(self.reader, None))
        self.assertTrue(self.writer.consume(self.reader, self.event))
        self.reader.write_tag.assert_called_once_with("040102", "spotify:album:abc")
        self.assertEqual(self.writer.snapshot(job["id"])["status"], "success")
        self.assertTrue(self.writer.consume(self.reader, self.event))
        self.assertTrue(self.writer.consume(self.reader, None))
        self.assertFalse(self.writer.consume(self.reader, self.event))

    def test_pending_write_can_be_resumed_and_cancelled_without_writing(self):
        job = self.writer.start("spotify:album:abc")
        self.assertEqual(self.writer.snapshot(), job)
        self.assertIsNone(self.writer.cancel("wrong"))
        self.assertEqual(self.writer.cancel(job["id"])["status"], "cancelled")
        self.writer.consume(self.reader, self.event)
        self.reader.write_tag.assert_not_called()

    def test_timeout_is_reported_even_if_reader_thread_stalls(self):
        job = self.writer.start("spotify:album:abc")
        self.now = 60
        self.assertEqual(self.writer.snapshot(job["id"])["error"], "write_timeout")
        self.writer.consume(self.reader, self.event)
        self.reader.write_tag.assert_not_called()

    def test_hardware_errors_are_explicit(self):
        for error, code in ((TagWriteError("tag_locked"), "tag_locked"), (OSError("bus"), "tag_write_failed")):
            writer = TagWriter()
            writer.start("spotify:album:abc")
            self.reader.write_tag.side_effect = error
            with self.assertLogs("app.tag_writer", level="WARNING"):
                self.assertTrue(writer.consume(self.reader, self.event))
            self.assertEqual(writer.snapshot()["error"], code)
        self.writer.start("spotify:album:abc")
        self.writer.fail()
        self.assertEqual(self.writer.snapshot()["error"], "reader_unavailable")

    def test_reader_loop_never_dispatches_writing_scans_then_resumes_after_removal(self):
        stop = threading.Event()
        self.writer.start("spotify:album:abc")
        events = iter([self.event, self.event, None, self.event])

        def read():
            try:
                return next(events)
            except StopIteration:
                stop.set()
                return None

        self.reader.read_once.side_effect = read
        with patch.object(main, "dispatch_nfc_event") as dispatch:
            main.run_reader_loop(self.reader, stop_event=stop, idle_sleep_seconds=0, writer=self.writer)
        self.reader.write_tag.assert_called_once()
        dispatch.assert_called_once_with(self.event)

    def test_supervisor_fails_pending_job_when_reader_breaks(self):
        self.writer.start("spotify:album:abc")
        with patch.object(main._thread, "interrupt_main"), self.assertLogs(main.logger, level="ERROR"):
            main.run_reader_supervisor(Mock(side_effect=OSError("bus")), writer=self.writer, max_failures=1)
        self.assertEqual(self.writer.snapshot()["error"], "reader_unavailable")
