import json
import sqlite3

import pytest

from recurrence_ranger import classify


def test_relevance_classification_resumes_without_repeating_work(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,?)",
            [(1, "add tests", "human"), (2, "weather", "human"), (3, "attachment", "uncertain")],
        )
    calls = []

    def fake_request(rows, model, endpoint):
        calls.append([row[0] for row in rows])
        return {1: "software_instruction", 2: "nonsoftware"}

    monkeypatch.setattr(classify, "_request", fake_request)
    first = classify.classify(path)
    second = classify.classify(path)
    assert first["remaining"] == second["remaining"] == 0
    assert calls == [[1, 2]]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT label FROM relevance ORDER BY prompt_id").fetchall() == [
            ("software_instruction",),
            ("nonsoftware",),
        ]


def test_bad_model_output_is_isolated_to_one_prompt(monkeypatch):
    def fake_request(rows, model, endpoint):
        if any(row_id == 2 for row_id, _ in rows):
            raise ValueError("bad model output")
        return {row_id: "software_instruction" for row_id, _ in rows}

    monkeypatch.setattr(classify, "_request", fake_request)
    labels = classify._classify_rows([(1, "tests"), (2, "hostile text"), (3, "CI")], "m", "e")
    assert labels == {
        1: ("software_instruction", None),
        2: ("uncertain", "model output error: ValueError"),
        3: ("software_instruction", None),
    }


def test_exact_short_inputs_skip_the_model(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,?)",
            [(1, "/exit", "human"), (2, "continue", "human")],
        )

    def should_not_run(*args):
        raise AssertionError("model should not run for exact short inputs")

    monkeypatch.setattr(classify, "_request", should_not_run)
    summary = classify.classify(path)
    assert summary["remaining"] == 0
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT label FROM relevance ORDER BY prompt_id").fetchall() == [
            ("nonsoftware",),
            ("uncertain",),
        ]


def test_local_request_batches_prompts_and_maps_codes(local_model):
    sent = local_model({"labels": ["I", "N"]})
    labels = classify._request(
        [(7, "add tests"), (9, "x" * 7000)],
        "qwen3.5:4b",
        "http://127.0.0.1:11434/api/generate",
    )
    assert labels == {7: "software_instruction", 9: "nonsoftware"}
    payload = sent[0]["payload"]
    assert sent[0]["url"] == "http://127.0.0.1:11434/api/generate"
    assert payload["model"] == "qwen3.5:4b"
    assert payload["stream"] is False
    assert payload["options"]["temperature"] == 0
    assert payload["format"]["required"] == ["labels"]
    items = json.loads(payload["prompt"][payload["prompt"].index("\n[") + 1 :])
    assert [item["id"] for item in items] == [7, 9]
    assert len(items[1]["text"]) == 6000


def test_a_short_label_list_is_rejected(local_model):
    local_model({"labels": ["I"]})
    with pytest.raises(ValueError, match="wrong number of labels"):
        classify._request(
            [(1, "one"), (2, "two")], "qwen3.5:4b", "http://127.0.0.1:11434/api/generate"
        )


def test_truncated_prompts_are_recorded_as_truncated(tmp_path, local_model):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.execute("INSERT INTO prompts VALUES (1,?,'human')", ("y" * 6001,))
    local_model({"labels": ["I"]})
    assert classify.classify(path)["classified_this_run"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT truncated FROM relevance").fetchone() == (1,)


def test_classification_stops_at_the_requested_limit(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,'human')", [(1, "add tests"), (2, "add CI")]
        )
    monkeypatch.setattr(
        classify,
        "_request",
        lambda rows, model, endpoint: {row_id: "software_instruction" for row_id, _ in rows},
    )
    summary = classify.classify(path, batch_size=1, limit=1)
    assert (summary["classified_this_run"], summary["remaining"]) == (1, 1)


def test_an_older_relevance_table_gains_the_note_column(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.execute(
            """CREATE TABLE relevance (
                 prompt_id INTEGER PRIMARY KEY, label TEXT NOT NULL, model TEXT NOT NULL,
                 prompt_version INTEGER NOT NULL, classified_at TEXT NOT NULL,
                 truncated INTEGER NOT NULL DEFAULT 0)"""
        )
        db.execute("INSERT INTO prompts VALUES (1,'/exit','human')")
    monkeypatch.setattr(classify, "_request", lambda *args: {})
    assert classify.classify(path)["exact_short_inputs"] == 1
    with sqlite3.connect(path) as db:
        assert "note" in {row[1] for row in db.execute("PRAGMA table_info(relevance)")}


def test_classification_rejects_unsafe_settings_and_missing_corpora(tmp_path):
    with pytest.raises(ValueError, match="local loopback"):
        classify.classify(tmp_path / "corpus.sqlite3", endpoint="http://example.com/api/generate")
    with pytest.raises(ValueError, match="batch size"):
        classify.classify(tmp_path / "corpus.sqlite3", batch_size=0)
    with pytest.raises(FileNotFoundError):
        classify.classify(tmp_path / "missing.sqlite3")


def test_command_line_reports_label_counts(tmp_path, monkeypatch, capsys):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.execute("INSERT INTO prompts VALUES (1,'add tests','human')")
    monkeypatch.setattr(
        classify,
        "_request",
        lambda rows, model, endpoint: {row_id: "software_instruction" for row_id, _ in rows},
    )
    assert classify.main([str(path), "--batch-size", "2", "--limit", "5"]) == 0
    printed = capsys.readouterr().out
    assert json.loads(printed[printed.index("{\n") :])["labels"] == [["software_instruction", 1]]
