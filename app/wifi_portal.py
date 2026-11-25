"""An HTTP listener reachable only on the TapTune setup hotspot."""

import ipaddress
import queue
import secrets
import socket
import subprocess
import threading
import time

from flask import Flask, abort, redirect, render_template, request
from werkzeug.serving import make_server

from .config import settings
from .wifi_setup import (
    HOTSPOT_ADDRESS, HOTSPOT_SSID, HOTSPOT_SUBNET, WifiSetup, WifiSetupError,
    valid_password, valid_ssid,
)

PORTAL_URL = f"http://{HOTSPOT_ADDRESS}"
PORTAL_NETWORK = ipaddress.ip_network(HOTSPOT_SUBNET)


def create_portal(networks, failed, submissions, hotspot_is_active):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    token = secrets.token_urlsafe(32)
    lock = threading.Lock()
    hostname = socket.gethostname().split(".", 1)[0]
    port = "" if settings.APP_PORT == 80 else f":{settings.APP_PORT}"
    lan_url = f"http://{hostname}.local{port}"

    @app.before_request
    def captive_redirect():
        try:
            peer = ipaddress.ip_address(request.remote_addr)
        except ValueError:
            abort(403)
        if peer not in PORTAL_NETWORK:
            abort(403)
        if request.host not in {HOTSPOT_ADDRESS, f"{HOTSPOT_ADDRESS}:80"} or request.path not in {
            "/setup", "/fr/setup", "/static/style.css",
        }:
            if request.method not in {"GET", "HEAD"}:
                abort(403)
            return redirect(f"{PORTAL_URL}/setup")

    @app.after_request
    def protect_response(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; img-src data:; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.route("/setup", methods=["GET", "POST"])
    @app.route("/fr/setup", methods=["GET", "POST"])
    def setup():
        locale = "fr" if request.path.startswith("/fr/") else "en"
        wifi = {
            "networks": networks, "token": token,
            "lan_url": lan_url + ("/fr/" if locale == "fr" else "/"),
            "state": "connecting" if lock.locked() else "failed" if failed else "ready",
        }

        def page(status=200):
            return app.make_response((render_template(
                "setup.html", locale=locale, switch_url="/setup" if locale == "fr" else "/fr/setup",
                action=request.path, wifi=wifi,
            ), status))

        if request.method != "POST":
            return page()
        if (
            request.mimetype != "application/x-www-form-urlencoded"
            or request.headers.get("Sec-Fetch-Site") == "cross-site"
            or request.headers.get("Origin", PORTAL_URL).rstrip("/") not in {PORTAL_URL, f"{PORTAL_URL}:80"}
            or not secrets.compare_digest(request.form.get("token", "").encode("utf-8"), token.encode("ascii"))
        ):
            abort(403)
        ssid = request.form.get("ssid") or request.form.get("network", "")
        password = request.form.get("password", "")
        if not valid_ssid(ssid) or not valid_password(password) or ssid == HOTSPOT_SSID:
            wifi["state"] = "invalid"
            wifi["ssid"] = ssid
            return page(400)
        try:
            active = hotspot_is_active()
        except WifiSetupError as error:
            app.logger.warning("Wi-Fi submission rejected: %s", error)
            active = False
        if not active:
            wifi["state"] = "offline"
            return page(503)
        if not lock.acquire(blocking=False):
            wifi["state"] = "connecting"
            return page(409)
        wifi["state"] = "connecting"
        response = page(202)
        # Start the radio handoff only once the response has been sent.
        response.call_on_close(lambda: submissions.put_nowait((ssid, password)))
        return response

    return app


def wait_for_credentials(interface, networks, failed):
    submissions = queue.Queue(maxsize=1)
    app = create_portal(networks, failed, submissions, WifiSetup().hotspot_is_active)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, interface.encode("ascii") + b"\0")
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((HOTSPOT_ADDRESS, 80))
        listener.listen()
        server = make_server(HOTSPOT_ADDRESS, 80, app, threaded=True, fd=listener.fileno())
        listener.close()
        with server, subprocess.Popen([
            "dnsmasq", "--keep-in-foreground", "--conf-file=/dev/null",
            "--bind-interfaces", f"--interface={interface}", "--except-interface=lo",
            "--no-resolv", "--no-hosts", f"--address=/#/{HOTSPOT_ADDRESS}", "--local=/#/",
            "--dhcp-range=10.42.66.10,10.42.66.200,255.255.255.0,1h",
            "--dhcp-authoritative", "--leasefile-ro", "--quiet-dhcp",
        ]) as dns:
            threading.Thread(target=server.serve_forever, name="wifi-portal-http", daemon=True).start()
            try:
                while dns.poll() is None:
                    try:
                        credentials = submissions.get(timeout=1)
                    except queue.Empty:
                        continue
                    time.sleep(4)  # Give the phone time to render the handoff instructions.
                    return credentials
                raise WifiSetupError(f"The hotspot DHCP/DNS service exited (status {dns.returncode}).")
            finally:
                server.shutdown()
                if dns.poll() is None:
                    dns.terminate()


def start_wifi_setup():
    if settings.TAPTUNE_WIFI_SETUP:
        threading.Thread(
            target=WifiSetup().run, args=(wait_for_credentials,), name="wifi-setup", daemon=True,
        ).start()
