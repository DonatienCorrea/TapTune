"""Persistent, credential-redacted playback activity and app diagnostics."""

import logging
import re
import sqlite3
import sys

from .config import settings
from .db import get_connection

ACTIVITY_LIMIT = 2000
PAGE_SIZE = 50


def redact(value):
    text = str(value)
    for name in ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN"):
        secret = getattr(settings, name)
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"(?i)\b(Bearer|Basic)\s+[^\s,'\";]+", r"\1 [redacted]", text)
    text = re.sub(
        r"(?i)(\b(?:access_token|refresh_token|client_secret|client_id|authorization|password|code)\b"
        r"['\"]?\s*[:=]\s*['\"]?)[^\s,'\"&;]+",
        r"\1[redacted]", text,
    )
    return text[:4000]


def record_activity(kind, level, source, message, uid="", value="", resolved_uri=""):
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO activity (kind, level, source, message, uid, value, resolved_uri)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, level, source, redact(message), redact(uid), redact(value), redact(resolved_uri)),
            )
            conn.execute(
                "DELETE FROM activity WHERE id <= COALESCE("
                " (SELECT id FROM activity ORDER BY id DESC LIMIT 1 OFFSET ?), 0)",
                (ACTIVITY_LIMIT,),
            )
    except (sqlite3.Error, OSError):
        # A diagnostics failure must not prevent playback or recursively log.
        sys.stderr.write("TapTune could not save an activity log entry; check database access.\n")


def record_playback(uid, value, source, result):
    result = result if isinstance(result, dict) else {"status": "ok"}
    status = result.get("status", "ok")
    success = status == "ok"
    message = (
        result.get("episode_name") or "Playback command sent to Spotify."
        if success else result.get("message") or result.get("error") or status
    )
    if success and result.get("mode") == "fake":
        message = "Demo mode: no real playback. " + message
    record_activity(
        "playback", "INFO" if success else "ERROR", source, message,
        uid=uid, value=value, resolved_uri=result.get("uri") or "",
    )


def list_activity(query="", kind="", level="", page=1):
    if len(query) > 200 or kind not in ("", "playback", "diagnostic") or level not in ("", "errors"):
        raise ValueError("Invalid activity filters")
    if not 1 <= page <= ACTIVITY_LIMIT // PAGE_SIZE:
        raise ValueError("Invalid activity page")
    clauses, values = [], []
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        clauses.append("(" + " OR ".join(
            column + " LIKE ? ESCAPE '\\'" for column in ("message", "uid", "value", "resolved_uri", "source")
        ) + ")")
        values.extend([pattern] * 5)
    if kind:
        clauses.append("kind = ?")
        values.append(kind)
    if level:
        clauses.append("level IN ('WARNING', 'ERROR', 'CRITICAL')")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM activity" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
            values + [PAGE_SIZE + 1, (page - 1) * PAGE_SIZE],
        ).fetchall()
    return [dict(row) for row in rows[:PAGE_SIZE]], len(rows) > PAGE_SIZE


class ActivityHandler(logging.Handler):
    def emit(self, record):
        try:
            # Tracebacks remain in system logs, not in the browser.
            record_activity("diagnostic", record.levelname, record.name, record.getMessage())
        except Exception:
            # Logging failure must not recursively log or stop the reader.
            sys.stderr.write("TapTune could not save an activity log entry; check database access.\n")


def install_activity_logging():
    logger = logging.getLogger("app")
    if not any(isinstance(handler, ActivityHandler) for handler in logger.handlers):
        handler = ActivityHandler(level=logging.INFO)
        logger.addHandler(handler)
