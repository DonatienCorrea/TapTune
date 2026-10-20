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
| `app/web.py` | Provides the assignment UI, `/health`, `/ready`, `/assign`, and `/dispatch`. |
| `app/db.py` | Stores tag mappings and event records in SQLite. |
| `app/nfc_reader.py` | Reads PN532 UIDs and Type 2 NDEF memory, falling back to saved mappings. |
| `app/spotify_service.py` | Validates values and dispatches Spotify content or playback actions. |
| `app/simulate.py` | Exercises mapping and dispatch without NFC hardware. |
| `app/ndef.py` | Decodes supported NDEF URI and text records when bytes are supplied. |
| `app/readiness.py` | Bounded startup checks, connection and one ready chime in the app process. |
| `install.sh` | Safe preparation, then explicit selected-stack service configuration. |

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

- The PN532 reads NDEF on Type 2 tags (such as NTAG21x). Supported embedded Spotify values or actions take precedence over UID mappings; blank, unsupported or unreadable memory falls back to the saved UID mapping.
- TapTune does not write NFC tags.
- A successful `/health` response does not prove that Spotify or the reader is healthy.
- Live playback needs a Spotify Connect device. Use [Raspotify/BlueALSA on Lite](speaker-setup.md) or [Spotifyd/PipeWire on Desktop](speaker-setup-desktop.md), not both. TapTune keeps playback on Spotify's current device, even while paused, and otherwise targets the Pi by name (`SPOTIFY_DEVICE_NAME`).
- Boot initializes the local receiver's volume but does not start music. A chime waits for TapTune's `/ready` check (live config and enabled reader thread), Spotify visibility and speaker audio. Lite uses ALSA; Desktop uses the dedicated audio user's PipeWire sink from the same app process. Other runtime problems are logged; there are no status LEDs.
- One bounded boot connection/chime phase is followed by no periodic Bluetooth reconnect or keepalive. Only local music start/resume dispatch may reconnect; pause, volume and commands targeting another active Spotify device do not.

## Why not one service?

The Bluetooth reconnect and Desktop ready-sound services have been **merged
into TapTune's app startup/dispatch path**. There is no background reconnect
loop or separately restarting chime worker. Reconfiguration removes those
obsolete units on an older installation.

The remaining boundaries are intentional:

| Route | TapTune-managed processes | OS audio dependencies |
| --- | --- | --- |
| Lite | System `raspi-spotify-nfc.service` and packaged `raspotify.service` | BlueZ, BlueALSA and ALSA |
| Desktop | System `raspi-spotify-nfc.service` and audio-user `taptune-spotifyd.service` | BlueZ, lingering user PipeWire/PipeWire-Pulse and WirePlumber |
| App-only | `raspi-spotify-nfc.service` only | Another authenticated Connect player; no installed local audio stack |

The Spotify Connect receiver is a separate upstream program with its own
authentication and lifecycle. Desktop audio lives behind a **user-session**
boundary; lingering and WirePlumber configuration allow it to exist before
login. TapTune's Desktop unit records that user for audio operations rather
than starting a second system-wide audio server. BlueZ and the audio server
are OS facilities, not duplicate TapTune workers. Folding all of these into
one Python process would not remove their account/privilege requirements.

The installer selects one receiver stack and disables known conflicting
services; it does not remove packages or reconcile arbitrary other users'
audio sessions. Never start Raspotify and Spotifyd together.

## Further reading

- [Getting started](getting-started.md)
- [Using tags](tag-usage.md)
- [Hardware setup](hardware-setup.md)
- [Raspberry Pi service](raspberry-pi-service.md)
