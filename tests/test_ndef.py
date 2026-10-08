import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ndef
from app.nfc_reader import PN532Reader, payload_for_tag


def uri_record(prefix_code: int, rest: bytes, message_begin=True, message_end=True) -> bytes:
    payload = bytes([prefix_code]) + rest
    header = 0x11  # short record, well known type
    if message_begin:
        header |= 0x80
    if message_end:
        header |= 0x40
    return bytes([header, 1, len(payload)]) + b"U" + payload


def wrap_in_tlv(message: bytes, pad_before: bytes = b"") -> bytes:
    return pad_before + bytes([0x03, len(message)]) + message + bytes([0xFE])


class ExtractMessageTests(unittest.TestCase):
    def test_finds_the_ndef_block_after_other_tlv_blocks(self):
        message = uri_record(0x04, b"open.spotify.com/track/abc")
        data = wrap_in_tlv(message, pad_before=bytes([0x00, 0x00, 0x01, 0x02, 0xAA, 0xBB]))

        self.assertEqual(ndef.extract_ndef_message(data), message)

    def test_reads_a_three_byte_length(self):
        message = b"\xd1" + bytes([1, 250]) + b"U" + bytes([0x04]) + b"a" * 249
        data = bytes([0x03, 0xFF, 0x00, len(message)]) + message + bytes([0xFE])

        self.assertEqual(ndef.extract_ndef_message(data), message)

    def test_rejects_a_blank_tag(self):
        with self.assertRaises(ndef.NdefError):
            ndef.extract_ndef_message(bytes([0x00, 0x00, 0xFE, 0x00]))

    def test_rejects_a_block_longer_than_the_data(self):
        with self.assertRaises(ndef.NdefError):
            ndef.extract_ndef_message(bytes([0x03, 0x40, 0x01, 0x02]))

    def test_rejects_a_truncated_length_byte(self):
        with self.assertRaises(ndef.NdefError):
            ndef.extract_ndef_message(bytes([0x03]))


class ParseRecordsTests(unittest.TestCase):
    def test_parses_a_short_uri_record(self):
        records = ndef.parse_records(uri_record(0x04, b"open.spotify.com/track/abc"))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].tnf, ndef.TNF_WELL_KNOWN)
        self.assertEqual(records[0].type, b"U")

    def test_parses_a_record_carrying_an_id(self):
        payload = bytes([0x04]) + b"open.spotify.com/track/abc"
        message = bytes([0xD9, 1, len(payload), 2]) + b"U" + b"id" + payload

        records = ndef.parse_records(message)

        self.assertEqual(ndef.record_value(records[0]), "https://open.spotify.com/track/abc")

    def test_parses_a_long_record(self):
        body = b"open.spotify.com/track/" + b"a" * 300
        payload = bytes([0x04]) + body
        message = bytes([0xC1, 1]) + len(payload).to_bytes(4, "big") + b"U" + payload

        records = ndef.parse_records(message)

        self.assertEqual(ndef.record_value(records[0]), "https://" + body.decode())

    def test_stops_at_the_end_of_the_message(self):
        message = uri_record(0x04, b"open.spotify.com/track/abc") + b"\xff\xff\xff"

        self.assertEqual(len(ndef.parse_records(message)), 1)

    def test_rejects_chunked_records(self):
        with self.assertRaises(ndef.NdefError):
            ndef.parse_records(bytes([0xB1, 1, 1]) + b"Ua")

    def test_rejects_a_record_longer_than_the_message(self):
        with self.assertRaises(ndef.NdefError):
            ndef.parse_records(bytes([0xD1, 1, 40]) + b"Uab")


class RecordValueTests(unittest.TestCase):
    def test_expands_an_abbreviated_uri_prefix(self):
        value = ndef.decode_uri_record(bytes([0x04]) + b"open.spotify.com/track/abc")

        self.assertEqual(value, "https://open.spotify.com/track/abc")

    def test_keeps_a_uri_that_stores_no_prefix(self):
        value = ndef.decode_uri_record(bytes([0x00]) + b"spotify:track:abc")

        self.assertEqual(value, "spotify:track:abc")

    def test_rejects_an_unknown_prefix_code(self):
        with self.assertRaises(ndef.NdefError):
            ndef.decode_uri_record(bytes([0x7F]) + b"whatever")

    def test_strips_the_language_code_from_a_text_record(self):
        payload = bytes([0x02]) + b"en" + b"spotify:playlist:abc"

        self.assertEqual(ndef.decode_text_record(payload), "spotify:playlist:abc")

    def test_reads_an_absolute_uri_record(self):
        record = ndef.NdefRecord(tnf=ndef.TNF_URI, type=b"", payload=b"spotify:album:abc")

        self.assertEqual(ndef.record_value(record), "spotify:album:abc")

    def test_ignores_a_record_type_it_cannot_use(self):
        record = ndef.NdefRecord(tnf=0x02, type=b"text/plain", payload=b"hello")

        self.assertIsNone(ndef.record_value(record))


class NormaliseSpotifyUriTests(unittest.TestCase):
    def test_converts_a_share_link(self):
        value = ndef.normalise_spotify_uri(
            "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc123"
        )

        self.assertEqual(value, "spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")

    def test_drops_a_locale_segment(self):
        value = ndef.normalise_spotify_uri("https://open.spotify.com/intl-fr/track/abc")

        self.assertEqual(value, "spotify:track:abc")

    def test_leaves_an_existing_spotify_uri_alone(self):
        self.assertEqual(
            ndef.normalise_spotify_uri("spotify:track:abc"), "spotify:track:abc"
        )

    def test_leaves_an_unrelated_link_alone(self):
        self.assertEqual(
            ndef.normalise_spotify_uri("https://example.com/track/abc"),
            "https://example.com/track/abc",
        )

    def test_leaves_an_unrecognised_spotify_path_alone(self):
        link = "https://open.spotify.com/user/someone"

        self.assertEqual(ndef.normalise_spotify_uri(link), link)


class TagValueTests(unittest.TestCase):
    def test_reads_a_spotify_link_written_by_a_phone(self):
        data = wrap_in_tlv(uri_record(0x04, b"open.spotify.com/playlist/abc?si=1"))

        self.assertEqual(ndef.tag_value_from_ndef(data), "spotify:playlist:abc")

    def test_skips_a_leading_record_it_cannot_use(self):
        text = bytes([0x02]) + b"en" + b""
        empty_text_record = bytes([0x91, 1, len(text)]) + b"T" + text
        link = uri_record(0x00, b"spotify:track:abc", message_begin=False)
        data = wrap_in_tlv(empty_text_record + link)

        self.assertEqual(ndef.tag_value_from_ndef(data), "spotify:track:abc")

    def test_returns_nothing_for_a_blank_tag(self):
        self.assertIsNone(ndef.tag_value_from_ndef(bytes([0x00, 0x00, 0xFE])))

    def test_returns_nothing_for_an_undecodable_record(self):
        data = wrap_in_tlv(uri_record(0x7F, b"whatever"))

        self.assertIsNone(ndef.tag_value_from_ndef(data))


class PayloadForTagTests(unittest.TestCase):
    def test_prefers_what_the_tag_describes_itself_as(self):
        data = wrap_in_tlv(uri_record(0x04, b"open.spotify.com/album/xyz"))

        payload = payload_for_tag(
            "AABBCCDD", data, lookup=lambda uid: {"value": "spotify:track:registered"}
        )

        self.assertEqual(payload, "spotify:album:xyz")

    def test_falls_back_to_the_registered_mapping(self):
        payload = payload_for_tag(
            "AABBCCDD", None, lookup=lambda uid: {"value": "spotify:track:registered"}
        )

        self.assertEqual(payload, "spotify:track:registered")

    def test_falls_back_to_the_mapping_when_the_tag_is_blank(self):
        payload = payload_for_tag(
            "AABBCCDD",
            bytes([0x00, 0x00, 0xFE]),
            lookup=lambda uid: {"value": "spotify:track:registered"},
        )

        self.assertEqual(payload, "spotify:track:registered")

    def test_falls_back_to_the_uid_when_nothing_is_known(self):
        self.assertEqual(payload_for_tag("AABBCCDD", None, lookup=lambda uid: None), "AABBCCDD")


class BlockEndTests(unittest.TestCase):
    def test_reports_the_end_once_the_header_is_visible(self):
        data = wrap_in_tlv(uri_record(0x04, b"open.spotify.com/track/abc"))

        self.assertEqual(ndef.ndef_block_end(data), 2 + len(data) - 3)

    def test_asks_for_more_while_the_length_is_cut_off(self):
        self.assertIsNone(ndef.ndef_block_end(bytes([0x03])))

    def test_skips_other_blocks(self):
        data = bytes([0x01, 0x02, 0xAA, 0xBB, 0x03, 0x04]) + b"1234"

        self.assertEqual(ndef.ndef_block_end(data), 10)

    def test_gives_up_at_the_terminator(self):
        with self.assertRaises(ndef.NdefError):
            ndef.ndef_block_end(bytes([0x00, 0xFE, 0x00, 0x00]))


class FakeNtag:
    """A PN532 holding one Type 2 tag, served 4 bytes per page."""

    def __init__(self, memory=None, uid=bytes([4, 1, 2, 3, 4, 5, 6]), capacity=144, fail_at=None):
        cc = bytes([0xE1, 0x10, capacity // 8, 0x00])
        self.pages = {3: cc}
        for number in range(36):
            chunk = (memory or b"")[number * 4:number * 4 + 4]
            self.pages[4 + number] = chunk.ljust(4, b"\x00")
        self.uid = uid
        self.fail_at = fail_at
        self.present = True
        self.reads = []

    def SAM_configuration(self):
        pass

    def read_passive_target(self, timeout):
        return self.uid if self.present else None

    def ntag2xx_read_block(self, page):
        self.reads.append(page)
        if page == self.fail_at:
            return None
        return self.pages.get(page)


def make_reader(tag):
    return PN532Reader(i2c=object(), reader_factory=lambda i2c, debug: tag)


class PN532NdefTests(unittest.TestCase):
    def test_reads_a_value_the_tag_describes_itself_with(self):
        memory = wrap_in_tlv(uri_record(0x04, b"open.spotify.com/playlist/abc?si=1"))
        event = make_reader(FakeNtag(memory)).read_once()

        self.assertEqual(event.uid, "04010203040506")
        self.assertEqual(event.payload, "spotify:playlist:abc")

    def test_stops_reading_pages_once_the_message_is_complete(self):
        tag = FakeNtag(wrap_in_tlv(uri_record(0x04, b"open.spotify.com/track/abc")))

        make_reader(tag).read_once()

        self.assertEqual(tag.reads[0], 3)
        self.assertLess(len(tag.reads), 12)

    def test_does_not_scan_the_whole_tag_when_it_is_blank(self):
        tag = FakeNtag(bytes([0x00, 0x00, 0xFE]))

        event = make_reader(tag).read_once()

        self.assertEqual(event.payload, event.uid)
        self.assertLess(len(tag.reads), 5)

    def test_falls_back_to_the_uid_when_a_page_read_fails(self):
        memory = wrap_in_tlv(uri_record(0x04, b"open.spotify.com/track/abc"))
        tag = FakeNtag(memory, fail_at=5)

        self.assertEqual(make_reader(tag).read_once().payload, "04010203040506")

    def test_falls_back_to_the_uid_for_a_tag_without_a_capability_container(self):
        tag = FakeNtag(wrap_in_tlv(uri_record(0x04, b"open.spotify.com/track/abc")))
        tag.pages[3] = bytes([0x00, 0x00, 0x00, 0x00])

        self.assertEqual(make_reader(tag).read_once().payload, "04010203040506")

    def test_falls_back_when_the_bus_raises(self):
        tag = FakeNtag(wrap_in_tlv(uri_record(0x04, b"open.spotify.com/track/abc")))

        def broken(page):
            raise RuntimeError("PN532 busy")

        tag.ntag2xx_read_block = broken

        self.assertEqual(make_reader(tag).read_once().payload, "04010203040506")

    def test_reads_the_memory_once_per_presentation(self):
        tag = FakeNtag(wrap_in_tlv(uri_record(0x04, b"open.spotify.com/track/abc")))
        reader = make_reader(tag)

        reader.read_once()
        reads_after_first = len(tag.reads)
        second = reader.read_once()

        self.assertEqual(len(tag.reads), reads_after_first)
        self.assertEqual(second.payload, "spotify:track:abc")

    def test_reads_again_after_the_tag_is_removed_and_returns(self):
        tag = FakeNtag(wrap_in_tlv(uri_record(0x04, b"open.spotify.com/track/abc")))
        reader = make_reader(tag)
        reader.read_once()
        tag.present = False
        self.assertIsNone(reader.read_once())
        tag.present = True
        reads_before = len(tag.reads)

        reader.read_once()

        self.assertGreater(len(tag.reads), reads_before)


if __name__ == "__main__":
    unittest.main()
