import json
import os

from recurrence_ranger.capture import Collector
from recurrence_ranger.sources import Source
from recurrence_ranger.store import Store


def line(record):
    return json.dumps(record).encode() + b"\n"


def claude_message(text, uuid="one"):
    return {
        "type": "user",
        "sessionId": "session",
        "uuid": uuid,
        "timestamp": "2026-09-21T00:00:00Z",
        "cwd": "/project",
        "message": {"role": "user", "content": text},
    }


def setup(tmp_path):
    home = tmp_path / "claude"
    path = home / "projects" / "project" / "session.jsonl"
    path.parent.mkdir(parents=True)
    source = Source("claude", "Claude", home, "test")
    store = Store(tmp_path / "db.sqlite3")
    return source, path, store, Collector(store)


def test_capture_restart_and_distinct_identical_turns(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("same", "one")) + line(claude_message("same", "two")))
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
    path = (
        home / "sessions" / "rollout-2026-09-21T00-00-00-12345678-1234-1234-1234-123456789012.jsonl"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(
        line(
            {
                "type": "session_meta",
                "payload": {"id": "12345678-1234-1234-1234-123456789012", "cwd": "/repo"},
            }
        )
        + line({"type": "event_msg", "payload": {"type": "user_message", "message": "earlier"}})
        + line(
            {
                "type": "response_item",
                "timestamp": "now",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "hello"}],
                },
            }
        )
        + line({"type": "future_event", "payload": {"value": 1}})
    )
    store = Store(tmp_path / "db.sqlite3")
    source = Source("codex", "Codex", home, "test")
    assert Collector(store).scan_once([source]).records == 4
    assert store.db.execute("SELECT text,role FROM messages WHERE kind='message'").fetchone() == (
        "hello",
        "user",
    )
    assert store.db.execute("SELECT project FROM sessions").fetchone() == ("/repo",)
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 4
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


def test_an_empty_file_is_tracked_without_records(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(b"")
    result = collector.scan_file(source, path)
    assert (result.records, result.pending, result.errors) == (0, 0, 0)
    assert store.db.execute("SELECT checkpoint,fingerprint FROM generations").fetchone() == (0, "")
    store.close()


def test_a_rewritten_prefix_starts_a_new_generation(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("original", "one")))
    assert collector.scan_file(source, path).records == 1
    rewritten = line(claude_message("changed!", "one"))
    assert len(rewritten) == len(line(claude_message("original", "one")))
    path.write_bytes(rewritten)
    assert collector.scan_file(source, path).records == 1
    assert store.db.execute("SELECT reason FROM generations ORDER BY number").fetchall() == [
        ("first observation",),
        ("committed prefix changed",),
    ]
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 2
    store.close()


def test_an_oversized_record_is_reported_without_advancing(tmp_path, monkeypatch):
    source, path, store, collector = setup(tmp_path)
    monkeypatch.setattr("recurrence_ranger.capture.MAX_RECORD_BYTES", 32)
    path.write_bytes(line(claude_message("far too long for the reduced record limit")))
    assert collector.scan_file(source, path).errors == 1
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone() == (0,)
    assert store.db.execute("SELECT COUNT(*) FROM generations").fetchone() == (0,)
    detail = store.db.execute("SELECT stage,detail FROM errors").fetchone()
    assert detail[0] == "capture"
    assert "exceeds 32 bytes" in detail[1]
    monkeypatch.undo()
    assert collector.scan_file(source, path).records == 1
    store.close()


def test_a_byte_budget_splits_one_file_across_scans(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("first", "one")) + line(claude_message("second", "two")))
    assert collector.scan_file(source, path, budget=1).records == 1
    assert collector.scan_file(source, path, budget=1).records == 1
    assert collector.scan_file(source, path, budget=1).records == 0
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 2
    store.close()


def test_a_partly_captured_file_is_selected_again(tmp_path):
    source, path, store, _ = setup(tmp_path)
    collector = Collector(store, file_budget=1)
    path.write_bytes(line(claude_message("first", "one")) + line(claude_message("second", "two")))
    assert collector.scan_once([source]).records == 1
    assert collector.scan_once([source]).records == 1
    assert collector.scan_once([source]).records == 0
    store.close()


def test_a_stale_checkpoint_does_not_duplicate_records(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("first", "one")) + line(claude_message("second", "two")))
    assert collector.scan_file(source, path).records == 2
    with store.db:
        store.db.execute("UPDATE generations SET checkpoint=0,fingerprint=''")
    result = collector.scan_file(source, path)
    assert (result.records, result.errors) == (0, 0)
    assert store.db.execute("SELECT COUNT(*) FROM raw_records").fetchone()[0] == 2
    assert store.db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 2
    store.close()


def test_a_failure_to_record_a_failure_still_reports_the_error(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("first")))
    store.db.execute("""CREATE TRIGGER reject_record BEFORE INSERT ON raw_records
                        BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
    store.db.execute("""CREATE TRIGGER reject_error BEFORE INSERT ON errors
                        BEGIN SELECT RAISE(ABORT, 'simulated error table failure'); END""")
    assert collector.scan_file(source, path).errors == 1
    assert store.db.execute("SELECT COUNT(*) FROM errors").fetchone()[0] == 0
    store.close()


def test_one_open_error_is_not_recorded_twice(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("first")))
    store.db.execute("""CREATE TRIGGER reject_record BEFORE INSERT ON raw_records
                        BEGIN SELECT RAISE(ABORT, 'simulated disk failure'); END""")
    assert collector.scan_file(source, path).errors == 1
    assert collector.scan_file(source, path).errors == 1
    assert store.db.execute("SELECT COUNT(*) FROM errors").fetchone()[0] == 1
    store.db.execute("DROP TRIGGER reject_record")
    assert collector.scan_file(source, path).records == 1
    assert store.db.execute("SELECT COUNT(*) FROM errors WHERE resolved_at IS NULL").fetchone() == (
        0,
    )
    store.close()


def test_an_unreadable_path_is_reported_during_a_scan(tmp_path):
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("first")))
    (path.parent / "dangling.jsonl").symlink_to(tmp_path / "gone.jsonl")
    result = collector.scan_once([source])
    assert (result.records, result.errors) == (1, 1)
    assert store.db.execute("SELECT stage FROM errors").fetchone() == ("stat",)
    store.close()


def test_a_deleted_file_is_marked_missing_and_its_tail_abandoned(tmp_path):
    source, path, store, collector = setup(tmp_path)
    complete = line(claude_message("first"))
    path.write_bytes(complete + b'{"unfinished":')
    assert collector.scan_once([source]).pending == 1
    path.unlink()
    collector.scan_once([source])
    assert store.db.execute("SELECT missing FROM files").fetchone() == (1,)
    assert store.db.execute("SELECT status FROM pending_fragments").fetchone() == ("abandoned",)
    collector.scan_once([source])
    assert store.db.execute("SELECT COUNT(*) FROM files WHERE missing=1").fetchone() == (1,)
    store.close()


def test_a_file_row_without_a_generation_is_marked_missing(tmp_path):
    """A crash can leave a file row behind before any generation was committed."""
    source, path, store, collector = setup(tmp_path)
    path.write_bytes(line(claude_message("first")))
    collector.scan_once([source])
    with store.db:
        store.db.execute(
            "INSERT INTO files(source_id,path,last_seen) VALUES (?,?,?)",
            (source.id, str(path.parent / "vanished.jsonl"), "now"),
        )
    collector.scan_once([source])
    assert store.db.execute(
        "SELECT missing FROM files WHERE path LIKE '%vanished.jsonl'"
    ).fetchone() == (1,)
    assert store.db.execute("SELECT COUNT(*) FROM pending_fragments").fetchone() == (0,)
    store.close()


def test_a_record_nested_too_deeply_does_not_stop_capture(tmp_path):
    source, path, store, collector = setup(tmp_path)
    deep = b"[" * 1_000_000 + b"]" * 1_000_000 + b"\n"
    path.write_bytes(deep + line(claude_message("after it")))
    result = collector.scan_once([source])
    assert (result.records, result.errors) == (2, 0)
    assert store.db.execute(
        "SELECT parse_status FROM raw_records ORDER BY start_offset"
    ).fetchall() == [("malformed",), ("parsed",)]
    assert store.db.execute("SELECT text FROM messages").fetchall() == [("after it",)]
