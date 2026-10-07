# Troubleshooting

[Documentation index](README.md)

Start with the smallest failing boundary: web process, configuration, Spotify, I2C, reader initialization, card read, assignment, then dispatch.

| Symptom | What to check |
| --- | --- |
| `curl` cannot connect | Confirm `systemctl status`, port `5000`, `APP_HOST`, and the Pi IP. |
| `systemctl enable --now` fails with “unavailable resources or another system error” | The unit paths probably do not match the checkout. Rerun `sudo ./systemd/install-service.sh` from the repository root. |
| The service exits immediately | Confirm `.env` exists, the unit paths match it, and `journalctl` shows the Python error. |
| Fake mode is unexpected | All three live Spotify values must be non-empty. Remove placeholder values or complete the credentials, then restart. |
| Spotify reports an authorization error | Recheck the client ID, client secret, refresh-token scopes, and exact redirect URI. |
| Spotify reports no active device | Open Spotify on a Connect-capable device using the same account, start playback once, and retry. |
| A tag is “unknown” | Assign the complete UID printed by the reader. Avoid extra spaces and preserve the exact value. |
| PN532 import fails | Activate the Pi virtual environment and rerun `./systemd/install-pi-dependencies.sh`. |
| `/dev/i2c-1` is missing | Enable I2C with `sudo raspi-config` and reboot. |
| `i2cdetect -y 1` does not show `24` | Power down, confirm I2C mode, and recheck 3.3 V, ground, SDA on physical pin 3, and SCL on pin 5. Then use the first-card test because generic probing is not definitive for every board. |
| The reader command waits forever | Stop the service and other reader processes, place a known Type A card directly over the antenna, and run `python -m app.pn532_diag --seconds 30`. |
| The UID changes or looks incomplete | Copy the entire value printed for one card. Do not assume every card has a four-byte UID. |
| The diagnostic reads a card but service taps do nothing | Set `NFC_READER_ENABLED=true` in the service's `.env`, restart, and inspect `journalctl` for initialization or unassigned-tag warnings. |
| The same held card plays repeatedly | Update to the current reader loop. It dispatches once and requires card removal before the next tap. |
| A tag cannot be written | Expected: TapTune does not write tags. A phone app can write NDEF, but the current PN532 path still uses UID mappings. |

## Web and service checks

```bash
sudo systemctl status raspi-spotify-nfc.service --no-pager
curl http://127.0.0.1:5000/health
sudo journalctl -u raspi-spotify-nfc.service -n 100 --no-pager
ss -ltn | grep ':5000'
```

Remember that `/health` proves only that the Flask process responds.

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
