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


if __name__ == "__main__":
    unittest.main()
