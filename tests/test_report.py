import json
import sqlite3

import pytest

from recurrence_ranger import classify, extract, report
from recurrence_ranger.capture import Collector
from recurrence_ranger.corpus import SCHEMA, derive
from recurrence_ranger.recall import flag
from recurrence_ranger.sources import Source
from recurrence_ranger.store import Store


def _line(value):
    return json.dumps(value).encode() + b"\n"


def _prompt(text, uuid, project="/work/project"):
    return {
        "type": "user",
        "sessionId": "s",
        "uuid": uuid,
        "timestamp": f"2026-09-21T00:0{uuid}:00Z",
        "cwd": project,
        "message": {"role": "user", "content": text},
    }


def _corpus(tmp_path):
    home = tmp_path / "claude"
    transcript = home / "projects" / "one.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(
        _line(_prompt("add tests and a README", "1"))
        + _line(_prompt("what is the weather?", "2"))
        + _line(_prompt("pin the dependencies", "3", "/work/RecurrenceRanger"))
    )
    capture_path = tmp_path / "capture.sqlite3"
    store = Store(capture_path)
    Collector(store).scan_once([Source("claude", "Claude", home, "test")])
    store.close()
    corpus_path = tmp_path / "corpus.sqlite3"
    derive(capture_path, corpus_path)
    return corpus_path


def test_summary_reports_stage_progress_and_excludes_this_project(tmp_path, monkeypatch):
    corpus_path = _corpus(tmp_path)
    labels = {
        "add tests and a README": "software_instruction",
        "what is the weather?": "nonsoftware",
        "pin the dependencies": "software_instruction",
    }
    monkeypatch.setattr(
        classify,
        "_request",
        lambda rows, model, endpoint: {row_id: labels[text] for row_id, text in rows},
    )
    assert classify.classify(corpus_path)["remaining"] == 0
    assert flag(corpus_path)["flagged"] == 0
    monkeypatch.setattr(
        extract,
        "_request",
        lambda rows, model, endpoint: {
            row_id: ["TESTS", "README"] if "tests" in text else ["PIN_VERSIONS"]
            for row_id, text in rows
        },
    )
    assert extract.extract(corpus_path)["remaining"] == 0

    summary = report.summarize(corpus_path)
    assert summary["watermark"] == 3
    assert summary["occurrences"] == [("human", 3)]
    assert summary["prompts_by_profile"] == [("Claude", "human", 3)]
    assert summary["relevance"] == [("nonsoftware", 1), ("software_instruction", 2)]
    assert summary["relevance_model_errors"] == 0
    assert summary["relevance_remaining"] == 0
    assert summary["extraction_reviewed"] == 1
    assert summary["extraction_model_errors"] == 0
    assert summary["themes"] == [
        {
            "theme": "README",
            "prompts": 1,
            "sessions": 1,
            "projects_with_path": 1,
            "profiles": 1,
        },
        {
            "theme": "TESTS",
            "prompts": 1,
            "sessions": 1,
            "projects_with_path": 1,
            "profiles": 1,
        },
    ]


def test_summary_omits_stages_that_have_not_run(tmp_path):
    corpus_path = _corpus(tmp_path)
    summary = report.summarize(corpus_path)
    assert summary["parser_version"] == 1
    assert summary["created_at"]
    assert str(tmp_path) in summary["source_path"]
    assert "relevance" not in summary
    assert "themes" not in summary


def test_summary_rejects_a_database_without_a_corpus_run(tmp_path):
    path = tmp_path / "empty.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(SCHEMA)
    with pytest.raises(ValueError, match="no corpus run"):
        report.summarize(path)


def test_report_command_prints_json(tmp_path, capsys):
    corpus_path = _corpus(tmp_path)
    assert report.main([str(corpus_path)]) == 0
    assert json.loads(capsys.readouterr().out)["watermark"] == 3
