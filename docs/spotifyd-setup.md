# Install Spotifyd on Raspberry Pi 5

[Documentation index](README.md)

**Spotifyd** is a lightweight Spotify Connect receiver. This guide is an optional
source-build step for the [Desktop/PipeWire setup](speaker-setup-desktop.md)
when a downloaded binary cannot run on your Pi.

> **Note:** For Lite without PipeWire, use [Raspotify speaker setup](speaker-setup.md) instead. Do not combine the two audio stacks.

## Prerequisites

- Raspberry Pi 5 with **2+ GB RAM** (the 8 GB model is ideal)
- **Official Raspberry Pi 27 W USB-C power supply** (5.1 V / 5 A minimum)
- Raspberry Pi OS Desktop with PipeWire (Bookworm/Trixie)
- SSH access or terminal access
- Spotify Premium account

## Why build from source?

Some downloaded binaries require shared libraries absent from your OS, for
example `libssl.so.1.1`. Check `/usr/local/bin/spotifyd --version` first. Building
on the target OS avoids depending on an incompatible prebuilt binary; not every
release requires the same OpenSSL version.

## 1. Check memory and swap

Rust compilation is memory-intensive. Check `free -h` and `swapon --show` first.
If your Pi has 2 GB RAM and insufficient swap, create additional swap below.
Do not overwrite an existing `/swapfile`, and do not append a duplicate fstab
entry when repeating the setup.

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

Verify that no required shared library is missing:

```bash
ldd /usr/local/bin/spotifyd
```

There must be no `not found` entries. A build may use different TLS libraries,
so the absence of a `libssl` line is not itself an error.

## 6. Configure the Desktop audio setup

Return to [Desktop speaker setup, step 3](speaker-setup-desktop.md#3-configure-and-authenticate-spotifyd).
That guide is the single configuration reference for:

- the `TapTune` device name and PulseAudio backend;
- Spotifyd's own account authentication (separate from TapTune's Web API token);
- lingering, Bluetooth recovery and PipeWire audio before login;
- the user ready-sound service and `READY_SOUND_ENABLED=true`; and
- TapTune's `install-service.sh --desktop` unit and the cold-boot test.

Do not run another `spotifyd.service` or Raspotify alongside that receiver.

## Troubleshooting

| Problem | Check |
| --- | --- |
| Build fails with out-of-memory error | Ensure swap is active: `free -h`. Rerun the build command. |
| `libssl.so.1.1: cannot open shared object file` | The build used the old OpenSSL. Clean and rebuild: `cargo clean && cargo +stable build --release --locked`. |
| Spotifyd starts but audio is silent or errors occur | Use `backend = "pulseaudio"` instead of `alsa`. PulseAudio handles PipeWire integration on modern Raspberry Pi OS. |
| Service fails to start: `Unable to locate executable` | Install the binary at `/usr/local/bin/spotifyd`, then rerun the Desktop installer as the authenticated user. |
| Spotifyd not in Spotify device list | It takes a few seconds to register. Refresh the device list in Spotify. Check `journalctl --user -u taptune-spotifyd.service -n 50 --no-pager`. |
| Audio only works after login | Follow the Desktop installer guide; check lingering, the PipeWire user services and WirePlumber's headless Bluetooth config. |
