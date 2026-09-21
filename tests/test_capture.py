import json
import os

from recurrence_ranger.capture import Collector
from recurrence_ranger.sources import Source
from recurrence_ranger.store import Store


def line(record):
    return json.dumps(record).encode() + b"\n"


def claude_message(text, uuid="one"):
    return {"type": "user", "sessionId": "session", "uuid": uuid,
            "timestamp": "2026-09-21T00:00:00Z", "cwd": "/project",
            "message": {"role": "user", "content": text}}


def setup(tmp_path):
    home = tmp_path / "claude"
    path = home / "projects" / "project" / "session.jsonl"
    path.parent.mkdir(parents=True)
    source = Source("claude", "Claude", home, "test")
    store = Store(tmp_path / "db.sqlite3")
    return source, path, store, Collector(store)


def test_capture_restart_and_distinct_identical_turns(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("same", "one")) +
                     line(claude_message("same", "two")))
    assert collector.scan_file(source, path).records == 2
    store.close()
    store = Store(tmp_path / "db.sqlite3")
    collector = Collector(store)
    assert collector.scan_file(source, path).records == 0
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 2
    assert store.db.execute("SELECT COUNT(*) FROM messages WHERE text='same'").fetchone()[0] == 2
    authorship = store.db.execute("SELECT DISTINCT authorship FROM messages").fetchone()[0]
    assert authorship == "unclassified"
    store.close()


def test_partial_tail_reconciled_and_abandoned_on_replacement(tmp_path):
    source, path, store, collector = setup(tmp_path)
    complete = line(claude_message("first"))
    fragment = line(claude_message("second", "two"))
    path.write_bytes(complete + fragment[:12])
    first = collector.scan_file(source, path)
    assert (first.records, first.pending) == (1, 1)
    assert store.db.execute("SELECT checkpoint FROM generations").fetchone()[0] == len(complete)
    with path.open("ab") as handle:
        handle.write(fragment[12:])
    assert collector.scan_file(source, path).records == 1
    assert store.db.execute("SELECT status FROM pending_fragments").fetchall() == []
    path.write_bytes(complete + b'{"unfinished":')
    collector.scan_file(source, path)
    path.unlink()
    path.write_bytes(line(claude_message("replacement", "three")))
    collector.scan_file(source, path)
    assert store.db.execute("SELECT COUNT(*) FROM generations").fetchone()[0] >= 2
    assert store.db.execute("SELECT status FROM pending_fragments").fetchone()[0] == "abandoned"
    store.close()


def test_malformed_is_retained_and_write_failure_does_not_advance(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(b"not json\n")
    assert collector.scan_file(source, path).records == 1
    assert store.db.execute("SELECT parse_status FROM raw_records").fetchone()[0] == "malformed"
    checkpoint = store.db.execute("SELECT checkpoint FROM generations").fetchone()[0]
    store.db.execute("""CREATE TRIGGER reject_new_record BEFORE INSERT ON raw_records
                        BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
    with path.open("ab") as handle:
        handle.write(line(claude_message("later")))
    assert collector.scan_file(source, path).errors == 1
    assert store.db.execute("SELECT checkpoint FROM generations").fetchone()[0] == checkpoint
    store.db.execute("DROP TRIGGER reject_new_record")
    assert collector.scan_file(source, path).records == 1
    store.close()


def test_codex_message_and_unknown_record(tmp_path):
    home = tmp_path / "codex"
    path = (home / "sessions" /
            "rollout-2026-09-21T00-00-00-12345678-1234-1234-1234-123456789012.jsonl")
    path.parent.mkdir(parents=True)
    path.write_bytes(line({"type": "response_item", "timestamp": "now", "payload": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": "hello"}]}}) +
        line({"type": "future_event", "payload": {"value": 1}}))
    store = Store(tmp_path / "db.sqlite3")
    source = Source("codex", "Codex", home, "test")
    assert Collector(store).scan_once([source]).records == 2
    assert store.db.execute("SELECT text,role FROM messages").fetchone() == ("hello", "user")
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 2
    store.close()


def test_live_file_receives_time_during_backfill(tmp_path):
    source, live, store, collector = setup(tmp_path)
    live.write_bytes(line(claude_message("live")))
    old_dir = source.home / "projects" / "old"
    old_dir.mkdir()
    for index in range(5):
        path = old_dir / f"{index}.jsonl"
        path.write_bytes(line(claude_message(str(index), str(index))))
        os.utime(path, (1, 1))
    result = collector.scan_once([source], max_files=2)
    assert result.records == 2
    assert store.db.execute("SELECT COUNT(*) FROM messages WHERE text='live'").fetchone()[0] == 1
    for _ in range(5):
        collector.scan_once([source], max_files=2)
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 6
    store.close()
