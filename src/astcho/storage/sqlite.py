from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


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

                CREATE TABLE IF NOT EXISTS expressions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    style TEXT NOT NULL,
                    examples_json TEXT NOT NULL DEFAULT '[]',
                    count INTEGER NOT NULL DEFAULT 1,
                    checked INTEGER NOT NULL DEFAULT 0,
                    rejected INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_active REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_expressions_group
                ON expressions(group_id, rejected, count DESC);

                CREATE TABLE IF NOT EXISTS system_state (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS llm_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    estimated_cost REAL NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
            for name, definition in {
                "affinity_daily_delta": "REAL NOT NULL DEFAULT 0",
                "affinity_day": "TEXT NOT NULL DEFAULT ''",
                "affinity_changed_at": "REAL NOT NULL DEFAULT 0",
                "affinity_decayed_at": "REAL NOT NULL DEFAULT 0",
            }.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")

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

    def set_affinity_state(
        self,
        group_id: str,
        user_id: str,
        *,
        affinity: float,
        daily_delta: float,
        day: str,
        changed_at: float,
        decayed_at: float,
    ) -> None:
        now = time.time()
        with self._lock, self.connection() as db:
            db.execute(
                """UPDATE users SET affinity=?, affinity_daily_delta=?, affinity_day=?,
                affinity_changed_at=?, affinity_decayed_at=?, interactions=interactions+1,
                updated_at=? WHERE group_id=? AND user_id=?""",
                (affinity, daily_delta, day, changed_at, decayed_at, now, group_id, user_id),
            )

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
        order = (
            "use_count ASC, last_used ASC, created_at ASC"
            if least_used_first
            else "created_at DESC"
        )
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
            row = db.execute("SELECT value_json FROM system_state WHERE key=?", (key,)).fetchone()
        return json.loads(row["value_json"]) if row else default

    def list_expressions(
        self, group_id: str, *, include_singletons: bool = True, limit: int = 100
    ) -> list[dict[str, Any]]:
        count_clause = "" if include_singletons else "AND count > 1"
        with self._lock, self.connection() as db:
            rows = db.execute(
                f"""SELECT * FROM expressions
                WHERE group_id=? AND rejected=0 {count_clause}
                ORDER BY count DESC, last_active DESC LIMIT ?""",
                (group_id, limit),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            item["examples"] = json.loads(item.pop("examples_json"))
            output.append(item)
        return output

    def add_expression(
        self, group_id: str, situation: str, style: str, *, similar_id: int | None = None
    ) -> None:
        now = time.time()
        with self._lock, self.connection() as db:
            if similar_id is None:
                db.execute(
                    """INSERT INTO expressions(
                    group_id,situation,style,examples_json,created_at,last_active)
                    VALUES(?,?,?,?,?,?)""",
                    (
                        group_id,
                        situation,
                        style,
                        json.dumps([situation], ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            else:
                row = db.execute(
                    "SELECT examples_json FROM expressions WHERE id=?", (similar_id,)
                ).fetchone()
                examples = json.loads(row[0]) if row else []
                if situation not in examples:
                    examples.append(situation)
                db.execute(
                    """UPDATE expressions SET count=count+1, examples_json=?,
                    last_active=?, checked=0
                    WHERE id=? AND group_id=?""",
                    (json.dumps(examples[-20:], ensure_ascii=False), now, similar_id, group_id),
                )

    def expression_count(self) -> int:
        with self._lock, self.connection() as db:
            return int(
                db.execute("SELECT COUNT(*) FROM expressions WHERE rejected=0").fetchone()[0]
            )

    def pending_expression_reviews(self, limit: int = 5) -> list[dict[str, Any]]:
        with self._lock, self.connection() as db:
            rows = db.execute(
                """SELECT * FROM expressions WHERE checked=0 AND rejected=0 AND count>1
                ORDER BY count DESC, last_active DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def review_expressions(self, accepted_ids: list[int], rejected_ids: list[int]) -> None:
        with self._lock, self.connection() as db:
            if accepted_ids:
                marks = ",".join("?" for _ in accepted_ids)
                db.execute(f"UPDATE expressions SET checked=1 WHERE id IN ({marks})", accepted_ids)
            if rejected_ids:
                marks = ",".join("?" for _ in rejected_ids)
                db.execute(
                    f"UPDATE expressions SET checked=1,rejected=1 WHERE id IN ({marks})",
                    rejected_ids,
                )

    def expression_for_human_review(self) -> dict[str, Any] | None:
        with self._lock, self.connection() as db:
            row = db.execute(
                """SELECT * FROM expressions WHERE checked=0 AND rejected=0
                ORDER BY RANDOM() LIMIT 1"""
            ).fetchone()
        return dict(row) if row else None

    def delete_expression(self, expression_id: int) -> bool:
        with self._lock, self.connection() as db:
            cursor = db.execute("DELETE FROM expressions WHERE id=?", (expression_id,))
        return cursor.rowcount > 0

    def record_usage(
        self, model: str, prompt_tokens: int, completion_tokens: int, estimated_cost: float
    ) -> None:
        with self._lock, self.connection() as db:
            db.execute(
                """INSERT INTO llm_usage(
                model,prompt_tokens,completion_tokens,estimated_cost,created_at)
                VALUES(?,?,?,?,?)""",
                (model, prompt_tokens, completion_tokens, estimated_cost, time.time()),
            )

    def usage_summary(self, hours: int) -> dict[str, float | int]:
        cutoff = time.time() - hours * 3600
        with self._lock, self.connection() as db:
            row = db.execute(
                """SELECT COALESCE(SUM(prompt_tokens),0) AS input_tokens,
                COALESCE(SUM(completion_tokens),0) AS output_tokens,
                COALESCE(SUM(estimated_cost),0) AS cost
                FROM llm_usage WHERE created_at>=?""",
                (cutoff,),
            ).fetchone()
        return {
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "cost": float(row["cost"]),
        }
