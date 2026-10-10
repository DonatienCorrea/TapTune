# TapTune documentation

[Project overview](../README.md) · [Public website](https://donatiencorrea.github.io/TapTune/) · [Site en français](fr/)

Use the path that matches what you are trying to do. You do not need to read the guides in repository order.

## Discover

- [Architecture and signal path](architecture.md) — what happens after a tag is tapped, which components are involved, and where the current boundaries are.
- [Using tags](tag-usage.md) — supported Spotify values, control actions, assignment, simulation, and the current NDEF behavior.

## Try without hardware

- [Getting started](getting-started.md) — run TapTune in fake mode on a computer and test the complete software path before buying or wiring hardware.

## Build the physical player

1. [Hardware setup](hardware-setup.md) — configure I2C, wire the PN532 safely, and read the first physical card.
2. [Spotify authorization](spotify-authorization.md) — create the refresh token used for live playback.
3. [Raspberry Pi service](raspberry-pi-service.md) — install TapTune on the Pi, enable the reader, and operate the service.
4. [Speaker setup](speaker-setup.md) — make the Pi its own Spotify speaker with a Bluetooth speaker (Lite/BlueALSA).
   For Debian 13 Desktop, use the [PipeWire desktop setup](speaker-setup-desktop.md).

## Maintain and repair

- [Troubleshooting](troubleshooting.md) — symptom-based checks for the web service, Spotify, I2C, the PN532, and tag assignments.
- [Raspberry Pi service](raspberry-pi-service.md#safe-updates) — back up, update, test, and restart a deployed installation safely.
