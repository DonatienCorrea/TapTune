# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Households using a screen-free music player, and the (often non-technical) person who sets it up from a phone. Makers and developers build and extend it.

## Product Purpose

TapTune turns physical NFC tags into a simple music interface: tap a tag to play a Spotify playlist, album, track or podcast, or tap a control tag to pause or skip. Success means a household can use music without opening a phone while the maker can still inspect and maintain the system locally.

## Positioning

The project makes Spotify playback tangible by connecting inexpensive, programmable physical tags to a local Raspberry Pi service.

## Operating Context

A headless Raspberry Pi running Raspberry Pi OS Lite, with a PN532 reader over I2C and a Bluetooth speaker. TapTune is a local Flask service; go-librespot is the Spotify Connect receiver (signed in by choosing TapTune once in the Spotify app, no developer credentials) and plays through PipeWire. SQLite stores tag assignments and the activity log. Boot prepares the receiver at 10% volume and plays one chime; it never starts music. Only music taps reconnect the speaker. Transient failures are retried automatically.

## Capabilities and Constraints

Tags play Spotify albums, playlists, tracks and podcast shows (newest episode), or play/pause, next and volume ±10 actions. The bilingual, mobile-friendly local page offers saved albums, saved playlists, What's playing, TapTune history and pasted Spotify links (previewed without login; searching opens Spotify in a new tab). Selections are written as verified NDEF links to supported tags with the Pi's PN532, not the phone's NFC. A first-run setup page covers Wi-Fi, speaker pairing and Spotify sign-in; a protected TapTune-Setup hotspot moves the Pi to a new network. Without a screen, the Activity log page shows what happened and offers update, restart, reboot and diagnostic-log download. There is no in-app search, no fake/demo mode and no authentication: the Pi belongs on a trusted home network.

## Brand Commitments

The name TapTune and the vocabulary of tags, taps, playback, and home-built hardware are established.

## Evidence on Hand

The repository README, Python application modules, SQLite schema, systemd service file, and docs page are the source of truth. No customer stories, benchmarks, or product photography are available; do not invent them.

## Product Principles

- Make the first action physical and understandable.
- Keep the local system inspectable and maintainable.
- Separate hardware concerns from playback and storage.
- Keep setup and maintenance possible from a phone, without a screen or terminal.
