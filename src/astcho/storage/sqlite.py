from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class SQLiteStore:
    """Thread-safe structured storage with short-lived SQLite connections."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    group_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    nickname TEXT NOT NULL DEFAULT '',
                    affinity REAL NOT NULL DEFAULT 0.3 CHECK(affinity BETWEEN 0 AND 1),
                    interactions INTEGER NOT NULL DEFAULT 0,
                    last_seen REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (group_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS memes (
                    file_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    local_path TEXT,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    inclination TEXT NOT NULL DEFAULT 'neutral',
                    description TEXT NOT NULL,
                    use_count INTEGER NOT NULL DEFAULT 0,
                    last_seen REAL NOT NULL,
                    last_used REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS vision_cache (
                    cache_key TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    last_accessed REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );
                """
            )

    def touch_user(self, group_id: str, user_id: str, nickname: str) -> None:
        now = time.time()
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO users(group_id, user_id, nickname, last_seen, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(group_id, user_id) DO UPDATE SET
                    nickname=excluded.nickname,
                    last_seen=excluded.last_seen,
                    updated_at=excluded.updated_at
                """,
                (group_id, user_id, nickname, now, now),
            )

    def get_user(self, group_id: str, user_id: str) -> dict[str, Any] | None:
        with self._lock, self.connection() as db:
            row = db.execute(
                "SELECT * FROM users WHERE group_id=? AND user_id=?", (group_id, user_id)
            ).fetchone()
        return dict(row) if row else None

    def update_affinity(self, group_id: str, user_id: str, delta: float) -> float:
        now = time.time()
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO users(group_id, user_id, last_seen, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id, user_id) DO NOTHING
                """,
                (group_id, user_id, now, now),
            )
            row = db.execute(
                "SELECT affinity FROM users WHERE group_id=? AND user_id=?",
                (group_id, user_id),
            ).fetchone()
            current = float(row["affinity"])
            updated = max(0.0, min(1.0, current + delta))
            db.execute(
                """
                UPDATE users SET affinity=?, interactions=interactions+1, updated_at=?
                WHERE group_id=? AND user_id=?
                """,
                (updated, now, group_id, user_id),
            )
        return updated

    def upsert_meme(self, meme: dict[str, Any]) -> None:
        now = time.time()
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO memes(
                    file_id, url, local_path, tags_json, inclination, description,
                    use_count, last_seen, last_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_id) DO UPDATE SET
                    url=excluded.url,
                    local_path=excluded.local_path,
                    tags_json=excluded.tags_json,
                    inclination=excluded.inclination,
                    description=excluded.description,
                    last_seen=excluded.last_seen
                """,
                (
                    meme["file_id"],
                    meme["url"],
                    meme.get("local_path"),
                    json.dumps(meme.get("tags", []), ensure_ascii=False),
                    meme.get("inclination", "neutral"),
                    meme["description"],
                    int(meme.get("use_count", 0)),
                    float(meme.get("last_seen", now)),
                    float(meme.get("last_used", 0)),
                    float(meme.get("created_at", now)),
                ),
            )

    def get_meme(self, file_id: str) -> dict[str, Any] | None:
        with self._lock, self.connection() as db:
            row = db.execute("SELECT * FROM memes WHERE file_id=?", (file_id,)).fetchone()
        if not row:
            return None
        result = dict(row)
        result["tags"] = json.loads(result.pop("tags_json"))
        return result

    def list_memes(self, *, least_used_first: bool = False) -> list[dict[str, Any]]:
        order = "use_count ASC, last_used ASC, created_at ASC" if least_used_first else "created_at DESC"
        with self._lock, self.connection() as db:
            rows = db.execute(f"SELECT * FROM memes ORDER BY {order}").fetchall()
        return [dict(row) for row in rows]

    def mark_meme_used(self, file_id: str) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                "UPDATE memes SET use_count=use_count+1, last_used=? WHERE file_id=?",
                (time.time(), file_id),
            )

    def delete_meme(self, file_id: str) -> dict[str, Any] | None:
        meme = self.get_meme(file_id)
        with self._lock, self.connection() as db:
            db.execute("DELETE FROM memes WHERE file_id=?", (file_id,))
        return meme

    def meme_count(self) -> int:
        with self._lock, self.connection() as db:
            return int(db.execute("SELECT COUNT(*) FROM memes").fetchone()[0])

    def get_vision(self, key: str, max_age_seconds: int = 7 * 86400) -> dict | None:
        cutoff = time.time() - max_age_seconds
        with self._lock, self.connection() as db:
            row = db.execute(
                "SELECT result_json FROM vision_cache WHERE cache_key=? AND last_accessed>=?",
                (key, cutoff),
            ).fetchone()
            if row:
                db.execute(
                    "UPDATE vision_cache SET last_accessed=? WHERE cache_key=?", (time.time(), key)
                )
        return json.loads(row["result_json"]) if row else None

    def set_vision(self, key: str, result: dict) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO vision_cache(cache_key, result_json, last_accessed) VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    result_json=excluded.result_json, last_accessed=excluded.last_accessed
                """,
                (key, json.dumps(result, ensure_ascii=False), time.time()),
            )

    def set_state(self, key: str, value: Any) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """
                INSERT INTO system_state(key, value_json, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json=excluded.value_json, updated_at=excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), time.time()),
            )

    def get_state(self, key: str, default: Any = None) -> Any:
        with self._lock, self.connection() as db:
            row = db.execute(
                "SELECT value_json FROM system_state WHERE key=?", (key,)
            ).fetchone()
        return json.loads(row["value_json"]) if row else default

