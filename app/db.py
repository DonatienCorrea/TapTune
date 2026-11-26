import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from .config import BASE_DIR, settings

SCHEMA_PATH = BASE_DIR / "data" / "schema.sql"


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    if not SCHEMA_PATH.is_file():
        raise FileNotFoundError(f"Database schema not found: {SCHEMA_PATH}")

    db_dir = Path(settings.DATABASE_PATH).resolve().parent
    db_dir.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(settings.DATABASE_PATH)) as connection, connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_PATH.read_text())
        yield connection


def list_tags() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT uid, value, tag_type, label, created_at, updated_at FROM tags ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_tag_by_uid(uid: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT uid, value, tag_type, label FROM tags WHERE uid = ?",
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
    return get_tag_by_uid(uid) or {"uid": uid, "value": value, "tag_type": tag_type, "label": label}


def clear_all_tags() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM activity")
