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

## Install

TapTune requires Raspberry Pi OS Lite and Spotify Premium.
Follow the [Raspberry Pi installation guide](docs/raspberry-pi-service.md) from
wiring the reader to pairing the speaker and writing your first tag.

## What it does

- **Music page**: choose **Recently played**, **Music**, or **Podcasts**. Browse
  albums and playlists or paste a Spotify share link, then write a tag with
  the Pi's reader. No Spotify developer account.
- **Control tags**: play/pause, next song, volume +10 / −10.
- **Setup page** (`/setup`): Wi-Fi, speaker and Spotify status; pair a new speaker.
- **TapTune-Setup Wi-Fi**: move the Pi to a new network from a phone.
- **Activity log** (`/logs`): what happened, plus update, restart, power off and
  diagnostic logs from the browser.
- Quiet by design: starts at 10% volume and never starts music by itself.

## Contributing

Run the tests with `python3 -m unittest discover -s tests -q`. See
[How TapTune works](docs/architecture.md). The website in `docs/` is published
with GitHub Pages from the `master` branch, `/docs` folder.
