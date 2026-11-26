# Connect the PN532 reader

[Installation guide](raspberry-pi-service.md) · [Documentation index](README.md)

## Wire the reader

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

After wiring, [enable I2C and run the installer](raspberry-pi-service.md#3-install-taptune).
No separate scan or tag test is needed during installation.

## Read a first tag

Use this test if TapTune can't find the reader or you need to copy a tag's ID.
If the service is running, stop it first with `sudo systemctl stop raspi-spotify-nfc.service`.
From the TapTune folder, run:

```bash
.venv/bin/python -m app.pn532_diag --seconds 30
```

When the reader is ready, hold a tag flat on it. The test prints its ID, such as
`uid=04A7B2F1`. If you stopped TapTune, start it again with
`sudo systemctl start raspi-spotify-nfc.service`.

## If it doesn't work

- `PN532 support is not available`: run `./install.sh` again (it installs `requirements-pi.txt`).
- `/dev/i2c-1` missing: [enable I2C](raspberry-pi-service.md#3-install-taptune). If it still doesn't appear, reboot the Pi and check again.
- Not initialized: recheck I2C mode, power, ground, and that SDA/SCL are not swapped.
- Initialized but no UID: place the tag directly on the antenna; try another tag.
- Only one program can use the reader: stop TapTune and any other test first.
