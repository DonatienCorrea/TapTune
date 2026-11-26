# Using tags

[Documentation index](README.md)

## Write music to a tag

1. Open `http://taptune.local/` on a phone or computer on the same Wi-Fi.
2. Choose music:
   - **My albums** / **My playlists**: your saved Spotify music (**Load more** for more).
   - **What's playing**: what TapTune is playing right now.
   - **TapTune history**: music already started from tags on this Pi.
   - **Spotify link**: paste a link to an album, playlist, song or podcast.
     To find something new (a podcast, for example), search for it: Spotify
     opens in a new tab. There, use **Share → Copy link** and paste it here.
3. Choose **Write tag**. **This replaces what is on the tag.**
4. Within 60 seconds, place the tag on the **Pi's reader** and leave it until
   the page says **Tag written** and **Verified**.
5. Remove the tag. Tap it again to play.

The Pi does the writing, so this works from any phone, including iPhone.
**Cancel** or the 60-second timeout ends a write; closing the page does not.
Only one write can wait at a time.

## Supported tags

Writing works on unlocked **NTAG213/215/216** (recommended), one Feiju
144-byte Type 2 tag model, and writable NFC Type 4 (NDEF) tags. Locked,
protected or unformatted tags are refused; TapTune never unlocks or formats a
tag. Other tags (for example MIFARE Classic) can still be used with
[manual setup](#manual-setup).

## What a tag can do

| On the tag | Effect |
| --- | --- |
| Album, playlist or song | Plays it |
| Podcast show | Plays its newest episode (looked up at each tap) |
| `action:play_pause` | Pause / resume |
| `action:next` (or `action:next_track`) | Next song |
| `action:volume_up` / `action:volume_down` | Volume +10 / −10 points |

Volume tags never start music. Spotify share links
(`https://open.spotify.com/playlist/…?si=…`) and `spotify:` URIs both work.
Tags written with a phone app (NFC Tools…) as a URL or text record also work.

## Manual setup

For control tags (play/pause, next, volume) or tags TapTune can't write, link
the tag's ID instead:

1. Read the tag's ID with the [reader test](hardware-setup.md#read-a-first-tag).
2. On the music page, open **Manual setup**, enter the ID and a value (or use the
   **Volume +10%** / **Volume -10%** shortcuts), then **Save tag**.

Music written on the tag wins over a manual setup. A blank or unreadable tag
uses its manual setup.

Each tap acts once: lift the tag before tapping again.
