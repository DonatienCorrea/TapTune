CREATE TABLE IF NOT EXISTS tags (
    uid TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    tag_type TEXT NOT NULL CHECK(tag_type IN ('content', 'action')),
    label TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tags_tag_type ON tags(tag_type);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    level TEXT NOT NULL,
    source TEXT NOT NULL,
    uid TEXT NOT NULL DEFAULT '',
    value TEXT NOT NULL DEFAULT '',
    resolved_uri TEXT NOT NULL DEFAULT '',
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
