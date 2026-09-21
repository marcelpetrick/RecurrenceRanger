"""Transactional, bounded incremental capture of complete JSONL records."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from recurrence_ranger.normalize import PARSER_VERSION, codex_session_project, parse_record
from recurrence_ranger.sources import Source, conversation_files
from recurrence_ranger.store import Store, utc_now

MAX_RECORD_BYTES = 256 * 1024 * 1024
SAMPLE_BYTES = 256


@dataclass
class ScanResult:
    files: int = 0
    records: int = 0
    bytes: int = 0
    errors: int = 0
    pending: int = 0


def _fingerprint(handle, offset: int) -> str:
    """Sample the committed prefix; this detects common rewrites, not every edit."""
    if not offset:
        return ""
    digest = hashlib.blake2s()
    digest.update(offset.to_bytes(8, "big"))
    positions = {0, max(0, offset // 2 - SAMPLE_BYTES // 2), max(0, offset - SAMPLE_BYTES)}
    for pos in sorted(positions):
        handle.seek(pos)
        digest.update(pos.to_bytes(8, "big"))
        digest.update(handle.read(min(SAMPLE_BYTES, offset - pos)))
    return digest.hexdigest()


class Collector:
    def __init__(self, store: Store, *, file_budget: int = 8 * 1024 * 1024):
        self.store = store
        self.file_budget = file_budget
        self._historical_cursor = 0

    def _source(self, source: Source) -> None:
        db = self.store.db
        db.execute(
            """
          INSERT INTO sources VALUES (?,?,?,?,?,?,?)
          ON CONFLICT(id) DO UPDATE SET label=excluded.label,home=excluded.home,
          origin=excluded.origin,available=excluded.available,last_seen=excluded.last_seen
        """,
            (
                source.id,
                source.tool,
                source.label,
                str(source.home),
                source.origin,
                int(source.exists),
                utc_now(),
            ),
        )
        db.execute(
            "INSERT OR IGNORE INTO source_aliases VALUES (?,?,?)",
            (source.id, str(source.home), source.origin),
        )
        for alias in source.aliases:
            db.execute(
                "INSERT OR IGNORE INTO source_aliases VALUES (?,?,?)",
                (source.id, alias, "discovered alias"),
            )

    def _error(self, source: Source, path: Path, stage: str, detail: str) -> None:
        with self.store.db:
            existing = self.store.db.execute(
                "SELECT id FROM errors WHERE source_id=? AND path=? AND stage=? "
                "AND resolved_at IS NULL",
                (source.id, str(path), stage),
            ).fetchone()
            if not existing:
                self.store.db.execute(
                    "INSERT INTO errors(source_id,path,stage,detail,created_at) VALUES (?,?,?,?,?)",
                    (source.id, str(path), stage, detail[:500], utc_now()),
                )

    def _file_row(self, source: Source, path: Path) -> tuple[int, tuple | None]:
        db = self.store.db
        db.execute(
            """
          INSERT INTO files(source_id,path,last_seen) VALUES (?,?,?)
          ON CONFLICT(path) DO UPDATE SET last_seen=excluded.last_seen,missing=0
        """,
            (source.id, str(path.resolve()), utc_now()),
        )
        file_id = db.execute(
            "SELECT id FROM files WHERE path=?", (str(path.resolve()),)
        ).fetchone()[0]
        db.execute("INSERT OR IGNORE INTO file_aliases VALUES (?,?)", (file_id, str(path)))
        generation = db.execute(
            """
          SELECT g.id,g.number,g.device,g.inode,g.checkpoint,g.fingerprint,
                 g.last_size,g.last_mtime_ns
          FROM files f JOIN generations g ON g.id=f.current_generation
          WHERE f.id=?
        """,
            (file_id,),
        ).fetchone()
        return file_id, generation

    def _new_generation(self, file_id: int, previous: tuple | None, stat, reason: str) -> tuple:
        db = self.store.db
        number = previous[1] + 1 if previous else 1
        if previous:
            db.execute(
                "UPDATE pending_fragments SET status='abandoned' "
                "WHERE generation_id=? AND status='pending'",
                (previous[0],),
            )
        cursor = db.execute(
            """
          INSERT INTO generations(file_id,number,device,inode,reason,created_at,
                                  last_size,last_mtime_ns)
          VALUES (?,?,?,?,?,?,?,?)
        """,
            (
                file_id,
                number,
                stat.st_dev,
                stat.st_ino,
                reason,
                utc_now(),
                stat.st_size,
                stat.st_mtime_ns,
            ),
        )
        db.execute("UPDATE files SET current_generation=? WHERE id=?", (cursor.lastrowid, file_id))
        return (
            cursor.lastrowid,
            number,
            stat.st_dev,
            stat.st_ino,
            0,
            "",
            stat.st_size,
            stat.st_mtime_ns,
        )

    def scan_file(self, source: Source, path: Path, *, budget: int | None = None) -> ScanResult:
        """Capture one file up to a byte budget, finishing each complete line."""
        result = ScanResult(files=1)
        budget = budget or self.file_budget
        try:
            with path.open("rb") as handle:
                stat = os.fstat(handle.fileno())
                with self.store.db:
                    self._source(source)
                    file_id, generation = self._file_row(source, path)
                    reason = "first observation"
                    if generation:
                        if (stat.st_dev, stat.st_ino) != (generation[2], generation[3]):
                            reason = "replacement"
                        elif stat.st_size < generation[4]:
                            reason = "truncation"
                        elif _fingerprint(handle, generation[4]) != generation[5]:
                            reason = "committed prefix changed"
                        else:
                            reason = ""
                    if reason:
                        generation = self._new_generation(file_id, generation, stat, reason)
                    generation_id, offset = generation[0], generation[4]
                    handle.seek(offset)
                    while handle.tell() < stat.st_size:
                        start = handle.tell()
                        limit = min(stat.st_size - start, MAX_RECORD_BYTES + 1)
                        line = handle.readline(limit)
                        if len(line) > MAX_RECORD_BYTES:
                            raise ValueError(f"record exceeds {MAX_RECORD_BYTES} bytes at {start}")
                        if not line.endswith(b"\n"):
                            self.store.db.execute(
                                """
                              INSERT INTO pending_fragments VALUES (?,?,?,?,?)
                              ON CONFLICT(generation_id) DO UPDATE SET
                                start_offset=excluded.start_offset,data=excluded.data,
                                status='pending',observed_at=excluded.observed_at
                            """,
                                (generation_id, start, line, "pending", utc_now()),
                            )
                            result.pending += 1
                            break
                        end = handle.tell()
                        status, error, message = parse_record(source.tool, path, line)
                        digest = hashlib.blake2s(line).hexdigest()
                        cursor = self.store.db.execute(
                            """
                          INSERT OR IGNORE INTO raw_records
                            (generation_id,start_offset,end_offset,data,digest,captured_at,
                             parse_status,parse_error,parser_version)
                          VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                            (
                                generation_id,
                                start,
                                end,
                                line,
                                digest,
                                utc_now(),
                                status,
                                error,
                                PARSER_VERSION,
                            ),
                        )
                        record_id = cursor.lastrowid
                        if (
                            cursor.rowcount
                            and source.tool == "codex"
                            and b'"session_meta"' in line[:256]
                        ):
                            metadata = codex_session_project(path, line)
                            if metadata:
                                self._session_project(source, *metadata)
                        if cursor.rowcount and message:
                            self._message(record_id, source, message)
                        if cursor.rowcount:
                            result.records += 1
                        result.bytes += len(line)
                        offset = end
                        if result.bytes >= budget:
                            break
                    self.store.db.execute(
                        "UPDATE generations SET checkpoint=?,fingerprint=?,"
                        "last_size=?,last_mtime_ns=? WHERE id=?",
                        (
                            offset,
                            _fingerprint(handle, offset),
                            stat.st_size,
                            stat.st_mtime_ns,
                            generation_id,
                        ),
                    )
                    self.store.db.execute(
                        "DELETE FROM pending_fragments "
                        "WHERE generation_id=? AND status='pending' "
                        "AND start_offset<?",
                        (generation_id, offset),
                    )
                    self.store.db.execute(
                        "UPDATE errors SET resolved_at=? WHERE "
                        "source_id=? AND path=? AND stage='capture' "
                        "AND resolved_at IS NULL",
                        (utc_now(), source.id, str(path)),
                    )
        except (OSError, ValueError, sqlite3.Error) as error:
            result.errors += 1
            try:
                self._error(source, path, "capture", str(error))
            except sqlite3.Error:
                # The caller still receives an error when the database itself cannot write.
                pass
        return result

    def _message(self, record_id: int, source: Source, message) -> None:
        db = self.store.db
        db.execute(
            """
          INSERT INTO sessions(source_id,source_session_id,project,first_seen)
          VALUES (?,?,?,?) ON CONFLICT(source_id,source_session_id) DO UPDATE SET
          project=COALESCE(sessions.project,excluded.project)
        """,
            (source.id, message.session, message.project, utc_now()),
        )
        session_id = db.execute(
            "SELECT id FROM sessions WHERE source_id=? AND source_session_id=?",
            (source.id, message.session),
        ).fetchone()[0]
        db.execute(
            """
          INSERT INTO messages(record_id,session_id,source_message_id,role,kind,
                               timestamp,project,text,parent_id)
          VALUES (?,?,?,?,?,?,?,?,?)
        """,
            (
                record_id,
                session_id,
                message.source_message_id,
                message.role,
                message.kind,
                message.timestamp,
                message.project,
                message.text,
                message.parent_id,
            ),
        )
        db.executemany(
            "INSERT INTO content_blocks VALUES (?,?,?,?,?)",
            [
                (record_id, index, block.kind, block.text, block.data_json)
                for index, block in enumerate(message.blocks)
            ],
        )

    def _session_project(self, source: Source, session: str, project: str) -> None:
        self.store.db.execute(
            """
          INSERT INTO sessions(source_id,source_session_id,project,first_seen)
          VALUES (?,?,?,?) ON CONFLICT(source_id,source_session_id) DO UPDATE SET
          project=excluded.project
        """,
            (source.id, session, project, utc_now()),
        )

    def scan_once(self, sources: list[Source], *, max_files: int = 32) -> ScanResult:
        """Interleave changed active files with older backfill files."""
        result = ScanResult()
        paths: list[tuple[Source, Path, os.stat_result]] = []
        for source in sources:
            with self.store.db:
                self._source(source)
            if not source.exists:
                continue
            for path in conversation_files(source):
                try:
                    paths.append((source, path, path.stat()))
                except OSError as error:
                    self._error(source, path, "stat", str(error))
                    result.errors += 1
        observed = {str(path.resolve()) for _, path, _ in paths}
        available = {source.id for source in sources if source.exists}
        with self.store.db:
            for file_id, source_id, path, generation_id, missing in self.store.db.execute(
                "SELECT id,source_id,path,current_generation,missing FROM files"
            ).fetchall():
                if source_id in available and path not in observed and not missing:
                    self.store.db.execute("UPDATE files SET missing=1 WHERE id=?", (file_id,))
                    if generation_id:
                        self.store.db.execute(
                            "UPDATE pending_fragments SET status='abandoned' "
                            "WHERE generation_id=? AND status='pending'",
                            (generation_id,),
                        )
        rows = self.store.db.execute("""
          SELECT f.path,g.checkpoint,g.last_size,g.last_mtime_ns,p.status,f.missing
          FROM files f LEFT JOIN generations g ON g.id=f.current_generation
          LEFT JOIN pending_fragments p ON p.generation_id=g.id
        """).fetchall()
        known = {row[0]: row[1:] for row in rows}
        needed = []
        for source, path, stat in paths:
            state = known.get(str(path.resolve()))
            if not state or state[4] or state[1] != stat.st_size or state[2] != stat.st_mtime_ns:
                needed.append((source, path, stat))
            elif state[0] < stat.st_size and state[3] != "pending":
                needed.append((source, path, stat))
        recent = sorted(
            (row for row in needed if time.time() - row[2].st_mtime < 3600),
            key=lambda row: row[2].st_mtime,
            reverse=True,
        )
        historical = sorted(
            (row for row in needed if time.time() - row[2].st_mtime >= 3600),
            key=lambda row: str(row[1]),
        )
        if historical:
            cursor = self._historical_cursor % len(historical)
            historical = historical[cursor:] + historical[:cursor]
            self._historical_cursor += max(1, max_files // 2)
        recent_quota = max(1, max_files // 2) if historical else max_files
        selected = recent[:recent_quota] + historical[: max_files - min(len(recent), recent_quota)]
        selected += recent[recent_quota : recent_quota + max_files - len(selected)]
        for source, path, _ in selected:
            one = self.scan_file(source, path)
            result.files += one.files
            result.records += one.records
            result.bytes += one.bytes
            result.errors += one.errors
            result.pending += one.pending
        return result
