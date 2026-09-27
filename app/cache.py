"""SQLite cache mirroring SerpApi semantics: exact-param key, 1h TTL, free hits."""
import json
import sqlite3
import time

from . import config


def _conn():
    import os

    c = sqlite3.connect(os.getenv("CACHE_PATH", config.CACHE_PATH))
    c.execute(
        "CREATE TABLE IF NOT EXISTS serp_cache (k TEXT PRIMARY KEY, body TEXT, ts REAL)"
    )
    return c


def get(key: str):
    c = _conn()
    try:
        row = c.execute("SELECT body, ts FROM serp_cache WHERE k=?", (key,)).fetchone()
    finally:
        c.close()
    if not row:
        return None
    body, ts = row
    if time.time() - ts > config.CACHE_TTL_S:
        return None
    return json.loads(body)


def put(key: str, body: dict):
    c = _conn()
    try:
        c.execute(
            "REPLACE INTO serp_cache (k, body, ts) VALUES (?,?,?)",
            (key, json.dumps(body), time.time()),
        )
        # Opportunistic eviction: drop rows older than the TTL on every write.
        c.execute("DELETE FROM serp_cache WHERE ts < ?", (time.time() - config.CACHE_TTL_S,))
        c.commit()
    finally:
        c.close()
