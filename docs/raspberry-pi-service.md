# Install TapTune on a Raspberry Pi

[Documentation index](README.md) · [Wi-Fi en français](fr/wi-fi.md)

Install once over SSH, then finish setup from a phone. No screen is needed on the Pi.

## What you need

- A Raspberry Pi with Wi-Fi, a microSD card and power supply
- A PN532 NFC reader set to I2C mode, and NFC tags (NTAG213/215/216 work best)
- A Bluetooth speaker
- A Spotify Premium account and the Spotify app on a phone

## 1. Prepare the SD card

In [Raspberry Pi Imager](https://www.raspberrypi.com/software/), choose
**Raspberry Pi OS Lite**. Before writing, open the OS customisation settings and set:

- hostname: `taptune`
- your user name and password, and **enable SSH**
- your Wi-Fi name, password and country

## 2. Connect the reader

With the Pi powered off, insert the SD card and [wire the PN532](hardware-setup.md#wire-the-reader).

## 3. Install TapTune

Power on the Pi. From a computer on the same Wi-Fi, run `ssh <user>@taptune.local`,
replacing `<user>` with the name you set in Imager. If `taptune.local` doesn't
resolve, use the Pi's IP address from your router instead.

Enable I2C for the reader, then install the system packages:

```bash
sudo raspi-config nonint do_i2c 0
sudo apt update && sudo apt install -y git python3-venv sqlite3
```

Download TapTune and run the installer as your normal user (**no `sudo`**):

```bash
cd ~ && git clone https://github.com/DonatienCorrea/TapTune.git &&
cd TapTune &&
./install.sh
```

The installer starts TapTune and asks for `sudo` only for system changes. No
settings file to edit: TapTune detects the reader automatically. Save the private
hotspot password shown at installation if you plan to [move to another Wi-Fi](#move-to-another-wi-fi).

## 4. Finish setup on your phone

On the **same Wi-Fi**, open `http://taptune.local/setup`. If that doesn't open, try
`http://taptune.local:5000/setup` or `http://<pi-ip>:5000/setup`.

- **Bluetooth speaker**: put the speaker in pairing mode, tap
  **Search for speakers** and choose it.
- **Spotify**: in the Spotify app, tap **Devices** and choose **TapTune**.
  TapTune never asks for your Spotify password and stays signed in after restarts.

To check or replace a paired speaker later, use **Play a test sound** or
**Change speaker** on the same page. For French, use `/fr/setup`.

## 5. Write your first tag

Once setup is complete, choose **Make a tag** and follow [Using tags](tag-usage.md#write-music-to-a-tag).
Tap it to play; no reboot is needed. If TapTune can't find the reader, use the
[reader checks](hardware-setup.md#if-it-doesnt-work).

## How it behaves

- At startup, TapTune sets the receiver to 10% volume and connects the speaker
  once. It plays one short chime (at 10% volume) when the reader, Spotify and
  speaker are ready. **It never starts music by itself.**
- After that, there is no background reconnecting. A music tap reconnects the
  speaker if needed; pause and volume taps never do. If the speaker turned
  itself off, switch it on and tap a music tag.
- If a phone is already playing, tags control that phone. Choose TapTune under
  **Devices** to play on the Pi.
- The web pages have no login: keep the Pi on your home network and never
  expose it to the internet. Never share `.env` or backups; they contain account secrets.

## Move to another Wi-Fi

If the Pi finds no known network about 60 seconds after starting, it opens its
own Wi-Fi called **TapTune-Setup** (password-protected, unique to this Pi).

1. If you haven't saved the password, run `taptune setup-wifi` before moving the Pi.
   It also shows a QR code if `qrencode` is installed.
2. At the new place, on your phone, scan the QR code or join `TapTune-Setup`
   with the password. Stay connected if the phone says "no internet".
3. The setup page opens. If not, go to `http://10.42.66.1/setup` (`http://`, not `https://`).
4. Pick your Wi-Fi and enter its password. The Pi leaves `TapTune-Setup` and joins it.
5. Reconnect your phone to your Wi-Fi and open `http://taptune.local/`.
   If it failed, `TapTune-Setup` comes back: try again.

Wi-Fi passwords can only be entered while connected to `TapTune-Setup`.
Enterprise Wi-Fi and networks with a browser sign-in page are not supported.
Anyone with the QR code can configure the Pi, so keep it private.

## Maintenance from the web page

Open **Activity log** on the music page (`http://taptune.local/logs`). It lists
taps, played music and messages, and has a **Maintenance** section:

- the current version;
- **Update TapTune**: downloads and installs the latest version in the
  background; TapTune restarts by itself when done;
- **Restart the Pi** and **Power off the Pi** (before unplugging it);
- **Download diagnostic logs**: a text file to send when asking for help.

No screen or terminal is needed for updates or logs.

TapTune retries by itself when something is briefly unavailable (the Spotify
receiver still starting at boot, a short network error), so a slow start
usually fixes itself.

## Commands (advanced, over SSH)

| Command | What it does |
| --- | --- |
| `taptune status` | Is everything running? Spotify sign-in, speaker profile |
| `taptune logs` | Logs of all TapTune services (`-f` follow, `-b -1` previous boot, `--since "10 min ago"`, `--save` to a file) |
| `taptune restart` | Restart everything and replay the startup check |
| `taptune update` | Back up, download the latest version, test, reinstall and restart |
| `taptune setup-wifi` | Show the `TapTune-Setup` password (and QR code if available) |
| `taptune reset` | Make the Pi like new (see below) |

`taptune update` backs up `.env` and the tag database to `data/backups/` (last
10 kept) before updating. Expected output from passing tests is hidden; failing
tests still show their details. If a step fails, the update stops and says which
one; nothing is rolled back. To restore the tag database from a backup:

```bash
sudo systemctl stop raspi-spotify-nfc.service
cp data/backups/tags.<date>.db.bak data/raspi_spotify_nfc.db
taptune restart
```

### Reset for a new owner or place

```bash
taptune reset
```

After you type `reset`, it backs up `.env` and the tags, signs the Pi out of
Spotify, forgets the speaker and every saved Wi-Fi, and reopens the setup page.
**Tags are kept.** About a minute later the `TapTune-Setup` Wi-Fi appears: set
the Pi up again from a phone. (Over Ethernet, open `http://taptune.local/setup`.)

## Settings (`.env`)

If you need to change an advanced setting, edit `.env` in the TapTune folder,
then run `./install.sh --configure` to apply it.
Never copy `.env.example` over an existing `.env`.

| Setting | Default | Meaning |
| --- | --- | --- |
| `BLUETOOTH_SPEAKER_MAC` | empty | Speaker address (the setup page can set it) |
| `SPOTIFY_DEVICE_NAME` | `TapTune` | Name shown in Spotify → Devices |
| `SPOTIFY_INITIAL_VOLUME` | `10` | Volume (%) set at startup |
| `READY_SOUND_ENABLED` | `true` | `false` turns off the startup chime |
| `APP_PORT` | `5000` | Second address port; keep it different from 80 |
| `TAPTUNE_HTTP_PORT_80` | on | `false` turns off the short `http://taptune.local/` address |
| `TAPTUNE_WIFI_SETUP` | on | `false` turns off the `TapTune-Setup` Wi-Fi |
| `SETUP_SKIP` | `false` | `true` hides the first-run setup page |
| `DATABASE_PATH` | `./data/raspi_spotify_nfc.db` | Where tags are stored |

## Under the hood

- go-librespot is downloaded from GitHub at a pinned version (SHA-256 checked)
  to `/usr/local/bin/go-librespot`. Its settings, `~/.config/go-librespot/config.yml`,
  are rewritten on each install; change `.env` instead. Its sign-in is saved in
  `~/.config/go-librespot/state.json`.
- It runs as the user service `taptune-go-librespot.service`
  (`journalctl --user -u taptune-go-librespot.service`); TapTune runs as the
  system service `raspi-spotify-nfc.service`. Both start without a login.
  Audio goes go-librespot → PipeWire → Bluetooth speaker.
- TapTune talks to go-librespot on `127.0.0.1:3678` only. Spotify apps find the
  Pi through mDNS (Avahi), so phone and Pi must be on the same network.
- `curl http://127.0.0.1:5000/health` checks the web app answers;
  `/ready` also checks settings and the reader.
