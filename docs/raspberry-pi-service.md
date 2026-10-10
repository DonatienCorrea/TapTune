# Install and operate TapTune on Raspberry Pi

[Documentation index](README.md)

Complete the [hardware first-card test](hardware-setup.md#read-the-first-card) and a [fake-mode run](getting-started.md) before enabling continuous reader polling.

## Requirements

- Raspberry Pi OS Lite or another Raspberry Pi OS installation;
- SSH access;
- Python 3.10 or newer;
- a PN532 configured for I2C;
- an NFC tag whose UID has passed the first-card test; and
- a Spotify Premium account and Spotify Developer app for live playback.

## Install the project

From an SSH session:

```bash
sudo apt update
sudo apt install -y git python3-venv sqlite3
cd /home/pi
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
./systemd/install-pi-dependencies.sh
cp .env.example .env
chmod 600 .env
```

The dependency script installs the base packages and Pi-only reader packages. It is safe to rerun inside an existing virtual environment when upgrading.

Edit `.env`:

```bash
nano .env
```

Keep `DATABASE_PATH=./data/raspi_spotify_nfc.db` unless you deliberately need another location. Leave `NFC_READER_ENABLED=false` during setup.

## Prove the software works

Before installing the service:

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
python -m app.main
```

From another machine on the same network:

```bash
curl http://<pi-ip>:5000/health
```

Follow [Spotify authorization](spotify-authorization.md) when you are ready for live playback. A valid token is not enough by itself; playback also needs a Spotify Connect device. Follow [Speaker setup](speaker-setup.md) to make the Pi that device so it plays right after boot.

## Assign and verify a tag

1. Open `http://<pi-ip>:5000/`.
2. Save the exact UID from the first-card test with a supported value.
3. Verify it before enabling hardware polling:

   ```bash
   curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
   ```

4. Stop TapTune.
5. Set `NFC_READER_ENABLED=true` in `.env`.

See [Using tags](tag-usage.md) for supported values and behavior.

## Install the systemd service

The checked-in unit uses `/home/pi/TapTune` as a placeholder. Installing it unchanged from another directory causes `systemctl enable --now` to fail because `WorkingDirectory`, `ExecStart`, and `EnvironmentFile` point to missing paths.

Run the installer from the repository root after `.venv` and `.env` exist:

```bash
sudo ./systemd/install-service.sh
```

The installer rewrites those three paths for the current checkout before installing the unit. With the Lite speaker setup, the unit starts after `raspotify` and the Bluetooth services. On Debian 13 Desktop, the Spotify Connect receiver is a separate user service and starts with the desktop session; see [PipeWire desktop setup](speaker-setup-desktop.md).

Preview the generated unit without root or installation:

```bash
./systemd/install-service.sh --dry-run
```

## Operate the service

```bash
sudo systemctl status raspi-spotify-nfc.service --no-pager
curl http://127.0.0.1:5000/health
```

Common operations:

```bash
sudo systemctl restart raspi-spotify-nfc.service
sudo systemctl stop raspi-spotify-nfc.service
sudo systemctl disable raspi-spotify-nfc.service
```

The service restarts after failures. With `NFC_READER_ENABLED=false`, it serves only the web UI. With the setting enabled, it also polls the PN532 and dispatches assigned tags.

## Logs and inspection

```bash
sudo journalctl -u raspi-spotify-nfc.service -n 100 --no-pager
sudo journalctl -u raspi-spotify-nfc.service -f
ss -ltn | grep ':5000'
```

Inspect mappings safely:

```bash
sqlite3 data/raspi_spotify_nfc.db \
  'select uid, tag_type, value, label, updated_at from tags order by updated_at desc;'
```

`/health` is a lightweight process check. It does not validate Spotify credentials, Connect-device availability, PN532/I2C wiring, reader-thread health, or database contents.

## Safe updates

Back up the database and `.env` before updating:

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

If `git pull --ff-only` reports local changes, stop and resolve them instead of overwriting `.env` or the database. Restore the database only while the service is stopped.
