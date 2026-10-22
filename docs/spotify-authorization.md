# Spotify authorization for TapTune

[Documentation index](README.md)

TapTune needs a Spotify client ID, client secret, and refresh token to control playback. This guide creates the refresh token with a one-time local Python script. A Spotify Premium account is required for playback control.

## 1. Create and configure a Spotify app

1. Sign in to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
2. Select **Create app**.
3. Enter a name such as `TapTune` and a short description.
4. Add this redirect URI:

   ```text
   http://127.0.0.1:8888/callback
   ```

5. Accept Spotify's terms and create the app.
6. Open **Settings**, copy the client ID, and select **View client secret** to reveal the client secret.

The redirect URI in Spotify and TapTune must match exactly. Spotify permits plain HTTP for an explicit loopback IP address such as `127.0.0.1`; do not replace it with `localhost`.

## 2. Prepare TapTune

From the TapTune repository:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Skip the `cp` command if `.env` already exists. Add the Spotify app credentials to `.env`:

```dotenv
SPOTIFY_CLIENT_ID=your_client_id
SPOTIFY_CLIENT_SECRET=your_client_secret
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
SPOTIFY_REFRESH_TOKEN=
```

Do not add quotes or spaces around the values.

## 3. Create the one-time script

Create `get_spotify_token.py` in the repository root with this content:

```python
import os
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from spotipy.cache_handler import MemoryCacheHandler
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

required_variables = (
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
    "SPOTIFY_REDIRECT_URI",
)
missing_variables = [name for name in required_variables if not os.getenv(name)]
if missing_variables:
    raise SystemExit(
        "Missing required values in .env: " + ", ".join(missing_variables)
    )

state = secrets.token_urlsafe(24)
oauth = SpotifyOAuth(
    client_id=os.environ["SPOTIFY_CLIENT_ID"],
    client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
    redirect_uri=os.environ["SPOTIFY_REDIRECT_URI"],
    scope=(
        "user-modify-playback-state user-read-playback-state "
        "user-library-read playlist-read-private playlist-read-collaborative "
        "user-read-recently-played"
    ),
    state=state,
    open_browser=False,
    cache_handler=MemoryCacheHandler(),
)
result = {}


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parameters = parse_qs(urlparse(self.path).query)

        if parameters.get("state", [None])[0] != state:
            self.send_response(400)
            message = b"Invalid OAuth state."
        elif "error" in parameters:
            result["error"] = parameters["error"][0]
            self.send_response(400)
            message = b"Spotify authorization failed."
        elif "code" not in parameters:
            self.send_response(400)
            message = b"Authorization code is missing."
        else:
            result["code"] = parameters["code"][0]
            self.send_response(200)
            message = b"Authorization complete. You can close this window."

        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(message)

    def log_message(self, format, *args):
        pass


authorization_url = oauth.get_authorize_url()
server = HTTPServer(("127.0.0.1", 8888), CallbackHandler)
print("Opening Spotify authorization in your browser...")
if not webbrowser.open(authorization_url):
    print(f"Open this URL manually:\n{authorization_url}")

server.handle_request()
server.server_close()

if "error" in result:
    raise SystemExit(f"Spotify authorization failed: {result['error']}")
if "code" not in result:
    raise SystemExit("Spotify did not return an authorization code.")

token = oauth.get_access_token(result["code"], check_cache=False)
refresh_token = token.get("refresh_token")
if not refresh_token:
    raise SystemExit("Spotify did not return a refresh token.")

print("\nCopy this refresh token into SPOTIFY_REFRESH_TOKEN in .env:\n")
print(refresh_token)
```

The script keeps token data in memory instead of writing a Spotipy cache file.

These permissions cover playback, saved albums, private/collaborative playlists,
and listening history for the web music picker. **If you previously authorized
TapTune for playback only, run this script again**, replace
`SPOTIFY_REFRESH_TOKEN`, and restart TapTune. Refreshing an old token does not
grant the additional permissions. Use the same Spotify account as the speaker.
Credentials and access tokens stay on the Pi; the browser receives music
metadata, not Spotify tokens.

## 4. Authorize the account

If you are setting up the Pi over SSH, open the SSH session with a local port
forward **from your computer** (replace `<user>` and `<pi-ip>`):

```bash
ssh -L 8888:127.0.0.1:8888 <user>@<pi-ip>
```

Run the script on the Pi in that session, then open its printed authorization
URL in your computer's browser. The callback to `127.0.0.1:8888` is forwarded to
the Pi. Without this tunnel, a browser on your computer cannot reach the Pi's
loopback callback. On the Pi itself with a desktop browser, no tunnel is needed.

Run:

```bash
python get_spotify_token.py
```

Spotify opens in your browser. Sign in with the Premium account TapTune should control, review the requested permissions, and approve access. The browser then shows that authorization is complete, and the terminal prints the refresh token.

Copy the complete token into `.env`:

```dotenv
SPOTIFY_REFRESH_TOKEN=your_refresh_token
```

Treat the refresh token like a password. Do not commit `.env`, paste the token into an issue, or include it in logs.

## 5. Remove the script and test playback

The script is no longer needed after the token has been copied:

```bash
rm get_spotify_token.py
python -m app.main
```

TapTune needs a Spotify Connect device to play on. For a first test, open Spotify on a phone or computer using the same account and start playback once. To play on the Pi without a phone, complete [Lite speaker setup](speaker-setup.md) or [Desktop/PipeWire setup](speaker-setup-desktop.md). The receiver has its own login, separate from this refresh token. In another terminal, activate the virtual environment and test TapTune:

```bash
source .venv/bin/activate
python -m app.simulate \
  --uid 01AABBCC \
  --payload 'spotify:track:4cOdK2wGLETKBW3PvgPWqT'
```

A successful result reports `"status": "ok"` and `"mode": "spotify"`. If the result reports `"mode": "fake"`, stop TapTune and confirm that all three credential values in `.env` are non-empty before restarting it.

## Troubleshooting

| Problem | Check |
| --- | --- |
| Spotify reports an invalid redirect URI | Confirm the dashboard and `.env` both use exactly `http://127.0.0.1:8888/callback`. |
| The callback page does not load | Confirm no other process is using port `8888`, then run the script again. |
| The browser does not open | Copy the authorization URL printed in the terminal into a browser. |
| Spotify returns no active device or `speaker_not_ready` | Complete [Speaker setup](speaker-setup.md), or open Spotify on the target device, play something once, and retry. |
| TapTune still uses fake mode | Confirm the client ID, client secret, and refresh token are all present, then restart TapTune. |
| Authorization was granted to the wrong account | Run the script again in a private browser window and sign in with the intended account. |
| The music picker reports missing permissions | Re-authorize with all the scopes above, replace the Pi's refresh token, and restart TapTune. |
| The music picker shows a demo library | One or more Spotify credentials are missing. Configure all three values and restart TapTune. |
