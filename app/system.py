"""Update, restart, reboot and diagnostics for the web page (the Pi has no screen).

TapTune runs as root. The update runs as the checkout owner in its own transient
systemd unit, so it survives the app restart it triggers.
"""

from __future__ import annotations

import logging
import os
import pwd
import subprocess
import threading
import time
from pathlib import Path
from typing import Callable

from .config import BASE_DIR, settings

logger = logging.getLogger(__name__)

APP_UNIT = "raspi-spotify-nfc.service"
UPDATE_UNIT = "taptune-web-update"
TAPTUNE_COMMAND = "/usr/local/bin/taptune"
LOG_SYSTEM_UNITS = (APP_UNIT, UPDATE_UNIT + ".service", "bluetooth.service")
LOG_USER_UNITS = ("taptune-go-librespot.service", "pipewire.service", "pipewire-pulse.service", "wireplumber.service")
EXIT_MARKER = "TAPTUNE_UPDATE_EXIT="
ACTION_DELAY_SECONDS = 1.0


def code_version() -> str:
    """Return the checked-out commit without needing git."""
    try:
        head = (BASE_DIR / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref: "):
            ref = BASE_DIR / ".git" / head[5:]
            if ref.is_file():
                return ref.read_text().strip()[:7]
            packed = BASE_DIR / ".git" / "packed-refs"
            for line in packed.read_text().splitlines() if packed.is_file() else []:
                if line.endswith(" " + head[5:]):
                    return line[:7]
            return head[5:]
        return head[:7]
    except OSError:
        return "unknown"


class UpdateRunning(Exception):
    pass


def update_log_path() -> Path:
    return Path(settings.DATABASE_PATH).parent / "update.log"


def _run(args, runner: Callable, timeout: float = 10) -> subprocess.CompletedProcess:
    return runner(args, capture_output=True, text=True, timeout=timeout)


def update_running(runner: Callable = subprocess.run) -> bool:
    try:
        result = _run(["systemctl", "is-active", UPDATE_UNIT], runner)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.stdout.strip() in ("active", "activating", "reloading")


def update_status(runner: Callable = subprocess.run) -> dict:
    path = update_log_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        finished = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(path.stat().st_mtime))
    except OSError:
        text, finished = "", None
    if update_running(runner):
        state, finished = "running", None
    elif not text:
        state = "idle"
    else:
        last = text.rstrip().rsplit("\n", 1)[-1]
        state = "succeeded" if last == EXIT_MARKER + "0" else "failed"
    lines = [line for line in text.splitlines() if not line.startswith(EXIT_MARKER)]
    return {"state": state, "finished_at": finished, "log": "\n".join(lines[-40:])}


def start_update(runner: Callable = subprocess.run) -> None:
    """Run `taptune update` as the checkout owner; its output goes to update.log."""
    if update_running(runner):
        raise UpdateRunning()
    owner = pwd.getpwuid(os.stat(BASE_DIR).st_uid)
    log = update_log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [
        "systemd-run", "--collect", "--unit=" + UPDATE_UNIT, "--uid=" + str(owner.pw_uid),
        "--setenv=HOME=" + owner.pw_dir, f"--setenv=XDG_RUNTIME_DIR=/run/user/{owner.pw_uid}",
        "--property=StandardOutput=truncate:" + str(log), "--property=StandardError=inherit",
        "/bin/sh", "-c", f'{TAPTUNE_COMMAND} update </dev/null; echo "{EXIT_MARKER}$?"',
    ]
    result = _run(command, runner)
    if result.returncode != 0:
        raise OSError((result.stderr or result.stdout or "systemd-run failed").strip())
    logger.info("Update started from the web page (as %s).", owner.pw_name)


def _later(args, runner: Callable, delay: float) -> None:
    def run():
        time.sleep(delay)
        try:
            result = _run(args, runner)
        except (OSError, subprocess.SubprocessError) as error:
            logger.error("%s failed: %s", " ".join(args), error)
            return
        if result.returncode != 0:
            logger.error("%s failed: %s", " ".join(args), (result.stderr or "").strip())

    threading.Thread(target=run, name="taptune-system-action", daemon=True).start()


def restart_app(runner: Callable = subprocess.run, delay: float = ACTION_DELAY_SECONDS) -> None:
    """Restart TapTune shortly after the HTTP answer is sent."""
    logger.warning("Restart requested from the web page.")
    _later(["systemctl", "--no-block", "restart", APP_UNIT], runner, delay)


def reboot(runner: Callable = subprocess.run, delay: float = ACTION_DELAY_SECONDS) -> None:
    logger.warning("Reboot requested from the web page.")
    _later(["systemctl", "reboot"], runner, delay)


def journal(runner: Callable = subprocess.run, lines: int = 500) -> str:
    args = ["journalctl", "--no-hostname", "--no-pager", "-b", "-n", str(lines)]
    matches = [f"_SYSTEMD_UNIT={unit}" for unit in LOG_SYSTEM_UNITS]
    matches += [f"_SYSTEMD_USER_UNIT={unit}" for unit in LOG_USER_UNITS]
    for index, match in enumerate(matches):
        args += ([match] if index == 0 else ["+", match])
    try:
        result = _run(args, runner, timeout=20)
    except (OSError, subprocess.SubprocessError) as error:
        return f"(journalctl failed: {error})"
    return result.stdout or (result.stderr or "(no journal output)")
