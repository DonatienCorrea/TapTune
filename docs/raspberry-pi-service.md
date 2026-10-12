# Install and operate TapTune on Raspberry Pi

[Documentation index](README.md)

Use this as the fresh-install checklist. Prepare the software first, prove fake
mode and the hardware separately, then authorize Spotify, configure **one**
speaker stack and enable continuous reader polling.

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
cd "$HOME"
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

Stop the foreground app with `Ctrl-C`. Complete the
[hardware first-card test](hardware-setup.md#read-the-first-card), then follow
[Spotify authorization](spotify-authorization.md) for live playback. If you are
connected over SSH, use that guide's SSH port-forwarding instructions for the
browser callback.

A Web API token is not enough: the Pi needs a separately authenticated Spotify
Connect receiver. Choose **one** path before enabling the TapTune service:

| Pi audio stack | Receiver setup | TapTune service installer |
| --- | --- | --- |
| OS Lite without PipeWire | [BlueALSA + Raspotify](speaker-setup.md) | `bash systemd/install-service.sh` |
| OS Desktop with PipeWire (Bookworm/Trixie) | [Desktop + Spotifyd](speaker-setup-desktop.md) | `bash systemd/install-service.sh --desktop` |

Both paths prepare playback after boot without login. Neither automatically
starts music at boot; a tag starts or resumes playback. Use the same Spotify
account for TapTune and the receiver. Return here after sound works from the
Spotify app, and run `python -m app.main` again for tag assignment.

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
bash systemd/install-service.sh
```

The installer invokes `sudo` for system changes, rewrites and quotes those three
paths, and restarts TapTune even if it is already running. With the Lite speaker
setup, the unit starts after `raspotify` and the Bluetooth services, but this
ordering does not mean the network, Spotify account or speaker is ready yet.
On Desktop/PipeWire, use `bash systemd/install-service.sh --desktop` instead:
this removes the Lite audio dependencies. The separate Spotifyd user services
must already be enabled with the [PipeWire desktop setup](speaker-setup-desktop.md).
Desktop mode also suppresses the system process's ALSA chime; its ready-sound
**user** service reads `READY_SOUND_ENABLED` from `.env` and plays through PipeWire.
After installing or updating the Desktop system unit, run
`systemctl --user --no-block restart taptune-ready-sound.service` as the audio
user so it performs a fresh readiness check.

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
`/ready` checks live configuration and whether the initialized reader thread is
alive when enabled. The ready-sound worker separately waits for Spotify
visibility and speaker audio before announcing readiness.

## Safe updates

Back up the database and `.env` before updating:

For Desktop/PipeWire, replace the `install-service.sh` command below with
`bash systemd/install-service.sh --desktop`, and rerun
`bash systemd/install-desktop-speaker.sh` as the Spotifyd user to update its
installed reconnect script and user units.

```bash
cd "$HOME/TapTune"  # or the checkout path used during installation
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
bash systemd/install-speaker.sh  # Lite only; Desktop: use install-desktop-speaker.sh
bash systemd/install-service.sh
sudo systemctl status raspi-spotify-nfc.service --no-pager
curl http://127.0.0.1:5000/health
```

If `git pull --ff-only` reports local changes, stop and resolve them instead of overwriting `.env` or the database. Restore the database only while the service is stopped.

Do not recopy `.env.example` over an existing `.env` during updates. After an
update, repeat the cold-boot check in your chosen speaker guide with no Pi login.
