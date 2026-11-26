# Install TapTune on a Raspberry Pi

[Documentation index](README.md) · [Wi-Fi en français](fr/wi-fi.md)

One path, start to finish: **Raspberry Pi OS Lite + the setup page**. TapTune runs
without a screen; once installed, everything is done from a phone.

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

Start the Pi, then connect from a computer on the same Wi-Fi: `ssh <user>@taptune.local`.

## 2. Download TapTune

Install the required system packages with `sudo`:

```bash
sudo apt update
sudo apt install -y git python3-venv sqlite3
```

Then download TapTune and run its installer as your normal user (without `sudo`):

```bash
cd ~
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
./install.sh
```

This prepares TapTune and creates a private `.env` settings file. It starts nothing.
`./install.sh --help` lists the options.

## 3. Connect the reader

Follow [Hardware setup](hardware-setup.md) to wire the PN532 and read a first tag.
TapTune finds the reader by itself; nothing to set.

## 4. Install the services

```bash
./install.sh --configure
```

This installs the Spotify receiver (go-librespot), PipeWire audio, the TapTune
service and the `taptune` command. It asks for your password (`sudo`) only for
system changes. It also prints the `TapTune-Setup` Wi-Fi QR code and password:
keep them private (see [Move to another Wi-Fi](#move-to-another-wi-fi)).

## 5. Speaker and Spotify (web setup)

Open `http://taptune.local/setup` on a phone on the **same Wi-Fi**:

- **Bluetooth speaker**: put the speaker in pairing mode, tap
  **Search for speakers** and choose it.
- **Spotify**: in the Spotify app, tap **Devices** and choose **TapTune**.
  TapTune never asks for your Spotify password and stays signed in after restarts.

Each step turns to *done* by itself.

## 6. Write your first tag

Open `http://taptune.local/`, choose music and write it to a tag
([Using tags](tag-usage.md)). Then reboot with the speaker on: wait for the short
chime and tap the tag. Sound should come from the speaker.

If `http://taptune.local/` doesn't answer, use `http://taptune.local:5000/` or
`http://<pi-ip>:5000/`.

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

## The setup page

`http://taptune.local/setup` (French: `/fr/setup`) shows the status of Wi-Fi,
the speaker and Spotify. Until all three have been done once, the home page
opens the setup page instead. Under **Bluetooth speaker**, **Change speaker** →
**Search for speakers** pairs a new speaker and saves it; **Play a test sound**
checks it.

## Move to another Wi-Fi

If the Pi finds no known network about 60 seconds after starting, it opens its
own Wi-Fi called **TapTune-Setup** (password-protected, unique to this Pi).

1. Before moving the Pi, run `taptune setup-wifi` to show its QR code and password.
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
- **Restart TapTune** and **Restart the Pi**;
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
| `taptune setup-wifi` | Show the `TapTune-Setup` QR code and password |
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

Edit `.env` in the TapTune folder, then run `./install.sh --configure` again.
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
