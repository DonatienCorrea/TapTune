import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import bluetooth, config, speaker_pairing
from app.web import create_app

MAC = "AA:BB:CC:DD:EE:FF"
OLD = "11:22:33:44:55:66"


def done(output="", code=0, stderr=""):
    return subprocess.CompletedProcess([], code, output, stderr)


class FakeBluez:
    """A tiny bluetoothctl: devices appear on scan and keep paired/trusted/connected state."""

    def __init__(self, nearby=None, pair_works=True, connect_works=True, powered=True, known=None):
        self.nearby = nearby if nearby is not None else {
            MAC: {"Name": "JBL Flip 5", "Icon": "audio-card"},
            "00:11:22:33:44:55": {"Name": "Phone", "Icon": "phone"},
            "66:55:44:33:22:11": {"Icon": "audio-card"},
            "77:66:55:44:33:22": {"Name": "Sonos", "UUIDs": ["Audio Sink                (0000110b-0000-1000-8000-00805f9b34fb)"]},
        }
        self.known = dict(known or {})
        self.pair_works = pair_works
        self.connect_works = connect_works
        self.powered = powered
        self.commands = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        if command[0] == "sudo":
            return done()
        args = [a for a in command[1:]]
        if args[:1] == ["--timeout"]:
            args = args[2:]
        mac = args[1] if len(args) > 1 else None
        if args == ["power", "on"]:
            return done() if self.powered else done(code=1, stderr="org.bluez.Error.Failed")
        if args == ["scan", "on"]:
            for address, device in self.nearby.items():
                self.known.setdefault(address, dict(device))
            return done("Discovery started")
        if args == ["devices"]:
            return done("".join(f"Device {a} {d.get('Name', a.replace(':', '-'))}\n" for a, d in self.known.items()))
        device = self.known.get(mac)
        if args[0] == "info":
            if device is None:
                return done(f"Device {mac} not available", code=1)
            lines = [f"Device {mac} (public)"]
            for key in ("Name", "Alias", "Icon"):
                if key in device:
                    lines.append(f"\t{key}: {device[key]}")
            for key in ("Paired", "Trusted", "Connected"):
                lines.append(f"\t{key}: {'yes' if device.get(key) else 'no'}")
            lines += [f"\tUUID: {uuid}" for uuid in device.get("UUIDs", [])]
            return done("\n".join(lines) + "\n")
        if device is None:
            return done(code=1, stderr="Device not available")
        if args[0] == "pair":
            device["Paired"] = self.pair_works
            return done() if self.pair_works else done(code=1, stderr="Failed to pair: org.bluez.Error.AuthenticationFailed")
        if args[0] == "trust":
            device["Trusted"] = True
            return done()
        if args[0] == "connect":
            device["Connected"] = self.connect_works
            return done() if self.connect_works else done(code=1, stderr="org.bluez.Error.Failed")
        if args[0] == "disconnect":
            device["Connected"] = False
            return done()
        return done(code=1)


class ScanTests(unittest.TestCase):
    def test_lists_only_named_audio_outputs_paired_first(self):
        bluez = FakeBluez(known={OLD: {"Name": "Old speaker", "Icon": "audio-card", "Paired": True}})
        speakers = speaker_pairing.scan_speakers(bluez, seconds=1)
        self.assertEqual([s["name"] for s in speakers], ["Old speaker", "JBL Flip 5", "Sonos"])
        self.assertTrue(speakers[0]["paired"])
        self.assertIn(["bluetoothctl", "--timeout", "1", "scan", "on"], bluez.commands)

    def test_adapter_off_is_reported(self):
        with self.assertRaises(speaker_pairing.PairingError) as caught:
            speaker_pairing.scan_speakers(FakeBluez(powered=False), seconds=1)
        self.assertEqual(caught.exception.code, "adapter_unavailable")

    def test_only_one_bluetooth_operation_at_a_time(self):
        speaker_pairing._lock.acquire()
        self.addCleanup(speaker_pairing._lock.release)
        with self.assertRaises(speaker_pairing.PairingBusy):
            speaker_pairing.scan_speakers(FakeBluez(), seconds=1)


class PairTests(unittest.TestCase):
    def test_pairs_trusts_and_connects_rescanning_a_forgotten_device(self):
        bluez = FakeBluez()
        speaker = speaker_pairing.pair_speaker(MAC.lower(), bluez, sleep=lambda s: None)
        self.assertEqual(speaker, {"mac": MAC, "name": "JBL Flip 5"})
        device = bluez.known[MAC]
        self.assertTrue(device["Paired"] and device["Trusted"] and device["Connected"])
        verbs = [c[3] if c[1] == "--timeout" else c[1] for c in bluez.commands if c[0] == "bluetoothctl"]
        self.assertEqual([v for v in verbs if v != "info"], ["power", "scan", "pair", "trust", "connect"])

    def test_already_paired_speaker_is_not_paired_again(self):
        bluez = FakeBluez(known={MAC: {"Name": "JBL", "Icon": "audio-card", "Paired": True, "Trusted": True}})
        speaker_pairing.pair_speaker(MAC, bluez, sleep=lambda s: None)
        self.assertFalse(any("pair" in c for c in bluez.commands))

    def test_failures_have_codes(self):
        cases = [
            (FakeBluez(nearby={}), "not_found"),
            (FakeBluez(pair_works=False), "pair_failed"),
            (FakeBluez(connect_works=False), "connect_failed"),
        ]
        for bluez, code in cases:
            with self.subTest(code=code), self.assertRaises(speaker_pairing.PairingError) as caught:
                speaker_pairing.pair_speaker(MAC, bluez, sleep=lambda s: None)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(speaker_pairing.PairingError) as caught:
            speaker_pairing.pair_speaker("AA:BB; rm -rf /", FakeBluez())
        self.assertEqual(caught.exception.code, "invalid_mac")


RASPOTIFY = (
    "LIBRESPOT_QUIET=\n"
    "# >>> TapTune >>>\n"
    'LIBRESPOT_NAME="TapTune"\n'
    'LIBRESPOT_DEVICE="bluealsa:DEV=11:22:33:44:55:66,PROFILE=a2dp"\n'
    "# <<< TapTune <<<\n"
)


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.env = Path(self.dir.name) / ".env"
        self.env.write_text(f"SPOTIFY_CLIENT_SECRET=keep\nBLUETOOTH_SPEAKER_MAC={OLD}\n")
        self.conf = Path(self.dir.name) / "conf"
        self.conf.write_text(RASPOTIFY)
        for p in (patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", OLD),
                  patch.object(config.settings, "DESKTOP_AUDIO_USER", "")):
            p.start()
            self.addCleanup(p.stop)

    def test_lite_saves_mac_switches_receiver_and_drops_old_speaker(self):
        bluez = FakeBluez(known={OLD: {"Name": "Old", "Connected": True}})
        bluetooth._output_volume_set[0] = True
        self.assertEqual(speaker_pairing.save_speaker(MAC.lower(), self.env, self.conf, bluez), "updated")
        self.assertEqual(self.env.read_text(), f"SPOTIFY_CLIENT_SECRET=keep\nBLUETOOTH_SPEAKER_MAC={MAC}\n")
        self.assertEqual(config.settings.BLUETOOTH_SPEAKER_MAC, MAC)
        self.assertFalse(bluetooth._output_volume_set[0])
        self.assertEqual(self.conf.read_text(), RASPOTIFY.replace(OLD, MAC))
        self.assertIn(["sudo", "-n", "systemctl", "--no-block", "restart", "raspotify.service"], bluez.commands)
        self.assertFalse(bluez.known[OLD]["Connected"])
        self.assertEqual(speaker_pairing.update_lite_receiver(MAC, self.conf, bluez), "unchanged")

    def test_desktop_and_custom_outputs_leave_raspotify_alone(self):
        with patch.object(config.settings, "DESKTOP_AUDIO_USER", "pi"):
            self.assertEqual(speaker_pairing.save_speaker(MAC, self.env, self.conf, FakeBluez()), "absent")
        self.assertEqual(self.conf.read_text(), RASPOTIFY)
        self.conf.write_text(RASPOTIFY.replace("bluealsa:DEV=11:22:33:44:55:66,PROFILE=a2dp", "hw:1"))
        self.assertEqual(speaker_pairing.update_lite_receiver(MAC, self.conf, FakeBluez()), "absent")
        self.assertEqual(speaker_pairing.update_lite_receiver(MAC, Path(self.dir.name) / "none", FakeBluez()), "absent")

    def test_rejected_raspotify_restart_is_reported(self):
        failing = lambda command, **kwargs: done(code=1)  # noqa: E731
        self.assertEqual(speaker_pairing.update_lite_receiver(MAC, self.conf, failing), "failed")


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def post(self, path, body=None, **headers):
        return self.client.post(path, json=body or {}, headers=headers)

    def test_scan_and_pair_save_only_the_validated_mac(self):
        with patch("app.speaker_pairing.scan_speakers", return_value=[{"mac": MAC, "name": "JBL"}]):
            self.assertEqual(self.post("/api/setup/speaker/scan").get_json()["speakers"][0]["mac"], MAC)
        with patch("app.speaker_pairing.pair_speaker", return_value={"mac": MAC, "name": "JBL"}) as pair, \
                patch("app.speaker_pairing.save_speaker", return_value="absent") as save:
            response = self.post("/api/setup/speaker/pair", {"mac": MAC, "SPOTIFY_CLIENT_ID": "x"})
        self.assertEqual(response.get_json(), {"speaker": {"mac": MAC, "name": "JBL"}, "receiver": "absent"})
        pair.assert_called_once_with(MAC)
        save.assert_called_once_with(MAC)

    def test_errors_and_cross_site_requests(self):
        with patch("app.speaker_pairing.pair_speaker") as pair:
            self.assertEqual(self.post("/api/setup/speaker/pair", {"mac": MAC}, Origin="http://evil.example").status_code, 403)
            self.assertEqual(self.client.post("/api/setup/speaker/pair", data={"mac": MAC}).status_code, 403)
            pair.assert_not_called()
        self.assertEqual(self.post("/api/setup/speaker/pair", {"mac": "nope"}).get_json(), {"error": "invalid_mac"})
        with patch("app.speaker_pairing.scan_speakers", side_effect=speaker_pairing.PairingBusy):
            self.assertEqual(self.post("/api/setup/speaker/scan").status_code, 409)
        with patch("app.speaker_pairing.pair_speaker", side_effect=speaker_pairing.PairingError("pair_failed", "x")):
            response = self.post("/api/setup/speaker/pair", {"mac": MAC})
        self.assertEqual((response.status_code, response.get_json()), (502, {"error": "pair_failed"}))

    def test_test_sound(self):
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", ""):
            self.assertEqual(self.post("/api/setup/speaker/test").status_code, 409)
        with patch.object(config.settings, "BLUETOOTH_SPEAKER_MAC", MAC), \
                patch("app.readiness.play_ready_sound", return_value=True) as play:
            self.assertTrue(self.post("/api/setup/speaker/test").get_json()["played"])
        play.assert_called_once()

    def test_setup_page_offers_pairing_and_change_in_both_languages(self):
        steps = [{"id": "bluetooth", "state": "done", "reason": "connected", "detail": MAC}]
        with patch("app.setup.setup_steps", return_value=steps), patch("app.setup.mark_complete"):
            en = self.client.get("/setup").get_data(as_text=True)
            fr = self.client.get("/fr/setup").get_data(as_text=True)
        self.assertIn("Change speaker", en)
        self.assertIn("Search for speakers", en)
        self.assertIn("Changer d’enceinte", fr)
        self.assertIn("Rechercher les enceintes", fr)
        with patch("app.setup.setup_steps", return_value=[{"id": "bluetooth", "state": "todo", "reason": "not_configured"}]):
            first = self.client.get("/setup").get_data(as_text=True)
        self.assertNotIn("Change speaker", first)
        self.assertRegex(first, r'id="speaker-pairing"\s*>')
        with patch("app.setup.setup_steps", return_value=[{"id": "bluetooth", "state": "todo", "reason": "not_configured"}]):
            first_fr = self.client.get("/fr/setup").get_data(as_text=True)
        self.assertNotIn("BLUETOOTH_SPEAKER_MAC", first)
        self.assertNotIn("BLUETOOTH_SPEAKER_MAC", first_fr)


if __name__ == "__main__":
    unittest.main()
