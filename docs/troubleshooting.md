# Troubleshooting

[Documentation index](README.md)

Over SSH:

```bash
taptune status            # is each part running?
taptune logs              # what happened (add -b -1 for the previous boot)
taptune logs --save       # save status + logs to a file to share
```

No screen or terminal? Open **Activity log** on the music page
(`http://taptune.local/logs`). It lists taps, played music and messages (last
2,000 entries, times in UTC). Its **Maintenance** section can update or restart
TapTune, restart the Pi, and **Download diagnostic logs** to share when asking
for help.

| Problem | What to do |
| --- | --- |
| The page doesn't open | Try `http://taptune.local:5000/` or `http://<pi-ip>:5000/`. Check the phone is on the same Wi-Fi. Run `taptune status`. |
| TapTune doesn't appear in Spotify → Devices | Phone and Pi must be on the same Wi-Fi (mDNS allowed). Check `taptune status` and `taptune logs`. |
| Setup page says Spotify isn't signed in | In Spotify, tap **Devices** and choose **TapTune** again (needed after a password change or `taptune reset`). |
| Music plays on the phone instead of the Pi | A paused phone still counts as the active device. Choose TapTune under **Devices**. |
| `bluetooth_not_ready` | Turn the speaker on, then tap a music tag. Check the address with `bluetoothctl info <MAC>`. Pause and volume tags never reconnect. |
| `speaker_not_ready` | Spotify can't see TapTune. Sign in again (Spotify → Devices → TapTune) and check `SPOTIFY_DEVICE_NAME`. |
| Sound is mono or very poor | `taptune status` should show an `a2dp-sink` profile, not `headset-head-unit`. Turn the speaker off and on, then tap a music tag. Unpair other devices that grab the speaker. |
| No chime after boot | Check `READY_SOUND_ENABLED=true` and `taptune logs`. Fix the cause, then `taptune restart`. Music never starts by itself at boot. |
| A tag does nothing | Does diagnostics show `NFC reader: ready`? If not, check the wiring. Check `taptune logs` for an unknown-tag message, then write the tag again or use [manual setup](tag-usage.md#manual-setup). |
| A tag can't be written | Use an unlocked NTAG213/215/216 and the Pi's reader. Keep the tag still until **Verified**. See [supported tags](tag-usage.md#supported-tags). |
| Something fails just after boot | Wait a minute: TapTune retries by itself while the Spotify receiver starts. If it lasts, use **Restart TapTune** on the Activity log page. |
| No albums or playlists on the music page | Spotify isn't signed in yet: see step 5 of the [installation guide](raspberry-pi-service.md#5-speaker-and-spotify-web-setup). |
| A podcast starts from its first episode | Choose TapTune in Spotify → Devices once more, then tap again. |
| Reader not found | See [Hardware setup](hardware-setup.md#if-it-doesnt-work). |
| `TapTune-Setup` Wi-Fi doesn't appear | It appears only when no known network works, about a minute after boot. Check `TAPTUNE_WIFI_SETUP` isn't `false`. |
| Install fails with `.env is accessible to other users` | Run `chmod 600 .env`. |
| `ModuleNotFoundError` | Use `.venv/bin/python`, or rerun `./install.sh`. |
| An update failed | Download diagnostic logs from the Activity log page, or run `taptune update` over SSH to see the failing step. Backups are in `data/backups/`. |
| Tests print tracebacks but end with `OK` | Normal: some tests check error handling. |

Test a manual setup without the reader:

```bash
curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
```

If this works but tapping doesn't, the problem is the reader, not Spotify.
