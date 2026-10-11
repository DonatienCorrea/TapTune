# Install Spotifyd on Raspberry Pi 5

[Documentation index](README.md)

**Spotifyd** is a lightweight Spotify Connect receiver that makes the Raspberry Pi its own Spotify speaker. This guide builds Spotifyd on your Pi from source, which ensures it runs correctly on recent Raspberry Pi OS versions (Debian Bookworm/Trixie) that use **OpenSSL 3**.

> **Note:** This guide is for **Spotifyd**. If you want to use **Raspotify** (the managed Debian package), follow [Speaker setup](speaker-setup.md) instead. Both provide Spotify Connect; Spotifyd requires manual compilation but gives you more control.

## Prerequisites

- Raspberry Pi 5 with **2+ GB RAM** (the 8 GB model is ideal)
- **Official Raspberry Pi 27 W USB-C power supply** (5.1 V / 5 A minimum)
- Raspberry Pi OS Lite or Desktop
- SSH access or terminal access
- Spotify Premium account

## Why build from source?

The official Spotifyd v0.4.2 prebuilt binaries for `aarch64` depend on **OpenSSL 1.1**, which is no longer available in current Raspberry Pi OS. Building from source uses your system's **OpenSSL 3**, avoiding the `libssl.so.1.1: cannot open shared object file` error.

## 1. Increase swap (required for 2 GB Pi)

Rust compilation is memory-intensive. If your Pi has 2 GB RAM, create additional swap:

```bash
# Create a 4 GB swapfile
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Verify it's active
free -h

# Make it permanent (survive reboot)
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Install build dependencies

```bash
sudo apt update
sudo apt install -y \
  build-essential curl git pkg-config \
  libasound2-dev libssl-dev libpulse-dev libdbus-1-dev \
  cmake libclang-dev
```

## 3. Install Rust

The official Rust toolchain is more recent than the `apt` package. Use `rustup`:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs -o /tmp/rustup-init.sh
sh /tmp/rustup-init.sh -y --profile minimal
. "$HOME/.cargo/env"

rustup update stable
rustc +stable --version
```

## 4. Build Spotifyd v0.4.2

Create a separate directory for the build:

```bash
mkdir -p ~/spotifyd-install
cd ~/spotifyd-install

git clone --depth 1 --branch v0.4.2 \
  https://github.com/Spotifyd/spotifyd.git spotifyd-source

cd spotifyd-source
```

Build with reduced parallelism to avoid memory pressure. This takes 30–45 minutes:

```bash
CARGO_BUILD_JOBS=1 \
RUSTFLAGS="-C codegen-units=1" \
cargo +stable build --release --locked
```

Verify the binary:

```bash
./target/release/spotifyd --version
```

If you see a version number, the build succeeded.

## 5. Install the binary

```bash
sudo install -m 755 target/release/spotifyd /usr/local/bin/spotifyd
spotifyd --version
```

Verify it's using OpenSSL 3, not the old OpenSSL 1.1:

```bash
ldd /usr/local/bin/spotifyd | grep -i ssl
```

You should see:
```
libssl.so.3 => /usr/lib/aarch64-linux-gnu/libssl.so.3 (0x...)
```

**Not** `libssl.so.1.1`.

## 6. Create a Spotifyd config

Create a directory for Spotifyd's configuration and cache:

```bash
mkdir -p ~/.config/spotifyd
nano ~/.config/spotifyd/spotifyd.conf
```

Paste this template for **PulseAudio** (recommended for Raspberry Pi OS with Bluetooth speakers):

```ini
[global]
username = "YOUR_SPOTIFY_USERNAME"
password = "YOUR_SPOTIFY_PASSWORD"
backend = "pulseaudio"
device_name = "Raspberry Pi 5"
bitrate = 320
cache_path = "/home/pi/.cache/spotifyd"
```

Replace `YOUR_SPOTIFY_USERNAME` and `YOUR_SPOTIFY_PASSWORD` with your Spotify account credentials.

> **Why PulseAudio?** Recent Raspberry Pi OS versions (Debian Bookworm/Trixie) use PipeWire with PulseAudio emulation. The `pulseaudio` backend works reliably with Bluetooth speakers and avoids ALSA device conflicts.

> **Security note:** Storing credentials in plain text is acceptable for this use case because the Pi is typically on a private network. For critical installations, use Spotify OAuth instead (see [Spotify authorization](spotify-authorization.md) for the TapTune pattern).

## 7. Test Spotifyd

Run it in the foreground to see startup messages:

```bash
spotifyd --no-daemon
```

Expected output includes:
```
Building connection ...
Connecting ...
Authenticated as '<username>'!
Spotify Connect Device
Registered server ...
```

Open Spotify on your phone or computer. In the device picker (speaker icon), you should see **"Raspberry Pi 5"** as an available device.

Test playback:
1. Start a song on your phone.
2. Open the device list and select **Raspberry Pi 5**.
3. Music should now come from the Pi's Bluetooth speaker.

If it works, press `Ctrl+C` to stop the foreground process.

## 8. Create a systemd service (optional)

To run Spotifyd automatically on boot, create a systemd unit:

```bash
sudo nano /etc/systemd/user/spotifyd.service
```

Paste this:

```ini
[Unit]
Description=Spotifyd Spotify Connect Receiver
Documentation=https://github.com/Spotifyd/spotifyd
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/.cargo/bin/spotifyd --no-daemon
Restart=on-failure
RestartSec=10

StandardOutput=journal
StandardError=journal

Environment="PATH=/home/pi/.cargo/bin:/usr/local/bin:/usr/bin:/bin"

[Install]
WantedBy=default.target
```

Enable and start the service:

```bash
systemctl --user daemon-reload
systemctl --user enable spotifyd.service
systemctl --user start spotifyd.service
systemctl --user status spotifyd.service
```

Check logs:

```bash
journalctl --user -u spotifyd.service -n 50 -f
```

If you want Spotifyd to start even when you're not logged in, enable lingering for your user:

```bash
sudo loginctl enable-linger pi
```

## 9. Connect via TapTune

Once Spotifyd is running (either manually or via systemd), TapTune's Spotify playback will use it as the default device.

In TapTune's `.env`:

```dotenv
SPOTIFY_DEVICE_NAME=Raspberry Pi 5
```

Make sure `SPOTIFY_DEVICE_NAME` matches the device name configured in `spotifyd.conf`.

Restart TapTune:

```bash
sudo systemctl restart raspi-spotify-nfc.service
```

Test a tag assignment:

```bash
curl -X POST -d 'uid=04A7B2F1' http://127.0.0.1:5000/dispatch
```

Music should play on the Spotifyd device.

## Troubleshooting

| Problem | Check |
| --- | --- |
| Build fails with out-of-memory error | Ensure swap is active: `free -h`. Rerun the build command. |
| `libssl.so.1.1: cannot open shared object file` | The build used the old OpenSSL. Clean and rebuild: `cargo clean && cargo +stable build --release --locked`. |
| Spotifyd starts but audio is silent or errors occur | Use `backend = "pulseaudio"` instead of `alsa`. PulseAudio handles PipeWire integration on modern Raspberry Pi OS. |
| Spotifyd not in Spotify device list | It takes 5–10 seconds to register. Refresh the device list in Spotify. Check `journalctl --user -u spotifyd.service -n 50`. |
| Service fails to start at boot | Check `systemctl --user status spotifyd.service`. Ensure `SPOTIFY_PASSWORD` and `SPOTIFY_USERNAME` are set. Verify the binary path in `ExecStart`. |

## Next steps

1. **If using Spotifyd alone:** continue with [Hardware setup](hardware-setup.md) to enable the PN532 reader and assign NFC tags.
2. **If also using speaker auto-connect:** see [Speaker setup](speaker-setup.md) for BlueALSA + Raspotify integration. (You don't need both Spotifyd and Raspotify; pick one.)
3. **For live NFC playback:** complete [Using tags](tag-usage.md) and [Raspberry Pi service](raspberry-pi-service.md) to enable the reader and dispatch.
