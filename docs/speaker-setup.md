# Make the Raspberry Pi its own speaker

[Documentation index](README.md)

By default Spotify only plays on a device where someone has already opened Spotify, such as a phone or computer. This guide makes the Raspberry Pi a Spotify speaker of its own. After setup:

1. You switch on the Bluetooth speaker and the Pi.
2. The Pi connects to the speaker and signs in to Spotify by itself.
3. A short two-note chime means **TapTune is ready**.
4. You tap a tag and the music plays. No phone is needed.

If music is already playing on another device, such as a phone, a tag keeps playing there. When nothing is playing, which is the normal state after switching on, TapTune plays on the Pi.

## What you need

- TapTune installed on the Pi ([Raspberry Pi service](raspberry-pi-service.md)) with working [Spotify authorization](spotify-authorization.md).
- Raspberry Pi OS **Lite** for the BlueALSA setup below. For Debian 13 Desktop, use the [PipeWire desktop setup](speaker-setup-desktop.md) instead.
- A Bluetooth speaker.
- A phone or computer with the Spotify app, needed **once** during setup.

Do not run `systemd/install-speaker.sh` on a Desktop/PipeWire installation. It configures BlueALSA and the system-wide Raspotify service, which do not use the desktop user's PipeWire audio session.

## 1. Install the speaker software

From the TapTune folder on the Pi:

```bash
./systemd/install-speaker.sh --dry-run   # optional: preview every command
./systemd/install-speaker.sh
```

The script:

- installs `bluez-alsa` so the Pi can play sound through a Bluetooth speaker;
- installs [raspotify](https://github.com/dtcooper/raspotify), a Spotify Connect receiver, with the name from `SPOTIFY_DEVICE_NAME` (default `TapTune`);
- turns on raspotify's **credential cache**. Raspotify ships with it disabled, which would make the Pi forget the Spotify account at every reboot; and
- installs `taptune-bluetooth.service`, which keeps reconnecting the speaker.

It is safe to run the script again, for example after changing `SPOTIFY_DEVICE_NAME`.

## 2. Pair the Bluetooth speaker

Put the speaker in pairing mode, then run:

```bash
bluetoothctl
```

Inside `bluetoothctl`, type the following. Replace `AA:BB:CC:DD:EE:FF` with your speaker's address, which appears in the scan results next to its name:

```text
scan on
pair AA:BB:CC:DD:EE:FF
trust AA:BB:CC:DD:EE:FF
connect AA:BB:CC:DD:EE:FF
scan off
quit
```

`trust` lets the Pi reconnect later without asking. Save the address in `.env`:

```dotenv
BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF
```

Then restart the reconnect service and check the speaker:

```bash
sudo systemctl restart taptune-bluetooth.service
aplay -D bluealsa /usr/share/sounds/alsa/Front_Center.wav
```

You should hear "Front center" from the speaker.

## 3. Link the Pi to your Spotify account (once)

1. Make sure the phone or computer is on the **same Wi-Fi network** as the Pi.
2. Open Spotify, start any song, and open the device list (the speaker icon).
3. Choose **TapTune**. The music moves to the Bluetooth speaker.

Raspotify now remembers the account. From now on it signs in by itself at every boot, and TapTune can find it without the phone.

Use the same Spotify account that you authorized for TapTune.

## 4. Check the ready sound and test a reboot

Restart TapTune, then reboot the Pi with the speaker on:

```bash
sudo systemctl restart raspi-spotify-nfc.service
sudo reboot
```

Within a minute or so of booting, you should hear the chime. Tap a tag and the music starts on the speaker.

If the speaker is switched on after the Pi, the Pi connects to it within about ten seconds, and the chime plays then. The chime plays once each time TapTune starts.

## Settings in `.env`

| Setting | Default | Meaning |
| --- | --- | --- |
| `SPOTIFY_DEVICE_NAME` | `TapTune` | Name of the Pi in Spotify's device list. When nothing else is playing, TapTune sends music here. Leave it empty to only use devices that are already active, which was the old behavior. |
| `BLUETOOTH_SPEAKER_MAC` | empty | Address of the speaker to keep connected. |
| `AUDIO_OUTPUT_DEVICE` | `bluealsa` | ALSA output used for the ready sound. If it fails, the system default device is tried. |
| `READY_SOUND_ENABLED` | `true` | Set to `false` to switch the chime off. |

Restart TapTune after changing these values. If you change `SPOTIFY_DEVICE_NAME`, rerun `./systemd/install-speaker.sh` so raspotify uses the same name.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| No chime after boot, and taps return `speaker_not_ready` | The Pi is not signed in to Spotify. Check `sudo systemctl status raspotify`, then repeat [step 3](#3-link-the-pi-to-your-spotify-account-once). |
| The Pi disappears from Spotify after a reboot | The credential cache is disabled. Rerun `./systemd/install-speaker.sh`, then repeat step 3. |
| The logs say the speaker is online but the ready sound could not be played | The speaker is not connected. Check `bluetoothctl info <MAC>` and `sudo journalctl -u taptune-bluetooth -n 50`. |
| Music plays on the phone instead of the speaker | Spotify still considers the phone active, even while paused. Choose TapTune in the phone's device list, or close Spotify on the phone. |
| Spotify shows TapTune but music is silent | Test the speaker with `aplay -D bluealsa …` from step 2, and check `sudo journalctl -u raspotify -n 50`. |
