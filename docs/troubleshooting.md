# Troubleshooting

[Documentation index](README.md)

Start with the smallest failing boundary: web process, configuration, Spotify, I2C, reader initialization, card read, assignment, then dispatch.

First look at everything in one place:

```bash
taptune status          # is each service running? does TapTune answer?
taptune logs -n 200     # merged logs of every TapTune service, this boot
taptune logs -b -1      # the previous boot, e.g. after a start that failed
taptune logs --save     # write status + logs to a file you can share
```

`taptune` is linked by `install-service.sh`; from a checkout you can also run
`./taptune`. See [Raspberry Pi service](raspberry-pi-service.md#logs-and-inspection).

| Symptom | What to check |
| --- | --- |
| `curl` cannot connect | Confirm `systemctl status`, port `5000`, `APP_HOST`, and the Pi IP. |
| `systemctl enable --now` fails with “unavailable resources or another system error” | Inspect `systemctl cat raspi-spotify-nfc.service` for the actual paths and journal for the failed directive. Run `./install.sh --lite --configure` (or `--desktop` / `--app-only`) **without sudo** to regenerate correctly quoted paths, including checkout names with spaces. Do not copy the template unit unchanged. |
| The service exits immediately | Confirm `.env` exists, the unit paths match it, and `taptune logs` shows the Python error. |
| Startup works only sometimes | Read `taptune logs -b 0` (or `-b -1`) for the first error. App/receiver process restarts and PN532 retries are separate from the bounded boot Bluetooth check. There is no periodic Bluetooth retry. After fixing the cause, `taptune restart` requests a fresh startup check. |
| Fake mode is unexpected | All three live Spotify values must be non-empty. Remove placeholder values or complete the credentials, then restart. |
| Spotify reports an authorization error | Recheck the client ID, client secret, refresh-token scopes, and exact redirect URI. |
| Spotify reports no active device | Complete the receiver's separate account login using the [Lite](speaker-setup.md) or [Desktop](speaker-setup-desktop.md) guide, or open another Connect-capable player using the same account and play something once. |
| Dispatch returns `speaker_not_ready` | Spotify has no current device and the Pi receiver named by `SPOTIFY_DEVICE_NAME` is not visible. Check the name and receiver's separate Spotify login in the [Lite](speaker-setup.md#troubleshooting) or [Desktop](speaker-setup-desktop.md#troubleshooting) guide. |
| Dispatch returns `bluetooth_not_ready` | Power on the paired/trusted speaker; verify `.env`'s address and `bluetoothctl info <MAC>`. Inspect `taptune logs` for connection/routing failures, then tap a local music/start tag. Pause and volume do not trigger reconnection. |
| Music plays on the phone instead of the Pi | Spotify's current device is retained even while paused. Select the Pi in Spotify's device picker before testing local playback. |
| No music starts automatically at boot | Expected: boot prepares the receiver and volume; a content or play/pause tag starts music. |
| No ready chime after boot | Check `READY_SOUND_ENABLED`, `/ready`, both Spotify logins, receiver name and audio output. The app performs one bounded check, not a periodic chime loop; after fixing the cause, restart TapTune. On Desktop inspect the configured audio user; do not start an obsolete ready-sound user unit. |
| Speaker disconnects during idle | No automatic background reconnect is expected. Turn the speaker on if necessary, then tap a local music/start tag. Do not use pause/volume as a wake-up test. |
| Duplicate TapTune devices, zeroconf errors or competing audio | Confirm only one receiver stack is running. Reapply the intended mode, inspect Raspotify and Spotifyd units (including other users'), and do not enable BlueALSA alongside PipeWire. A duplicate name alone does not establish the exact fault; inspect the receiver journal. |
| `ModuleNotFoundError: spotipy` or PN532 support missing | Use `.venv/bin/python`, not the system Python. Rerun `./install.sh --lite` / `--desktop` for a Pi or `--app-only` for development; this prepares dependencies but starts no services. |
| Python or venv preparation fails | Install Python 3.10+ and `python3-venv`, check the first pip/network error, and rerun preparation. No dependency install failure is treated as success. |
| Tests print warnings or failure-path tracebacks but end with `OK` | Some tests deliberately exercise errors. Read the unittest summary and exit status; a traceback from a mocked failure is not evidence of a deployed service failure. A `FAILED` summary must still be investigated. |
| A tag is “unknown” | Assign the complete UID printed by the reader. Avoid extra spaces and preserve the exact value. |
| PN532 import fails | Activate the Pi virtual environment and rerun `./systemd/install-pi-dependencies.sh`. |
| `/dev/i2c-1` is missing | Enable I2C with `sudo raspi-config` and reboot. |
| `i2cdetect -y 1` does not show `24` | Power down, confirm I2C mode, and recheck 3.3 V, ground, SDA on physical pin 3, and SCL on pin 5. Then use the first-card test because generic probing is not definitive for every board. |
| The reader command waits forever | Stop the service and other reader processes, place a known Type A card directly over the antenna, and run `python -m app.pn532_diag --seconds 30`. |
| The UID changes or looks incomplete | Copy the entire value printed for one card. Do not assume every card has a four-byte UID. |
| The diagnostic reads a card but service taps do nothing | Set `NFC_READER_ENABLED=true` in the service's `.env`, restart, and inspect `taptune logs` for reader retries or unassigned-tag warnings. |
| The same held card plays repeatedly | Update to the current reader loop. It dispatches once and requires card removal before the next tap. |
| A tag cannot be written | Expected: TapTune does not write tags. Write NDEF with a phone on a Type 2 tag (NTAG21x), or assign its UID in the UI. The PN532 reads supported NDEF values before falling back to UID mappings. |

## Web and service checks

```bash
sudo systemctl status raspi-spotify-nfc.service --no-pager
curl http://127.0.0.1:5000/health
sudo journalctl -u raspi-spotify-nfc.service -n 100 --no-pager
ss -ltn | grep ':5000'
```

Remember that `/health` proves only that the Flask process responds.
`/ready` additionally requires live Spotify configuration and the initialized
reader thread to be alive when enabled. It does not itself contact Spotify or
check the Bluetooth output; the ready-sound worker performs those checks before
playing the chime.

The app now owns boot Bluetooth and chime work on both stacks. Old
`taptune-bluetooth.service` (system/user) and user
`taptune-ready-sound.service` units are removed by reconfiguration/update;
instructions to enable or restart them are obsolete. Desktop still needs
the Spotifyd and PipeWire/WirePlumber **user** services. See
[why these services remain separate](architecture.md#why-not-one-service).

## PN532 checks

Stop the service before running a standalone reader test:

```bash
sudo systemctl stop raspi-spotify-nfc.service
source .venv/bin/activate
python -m app.pn532_diag --seconds 30
```

If initialization reports missing PN532 support:

```bash
./systemd/install-pi-dependencies.sh
```

Then retry from the same activated environment.

## Assignment and dispatch checks

Inspect the saved UID:

```bash
sqlite3 data/raspi_spotify_nfc.db \
  'select uid, tag_type, value, label, updated_at from tags order by updated_at desc;'
```

Dispatch the exact UID without the reader:

```bash
curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
```

- If this fails, correct the mapping or playback configuration before debugging hardware. Inspect the JSON `status` and error reason, not only HTTP connectivity.
- If it succeeds but a physical tap does not, focus on `NFC_READER_ENABLED`, reader initialization, UID output, and service logs.

Repeated action taps:

- A tag acts once per tap. Lift it away from the reader before tapping again;
  holding it in place does not repeat the action.
- Spotify reports volume and play/pause state a few seconds late. TapTune
  remembers what it just did, so repeated volume taps keep stepping and a
  second play/pause tap resumes. The log shows each decision, for example
  `Volume 40% -> 50%` or `Play/pause: resuming.`; if Spotify refuses to resume
  on a device, TapTune moves playback to the Pi and logs a warning.

## Spotify authorization checks

See the dedicated [Spotify authorization troubleshooting table](spotify-authorization.md#troubleshooting) for callback, redirect URI, account, and refresh-token problems.
