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
- play/pause, next-track and volume ±10-point actions;
- a 30% startup volume for the Pi receiver;
- SQLite storage for assignments and event records;
- a fake mode and simulator for testing without Spotify or NFC hardware;
- a PN532 reader path over Raspberry Pi I2C;
- one guided installer for preparing Python and configuring the selected Pi audio stack; and
- a `taptune` command to update everything, restart, check status and read all logs in one place.

## Quick install on Raspberry Pi

**Use Raspberry Pi OS Lite for the shortest supported standalone-player route.**
Desktop/PipeWire is supported, but requires a compatible Spotifyd binary and its
own account authentication. Never combine the two audio stacks.

```bash
sudo apt update
sudo apt install -y git python3-venv
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
./install.sh --lite
```

This prepares `.venv`, Python dependencies and a private `.env`; **it does not
start services or music**. Follow the [installation checklist](docs/raspberry-pi-service.md)
for wiring, a first-card check, Bluetooth pairing and Spotify authorization,
then run `./install.sh --lite --configure`. The checklist tells you exactly
when to log the receiver into Spotify; there is no second manual service install.

For Desktop, use `--desktop` in both commands. `./install.sh --help` explains
all modes; add `--dry-run` to preview without changes. Run as your normal user,
not with `sudo` (on Desktop, the Spotifyd audio user).

## Documentation

| I want to… | Start here |
| --- | --- |
| Understand the idea before touching hardware | [How TapTune works](docs/architecture.md) |
| Try TapTune on a computer without a reader or Spotify account | [Getting started in fake mode](docs/getting-started.md) |
| Connect and test the PN532 reader | [Hardware setup](docs/hardware-setup.md) |
| Assign tags and understand supported actions | [Using tags](docs/tag-usage.md) |
| Connect a Spotify account | [Spotify authorization](docs/spotify-authorization.md) |
| Build the physical player, start to finish | [Installation checklist](docs/raspberry-pi-service.md) |
| Play music through a Bluetooth speaker | [Speaker setup](docs/speaker-setup.md) (Lite) or [PipeWire desktop setup](docs/speaker-setup-desktop.md) (Debian 13 Desktop) |
| Diagnose a problem | [Troubleshooting](docs/troubleshooting.md) |
| Browse every guide | [Documentation index](docs/README.md) |

## Quick start without hardware

Fake mode is the safest first run. It exercises the database, assignment page, dispatch code, and simulator without a Raspberry Pi, PN532, or Spotify credentials.

```bash
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
./install.sh --app-only
.venv/bin/python -m app.main
```

Requires Python 3.10+ and venv support. Open `http://127.0.0.1:5000/`. A newly
created `.env` leaves Spotify credentials empty, so TapTune uses its fake client.
The installer never overwrites an existing `.env`; use the
[fake-mode guide](docs/getting-started.md) for an explicit isolated fake run.

In a second terminal:

```bash
source .venv/bin/activate
python -m app.simulate \
  --uid 01AABBCC \
  --payload 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'
```

The printed Python dictionary contains `result` with `'status': 'ok'` and
`'mode': 'fake'` (the simulator does not print JSON).

## Current boundaries

- The web UI always starts; PN532 polling starts only when `NFC_READER_ENABLED=true`.
- Self-describing tags: on NTAG21x (Type 2) tags the PN532 reader fetches the NDEF memory and plays the Spotify link or `spotify:` URI written on the tag, for example from a phone with NFC Tools. Share links such as `https://open.spotify.com/playlist/<id>?si=…` are converted automatically. A blank tag, a non-Type-2 tag (MIFARE Classic), or a failed read falls back to the value assigned to the UID in the web UI. The memory is read once each time a tag is presented. TapTune does not write tags.
- Live playback requires a Spotify Premium account and valid developer credentials. Both the [Lite speaker setup](docs/speaker-setup.md) and the [Desktop/PipeWire setup](docs/speaker-setup-desktop.md) support playback after boot without logging in. Desktop requires the included user-audio installer and a dedicated audio user. If Spotify reports a current device, even while paused, taps control that device.
- Boot prepares the receiver; it does **not** automatically start a playlist or resume music. Playback starts with a content tag or play/pause tag. Both TapTune's Web API authorization and the receiver's separate Spotify login must use the same account.
- TapTune runs one bounded boot connection/readiness phase and plays at most one chime per app start, after the app, enabled reader, local Spotify receiver and speaker audio pass their checks. Desktop routes sound through the dedicated audio user's PipeWire session. After that there is no periodic reconnect, keepalive sound or repeated chime. Only a **local music start/resume** tap can reconnect; pause and volume taps never do. An off speaker still needs to be powered on. There is no status LED; inspect `taptune status` and `taptune logs`.
- Hardware-specific Python packages are kept in `requirements-pi.txt` so local development remains hardware-free.

## Project map

| Path | Purpose |
| --- | --- |
| `app/web.py` | Flask routes for assignment, health, and dispatch |
| `app/nfc_reader.py` | PN532 polling and UID lookup |
| `app/spotify_service.py` | Spotify and fake playback dispatch, including the choice of playback device |
| `app/readiness.py` | Ready chime after app, reader, Spotify receiver and speaker-audio checks |
| `app/db.py` | SQLite assignments and event records |
| `app/simulate.py` | Hardware-free command-line simulation |
| `data/schema.sql` | Database schema |
| `taptune` | Update, restart, status and merged logs for every service |
| `install.sh` | Guided preparation and explicit live-service configuration |
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
