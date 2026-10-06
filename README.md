# TapTune

TapTune is a Raspberry Pi + PN532 NFC reader project for assigning physical tags to Spotify content and simple playback actions. The repository currently provides:

- a Flask tag-assignment UI;
- SQLite storage for tag mappings and event records;
- Spotify live mode (with a refresh token) and a safe in-process fake mode;
- a command-line simulator for testing the dispatch path without hardware; and
- a `systemd` unit for running the web service on a Pi.

> **Current boundary:** `app.main` always starts the web UI and `/health`. It starts the PN532 polling loop only when `NFC_READER_ENABLED=true`; the default is `false` so local development and first-time setup do not require hardware. The current PN532 path reads UIDs and dispatches their saved mappings. TapTune can decode supported self-describing NDEF values when a reader supplies tag memory, but the PN532 reader does not yet supply NDEF data and TapTune does not write tags. Use the simulator or `/dispatch` before enabling the reader, then enable it for normal tap-to-play use.

## Signal path

```text
tag UID → assignment in the web UI → SQLite mapping → dispatch endpoint/simulator → fake or Spotify client
```

The app listens on `APP_HOST:APP_PORT` (defaults to `0.0.0.0:5000`). The UI is at `/`, the health check is `/health`, and `/dispatch` accepts either a saved `uid` or a direct `value`.

## Prerequisites

### macOS or local development

- macOS with Python 3.10+ and `python3`;
- network access to install the packages in `requirements.txt`; and
- a Spotify Premium account only if you want live playback. Fake mode needs no Spotify account or credentials.

### Raspberry Pi

- Raspberry Pi OS Lite (or another Raspberry Pi OS installation) with SSH access;
- a Raspberry Pi with a PN532 configured for I2C;
- Python 3.10+;
- a Spotify Premium account and a Spotify Developer app for live playback; and
- an NFC tag. Read its UID with the PN532 first-card test below; this repository does not write payloads to tags.

Install the hardware-specific dependencies from `requirements-pi.txt` in addition to the base requirements. The PN532 uses the Raspberry Pi's I2C bus rather than SPI.

## Quick start: local fake mode

Fake mode is the recommended first run. It exercises the database, UI, dispatch code, and simulator without hardware or Spotify credentials.

```bash
git clone <repository-url> TapTune
cd TapTune
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m unittest discover -s tests -v
python -m app.main
```

Open `http://127.0.0.1:5000/` in a browser. The copied `.env` deliberately leaves the Spotify variables empty, so the app uses its in-memory fake Spotify client. Stop the server with `Ctrl-C`.

## Spotify setup

Live mode is enabled only when `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REFRESH_TOKEN` are all non-empty. If any one is blank, TapTune uses its in-memory fake client and does not contact Spotify.

1. Sign in to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Create or select an app and copy its client ID and client secret.
3. Add the exact value of `SPOTIFY_REDIRECT_URI` to the app's Redirect URIs. The example uses `http://127.0.0.1:8888/callback`; a URI mismatch prevents OAuth.
4. Follow the [Spotify authorization guide](docs/spotify-authorization.md) to obtain a refresh token with the scopes `user-modify-playback-state user-read-playback-state`.
5. Put the three values in `.env` on the machine running TapTune. Do not commit `.env` or paste the secret into logs.

Spotify playback also requires an available Spotify Connect device. A valid token alone does not guarantee that `start_playback` succeeds.

## Testing

### Automated test suite

Run the suite from the repository root after activating the virtual environment:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

The suite uses a temporary SQLite database and the fake Spotify client. It does not require `.env`, Spotify credentials, a PN532, I2C, or a running server. It covers configuration validation, tag assignment, dispatch, simulator validation, and reader UID lookup behavior.

### Manual fake-mode dispatch check

With `python -m app.main` running in one terminal, use a second terminal to check the HTTP service and dispatch paths:

```bash
curl http://127.0.0.1:5000/health
python -m app.simulate --uid 01AABBCC --payload 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'
python -m app.simulate --uid 02AABBCC --payload 'action:play_pause'
python -m app.simulate --uid 03AABBCC --payload 'action:next'
```

The simulator upserts each mapping, records an event, dispatches it, and prints a result containing `"mode": "fake"`. The default database is `data/raspi_spotify_nfc.db`; it is ignored by Git.

> The simulator runs as its own command and does not send a request to the Flask server. The health request verifies the server; the simulator verifies the mapping and dispatch path. Both should succeed before configuring live Spotify or installing the service.

## PN532 wiring and I2C setup

PN532 breakout boards expose different labels and use different switches or
solder jumpers to select a host interface. Before applying power, set the board
to **I2C mode** according to its own silkscreen or manufacturer documentation.
Do not copy an SPI or UART switch position from a different PN532 board.

Use the Raspberry Pi's primary I2C bus:

| PN532 pin | Raspberry Pi physical pin | BCM | Notes |
| --- | --- | --- | --- |
| VCC / 3.3V | 1 | - | Use 3.3 V unless the breakout's documentation explicitly requires another supply. |
| GND | 6 | - | Common ground. |
| SDA | 3 | GPIO 2 / SDA1 | I2C data. |
| SCL | 5 | GPIO 3 / SCL1 | I2C clock. |
| IRQ | - | - | Leave disconnected for the polling setup. |
| RST / RSTO | - | - | Leave disconnected unless the selected PN532 library or breakout instructions require it. |

The Pi's GPIO lines are 3.3 V only. A breakout may accept 5 V on its power
input, but that does not make 5 V safe on SDA or SCL. Power down the Pi before
changing the board mode or wiring.

Enable I2C and install the bus utilities:

```bash
sudo raspi-config nonint do_i2c 0
sudo apt install -y i2c-tools
sudo reboot
```

After reboot, verify the controller and scan the bus:

```bash
ls -l /dev/i2c-1
sudo i2cdetect -y 1
```

A PN532 in I2C mode normally uses the 7-bit address `0x24`, so the scan should
show `24`. Some PN532 firmware/library combinations do not respond reliably to
the generic probing used by `i2cdetect`; if `/dev/i2c-1` exists but `24` is
absent, recheck the board's interface selection, SDA/SCL orientation, power,
and ground, then use the first-card test as the definitive application check.

## First-card test

Run this once before starting normal application setup. It proves that the Pi,
I2C bus, PN532, and one physical card can work together without involving
Spotify or the web service.

1. Stop the TapTune service if it is already running so only one process owns
   the reader:

   ```bash
   sudo systemctl stop raspi-spotify-nfc.service
   ```

2. Activate the project environment and make sure the hardware-specific
   dependencies from `requirements-pi.txt` are installed; the diagnostic fails
   immediately with `PN532 support is not available; install
   requirements-pi.txt on the Pi.` if they are missing:

   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements-pi.txt
   ```

3. Run the bounded PN532 diagnostic:

   ```bash
   python -m app.pn532_diag --seconds 30
   ```

4. When `PN532 initialized over I2C` appears, hold one card flat and close to
   the antenna until the command prints a UID such as `uid=04A7B2F1`, then
   remove the card. UID length varies by card type; copy the complete value
   exactly as printed.
5. If initialization fails with the `requirements-pi.txt` message above, confirm
   step 2 installed the hardware dependencies into the active environment. If
   it instead fails after that, recheck I2C mode, power, SDA, and SCL. If the
   command initializes but times out, move the card directly over the antenna
   and retry with a known ISO/IEC 14443 Type A card. The unbounded
   `python -m app.nfc_reader --read` command is also available when you want to
   wait indefinitely for one card.

Do not continue to assignment until this command reads the card consistently.

## First tag assignment

After the first-card test passes, use the normal application flow:

1. Start TapTune and open `http://127.0.0.1:5000/` locally, or `http://<pi-ip>:5000/` from another device on the same network.
2. Enter the complete UID from the first-card test exactly as printed, for example `04A7B2F1`.
3. Enter one supported value:
   - `spotify:track:<id>`
   - `spotify:playlist:<id>`
   - `spotify:album:<id>`
   - `action:play_pause`
   - `action:next`
4. Optionally add a friendly label and select **Save tag**.
5. Verify the row appears under **Assigned tags**.
6. Verify the saved mapping explicitly before enabling hardware polling:

```bash
curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
```

7. Stop TapTune, set `NFC_READER_ENABLED=true` in `.env`, and restart it. A
   physical tap now dispatches the saved mapping. Keep the card away from the
   antenna until startup is complete, and remove it between taps; the loop
   dispatches once per presentation rather than repeatedly while a card is held
   in place.

`action:next` and `action:next_track` are equivalent; the UI quick-fill control uses the latter.

### Self-describing tags

TapTune's NDEF decoder supports tags that carry their own value instead of
being registered by UID. You can prepare one with NFC Tools, or any phone app
that writes an NDEF URI or text record. This is a supported data format, but
the current PN532 hardware reader returns only the UID, so self-describing tags
still need future reader-memory integration before they work directly from a
physical tap.

Either form works:

- the Spotify share link, for example `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=…`, which is normalised to `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M` with the tracking parameters and any locale segment dropped
- the URI directly, for example `spotify:track:<id>`, written as a URI or a text record

When NDEF bytes are supplied to the decoder, a supported NDEF value wins. A
blank tag, or one holding something TapTune cannot use, falls back to the
registered UID mapping and then to the raw UID.

Decoding lives in `app/ndef.py` and has no hardware dependency, so it is tested
without a reader attached. Reading NDEF from hardware still depends on the
PN532 reader layer supplying tag memory; the current reader returns UID-based
mappings only.

## Raspberry Pi installation

From an SSH session on the Pi:

```bash
sudo apt update
sudo apt install -y git python3-venv sqlite3
cd /home/pi
git clone <repository-url> TapTune
cd TapTune
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
./systemd/install-pi-dependencies.sh
cp .env.example .env
chmod 600 .env
```

The dependency script installs the Pi-only reader packages in addition to the
base application dependencies. It is safe to rerun in an existing virtual
environment when upgrading.

Edit `.env` with `nano .env`. Keep `DATABASE_PATH=./data/raspi_spotify_nfc.db`
unless you deliberately want another location, and leave
`NFC_READER_ENABLED=false` during setup. Enable I2C with `sudo raspi-config` →
**Interface Options** → **I2C**, reboot, and connect the PN532 using the wiring
table above. Complete the first-card test and explicit `/dispatch` check, then
set `NFC_READER_ENABLED=true` for normal service operation.

Before installing the service, prove the software works on the Pi in fake mode:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m app.main
```

From another machine, replace `<pi-ip>`:

```bash
curl http://<pi-ip>:5000/health
```

## Install and operate the service

The checked-in unit file has `/home/pi/TapTune` as a placeholder path. If your checkout lives anywhere else (a different username or directory), installing it as-is makes `systemctl enable --now` fail with a generic "unavailable resources or another system error", because `ExecStart`/`WorkingDirectory`/`EnvironmentFile` point at a path that doesn't exist. `systemd/install-service.sh` rewrites those three paths to match your actual checkout before installing. Run it from the repository root after `.venv` and `.env` exist:

```bash
sudo ./systemd/install-service.sh
```

To preview the generated unit without installing or requiring root, add `--dry-run`:

```bash
./systemd/install-service.sh --dry-run
```

Check status and the local endpoint:

```bash
sudo systemctl status raspi-spotify-nfc.service --no-pager
curl http://127.0.0.1:5000/health
```

Useful operations:

```bash
sudo systemctl restart raspi-spotify-nfc.service
sudo systemctl stop raspi-spotify-nfc.service
sudo systemctl disable raspi-spotify-nfc.service
```

The service is configured to restart after failures. With
`NFC_READER_ENABLED=false` it serves only the web UI; with the setting changed
to `true`, it also polls the PN532 and dispatches assigned tags.

## Health checks and logs

`/health` is a lightweight process check and returns JSON such as `{"app":"TapTune","status":"ok"}`. It does not validate Spotify credentials, Connect-device availability, PN532/I2C wiring, reader-thread health, or database contents.

For service diagnostics:

```bash
sudo journalctl -u raspi-spotify-nfc.service -n 100 --no-pager
sudo journalctl -u raspi-spotify-nfc.service -f
ss -ltn | grep ':5000'
```

For a safe database inspection:

```bash
sqlite3 data/raspi_spotify_nfc.db \
  'select uid, tag_type, value, label, updated_at from tags order by updated_at desc;'
```

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `curl` cannot connect | Confirm `systemctl status`, port `5000`, `APP_HOST`, and the Pi IP. |
| `systemctl enable --now` fails with "unavailable resources or another system error" | The unit paths don't match your checkout. Reinstall with `sudo ./systemd/install-service.sh`, which rewrites `WorkingDirectory`/`ExecStart`/`EnvironmentFile` to your actual path. |
| Service exits immediately | Confirm `.env` exists in the checkout, the unit paths match it, and `journalctl` shows the Python error. |
| Fake mode is unexpected | All three live Spotify variables must be non-empty; remove stale placeholder values and restart the service. |
| Spotify returns an auth error | Recheck client ID/secret, refresh-token scopes, and an exact redirect URI match. |
| Spotify returns no active device/playback error | Open Spotify on a Connect-capable device and confirm the account can control playback. |
| Tag is “unknown” | Assign the exact UID shown by the reader; UID case and extra spaces matter to the current lookup. |
| PN532 import fails | Activate the Pi virtual environment and rerun `./systemd/install-pi-dependencies.sh`. |
| `/dev/i2c-1` is missing | Enable I2C with `sudo raspi-config` and reboot. |
| `i2cdetect -y 1` does not show `24` | Power down, confirm the PN532 is set to I2C, and recheck 3.3 V, ground, SDA on pin 3, and SCL on pin 5. Then retry the first-card test because generic probing is not definitive for every board. |
| Reader command waits forever | Stop the service and any other reader process, place a known Type A card directly over the antenna, and run `python -m app.pn532_diag --seconds 30`. |
| UID changes or is incomplete | Copy the entire UID printed for one card. Do not assume every card has a four-byte UID. |
| Diagnostic reads a card but service taps do nothing | Set `NFC_READER_ENABLED=true` in the service's `.env`, restart the service, and inspect `journalctl` for PN532 initialization or unassigned-tag warnings. |
| The same held card plays repeatedly | Update to the current reader loop. It dispatches once, then requires the card to be removed before another tap. |
| A tag cannot be written | Expected: TapTune does not write tags itself. Write the value from a phone with NFC Tools instead; see "Self-describing tags". |

## Safe updates

Back up the SQLite database and `.env` before updating. Keep secrets outside Git:

```bash
cd /home/pi/TapTune
cp data/raspi_spotify_nfc.db "data/raspi_spotify_nfc.db.$(date +%Y%m%d%H%M%S).bak"
cp .env ".env.$(date +%Y%m%d%H%M%S).bak"
sudo systemctl stop raspi-spotify-nfc.service
git fetch --prune
git pull --ff-only
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-pi.txt
python -m unittest discover -s tests -v
sudo ./systemd/install-service.sh
sudo systemctl start raspi-spotify-nfc.service
sudo systemctl status raspi-spotify-nfc.service --no-pager
curl http://127.0.0.1:5000/health
```

If `git pull --ff-only` reports local changes, stop and resolve them rather than overwriting `.env` or the database. Restore the database only with the service stopped.

## GitHub Pages

The static landing page is in `docs/`. To enable it on GitHub, open **Settings → Pages**, choose **Deploy from a branch**, select `master` and `/docs`, then save.
