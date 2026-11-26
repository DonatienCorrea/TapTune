# Connect the PN532 reader

[Installation guide](raspberry-pi-service.md) · [Documentation index](README.md)

**Turn the Pi off before wiring.**

1. Set the PN532 board to **I2C mode** (switches or jumpers; follow the label on your board).
2. Wire it to the Pi:

   | PN532 | Raspberry Pi pin |
   | --- | --- |
   | VCC / 3.3V | 1 (3.3 V) |
   | GND | 6 (ground) |
   | SDA | 3 (GPIO 2) |
   | SCL | 5 (GPIO 3) |
   | IRQ, RST | not connected |

   The Pi's pins are 3.3 V only: never put 5 V on SDA or SCL.

3. Turn the Pi on and enable I2C:

   ```bash
   sudo raspi-config nonint do_i2c 0
   sudo apt install -y i2c-tools
   sudo reboot
   ```

4. Check the reader is seen (it should show `24`):

   ```bash
   sudo i2cdetect -y 1
   ```

   Some boards don't answer this scan; step 5 is the real test.

## Read a first tag

From the TapTune folder (if TapTune is already installed, stop it first with
`sudo systemctl stop raspi-spotify-nfc.service`):

```bash
.venv/bin/python -m app.pn532_diag --seconds 30
```

Wait for `PN532 initialized over I2C`, then hold a tag flat on the reader. It
should print something like `uid=04A7B2F1`. Repeat a few times: it must read
every time before you continue.

## If it doesn't work

- `PN532 support is not available`: run `./install.sh` again (it installs `requirements-pi.txt`).
- `/dev/i2c-1` missing: I2C is off; repeat step 3.
- Not initialized: recheck I2C mode, power, ground, and that SDA/SCL are not swapped.
- Initialized but no UID: place the tag directly on the antenna; try another tag.
- Only one program can use the reader: stop TapTune and any other test first.
