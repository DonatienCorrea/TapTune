import _thread
import logging
import threading
import time

from .config import BASE_DIR, settings
from .db import record_event
from .nfc_reader import NFCEvent, PN532Reader
from .readiness import start_speaker_thread
from .spotify_service import dispatch_tag_value, get_tag_type, is_live_spotify_configured
from .web import app

logger = logging.getLogger(__name__)


READER_RETRY_INITIAL_SECONDS = 2.0
READER_RETRY_MAX_SECONDS = 30.0
READER_MAX_CONSECUTIVE_FAILURES = 20
# A reader that worked this long before failing starts a fresh retry budget.
READER_HEALTHY_RUN_SECONDS = 60.0


def dispatch_nfc_event(event: NFCEvent):
    tag_type = get_tag_type(event.payload)
    if tag_type is None:
        logger.warning(
            "NFC tag %s is not assigned; add this UID in the TapTune web UI.",
            event.uid,
        )
        return None

    try:
        record_event(event.uid, tag_type, event.payload, source=event.source)
        result = dispatch_tag_value(event.payload)
    except Exception:  # noqa: BLE001 - one failed tap must never stop the reader.
        logger.exception("Could not dispatch NFC tag %s; tap again.", event.uid)
        return None
    if isinstance(result, dict) and result.get("status") == "error":
        logger.warning("NFC tag %s (%s) failed: %s", event.uid, event.payload, result.get("message") or result)
    else:
        logger.info("Dispatched NFC tag %s: %s", event.uid, result)
    return result


def run_reader_loop(reader, stop_event=None, idle_sleep_seconds: float = 0.05) -> None:
    last_uid = None
    while stop_event is None or not stop_event.is_set():
        event = reader.read_once()
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
) -> None:
    """Open the PN532 and poll it, reopening it after I2C or startup errors.

    Only after many consecutive failures is TapTune stopped so systemd restarts
    the whole process.
    """
    failures = 0
    delay = READER_RETRY_INITIAL_SECONDS
    previous_error = None
    while stop_event is None or not stop_event.is_set():
        started = time.monotonic()
        try:
            reader = reader_factory()
            if failures:
                logger.info("PN532 reader recovered after %d failed attempt(s).", failures)
            else:
                logger.info("PN532 reader started.")
            if ready_event is not None:
                ready_event.set()
            run_reader_loop(reader, stop_event=stop_event)
            return
        except Exception as error:  # noqa: BLE001 - I2C/PN532 errors are often transient at boot.
            if ready_event is not None:
                ready_event.clear()
            if time.monotonic() - started >= READER_HEALTHY_RUN_SECONDS:
                failures = 0
                delay = READER_RETRY_INITIAL_SECONDS
            failures += 1
            last_error = repr(error)
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


def start_reader_thread(reader_factory=PN532Reader) -> threading.Thread:
    ready_event = threading.Event()
    thread = threading.Thread(
        target=run_reader_supervisor,
        args=(reader_factory,),
        kwargs={"ready_event": ready_event},
        name="pn532-reader",
        daemon=True,
    )
    thread.reader_ready = ready_event
    thread.start()
    return thread


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


def log_startup_summary() -> None:
    live = is_live_spotify_configured()
    logger.info(
        "TapTune %s starting: http://%s:%s, Spotify %s, receiver %r, reader %s, "
        "speaker %s, ready sound %s, database %s.",
        code_version(), settings.APP_HOST, settings.APP_PORT,
        "live" if live else "FAKE", settings.SPOTIFY_DEVICE_NAME or "(none)",
        "enabled" if settings.NFC_READER_ENABLED else "disabled",
        settings.BLUETOOTH_SPEAKER_MAC or "(none)",
        "on" if settings.READY_SOUND_ENABLED else "off", settings.DATABASE_PATH,
    )
    if not live:
        missing = [
            name for name in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN")
            if not getattr(settings, name)
        ]
        logger.warning(
            "Spotify is in FAKE mode: nothing will play. Missing in .env: %s.", ", ".join(missing)
        )
    if not settings.NFC_READER_ENABLED:
        logger.warning("NFC_READER_ENABLED=false: tags are not read, only the web page works.")


def log_thread_exception(args) -> None:
    logger.critical(
        "Unexpected error in thread %s.", getattr(args.thread, "name", "?"),
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    threading.excepthook = log_thread_exception
    log_startup_summary()
    if settings.NFC_READER_ENABLED:
        app.config["NFC_READER_THREAD"] = start_reader_thread()
    start_speaker_thread()
    try:
        app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False)
    except OSError:
        logger.exception("The web server could not start on port %s (already in use?).", settings.APP_PORT)
        raise
    logger.warning("TapTune web server stopped; systemd will restart the service.")


if __name__ == "__main__":
    main()
