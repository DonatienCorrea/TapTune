# TapTune

**Tap a physical object. Start the music.**

TapTune turns a Raspberry Pi, an NFC reader and a Bluetooth speaker into a
screen-free Spotify player. Tap a tag to play an album, playlist, song or
podcast, or to pause, skip or change the volume.

[Website](https://donatiencorrea.github.io/TapTune/) · [Site en français](https://donatiencorrea.github.io/TapTune/fr/) · [Documentation](docs/README.md)

> [!IMPORTANT]
> TapTune is a do-it-yourself project, not a finished product. Someone has to
> wire the reader and run the installer once; after that, everything is done
> from a phone.

## What you need

- A Raspberry Pi with Wi-Fi, running Raspberry Pi OS Lite
- A PN532 NFC reader and NFC tags (NTAG213/215/216 work best)
- A Bluetooth speaker
- Spotify Premium

## Install

Follow the [installation guide](docs/raspberry-pi-service.md). In short:

```bash
sudo apt update && sudo apt install -y git python3-venv
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
./install.sh
# connect the reader, pair the speaker (see the guide)
./install.sh --configure
```

Then, in Spotify on your phone, tap **Devices** → **TapTune**, and open
`http://taptune.local/` to write your first tag.

## What it does

- **Music page**: pick from your saved albums and playlists, What's playing,
  TapTune history, or paste any Spotify link (album, playlist, song, podcast),
  then write it to a tag with the Pi's reader. No Spotify developer account.
- **Control tags**: play/pause, next song, volume +10 / −10.
- **Setup page** (`/setup`): Wi-Fi, speaker and Spotify status; pair a new speaker.
- **TapTune-Setup Wi-Fi**: move the Pi to a new network from a phone.
- **Activity log** (`/logs`): what happened, plus update, restart and
  diagnostic logs from the browser.
- Quiet by design: starts at 10% volume and never starts music by itself.

## Contributing

Run the tests with `python3 -m unittest discover -s tests -q`. See
[How TapTune works](docs/architecture.md). The website in `docs/` is published
with GitHub Pages from the `master` branch, `/docs` folder.
