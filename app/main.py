import _thread
import logging
import threading
import time

from .config import settings
from .db import record_event
from .nfc_reader import NFCEvent, PN532Reader
from .spotify_service import dispatch_tag_value, get_tag_type
from .web import app

logger = logging.getLogger(__name__)


def dispatch_nfc_event(event: NFCEvent):
    tag_type = get_tag_type(event.payload)
    if tag_type is None:
        logger.warning(
            "NFC tag %s is not assigned; add this UID in the TapTune web UI.",
            event.uid,
        )
        return None

    record_event(event.uid, tag_type, event.payload, source=event.source)
    result = dispatch_tag_value(event.payload)
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


def run_reader_loop_or_stop(reader) -> None:
    try:
        run_reader_loop(reader)
    except Exception:
        logger.exception("PN532 reader loop failed; stopping TapTune for systemd to restart it.")
        _thread.interrupt_main()


def start_reader_thread(reader_factory=PN532Reader) -> threading.Thread:
    reader = reader_factory()
    thread = threading.Thread(
        target=run_reader_loop_or_stop,
        args=(reader,),
        name="pn532-reader",
        daemon=True,
    )
    thread.start()
    return thread


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if settings.NFC_READER_ENABLED:
        start_reader_thread()
    app.run(host=settings.APP_HOST, port=settings.APP_PORT, debug=False)
