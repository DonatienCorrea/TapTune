# Spotify receiver: go-librespot

[Installation checklist](raspberry-pi-service.md) · [Documentation index](README.md)

New installs use [go-librespot](https://github.com/devgianlu/go-librespot) as
the Pi's Spotify receiver on **both** Raspberry Pi OS Lite and Desktop. Audio
takes the same route on both: go-librespot → PipeWire → Bluetooth speaker. On
Lite, PipeWire runs in the background without a desktop.

| | go-librespot (default for new installs) | Legacy |
| --- | --- | --- |
| Receiver | go-librespot | Raspotify (Lite), Spotifyd (Desktop) |
| Audio | PipeWire on both | BlueALSA (Lite), PipeWire (Desktop) |
| Spotify sign-in | Choose TapTune once in the Spotify app | Receiver login, plus a Web API refresh token |
| Spotify Developer app | Only for the music browser on the web page | Required |

## Sign in once

1. Run `./install.sh --lite --configure` (or `--desktop --configure`). This
   installs go-librespot, PipeWire and the `taptune-go-librespot` user service.
2. On a phone or computer on the **same Wi-Fi**, open Spotify, tap
   **Devices** and choose **TapTune** (your `SPOTIFY_DEVICE_NAME`).
3. Open `http://<pi-name>.local:5000/setup`. The Spotify step turns to
   *done* by itself once the Pi is signed in.

TapTune never asks for your Spotify password. go-librespot saves its sign-in
(`persist_credentials: true`) in `~/.config/go-librespot/credentials.json`, so
after a restart the Pi signs in by itself and tags play with no phone nearby.
If the sign-in is lost (for example after a password change), choose TapTune in
Spotify → Devices again.

`taptune status` shows a **Spotify sign-in (go-librespot)** line.

## What uses what

- **Tags, play/pause, next and volume** go through go-librespot's local API,
  which listens only on `127.0.0.1:3678`. No Spotify Developer app is needed.
- If a phone is already playing, these commands are sent to that phone, as
  before.
- **Show tags** still start the newest episode. TapTune looks it up with the
  sign-in that go-librespot already has. If the lookup fails, the show plays
  from its start.
- **The music browser** (saved albums, playlists, search) still uses the Spotify
  Web API. It is optional: to use it, fill in `SPOTIFY_CLIENT_ID`,
  `SPOTIFY_CLIENT_SECRET` and `SPOTIFY_REFRESH_TOKEN` as described in
  [Spotify authorization](spotify-authorization.md).

## Move an existing install

Existing installs keep Raspotify or Spotifyd. `taptune update` does not switch
receivers. To move:

```bash
cd ~/TapTune
sed -i 's/^#\?\s*SPOTIFY_RECEIVER=.*/SPOTIFY_RECEIVER=go-librespot/' .env
grep -q '^SPOTIFY_RECEIVER=' .env || echo 'SPOTIFY_RECEIVER=go-librespot' >> .env
taptune update
```

The installer stops and disables Raspotify, Spotifyd and BlueALSA (it does not
uninstall them). Then choose TapTune once in Spotify → Devices.

**To go back**, set `SPOTIFY_RECEIVER=legacy` and run `taptune update` again.
This stops go-librespot and reinstalls the previous receiver. On Lite, the
Raspotify login may need to be done again: see [Lite speaker setup](speaker-setup.md).

## Installation details

- The installer downloads a pinned go-librespot release from GitHub and checks
  its SHA-256 before putting it in `/usr/local/bin/go-librespot`.
- Its settings are in `~/.config/go-librespot/config.yml` (private, mode
  `600`). TapTune rewrites this file on each install; change `.env` instead.
- The service is a user service of the audio user, which stays running without
  a login (`loginctl enable-linger`):

  ```bash
  systemctl --user status taptune-go-librespot.service
  journalctl --user -u taptune-go-librespot.service -n 100 --no-pager
  ```

- The Pi is found by Spotify apps through Avahi (mDNS). Phone and Pi must be on
  the same network, and the network must allow mDNS.
