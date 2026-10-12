# TapTune documentation

[Project overview](../README.md) · [Public website](https://donatiencorrea.github.io/TapTune/) · [Site en français](fr/)

Use the path that matches what you are trying to do. You do not need to read the guides in repository order.

## Discover

- [Architecture and signal path](architecture.md) — what happens after a tag is tapped, which components are involved, and where the current boundaries are.
- [Using tags](tag-usage.md) — supported Spotify values, control actions, assignment, simulation, and the current NDEF behavior.

## Try without hardware

- [Getting started](getting-started.md) — run TapTune in fake mode on a computer and test the complete software path before buying or wiring hardware.

## Build the physical player

Start with [Raspberry Pi service](raspberry-pi-service.md), the fresh-install
checklist. It prepares the checkout and virtual environment before linking to
hardware, account authorization and **one** speaker path:

1. [Hardware setup](hardware-setup.md) — configure I2C, wire the PN532 safely, and read the first physical card.
2. [Spotify authorization](spotify-authorization.md) — create TapTune's Web API refresh token (separate from the receiver login).
3. **Speaker setup** (choose by audio stack, not Pi model):
   - [BlueALSA + Raspotify speaker setup](speaker-setup.md) — install the managed Raspotify package with Bluetooth speaker auto-connect (Lite/BlueALSA).
   - [PipeWire desktop setup](speaker-setup-desktop.md) — for Bookworm/Trixie Desktop environments.

[Spotifyd source build](spotifyd-setup.md) is an optional way to obtain the
binary for the Desktop path, not a third audio setup. Do not combine the Lite
and Desktop receiver services.

## Maintain and repair

- [Troubleshooting](troubleshooting.md) — symptom-based checks for the web service, Spotify, I2C, the PN532, and tag assignments.
- [Raspberry Pi service](raspberry-pi-service.md#safe-updates) — back up, update, test, and restart a deployed installation safely.
