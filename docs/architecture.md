# Architecture and signal path

[Documentation index](README.md)

TapTune separates physical input, stored assignments, playback dispatch, and the web interface so each part can be tested independently.

```text
NFC tag
  ↓ UID over I2C
PN532 reader
  ↓ lookup
SQLite tag mapping
  ↓ Spotify URI or action
playback dispatcher
  ↓
fake client or Spotify Connect
```

The web assignment page and command-line simulator join the same storage and dispatch path without requiring the physical reader.

## Main components

| Component | Responsibility |
| --- | --- |
| `app/main.py` | Starts the Flask UI and optionally the PN532 polling loop. |
| `app/config.py` | Reads and validates environment settings. |
| `app/web.py` | Provides the assignment UI, `/health`, `/assign`, and `/dispatch`. |
| `app/db.py` | Stores tag mappings and event records in SQLite. |
| `app/nfc_reader.py` | Reads PN532 UIDs and resolves saved mappings. |
| `app/spotify_service.py` | Validates values and dispatches Spotify content or playback actions. |
| `app/simulate.py` | Exercises mapping and dispatch without NFC hardware. |
| `app/ndef.py` | Decodes supported NDEF URI and text records when bytes are supplied. |

## Startup modes

`app.main` always starts the web UI and `/health`.

- With `NFC_READER_ENABLED=false` (the default), no hardware library or reader is required.
- With `NFC_READER_ENABLED=true`, the PN532 loop joins the service and dispatches saved mappings when a UID is presented.

Spotify uses a similar fallback:

- when all three Spotify credential values are present, TapTune creates a live Spotipy client;
- when any value is absent, it uses an in-process fake client.

These boundaries make it possible to test most of the system on a regular computer.

## Data and dispatch

The SQLite schema lives in `data/schema.sql`. Tag mappings associate a UID with:

- a validated Spotify URI;
- a playback action;
- a derived `content` or `action` type; and
- an optional human-readable label.

A dispatch can begin from:

- the PN532 reader resolving a physical UID;
- the `/dispatch` endpoint receiving a saved `uid`;
- the `/dispatch` endpoint receiving a direct `value`; or
- `app.simulate` saving and dispatching a test value.

All paths reach `dispatch_tag_value`, which validates and translates the stored value into a fake or live Spotify operation.

## Current boundaries

- The PN532 layer currently returns UID-based mappings only.
- `app/ndef.py` can decode supported tag memory supplied by another caller, but the hardware path does not yet read that memory.
- TapTune does not write NFC tags.
- A successful `/health` response does not prove that Spotify or the reader is healthy.
- Live playback needs a Spotify Connect device. With [Speaker setup](speaker-setup.md), raspotify makes the Pi that device. TapTune keeps playback on an already active device and otherwise targets the Pi by name (`SPOTIFY_DEVICE_NAME`).
- A chime plays once the Pi speaker is online after boot; other runtime problems are reported through logs; there are no status LEDs.

## Further reading

- [Getting started](getting-started.md)
- [Using tags](tag-usage.md)
- [Hardware setup](hardware-setup.md)
- [Raspberry Pi service](raspberry-pi-service.md)
