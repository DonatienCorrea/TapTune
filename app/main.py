import _thread
import logging
import threading
import time

from werkzeug.serving import make_server

from .config import settings
from .activity import install_activity_logging, record_activity, record_playback
from .nfc_reader import NFCEvent, PN532Reader, reader_supported
from .readiness import start_speaker_thread
from .system import code_version
from .spotify_service import dispatch_tag_value, get_tag_type
from .web import app
from .wifi_portal import run_wifi_setup

logger = logging.getLogger(__name__)


READER_RETRY_INITIAL_SECONDS = 2.0
READER_RETRY_MAX_SECONDS = 30.0
READER_MAX_CONSECUTIVE_FAILURES = 20
# A reader that worked this long before failing starts a fresh retry budget.
READER_HEALTHY_RUN_SECONDS = 60.0


def dispatch_nfc_event(event: NFCEvent):
    if get_tag_type(event.payload) is None:
        record_activity(
            "playback", "WARNING", event.source, "Unassigned tag: assign its UID on the music page.",
            uid=event.uid, value=event.payload,
        )
        logger.warning(
            "NFC tag %s is not assigned; add this UID in the TapTune web UI.",
            event.uid,
        )
        return None

    try:
        result = dispatch_tag_value(event.payload)
        record_playback(event.uid, event.payload, event.source, result)
    except Exception:  # noqa: BLE001 - one failed tap must never stop the reader.
        record_activity(
            "playback", "ERROR", event.source, "Tag dispatch failed; check the service logs and tap again.",
            uid=event.uid, value=event.payload,
        )
        logger.exception("Could not dispatch NFC tag %s; tap again.", event.uid)
        return None
    if isinstance(result, dict) and result.get("status") == "error":
        logger.warning("NFC tag %s (%s) failed: %s", event.uid, event.payload, result.get("message") or result)
    else:
        logger.info("Dispatched NFC tag %s: %s", event.uid, result)
    return result


def run_reader_loop(reader, stop_event=None, idle_sleep_seconds: float = 0.05, writer=None) -> None:
    last_uid = None
    while stop_event is None or not stop_event.is_set():
        event = reader.read_once()
        if writer is not None and writer.consume(reader, event):
            last_uid = event.uid if event else None
            if event is None and idle_sleep_seconds:
                time.sleep(idle_sleep_seconds)
            continue
        if event is None:
            last_uid = None
            if idle_sleep_seconds:
                time.sleep(idle_sleep_seconds)
            continue

        if event.uid != last_uid:
            dispatch_nfc_event(event)
            last_uid = event.uid


def run_reader_supervisor(
    reader_factory,
    stop_event=None,
    ready_event=None,
    sleep=time.sleep,
    max_failures: int = READER_MAX_CONSECUTIVE_FAILURES,
    writer=None,
) -> None:
    """Open the PN532 and poll it, reopening it after I2C or startup errors.

    A reader that never opened (not wired yet) is checked again every 30 s
    forever. A reader that worked and then fails many times in a row stops
    TapTune so systemd restarts the whole process.
    """
    failures = 0
    opened = False
    delay = READER_RETRY_INITIAL_SECONDS
    previous_error = None
    while stop_event is None or not stop_event.is_set():
        started = time.monotonic()
        try:
            reader = reader_factory()
            opened = True
            if failures:
                logger.info("PN532 reader recovered after %d failed attempt(s).", failures)
            else:
                logger.info("PN532 reader started.")
            if ready_event is not None:
                ready_event.set()
            run_reader_loop(reader, stop_event=stop_event, writer=writer)
            return
        except Exception as error:  # noqa: BLE001 - I2C/PN532 errors are often transient at boot.
            if writer is not None:
                writer.fail()
            if ready_event is not None:
                ready_event.clear()
            if time.monotonic() - started >= READER_HEALTHY_RUN_SECONDS:
                failures = 0
                delay = READER_RETRY_INITIAL_SECONDS
            failures += 1
            last_error = repr(error)
            if failures >= max_failures and not opened:
                if failures == max_failures:
                    logger.error(
                        "No NFC reader found: check the PN532 wiring and its I2C switch. "
                        "TapTune keeps checking every %.0fs.", READER_RETRY_MAX_SECONDS,
                    )
                else:
                    logger.debug("Still no NFC reader: %r", error)
                sleep(READER_RETRY_MAX_SECONDS)
                continue
            if failures >= max_failures:
                logger.exception(
                    "PN532 reader failed %d times in a row; stopping TapTune for systemd to restart it.",
                    failures,
                )
                _thread.interrupt_main()
                return
            logger.warning(
                "PN532 reader error (attempt %d/%d): %r; retrying in %.0fs. "
                "Check the wiring, I2C (/dev/i2c-1) and that no other reader process is running.",
                failures, max_failures, error, delay,
                # The full traceback once per distinct error, not at every retry.
                exc_info=last_error != previous_error,
            )
            previous_error = last_error
            sleep(delay)
            delay = min(delay * 2, READER_RETRY_MAX_SECONDS)


def start_reader_thread(reader_factory=PN532Reader, writer=None) -> threading.Thread:
    ready_event = threading.Event()
    thread = threading.Thread(
        target=run_reader_supervisor,
        args=(reader_factory,),
        kwargs={"ready_event": ready_event, "writer": writer},
        name="pn532-reader",
        daemon=True,
    )
    thread.reader_ready = ready_event
    thread.start()
    return thread


def log_startup_summary() -> None:
    logger.info(
        "TapTune %s starting: http://%s:%s, Spotify receiver %r, reader %s, "
        "speaker %s, ready sound %s, database %s.",
        code_version(), settings.APP_HOST, settings.APP_PORT, settings.SPOTIFY_DEVICE_NAME,
        "PN532" if reader_supported() else "unavailable (no PN532 libraries)",
        settings.BLUETOOTH_SPEAKER_MAC or "(none)",
        "on" if settings.READY_SOUND_ENABLED else "off", settings.DATABASE_PATH,
    )
    if not reader_supported():
        logger.warning("No PN532 libraries: tags are not read, only the web page works.")


def log_thread_exception(args) -> None:
    logger.critical(
        "Unexpected error in thread %s.", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def run_network_services() -> None:
    # The captive portal owns port 80 until Wi-Fi setup hands off to the LAN.
    if settings.TAPTUNE_WIFI_SETUP and not run_wifi_setup():
        return
    if not settings.TAPTUNE_HTTP_PORT_80 or settings.APP_PORT == 80:
        return
    try:
        server = make_server(settings.APP_HOST, 80, app, threaded=True)
    except SystemExit:
        # Werkzeug exits on bind errors, e.g. if another service owns port 80.
        logger.warning("Could not start TapTune on port 80; use port %s instead.", settings.APP_PORT)
        return
    with server:
        logger.info("TapTune is also available on HTTP port 80.")
        server.serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    install_activity_logging()
    threading.excepthook = log_thread_exception
    log_startup_summary()
    if reader_supported():
        app.config["NFC_READER_THREAD"] = start_reader_thread(writer=app.config["TAG_WRITER"])
    start_speaker_thread()
    if settings.TAPTUNE_WIFI_SETUP or settings.TAPTUNE_HTTP_PORT_80:
        threading.Thread(target=run_network_services, name="network-setup", daemon=True).start()
    try:
        app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False)
    except OSError:
        logger.exception("The web server could not start on port %s (already in use?).", settings.APP_PORT)
        raise
    logger.warning("TapTune web server stopped; systemd will restart the service.")


if __name__ == "__main__":
    main()
