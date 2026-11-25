"""Boot-time NetworkManager fallback for Raspberry Pi OS."""

import argparse
import logging
import os
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)

HOTSPOT_SSID = "TapTune-Setup"
HOTSPOT_UUID = "bed69db1-17dc-419b-bbac-3eff35e29389"
HOTSPOT_ADDRESS = "10.42.66.1"
HOTSPOT_SUBNET = "10.42.66.0/24"
HOTSPOT_PROFILE = Path("/etc/NetworkManager/system-connections/taptune-setup.nmconnection")
FIREWALL_TABLE = "taptune_setup"
BOOT_WAIT = 60


class WifiSetupError(RuntimeError):
    pass


def valid_ssid(ssid: str) -> bool:
    return (
        0 < len(ssid.encode("utf-8")) <= 32
        and not any(ord(char) < 32 or ord(char) == 127 for char in ssid)
        and not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", ssid)
    )


def valid_password(password: str) -> bool:
    return (
        not password
        or bool(re.fullmatch(r"[0-9a-fA-F]{64}", password))
        or (8 <= len(password.encode("utf-8")) <= 63 and password.isprintable())
    )


class WifiSetup:
    def __init__(self, runner=subprocess.run):
        self.runner = runner

    def _command(self, args, *, timeout=8, stdin=None):
        try:
            result = self.runner(
                args, input=stdin, capture_output=True, encoding="utf-8", errors="replace",
                timeout=timeout, env={**os.environ, "LC_ALL": "C.UTF-8"},
            )
        except (OSError, subprocess.SubprocessError):
            return None
        # Neither the command results nor stdin belong in the journal: nmcli can echo secrets.
        return result.stdout if result.returncode == 0 else None

    def _nm(self, *args, wait=6, stdin=None):
        return self._command(["nmcli", "--wait", str(wait), *args], timeout=wait + 3, stdin=stdin)

    def _devices(self):
        output = self._nm("-t", "--escape", "no", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status")
        if output is None:
            return None
        return [line.split(":", 3) for line in output.splitlines() if line.count(":") >= 3]

    @staticmethod
    def _has_uplink(devices):
        return any(
            kind in {"wifi", "ethernet"} and state in {"connected", "connected (externally)"}
            and connection != HOTSPOT_SSID
            for _, kind, state, connection in devices
        )

    def _fallback_interface(self, uptime, sleep):
        while True:
            devices = self._devices()
            if devices is not None and self._has_uplink(devices):
                return None
            remaining = BOOT_WAIT - uptime()
            if remaining <= 0:
                break
            sleep(min(remaining, 3))
        if devices is None:
            raise WifiSetupError("NetworkManager is unavailable.")
        for name, kind, state, _ in devices:
            if (
                kind == "wifi" and state not in {"unmanaged", "unavailable"}
                and re.fullmatch(r"[\w.-]{1,15}", name, re.ASCII)
            ):
                ap = self._nm("-g", "WIFI-PROPERTIES.AP", "device", "show", name)
                if ap is not None and ap.strip() == "yes":
                    return name
        raise WifiSetupError("No managed Wi-Fi adapter supports hotspot mode. Check the WLAN country and radio.")

    def _scan(self, interface):
        output = self._nm("-t", "--escape", "no", "-f", "SSID", "device", "wifi", "list",
                          "ifname", interface, "--rescan", "yes", wait=12)
        if output is None:
            logger.warning("Wi-Fi scan failed; using the last scan results, if any.")
            return None
        return tuple(dict.fromkeys(
            ssid for ssid in output.split("\n") if ssid != HOTSPOT_SSID and valid_ssid(ssid)
        ))

    def _apply_firewall(self, interface):
        rules = f"""
table inet {FIREWALL_TABLE} {{
    chain input {{
        type filter hook input priority -10; policy accept;
        iifname "{interface}" meta nfproto ipv4 udp sport 68 udp dport 67 accept
        iifname "{interface}" ip saddr {HOTSPOT_SUBNET} ip daddr {HOTSPOT_ADDRESS} udp dport 53 accept
        iifname "{interface}" ip saddr {HOTSPOT_SUBNET} ip daddr {HOTSPOT_ADDRESS} tcp dport {{ 53, 80 }} accept
        iifname "{interface}" drop
    }}
    chain forward {{
        type filter hook forward priority -10; policy accept;
        iifname "{interface}" drop
        oifname "{interface}" drop
    }}
}}
"""
        if self._command(["nft", "-f", "-"], stdin=rules) is None:
            raise WifiSetupError("Could not isolate the hotspot with nftables.")

    def hotspot_is_active(self):
        active = self._nm("-t", "-f", "UUID", "connection", "show", "--active")
        if active is None:
            raise WifiSetupError("Could not check the active NetworkManager connections.")
        return HOTSPOT_UUID in active.splitlines()

    def cleanup(self):
        tables = self._command(["nft", "list", "tables"])
        if tables is None:
            raise WifiSetupError("Could not check the hotspot firewall.")
        if f"table inet {FIREWALL_TABLE}" not in tables.splitlines():
            return
        if self.hotspot_is_active() and self._nm("connection", "down", "uuid", HOTSPOT_UUID) is None:
            raise WifiSetupError("Could not stop the hotspot; its isolation firewall was left in place.")
        if self._command(["nft", "delete", "table", "inet", FIREWALL_TABLE]) is None:
            raise WifiSetupError("Could not remove the hotspot firewall.")

    def _connect(self, interface, ssid, password, hidden):
        # Use a new profile so a failed password cannot overwrite a saved connection.
        profile = f"TapTune Wi-Fi {uuid4().hex}"
        args = ["device", "wifi", "connect", ssid, "ifname", interface, "name", profile]
        if hidden:
            args.extend(("hidden", "yes"))
        if password:
            args.insert(0, "--ask")
        if self._nm(*args, wait=30, stdin=f"{password}\n" if password else None) is not None:
            logger.info("Wi-Fi setup connected to the selected network.")
            return True
        profiles = self._nm("-t", "--escape", "no", "-f", "NAME", "connection", "show")
        if profiles is None or (profile in profiles.splitlines() and self._nm(
            "connection", "delete", "id", profile,
        ) is None):
            logger.warning("Could not clean up the failed Wi-Fi profile; check NetworkManager.")
        logger.warning("Wi-Fi setup could not join the selected network; restoring the hotspot.")
        return False

    def run(self, wait_for_credentials, *, uptime=None, sleep=time.sleep):
        if uptime is None:
            uptime = lambda: time.clock_gettime(time.CLOCK_BOOTTIME)
        guarding = False
        try:
            # Recover from a previous process exit before judging the uplink.
            self.cleanup()
            interface = self._fallback_interface(uptime, sleep)
            if interface is None:
                return
            failed = False
            networks = ()
            while True:
                scanned = self._scan(interface)
                if scanned is not None:
                    networks = scanned
                devices = self._devices()
                if devices is None:
                    raise WifiSetupError("NetworkManager became unavailable after the Wi-Fi scan.")
                if self._has_uplink(devices):
                    return
                self._apply_firewall(interface)
                guarding = True
                if self._nm("connection", "up", "uuid", HOTSPOT_UUID, "ifname", interface, wait=15) is None:
                    raise WifiSetupError("NetworkManager could not start the TapTune-Setup hotspot.")
                logger.info("TapTune-Setup hotspot is active on %s.", interface)
                ssid, password = wait_for_credentials(interface, networks, failed)
                self.cleanup()
                guarding = False
                # Some radios lose their scan table when switching from AP to client mode.
                scanned = self._scan(interface)
                if scanned is not None:
                    networks = scanned
                if self._connect(interface, ssid, password, hidden=ssid not in networks):
                    return
                del password
                failed = True
        except (OSError, WifiSetupError) as error:
            logger.error("Wi-Fi setup stopped: %s", error)
        finally:
            if guarding:
                try:
                    self.cleanup()
                except WifiSetupError as error:
                    logger.error("Wi-Fi setup cleanup failed: %s", error)


def provision(path=HOTSPOT_PROFILE, runner=subprocess.run):
    if not path.exists():
        # A per-Pi WPA2 key protects the HTTP form on the local wireless link.
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(f"""[connection]
id={HOTSPOT_SSID}
uuid={HOTSPOT_UUID}
type=wifi
autoconnect=false

[wifi]
mode=ap
band=bg
ssid={HOTSPOT_SSID}

[wifi-security]
key-mgmt=wpa-psk
proto=rsn;
psk={secrets.token_hex(10)}

[ipv4]
method=manual
address1={HOTSPOT_ADDRESS}/24

[ipv6]
method=disabled
""")
                handle.flush()
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
    if WifiSetup(runner)._nm("connection", "load", str(path)) is None:
        raise WifiSetupError("NetworkManager could not load the TapTune-Setup profile.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("provision", "cleanup"))
    try:
        if parser.parse_args().action == "provision":
            provision()
        else:
            WifiSetup().cleanup()
    except (OSError, WifiSetupError) as error:
        parser.exit(1, f"error: {error}\n")
