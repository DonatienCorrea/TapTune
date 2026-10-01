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
    """Simulates reading a line that either floats or is actively driven."""

    PUD_UP = "UP"
    PUD_DOWN = "DOWN"

    def __init__(self, driven_level=None):
        super().__init__(0x92)
        self.driven_level = driven_level
        self.pull = None

    def setup(self, pin, direction, initial=None, pull_up_down=None):
        if pull_up_down is not None:
            self.pull = pull_up_down
        super().setup(pin, direction, initial=initial)

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
    """Simulates MISO either reacting to the reset edge or ignoring it."""

    PUD_UP = "UP"
    PUD_DOWN = "DOWN"

    def __init__(self, reacts):
        super().__init__(0x92)
        self.reacts = reacts

    def setup(self, pin, direction, initial=None, pull_up_down=None):
        super().setup(pin, direction, initial=initial)

    def input(self, pin):
        if not self.reacts:
            return self.LOW
        return self.HIGH if self.levels.get(25) == self.HIGH else self.LOW


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
        changed, _, _ = rc522_diag.interpret_reset_effect((0, 1))

        self.assertTrue(changed)
        self.assertEqual(rc522_diag.run_reset_effect(ResetEffectGpio(True)), 0)

    def test_reset_effect_detects_an_unreachable_reset(self):
        changed, _, _ = rc522_diag.interpret_reset_effect((0, 0))

        self.assertFalse(changed)
        self.assertEqual(rc522_diag.run_reset_effect(ResetEffectGpio(False)), 2)

    def test_reset_effect_samples_before_and_after_release(self):
        gpio = ResetEffectGpio(True)

        readings = rc522_diag.probe_miso_across_reset(gpio, 9, 8, 25)

        self.assertEqual(readings, (0, 1))
        self.assertEqual(gpio.levels[8], gpio.LOW)

    def test_reset_effect_requires_a_reset_pin(self):
        self.assertEqual(rc522_diag.run_reset_effect(ResetEffectGpio(True), rst_bcm=None), 1)


if __name__ == "__main__":
    unittest.main()
