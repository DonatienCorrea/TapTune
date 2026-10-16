import _thread
import logging
import threading
import time

from .config import settings
from .db import record_event
from .nfc_reader import NFCEvent, PN532Reader
from .readiness import start_speaker_thread
from .spotify_service import dispatch_tag_value, get_tag_type
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
            if failures >= max_failures:
                logger.exception(
                    "PN532 reader failed %d times in a row; stopping TapTune for systemd to restart it.",
                    failures,
                )
                _thread.interrupt_main()
                return
            logger.warning(
                "PN532 reader error (attempt %d/%d): %s; retrying in %.0fs.",
                failures, max_failures, error, delay,
            )
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


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if settings.NFC_READER_ENABLED:
        app.config["NFC_READER_THREAD"] = start_reader_thread()
    start_speaker_thread()
    app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False)
