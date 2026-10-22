# Lite speaker setup: BlueALSA + Raspotify

[Installation checklist](raspberry-pi-service.md) · [Documentation index](README.md)

This is the speaker reference for **Raspberry Pi OS Lite without PipeWire**.
For Desktop, use [PipeWire + Spotifyd](speaker-setup-desktop.md), not these
commands. For a fresh install, the checklist prepares Python first and calls
this guide only for pairing and the one-time receiver login.

## 1. Pair the Bluetooth speaker

```bash
sudo apt update
sudo apt install -y bluez
sudo systemctl enable --now bluetooth.service
bluetoothctl
```

Put the speaker in pairing mode. Inside `bluetoothctl`, replace the example MAC
with the address next to your speaker in the scan results:

```text
power on
agent on
default-agent
scan on
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
scan off
quit
```

Pairing and trusting are manual, once per speaker. A connection may not work
until BlueALSA is installed. Save the actual MAC in `.env`:

```dotenv
BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF
SPOTIFY_DEVICE_NAME=TapTune
SPOTIFY_INITIAL_VOLUME=30
AUDIO_OUTPUT_DEVICE=bluealsa
READY_SOUND_ENABLED=true
```

Return to [Configure and start services](raspberry-pi-service.md#configure-and-start-services).
`./install.sh --lite --configure` installs BlueALSA, the managed Raspotify
package, its speaker-specific A2DP output and credential caching, then the
TapTune service. No separate Bluetooth reconnect service is needed.

## 2. Link the Pi to your Spotify account

After configuration has installed Raspotify:

1. Open Spotify on a phone/computer on the same network as the Pi.
2. Sign into **the same Premium account** authorized for TapTune's Web API.
3. Start a song and choose **TapTune** (or `SPOTIFY_DEVICE_NAME`) in the device picker.
4. Confirm audio comes from the Bluetooth speaker, then pause playback.

Raspotify caches that receiver login for future boots. This is separate from
TapTune's Web API refresh token; a token alone cannot make the receiver available.
If multiple devices called TapTune appear, look for a second Raspotify/Spotifyd
instance rather than renaming devices until the collision disappears.

## 3. Check audio and a cold boot

If Spotify is visible but silent, test the configured speaker directly:

```bash
bluetoothctl connect AA:BB:CC:DD:EE:FF
aplay -D 'bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp' /usr/share/sounds/alsa/Front_Center.wav
```

Use your speaker's MAC. You should hear "Front center". A receiver visible in
Spotify does not prove A2DP audio works. The Pi output is unmuted at full device
level; listening volume is controlled by Spotify, initially 30%.

Return to [Assign and verify a tag](raspberry-pi-service.md#assign-and-verify-a-tag)
and the checklist's no-login cold-boot check. TapTune makes one bounded startup
connection/readiness phase and plays at most one chime per app start. A chime
checks app, enabled reader, receiver visibility and actual audio output; it
cannot promise that every later Spotify request or card read will succeed.

**There is no periodic reconnect or keepalive.** After the boot phase, only a
local music start/resume tap may reconnect. Pause and volume taps do not.
If the speaker powers off, turn it on and tap a content/start tag. A manual
`taptune restart` requests a fresh startup check; boot never starts music.

## Settings in `.env`

| Setting | Default | Meaning |
| --- | --- | --- |
| `SPOTIFY_DEVICE_NAME` | `TapTune` | Local Connect name; must match the receiver. Spotify's current device is retained even while paused. |
| `SPOTIFY_INITIAL_VOLUME` | `30` | Receiver startup volume, 0–100. |
| `BLUETOOTH_SPEAKER_MAC` | empty | Paired speaker address used at startup and local music start/resume. |
| `AUDIO_OUTPUT_DEVICE` | `bluealsa` | Expanded to the configured MAC's A2DP device; never silently falls back to HDMI. |
| `READY_SOUND_ENABLED` | `true` | Set `false` to disable the chime. |

After changing receiver name, MAC, output or startup volume, reapply with
`./install.sh --lite --configure`. Use `taptune update` for code updates.
The low-level `systemd/install-speaker.sh` is an implementation detail and
repair tool, not an additional fresh-install step.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| `speaker_not_ready` or receiver disappears after reboot | Inspect `sudo systemctl status raspotify --no-pager`; repeat the receiver login and check credential caching. |
| Receiver is visible but silent | Test the explicit A2DP device above; inspect `bluetoothctl info <MAC>` and `sudo journalctl -u raspotify -n 100 --no-pager`. |
| Music plays on the phone | A paused phone is still Spotify's current device; select TapTune in the device picker. |
| No chime | Inspect `taptune logs` for the startup timeout/failure; check `READY_SOUND_ENABLED` and `/ready`. After fixing the cause, restart TapTune for a new check. |
| Bluetooth disconnects while idle | Expected not to reconnect periodically; power on the speaker if needed and tap a local music start/resume tag. |
| Multiple TapTune receivers or competing audio | Do not run Raspotify and Spotifyd together. Reconfigure the intended stack; inspect other users' sessions if competition remains. |
