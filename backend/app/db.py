import json
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role       TEXT NOT NULL,   -- 'user' or 'assistant'
    content    TEXT NOT NULL,
    metadata   TEXT,            -- JSON string, assistant messages only
    created_at TEXT NOT NULL    -- server time, ISO-8601
);
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    system_prompt TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON messages(session_id);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with closing(_connect(path)) as conn, conn:
        conn.executescript(SCHEMA)


def check_db(path: str) -> None:
    """Raises sqlite3.Error if the database is not reachable."""
    with closing(_connect(path)) as conn:
        conn.execute("SELECT 1 FROM messages LIMIT 1")


def get_history(path: str, session_id: str) -> list[dict] | None:
    """Oldest first, no system prompt. None if the session does not exist."""
    with closing(_connect(path)) as conn:
        if conn.execute("SELECT 1 FROM sessions WHERE session_id = ?", (session_id,)).fetchone() is None:
            return None
        rows = conn.execute(
            "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    out = []
    for r in rows:
        msg = {"role": r["role"], "content": r["content"]}
        if r["metadata"]:
            msg["metadata"] = json.loads(r["metadata"])
        out.append(msg)
    return out


def load_context(path: str, session_id: str) -> tuple[str | None, list[dict]]:
    """(stored system prompt or None, history oldest first). Unknown session -> (None, [])."""
    with closing(_connect(path)) as conn:
        row = conn.execute("SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    return (row["system_prompt"] if row else None), (get_history(path, session_id) or [])


def save_exchange(
    path: str,
    session_id: str,
    system_prompt: str | None,
    user_message: str,
    assistant_reply: str,
    metadata: dict,
) -> None:
    """The ONLY way messages are written. Call it only after a successful reply;
    the session and both messages are stored in one transaction."""
    with closing(_connect(path)) as conn, conn:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (session_id, system_prompt, created_at) VALUES (?, ?, ?)",
            (session_id, system_prompt, now_iso()),
        )
        if system_prompt is not None:
            conn.execute("UPDATE sessions SET system_prompt = ? WHERE session_id = ?", (system_prompt, session_id))
        conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'user', ?, NULL, ?)",
            (session_id, user_message, now_iso()),
        )
        conn.execute(
            "INSERT INTO messages (session_id, role, content, metadata, created_at) VALUES (?, 'assistant', ?, ?, ?)",
            (session_id, assistant_reply, json.dumps(metadata), now_iso()),
        )
