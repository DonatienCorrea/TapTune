import queue
import re
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch

from app import wifi_setup as wifi
from app.wifi_portal import PORTAL_URL, create_portal


class NetworkCommands:
    """Small stateful fake for the NetworkManager and nftables commands we use."""

    def __init__(self, uplink=None):
        self.uplink = uplink
        self.hotspot = False
        self.firewall = False
        self.failed_profile = None
        self.calls = []
        self.credentials = []

    def __call__(self, command, input=None, **kwargs):
        self.calls.append(command)
        success, output = True, ""
        if command[0] == "nft":
            args = command[1:]
            if args == ["list", "tables"]:
                output = f"table inet {wifi.FIREWALL_TABLE}\n" if self.firewall else ""
            elif args == ["-f", "-"]:
                assert f'iifname "wlan0" ip saddr {wifi.HOTSPOT_SUBNET}' in input
                assert 'iifname "wlan0" drop' in input
                self.firewall = True
            elif args == ["delete", "table", "inet", wifi.FIREWALL_TABLE]:
                assert not self.hotspot
                self.firewall = False
            else:
                raise AssertionError(args)
        else:
            args = command[3:]
            if args[-2:] == ["device", "status"]:
                output = "wlan0:wifi:disconnected:\n"
                if self.uplink == "wifi":
                    output = "wlan0:wifi:connected:Home:with colon\n"
                elif self.uplink == "ethernet":
                    output += "eth0:ethernet:connected:Wired\n"
            elif args[:2] == ["-g", "WIFI-PROPERTIES.AP"]:
                output = "yes\n"
            elif args[:7] == ["-t", "--escape", "no", "-f", "SSID", "device", "wifi"]:
                assert not self.hotspot
                output = "Home:café\nHome:café\nGuest\nTapTune-Setup\n"
            elif args[:4] == ["connection", "up", "uuid", wifi.HOTSPOT_UUID]:
                assert self.firewall
                self.hotspot = True
            elif args[-3:] == ["connection", "show", "--active"]:
                output = wifi.HOTSPOT_UUID + "\n" if self.hotspot else ""
            elif args == ["connection", "down", "uuid", wifi.HOTSPOT_UUID]:
                self.hotspot = False
            elif args[:3] == ["connection", "delete", "id"]:
                assert self.failed_profile == args[3]
                self.failed_profile = None
            elif args[-3:] == ["NAME", "connection", "show"]:
                output = self.failed_profile + "\n"
            elif args[:4] == ["--ask", "device", "wifi", "connect"] or args[:3] == ["device", "wifi", "connect"]:
                assert not self.hotspot and not self.firewall
                assert input is None or input.rstrip("\n") not in command
                self.credentials.append(input)
                success = input != "bad-passphrase\n"
                if not success:
                    self.failed_profile = args[args.index("name") + 1]
            else:
                raise AssertionError(args)
        return subprocess.CompletedProcess(command, 0 if success else 1, output, "")


class WifiSetupTests(unittest.TestCase):
    def test_known_uplink_avoids_hotspot_even_after_boot_deadline(self):
        for uplink in ("wifi", "ethernet"):
            with self.subTest(uplink=uplink):
                runner = NetworkCommands(uplink)
                portal = Mock()
                wifi.WifiSetup(runner).run(portal, uptime=lambda: 61)
                portal.assert_not_called()
                self.assertEqual(len(runner.calls), 2)

    def test_waits_for_boot_grace_scans_before_ap_and_recovers_after_failed_join(self):
        runner = NetworkCommands()
        portal = Mock(side_effect=[("Home:café", "bad-passphrase"), ("Home:café", "correct-passphrase")])
        sleep = Mock()
        with self.assertLogs(wifi.logger, "INFO") as logs:
            wifi.WifiSetup(runner).run(portal, uptime=Mock(side_effect=[55, 58, 60]), sleep=sleep)
        self.assertEqual(sleep.call_args_list, [call(3), call(2)])
        self.assertEqual(portal.call_args_list, [
            call("wlan0", ("Home:café", "Guest"), False),
            call("wlan0", ("Home:café", "Guest"), True),
        ])
        self.assertEqual(runner.credentials, ["bad-passphrase\n", "correct-passphrase\n"])
        self.assertIsNone(runner.failed_profile)
        self.assertFalse(runner.hotspot)
        self.assertFalse(runner.firewall)
        self.assertNotIn("passphrase", "\n".join(logs.output))

    def test_hotspot_start_error_cleans_up_the_isolation_rules(self):
        commands = NetworkCommands()

        def runner(args, **kwargs):
            if args[3:6] == ["connection", "up", "uuid"]:
                return subprocess.CompletedProcess(args, 1, "", "")
            return commands(args, **kwargs)

        portal = Mock()
        with self.assertLogs(wifi.logger, "ERROR"):
            wifi.WifiSetup(runner).run(portal, uptime=lambda: 60)
        self.assertFalse(commands.firewall)
        portal.assert_not_called()

    def test_cleanup_leaves_isolation_installed_when_hotspot_cannot_stop(self):
        commands = NetworkCommands()
        commands.firewall = commands.hotspot = True

        def runner(args, **kwargs):
            if args[3:6] == ["connection", "down", "uuid"]:
                return subprocess.CompletedProcess(args, 1, "", "")
            return commands(args, **kwargs)

        with self.assertRaises(wifi.WifiSetupError):
            wifi.WifiSetup(runner).cleanup()
        self.assertTrue(commands.firewall)

    def test_provision_keeps_per_pi_key_private_and_preserves_it_on_reinstall(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "setup.nmconnection"
            runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
            wifi.provision(profile, runner)
            contents = profile.read_text()
            self.assertRegex(contents, r"\npsk=[a-f0-9]{20}\n")
            self.assertEqual(stat.S_IMODE(profile.stat().st_mode), 0o600)
            wifi.provision(profile, runner)
            self.assertEqual(profile.read_text(), contents)
            self.assertEqual(runner.call_args.args[0][-3:], ["connection", "load", str(profile)])


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.jobs = queue.Queue(maxsize=1)
        self.networks = ("Home:café", '"><img src=x>', "Guest")
        self.active = Mock(return_value=True)
        with patch("app.wifi_portal.socket.gethostname", return_value="jukebox"):
            self.client = create_portal(self.networks, False, self.jobs, self.active).test_client()
        self.options = {"base_url": PORTAL_URL, "environ_overrides": {"REMOTE_ADDR": "10.42.66.20"}}
        response = self.client.get("/setup", **self.options)
        self.token = re.search(r'name="token" value="([^"]+)"', response.get_data(as_text=True))[1]

    def test_probe_redirection_uses_fixed_hotspot_address_and_only_serves_setup(self):
        response = self.client.get("/generate_204", **{**self.options, "base_url": "http://probe.example"})
        self.assertEqual(response.headers["Location"], PORTAL_URL + "/setup")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(self.client.get("/api/setup", **self.options).headers["Location"], PORTAL_URL + "/setup")
        with self.client.get("/static/style.css", **self.options) as style:
            self.assertEqual(style.status_code, 200)
        page = self.client.get("/fr/setup", **self.options).get_data(as_text=True)
        self.assertIn("Mot de passe Wi-Fi", page)
        self.assertIn("Home:café", page)
        self.assertNotIn("<img src=x>", page)

    def test_writes_require_hotspot_peer_canonical_host_and_same_origin_token(self):
        valid = {"token": self.token, "network": "Guest", "password": "test-password"}
        for options, data, headers in (
            ({**self.options, "environ_overrides": {"REMOTE_ADDR": "192.168.1.20"}}, valid,
             {"X-Forwarded-For": "10.42.66.20"}),
            ({**self.options, "base_url": "http://other.example"}, valid, {}),
            (self.options, valid, {"Origin": "http://other.example"}),
            (self.options, {**valid, "token": ""}, {}),
        ):
            with self.subTest(options=options, headers=headers):
                self.assertEqual(self.client.post("/setup", data=data, headers=headers, **options).status_code, 403)
        self.assertTrue(self.jobs.empty())
        self.active.assert_not_called()

    def test_rejects_submission_if_networkmanager_no_longer_has_the_hotspot_up(self):
        self.active.return_value = False
        response = self.client.post("/setup", data={"token": self.token, "network": "Guest"}, **self.options)
        self.assertEqual(response.status_code, 503)
        self.assertIn("The setup hotspot is no longer active.", response.get_data(as_text=True))
        self.assertTrue(self.jobs.empty())

    def test_submits_after_flushing_response_and_shows_locale_handoff_without_password(self):
        form = {"token": self.token, "ssid": " Other café ", "network": "Guest", "password": "secret password"}
        response = self.client.post("/fr/setup", data=form, **self.options)
        self.assertEqual(response.status_code, 202)
        self.assertTrue(self.jobs.empty())
        self.assertIn("http://jukebox.local:5000/fr/", response.get_data(as_text=True))
        self.assertNotIn("secret password", response.get_data(as_text=True))
        duplicate = self.client.post("/setup", data=form, **self.options)
        self.assertEqual(duplicate.status_code, 409)
        response.close()
        self.assertEqual(self.jobs.get_nowait(), (" Other café ", "secret password"))

    def test_invalid_byte_lengths_and_reserved_hotspot_name_do_not_enqueue_attempts(self):
        for ssid, password in (("é" * 17, ""), ("Guest", "short"), (wifi.HOTSPOT_SSID, "")):
            with self.subTest(ssid=ssid, password=password):
                response = self.client.post("/setup", data={
                    "token": self.token, "ssid": ssid, "password": password,
                }, **self.options)
                self.assertEqual(response.status_code, 400)
                self.assertIn("Check your entries", response.get_data(as_text=True))
        self.assertTrue(self.jobs.empty())

    def test_recovered_portal_shows_retry_and_manual_entry_without_scan_results(self):
        recovered = create_portal((), True, self.jobs, self.active).test_client()
        page = recovered.get("/setup", **self.options).get_data(as_text=True)
        self.assertIn("Could not connect", page)
        self.assertIn('name="ssid"', page)
        self.assertNotIn("<select", page)
