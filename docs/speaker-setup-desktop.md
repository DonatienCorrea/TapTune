# Speaker setup on Raspberry Pi OS Desktop

[Documentation index](README.md)

Use this guide for Debian 13 / Raspberry Pi OS Desktop with PipeWire. The standard [`install-speaker.sh`](../systemd/install-speaker.sh) path is for Raspberry Pi OS Lite: it configures BlueALSA and a system-wide Raspotify service, not the desktop user's PipeWire session.

This setup runs Spotifyd as a **user service**. It uses the desktop session's PipeWire PulseAudio-compatible socket, so the Connect speaker is available while that user is logged in. If the Pi does not log in automatically after boot, the speaker will not be available until you log in.

## 1. Connect the Bluetooth speaker

Pair the speaker using the desktop Bluetooth settings. In the sound settings, select it as the output device and confirm that the desktop can play audio through it. PipeWire/WirePlumber manages the Bluetooth connection; do not install BlueALSA or enable `taptune-bluetooth.service` for this setup.

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
use_mpris = false
EOF
chmod 600 ~/.config/spotifyd/spotifyd.conf
```

Authenticate from the desktop user's terminal. Spotifyd opens an OAuth link; complete it in a browser using the Spotify account you use for TapTune:

```bash
/usr/local/bin/spotifyd authenticate
```

Spotifyd stores its credentials in that user's cache. Keep using the same desktop account so the service can read them.

## 4. Run Spotifyd when the desktop session starts

Install the included user unit:

```bash
mkdir -p ~/.config/systemd/user
cp systemd/taptune-spotifyd.user.service ~/.config/systemd/user/taptune-spotifyd.service
systemctl --user daemon-reload
systemctl --user enable --now taptune-spotifyd.service
```

Check that the receiver is running:

```bash
systemctl --user status taptune-spotifyd.service --no-pager
```

Open Spotify on a phone or computer on the same network and choose **TapTune** from its device list. This confirms that Spotify Connect can reach the Pi.

## 5. Configure TapTune

In TapTune's `.env`, keep the Connect device name in sync and disable the ready chime:

```dotenv
SPOTIFY_DEVICE_NAME=TapTune
READY_SOUND_ENABLED=false
```

TapTune runs as a system service and cannot use the desktop user's PipeWire audio session for its chime. Spotifyd handles music playback through PipeWire. Restart TapTune after changing `.env`:

```bash
sudo systemctl restart raspi-spotify-nfc.service
```

When nothing is already playing, TapTune sends playback to the `TapTune` Connect device. Music starts after the desktop user session and Spotifyd are running.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| TapTune is missing from Spotify's device list | Confirm the desktop user is logged in, then run `systemctl --user status taptune-spotifyd.service --no-pager`. |
| Spotifyd fails to start | Read its user-service log with `journalctl --user -u taptune-spotifyd.service -n 100 --no-pager`. |
| Spotifyd is visible but silent | Confirm the Bluetooth speaker is connected and selected as the desktop output; check `wpctl status` and the Spotifyd log. |
| TapTune dispatch returns `speaker_not_ready` | Check the `SPOTIFY_DEVICE_NAME` value in `.env` matches `device_name` in `spotifyd.conf`, then restart both services. |
