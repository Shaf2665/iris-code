"""
Project indexer — semantic codebase search.

Walks a project directory, chunks text files into overlapping windows, embeds
each chunk via hermes-router, and stores them as float32 BLOBs in SQLite (same
storage pattern as personal facts). Search embeds the query and ranks chunks by
cosine similarity.

Re-indexing is incremental: each file's content SHA-256 is stored, and a file
whose hash is unchanged is skipped entirely (no re-embedding). Changed/new files
have their old chunks deleted and fresh ones embedded.
"""
from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import embedder

logger = logging.getLogger(__name__)

_MAX_FILE_SIZE = 100_000   # bytes — skip files larger than this
_CHUNK_CHARS = 1500        # characters per chunk (~375 tokens)
_OVERLAP_CHARS = 200       # overlap between consecutive chunks
_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", ".next", "target", ".mypy_cache", ".pytest_cache",
    ".ruff_cache", ".tox", ".idea", ".vscode", "site-packages",
}
_SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".o", ".a", ".class",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".pdf",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".lock", ".bin", ".db", ".sqlite", ".sqlite3", ".woff", ".woff2", ".ttf",
}


def _norm_key(project_dir: str) -> str:
    """Stable storage key for a project directory. os.path.normcase folds Windows
    path casing and separators (so 'D:\\Foo' and 'd:/foo' collide); on POSIX it's
    a no-op. This guarantees index(), search() and stats() agree on the key no
    matter how the path was entered, which was causing 'not indexed' after a
    successful index on Windows."""
    return os.path.normcase(str(Path(project_dir).resolve()))


def _should_index(path: Path) -> bool:
    if path.suffix.lower() in _SKIP_EXTENSIONS:
        return False
    try:
        if path.stat().st_size > _MAX_FILE_SIZE:
            return False
    except OSError:
        return False
    return True


def _chunk_text(text: str, rel_path: str) -> list[str]:
    """Split text into overlapping chunks, each prefixed with its file path so
    the embedding (and the model reading search results) knows the source."""
    chunks: list[str] = []
    start = 0
    step = max(_CHUNK_CHARS - _OVERLAP_CHARS, 1)
    while start < len(text):
        end = start + _CHUNK_CHARS
        chunks.append(f"# {rel_path}\n{text[start:end]}")
        start += step
    return chunks or [f"# {rel_path}\n"]


class ProjectIndex:
    def __init__(self, db_path: str = "forge_memory.db"):
        self._conn = sqlite3.connect(db_path, check_same_thread=False, timeout=5.0)
        self._lock = threading.Lock()
        self._create_table()

    def _create_table(self):
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS project_chunks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_dir TEXT NOT NULL,
                file_path   TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content     TEXT NOT NULL,
                file_hash   TEXT,
                embedding   BLOB,
                indexed_at  TEXT NOT NULL
            )
        """)
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_dir ON project_chunks(project_dir)"
        )
        try:
            self._conn.execute("ALTER TABLE project_chunks ADD COLUMN file_hash TEXT")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    # ── indexing ───────────────────────────────────────────────────────

    def index(
        self,
        project_dir: str,
        force: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> int:
        """Walk + chunk + embed the project. Returns the number of chunks embedded
        in this run (0 if everything was already up to date)."""
        root = Path(project_dir).resolve()
        key = _norm_key(project_dir)
        report = on_progress or (lambda _m: None)

        if force:
            self.clear(key)

        files = self._collect_files(root)
        report(f"Scanning {len(files)} files in {key}...")

        # Existing per-file hashes, so unchanged files are skipped.
        existing_hashes = self._existing_hashes(key)
        embedded = 0
        seen_files: set[str] = set()

        for i, abspath in enumerate(files, 1):
            rel = os.path.relpath(abspath, root)
            seen_files.add(rel)
            try:
                text = Path(abspath).read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            file_hash = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()

            if not force and existing_hashes.get(rel) == file_hash:
                continue  # unchanged — skip re-embedding

            # Changed or new — replace its chunks.
            self._delete_file_chunks(key, rel)
            chunks = _chunk_text(text, rel)
            for ci, chunk in enumerate(chunks):
                try:
                    blob = embedder.embed_blob(chunk)
                except Exception as e:
                    logger.warning("Embedding failed for %s chunk %d: %s", rel, ci, e)
                    blob = None
                self._insert_chunk(key, rel, ci, chunk, file_hash, blob)
                embedded += 1
            if i % 10 == 0 or embedded and i == len(files):
                report(f"  indexed {i}/{len(files)} files ({embedded} chunks)...")

        # Drop chunks for files that no longer exist.
        removed = self._prune_missing(key, seen_files)
        if removed:
            report(f"  pruned {removed} chunks from deleted files")

        with self._lock:
            self._conn.commit()
        report(f"Done — {embedded} chunks embedded this run.")
        return embedded

    def _collect_files(self, root: Path) -> list[str]:
        out: list[str] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                p = Path(dirpath) / name
                if _should_index(p):
                    out.append(str(p))
        return out

    # ── search ─────────────────────────────────────────────────────────

    def search(self, query: str, project_dir: str, k: int = 5) -> list[dict]:
        """Semantic search. Returns [{file_path, chunk_index, content, score}]."""
        key = _norm_key(project_dir)
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, file_path, chunk_index, content, embedding "
                "FROM project_chunks WHERE project_dir = ?",
                (key,),
            ).fetchall()
        if not rows:
            return []
        try:
            q = embedder.embed(query)
        except Exception as e:
            logger.warning("Query embedding failed: %s", e)
            return []

        candidates = []
        for cid, fpath, cidx, content, blob in rows:
            vec = embedder.unpack(blob) if blob is not None else None
            if vec is not None:
                candidates.append((cid, (fpath, cidx, content), vec))
        if not candidates:
            return []

        scored = embedder.top_k_scored(q, candidates, k)
        return [
            {"file_path": payload[0], "chunk_index": payload[1],
             "content": payload[2], "score": round(score, 4)}
            for score, _cid, payload in scored
        ]

    # ── maintenance ────────────────────────────────────────────────────

    def clear(self, project_dir: str) -> None:
        key = _norm_key(project_dir)
        with self._lock:
            self._conn.execute("DELETE FROM project_chunks WHERE project_dir = ?", (key,))
            self._conn.commit()

    def clear_all(self) -> None:
        """Drop every indexed chunk for all projects (in-app 'Clear data' action)."""
        with self._lock:
            self._conn.execute("DELETE FROM project_chunks")
            self._conn.commit()

    def stats(self, project_dir: str) -> dict:
        key = _norm_key(project_dir)
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT file_path), COUNT(*), MAX(indexed_at) "
                "FROM project_chunks WHERE project_dir = ?",
                (key,),
            ).fetchone()
        return {
            "file_count": row[0] or 0,
            "chunk_count": row[1] or 0,
            "last_indexed": row[2] or "",
        }

    # ── internals ──────────────────────────────────────────────────────

    def _existing_hashes(self, key: str) -> dict[str, str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT file_path, file_hash FROM project_chunks WHERE project_dir = ?",
                (key,),
            ).fetchall()
        return {r[0]: r[1] for r in rows if r[1]}

    def _delete_file_chunks(self, key: str, rel: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM project_chunks WHERE project_dir = ? AND file_path = ?",
                (key, rel),
            )

    def _insert_chunk(self, key, rel, ci, content, file_hash, blob) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO project_chunks "
                "(project_dir, file_path, chunk_index, content, file_hash, embedding, indexed_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, rel, ci, content, file_hash, blob,
                 datetime.now(timezone.utc).isoformat()),
            )

    def _prune_missing(self, key: str, seen_files: set[str]) -> int:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT file_path FROM project_chunks WHERE project_dir = ?",
                (key,),
            ).fetchall()
        stale = [r[0] for r in rows if r[0] not in seen_files]
        for rel in stale:
            self._delete_file_chunks(key, rel)
        return len(stale)

    def close(self):
        self._conn.close()
