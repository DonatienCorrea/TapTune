import unittest

from app import rc522_diag


class FakeSpi:
    def __init__(self, version):
        self.version = version
        self.mode = None
        self.max_speed_hz = None

    def open(self, bus, device):
        self.device = device

    def close(self):
        pass

    def xfer2(self, values):
        register = (values[0] & 0x7E) >> 1
        if values[0] & 0x80 and register == rc522_diag.VERSION_REG:
            return [0, self.version]
        return [0, 0]


class FakeSpidevModule:
    def __init__(self, version):
        self.version = version

    def SpiDev(self):
        return FakeSpi(self.version)


class LoopbackSpi:
    def open(self, bus, device):
        self.bus = bus
        self.device = device

    def close(self):
        pass

    def xfer2(self, values):
        return values


class LoopbackSpidevModule:
    def SpiDev(self):
        return LoopbackSpi()


class FakeBitBangGpio:
    """Simulates an RC522 answering a bit-banged SPI read of one register."""

    BCM = "BCM"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0

    def __init__(self, response):
        self.response = response
        self.levels = {}
        self.rising_edges = 0
        self.command = 0
        self.cs_asserted = False
        self.cleaned = []

    def setmode(self, mode):
        self.mode = mode

    def setup(self, pin, direction, initial=None):
        if initial is not None:
            self.levels[pin] = initial

    def cleanup(self, pin):
        self.cleaned.append(pin)

    def output(self, pin, value):
        if pin == 8:
            self.cs_asserted = value == self.LOW
        if pin == 11 and value == self.HIGH:
            self.rising_edges += 1
            if self.rising_edges <= 8:
                self.command = (self.command << 1) | self.levels.get(10, 0)
        self.levels[pin] = value

    def input(self, pin):
        if pin != 9 or not self.cs_asserted or self.rising_edges <= 8:
            return self.LOW
        index = self.rising_edges - 9
        if index > 7:
            return self.LOW
        return (self.response >> (7 - index)) & 1


class SilentBitBangGpio(FakeBitBangGpio):
    def input(self, pin):
        return self.LOW


class FailingClaimGpio(FakeBitBangGpio):
    def __init__(self, failing_pin):
        super().__init__(0x92)
        self.failing_pin = failing_pin

    def setup(self, pin, direction, initial=None):
        if pin == self.failing_pin:
            raise OSError("Invalid argument")
        super().setup(pin, direction, initial=initial)


class PullProbeGpio(FakeBitBangGpio):
    """Simulates reading a line that either floats or is actively driven.

    Like the real driver, a pull is only applied while claiming a released pin,
    so a setup call on a pin that is still held leaves the previous pull alone.
    """

    PUD_UP = "UP"
    PUD_DOWN = "DOWN"

    def __init__(self, driven_level=None):
        super().__init__(0x92)
        self.driven_level = driven_level
        self.pull = None
        self.held = set()

    def setup(self, pin, direction, initial=None, pull_up_down=None):
        if pull_up_down is not None and pin not in self.held:
            self.pull = pull_up_down
        self.held.add(pin)
        super().setup(pin, direction, initial=initial)

    def cleanup(self, pin=None):
        self.held.discard(pin)

    def input(self, pin):
        if self.driven_level is not None:
            return self.driven_level
        return self.HIGH if self.pull == self.PUD_UP else self.LOW


class ResetTrackingGpio(FakeBitBangGpio):
    def __init__(self, response=0x92):
        super().__init__(response)
        self.rst_sequence = []

    def setup(self, pin, direction, initial=None, pull_up_down=None):
        if pin == 25 and initial is not None:
            self.rst_sequence.append(initial)
        super().setup(pin, direction, initial=initial)

    def output(self, pin, value):
        if pin == 25:
            self.rst_sequence.append(value)
        super().output(pin, value)


class ResetEffectGpio(FakeBitBangGpio):
    """Simulates MISO reacting to the reset edge, ignoring it, or floating."""

    PUD_UP = "UP"
    PUD_DOWN = "DOWN"

    def __init__(self, behaviour):
        super().__init__(0x92)
        self.behaviour = behaviour
        self.pull = None
        self.held = set()

    def setup(self, pin, direction, initial=None, pull_up_down=None):
        if pull_up_down is not None and pin not in self.held:
            self.pull = pull_up_down
        self.held.add(pin)
        super().setup(pin, direction, initial=initial)

    def cleanup(self, pin=None):
        self.held.discard(pin)

    def input(self, pin):
        if self.behaviour == "floating":
            return self.HIGH if self.pull == self.PUD_UP else self.LOW
        if self.behaviour == "frozen":
            return self.LOW
        return self.HIGH if self.levels.get(25) == self.HIGH else self.LOW


class ChipSelectGpio(FakeBitBangGpio):
    """Simulates MISO driven only while selected, never driven, or always held."""

    PUD_UP = "UP"
    PUD_DOWN = "DOWN"

    def __init__(self, behaviour):
        super().__init__(0x92)
        self.behaviour = behaviour
        self.pull = None
        self.held = set()
        self.cs_states = []

    def setup(self, pin, direction, initial=None, pull_up_down=None):
        if pull_up_down is not None and pin not in self.held:
            self.pull = pull_up_down
        self.held.add(pin)
        super().setup(pin, direction, initial=initial)

    def cleanup(self, pin=None):
        self.held.discard(pin)

    def _floating(self):
        return self.HIGH if self.pull == self.PUD_UP else self.LOW

    def input(self, pin):
        selected = self.levels.get(8) == self.LOW
        self.cs_states.append(selected)
        if self.behaviour == "always_driven":
            return self.LOW
        if self.behaviour == "selected_only" and selected:
            return self.LOW
        return self._floating()


class FakeI2CBus:
    """Simulates an I2C device that answers, stays silent, or is absent."""

    def __init__(self, version=None, openable=True):
        self.version = version
        self.openable = openable
        self.closed = False
        self.probed = None

    def __call__(self, bus):
        self.bus = bus
        return self

    def open(self):
        if not self.openable:
            raise OSError("No such file or directory")

    def close(self):
        self.closed = True

    def read_register(self, address, register):
        self.probed = (address, register)
        if self.version is None:
            raise OSError("Remote I/O error")
        return self.version


class RC522DiagnosticTests(unittest.TestCase):
    def test_scan_buses_accepts_recognized_reader_versions(self):
        connections = rc522_diag.scan_buses(FakeSpidevModule(0x92))

        self.assertEqual(len(connections), 6)
        self.assertEqual(connections[0], rc522_diag.ReaderConnection(0, 1_000_000, 0x92))

    def test_scan_buses_rejects_unknown_nonzero_values(self):
        connections = rc522_diag.scan_buses(FakeSpidevModule(0x42))

        self.assertEqual(connections, [])

    def test_register_address_encoding(self):
        spi = FakeSpi(0x91)

        self.assertEqual(rc522_diag.read_reg(spi, rc522_diag.VERSION_REG), 0x91)

    def test_loopback_passes_when_received_bytes_match(self):
        result = rc522_diag.run_loopback(LoopbackSpidevModule())

        self.assertEqual(result, 0)

    def test_clock_test_passes_when_any_byte_is_non_zero(self):
        self.assertTrue(rc522_diag.interpret_clock_bytes([0x00, 0xFF, 0x00, 0x00]))

    def test_clock_test_fails_when_all_bytes_are_zero(self):
        self.assertFalse(rc522_diag.interpret_clock_bytes([0x00, 0x00, 0x00, 0x00]))

    def test_bitbang_sends_the_version_read_command(self):
        gpio = FakeBitBangGpio(0x92)
        bus = rc522_diag.BitBangBus(gpio, delay=0)
        bus.setup()

        bus.read_register(rc522_diag.VERSION_REG)

        self.assertEqual(gpio.command, 0xEE)
        self.assertEqual(gpio.levels[8], gpio.HIGH)

    def test_bitbang_reads_a_recognized_version(self):
        gpio = FakeBitBangGpio(0x92)
        bus = rc522_diag.BitBangBus(gpio, delay=0)
        bus.setup()

        self.assertEqual(bus.read_register(rc522_diag.VERSION_REG), 0x92)

    def test_bitbang_run_reports_success_for_a_responding_reader(self):
        self.assertEqual(rc522_diag.run_bitbang(FakeBitBangGpio(0x92)), 0)

    def test_bitbang_run_reports_no_response_when_miso_stays_low(self):
        self.assertEqual(rc522_diag.run_bitbang(SilentBitBangGpio(0x92)), 2)

    def test_bitbang_reports_which_pin_could_not_be_claimed(self):
        gpio = FailingClaimGpio(11)
        bus = rc522_diag.BitBangBus(gpio, delay=0)

        with self.assertRaises(rc522_diag.PinClaimError) as caught:
            bus.setup()

        self.assertEqual(caught.exception.pin, 11)
        self.assertEqual(caught.exception.label, "SCK")

    def test_bitbang_run_fails_cleanly_when_pins_are_unavailable(self):
        self.assertEqual(rc522_diag.run_bitbang(FailingClaimGpio(8)), 1)

    def test_bitbang_accepts_custom_pins(self):
        self.assertEqual(rc522_diag.parse_bitbang_pins("5,6,13,19"), (5, 6, 13, 19))

    def test_bitbang_pins_reject_duplicates_and_bad_counts(self):
        for value in ("5,6,13", "5,5,13,19", "5,6,13,99", "a,b,c,d"):
            with self.assertRaises(ValueError):
                rc522_diag.parse_bitbang_pins(value)

    def test_bitbang_uses_the_custom_pins_it_is_given(self):
        gpio = FakeBitBangGpio(0x92)
        bus = rc522_diag.BitBangBus(gpio, sck=5, mosi=6, miso=13, cs=19, delay=0)
        bus.setup()
        bus.cleanup()

        self.assertEqual(sorted(gpio.cleaned), [5, 6, 13, 19])

    def test_line_check_detects_a_floating_miso(self):
        driven, _, _ = rc522_diag.interpret_line((1, 0))

        self.assertFalse(driven)
        self.assertEqual(rc522_diag.run_line_check(PullProbeGpio()), 2)

    def test_line_check_detects_an_actively_driven_miso(self):
        driven, _, _ = rc522_diag.interpret_line((0, 0))

        self.assertTrue(driven)
        self.assertEqual(rc522_diag.run_line_check(PullProbeGpio(driven_level=0)), 0)

    def test_line_check_probes_with_both_internal_resistors(self):
        gpio = PullProbeGpio()

        readings = rc522_diag.probe_line(gpio, 9, 8)

        self.assertEqual(readings, (1, 0))
        self.assertEqual(gpio.levels[8], gpio.LOW)

    def test_release_power_down_pulses_reset_low_then_high(self):
        gpio = ResetTrackingGpio()

        rc522_diag.release_power_down(gpio, 25)

        self.assertEqual(gpio.rst_sequence, [gpio.LOW, gpio.HIGH])

    def test_bitbang_releases_power_down_before_reading(self):
        gpio = ResetTrackingGpio()

        rc522_diag.run_bitbang(gpio)

        self.assertEqual(gpio.rst_sequence, [gpio.LOW, gpio.HIGH])
        self.assertIn(25, gpio.cleaned)

    def test_bitbang_skips_reset_when_disabled(self):
        gpio = ResetTrackingGpio()

        rc522_diag.run_bitbang(gpio, rst_bcm=None)

        self.assertEqual(gpio.rst_sequence, [])

    def test_reset_effect_detects_a_chip_that_reacts(self):
        changed, _, _ = rc522_diag.interpret_reset_effect(((0, 0), (1, 1)))

        self.assertTrue(changed)
        self.assertEqual(rc522_diag.run_reset_effect(ResetEffectGpio("reacts")), 0)

    def test_reset_effect_detects_an_unreachable_reset(self):
        changed, _, _ = rc522_diag.interpret_reset_effect(((0, 0), (0, 0)))

        self.assertFalse(changed)
        self.assertEqual(rc522_diag.run_reset_effect(ResetEffectGpio("frozen")), 2)

    def test_reset_effect_reports_a_floating_line_rather_than_a_dead_reset(self):
        changed, summary, detail = rc522_diag.interpret_reset_effect(((1, 0), (1, 0)))

        self.assertFalse(changed)
        self.assertIn("nothing", summary)
        self.assertIn("MISO jumper", detail)
        self.assertEqual(rc522_diag.run_reset_effect(ResetEffectGpio("floating")), 2)

    def test_reset_effect_samples_both_pulls_in_each_state(self):
        gpio = ResetEffectGpio("reacts")

        readings = rc522_diag.probe_miso_across_reset(gpio, 9, 8, 25)

        self.assertEqual(readings, ((0, 0), (1, 1)))
        self.assertEqual(gpio.levels[8], gpio.LOW)

    def test_line_check_releases_the_pin_between_pulls(self):
        gpio = PullProbeGpio()

        self.assertEqual(rc522_diag.probe_line(gpio, 9, 8), (1, 0))

    def test_reset_effect_requires_a_reset_pin(self):
        self.assertEqual(
            rc522_diag.run_reset_effect(ResetEffectGpio("reacts"), rst_bcm=None), 1
        )

    def test_chip_select_effect_recognises_a_slave_that_drives_only_when_selected(self):
        gpio = ChipSelectGpio("selected_only")

        readings = rc522_diag.probe_chip_select_effect(gpio, 9, 8)
        driven, summary, detail = rc522_diag.interpret_chip_select_effect(readings)

        self.assertEqual(readings, ((1, 0), (0, 0)))
        self.assertTrue(driven)
        self.assertIn("floats while deselected", summary)
        self.assertIn("output buffer", detail)
        self.assertEqual(rc522_diag.run_chip_select_effect(gpio), 0)

    def test_chip_select_effect_probes_both_selection_states(self):
        gpio = ChipSelectGpio("selected_only")

        rc522_diag.probe_chip_select_effect(gpio, 9, 8)

        self.assertEqual(gpio.cs_states, [False, False, True, True])

    def test_chip_select_effect_reports_a_line_nothing_drives_when_selected(self):
        gpio = ChipSelectGpio("floating")

        readings = rc522_diag.probe_chip_select_effect(gpio, 9, 8)
        driven, summary, detail = rc522_diag.interpret_chip_select_effect(readings)

        self.assertEqual(readings, ((1, 0), (1, 0)))
        self.assertFalse(driven)
        self.assertIn("whether chip select is high or low", summary)
        self.assertIn("3.3 V line", detail)
        self.assertEqual(rc522_diag.run_chip_select_effect(gpio), 2)

    def test_chip_select_effect_flags_a_line_held_even_when_deselected(self):
        gpio = ChipSelectGpio("always_driven")

        readings = rc522_diag.probe_chip_select_effect(gpio, 9, 8)
        driven, summary, detail = rc522_diag.interpret_chip_select_effect(readings)

        self.assertEqual(readings, ((0, 0), (0, 0)))
        self.assertTrue(driven)
        self.assertIn("both chip select states", summary)
        self.assertIn("short", detail)

    def test_chip_select_effect_reports_unstable_readings(self):
        driven, summary, _ = rc522_diag.interpret_chip_select_effect(((0, 0), (1, 0)))

        self.assertFalse(driven)
        self.assertIn("unstable", summary)

    def test_chip_select_effect_reports_a_failed_claim(self):
        self.assertEqual(rc522_diag.run_chip_select_effect(FailingClaimGpio(9)), 1)

    def test_spi_params_ignore_comments_and_keep_file_order(self):
        text = (
            "# dtparam=spi=on\n"
            "dtparam=spi=on\n"
            "dtparam=i2c_arm=on\n"
            "dtoverlay=spi0-1cs\n"
            "dtparam=spi=off\n"
        )

        self.assertEqual(
            rc522_diag.parse_spi_params(text),
            ["dtparam=spi=on", "dtoverlay=spi0-1cs", "dtparam=spi=off"],
        )

    def test_spi_status_is_enabled_when_the_bus_and_pins_agree(self):
        enabled, notes = rc522_diag.summarise_spi_status(
            "/boot/firmware/config.txt",
            ["dtparam=spi=on"],
            ["/dev/spidev0.0", "/dev/spidev0.1", "/dev/spidev10.0"],
            "spidev spi_dw",
            "7: a0 spi0\n9: a0 spi0",
        )

        self.assertTrue(enabled)
        self.assertIn("GPIO 7-11 are muxed to SPI0.", notes)

    def test_spi_status_ignores_the_boot_eeprom_bus(self):
        enabled, notes = rc522_diag.summarise_spi_status(
            "/boot/firmware/config.txt", [], ["/dev/spidev10.0"], "", "9: ip none"
        )

        self.assertFalse(enabled)
        self.assertIn(
            "Only the boot EEPROM bus is present; nothing is bound to the "
            "40-pin header.",
            notes,
        )

    def test_spi_status_flags_a_last_line_that_overrides_an_earlier_one(self):
        _, notes = rc522_diag.summarise_spi_status(
            "/boot/firmware/config.txt",
            ["dtparam=spi=on", "dtparam=spi=off"],
            ["/dev/spidev0.0"],
            "spidev",
            "9: a0 spi0",
        )

        self.assertIn("config.txt requests SPI off (/boot/firmware/config.txt).", notes)
        self.assertIn(
            "SPI is live but config.txt turns it off at the next boot.", notes
        )

    def test_spi_status_flags_a_pending_reboot(self):
        enabled, notes = rc522_diag.summarise_spi_status(
            "/boot/firmware/config.txt", ["dtparam=spi=on"], [], "", "9: ip none"
        )

        self.assertFalse(enabled)
        self.assertIn(
            "config.txt and the running kernel disagree; reboot to apply it.", notes
        )

    def test_spi_status_notes_a_missing_dtparam(self):
        _, notes = rc522_diag.summarise_spi_status(
            "/boot/firmware/config.txt", [], [], "", ""
        )

        self.assertIn(
            "No 'dtparam=spi=' line in config.txt; SPI is off unless an overlay "
            "enables it.",
            notes,
        )

    def test_i2c_check_identifies_a_chip_that_latched_i2c_mode(self):
        bus = FakeI2CBus(version=0x92)

        self.assertEqual(rc522_diag.run_i2c_check(bus), 0)
        self.assertEqual(bus.probed, (0x28, rc522_diag.VERSION_REG))
        self.assertTrue(bus.closed)

    def test_i2c_check_reports_silence(self):
        bus = FakeI2CBus(version=None)

        self.assertEqual(rc522_diag.run_i2c_check(bus), 2)
        self.assertTrue(bus.closed)

    def test_i2c_check_rejects_a_foreign_device(self):
        answered, summary, _ = rc522_diag.interpret_i2c_version(0x50)

        self.assertFalse(answered)
        self.assertIn("0x50", summary)

    def test_i2c_check_reports_a_disabled_bus(self):
        self.assertEqual(rc522_diag.run_i2c_check(FakeI2CBus(openable=False)), 1)

    def test_i2c_check_accepts_an_alternate_address(self):
        bus = FakeI2CBus(version=0x91)

        self.assertEqual(rc522_diag.run_i2c_check(bus, address=0x2A), 0)
        self.assertEqual(bus.probed, (0x2A, rc522_diag.VERSION_REG))


if __name__ == "__main__":
    unittest.main()
