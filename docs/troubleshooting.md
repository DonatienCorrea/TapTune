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
| `systemctl enable --now` fails with “unavailable resources or another system error” | The unit paths probably do not match the checkout. Rerun `sudo ./systemd/install-service.sh` from the repository root. |
| The service exits immediately | Confirm `.env` exists, the unit paths match it, and `taptune logs` shows the Python error. |
| Startup works only sometimes | Every service now retries on its own: wait a minute after boot, then run `taptune status`. If something is still down, read `taptune logs -b 0` (or `-b -1` for the previous boot) and look for the first error. `taptune restart` restarts everything in order. |
| Fake mode is unexpected | All three live Spotify values must be non-empty. Remove placeholder values or complete the credentials, then restart. |
| Spotify reports an authorization error | Recheck the client ID, client secret, refresh-token scopes, and exact redirect URI. |
| Spotify reports no active device | Complete [Speaker setup](speaker-setup.md) so the Pi is always available, or open Spotify on a Connect-capable device using the same account, start playback once, and retry. |
| Dispatch returns `speaker_not_ready` | Spotify has no current device and the Pi receiver named by `SPOTIFY_DEVICE_NAME` is not visible. Check the name and receiver's separate Spotify login in the [Lite](speaker-setup.md#troubleshooting) or [Desktop](speaker-setup-desktop.md#troubleshooting) guide. |
| Dispatch returns `bluetooth_not_ready` | Power on the paired speaker; verify the address in `.env` and `bluetoothctl info <MAC>`. Read the system reconnect log on Lite or the user reconnect log on Desktop. |
| Music plays on the phone instead of the Pi | Spotify's current device is retained even while paused. Select the Pi in Spotify's device picker before testing local playback. |
| No music starts automatically at boot | Expected: boot prepares the receiver and volume; a content or play/pause tag starts music. |
| No ready chime after boot | Set `READY_SOUND_ENABLED=true` in `.env`. Check `/ready`, the Connect name, speaker connection and the [Lite](speaker-setup.md#troubleshooting) or [Desktop user-service](speaker-setup-desktop.md#troubleshooting) logs. |
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

- If this fails, correct the mapping or playback configuration before debugging hardware.
- If it succeeds but a physical tap does not, focus on `NFC_READER_ENABLED`, reader initialization, UID output, and service logs.

## Spotify authorization checks

See the dedicated [Spotify authorization troubleshooting table](spotify-authorization.md#troubleshooting) for callback, redirect URI, account, and refresh-token problems.
