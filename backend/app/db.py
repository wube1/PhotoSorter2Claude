"""SQLite persistence (WAL mode). One connection guarded by a lock: simple and fast enough."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    rel_path      TEXT NOT NULL UNIQUE,
    size          INTEGER NOT NULL,
    mtime         REAL NOT NULL,
    sha256        TEXT,
    taken_at      TEXT,              -- ISO local time "YYYY-MM-DDTHH:MM:SS"
    taken_source  TEXT,              -- exif | mtime
    lat           REAL,
    lon           REAL,
    width         INTEGER,
    height        INTEGER,
    camera        TEXT,
    doc_score     REAL,
    analyzed      INTEGER NOT NULL DEFAULT 0,
    error         TEXT,
    dup_of        INTEGER,
    auto_folder   TEXT,
    auto_status   TEXT NOT NULL DEFAULT 'pending',   -- pending | ready | review
    auto_reason   TEXT,
    location      TEXT,              -- JSON {city, place, source, place_key}
    manual_folder TEXT,              -- user override (template, may contain {date})
    approved      INTEGER NOT NULL DEFAULT 0,
    added_at      REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS files_sha ON files(sha256);

CREATE TABLE IF NOT EXISTS geocache (
    key        TEXT PRIMARY KEY,
    result     TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS replacements (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_folder TEXT NOT NULL,
    to_folder   TEXT NOT NULL,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("PRAGMA busy_timeout=5000")
            self.conn.executescript(SCHEMA)
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)", (str(SCHEMA_VERSION),)
            )

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    # ---------------------------------------------------------------- helpers
    def query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, tuple(params)).fetchall()

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.conn.execute(sql, tuple(params))

    def executemany(self, sql: str, rows: Iterable[Iterable[Any]]) -> None:
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                self.conn.executemany(sql, [tuple(r) for r in rows])
                self.conn.execute("COMMIT")
            except Exception:
                self.conn.execute("ROLLBACK")
                raise

    # ------------------------------------------------------------------ files
    def all_files(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM files ORDER BY taken_at IS NULL, taken_at, rel_path")

    def files_by_ids(self, ids: Iterable[int]) -> list[sqlite3.Row]:
        ids = [int(i) for i in ids]
        if not ids:
            return []
        out: list[sqlite3.Row] = []
        for start in range(0, len(ids), 500):
            chunk = ids[start : start + 500]
            marks = ",".join("?" * len(chunk))
            out.extend(self.query(f"SELECT * FROM files WHERE id IN ({marks})", chunk))
        return out

    def file(self, file_id: int) -> sqlite3.Row | None:
        rows = self.query("SELECT * FROM files WHERE id=?", (file_id,))
        return rows[0] if rows else None

    def file_index(self) -> dict[str, sqlite3.Row]:
        return {r["rel_path"]: r for r in self.query("SELECT id, rel_path, size, mtime, analyzed FROM files")}

    def insert_or_reset_file(self, rel_path: str, size: int, mtime: float) -> int:
        now = time.time()
        with self.lock:
            row = self.conn.execute("SELECT id FROM files WHERE rel_path=?", (rel_path,)).fetchone()
            if row:
                # content changed: keep the user's manual choice, reset analysis
                self.conn.execute(
                    "UPDATE files SET size=?, mtime=?, analyzed=0, error=NULL, auto_status='pending', "
                    "updated_at=? WHERE id=?",
                    (size, mtime, now, row["id"]),
                )
                return int(row["id"])
            cur = self.conn.execute(
                "INSERT INTO files(rel_path, size, mtime, added_at, updated_at) VALUES(?,?,?,?,?)",
                (rel_path, size, mtime, now, now),
            )
            return int(cur.lastrowid)

    def update_file(self, file_id: int, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"UPDATE files SET {cols} WHERE id=?", [*fields.values(), file_id])

    def update_files(self, ids: Iterable[int], **fields: Any) -> None:
        ids = list(ids)
        if not ids or not fields:
            return
        fields["updated_at"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.executemany(f"UPDATE files SET {cols} WHERE id=?", [[*fields.values(), i] for i in ids])

    def delete_files(self, ids: Iterable[int]) -> None:
        self.executemany("DELETE FROM files WHERE id=?", [[i] for i in ids])

    # --------------------------------------------------------------- geocache
    def geocache_get(self, key: str) -> dict[str, Any] | None:
        rows = self.query("SELECT result FROM geocache WHERE key=?", (key,))
        return json.loads(rows[0]["result"]) if rows else None

    def geocache_put(self, key: str, result: dict[str, Any]) -> None:
        self.execute(
            "INSERT OR REPLACE INTO geocache(key, result, created_at) VALUES(?,?,?)",
            (key, json.dumps(result, ensure_ascii=False), time.time()),
        )

    # ----------------------------------------------------------- replacements
    def replacements(self) -> list[sqlite3.Row]:
        return self.query("SELECT * FROM replacements ORDER BY id")

    def add_replacement(self, from_folder: str, to_folder: str) -> int:
        cur = self.execute(
            "INSERT INTO replacements(from_folder, to_folder, created_at) VALUES(?,?,?)",
            (from_folder, to_folder, time.time()),
        )
        return int(cur.lastrowid)

    def delete_replacement(self, rep_id: int) -> None:
        self.execute("DELETE FROM replacements WHERE id=?", (rep_id,))
