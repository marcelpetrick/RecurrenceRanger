import json
import sqlite3

import pytest

from recurrence_ranger.sources import Source, conversation_files, discover
from recurrence_ranger.store import Store


def test_discovery_keeps_explicit_missing_and_deduplicates_alias(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    (home / ".claude-copy").symlink_to(home / ".claude")
    manifest = tmp_path / "sources.json"
    manifest.write_text(json.dumps({"schema_version": 1, "sources": [
        {"tool": "claude", "label": "Primary", "home": str(home / ".claude-copy")},
        {"tool": "codex", "label": "Missing", "home": str(home / ".codex-dmo")},
    ]}))
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
    assert store.db.execute("PRAGMA user_version").fetchone()[0] == 1
    with store.db:
        store.db.execute("INSERT INTO sources VALUES (?,?,?,?,?,?,?)", (
            "claude:one", "claude", "One", "/one", "test", 1, "now"))
    backup = tmp_path / "backup.sqlite3"
    store.backup(backup)
    assert sqlite3.connect(backup).execute("SELECT label FROM sources").fetchone() == ("One",)
    store.close()
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA user_version=999")
    with pytest.raises(RuntimeError, match="newer"):
        Store(path)
