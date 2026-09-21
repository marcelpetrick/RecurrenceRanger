import json
import os
import runpy
import signal
import sqlite3
import sys

import pytest

from recurrence_ranger.capture import Collector, ScanResult
from recurrence_ranger.cli import main, writer_lock


def test_cli_backfill_status_verify_and_backup(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    transcript = home / ".claude" / "projects" / "project" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "one",
                "uuid": "u1",
                "message": {"role": "user", "content": "hello"},
            }
        )
        + "\n"
    )
    (home / ".claude" / "history.jsonl").write_text(
        json.dumps(
            {
                "display": "hello",
                "sessionId": "one",
                "project": "/project",
                "timestamp": 1,
            }
        )
        + "\n"
    )
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {"label": "Claude", "tool": "claude", "home": str(home / ".claude")},
                ],
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    db = tmp_path / "private" / "db.sqlite3"
    prefix = ["--db", str(db), "--manifest", str(manifest)]
    assert main([*prefix, "backfill", "--max-files", "1"]) == 0
    capsys.readouterr()
    assert main([*prefix, "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["sources"][0]["records"] == 2
    assert status["ingestion_watermark"] == 2
    assert main([*prefix, "verify"]) == 0
    assert json.loads(capsys.readouterr().out)["checkpoint_gaps"] == []
    backup = tmp_path / "backup.sqlite3"
    assert main([*prefix, "backup", str(backup)]) == 0
    capsys.readouterr()
    assert main([*prefix, "restore-check", str(backup)]) == 0
    assert json.loads(capsys.readouterr().out)["raw_records"] == 2
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM ingestion_runs").fetchone()[0] == 1


def test_second_writer_is_rejected(tmp_path):
    path = tmp_path / "db.sqlite3"
    with writer_lock(path):
        try:
            with writer_lock(path):
                raise AssertionError("second lock should fail")
        except RuntimeError as error:
            assert "another collector" in str(error)


def _profile(tmp_path, monkeypatch):
    """A private home with one transcript plus a manifest naming it and a missing home."""
    home = tmp_path / "home"
    transcript = home / ".claude" / "projects" / "project" / "session.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text(
        json.dumps(
            {
                "type": "user",
                "sessionId": "one",
                "uuid": "u1",
                "message": {"role": "user", "content": "hello"},
            }
        )
        + "\n"
    )
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {"label": "Claude", "tool": "claude", "home": str(home / ".claude")},
                    {"label": "Codex DMO", "tool": "codex", "home": str(home / ".codex-dmo")},
                ],
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    return transcript, [
        "--db",
        str(tmp_path / "private" / "db.sqlite3"),
        "--manifest",
        str(manifest),
    ]


def test_inventory_reports_availability_and_unreadable_files(tmp_path, monkeypatch, capsys):
    transcript, prefix = _profile(tmp_path, monkeypatch)
    (transcript.parent / "dangling.jsonl").symlink_to(tmp_path / "gone.jsonl")
    assert main([*prefix, "inventory"]) == 0
    profiles = {row["label"]: row for row in json.loads(capsys.readouterr().out)["sources"]}
    assert profiles["Claude"]["available"] is True
    assert profiles["Claude"]["files"] == 2
    assert profiles["Claude"]["stat_failures"] == 1
    assert profiles["Claude"]["bytes"] == transcript.stat().st_size
    assert profiles["Codex DMO"]["available"] is False
    assert profiles["Codex DMO"]["files"] == 0


def test_verify_reports_a_missing_record_as_a_gap(tmp_path, monkeypatch, capsys):
    transcript, prefix = _profile(tmp_path, monkeypatch)
    with transcript.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "type": "user",
                    "sessionId": "one",
                    "uuid": "u2",
                    "message": {"role": "user", "content": "second"},
                }
            )
            + "\n"
        )
    assert main([*prefix, "backfill"]) == 0
    capsys.readouterr()
    with sqlite3.connect(prefix[1]) as connection:
        connection.execute("DELETE FROM raw_records WHERE start_offset=0")
    assert main([*prefix, "verify"]) == 1
    gaps = json.loads(capsys.readouterr().out)["checkpoint_gaps"]
    assert [gap["expected"] for gap in gaps] == [0]
    assert gaps[0]["start"] > 0
    with sqlite3.connect(prefix[1]) as connection:
        connection.execute("DELETE FROM raw_records")
    assert main([*prefix, "verify"]) == 1
    assert json.loads(capsys.readouterr().out)["checkpoint_gaps"] == [
        {"generation": 1, "expected": 0, "checkpoint": transcript.stat().st_size}
    ]


def test_restore_check_rejects_a_file_that_is_not_a_database(tmp_path, monkeypatch, capsys):
    _, prefix = _profile(tmp_path, monkeypatch)
    broken = tmp_path / "broken.sqlite3"
    broken.write_bytes(b"not a database")
    assert main([*prefix, "restore-check", str(broken)]) == 1
    assert "recurrence-ranger:" in capsys.readouterr().err


def test_collection_bounds_must_be_positive(tmp_path, monkeypatch, capsys):
    _, prefix = _profile(tmp_path, monkeypatch)
    assert main([*prefix, "scan", "--max-files", "0"]) == 1
    assert "max-files" in capsys.readouterr().err
    assert main([*prefix, "run", "--poll-seconds", "0"]) == 1
    assert "poll-seconds" in capsys.readouterr().err


def test_run_stops_on_a_termination_signal(tmp_path, monkeypatch, capsys):
    _, prefix = _profile(tmp_path, monkeypatch)

    def scan_then_terminate(self, sources, *, max_files=32):
        os.kill(os.getpid(), signal.SIGTERM)
        return ScanResult(files=1, records=1)

    monkeypatch.setattr(Collector, "scan_once", scan_then_terminate)
    assert main([*prefix, "run", "--poll-seconds", "0.01"]) == 0
    assert json.loads(capsys.readouterr().out)["cycles"] == 1


def test_run_stops_after_the_requested_cycles(tmp_path, monkeypatch, capsys):
    _, prefix = _profile(tmp_path, monkeypatch)
    assert main([*prefix, "run", "--max-cycles", "2", "--poll-seconds", "0.01"]) == 0
    assert json.loads(capsys.readouterr().out)["cycles"] == 2


def test_backfill_stops_when_capture_keeps_failing(tmp_path, monkeypatch, capsys):
    _, prefix = _profile(tmp_path, monkeypatch)
    monkeypatch.setattr(
        Collector, "scan_once", lambda self, sources, max_files=32: ScanResult(files=1, errors=1)
    )
    assert main([*prefix, "backfill"]) == 1
    assert "capture stalled" in capsys.readouterr().err
    with sqlite3.connect(prefix[1]) as connection:
        assert connection.execute("SELECT errors FROM ingestion_runs").fetchone() == (2,)


def test_module_entry_point_runs_the_cli(tmp_path, monkeypatch, capsys):
    _, prefix = _profile(tmp_path, monkeypatch)
    monkeypatch.setattr(sys, "argv", ["recurrence-ranger", *prefix, "status"])
    with pytest.raises(SystemExit) as exit_code:
        runpy.run_module("recurrence_ranger", run_name="__main__")
    assert exit_code.value.code == 0
    assert json.loads(capsys.readouterr().out)["ingestion_watermark"] == 0
