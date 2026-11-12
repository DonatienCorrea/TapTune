# Desktop speaker setup: PipeWire + Spotifyd

[Installation checklist](raspberry-pi-service.md) · [Documentation index](README.md)

This is the advanced route for Raspberry Pi OS Desktop with PipeWire
(Bookworm/Debian 12 or Trixie/Debian 13). **Lite + Raspotify is the shorter
route** if you do not need a desktop. Do not install BlueALSA/Raspotify alongside
this setup.

Use a dedicated music Pi with **one audio user**. Prepare the checkout using
`./install.sh --desktop`, then complete these prerequisites as that same user,
not root. The receiver's account cache and PipeWire session belong to this user.
Another desktop/login-manager session can compete for Bluetooth audio.

## 1. Pair and test the speaker

Pair/trust the speaker in the desktop Bluetooth settings, select it as the
sound output and play a test sound. Get the address with `bluetoothctl devices`
and set `BLUETOOTH_SPEAKER_MAC` in TapTune's `.env`.

Install the runtime audio tools:

```bash
sudo apt update
sudo apt install -y pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth pulseaudio-utils bluez dbus-user-session
```

## 2. Supply a compatible Spotifyd binary

Follow the [official Spotifyd installation guide](https://docs.spotifyd.rs/installation/)
for your OS and architecture. Use the default build with desktop audio backends,
installed at `/usr/local/bin/spotifyd`, and check:

```bash
/usr/local/bin/spotifyd --version
ldd /usr/local/bin/spotifyd
```

There must be no missing shared libraries. TapTune deliberately does **not**
download an arbitrary Spotifyd build or assume an ALSA-only build supports
PipeWire. If a binary requires unavailable libraries such as `libssl.so.1.1`,
the [optional source-build reference](spotifyd-setup.md) describes building on
the target OS. It is not a required Lite step.

## 3. Configure and authenticate Spotifyd

For a new Spotifyd configuration (back up an existing file instead of
overwriting it):

```bash
mkdir -p ~/.config/spotifyd
cat > ~/.config/spotifyd/spotifyd.conf <<'EOF'
[global]
device_name = "TapTune"
device_type = "speaker"
backend = "pulseaudio"
initial_volume = 10
bitrate = 320
volume_controller = "softvol"
use_mpris = false
EOF
chmod 600 ~/.config/spotifyd/spotifyd.conf
/usr/local/bin/spotifyd authenticate
```

Use one `[global]` section and the standard `~/.config` directory.
Authenticate in the browser with **the same Premium account** used for
[TapTune's separate Web API authorization](spotify-authorization.md).
Spotifyd stores the receiver login in this user's cache.

Over SSH, forward the receiver callback **from your computer**:
`ssh -L 8000:127.0.0.1:8000 <user>@<pi-ip>`, then run authentication on the Pi
and open the printed URL in the computer's browser. Spotifyd v0.4.2 defaults
to port 8000; check `spotifyd authenticate --help` for other versions.
This is separate from TapTune's callback on port 8888.

In TapTune's `.env`, keep the name and volume consistent:

```dotenv
SPOTIFY_DEVICE_NAME=TapTune
SPOTIFY_INITIAL_VOLUME=10
BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF
READY_SOUND_ENABLED=true
```

Use the real speaker address. Return to
[Configure and start services](raspberry-pi-service.md#configure-and-start-services)
and run `./install.sh --desktop --configure` there. Do not separately run the
speaker/service installers.
The installer sets Spotifyd to 320 kbps, its maximum supported bitrate, and
applies the 10% startup volume.

## What completion configures

The installer enables lingering and the audio user's PipeWire/WirePlumber
services at boot, disables WirePlumber's active-login check for Bluetooth
audio, and installs `taptune-spotifyd.service` as a **user** unit.
WirePlumber 0.4 and 0.5 need different formats; the installer detects them.
**Desktop login or auto-login is not needed.**

TapTune itself runs as a system service. Its Desktop mode records the invoking
audio user (`DESKTOP_AUDIO_USER` in the generated unit) and uses that user's
PipeWire session for connection/routing and the ready chime. The app owns the
one bounded startup phase; **there is no separate Bluetooth reconnect or
ready-sound service**. Old TapTune units are disabled/removed on reconfiguration.
The installer also disables conflicting Lite receiver services without removing
their packages, including the leftover `bluealsa-aplay.service`, and disables
both system and audio-user `spotifyd.service` units so only
`taptune-spotifyd.service` remains.

On a dedicated player, the LightDM login screen must not own Bluetooth audio.
The installer adds
`/etc/systemd/user/wireplumber.service.d/90-taptune-no-greeter.conf` with
`ConditionUser=!lightdm` and stops LightDM's WirePlumber if its user manager is
running. This prevents login-screen audio, **not** the audio user's desktop
sound, and also applies at the next boot if LightDM is currently stopped.
It does not stop LightDM itself, disable desktop login or modify other users'
receiver services. Do not independently reenable a second `spotifyd.service`,
Raspotify or BlueALSA, including from another user. If repurposing the Pi,
remove that drop-in and reload/restart the affected user services to restore
login-screen audio.

After startup there is no periodic Bluetooth reconnect or keepalive sound.
Only local music start/resume taps reconnect and route audio when needed.
Pause and volume taps do not. A powered-off speaker must be switched on
manually. Connection failure is reported rather than silently sending audio
to HDMI. Spotify's current device is kept even while paused; select TapTune in
Spotify's device picker to test the local receiver.

Changing the speaker MAC, receiver name, volume or audio user requires
reconfiguration as the correct audio user. Use `taptune update` for code changes,
not a parallel manual Spotifyd service install.

## Verify before relying on it

Reboot with the speaker on. **Before logging into the Pi**, wait for the single
ready chime and tap a music tag; confirm sound comes from the Bluetooth
speaker. Boot does not start music. Readiness is bounded, not an endless retry;
after fixing a startup failure use `taptune restart` for a new check.

Then inspect from a terminal as the audio user:

```bash
loginctl show-user "$(id -un)" -p Linger
systemctl --user status pipewire-pulse.service wireplumber.service taptune-spotifyd.service --no-pager
pactl get-default-sink
pactl list short sinks
pactl list cards
taptune status
taptune logs
journalctl --user -u taptune-spotifyd.service -n 100 --no-pager
```

For the Bluetooth speaker, confirm an active `a2dp-sink` profile (possibly
with a codec suffix) and a stereo `2ch` sink. `headset-head-unit` with
`1ch 16000Hz` is hands-free call audio, not the intended music output.
`SUSPENDED` is normal before playback. A Bluetooth connection, successful
Spotify command or healthy web endpoint alone does not prove stereo playback.

Check idle behavior separately: pause music, let the speaker disconnect, turn it
on if necessary, then tap a local content/start tag. Pause/volume tags should
not reconnect it, and idle time should not produce another chime.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Receiver missing before login | Check `Linger=yes`, user audio services, and the Spotifyd cache belongs to this user. |
| Spotifyd cannot start | Inspect its user journal; check `--version`, missing libraries and the `pulseaudio` backend. |
| Audio works only after desktop login | Check WirePlumber's headless config, lingering, `DESKTOP_AUDIO_USER` in the installed TapTune unit, and competing users' sessions. |
| Receiver visible but silent | Inspect `wpctl status`, speaker connection/default output and `taptune logs` for routing errors. |
| Only hands-free audio, or A2DP missing / `Device or resource busy` | Check for a second `spotifyd.service`, a leftover BlueALSA player, and LightDM's WirePlumber. Earlier Desktop installers did not clean up all three. Apply the updated Desktop installer through `taptune update`, then reboot and verify A2DP stereo playback. Other paired devices can also compete for the speaker. |
| Volume actions fail | Use `volume_controller = "softvol"` and check receiver volume support. |
| `speaker_not_ready` | Match `.env`'s `SPOTIFY_DEVICE_NAME` to Spotifyd's `device_name`; confirm both account logins. |
| No chime | Inspect TapTune's system journal, `/ready` and `READY_SOUND_ENABLED`; no separate user ready-sound unit should be started. |
