"""Command-line operation of the private collector."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sqlite3
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from recurrence_ranger.capture import Collector
from recurrence_ranger.normalize import PARSER_VERSION
from recurrence_ranger.sources import conversation_files, discover
from recurrence_ranger.store import Store, utc_now

DEFAULT_DB = Path("~/.local/share/recurrence-ranger/conversations.sqlite3")


@contextmanager
def writer_lock(path: Path) -> Iterator[None]:
    lock_path = path.expanduser().with_suffix(".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another collector owns this database") from error
        yield
    finally:
        os.close(descriptor)


def _status(store: Store) -> dict:
    db = store.db
    return {
        "database": str(store.path),
        "schema_version": db.execute("PRAGMA user_version").fetchone()[0],
        "parser_version": PARSER_VERSION,
        "ingestion_watermark": db.execute("SELECT COALESCE(MAX(id),0) FROM raw_records").fetchone()[
            0
        ],
        "sources": store.status(),
        "missing_files": db.execute("SELECT COUNT(*) FROM files WHERE missing=1").fetchone()[0],
        "abandoned_fragments": db.execute(
            "SELECT COUNT(*) FROM pending_fragments WHERE status='abandoned'"
        ).fetchone()[0],
    }


def _verify(store: Store) -> dict:
    db = store.db
    integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
    gaps = []
    for generation_id, checkpoint in db.execute("SELECT id,checkpoint FROM generations"):
        expected = 0
        for start, end in db.execute(
            "SELECT start_offset,end_offset FROM raw_records "
            "WHERE generation_id=? ORDER BY start_offset",
            (generation_id,),
        ):
            if start != expected or end <= start:
                gaps.append({"generation": generation_id, "expected": expected, "start": start})
            expected = end
        if expected != checkpoint:
            gaps.append(
                {"generation": generation_id, "expected": expected, "checkpoint": checkpoint}
            )
    return {
        "integrity": integrity,
        "checkpoint_gaps": gaps,
        "raw_records": db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0],
    }


def _inventory(manifest: Path | None) -> dict:
    profiles = []
    for source in discover(manifest):
        files = conversation_files(source) if source.exists else []
        sizes = []
        for path in files:
            try:
                sizes.append(path.stat().st_size)
            except OSError:
                pass
        profiles.append(
            {
                "label": source.label,
                "tool": source.tool,
                "home": str(source.home),
                "origin": source.origin,
                "available": source.exists,
                "files": len(files),
                "bytes": sum(sizes),
                "stat_failures": len(files) - len(sizes),
            }
        )
    return {"sources": profiles}


def _collect(store: Store, args: argparse.Namespace) -> int:
    collector = Collector(store, file_budget=args.file_budget_mib * 1024 * 1024)
    db = store.db
    with db:
        run_id = db.execute(
            "INSERT INTO ingestion_runs(started_at,mode) VALUES (?,?)", (utc_now(), args.command)
        ).lastrowid
    stopping = False

    def request_stop(_signal: int, _frame: FrameType | None) -> None:
        nonlocal stopping
        stopping = True

    old_term = signal.signal(signal.SIGTERM, request_stop)
    old_int = signal.signal(signal.SIGINT, request_stop)
    cycles = 0
    stagnant = 0
    try:
        while not stopping:
            result = collector.scan_once(discover(args.manifest), max_files=args.max_files)
            cycles += 1
            with db:
                db.execute(
                    "UPDATE ingestion_runs SET files_scanned=files_scanned+?,"
                    "records_added=records_added+?,errors=errors+? WHERE id=?",
                    (result.files, result.records, result.errors, run_id),
                )
            if result.records or result.bytes:
                stagnant = 0
            elif result.errors:
                stagnant += 1
            if args.command == "scan" or (args.max_cycles and cycles >= args.max_cycles):
                break
            if args.command == "backfill":
                if not result.files:
                    break
                if stagnant >= 2:
                    print("capture stalled on repeated errors", file=sys.stderr)
                    return 1
                continue
            time.sleep(args.poll_seconds)
    finally:
        with db:
            db.execute("UPDATE ingestion_runs SET finished_at=? WHERE id=?", (utc_now(), run_id))
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)
    print(json.dumps({"cycles": cycles, "status": _status(store)}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="recurrence-ranger")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--manifest",
        type=Path,
        help="JSON source manifest; discovery also checks environment and home",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inventory")
    for name in ("scan", "backfill", "run"):
        command = commands.add_parser(name)
        command.add_argument("--max-files", type=int, default=32)
        command.add_argument("--file-budget-mib", type=int, default=8)
        command.add_argument(
            "--max-cycles",
            type=int,
            default=0,
            help="stop after this many cycles; useful for validation",
        )
        command.add_argument("--poll-seconds", type=float, default=10)
    commands.add_parser("status")
    commands.add_parser("verify")
    backup = commands.add_parser("backup")
    backup.add_argument("target", type=Path)
    restore = commands.add_parser("restore-check")
    restore.add_argument("source", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inventory":
            print(json.dumps(_inventory(args.manifest), indent=2))
            return 0
        if args.command == "restore-check":
            connection = sqlite3.connect(f"file:{args.source.expanduser()}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                count = connection.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0]
                print(json.dumps({"integrity": integrity, "raw_records": count}))
                return 0 if integrity == "ok" else 1
            finally:
                connection.close()
        if args.command in {"scan", "backfill", "run"}:
            if args.max_files < 1 or args.file_budget_mib < 1 or args.poll_seconds <= 0:
                raise ValueError("max-files, file-budget-mib and poll-seconds must be positive")
            with writer_lock(args.db):
                store = Store(args.db)
                try:
                    return _collect(store, args)
                finally:
                    store.close()
        store = Store(args.db)
        try:
            if args.command == "status":
                print(json.dumps(_status(store), indent=2))
            elif args.command == "verify":
                result = _verify(store)
                print(json.dumps(result, indent=2))
                return 0 if result["integrity"] == "ok" and not result["checkpoint_gaps"] else 1
            else:
                # The parser accepts no other command that reaches this point.
                store.backup(args.target)
                print(json.dumps({"backup": str(args.target)}))
            return 0
        finally:
            store.close()
    except (OSError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"recurrence-ranger: {error}", file=sys.stderr)
        return 1
