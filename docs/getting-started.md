# Getting started without hardware

[Documentation index](README.md)

Fake mode is the recommended first experience. It verifies the database, tag-assignment page, simulator, and playback dispatch without requiring a Raspberry Pi, NFC reader, Spotify account, or physical tag.

## Requirements

- Python 3.10 or newer;
- `python3` and virtual-environment support;
- Git; and
- network access to install packages from `requirements.txt`.

## Install and run

```bash
git clone https://github.com/DonatienCorrea/TapTune.git
cd TapTune
./install.sh --app-only
.venv/bin/python -m app.main
```

Open `http://127.0.0.1:5000/` in a browser. Stop the server with `Ctrl-C`.

Preparation does not install or start system services. The example environment
leaves `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REFRESH_TOKEN`
empty. If any one is blank, TapTune uses its fake Spotify client.

The installer reuses `.venv` and never overwrites `.env`. If you already have live
credentials, use a separate clone for fake experiments, or explicitly override
the live client and reader **for this process only**:

```bash
SPOTIFY_CLIENT_ID= NFC_READER_ENABLED=false .venv/bin/python -m app.main
```

Use the same overrides on simulator commands when testing an existing live
checkout. Fake mode still writes mappings to the configured SQLite database;
use a separate clone if you must preserve deployed tag assignments. The web UI
is unauthenticated; keep it on a trusted network, never expose port 5000 to the
internet. For a computer-only run, prefix the command with `APP_HOST=127.0.0.1`.

## Verify the service

With `python -m app.main` running:

```bash
curl http://127.0.0.1:5000/health
```

The response should look like:

```json
{"app":"TapTune","status":"ok"}
```

The health endpoint confirms that the Flask process responds. It does not validate Spotify, the PN532, I2C, the reader thread, or database contents.

## Simulate taps

In a second terminal:

```bash
source .venv/bin/activate
python -m app.simulate --uid 01AABBCC --payload 'spotify:playlist:37i9dQZF1DXcBWIGoYBM5M'
python -m app.simulate --uid 02AABBCC --payload 'action:play_pause'
python -m app.simulate --uid 03AABBCC --payload 'action:next'
```

The simulator:

1. validates the supplied value;
2. saves or updates its UID mapping;
3. records an event;
4. sends the value through the same dispatch service used by a real tap; and
5. prints a Python dictionary whose nested `result` contains `'status': 'ok'`
   and `'mode': 'fake'` (not a JSON response).

The simulator runs as its own command; it does not call the Flask server. The health request verifies the server, while the simulator verifies mapping and dispatch. Both should succeed before adding Spotify or hardware.

The default database is `data/raspi_spotify_nfc.db`. It is ignored by Git.

## Next steps

- Learn which values a tag can trigger in [Using tags](tag-usage.md).
- Connect live playback with [Spotify authorization](spotify-authorization.md).
- Prepare the physical reader with [Hardware setup](hardware-setup.md).
- Install the long-running Pi service with [Raspberry Pi service](raspberry-pi-service.md).

## Reaching TapTune from your phone

TapTune enables Avahi (mDNS) when the service is installed. On Lite and Desktop, open `http://<hostname>.local/setup` from the same network. [Set the hostname and Wi-Fi in Raspberry Pi Imager](raspberry-pi-service.md#set-wi-fi-in-raspberry-pi-imager); if you chose `taptune`, open `http://taptune.local/setup`. Existing installations keep their hostname (run `hostname` on the Pi). The installer never changes the hostname or `/etc/hosts`.

If port 80 is unavailable, or you installed in app-only mode, use `http://<hostname>.local:5000/setup` (substitute `APP_PORT` if changed).

The setup page on the local network shows live Wi-Fi, speaker and Spotify status. The home page only redirects to setup on a first run; installations whose `.env` already has the speaker and Spotify credentials, or that completed setup once, keep their home page even when the speaker is off or the network drops. To move an installed Pi without a keyboard or Ethernet cable, use the separate [TapTune-Setup hotspot](raspberry-pi-service.md#move-taptune-to-a-different-wi-fi-network). The Wi-Fi form is not available on the local network.
