# TapTune

**Tap a physical object. Start the music.**

TapTune is an open-source Raspberry Pi project that turns NFC tags into simple Spotify controls. A tag can start a playlist, album, or track, pause playback, or skip to the next song—without opening a phone or navigating a screen.

[Site en français](https://donatiencorrea.github.io/TapTune/fr/) · [Public website](https://donatiencorrea.github.io/TapTune/) · [Documentation](docs/README.md)

> [!IMPORTANT]
> TapTune is currently a **do-it-yourself project**, not a finished product for sale. The long-term goal is to make tangible music controls accessible to people who cannot assemble and configure Raspberry Pi hardware themselves. Today, a maker still needs to prepare the Raspberry Pi, connect a PN532 NFC reader, and configure Spotify.

## Who TapTune is for

- **Listeners and families** who want a direct, screen-free way to start music.
- **Children, older adults, guests, or anyone** who finds a familiar physical object easier than an app.
- **Makers and developers** who want to build, adapt, or help simplify the system.

## What it does

```text
tap an NFC tag → read its UID → find its saved action → control Spotify
```

TapTune provides:

- a local web page for assigning NFC tags;
- Spotify playlist, album, and track playback;
- play/pause and next-track actions;
- SQLite storage for assignments and event records;
- a fake mode and simulator for testing without Spotify or NFC hardware;
- a PN532 reader path over Raspberry Pi I2C; and
- a `systemd` service installer for running TapTune continuously on a Pi.

## Choose your path

| I want to… | Start here |
| --- | --- |
| Understand the idea before touching hardware | [How TapTune works](docs/architecture.md) |
| Try TapTune on a computer without a reader or Spotify account | [Getting started in fake mode](docs/getting-started.md) |
| Connect and test the PN532 reader | [Hardware setup](docs/hardware-setup.md) |
| Assign tags and understand supported actions | [Using tags](docs/tag-usage.md) |
| Connect a Spotify account | [Spotify authorization](docs/spotify-authorization.md) |
| Install and operate TapTune on a Raspberry Pi | [Raspberry Pi service](docs/raspberry-pi-service.md) |
| Play music through a Bluetooth speaker | [Speaker setup](docs/speaker-setup.md) (Lite) or [PipeWire desktop setup](docs/speaker-setup-desktop.md) (Debian 13 Desktop) |
| Diagnose a problem | [Troubleshooting](docs/troubleshooting.md) |
| Browse every guide | [Documentation index](docs/README.md) |

## Quick start without hardware

Fake mode is the safest first run. It exercises the database, assignment page, dispatch code, and simulator without a Raspberry Pi, PN532, or Spotify credentials.

```bash
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m unittest discover -s tests -v
python -m app.main
```

Open `http://127.0.0.1:5000/`. The copied `.env` leaves the Spotify credentials empty, so TapTune automatically uses its in-memory fake client.

In a second terminal:

```bash
source .venv/bin/activate
python -m app.simulate \
  --uid 01AABBCC \
  --payload 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'
```

The result should include `"status": "ok"` and `"mode": "fake"`.

## Current boundaries

- The web UI always starts; PN532 polling starts only when `NFC_READER_ENABLED=true`.
- Self-describing tags: on NTAG21x (Type 2) tags the PN532 reader fetches the NDEF memory and plays the Spotify link or `spotify:` URI written on the tag, for example from a phone with NFC Tools. Share links such as `https://open.spotify.com/playlist/<id>?si=…` are converted automatically. A blank tag, a non-Type-2 tag (MIFARE Classic), or a failed read falls back to the value assigned to the UID in the web UI. The memory is read once each time a tag is presented. TapTune does not write tags.
- Live playback requires a Spotify Premium account and valid developer credentials. With the [Lite speaker setup](docs/speaker-setup.md), the Pi is its own Spotify speaker after boot. The [Desktop/PipeWire setup](docs/speaker-setup-desktop.md) makes it available after the desktop user logs in. If music is already playing on another device, taps control that device.
- On Lite, a short chime tells you when TapTune is ready after boot. Desktop/PipeWire setup disables the chime because TapTune's system service cannot play into the user's audio session. There is no status LED, and other runtime errors are inspected through logs.
- Hardware-specific Python packages are kept in `requirements-pi.txt` so local development remains hardware-free.

## Project map

| Path | Purpose |
| --- | --- |
| `app/web.py` | Flask routes for assignment, health, and dispatch |
| `app/nfc_reader.py` | PN532 polling and UID lookup |
| `app/spotify_service.py` | Spotify and fake playback dispatch, including the choice of playback device |
| `app/readiness.py` | Ready chime once the Pi's Spotify speaker is online |
| `app/db.py` | SQLite assignments and event records |
| `app/simulate.py` | Hardware-free command-line simulation |
| `data/schema.sql` | Database schema |
| `systemd/` | Raspberry Pi dependency, service, and speaker installers |
| `docs/` | Public landing page and task-focused guides |
| `tests/` | Hardware-free unit and integration coverage |

## Development checks

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

The test suite uses a temporary database and fake Spotify client. It does not require `.env`, Spotify credentials, a PN532, I2C, or a running server.

## GitHub Pages

The bilingual static website lives in `docs/`. In repository settings, configure GitHub Pages to deploy from the `master` branch and `/docs` directory.
