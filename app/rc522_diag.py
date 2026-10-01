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


def interpret_clock_bytes(received: List[int]) -> bool:
    return any(byte != 0x00 for byte in received)


def run_clock_test(spidev) -> int:
    spi = spidev.SpiDev()
    try:
        spi.open(0, 0)
        spi.mode = 0
        spi.max_speed_hz = 100_000
        received = spi.xfer2([0x00] * 4)
    except Exception as exc:
        print(f"SPI0 clock test failed to run: {exc}")
        return 1
    finally:
        spi.close()

    print("Received: " + " ".join(f"0x{byte:02X}" for byte in received))
    if interpret_clock_bytes(received):
        print(
            "SCK is toggling. Physical pin 23 drives a real clock, so the Pi side of "
            "SCK is proven good."
        )
        return 0
    print(
        "Read back all zero bytes. This suggests physical pin 23 is not clocking, but "
        "it is not conclusive: sampling can land on the low phase of the clock. "
        "Re-seat the pin 23 to pin 21 jumper and retry before suspecting the Pi."
    )
    return 2


PHYSICAL_PINS = {
    4: 7, 5: 29, 6: 31, 7: 26, 8: 24, 9: 21, 10: 19, 11: 23,
    12: 32, 13: 33, 16: 36, 17: 11, 18: 12, 19: 35, 20: 38,
    21: 40, 22: 15, 23: 16, 24: 18, 25: 22, 26: 37, 27: 13,
}

DEFAULT_BITBANG_PINS = (11, 10, 9, 8)


def describe_pin(bcm: int) -> str:
    physical = PHYSICAL_PINS.get(bcm)
    return f"GPIO {bcm}" + (f" (physical {physical})" if physical else "")


DEFAULT_RST_BCM = 25


def release_power_down(gpio, rst_bcm: int) -> None:
    """Take NRSTPD low then high to leave hard power-down.

    The MFRC522 holds its whole digital core, including the SPI interface, in
    reset while NRSTPD is low. The breakout boards have no pull-up on that pin,
    so an undriven RST floats and the chip can stay powered down and silent.
    """
    gpio.setmode(gpio.BCM)
    gpio.setup(rst_bcm, gpio.OUT, initial=gpio.LOW)
    time.sleep(0.01)
    gpio.output(rst_bcm, gpio.HIGH)
    time.sleep(0.05)


def probe_miso_across_reset(gpio, miso: int, cs: int, rst_bcm: int) -> tuple:
    """Sample MISO in hard power-down and again after leaving it.

    Section 8.6.1 freezes the output pins while NRSTPD is low, and section 8.1.1
    has the chip re-detect its host interface on the rising edge. A chip that
    receives the reset should therefore not look identical in both states.

    Each state is sampled with the internal pull-up and then the pull-down, so a
    line that nobody drives is reported as floating instead of being mistaken
    for a frozen output.
    """
    gpio.setmode(gpio.BCM)
    gpio.setup(cs, gpio.OUT, initial=gpio.LOW)
    gpio.setup(rst_bcm, gpio.OUT, initial=gpio.LOW)
    time.sleep(0.05)
    held_low = probe_pulls(gpio, miso)
    gpio.output(rst_bcm, gpio.HIGH)
    time.sleep(0.05)
    released = probe_pulls(gpio, miso)
    return (held_low, released)


def probe_pulls(gpio, pin: int) -> tuple:
    readings = []
    for pull in (gpio.PUD_UP, gpio.PUD_DOWN):
        gpio.setup(pin, gpio.IN, pull_up_down=pull)
        time.sleep(0.01)
        readings.append(1 if gpio.input(pin) else 0)
        gpio.cleanup(pin)
    return tuple(readings)


def interpret_reset_effect(readings: tuple) -> tuple:
    in_power_down, released = readings
    floating = (1, 0)
    if in_power_down == floating and released == floating:
        return (
            False,
            "MISO follows the internal resistors in both states, so nothing "
            "drives it.",
            "The line is floating whether RST is held low or released. The "
            "RC522 never drives MISO at all, so check the MISO jumper and its "
            "solder joint at the module before suspecting the chip.",
        )
    if in_power_down != released:
        return (
            True,
            "MISO changed when RST was released.",
            "The reset signal reaches the chip and it responds to leaving "
            "power-down, so RST wiring is good.",
        )
    return (
        False,
        "MISO is identical in power-down and after releasing RST.",
        "Toggling RST changes nothing at the module. Either the RST jumper or "
        "its header joint is open, so the chip never leaves hard power-down, or "
        "the chip is dead. Check RC522 RST to physical pin 22 for continuity "
        "with the power off before replacing the module.",
    )


def run_reset_effect(gpio, pins=DEFAULT_BITBANG_PINS, rst_bcm=DEFAULT_RST_BCM) -> int:
    _, _, miso, cs = pins
    if rst_bcm is None:
        print("This test needs a reset pin; drop --no-rst.")
        return 1
    print(f"Holding {describe_pin(rst_bcm)} (RST) low, then releasing it.")
    print(f"Watching {describe_pin(miso)} (MISO) with chip select asserted.\n")
    try:
        readings = probe_miso_across_reset(gpio, miso, cs, rst_bcm)
    except Exception as exc:
        print(f"Could not probe across reset: {exc}")
        print("Disable SPI first with 'sudo raspi-config nonint do_spi 1 && sudo reboot'.")
        return 1
    finally:
        for pin in (miso, cs, rst_bcm):
            try:
                gpio.cleanup(pin)
            except Exception:
                pass

    for label, pair in (("RST low (power-down)", readings[0]), ("RST high (running)", readings[1])):
        print(f"MISO with {label}: pull-up {pair[0]}, pull-down {pair[1]}")
    print()
    changed, summary, detail = interpret_reset_effect(readings)
    print(summary)
    print(detail)
    return 0 if changed else 2


def probe_line(gpio, pin: int, cs: int) -> tuple:
    """Read a line with the internal pull-up and then the pull-down applied.

    With chip select asserted the RC522 drives MISO actively, so a live module
    overrides both internal resistors and returns the same level twice. A line
    that simply follows whichever resistor is applied is being driven by nothing
    at all.

    The pin is released between the two readings because the underlying driver
    only applies a pull while claiming a line, so re-running setup on a pin it
    already holds silently keeps the first pull in place.
    """
    gpio.setmode(gpio.BCM)
    gpio.setup(cs, gpio.OUT, initial=gpio.LOW)
    readings = []
    for pull in (gpio.PUD_UP, gpio.PUD_DOWN):
        gpio.setup(pin, gpio.IN, pull_up_down=pull)
        time.sleep(0.01)
        readings.append(1 if gpio.input(pin) else 0)
        gpio.cleanup(pin)
    return tuple(readings)


def interpret_line(readings: tuple) -> tuple:
    pulled_up, pulled_down = readings
    if pulled_up == pulled_down:
        level = "high" if pulled_up else "low"
        return (
            True,
            f"MISO sits {level} regardless of the internal resistors.",
            "The line is held by the module, so the MISO wire and its pad are "
            "connected. Note that a chip in hard power-down also freezes this "
            "output, so this does not by itself prove the chip is running.",
        )
    return (
        False,
        "MISO simply follows whichever internal resistor is applied.",
        "Nothing is driving it. With chip select asserted a working RC522 would "
        "hold this line itself, so the MISO wire, its header joint, or the "
        "module's output is open.",
    )


def run_line_check(gpio, pins=DEFAULT_BITBANG_PINS, rst_bcm=DEFAULT_RST_BCM) -> int:
    _, _, miso, cs = pins
    print(f"Probing {describe_pin(miso)} (MISO) with chip select asserted.")
    claimed = [miso, cs]
    try:
        if rst_bcm is not None:
            print(f"Releasing power-down on {describe_pin(rst_bcm)} (RST) first.")
            release_power_down(gpio, rst_bcm)
            claimed.append(rst_bcm)
        print()
        readings = probe_line(gpio, miso, cs)
    except Exception as exc:
        print(f"Could not probe the MISO line: {exc}")
        print("Disable SPI first with 'sudo raspi-config nonint do_spi 1 && sudo reboot'.")
        return 1
    finally:
        for pin in claimed:
            try:
                gpio.cleanup(pin)
            except Exception:
                pass

    print(f"With internal pull-up:   {readings[0]}")
    print(f"With internal pull-down: {readings[1]}\n")
    driven, summary, detail = interpret_line(readings)
    print(summary)
    print(detail)
    return 0 if driven else 2


class PinClaimError(Exception):
    def __init__(self, pin: int, label: str, cause: Exception):
        super().__init__(f"GPIO {pin} ({label}) could not be claimed: {cause}")
        self.pin = pin
        self.label = label
        self.cause = cause


class BitBangBus:
    """Drive the RC522 over SPI by toggling plain GPIO lines.

    This bypasses the kernel SPI driver and the Pi 5 RP1 SPI peripheral,
    including its GPIO-driven chip select, so a reply here proves the module
    is alive even if the hardware SPI path is at fault.
    """

    def __init__(self, gpio, sck=11, mosi=10, miso=9, cs=8, delay=0.00001):
        self.gpio = gpio
        self.sck = sck
        self.mosi = mosi
        self.miso = miso
        self.cs = cs
        self.delay = delay

    def setup(self) -> None:
        self.gpio.setmode(self.gpio.BCM)
        plan = [
            (self.sck, "SCK", self.gpio.OUT, self.gpio.LOW),
            (self.mosi, "MOSI", self.gpio.OUT, self.gpio.LOW),
            (self.cs, "CS", self.gpio.OUT, self.gpio.HIGH),
            (self.miso, "MISO", self.gpio.IN, None),
        ]
        for pin, label, direction, initial in plan:
            try:
                if initial is None:
                    self.gpio.setup(pin, direction)
                else:
                    self.gpio.setup(pin, direction, initial=initial)
            except Exception as exc:
                raise PinClaimError(pin, label, exc) from exc

    def cleanup(self) -> None:
        for pin in (self.sck, self.mosi, self.cs, self.miso):
            try:
                self.gpio.cleanup(pin)
            except Exception:
                pass

    def _settle(self) -> None:
        if self.delay:
            time.sleep(self.delay)

    def transfer_byte(self, value: int) -> int:
        received = 0
        for index in range(8):
            bit = (value >> (7 - index)) & 1
            self.gpio.output(self.mosi, self.gpio.HIGH if bit else self.gpio.LOW)
            self._settle()
            self.gpio.output(self.sck, self.gpio.HIGH)
            self._settle()
            received = (received << 1) | (1 if self.gpio.input(self.miso) else 0)
            self.gpio.output(self.sck, self.gpio.LOW)
            self._settle()
        return received

    def read_register(self, register: int) -> int:
        self.gpio.output(self.cs, self.gpio.LOW)
        self._settle()
        try:
            self.transfer_byte(((register << 1) & 0x7E) | 0x80)
            return self.transfer_byte(0x00)
        finally:
            self.gpio.output(self.cs, self.gpio.HIGH)
            self._settle()


def parse_bitbang_pins(text: str):
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 4:
        raise ValueError("--bitbang-pins needs exactly four values: SCK,MOSI,MISO,CS")
    try:
        pins = tuple(int(part) for part in parts)
    except ValueError:
        raise ValueError("--bitbang-pins values must be BCM pin numbers") from None
    if len(set(pins)) != 4:
        raise ValueError("--bitbang-pins values must be four different pins")
    if any(pin < 0 or pin > 27 for pin in pins):
        raise ValueError("--bitbang-pins values must be between 0 and 27")
    return pins


def run_bitbang(gpio, pins=DEFAULT_BITBANG_PINS, rst_bcm=DEFAULT_RST_BCM) -> int:
    sck, mosi, miso, cs = pins
    print("Bit-banging SPI on:")
    for label, bcm in (("SCK", sck), ("MOSI", mosi), ("MISO", miso), ("CS", cs)):
        print(f"  {label:<4} {describe_pin(bcm)}")
    if rst_bcm is not None:
        print(f"  RST  {describe_pin(rst_bcm)} (released from power-down first)")
    print("This ignores /dev/spidev and the RP1 SPI peripheral entirely.\n")
    bus = BitBangBus(gpio, sck=sck, mosi=mosi, miso=miso, cs=cs)
    if rst_bcm is not None:
        try:
            release_power_down(gpio, rst_bcm)
        except Exception as exc:
            print(f"Could not release power-down on {describe_pin(rst_bcm)}: {exc}")
            print("Retry with --no-rst if RST is wired elsewhere or left unconnected.")
            return 1
    try:
        bus.setup()
    except PinClaimError as exc:
        bus.cleanup()
        print(f"Could not claim {describe_pin(exc.pin)} as {exc.label}: {exc.cause}")
        if tuple(pins) == DEFAULT_BITBANG_PINS:
            print(
                "\nGPIO 8-11 are still held by the SPI driver, which owns them in "
                "alt-function mode, so they cannot be driven as plain GPIO."
            )
            print("Turn SPI off for this test, then run it again:")
            print("  sudo raspi-config nonint do_spi 1 && sudo reboot")
            print(
                "Afterwards turn SPI back on with "
                "'sudo raspi-config nonint do_spi 0 && sudo reboot'."
            )
            print(
                "\nAlternatively, leave SPI enabled, move the four RC522 signal "
                "wires to free pins and pass them explicitly, for example:"
            )
            print("  python -m app.rc522_diag --bitbang --bitbang-pins 5,6,13,19")
        else:
            print("Pick pins that no other driver or process is using, then retry.")
        return 1
    except Exception as exc:
        bus.cleanup()
        print(f"Could not set up the bit-banged bus: {exc}")
        return 1

    try:
        version = bus.read_register(VERSION_REG)
    except Exception as exc:
        print(f"Bit-banged transfer failed: {exc}")
        return 1
    finally:
        bus.cleanup()
        if rst_bcm is not None:
            try:
                gpio.cleanup(rst_bcm)
            except Exception:
                pass

    label = KNOWN_VERSIONS.get(version)
    print(f"VersionReg: 0x{version:02X}")
    if label is not None:
        print(f"The RC522 answered ({label}).")
        print(
            "The module is alive, so the fault is in the hardware SPI path "
            "rather than the reader."
        )
        return 0
    if version in (0x00, 0xFF):
        print("No answer, exactly as over hardware SPI.")
        if rst_bcm is not None:
            print(
                "RST was pulsed low then high first, so the chip was taken out of "
                "hard power-down before this read."
            )
        print(
            "Software and the SPI peripheral are now both excluded: the module, "
            "its solder joints, or the jumper wires are at fault."
        )
        return 2
    print("Unrecognised value; treating it as no valid reader response.")
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
        "--clock-test",
        action="store_true",
        help="test SCK with the RC522 disconnected and physical pins 23 and 21 bridged",
    )
    parser.add_argument(
        "--bitbang",
        action="store_true",
        help="read VersionReg by toggling the SPI pins as plain GPIO, with the RC522 connected normally",
    )
    parser.add_argument(
        "--line-check",
        action="store_true",
        help="probe MISO with the internal pull-up and pull-down to see whether anything drives it",
    )
    parser.add_argument(
        "--reset-effect",
        action="store_true",
        help="check whether toggling RST changes anything at the module",
    )
    parser.add_argument(
        "--bitbang-pins",
        help="BCM pins for --bitbang as SCK,MOSI,MISO,CS (default 11,10,9,8)",
    )
    parser.add_argument(
        "--confirm-disconnected",
        action="store_true",
        help="confirm the RC522 is disconnected before running --loopback or --clock-test",
    )
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be greater than zero")
    if args.pin_config:
        raise SystemExit(show_pin_configuration())
    if args.bitbang or args.line_check or args.reset_effect:
        pins = DEFAULT_BITBANG_PINS
        if args.bitbang_pins:
            try:
                pins = parse_bitbang_pins(args.bitbang_pins)
            except ValueError as exc:
                parser.error(str(exc))
        rst_bcm = None if args.no_rst else args.rst_bcm
        try:
            import RPi.GPIO as GPIO
        except ImportError:
            parser.error(
                "RPi.GPIO is unavailable; run ./systemd/install-pi-dependencies.sh"
            )
        if args.reset_effect:
            raise SystemExit(run_reset_effect(GPIO, pins, rst_bcm))
        if args.line_check:
            raise SystemExit(run_line_check(GPIO, pins, rst_bcm))
        raise SystemExit(run_bitbang(GPIO, pins, rst_bcm))
    if args.loopback or args.clock_test:
        if not args.confirm_disconnected:
            parser.error(
                "--loopback and --clock-test require --confirm-disconnected after "
                "removing all RC522 connections and bridging the two physical pins"
            )
        try:
            import spidev
        except ImportError:
            parser.error("spidev is unavailable; run ./systemd/install-pi-dependencies.sh")
        if args.loopback:
            raise SystemExit(run_loopback(spidev))
        raise SystemExit(run_clock_test(spidev))
    raise SystemExit(run(args.seconds, None if args.no_rst else args.rst_bcm))


if __name__ == "__main__":
    main()
