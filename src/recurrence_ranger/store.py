"""SQLite schema, transactional record storage, and consistent backups."""

from __future__ import annotations

import sqlite3
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

SCHEMA_VERSION = 2


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def connect_read_only(path: Path) -> sqlite3.Connection:
    """Open an existing database without write access.

    The path goes into a URI, where '#', '?' and '%' have a meaning of their own; unescaped,
    a path containing one of them silently opens a different file.
    """
    return sqlite3.connect(f"file:{urllib.parse.quote(str(path))}?mode=ro", uri=True)


SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, tool TEXT NOT NULL, label TEXT NOT NULL,
  home TEXT NOT NULL, origin TEXT NOT NULL, available INTEGER NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_aliases (
  source_id TEXT NOT NULL REFERENCES sources(id), path TEXT NOT NULL,
  origin TEXT NOT NULL, PRIMARY KEY(source_id,path)
);
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
  path TEXT NOT NULL UNIQUE, last_seen TEXT, missing INTEGER NOT NULL DEFAULT 0,
  current_generation INTEGER
);
CREATE TABLE IF NOT EXISTS file_aliases (
  file_id INTEGER NOT NULL REFERENCES files(id), path TEXT NOT NULL,
  PRIMARY KEY(file_id,path)
);
CREATE TABLE IF NOT EXISTS generations (
  id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id),
  number INTEGER NOT NULL, device INTEGER NOT NULL, inode INTEGER NOT NULL,
  reason TEXT NOT NULL, created_at TEXT NOT NULL, checkpoint INTEGER NOT NULL DEFAULT 0,
  fingerprint TEXT NOT NULL DEFAULT '', last_size INTEGER NOT NULL DEFAULT 0,
  last_mtime_ns INTEGER NOT NULL DEFAULT 0, UNIQUE(file_id,number)
);
CREATE TABLE IF NOT EXISTS raw_records (
  id INTEGER PRIMARY KEY, generation_id INTEGER NOT NULL REFERENCES generations(id),
  start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, data BLOB NOT NULL,
  digest TEXT NOT NULL, captured_at TEXT NOT NULL, parse_status TEXT NOT NULL,
  parse_error TEXT, parser_version INTEGER NOT NULL DEFAULT 1,
  UNIQUE(generation_id,start_offset,end_offset)
);
CREATE TABLE IF NOT EXISTS pending_fragments (
  generation_id INTEGER PRIMARY KEY REFERENCES generations(id),
  start_offset INTEGER NOT NULL, data BLOB NOT NULL, status TEXT NOT NULL,
  observed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
  source_session_id TEXT NOT NULL, project TEXT, first_seen TEXT NOT NULL,
  UNIQUE(source_id,source_session_id)
);
CREATE TABLE IF NOT EXISTS messages (
  record_id INTEGER PRIMARY KEY REFERENCES raw_records(id),
  session_id INTEGER REFERENCES sessions(id), source_message_id TEXT,
  role TEXT NOT NULL, kind TEXT NOT NULL, timestamp TEXT, project TEXT,
  text TEXT, parent_id TEXT, authorship TEXT NOT NULL DEFAULT 'unclassified'
);
CREATE TABLE IF NOT EXISTS content_blocks (
  record_id INTEGER NOT NULL REFERENCES messages(record_id), block_index INTEGER NOT NULL,
  block_type TEXT NOT NULL, text TEXT, data_json TEXT,
  PRIMARY KEY(record_id,block_index)
);
CREATE TABLE IF NOT EXISTS errors (
  id INTEGER PRIMARY KEY, source_id TEXT, path TEXT, stage TEXT NOT NULL,
  detail TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS ingestion_runs (
  id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
  mode TEXT NOT NULL, files_scanned INTEGER NOT NULL DEFAULT 0,
  records_added INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_raw_generation ON raw_records(generation_id,start_offset);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
CREATE INDEX IF NOT EXISTS idx_errors_open ON errors(resolved_at,source_id);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.path, timeout=5)
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            self.db.close()
            raise RuntimeError(
                f"database schema {version} is newer than supported {SCHEMA_VERSION}"
            )
        if version == 0:
            with self.db:
                self.db.executescript(SCHEMA)
                self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version == 1:
            with self.db:
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS file_aliases ("
                    "file_id INTEGER NOT NULL REFERENCES files(id),"
                    "path TEXT NOT NULL,PRIMARY KEY(file_id,path))"
                )
                self.db.execute(
                    "ALTER TABLE raw_records ADD COLUMN parser_version INTEGER NOT NULL DEFAULT 1"
                )
                self.db.execute(
                    "CREATE TABLE IF NOT EXISTS ingestion_runs ("
                    "id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,"
                    "finished_at TEXT,mode TEXT NOT NULL,"
                    "files_scanned INTEGER NOT NULL DEFAULT 0,"
                    "records_added INTEGER NOT NULL DEFAULT 0,"
                    "errors INTEGER NOT NULL DEFAULT 0)"
                )
                self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    def backup(self, target: Path) -> None:
        target = target.expanduser()
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(target) as other:
            self.db.backup(other)
        target.chmod(0o600)

    def status(self) -> list[dict]:
        rows = self.db.execute("""
          SELECT s.label,s.tool,s.available,
                 (SELECT COUNT(*) FROM files f WHERE f.source_id=s.id),
                 (SELECT COUNT(*) FROM raw_records r JOIN generations g ON g.id=r.generation_id
                  JOIN files f ON f.id=g.file_id WHERE f.source_id=s.id),
                 (SELECT COALESCE(SUM(g.checkpoint),0) FROM files f
                  JOIN generations g ON g.id=f.current_generation WHERE f.source_id=s.id),
                 (SELECT COALESCE(SUM(g.last_size),0) FROM files f
                  JOIN generations g ON g.id=f.current_generation WHERE f.source_id=s.id),
                 (SELECT COUNT(*) FROM pending_fragments p JOIN generations g
                  ON g.id=p.generation_id JOIN files f ON f.id=g.file_id
                  WHERE f.source_id=s.id AND p.status='pending'),
                 (SELECT COUNT(*) FROM errors e WHERE e.source_id=s.id AND e.resolved_at IS NULL)
          FROM sources s ORDER BY s.label
        """).fetchall()
        return [
            dict(
                label=r[0],
                tool=r[1],
                available=bool(r[2]),
                files=r[3],
                records=r[4],
                checkpoint_bytes=r[5],
                observed_bytes=r[6],
                pending_fragments=r[7],
                open_errors=r[8],
            )
            for r in rows
        ]
