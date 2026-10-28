# Using and assigning tags

[Documentation index](README.md)

TapTune can write a Spotify link onto a tag, or map its UID to a Spotify value or
playback action in SQLite. A supported link stored on the tag takes priority
over a UID mapping.

## Browse Spotify and write a tag

1. Complete [Spotify authorization](spotify-authorization.md), including the
   library, playlist and recently played permissions. Existing playback-only
   tokens must be re-authorized.
2. Connect the PN532, set `NFC_READER_ENABLED=true`, and start TapTune with
   `python -m app.main` or the installed systemd service. Do not run a second
   NFC diagnostic or writer process at the same time.
3. Open `http://<pi-ip>:5000/` on your iPhone or another device on the same network.
4. Under **1. Choose your music**, browse **My albums**, **My playlists**, or **Recent albums**, or select **Search Spotify** to search
   Spotify for albums, playlists or tracks. **Load more** fetches another page.
   Recent albums are derived from recently played tracks, deduplicated within
   each page in listening order; they are not Spotify's album-history feed.
5. Choose music. Under **2. Write your tag**, check the selection and choose **Start writing**.
   **This replaces the tag's existing content.**
6. Place one unlocked **NTAG213/215/216**, **supported Feiju 144-byte Type 2 tag**, or **writable NFC Type 4 NDEF tag** on the **Pi's reader** within
   60 seconds. Leave it in place until the page reports **written and verified**.
7. Remove the tag, then present it again to play the music.

Safari does not need NFC access: the Pi performs the write. Saving the page to
the iPhone's home screen is optional. The tag contains a standard NDEF Spotify
HTTPS link, so it is self-describing and does not need a UID mapping on this Pi.
No database assignment is created by writing. Under **Spotify link and advanced
options**, **Fill the advanced form with this music** opens the manual form
and fills its URI and label when a UID mapping is preferred. Manual setup,
playback shortcuts and the list of manual assignments are collapsed under
**Advanced: manual tag setup & playback shortcuts**; they are not part of the
normal two-step writing flow.

The connection panel distinguishes **Demo preview** from a real Spotify
connection. TapTune automatically reuses the Spotify credentials and refresh
token already saved in the `.env` of the device running it. You do not need to
copy a token into the browser. A preview on another computer cannot access the
Pi's token: open the Pi's page for its account and reader. If Spotify denies
access to a collection, the page explains which permission may be missing
instead of replacing your library with demo music. Only authorize again when
the saved connection is rejected or lacks the required permissions.

During a pending write, scans are consumed by the writer rather than playback.
Only one write can wait at a time, including across browser tabs. The page
restores a pending job when reloaded. **Cancel write** or the 60-second timeout
ends the request; **closing the browser alone does not cancel it**. The tag
must be removed before normal playback scanning resumes. **Check reader**
refreshes the state after a lost connection.

Locked, password-protected, unsupported or undersized tags report an error;
TapTune does not unlock or format them. Only Type 2 user-memory pages or the
Type 4 NDEF file are written, never the UID, capability container, lock or configuration pages. Interrupted
writes can leave an incomplete tag: retry the write before using it. A
successful write is confirmed by reading the link back, not just by an NFC
acknowledgment.

Feiju Type 2 compatibility is restricted to the observed version response
`00 00 53 04 02 01 00 0F 03`, capability container `E1 10 12 00`, and initial
Lock Control TLV `01 03 A0 0C 34`. This matches the 144-byte F8213-style
layout; it is not blanket support for every chip with manufacturer ID `53`.
The writer checks static and dynamic lock bytes, preserves that TLV, and
writes only pages 5 through 39. The five metadata bytes count against capacity.
UID, capability container, lock and configuration pages are never written.
The [manufacturer's F8213 description](http://www.nfc-ic.com/RFIDNFC_productDetailed?product_id=14)
specifies 45 four-byte pages, 144 user bytes, and static/dynamic locking.
Physical compatibility still needs confirmation on the actual tag.

Type 2 playback and verification read four pages per command, with a 20 ms
pause before each transfer, rather than issuing overlapping reads for every
page. Feiju page writes also have a conservative 20 ms pause; write failures
log the page and PN532 status. A failed verification still reports an error,
even if every write was acknowledged. A Pi diagnostic confirmed matching
content with these four-page reads; the integrated write flow still requires
hardware confirmation.

Type 2 page writes returning PN532 RF protocol error `0x0B` get at most three
attempts per page. Before each retry, TapTune waits 100 ms and reselects the
same UID; a missing or different tag stops the write. It resends only the same
four bytes to the same user page. Other statuses, malformed responses and
transport exceptions are not retried. Exhausted retries report failure, and
full UID/content verification remains required before success. Type 4 writes
are unchanged.

For Type 4, TapTune selects the NFC Forum NDEF application and reads its
capability container before writing. It requires a freely readable and writable
standard NDEF file with a two-byte length, at most 32767 bytes including that
length, under the NDEF application `D2760000850101` (mapping versions 1 or 2).
Transfers use bounded short APDUs and respect the tag's advertised
read/write limits. Extended NDEF files, protected files and unformatted tags
are rejected; no application or file is created. **ISO 14443-4 alone does not
guarantee NDEF support.** The NDEF length is cleared before the content changes,
published last, then the UID and entire message are read back before success.
Remove and tap the tag again to confirm playback. Hardware compatibility
must still be checked on the actual tag and Pi.

Without Spotify credentials, the picker shows explicitly labelled **demo**
content for hardware-free UI testing, not your real library. Without a ready
reader, browsing and manual assignments still work but writing is disabled.
The Pi page has no login: keep it on a trusted local network and do not
port-forward it to the internet.

## Supported values

Content:

```text
spotify:track:<id>
spotify:playlist:<id>
spotify:album:<id>
```

Controls:

```text
action:play_pause
action:next
action:next_track
action:volume_up
action:volume_down
```

`action:next` and `action:next_track` are equivalent.

`action:volume_up` adds **10 percentage points** (30% becomes 40%);
`action:volume_down` subtracts 10 points. Volume is clamped to 0–100%.
Assign two tags using the **Volume +10%** and **Volume -10%** quick-fill buttons.
These controls do not start music. They adjust the current Spotify device, or
the configured Pi receiver when there is no current playback. If Spotify cannot
read or control the device's volume, TapTune reports an error rather than
guessing a value.

TapTune sets its own receiver to **30% when the app starts**, once the receiver
appears on Spotify Connect. Set `SPOTIFY_INITIAL_VOLUME=30` in `.env` to make this
explicit. It does not reset another active device's volume or reset the volume
on every tap. For Spotifyd, also use `initial_volume = 30` in its `[global]`
configuration so the receiver starts safely even before TapTune reaches it.

When `BLUETOOTH_SPEAKER_MAC` is configured, **local music start/resume** checks
the Bluetooth connection and may reconnect if necessary. An unreachable
speaker produces `bluetooth_not_ready`; turn it on and tap a music/start tag
again. Pause and volume taps never reconnect, nor do fake mode or commands
directed to another active Spotify device. After one bounded boot phase,
there is no periodic reconnection, keepalive or repeated chime.

## Assign the first tag

Before assigning a physical tag, complete the [first-card test](hardware-setup.md#read-the-first-card) and copy the full UID printed by the diagnostic.

1. Start TapTune with `NFC_READER_ENABLED=false`.
2. Open `http://127.0.0.1:5000/`, or `http://<pi-ip>:5000/` from another device on the same network.
3. Open **Advanced: manual tag setup & playback shortcuts** and enter the complete UID exactly as printed, for example `04A7B2F1`.
4. Enter one supported value.
5. Optionally add a friendly label.
6. Select **Save tag** and confirm that the row appears under **Assigned tags**.
7. Verify the saved mapping explicitly:

   ```bash
   curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
   ```

8. Stop TapTune, set `NFC_READER_ENABLED=true` in `.env`, and restart it.

A physical tap now dispatches the saved mapping. Keep the card away from the antenna until startup finishes, and remove it between taps. The loop dispatches once per presentation rather than repeatedly while a card is held in place.

## Simulate a tag

Simulation is useful before the reader is connected:

```bash
python -m app.simulate \
  --uid 01AABBCC \
  --payload 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'
```

The command validates and saves the mapping, records an event, dispatches it, and prints the result.

## Spotify links and URIs

The NDEF decoder recognizes both direct Spotify URIs and supported Spotify share links. For example:

```text
https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=…
```

is normalized to:

```text
spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
```

Tracking parameters and a Spotify locale segment are removed.

## Self-describing NDEF tags

TapTune's software decoder supports NDEF URI and text records that contain their own Spotify value. A tag can be prepared with NFC Tools or another phone app that writes NDEF.

When NDEF bytes are supplied to the decoder:

1. a supported NDEF value wins;
2. a blank or unsupported value falls back to the registered UID mapping; and
3. if no mapping exists, the raw UID remains the final fallback.

The PN532 reads NDEF memory on Type 2 tags (such as NTAG21x) and standard NFC Type 4 NDEF tags. A text record
containing `action:volume_up` or `action:volume_down` works without a UID mapping.
Blank tags, unsupported values and failed memory reads fall back to UID lookup.
The web music picker writes Spotify links onto unlocked NTAG213/215/216, supported Feiju 144-byte Type 2 tags, and supported writable Type 4 NDEF tags
through the Pi's PN532. Playback shortcuts can still be assigned by UID or
written as NDEF text records using a phone app.

Decoding lives in `app/ndef.py` and is tested without reader hardware.
