# Speaker setup on Raspberry Pi OS Desktop

[Documentation index](README.md)

Use this guide for Debian 13 / Raspberry Pi OS Desktop with PipeWire. The standard [`install-speaker.sh`](../systemd/install-speaker.sh) path is for Raspberry Pi OS Lite: it configures BlueALSA and a system-wide Raspotify service, not the desktop user's PipeWire session.

This setup runs Spotifyd as a **user service** using PipeWire's PulseAudio-compatible
socket (`backend = "pulseaudio"`). The installer below enables user lingering,
starts the audio services at boot and disables WirePlumber's active-login check
for Bluetooth audio. **No desktop login or auto-login is required.**

Use this on a dedicated music Pi with one audio user. Disabling the login check
lets that user's WirePlumber own Bluetooth audio while logged out; another
desktop/login-manager audio session can still compete for the device.

## 1. Connect the Bluetooth speaker

Pair the speaker using the desktop Bluetooth settings. In the sound settings,
select it as the output device and confirm it plays audio. Get its address with
`bluetoothctl devices` and put `BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF` in TapTune's
`.env` (using your speaker's address).

Do not install BlueALSA or enable the **system-wide** `taptune-bluetooth.service`.
The installer uses a separate **user** service with the same name, which can
access this user's PipeWire server.

## 2. Install Spotifyd

Install the **default** Spotifyd build for your Pi's architecture using the [official Spotifyd installation guide](https://docs.spotifyd.rs/installation/). The default build includes desktop audio backends. Put the executable at `/usr/local/bin/spotifyd`.

Spotifyd and Raspotify are separate Spotify Connect receivers. Do not install or enable the system-wide Raspotify receiver for this Desktop setup. If you previously installed the Lite speaker setup, stop its services to avoid competing audio receivers:

```bash
sudo systemctl disable --now raspotify.service
sudo systemctl disable --now bluealsa.service
sudo systemctl disable --now taptune-bluetooth.service
```

Skip a command if that service is not installed.

## 3. Configure and authenticate Spotifyd

Create the configuration file:

```bash
mkdir -p ~/.config/spotifyd
cat > ~/.config/spotifyd/spotifyd.conf <<'EOF'
[global]
device_name = "TapTune"
device_type = "speaker"
backend = "pulseaudio"
initial_volume = 30
volume_controller = "softvol"
use_mpris = false
EOF
chmod 600 ~/.config/spotifyd/spotifyd.conf
```

Authenticate from the desktop user's terminal. Spotifyd opens an OAuth link; complete it in a browser using the Spotify account you use for TapTune:

```bash
/usr/local/bin/spotifyd authenticate
```

Spotifyd stores its credentials in that user's cache. Keep using the same desktop account so the service can read them.

## 4. Enable audio before login and Bluetooth recovery

Install the runtime tools if needed:

```bash
sudo apt install -y pipewire pipewire-pulse wireplumber pulseaudio-utils bluez
```

From the TapTune repository, run **as the same user who authenticated Spotifyd**,
not with `sudo` (the script invokes `sudo` only for system changes):

```bash
bash systemd/install-desktop-speaker.sh --dry-run
bash systemd/install-desktop-speaker.sh
```

It installs the Spotifyd and Bluetooth user services, sets Spotifyd's
`initial_volume` to 30, enables lingering for this user, starts PipeWire and
WirePlumber at boot, and configures Bluetooth audio without an active login
session. WirePlumber 0.4 (Bookworm) and 0.5 (Trixie) use different configuration
formats; the installer detects which to use.

The Bluetooth service checks the link every 10 seconds, retries connections,
sets this speaker as the default audio sink and moves existing playback streams
back to it after reconnection. This includes desktop audio, so the Pi should be
dedicated to this speaker. It logs failures and retries while the audio server
or speaker is unavailable.

If you previously enabled another `spotifyd.service`, disable it so only one
receiver runs: `systemctl --user disable --now spotifyd.service`.

## 5. Configure TapTune

In TapTune's `.env`, keep the Connect device name in sync and disable the ready chime:

```dotenv
SPOTIFY_DEVICE_NAME=TapTune
SPOTIFY_INITIAL_VOLUME=30
BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF
READY_SOUND_ENABLED=false
```

Use your actual Bluetooth address. TapTune checks this connection on each local
receiver command, reconnects if needed, and reports `bluetooth_not_ready` rather
than dispatching to a disconnected speaker. A tap may take a few seconds while
the speaker reconnects. Physical power-off cannot be repaired in software.

TapTune's system service cannot use the user's PipeWire audio session for its
chime, so leave the chime disabled. Volume initialization still runs. Reinstall
TapTune's unit in Desktop mode so it no longer starts competing Lite services:

```bash
bash systemd/install-service.sh --desktop
sudo systemctl restart raspi-spotify-nfc.service
```

When nothing is already playing, TapTune sends playback to the `TapTune`
Connect device. If another Spotify device is active, tags continue to control
that device.

## 6. Verify a cold boot

Reboot with the speaker powered on. **Before logging into the Pi**, choose
**TapTune** in Spotify on your phone or tap a music tag. Confirm sound comes from
the Bluetooth speaker, not HDMI or the Pi's analogue output. Allow time for
network connection and Spotify registration.

Then log in to inspect:

```bash
loginctl show-user "$(id -un)" -p Linger
systemctl --user status pipewire-pulse.service wireplumber.service taptune-spotifyd.service taptune-bluetooth.service --no-pager
pactl get-default-sink
journalctl --user -u taptune-bluetooth.service -u taptune-spotifyd.service -n 100 --no-pager
```

For idle recovery, stop music, let the speaker disconnect, then tap again.
Reconnection and PipeWire routing are separate steps: if BlueZ reconnects but
audio is still on another sink, inspect the Bluetooth user-service log. A
speaker that powers off completely needs its auto-standby setting disabled
(if available) or must be turned on manually. We do not send periodic sounds
or silently resume music to keep it awake.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| TapTune is missing from Spotify's device list | Check `Linger=yes` with `loginctl show-user "$(id -un)" -p Linger`, then inspect the Spotifyd and PipeWire user services. |
| Spotifyd fails to start | Read its user-service log with `journalctl --user -u taptune-spotifyd.service -n 100 --no-pager`. |
| Spotifyd is visible but silent | Confirm the Bluetooth speaker is connected and selected as the desktop output; check `wpctl status` and the Spotifyd log. |
| Bluetooth says connected but music only works after login | Check the WirePlumber headless config installed by the script and that PipeWire/WirePlumber are running under the Spotifyd user. Lingering alone does not disable WirePlumber's active-session check. |
| Volume tags fail | Use `volume_controller = "softvol"`, not `"none"`, and check that Spotify reports volume support for the receiver. |
| The speaker disconnects after idle | Check the Bluetooth user-service log. Turn the speaker back on if it powered off; software cannot wake an unreachable powered-off device. |
| TapTune dispatch returns `speaker_not_ready` | Check the `SPOTIFY_DEVICE_NAME` value in `.env` matches `device_name` in `spotifyd.conf`, then restart both services. |
