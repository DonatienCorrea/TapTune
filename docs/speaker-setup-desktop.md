# Speaker setup on Raspberry Pi OS Desktop

[Documentation index](README.md)

Use this guide for Raspberry Pi OS Desktop with PipeWire (Bookworm/Debian 12 or
Trixie/Debian 13). First prepare the checkout, `.venv` and `.env` using
[Install the project](raspberry-pi-service.md#install-the-project), and complete
[TapTune's Spotify authorization](spotify-authorization.md). The standard
[`install-speaker.sh`](../systemd/install-speaker.sh) path is for Lite: it
configures BlueALSA and a system-wide Raspotify service, not this user's session.

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

Check `/usr/local/bin/spotifyd --version` before proceeding. If the downloaded
binary fails with a missing shared library, use the
[Spotifyd source-build guide](spotifyd-setup.md), then return to step 3 here.

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

If running this command over SSH, forward Spotifyd's OAuth callback port from
your computer with `ssh -L 8000:127.0.0.1:8000 <user>@<pi-ip>`, then open the
printed link on that computer. Spotifyd v0.4.2 defaults to port 8000 (check
`spotifyd authenticate --help` if using another version). This is separate from
TapTune's token-generation callback on port 8888.

Spotifyd stores its credentials in that user's cache. Keep using the same desktop account so the service can read them.
TapTune's Web API refresh token does not authenticate Spotifyd; both logins are
required and must use the same Spotify account.

## 4. Enable audio before login and Bluetooth recovery

Install the runtime tools if needed:

```bash
sudo apt update
sudo apt install -y pipewire pipewire-pulse wireplumber libspa-0.2-bluetooth pulseaudio-utils bluez dbus-user-session
```

From the TapTune repository, run **as the same user who authenticated Spotifyd**,
not with `sudo` (the script invokes `sudo` only for system changes):

```bash
bash systemd/install-desktop-speaker.sh --dry-run
bash systemd/install-desktop-speaker.sh
```

It installs the Spotifyd, Bluetooth and ready-sound user services, sets Spotifyd's
`initial_volume` to `SPOTIFY_INITIAL_VOLUME` from `.env` (default 30), enables lingering for this user, starts PipeWire and
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

In TapTune's `.env`, keep the Connect device name in sync and enable the ready chime:

```dotenv
SPOTIFY_DEVICE_NAME=TapTune
SPOTIFY_INITIAL_VOLUME=30
BLUETOOTH_SPEAKER_MAC=AA:BB:CC:DD:EE:FF
READY_SOUND_ENABLED=true
```

Use your actual Bluetooth address. TapTune checks this connection on each local
receiver command, reconnects if needed, and reports `bluetooth_not_ready` rather
than dispatching to a disconnected speaker. A tap may take a few seconds while
the speaker reconnects. Physical power-off cannot be repaired in software.

TapTune's system service cannot use the user's PipeWire audio session. Desktop
mode therefore disables the chime **only in that system unit**, while the
`taptune-ready-sound.service` user unit honors `READY_SOUND_ENABLED` in `.env`
and plays it with `paplay`. Volume initialization still runs in TapTune.
On a fresh install, return to
[Assign and verify a tag](raspberry-pi-service.md#assign-and-verify-a-tag) now,
then install the system unit in Desktop mode there. If the service is already
installed, update it so it does not start competing Lite services:

```bash
bash systemd/install-service.sh --desktop
systemctl --user --no-block restart taptune-ready-sound.service
```

The chime waits up to ten minutes for TapTune's `/ready` check, the local Spotify
receiver, the Bluetooth link and the speaker being the default PipeWire output.
It then plays the two-note sound explicitly on that speaker, never HDMI.
`/ready` requires live Spotify configuration and a running initialized reader
thread when `NFC_READER_ENABLED=true`; actual Spotify visibility is checked
separately. These checks cannot prove future tag reads or Spotify playback will
never fail.

It sounds once per boot or restart of the ready-sound user service, not on
every tap or Bluetooth reconnection. Set `READY_SOUND_ENABLED=false` to disable
it. After restarting TapTune manually, restart the ready-sound user service too
if you want a new confirmation.

TapTune sends playback to the `TapTune` Connect device **only if Spotify reports
no current device**. A paused phone
still counts as the current device; select TapTune in Spotify's device picker
to test local playback. Boot configures audio and volume but does not start
music automatically.

If you change the Bluetooth MAC or startup volume later,
rerun the Desktop speaker installer and restart TapTune: the user reconnect
service reads an installed copy of the MAC, not the repository's `.env`.

## 6. Verify a cold boot

Reboot with the speaker powered on. **Before logging into the Pi**, wait for
the ready chime, then tap a music tag. Confirm sound comes from
the Bluetooth speaker, not HDMI or the Pi's analogue output. Allow time for
network connection and Spotify registration.

Then log in to inspect:

```bash
loginctl show-user "$(id -un)" -p Linger
systemctl --user status pipewire-pulse.service wireplumber.service taptune-spotifyd.service taptune-bluetooth.service taptune-ready-sound.service --no-pager
pactl get-default-sink
journalctl --user -u taptune-bluetooth.service -u taptune-spotifyd.service -u taptune-ready-sound.service -n 100 --no-pager
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
| No ready chime | Set `READY_SOUND_ENABLED=true` in `.env`, confirm `curl http://127.0.0.1:5000/ready` succeeds, then read `journalctl --user -u taptune-ready-sound.service -n 100 --no-pager`. After fixing the problem or turning on a speaker beyond the ten-minute wait, restart that user service. |
