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
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python -m unittest discover -s tests -v
python -m app.main
```

Open `http://127.0.0.1:5000/` in a browser. Stop the server with `Ctrl-C`.

The example environment deliberately leaves `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, and `SPOTIFY_REFRESH_TOKEN` empty. If any one of those values is blank, TapTune uses its in-memory fake Spotify client and does not contact Spotify.

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
5. prints a result containing `"mode": "fake"`.

The simulator runs as its own command; it does not call the Flask server. The health request verifies the server, while the simulator verifies mapping and dispatch. Both should succeed before adding Spotify or hardware.

The default database is `data/raspi_spotify_nfc.db`. It is ignored by Git.

## Next steps

- Learn which values a tag can trigger in [Using tags](tag-usage.md).
- Connect live playback with [Spotify authorization](spotify-authorization.md).
- Prepare the physical reader with [Hardware setup](hardware-setup.md).
- Install the long-running Pi service with [Raspberry Pi service](raspberry-pi-service.md).
