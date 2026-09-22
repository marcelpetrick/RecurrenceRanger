import json
import sqlite3

import pytest

from recurrence_ranger.sources import Source, conversation_files, discover, load_manifest
from recurrence_ranger.store import Store, connect_read_only


def test_discovery_keeps_explicit_missing_and_deduplicates_alias(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    (home / ".claude-copy").symlink_to(home / ".claude")
    (home / ".claude.lock").mkdir()
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {"tool": "claude", "label": "Primary", "home": str(home / ".claude-copy")},
                    {"tool": "codex", "label": "Missing", "home": str(home / ".codex-dmo")},
                ],
            }
        )
    )
    monkeypatch.setenv("HOME", str(home))
    sources = discover(manifest, home=home)
    assert len([s for s in sources if s.tool == "claude"]) == 1
    assert next(s for s in sources if s.label == "Missing").exists is False


def test_file_walk_does_not_follow_directory_symlinks(tmp_path):
    root = tmp_path / "claude"
    project = root / "projects" / "one"
    project.mkdir(parents=True)
    (project / "a.jsonl").write_text("{}\n")
    (root / "projects" / "loop").symlink_to(root / "projects")
    assert conversation_files(Source("claude", "test", root, "test")) == [project / "a.jsonl"]


def test_store_schema_backup_and_newer_version_guard(tmp_path):
    path = tmp_path / "private" / "db.sqlite3"
    store = Store(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
    with store.db:
        store.db.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?)",
            ("claude:one", "claude", "One", "/one", "test", 1, "now"),
        )
    backup = tmp_path / "backup.sqlite3"
    store.backup(backup)
    assert sqlite3.connect(backup).execute("SELECT label FROM sources").fetchone() == ("One",)
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(RuntimeError, match="newer"):
        Store(path)


def test_manifest_rejects_unknown_schema_and_tools(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(json.dumps({"schema_version": 2, "sources": []}))
    with pytest.raises(ValueError, match="unsupported source manifest"):
        load_manifest(path)
    path.write_text(json.dumps({"schema_version": 1, "sources": {}}))
    with pytest.raises(ValueError, match="unsupported source manifest"):
        load_manifest(path)
    path.write_text(
        json.dumps(
            {"schema_version": 1, "sources": [{"tool": "gemini", "label": "G", "home": "~/.g"}]}
        )
    )
    with pytest.raises(ValueError, match="unsupported tool: gemini"):
        load_manifest(path)


def test_discovery_reads_environment_and_launcher_homes(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude-env" / "projects").mkdir(parents=True)
    (home / ".codex-launcher" / "sessions").mkdir(parents=True)
    (home / ".zshrc").write_text(
        "# export CODEX_HOME=$HOME/.codex-commented\n"
        'export CODEX_HOME="$HOME/.codex-launcher"\n'
        "alias c='env CLAUDE_CONFIG_DIR=~/.claude-alias claude'\n"
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude-env"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    sources = discover(home=home)
    homes = {str(source.home) for source in sources}
    origins = {source.origin for source in sources}
    assert next(s for s in sources if s.origin == "environment").home == home / ".claude-env"
    assert str(home / ".codex-launcher") in homes
    assert str(home / ".claude-alias") in homes
    assert str(home / ".codex-commented") not in homes
    assert origins >= {"environment", "launcher:.zshrc", "default"}


def test_discovery_survives_unreadable_shell_configuration(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".config" / "fish").mkdir(parents=True)
    (home / ".zshrc").mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    assert [source.origin for source in discover(home=home)] == ["default", "default"]


def test_codex_files_include_archives_and_skip_other_names(tmp_path):
    home = tmp_path / "codex"
    (home / "sessions").mkdir(parents=True)
    (home / "archived_sessions").mkdir()
    rollout = home / "sessions" / "rollout-1.jsonl"
    archived = home / "archived_sessions" / "rollout-0.jsonl"
    for path in (rollout, archived):
        path.write_text("{}\n")
    (home / "sessions" / "notes.jsonl").write_text("{}\n")
    (home / "history.jsonl").write_text("{}\n")
    found = conversation_files(Source("codex", "Codex", home, "test"))
    assert set(found) == {rollout, archived, home / "history.jsonl"}


def test_store_migrates_a_first_generation_database(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
          CREATE TABLE sources (id TEXT PRIMARY KEY, tool TEXT NOT NULL, label TEXT NOT NULL,
            home TEXT NOT NULL, origin TEXT NOT NULL, available INTEGER NOT NULL,
            last_seen TEXT NOT NULL);
          CREATE TABLE files (id INTEGER PRIMARY KEY, source_id TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE, last_seen TEXT, missing INTEGER NOT NULL DEFAULT 0,
            current_generation INTEGER);
          CREATE TABLE generations (id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL,
            number INTEGER NOT NULL, device INTEGER NOT NULL, inode INTEGER NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL, checkpoint INTEGER NOT NULL DEFAULT 0,
            fingerprint TEXT NOT NULL DEFAULT '', last_size INTEGER NOT NULL DEFAULT 0,
            last_mtime_ns INTEGER NOT NULL DEFAULT 0, UNIQUE(file_id,number));
          CREATE TABLE raw_records (id INTEGER PRIMARY KEY, generation_id INTEGER NOT NULL,
            start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, data BLOB NOT NULL,
            digest TEXT NOT NULL, captured_at TEXT NOT NULL, parse_status TEXT NOT NULL,
            parse_error TEXT, UNIQUE(generation_id,start_offset,end_offset));
          INSERT INTO raw_records VALUES (1,1,0,3,'{}\n','d','now','parsed',NULL);
          PRAGMA user_version=1;
        """)
    store = Store(path)
    try:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 2
        assert store.db.execute("SELECT parser_version FROM raw_records").fetchone() == (1,)
        tables = {
            row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"file_aliases", "ingestion_runs"} <= tables
    finally:
        store.close()


@pytest.mark.parametrize("name", ["a#b", "a?b", "a%20b", "a b"])
def test_a_read_only_database_opens_the_named_file(tmp_path, name):
    path = tmp_path / name / "db.sqlite3"
    store = Store(path)
    with store.db:
        store.db.execute(
            "INSERT INTO sources VALUES (?,?,?,?,?,?,?)",
            ("claude:one", "claude", "One", "/one", "test", 1, "now"),
        )
    store.close()
    db = connect_read_only(path)
    try:
        assert db.execute("SELECT label FROM sources").fetchall() == [("One",)]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            db.execute("DELETE FROM sources")
    finally:
        db.close()


def test_a_backup_closes_its_target_connection(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.sqlite3")
    opened = []
    connect = sqlite3.connect

    class Tracked(sqlite3.Connection):
        closed = False

        def close(self):
            self.closed = True
            super().close()

    def tracking(path, *args, **kwargs):
        connection = connect(path, *args, factory=Tracked, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr("recurrence_ranger.store.sqlite3.connect", tracking)
    store.backup(tmp_path / "backup.sqlite3")
    monkeypatch.undo()
    store.close()
    assert [connection.closed for connection in opened] == [True]
