"""Decode NDEF messages so a tag can describe itself.

A tag written from a phone with NFC Tools stores an NDEF message in its user
memory rather than relying on TapTune knowing its UID. Reading that message
makes a tag portable: it carries its own Spotify URI and works on any TapTune
installation without being registered first.

This module is deliberately free of any hardware dependency. It takes the bytes
a reader hands back and turns them into a TapTune value, so it is testable
without a reader attached.
"""

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urlparse

TLV_NULL = 0x00
TLV_NDEF = 0x03
TLV_TERMINATOR = 0xFE

TNF_WELL_KNOWN = 0x01
TNF_URI = 0x03

RECORD_TYPE_URI = b"U"
RECORD_TYPE_TEXT = b"T"

# NFC Forum URI Record Type Definition, table 3: the first payload byte
# abbreviates a common prefix so it does not have to be stored on the tag.
URI_PREFIXES = (
    "",
    "http://www.",
    "https://www.",
    "http://",
    "https://",
    "tel:",
    "mailto:",
    "ftp://anonymous:anonymous@",
    "ftp://ftp.",
    "ftps://",
    "sftp://",
    "smb://",
    "nfs://",
    "ftp://",
    "dav://",
    "news:",
    "telnet://",
    "imap:",
    "rtsp://",
    "urn:",
    "pop:",
    "sip:",
    "sips:",
    "tftp:",
    "btspp://",
    "btl2cap://",
    "btgoep://",
    "tcpobex://",
    "irdaobex://",
    "file://",
    "urn:epc:id:",
    "urn:epc:tag:",
    "urn:epc:pat:",
    "urn:epc:raw:",
    "urn:epc:",
    "urn:nfc:",
)

SPOTIFY_HOSTS = ("open.spotify.com", "play.spotify.com")
SPOTIFY_KINDS = ("track", "playlist", "album", "artist", "show", "episode")


class NdefError(ValueError):
    """Raised when a byte sequence is not a message this module can decode."""


@dataclass
class NdefRecord:
    tnf: int
    type: bytes
    payload: bytes


def extract_ndef_message(data: bytes) -> bytes:
    """Pull the NDEF message out of the TLV blocks in a tag's user memory.

    Type 2 tags such as the NTAG21x family wrap their payload in tag-length-value
    blocks. Anything that is not the NDEF block is skipped, and the terminator
    ends the walk.
    """
    index = 0
    while index < len(data):
        tag = data[index]
        if tag == TLV_TERMINATOR:
            break
        if tag == TLV_NULL:
            index += 1
            continue
        if index + 1 >= len(data):
            raise NdefError("TLV block is truncated before its length byte")
        length = data[index + 1]
        value_start = index + 2
        if length == 0xFF:
            if index + 3 >= len(data):
                raise NdefError("Three byte TLV length is truncated")
            length = (data[index + 2] << 8) | data[index + 3]
            value_start = index + 4
        value_end = value_start + length
        if value_end > len(data):
            raise NdefError("TLV block claims more bytes than the tag returned")
        if tag == TLV_NDEF:
            return data[value_start:value_end]
        index = value_end
    raise NdefError("No NDEF block found on the tag")


def parse_records(message: bytes) -> List[NdefRecord]:
    """Split an NDEF message into its records.

    Chunked records are rejected rather than silently mis-decoded; nothing a
    phone writes to an NTAG21x uses them.
    """
    records: List[NdefRecord] = []
    index = 0
    while index < len(message):
        header = message[index]
        index += 1
        if header & 0x20:
            raise NdefError("Chunked records are not supported")
        short_record = bool(header & 0x10)
        has_id = bool(header & 0x08)
        tnf = header & 0x07

        if index >= len(message):
            raise NdefError("Record ends before its type length")
        type_length = message[index]
        index += 1

        if short_record:
            if index >= len(message):
                raise NdefError("Record ends before its payload length")
            payload_length = message[index]
            index += 1
        else:
            if index + 4 > len(message):
                raise NdefError("Record ends before its four byte payload length")
            payload_length = int.from_bytes(message[index:index + 4], "big")
            index += 4

        id_length = 0
        if has_id:
            if index >= len(message):
                raise NdefError("Record ends before its ID length")
            id_length = message[index]
            index += 1

        end = index + type_length + id_length + payload_length
        if end > len(message):
            raise NdefError("Record claims more bytes than the message holds")
        record_type = message[index:index + type_length]
        payload_start = index + type_length + id_length
        records.append(
            NdefRecord(
                tnf=tnf,
                type=record_type,
                payload=message[payload_start:payload_start + payload_length],
            )
        )
        index = end

        if header & 0x40:  # message end
            break
    return records


def decode_uri_record(payload: bytes) -> str:
    if not payload:
        raise NdefError("URI record has no payload")
    prefix_code = payload[0]
    if prefix_code >= len(URI_PREFIXES):
        raise NdefError(f"Unknown URI prefix code {prefix_code}")
    return URI_PREFIXES[prefix_code] + payload[1:].decode("utf-8", "replace")


def decode_text_record(payload: bytes) -> str:
    if not payload:
        raise NdefError("Text record has no payload")
    status = payload[0]
    language_length = status & 0x3F
    encoding = "utf-16" if status & 0x80 else "utf-8"
    return payload[1 + language_length:].decode(encoding, "replace").strip()


def record_value(record: NdefRecord) -> Optional[str]:
    """Return the usable string a record carries, or None if it holds none."""
    if record.tnf == TNF_WELL_KNOWN and record.type == RECORD_TYPE_URI:
        return decode_uri_record(record.payload)
    if record.tnf == TNF_URI:
        return record.payload.decode("utf-8", "replace")
    if record.tnf == TNF_WELL_KNOWN and record.type == RECORD_TYPE_TEXT:
        return decode_text_record(record.payload)
    return None


def normalise_spotify_uri(value: str) -> str:
    """Turn a Spotify share link into the `spotify:kind:id` form TapTune uses.

    Phones write what the Spotify app shares, which is an https link with
    tracking parameters attached. Anything that is not a Spotify link is
    returned unchanged.
    """
    value = value.strip()
    if value.startswith("spotify:"):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        return value
    if parsed.netloc.lower() not in SPOTIFY_HOSTS:
        return value
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0].startswith("intl-"):
        parts = parts[1:]
    if len(parts) < 2 or parts[0] not in SPOTIFY_KINDS:
        return value
    return f"spotify:{parts[0]}:{parts[1]}"


def tag_value_from_ndef(data: bytes) -> Optional[str]:
    """Return the TapTune value a tag describes itself with, if it holds one.

    Returns None rather than raising when the tag is blank or holds something
    this module cannot read, so a caller can fall back to a UID lookup.
    """
    try:
        records = parse_records(extract_ndef_message(data))
    except NdefError:
        return None
    for record in records:
        try:
            value = record_value(record)
        except NdefError:
            continue
        if value:
            return normalise_spotify_uri(value)
    return None
