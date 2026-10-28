# Install and operate TapTune on Raspberry Pi

[Documentation index](README.md)

**This is the start-to-finish installation checklist.** Use Raspberry Pi OS
**Lite** for the shortest standalone-player setup. Use **Desktop** only if you
need PipeWire and can install/authenticate Spotifyd. Pick one route and keep it
throughout; do not run both audio stacks.

You need a networked Raspberry Pi, SSH or terminal access, Python 3.10+, a PN532
in I2C mode, a compatible tag, a Bluetooth speaker, Spotify Premium and a Spotify
Developer app. A phone/computer with Spotify is needed for initial authorization,
not for everyday tag use. For a software-only trial, use the separate
[fake-mode guide](getting-started.md).

## Install the project

Run as your normal user, **not with sudo**. On Desktop, use the one dedicated
audio user who will authenticate Spotifyd.

```bash
sudo apt update
sudo apt install -y git python3-venv sqlite3
cd "$HOME"
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
./install.sh --lite
```

For Desktop, replace `--lite` with `--desktop`. Preparation creates or reuses
`.venv`, installs base and PN532 Python dependencies, and creates `.env` with
mode `600` **only if absent**. It starts no services, changes no audio stack,
and does not overwrite existing settings or permissions. If an old `.env` is
too open, run `chmod 600 .env` before completion. Do not source `.env` in a shell.

Preview either phase without modifying the machine:

```bash
./install.sh --lite --dry-run
./install.sh --lite --configure --dry-run
./install.sh --help
```

Paths containing spaces are supported: use the installers, which rewrite and
quote the actual checkout paths in systemd units. Do not copy a unit unchanged
from the repository; its `/home/pi/TapTune` paths are placeholders.

## Finish the manual prerequisites

These steps cannot safely be automated by the installer. Stay in this checklist;
return here after each linked reference.

1. **Wire and prove the reader.** Power down before wiring, select I2C mode,
   enable I2C and reboot as described in [Hardware setup](hardware-setup.md).
   Run `.venv/bin/python -m app.pn532_diag --seconds 30` and obtain a reliable
   complete UID. Then set `NFC_READER_ENABLED=true` in `.env`.
2. **Authorize TapTune's Spotify Web API client.** Follow
   [Spotify authorization](spotify-authorization.md), including the SSH callback
   tunnel if needed. Fill in the client ID, secret and refresh token in `.env`.
   The dashboard redirect URI and `.env` must match **exactly**.
3. **Prepare the selected speaker path.** On **Lite**, complete
   [speaker pairing](speaker-setup.md#1-pair-the-bluetooth-speaker) and save its
   MAC in `.env`; the next checklist step installs the receiver. On **Desktop**,
   complete [Desktop prerequisites](speaker-setup-desktop.md) through Spotifyd
   authentication and audio packages, but do not install services separately.
4. **Review `.env`.** Keep `SPOTIFY_DEVICE_NAME=TapTune` consistent with the
   receiver name, `SPOTIFY_INITIAL_VOLUME=30` for a safe starting level, and
   `DATABASE_PATH=./data/raspi_spotify_nfc.db` unless intentionally relocating
   the database. Set your real `BLUETOOTH_SPEAKER_MAC`.

The two Spotify authorizations are different: the Web API token controls
playback; Raspotify/Spotifyd must also log into **the same account** to receive
audio. On Lite the receiver login happens just after its installation below.

## Configure and start services

From the checkout, after the manual prerequisites:

```bash
./install.sh --lite --configure
```

Use `--desktop --configure` for Desktop. Completion requires existing `.venv`
and a private `.env`, populated live credential fields, enabled reader and a
paired/trusted speaker. These checks do **not** validate Spotify tokens online,
prove wiring or detect whether Spotifyd's cached account is correct.

The command runs the matching speaker installer, then installs and restarts the
TapTune unit with the correct mode. It invokes `sudo` only for system changes.
**Do not run another service installer afterwards.**

Lite installs BlueALSA plus the managed Raspotify package. Its installer may
download and execute the upstream Raspotify installer from
`https://dtcooper.github.io/raspotify/install.sh`; inspect
`systemd/install-speaker.sh` before granting permission if that matters for your
deployment. Desktop does not download Spotifyd automatically: you supply a
compatible binary and authenticate it first. The chosen installer disables
competing receiver services and removes obsolete TapTune reconnect/chime units;
it does not uninstall packages or manage other users' audio sessions.

On a **first Lite install**, now open Spotify on a phone/computer on the same
network and choose **TapTune** in the device picker. This caches Raspotify's
account login. Confirm music plays on the Bluetooth speaker, then pause it.
No chime during this account setup is a reason to inspect the receiver login,
not to install a second receiver.

If the startup check expired while completing the receiver login, run
`taptune restart` to request a fresh bounded check and chime.

## Assign and verify a tag

Open `http://<pi-ip>:5000/`. Choose music in the Spotify picker, select
**Start writing**, and place an unlocked NTAG213/215/216 or writable NFC Type 4 NDEF tag on the Pi's reader
until the page confirms the write was verified. Remove it, then tap again to
play. See [Using tags](tag-usage.md#browse-spotify-and-write-a-tag) for details.

For manual UID assignments or playback actions, open
**Advanced: manual tag setup & playback shortcuts** and assign the UID from
the diagnostic. Test a saved UID mapping without the reader if needed:

```bash
curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
```

The UI and dispatch endpoint have **no authentication**. Use a trusted local
network; do not forward port 5000 from the internet. `.env`, receiver caches and
backups contain account secrets: never commit or attach them to an issue.

Reboot with the speaker powered on. **Before logging into the Pi**, wait for
the single ready chime and tap a music tag. Confirm sound comes from the
Bluetooth speaker rather than HDMI. This cold-boot check is necessary on real
hardware; software tests alone cannot prove it.

## Startup and Bluetooth behavior

TapTune owns one bounded boot connection/readiness phase and at most one chime
per app start. It waits for the app, initialized reader when enabled, Spotify
receiver visibility and speaker audio; there is no guarantee of a fixed boot
time. Boot prepares volume and the receiver but **does not start music**.

After that phase there is **no periodic Bluetooth reconnect**, periodic sound
or repeated readiness chime. A local content/start/resume tag may reconnect and
route audio. Pause, volume and commands for another active Spotify device do
not reconnect. If a speaker powers itself off, turn it back on and tap a local
music/start tag; software cannot wake an unreachable powered-off speaker.
Spotify's current device is retained even while paused, so select TapTune in
Spotify's device picker when testing the local receiver.

TapTune and the receiver can restart after process failures; that is different
from continuously trying Bluetooth. Reader initialization retries are also
separate from Bluetooth policy. See [Service boundaries](architecture.md#why-not-one-service)
for the remaining services and why they cannot all be merged.

## Operate the service

`install.sh --configure` links `taptune` into `/usr/local/bin`; it is also
runnable as `./taptune`. Run it as your normal user (the audio user on Desktop).
It detects the setup; explicit `--lite`, `--desktop` or `--app-only` before the
command overrides detection.

```bash
taptune status
taptune restart
taptune help
```

Rerunning preparation does not start services or reset credentials. Rerunning
`--configure` reapplies the selected service/audio configuration and restarts
the app, so use it after changing the speaker MAC, receiver name or startup
volume, or when deliberately changing stack. Back up first. Do not move the
checkout after installation without reconfiguring its unit paths.

**Advanced app-only deployment:** `./install.sh --app-only` prepares only base
Python dependencies. `--app-only --configure` installs only TapTune and requires
live credentials; it does not install a local receiver or Bluetooth stack.
Use another authenticated Spotify Connect device, disable local targeting with
`SPOTIFY_DEVICE_NAME=` and the local chime with `READY_SOUND_ENABLED=false` when
there is no Pi receiver. Leave NFC disabled unless you have
separately installed Pi dependencies and passed the reader diagnostic.

## Logs and inspection

```bash
taptune logs
taptune logs -f
taptune logs -b -1
taptune logs --since "10 min ago"
taptune logs -- -p warning
taptune logs --save
```

Logs cover TapTune (including boot/chime/Bluetooth decisions), the selected
receiver and OS audio services. The installer enables persistent journaling
(up to 200 MB) so earlier boots remain inspectable. Review and redact saved logs
before sharing them.

```bash
sudo journalctl -u raspi-spotify-nfc.service -n 100 --no-pager
journalctl --user -u taptune-spotifyd.service -n 100 --no-pager  # Desktop only
curl http://127.0.0.1:5000/health
curl http://127.0.0.1:5000/ready
```

`/health` proves only that Flask responds. `/ready` checks live configuration
and the initialized reader thread when enabled; Spotify visibility and audio
are checked separately by the startup worker. None of these can guarantee
future card reads or Spotify requests. Use [Troubleshooting](troubleshooting.md)
for the first failing boundary rather than repeatedly reinstalling.

## Safe updates

Fresh install uses `install.sh`; a deployed installation uses:

```bash
taptune update
```

The command backs up `.env` and the SQLite tag database to `data/backups/`
(last 10 kept), pulls with `git pull --ff-only`, installs dependencies, runs
tests, reapplies the selected installers, restarts and checks `/health`.
A health response does not prove that Bluetooth or Spotify playback is ready.

Run as the audio user on Desktop. Options include `--no-pull` to reinstall the
current checkout, `--skip-tests` to intentionally bypass tests, and
`taptune --dry-run update` to preview. If upgrading an old installation without
the linked command, run `git pull --ff-only` and `./taptune update` from its
checkout. Do not use a new clone or recopy `.env.example` over your live `.env`.

Keep a separate secure backup before changing audio stacks or restoring data.
If update fails, it reports the failed step and stops; there is no automatic
rollback. Failures before service installation leave the running services
alone; a later failure can leave partially updated configuration. Read the
error before retrying. Inspect `data/backups/` for the actual dated filenames.
For a database restore, stop TapTune first:

```bash
sudo systemctl stop raspi-spotify-nfc.service
cp data/backups/tags.<date>.db.bak data/raspi_spotify_nfc.db
taptune restart
```

Never overwrite a custom `DATABASE_PATH` with this default-path example.
Restore `.env` only from a trusted backup, keep mode `600`, and reconfigure if
restoring audio settings. Repeat the no-login cold-boot check after updates.
