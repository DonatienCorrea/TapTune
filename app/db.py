import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import BASE_DIR, settings

SCHEMA_PATH = BASE_DIR / "data" / "schema.sql"


def get_connection() -> sqlite3.Connection:
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"Database schema not found: {SCHEMA_PATH}")

    db_dir = Path(settings.DATABASE_PATH).resolve().parent
    db_dir.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(settings.DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")

    connection.executescript(SCHEMA_PATH.read_text())

    return connection


def list_tags() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT uid, value, tag_type, label, last_track_uri, last_position_ms, created_at, updated_at FROM tags ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_tag_by_uid(uid: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT uid, value, tag_type, label, last_track_uri, last_position_ms FROM tags WHERE uid = ?",
            (uid,),
        ).fetchone()
        return dict(row) if row else None


def upsert_tag(uid: str, value: str, tag_type: str, label: Optional[str] = None) -> Dict[str, Any]:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO tags (uid, value, tag_type, label, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(uid) DO UPDATE SET
                value = excluded.value,
                tag_type = excluded.tag_type,
                label = COALESCE(excluded.label, tags.label),
                updated_at = CURRENT_TIMESTAMP
            """,
            (uid, value, tag_type, label),
        )
        conn.commit()
        return get_tag_by_uid(uid) or {"uid": uid, "value": value, "tag_type": tag_type, "label": label}


def save_resume_state(uid: str, last_track_uri: str, last_position_ms: int) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE tags SET last_track_uri = ?, last_position_ms = ?, updated_at = CURRENT_TIMESTAMP WHERE uid = ?",
            (last_track_uri, last_position_ms, uid),
        )
        conn.commit()


def record_event(uid: str, tag_type: str, value: str, source: str = "nfc") -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO events (uid, tag_type, value, source) VALUES (?, ?, ?, ?)",
            (uid, tag_type, value, source),
        )
        conn.commit()


def clear_all_tags() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM activity")
        conn.commit()
