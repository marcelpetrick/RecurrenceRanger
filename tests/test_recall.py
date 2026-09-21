import json
import sqlite3

import pytest

from recurrence_ranger.recall import flag, main


def test_recall_flags_software_instructions_mislabeled_as_unrelated(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT,project TEXT)"
        )
        db.execute("CREATE TABLE relevance (prompt_id INTEGER,label TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,?,?)",
            [
                (1, "create the GitHub Actions pipeline", "human", "/other"),
                (2, "what is the weather?", "human", "/other"),
                (3, "add tests", "human", "/other"),
            ],
        )
        db.executemany(
            "INSERT INTO relevance VALUES (?,?)",
            [(1, "nonsoftware"), (2, "nonsoftware"), (3, "software_instruction")],
        )
    assert flag(path)["flagged"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT prompt_id FROM recall_candidates").fetchall() == [(1,)]


def test_recall_requires_an_existing_corpus(tmp_path):
    with pytest.raises(FileNotFoundError):
        flag(tmp_path / "missing.sqlite3")


def test_recall_command_prints_the_flag_count(tmp_path, capsys):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT,project TEXT)"
        )
        db.execute("CREATE TABLE relevance (prompt_id INTEGER,label TEXT)")
        db.execute("INSERT INTO prompts VALUES (1,'improve the coverage','human','/other')")
        db.execute("INSERT INTO relevance VALUES (1,'software_other')")
    assert main([str(path)]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed == {"flagged": 1, "rule_version": 1}
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT matched_term FROM recall_candidates").fetchone() == ("coverage",)
