# Make the Raspberry Pi its own speaker

[Documentation index](README.md)

By default Spotify only plays on a device where someone has already opened Spotify, such as a phone or computer. This guide makes the Raspberry Pi a Spotify speaker of its own. After setup:

1. You switch on the Bluetooth speaker and the Pi.
2. The Pi connects to the speaker and signs in to Spotify by itself.
3. A short two-note chime means **TapTune is ready**.
4. You tap a tag and the music plays. No phone is needed.

If Spotify reports a current device, such as a phone, a tag keeps controlling it
even while it is paused. When Spotify has no current device, TapTune targets the
Pi by name. Boot itself does **not** start music; tap a content or play/pause tag.

## What you need

- A TapTune checkout with `.venv`, dependencies and `.env` prepared ([Install the project](raspberry-pi-service.md#install-the-project)), and working [Spotify authorization](spotify-authorization.md). The TapTune service does not need to be installed yet.
- Raspberry Pi OS **Lite** for the BlueALSA setup below. For Debian 13 Desktop, use the [PipeWire desktop setup](speaker-setup-desktop.md) instead.
- A Bluetooth speaker.
- A phone or computer with the Spotify app, needed **once** during setup.

Do not run `systemd/install-speaker.sh` on a Desktop/PipeWire installation. It configures BlueALSA and the system-wide Raspotify service, which do not use the desktop user's PipeWire audio session.

## 1. Pair the Bluetooth speaker

From the TapTune folder on the Pi:

```bash
sudo apt update
sudo apt install -y bluez
sudo systemctl enable --now bluetooth.service
```

Put the speaker in pairing mode, then run:

```bash
bluetoothctl
```

Inside `bluetoothctl`, type the following. Replace `AA:BB:CC:DD:EE:FF` with your speaker's address, which appears in the scan results next to its name:

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

`trust` lets the Pi reconnect later without asking. Connection may not work until
BlueALSA is installed in the next step. Save the address and device name in `.env`:

```dotenv
BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF
SPOTIFY_DEVICE_NAME=TapTune
SPOTIFY_INITIAL_VOLUME=30
AUDIO_OUTPUT_DEVICE=bluealsa
READY_SOUND_ENABLED=true
```

## 2. Install the speaker software and check sound

From the TapTune folder, without wrapping the script in `sudo`:

```bash
bash systemd/install-speaker.sh --dry-run   # optional: preview every command
bash systemd/install-speaker.sh
bluetoothctl connect AA:BB:CC:DD:EE:FF
aplay -D 'bluealsa:DEV=AA:BB:CC:DD:EE:FF,PROFILE=a2dp' /usr/share/sounds/alsa/Front_Center.wav
```

Use your speaker's address in both commands. You should hear "Front center".

The script installs BlueALSA and the managed **Raspotify package** (not just any
`librespot` executable). It configures the Connect name, the specific speaker's
A2DP output and startup volume, enables credential caching, trusts the speaker
and starts the reconnect service before restarting Raspotify. It is safe to
rerun after changing these settings. The ready sound uses the same speaker
address when `AUDIO_OUTPUT_DEVICE=bluealsa`.

## 3. Link the Pi to your Spotify account (once)

1. Make sure the phone or computer is on the **same Wi-Fi network** as the Pi.
2. Open Spotify, start any song, and open the device list (the speaker icon).
3. Choose **TapTune** (or your configured `SPOTIFY_DEVICE_NAME`). The music moves to the Bluetooth speaker.

Raspotify now remembers the account. From now on it signs in by itself at every boot, and TapTune can find it without the phone.

Use the same Spotify account that you authorized for TapTune.

## 4. Check the ready sound and test a reboot

Return to [Assign and verify a tag](raspberry-pi-service.md#assign-and-verify-a-tag)
and install the TapTune service if this is a fresh install. Once the service is
installed, restart it and reboot with the speaker on:

```bash
sudo systemctl restart raspi-spotify-nfc.service
sudo reboot
```

The chime waits until TapTune responds on `/ready`, its reader thread is running
when enabled, Spotify sees the configured receiver and the speaker's A2DP
output accepts the sound. It cannot guarantee every future tag read or Spotify
request will succeed.

Before logging in to the Pi, wait for the chime, then tap a tag and confirm music
comes from this speaker. Allow time for Wi-Fi and Spotify registration; startup
initialization retries for up to ten minutes rather than guaranteeing a fixed
boot time.

The reconnect service retries about every ten seconds (a connection attempt can
take additional time). If the speaker comes on within the startup readiness
window, the chime plays then, once per TapTune start. If you waited longer,
restart TapTune to hear the chime; the reconnect service still runs and tags
still work without it.

## Settings in `.env`

| Setting | Default | Meaning |
| --- | --- | --- |
| `SPOTIFY_DEVICE_NAME` | `TapTune` | Name of the Pi in Spotify's device list. When Spotify has no current device, TapTune sends music here. Paused current devices are retained. Leave empty to disable local targeting. |
| `SPOTIFY_INITIAL_VOLUME` | `30` | Receiver startup volume (0–100); also configured in Raspotify by the installer. |
| `BLUETOOTH_SPEAKER_MAC` | empty | Address of the speaker to keep connected. |
| `AUDIO_OUTPUT_DEVICE` | `bluealsa` | ALSA output used for both Raspotify and the ready sound. The default is expanded to the configured MAC's A2DP device; failure is logged and retried, not redirected to HDMI. |
| `READY_SOUND_ENABLED` | `true` | Set to `false` to switch the chime off. |

Rerun `bash systemd/install-speaker.sh` after changing the name, MAC, audio output
or startup volume, then restart TapTune so both services read the same settings.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No chime after boot, and taps return `speaker_not_ready` | Check the configured Connect name and `sudo systemctl status raspotify --no-pager`; the receiver may not be signed in. Repeat [step 3](#3-link-the-pi-to-your-spotify-account-once). |
| The Pi disappears from Spotify after a reboot | The credential cache is disabled. Rerun `./systemd/install-speaker.sh`, then repeat step 3. |
| The logs say the Spotify speaker is online but the ready sound could not be played | Spotify visibility is not audio readiness. Check `bluetoothctl info <MAC>`, test the explicit A2DP device from step 2, and read `sudo journalctl -u taptune-bluetooth -n 50 --no-pager`. |
| Music plays on the phone instead of the speaker | Spotify still considers the phone active, even while paused. Choose TapTune in the phone's device list, or close Spotify on the phone. |
| Spotify shows TapTune but music is silent | Test the speaker with `aplay -D bluealsa …` from step 2, and check `sudo journalctl -u raspotify -n 50`. |
