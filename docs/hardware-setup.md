# PN532 hardware setup

[Documentation index](README.md)

This guide configures a PN532 NFC reader over the Raspberry Pi's primary I2C bus and proves that one physical card can be read before Spotify or the web service is involved.

## Before connecting power

PN532 breakout boards use different labels, switches, or solder jumpers to select a host interface. Set the board to **I2C mode** according to its own silkscreen or manufacturer documentation. Do not copy an SPI or UART switch position from another model.

The Raspberry Pi GPIO lines are 3.3 V only. A breakout may accept 5 V on its power input, but that does not make 5 V safe on SDA or SCL.

Power down the Pi before changing the reader mode or wiring.

## Wiring

Use the Raspberry Pi's primary I2C bus:

| PN532 pin | Raspberry Pi physical pin | BCM | Notes |
| --- | --- | --- | --- |
| VCC / 3.3V | 1 | — | Use 3.3 V unless the breakout documentation explicitly requires another supply. |
| GND | 6 | — | Common ground. |
| SDA | 3 | GPIO 2 / SDA1 | I2C data. |
| SCL | 5 | GPIO 3 / SCL1 | I2C clock. |
| IRQ | — | — | Leave disconnected for the polling setup. |
| RST / RSTO | — | — | Leave disconnected unless the selected PN532 library or breakout requires it. |

## Enable and inspect I2C

```bash
sudo raspi-config nonint do_i2c 0
sudo apt install -y i2c-tools
sudo reboot
```

After reboot:

```bash
ls -l /dev/i2c-1
sudo i2cdetect -y 1
```

A PN532 in I2C mode normally uses the 7-bit address `0x24`, so the scan should show `24`.

Some PN532 firmware and library combinations do not respond reliably to the generic probe used by `i2cdetect`. If `/dev/i2c-1` exists but `24` is absent, recheck interface selection, SDA/SCL orientation, power, and ground, then use the first-card diagnostic below as the definitive application check.

## Install Pi-specific dependencies

From the repository root:

```bash
source .venv/bin/activate
python -m pip install -r requirements-pi.txt
```

The diagnostic fails immediately with the message below when these packages are not available in the active environment:

```text
PN532 support is not available; install requirements-pi.txt on the Pi.
```

## Read the first card

This bounded test proves that the Pi, I2C bus, PN532, Python dependency, and one physical card work together.

1. Stop the TapTune service so only one process owns the reader:

   ```bash
   sudo systemctl stop raspi-spotify-nfc.service
   ```

2. Activate the environment and run:

   ```bash
   source .venv/bin/activate
   python -m app.pn532_diag --seconds 30
   ```

3. Wait for `PN532 initialized over I2C`.
4. Hold one card flat and close to the antenna until the command prints a UID such as:

   ```text
   uid=04A7B2F1
   ```

5. Remove the card and copy the complete UID exactly as printed. UID length varies by card type.

Do not continue to assignment until the command reads the card consistently.

For an unbounded test that waits indefinitely:

```bash
python -m app.nfc_reader --read
```

## If the card is not read

- If initialization reports the missing-support message, install `requirements-pi.txt` in the active virtual environment.
- If initialization still fails, recheck I2C mode, power, ground, SDA, and SCL.
- If initialization succeeds but the command times out, place the card directly over the antenna and retry with a known ISO/IEC 14443 Type A card.
- Stop the service and any other reader process before retrying.

Continue with [Using and assigning tags](tag-usage.md) after the first UID is reliable.
