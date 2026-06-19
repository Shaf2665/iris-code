"""
Persists conversation history (list[dict]) to SQLite so sessions survive restarts.
History entries are stored as JSON and share the same DB file as personal facts (WAL mode).

Copied verbatim from Iris Teams (`iris/memory/conversations.py`).
"""
import json
import sqlite3
import threading
from datetime import datetime, timezone


class ConversationStore:
    def __init__(self, db_path: str = "forge_memory.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5.0)
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                conv_id    TEXT PRIMARY KEY,
                history    TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self._conn.commit()

    def load(self, conv_id: str) -> list[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT history FROM conversations WHERE conv_id = ?", (conv_id,)
            ).fetchone()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                return []
        return []

    def save(self, conv_id: str, history: list[dict]) -> None:
        with self._lock:
            self._conn.execute("""
                INSERT INTO conversations (conv_id, history, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(conv_id) DO UPDATE SET
                    history    = excluded.history,
                    updated_at = excluded.updated_at
            """, (conv_id, json.dumps(history), datetime.now(timezone.utc).isoformat()))
            self._conn.commit()

    def delete(self, conv_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM conversations WHERE conv_id = ?", (conv_id,))
            self._conn.commit()

    def list_sessions(self) -> list[tuple[str, str, int]]:
        """Return (conv_id, updated_at, user_message_count) sorted newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT conv_id, updated_at, history FROM conversations ORDER BY updated_at DESC"
            ).fetchall()
        result = []
        for conv_id, updated_at, history_json in rows:
            try:
                history = json.loads(history_json)
                count = sum(1 for m in history if m.get("role") == "user")
            except Exception:
                count = 0
            result.append((conv_id, updated_at or "", count))
        return result

    def close(self):
        self._conn.close()
