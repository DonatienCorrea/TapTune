# TapTune documentation

[Project overview](../README.md) · [Public website](https://donatiencorrea.github.io/TapTune/) · [Site en français](fr/)

**Building a Pi player? Start with the [installation checklist](raspberry-pi-service.md).**
It is the single start-to-finish route: `install.sh` prepares Python, you complete
the physical/account steps, and `install.sh --configure` installs the services.
Raspberry Pi OS Lite is the shortest supported route; Desktop has extra audio
prerequisites. No need to read every reference below before starting.

## Discover

- [Architecture and signal path](architecture.md) — what happens after a tag is tapped, which components are involved, and where the current boundaries are.
- [Using tags](tag-usage.md) — supported Spotify values, control actions, assignment, simulation, and the current NDEF behavior.

## Try without hardware

- [Getting started](getting-started.md) — run TapTune in fake mode on a computer and test the complete software path before buying or wiring hardware.

## Build the physical player

The checklist links to these focused references at the point they are needed:

1. [Hardware setup](hardware-setup.md) — configure I2C, wire the PN532 safely, and read the first physical card.
2. [Spotify authorization](spotify-authorization.md) — create TapTune's Web API refresh token (separate from the receiver login).
3. **Speaker setup** (choose by audio stack, not Pi model):
   - [BlueALSA + Raspotify speaker setup](speaker-setup.md) — pairing and the receiver's one-time Spotify login.
   - [PipeWire desktop setup](speaker-setup-desktop.md) — for Bookworm/Trixie Desktop environments.

[Spotifyd source build](spotifyd-setup.md) is an **advanced, optional**
binary-install reference for Desktop, not a third audio setup or required
step on Lite. Do not combine the Lite and Desktop receiver services.

## Maintain and repair

- [Troubleshooting](troubleshooting.md) — symptom-based checks for the web service, Spotify, I2C, the PN532, and tag assignments.
- [Raspberry Pi service](raspberry-pi-service.md#safe-updates) — back up, update, test, and restart a deployed installation safely.
- [Service boundaries](architecture.md#why-not-one-service) — what was merged and why the receiver and OS audio remain separate.
