"""Write requests are consumed only by the existing NFC reader thread."""

import logging
import secrets
import threading
import time

from .nfc_reader import TagWriteError
from .ndef import encode_spotify_ndef

logger = logging.getLogger(__name__)
WRITE_TIMEOUT_SECONDS = 60


class WriterBusy(ValueError):
    pass


class TagWriter:
    def __init__(self, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._job = None
        self._suppress_until_removed = False

    def _expire(self):
        if self._job and self._job["status"] == "waiting" and self._clock() >= self._deadline:
            self._job.update(status="error", error="write_timeout")
            self._suppress_until_removed = True

    def start(self, value):
        encode_spotify_ndef(value)
        with self._lock:
            self._expire()
            if self._job and self._job["status"] == "waiting":
                raise WriterBusy("A tag write is already waiting")
            self._job = {
                "id": secrets.token_urlsafe(24), "status": "waiting",
                "value": value, "uid": None, "error": None,
            }
            self._deadline = self._clock() + WRITE_TIMEOUT_SECONDS
            return dict(self._job)

    def snapshot(self, job_id=None):
        with self._lock:
            self._expire()
            if self._job is None or (job_id is not None and job_id != self._job["id"]):
                return None
            return dict(self._job)

    def cancel(self, job_id):
        with self._lock:
            self._expire()
            if self._job is None or self._job["id"] != job_id:
                return None
            if self._job["status"] == "waiting":
                self._job.update(status="cancelled")
                self._suppress_until_removed = True
            return dict(self._job)

    def fail(self):
        with self._lock:
            if self._job and self._job["status"] == "waiting":
                self._job.update(status="error", error="reader_unavailable")
                self._suppress_until_removed = True

    def consume(self, reader, event):
        """Return True when this scan belongs to writing, never playback."""
        with self._lock:
            self._expire()
            waiting = self._job and self._job["status"] == "waiting"
            if self._suppress_until_removed:
                if event is None:
                    self._suppress_until_removed = False
                return True
            if not waiting:
                return False
            if event is None:
                return True
            self._job["uid"] = event.uid
            try:
                if not reader.write_tag(event.uid, self._job["value"]):
                    raise TagWriteError("tag_write_failed")
            except (TagWriteError, OSError, RuntimeError) as error:
                code = error.code if isinstance(error, TagWriteError) else "tag_write_failed"
                logger.warning("Tag write failed for %s: %s", event.uid, code, exc_info=True)
                self._job.update(status="error", error=code)
            else:
                self._job.update(status="success")
                logger.info("Wrote and verified tag %s: %s", event.uid, self._job["value"])
            self._suppress_until_removed = True
            return True
