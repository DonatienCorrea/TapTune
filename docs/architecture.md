# How TapTune works (for developers)

[Documentation index](README.md)

```text
NFC tag → PN532 reader (I2C) → Spotify link on the tag, or saved tag ID (SQLite)
        → go-librespot local API (127.0.0.1:3678) → PipeWire → Bluetooth speaker
```

TapTune is one Python (Flask) service, `raspi-spotify-nfc.service`. The Spotify
receiver, go-librespot, runs as a separate user service,
`taptune-go-librespot.service`, because it has its own sign-in and audio session.

## Main parts

| File | Role |
| --- | --- |
| `app/main.py` | Starts the web app and the reader loop (it waits for the PN532 if absent) |
| `app/web.py` | Music page, setup page, Activity log (`/logs`) with maintenance, APIs, `/health`, `/ready` |
| `app/nfc_reader.py`, `app/type4_ndef.py`, `app/ndef.py` | Read tag IDs and links; write and verify tags |
| `app/tag_writer.py` | One 60-second, cancellable write at a time |
| `app/spotify_service.py`, `app/librespot.py` | Play tags and actions through go-librespot |
| `app/spotify_browser.py` | Saved albums/playlists, What's playing, history, link previews |
| `app/readiness.py`, `app/bluetooth.py` | Startup volume, speaker connection and chime |
| `app/setup.py`, `app/speaker_pairing.py` | Setup page status and speaker pairing |
| `app/wifi_setup.py`, `app/wifi_portal.py` | `TapTune-Setup` hotspot and Wi-Fi form |
| `app/activity.py`, `app/db.py`, `data/schema.sql` | Activity log and tag database |
| `install.sh`, `taptune`, `systemd/` | Installer, maintenance command, services |

## Key behaviours

- A Spotify link written on the tag wins over a saved tag ID. Blank, unsupported
  or unreadable tags fall back to the saved tag ID.
- A podcast show tag looks up the newest playable episode at each tap.
- Spotify link previews (title, cover) use Spotify's public oEmbed service; no
  account is needed. Saved albums and playlists come from go-librespot.
- Writing: the reader thread is the only code touching NFC hardware. While a
  write waits, taps don't play. The NDEF length is cleared first, written last,
  and the whole tag is read back before reporting success. TapTune never formats
  or unlocks tags, and only writes user memory (Type 2 pages, or the Type 4 NDEF
  file). The Feiju profile is matched exactly (version `00 00 53 04 02 01 00 0F 03`,
  capability container `E1 10 12 00`) and only pages 5–39 are written.
- Startup: one bounded check (reader, receiver, speaker), then one chime at 10%.
  Temporary failures (receiver not ready, network errors) are retried. No
  background Bluetooth reconnect: only music taps reconnect the speaker.
- The Activity log keeps the last 2,000 entries in SQLite, with Spotify secrets redacted.
- The web pages have no authentication: trusted home network only. Wi-Fi
  passwords are accepted only from the `TapTune-Setup` hotspot.

## Development

```bash
python3 -m unittest discover -s tests -q
node --test tests/test_music_ui.js
```

Tests need no Pi, reader or Spotify account.
