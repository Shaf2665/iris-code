"""
Semantic embedding helper — calls hermes-router /v1/embeddings (no local model).

Vectors are L2-normalised so dot-product == cosine similarity, and stored as
compact float32 BLOBs (4 bytes/dim) rather than JSON text (~22 bytes/dim) — a
~5.6x reduction in both database size and parse cost.

Copied verbatim from Iris Teams (`iris/memory/embedder.py`); only the env var
prefix is FORGE_* (with an IRIS_* fallback for shared setups).
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections import OrderedDict

import httpx
import numpy as np

logger = logging.getLogger(__name__)

_BASE_URL = os.environ.get("FORGE_ROUTER_URL") or os.environ.get("IRIS_ROUTER_URL", "http://localhost:8319")
_API_KEY  = os.environ.get("FORGE_API_KEY")    or os.environ.get("IRIS_API_KEY",    "sk-router-hermes-1")
# The router ignores the model name and substitutes its best embed provider.
_MODEL = "text-embedding-3-small"

# Small LRU cache so the same text isn't embedded twice within a session.
_CACHE_MAX = 256
_cache: "OrderedDict[str, list[float]]" = OrderedDict()
_cache_lock = threading.Lock()


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def embed(text: str) -> list[float]:
    """Return a normalised embedding vector via hermes-router (LRU-cached)."""
    with _cache_lock:
        cached = _cache.get(text)
        if cached is not None:
            _cache.move_to_end(text)
            return cached
    resp = httpx.post(
        f"{_BASE_URL}/v1/embeddings",
        headers={"Authorization": f"Bearer {_API_KEY}"},
        json={"model": _MODEL, "input": text},
        timeout=30,
    )
    resp.raise_for_status()
    vec = _normalize(resp.json()["data"][0]["embedding"])
    with _cache_lock:
        _cache[text] = vec
        _cache.move_to_end(text)
        if len(_cache) > _CACHE_MAX:
            _cache.popitem(last=False)
    return vec


# ── storage (compact float32 BLOB) ──────────────────────────────────────────

def pack(vec) -> bytes:
    """Serialise a vector to compact float32 bytes for a SQLite BLOB column."""
    return np.asarray(vec, dtype=np.float32).tobytes()


def unpack(stored) -> np.ndarray | None:
    """Deserialise a stored embedding into a float32 array.

    Accepts the current BLOB format (bytes) or legacy JSON text, so existing
    rows keep working until they are migrated/rewritten."""
    if stored is None:
        return None
    if isinstance(stored, (bytes, bytearray)):
        return np.frombuffer(stored, dtype=np.float32)
    try:                                  # legacy JSON-text rows
        return np.asarray(json.loads(stored), dtype=np.float32)
    except Exception:
        return None


def embed_blob(text: str) -> bytes:
    """Embed text and return it ready for BLOB storage."""
    return pack(embed(text))


# ── similarity ───────────────────────────────────────────────────────────────

def top_k(query_emb, candidates, k: int) -> list[tuple[int, str]]:
    """
    candidates: list of (id, text, embedding) where embedding is a float32 array
    (or any sequence). Returns up to k (id, text) pairs by cosine similarity.
    """
    return [(cid, text) for _score, cid, text in top_k_scored(query_emb, candidates, k)]


def top_k_scored(query_emb, candidates, k: int) -> list[tuple[float, int, str]]:
    """Like top_k but keeps the cosine score: returns (score, id, text), best first."""
    q = np.asarray(query_emb, dtype=np.float32)
    scored = [
        (float(q @ np.asarray(emb, dtype=np.float32)), cid, text)
        for cid, text, emb in candidates
    ]
    scored.sort(reverse=True)
    return scored[:k]
