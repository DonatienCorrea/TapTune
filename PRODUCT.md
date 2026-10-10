# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Households and makers building a tactile music player with a Raspberry Pi. Developers and hobbyists also use the page as an installation and architecture reference.

## Product Purpose

TapTune turns physical NFC tags into a simple music interface: tap a tag to play a Spotify playlist, album, or track, or tap a control tag to pause or skip. Success means a household can use music without opening a phone while the maker can still inspect and maintain the system locally.

## Positioning

The project makes Spotify playback tangible by connecting inexpensive, programmable physical tags to a local Raspberry Pi service, with a simulated input path for development without hardware.

## Operating Context

The service runs on Raspberry Pi OS Lite with a PN532 reader over I2C. A local Flask web UI assigns tag UIDs, SQLite persists mappings, and systemd keeps the service running. Playback uses a shared Spotify Premium account and Spotify Connect; raspotify makes the Pi its own Connect speaker through a Bluetooth speaker, so music plays right after boot. Reader polling is disabled by default for hardware-free setup and joins the service dispatch loop when `NFC_READER_ENABLED=true`.

## Capabilities and Constraints

Supports Spotify playlist, album, and track URIs plus play/pause and next actions. Includes fake mode and a CLI simulator. A chime signals readiness after boot; there are no status LEDs, and other errors are logged and inspected over SSH. Hardware-specific dependencies are separate from base development dependencies.

## Brand Commitments

The name TapTune and the vocabulary of tags, taps, playback, and home-built hardware are established.

## Evidence on Hand

The repository README, Python application modules, SQLite schema, systemd service file, and docs page are the source of truth. No customer stories, benchmarks, or product photography are available; do not invent them.

## Product Principles

- Make the first action physical and understandable.
- Keep the local system inspectable and maintainable.
- Separate hardware concerns from playback and storage.
- Let makers test the full flow before wiring hardware.
