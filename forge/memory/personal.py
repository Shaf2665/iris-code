"""
Personal memory — durable facts about the developer and their projects
(stack preferences, conventions, project context). Semantic search over facts
via hermes-router embeddings, stored as float32 BLOBs.

Adapted from Iris Teams' `iris/memory/owner.py` (renamed OwnerMemory ->
PersonalMemory; dropped the customer-facing min_score path, which Forge — a
single-user tool — never needs).
"""
import logging
import sqlite3
import threading
from datetime import datetime, timezone

from . import embedder

logger = logging.getLogger(__name__)


class PersonalMemory:
    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5.0)
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                fact      TEXT    NOT NULL,
                timestamp TEXT    NOT NULL,
                embedding BLOB    DEFAULT NULL
            )
        """)
        try:
            self._conn.execute("ALTER TABLE facts ADD COLUMN embedding BLOB DEFAULT NULL")
        except sqlite3.OperationalError:
            pass  # column already exists
        self._conn.commit()

    # ── write ──────────────────────────────────────────────────────────

    def save(self, fact: str):
        with self._lock:
            existing = self._conn.execute(
                "SELECT 1 FROM facts WHERE fact = ? LIMIT 1", (fact,)
            ).fetchone()
            if existing:
                return
            emb = self._safe_embed_blob(fact)
            self._conn.execute(
                "INSERT INTO facts (fact, timestamp, embedding) VALUES (?, ?, ?)",
                (fact, datetime.now(timezone.utc).isoformat(), emb),
            )
            self._conn.commit()

    def update(self, fact_id: int, fact: str):
        with self._lock:
            emb = self._safe_embed_blob(fact)
            self._conn.execute(
                "UPDATE facts SET fact = ?, embedding = ? WHERE id = ?",
                (fact, emb, fact_id),
            )
            self._conn.commit()

    def delete(self, fact_id: int):
        with self._lock:
            self._conn.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            self._conn.commit()

    def clear(self):
        with self._lock:
            self._conn.execute("DELETE FROM facts")
            self._conn.commit()

    # ── read ───────────────────────────────────────────────────────────

    def relevant_facts(self, query: str, k: int = 5) -> list[str]:
        """Return up to k facts most semantically relevant to query.

        Falls back to recent_facts() if embeddings are unavailable, so the
        developer's notes still surface even when the router is unreachable."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, fact, embedding FROM facts ORDER BY id ASC"
            ).fetchall()

        if not rows:
            return []

        try:
            query_emb = embedder.embed(query)
        except Exception as e:
            logger.warning("Embedding query failed (%s) — falling back to recent facts", e)
            return self.recent_facts(limit=k)

        candidates = []
        needs_backfill: list[tuple[int, str]] = []

        for fid, fact, emb_blob in rows:
            vec = embedder.unpack(emb_blob) if emb_blob is not None else None
            if vec is not None:
                candidates.append((fid, fact, vec))
            else:
                needs_backfill.append((fid, fact))

        if needs_backfill:
            self._backfill(needs_backfill, candidates)

        if not candidates:
            return self.recent_facts(limit=k)

        scored = embedder.top_k_scored(query_emb, candidates, k)
        return [text for _score, _cid, text in scored]

    def recent_facts(self, limit: int = 20) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT fact FROM facts ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [row[0] for row in reversed(rows)]

    def all_facts(self) -> list[tuple[int, str]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, fact FROM facts ORDER BY id ASC"
            ).fetchall()
        return [(row[0], row[1]) for row in rows]

    # ── helpers ────────────────────────────────────────────────────────

    def _safe_embed_blob(self, text: str) -> bytes | None:
        try:
            return embedder.embed_blob(text)
        except Exception as e:
            logger.warning("Could not embed fact (%s) — stored without embedding", e)
            return None

    def _backfill(self, missing: list[tuple[int, str]], candidates: list):
        """Compute embeddings for facts that don't have one and persist them."""
        for fid, fact in missing:
            try:
                emb = embedder.embed(fact)
                blob = embedder.pack(emb)
                with self._lock:
                    self._conn.execute(
                        "UPDATE facts SET embedding = ? WHERE id = ?", (blob, fid)
                    )
                candidates.append((fid, fact, emb))
            except Exception as e:
                logger.warning("Backfill failed for fact %d: %s", fid, e)
        with self._lock:
            self._conn.commit()

    def close(self):
        self._conn.close()
