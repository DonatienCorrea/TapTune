# TapTune

TapTune is a Raspberry Pi + RC522 NFC reader project for assigning physical tags to Spotify content and simple playback actions. The repository currently provides:

- a Flask tag-assignment UI;
- SQLite storage for tag mappings and event records;
- Spotify live mode (with a refresh token) and a safe in-process fake mode;
- a command-line simulator for testing the dispatch path without hardware; and
- a `systemd` unit for running the web service on a Pi.

> **Current boundary:** `app.main` starts the web UI and `/health`; it does not yet start an NFC polling loop. `app.nfc_reader.RC522Reader` can read a UID when the Pi dependency is installed, but physical scans are not connected to dispatch in this scaffold. NFC tag writing is also not implemented. Use the simulator to verify playback dispatch today, and use the UI to assign the UID read from a tag.

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
- a Raspberry Pi with an RC522 connected over SPI;
- Python 3.10+;
- a Spotify Premium account and a Spotify Developer app for live playback; and
- a tag UID. Read the UID with the RC522 tooling or another NFC reader; this repository does not write payloads to tags.

The current RC522 code expects the `MFRC522` Python package and `spidev`; install those from `requirements-pi.txt` in addition to the base requirements.

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

The suite uses a temporary SQLite database and the fake Spotify client. It does not require `.env`, Spotify credentials, an RC522, SPI, or a running server. It covers configuration validation, tag assignment, dispatch, simulator validation, and the RC522 UID lookup behavior.

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

## Read a tag's UID

Before assigning a tag in the UI, you need its UID. On the Pi, with the RC522 wired up, SPI enabled, and `requirements-pi.txt` installed:

```bash
source .venv/bin/activate
python -m app.nfc_reader --read
```

The command polls the reader, prints `Hold a tag near the reader...`, and once you present a tag prints its four-byte UID as uppercase hexadecimal (without the reader's check byte), for example `uid=04A7B2F1`. Press `Ctrl-C` to cancel if no tag is presented.

If the command waits without detecting a tag, run the low-level diagnostic:

```bash
python -m app.rc522_diag --seconds 30
```

The diagnostic bypasses the `mfrc522` package. It checks both SPI chip-select
lines at several speeds, accepts only known RC522 version values, verifies
register writes and antenna control, checks the reset line, and sends a direct
REQA command. Stop any other reader process first so it does not keep the reset
GPIO busy. Use `--no-rst` only to isolate a reset-line problem.

## First tag assignment

The assignment UI is the supported way to associate a UID with playback:

1. Start TapTune and open `http://127.0.0.1:5000/` locally, or `http://<pi-ip>:5000/` from another device on the same network.
2. Enter the UID from the previous step exactly as printed (the RC522 implementation formats it as uppercase hexadecimal, for example `04A7B2F1`).
3. Enter one supported value:
   - `spotify:track:<id>`
   - `spotify:playlist:<id>`
   - `spotify:album:<id>`
   - `action:play_pause`
   - `action:next`
4. Optionally add a friendly label and select **Save tag**.
5. Verify the row appears under **Assigned tags**.
6. Dispatch the saved mapping explicitly while NFC polling is not yet wired:

```bash
curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
```

`action:next` and `action:next_track` are equivalent; the UI quick-fill control uses the latter.

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

The dependency script replaces the `RPi.GPIO` package pulled in by `mfrc522` with the compatible `rpi-lgpio` backend required by Raspberry Pi 5. It is safe to rerun in an existing virtual environment when upgrading.

Edit `.env` with `nano .env`. Keep `DATABASE_PATH=./data/raspi_spotify_nfc.db` unless you deliberately want another location. Enable SPI with `sudo raspi-config` → **Interface Options** → **SPI**, then reboot if Raspberry Pi OS requests it. Connect the RC522 according to the board's pin labels and Pi documentation; do not power a 3.3 V RC522 from 5 V.

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

The service is configured to restart after failures. It currently serves the web UI; it does not make physical taps dispatch automatically (see the boundary at the top of this file).

## Health checks and logs

`/health` is a lightweight process check and returns JSON such as `{"app":"TapTune","status":"ok"}`. It does not validate Spotify credentials, Connect-device availability, SPI wiring, or database contents.

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
| RC522 import fails | Activate the Pi virtual environment, run `./systemd/install-pi-dependencies.sh`, and verify SPI is enabled. |
| `Cannot determine SOC peripheral base address` on Raspberry Pi 5 | Pull the latest changes and run `./systemd/install-pi-dependencies.sh` to replace `RPi.GPIO` with `rpi-lgpio`. |
| Reader waits or reports `0x00`/`0xFF` | Stop other reader jobs and run `python -m app.rc522_diag --seconds 30`; its final output distinguishes SPI, reset, antenna, and tag-response failures. |
| Physical taps do nothing | Expected with the current scaffold: `app.main` does not poll `RC522Reader` yet. Use `app.simulate` or `/dispatch`. |
| A tag cannot be written | Expected: tag writing is explicitly not implemented in v1. |

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
