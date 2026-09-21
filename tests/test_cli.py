import json
import sqlite3

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
