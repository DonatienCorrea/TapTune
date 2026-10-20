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

The service runs on Raspberry Pi OS with a PN532 reader over I2C. A local Flask web UI assigns tag UIDs, SQLite persists mappings, and systemd keeps the service running. Playback uses a shared Spotify Premium account and Spotify Connect; Raspotify/BlueALSA on Lite or Spotifyd/PipeWire on Desktop makes the Pi its own Bluetooth speaker receiver without login. Boot prepares the receiver; a tag starts music. One bounded boot connection/chime is followed by no periodic Bluetooth reconnect; only local music start/resume taps may reconnect, never pause or volume. Reader polling is disabled by default for hardware-free setup and joins the service dispatch loop when `NFC_READER_ENABLED=true`.

## Capabilities and Constraints

Supports Spotify playlist, album, and track URIs plus play/pause, next and volume actions. Reads supported NDEF values from Type 2 tags before falling back to UID assignments. Includes fake mode and a CLI simulator. The app owns startup connection/readiness and one chime; Desktop uses the dedicated audio user's PipeWire session, not a separate sound service. There are no status LEDs, and other errors are logged and inspected over SSH. Hardware-specific dependencies are separate from base development dependencies. One guided installer prepares Python and then explicitly configures live services after manual wiring, pairing and authorization; Lite is the shortest standalone route.

## Brand Commitments

The name TapTune and the vocabulary of tags, taps, playback, and home-built hardware are established.

## Evidence on Hand

The repository README, Python application modules, SQLite schema, systemd service file, and docs page are the source of truth. No customer stories, benchmarks, or product photography are available; do not invent them.

## Product Principles

- Make the first action physical and understandable.
- Keep the local system inspectable and maintainable.
- Separate hardware concerns from playback and storage.
- Let makers test the full flow before wiring hardware.
