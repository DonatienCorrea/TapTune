# Using and assigning tags

[Documentation index](README.md)

TapTune reads supported NDEF content on Type 2 tags first, or uses a tag's UID
to look up its saved Spotify value or action in SQLite.

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
3. Enter the complete UID exactly as printed, for example `04A7B2F1`.
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

The PN532 reads NDEF memory on Type 2 tags (such as NTAG21x). A text record
containing `action:volume_up` or `action:volume_down` works without a UID mapping.
Blank tags, unsupported values and failed memory reads fall back to UID lookup.
TapTune does not write tags.

Decoding lives in `app/ndef.py` and is tested without reader hardware.
