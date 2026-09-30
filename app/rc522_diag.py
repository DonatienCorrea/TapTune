import argparse
import glob
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import List, Optional


COMMAND_REG = 0x01
COM_I_EN_REG = 0x02
COM_IRQ_REG = 0x04
ERROR_REG = 0x06
FIFO_DATA_REG = 0x09
FIFO_LEVEL_REG = 0x0A
CONTROL_REG = 0x0C
BIT_FRAMING_REG = 0x0D
MODE_REG = 0x11
TX_CONTROL_REG = 0x14
TX_ASK_REG = 0x15
T_MODE_REG = 0x2A
T_PRESCALER_REG = 0x2B
T_RELOAD_REG_H = 0x2C
T_RELOAD_REG_L = 0x2D
VERSION_REG = 0x37

PCD_IDLE = 0x00
PCD_TRANSCEIVE = 0x0C
PCD_RESET_PHASE = 0x0F
PICC_REQIDL = 0x26

KNOWN_VERSIONS = {
    0x88: "FM17522 clone",
    0x90: "MFRC522 v0.0",
    0x91: "MFRC522 v1.0",
    0x92: "MFRC522 v2.0",
    0xB2: "FM17522E clone",
}


@dataclass(frozen=True)
class ReaderConnection:
    device: int
    speed: int
    version: int


def read_reg(spi, register: int) -> int:
    return spi.xfer2([((register << 1) & 0x7E) | 0x80, 0])[1]


def write_reg(spi, register: int, value: int) -> None:
    spi.xfer2([(register << 1) & 0x7E, value & 0xFF])


def set_bits(spi, register: int, mask: int) -> None:
    write_reg(spi, register, read_reg(spi, register) | mask)


def clear_bits(spi, register: int, mask: int) -> None:
    write_reg(spi, register, read_reg(spi, register) & (~mask & 0xFF))


class ResetPin:
    def __init__(self, bcm_pin: Optional[int]):
        self.bcm_pin = bcm_pin
        self.gpio = None
        if bcm_pin is None:
            print("RESET control disabled.")
            return

        try:
            import RPi.GPIO as GPIO

            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(bcm_pin, GPIO.OUT, initial=GPIO.HIGH)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot claim RESET on BCM{bcm_pin}: {exc}. "
                "Stop other reader processes or retry with --no-rst."
            ) from exc

        self.gpio = GPIO
        print(f"RESET held HIGH on BCM{bcm_pin} (physical pin 22 for BCM25).")

    def set(self, high: bool) -> None:
        if self.gpio is not None:
            self.gpio.output(
                self.bcm_pin,
                self.gpio.HIGH if high else self.gpio.LOW,
            )
            time.sleep(0.05)

    def cleanup(self) -> None:
        if self.gpio is not None:
            self.gpio.cleanup(self.bcm_pin)


def scan_buses(spidev) -> List[ReaderConnection]:
    print("\nReading VersionReg on CE0 and CE1:")
    connections = []
    for device in (0, 1):
        for speed in (1_000_000, 500_000, 100_000):
            spi = spidev.SpiDev()
            try:
                spi.open(0, device)
            except Exception as exc:
                print(f"  CE{device} @ {speed:7d} Hz: unavailable ({exc})")
                continue

            try:
                spi.mode = 0
                spi.max_speed_hz = speed
                version = read_reg(spi, VERSION_REG)
            finally:
                spi.close()

            label = KNOWN_VERSIONS.get(version)
            if label is None:
                detail = (
                    "no response"
                    if version in (0x00, 0xFF)
                    else "unknown value; not accepted as a reader"
                )
                print(f"  CE{device} @ {speed:7d} Hz: 0x{version:02X} ({detail})")
                continue

            print(f"  CE{device} @ {speed:7d} Hz: 0x{version:02X} ({label})")
            connections.append(ReaderConnection(device, speed, version))
    return connections


def show_pin_configuration() -> int:
    tool = shutil.which("pinctrl") or shutil.which("raspi-gpio")
    if tool is None:
        print("Neither pinctrl nor raspi-gpio is installed.")
        print("Install raspi-utils to inspect the SPI pin multiplexing.")
        return 1

    result = subprocess.run(
        [tool, "get", "7-11"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    print(output or "No pin configuration output.")
    if result.returncode != 0:
        return 1

    lowered = output.lower()
    if "spi" not in lowered and "a0" not in lowered:
        print("GPIO 7-11 do not appear to be routed to SPI0.")
        return 2
    print("GPIO 7-11 appear to be routed to SPI0.")
    return 0


def run_loopback(spidev) -> int:
    pattern = [0xAA, 0x55, 0x00, 0xFF, 0x0F, 0xF0, 0x81]
    spi = spidev.SpiDev()
    try:
        spi.open(0, 0)
        spi.mode = 0
        spi.max_speed_hz = 500_000
        received = spi.xfer2(pattern.copy())
    except Exception as exc:
        print(f"SPI0 loopback failed to run: {exc}")
        return 1
    finally:
        spi.close()

    print("Sent:     " + " ".join(f"0x{byte:02X}" for byte in pattern))
    print("Received: " + " ".join(f"0x{byte:02X}" for byte in received))
    if received == pattern:
        print("SPI0 MOSI-to-MISO loopback passed.")
        return 0
    print("SPI0 loopback failed. Check the physical 19-to-21 bridge and pin numbering.")
    return 2


def check_reset(spidev, connection: ReaderConnection, reset: ResetPin) -> None:
    if reset.gpio is None:
        return

    spi = spidev.SpiDev()
    spi.open(0, connection.device)
    spi.mode = 0
    spi.max_speed_hz = connection.speed
    try:
        reset.set(True)
        high = read_reg(spi, VERSION_REG)
        reset.set(False)
        low = read_reg(spi, VERSION_REG)
        reset.set(True)
        restored = read_reg(spi, VERSION_REG)
    finally:
        spi.close()

    print(
        f"\nRESET test: HIGH=0x{high:02X}, LOW=0x{low:02X}, "
        f"HIGH again=0x{restored:02X}"
    )
    if low == high:
        print("RESET did not affect the chip; verify RC522 RST -> physical pin 22.")


def initialize_chip(spi) -> bool:
    write_reg(spi, COMMAND_REG, PCD_RESET_PHASE)
    time.sleep(0.05)
    write_reg(spi, T_MODE_REG, 0x8D)
    write_reg(spi, T_PRESCALER_REG, 0x3E)
    write_reg(spi, T_RELOAD_REG_L, 30)
    write_reg(spi, T_RELOAD_REG_H, 0)
    write_reg(spi, TX_ASK_REG, 0x40)
    write_reg(spi, MODE_REG, 0x3D)

    readback = read_reg(spi, T_MODE_REG)
    set_bits(spi, TX_CONTROL_REG, 0x03)
    antenna = read_reg(spi, TX_CONTROL_REG)
    print(f"Register write/read: 0x8D -> 0x{readback:02X}")
    print(f"Antenna control: 0x{antenna:02X}")
    return readback == 0x8D and antenna & 0x03 == 0x03


def request_tag(spi):
    write_reg(spi, BIT_FRAMING_REG, 0x07)
    write_reg(spi, COM_I_EN_REG, 0xF7)
    write_reg(spi, COM_IRQ_REG, 0x7F)
    set_bits(spi, FIFO_LEVEL_REG, 0x80)
    write_reg(spi, COMMAND_REG, PCD_IDLE)
    write_reg(spi, FIFO_DATA_REG, PICC_REQIDL)
    write_reg(spi, COMMAND_REG, PCD_TRANSCEIVE)
    set_bits(spi, BIT_FRAMING_REG, 0x80)

    irq = 0
    for _ in range(2000):
        irq = read_reg(spi, COM_IRQ_REG)
        if irq & 0x31:
            break
    clear_bits(spi, BIT_FRAMING_REG, 0x80)

    error = read_reg(spi, ERROR_REG)
    if error & 0x1B or not irq & 0x20:
        return False, [], error, irq, 0

    count = read_reg(spi, FIFO_LEVEL_REG)
    last_bits = read_reg(spi, CONTROL_REG) & 0x07
    bit_count = (count - 1) * 8 + last_bits if last_bits else count * 8
    data = [read_reg(spi, FIFO_DATA_REG) for _ in range(count)]
    return bit_count == 0x10, data, error, irq, bit_count


def scan_for_tag(spi, seconds: float) -> bool:
    print(f"\nScanning for a 13.56 MHz ISO 14443A tag for {seconds:g} seconds...")
    deadline = time.monotonic() + seconds
    attempts = 0
    last_error = 0
    last_irq = 0
    while time.monotonic() < deadline:
        found, data, last_error, last_irq, bits = request_tag(spi)
        attempts += 1
        if found:
            print("Tag detected; ATQA=" + " ".join(f"0x{byte:02X}" for byte in data))
            return True
        if attempts % 25 == 0:
            print(".", end="", flush=True)
        time.sleep(0.05)

    print(
        f"\nNo tag detected. ErrorReg=0x{last_error:02X}, "
        f"ComIrqReg=0x{last_irq:02X}"
    )
    if last_irq & 0x01 and not last_irq & 0x20:
        print("The chip completed its timer but received no tag response.")
        print("Check tag frequency/type, antenna soldering, and nearby metal.")
    return False


def run(seconds: float, reset_bcm: Optional[int]) -> int:
    devices = sorted(glob.glob("/dev/spidev*"))
    if not devices:
        print("No /dev/spidev* device found. Enable SPI with raspi-config and reboot.")
        return 1
    print("SPI devices:", " ".join(devices))

    try:
        import spidev
    except ImportError:
        print("spidev is unavailable; run ./systemd/install-pi-dependencies.sh")
        return 1

    try:
        reset = ResetPin(reset_bcm)
    except RuntimeError as exc:
        print(f"ERROR: {exc}")
        return 1

    try:
        connections = scan_buses(spidev)
        if not connections:
            print("\nNo recognized RC522 responded on CE0 or CE1 at any tested speed.")
            print("Check 3.3 V power, wiring, jumper continuity, soldering, or another module.")
            return 2

        connection = connections[0]
        print(
            f"\nUsing CE{connection.device} at {connection.speed} Hz "
            f"(VersionReg=0x{connection.version:02X})."
        )
        if connection.device == 1:
            print("Reader is on CE1; move SDA/SS to physical pin 24 for TapTune's CE0.")
        check_reset(spidev, connection, reset)

        spi = spidev.SpiDev()
        spi.open(0, connection.device)
        spi.mode = 0
        spi.max_speed_hz = connection.speed
        try:
            if not initialize_chip(spi):
                print("RC522 register or antenna initialization failed.")
                return 3
            return 0 if scan_for_tag(spi, seconds) else 4
        finally:
            spi.close()
    finally:
        reset.cleanup()


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnose an RC522 reader over SPI")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--rst-bcm", type=int, default=25)
    parser.add_argument("--no-rst", action="store_true")
    parser.add_argument(
        "--pin-config",
        action="store_true",
        help="show whether GPIO 7-11 are routed to SPI0, then exit",
    )
    parser.add_argument(
        "--loopback",
        action="store_true",
        help="test SPI0 with the RC522 disconnected and physical pins 19 and 21 bridged",
    )
    parser.add_argument(
        "--confirm-disconnected",
        action="store_true",
        help="confirm the RC522 is disconnected before running --loopback",
    )
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be greater than zero")
    if args.pin_config:
        raise SystemExit(show_pin_configuration())
    if args.loopback:
        if not args.confirm_disconnected:
            parser.error(
                "--loopback requires --confirm-disconnected after removing all RC522 "
                "connections and bridging physical pins 19 and 21"
            )
        try:
            import spidev
        except ImportError:
            parser.error("spidev is unavailable; run ./systemd/install-pi-dependencies.sh")
        raise SystemExit(run_loopback(spidev))
    raise SystemExit(run(args.seconds, None if args.no_rst else args.rst_bcm))


if __name__ == "__main__":
    main()
