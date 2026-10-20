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
paths (including paths with spaces), and restarts TapTune even if it is already
running. With the Lite speaker setup, the unit starts after `raspotify` and the
Bluetooth services, but this ordering does not mean the network, Spotify account
or speaker is ready yet.
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

The installer links the `taptune` command (also runnable as `./taptune` from
the checkout). Run it as your normal user, not with `sudo`; it asks for `sudo`
when needed. It detects the Lite or Desktop setup automatically (force it with
`--lite` or `--desktop`).

```bash
taptune status    # every service's state, plus /health and /ready
taptune restart   # restart Bluetooth, the Spotify receiver and TapTune in order
taptune help
```

Every service restarts on its own and never stops retrying:

- TapTune restarts after any crash. Inside it, the PN532 is reopened with
  increasing delays (2 s up to 30 s) after I2C errors at boot or later; after
  20 failures in a row TapTune restarts as a whole. `/ready` stays `503` until
  the reader has actually opened.
- A Spotify token refresh that fails because the network is not up yet is
  retried, and a tap during a network outage reports `network_error` instead
  of stopping the reader. The Pi receiver is looked up three times before a
  tap reports `speaker_not_ready`.
- Raspotify (Lite) waits for the network and always restarts. Spotifyd
  (Desktop) waits for DNS before starting and restarts even after a clean exit.
- The Bluetooth reconnect services power the adapter on if a connection fails.
- Each time the speaker connects, the Pi's own output (the PipeWire sink on
  Desktop, the BlueALSA mixer on Lite) is set to 100% and unmuted. Music level
  is controlled only by Spotify (30% at startup, then volume tags), and the
  ready chime is a quieter sound file, so it does not lower the music.
- The Desktop ready-sound service tries again after its ten-minute wait.

With `NFC_READER_ENABLED=false`, TapTune serves only the web UI. With the
setting enabled, it also polls the PN532 and dispatches assigned tags.

## Logs and inspection

All TapTune services log to the systemd journal. `taptune logs` shows them
merged in time order: TapTune, the Bluetooth reconnect, Raspotify or Spotifyd,
the ready chime, BlueALSA or PipeWire/WirePlumber and BlueZ.

```bash
taptune logs                 # last 200 lines of this boot
taptune logs -f              # follow live (Ctrl-C to stop)
taptune logs -b -1           # the previous boot, after a failed start
taptune logs --since "10 min ago"
taptune logs -- -p warning   # only warnings and errors
taptune logs --save          # status + logs in taptune-logs-<date>.txt
```

Each start logs one summary line (version, Spotify live or **FAKE** mode,
receiver name, reader, speaker) and warns about fake mode or a disabled reader.
Failed taps are logged as warnings with the reason, and a readiness timeout
names the last problem it saw, so `taptune logs -- -p warning` usually points
straight at the cause.

The installer keeps the journal across reboots
(`/etc/systemd/journald.conf.d/taptune.conf`, at most 200 MB) so earlier boots
stay readable. Single services can still be read directly:

```bash
sudo journalctl -u raspi-spotify-nfc.service -n 100 --no-pager
journalctl --user -u taptune-spotifyd.service -n 100 --no-pager   # Desktop
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

One command updates everything:

```bash
taptune update
```

It:

1. backs up `.env` and the tag database to `data/backups/` (last 10 kept);
2. runs `git pull --ff-only`, and stops without changing anything if local
   changes are in the way;
3. installs the Python dependencies;
4. runs the test suite and stops before restarting anything if it fails;
5. reruns the speaker installer for your setup (`install-speaker.sh` on Lite,
   `install-desktop-speaker.sh` on Desktop) and `install-service.sh`, which
   restart every service; and
6. waits until TapTune answers on `/health`.

Options: `--no-pull` reinstalls the current checkout, `--skip-tests` skips the
tests and `--dry-run` (before `update`) prints the commands without running
them. Run it as the Spotifyd audio user on Desktop.

The first time, the command does not exist yet. Download it once, then run it
from the checkout:

```bash
cd "$HOME/TapTune"   # or your checkout path
git pull --ff-only
./taptune update
```

If a step fails, `taptune` stops, names the step and the command that failed,
and leaves the running services untouched when the failure happens before the
reinstall step. Restore a backup only while the service is stopped:

```bash
sudo systemctl stop raspi-spotify-nfc.service
cp data/backups/tags.<date>.db.bak data/raspi_spotify_nfc.db
taptune restart
```

Do not recopy `.env.example` over an existing `.env` during updates. After an
update, repeat the cold-boot check in your chosen speaker guide with no Pi login.
