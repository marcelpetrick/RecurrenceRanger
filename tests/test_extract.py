import json
import sqlite3

import pytest

from recurrence_ranger import extract, localmodel


def test_extraction_keeps_multiple_rules_and_empty_decisions(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,project TEXT)")
        db.execute("CREATE TABLE relevance (prompt_id INTEGER,label TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,?)",
            [
                (1, "add tests and CI", "/one"),
                (2, "move button", "/two"),
                (3, "add README", "/repo/20260921_MarcelsWishlistForSoftwareProjects"),
            ],
        )
        db.executemany(
            "INSERT INTO relevance VALUES (?,?)",
            [
                (1, "software_instruction"),
                (2, "software_instruction"),
                (3, "software_instruction"),
            ],
        )
    calls = []

    def fake_request(rows, model, endpoint):
        calls.append([row[0] for row in rows])
        return {1: ["TESTS", "CI_HOSTED"], 2: []}

    monkeypatch.setattr(extract, "_request", fake_request)
    first = extract.extract(path)
    second = extract.extract(path)
    assert first["remaining"] == second["remaining"] == 0
    assert calls == [[1, 2]]
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT prompt_id,theme FROM guideline_occurrences ORDER BY prompt_id,theme"
        ).fetchall() == [(1, "CI_HOSTED"), (1, "TESTS")]
        assert db.execute("SELECT COUNT(*) FROM extraction_reviews").fetchone()[0] == 2


def _corpus_with_prompts(path, rows):
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,project TEXT)")
        db.execute("CREATE TABLE relevance (prompt_id INTEGER,label TEXT)")
        db.executemany("INSERT INTO prompts VALUES (?,?,'/one')", rows)
        db.executemany(
            "INSERT INTO relevance VALUES (?,'software_instruction')",
            [(row_id,) for row_id, _ in rows],
        )
    return path


def test_local_request_returns_deduplicated_theme_codes(local_model):
    sent = local_model({"themes": [["TESTS", "TESTS", "CI_LOCAL"], []]})
    themes = extract._request(
        [(3, "run the local pipeline with tests"), (4, "z" * 7000)],
        "qwen3.5:4b",
        "http://127.0.0.1:11434/api/generate",
    )
    assert themes == {3: ["TESTS", "CI_LOCAL"], 4: []}
    payload = sent[0]["payload"]
    assert payload["options"]["num_predict"] == 400
    items = json.loads(payload["prompt"][payload["prompt"].index("\n[") + 1 :])
    assert len(items[1]["text"]) == 6000


def test_unknown_or_missing_theme_lists_are_rejected(local_model):
    local_model({"themes": [["NOT_A_THEME"]]})
    with pytest.raises(ValueError, match="unknown theme"):
        extract._request([(1, "one")], "m", "http://127.0.0.1:11434/api/generate")
    local_model({"themes": [[]]})
    with pytest.raises(ValueError, match="wrong number of theme lists"):
        extract._request([(1, "one"), (2, "two")], "m", "http://127.0.0.1:11434/api/generate")


def test_a_failing_prompt_is_isolated_and_recorded(tmp_path, local_model):
    path = _corpus_with_prompts(tmp_path / "corpus.sqlite3", [(1, "add tests"), (2, "add CI")])
    local_model({"themes": [["NOT_A_THEME"]]}, {"themes": [["TESTS"]]}, {"themes": [["CI_LOCAL"]]})
    assert extract.extract(path, batch_size=2)["remaining"] == 0
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT prompt_id,theme FROM guideline_occurrences ORDER BY prompt_id"
        ).fetchall() == [(1, "TESTS"), (2, "CI_LOCAL")]
        assert db.execute("SELECT note FROM extraction_reviews ORDER BY prompt_id").fetchall() == [
            (None,),
            (None,),
        ]


def test_extraction_stops_at_the_requested_limit(tmp_path, monkeypatch):
    path = _corpus_with_prompts(tmp_path / "corpus.sqlite3", [(1, "add tests"), (2, "add CI")])
    monkeypatch.setattr(
        extract, "_request", lambda rows, model, endpoint: {row_id: [] for row_id, _ in rows}
    )
    summary = extract.extract(path, batch_size=1, limit=1)
    assert (summary["reviewed_this_run"], summary["remaining"]) == (1, 1)


def test_extraction_rejects_unsafe_settings_and_missing_corpora(tmp_path):
    with pytest.raises(ValueError, match="local loopback"):
        extract.extract(tmp_path / "corpus.sqlite3", endpoint="http://example.com/api/generate")
    with pytest.raises(ValueError, match="batch size"):
        extract.extract(tmp_path / "corpus.sqlite3", batch_size=0)
    with pytest.raises(FileNotFoundError):
        extract.extract(tmp_path / "missing.sqlite3")


def test_command_line_reports_theme_counts(tmp_path, monkeypatch, capsys):
    path = _corpus_with_prompts(tmp_path / "corpus.sqlite3", [(1, "add tests")])
    monkeypatch.setattr(
        extract, "_request", lambda rows, model, endpoint: {row_id: ["TESTS"] for row_id, _ in rows}
    )
    assert (
        extract.main(
            [
                str(path),
                "--batch-size",
                "3",
                "--limit",
                "9",
                "--endpoint",
                "http://127.0.0.1:9/api/generate",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert json.loads(printed[printed.index("{\n") :])["themes"] == [["TESTS", 1]]


def test_a_persistently_failing_prompt_is_recorded_without_themes(monkeypatch):
    def fake_request(rows, model, endpoint):
        if any(row_id == 2 for row_id, _ in rows):
            raise ValueError("bad model output")
        return {row_id: ["TESTS"] for row_id, _ in rows}

    monkeypatch.setattr(extract, "_request", fake_request)
    assert extract._extract_rows([(1, "a"), (2, "hostile text"), (3, "c")], "m", "e") == {
        1: (["TESTS"], None),
        2: ([], "model output error: ValueError"),
        3: (["TESTS"], None),
    }


def test_an_unreachable_endpoint_stops_extraction(tmp_path, monkeypatch, capsys):
    path = _corpus_with_prompts(tmp_path / "corpus.sqlite3", [(1, "add tests")])

    def dead_endpoint(rows, model, endpoint):
        raise localmodel.EndpointUnavailable("no model listening")

    monkeypatch.setattr(extract, "_request", dead_endpoint)
    with pytest.raises(localmodel.EndpointUnavailable):
        extract.extract(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM extraction_reviews").fetchone() == (0,)
    assert extract.main([str(path)]) == 1
    assert "no model listening" in capsys.readouterr().err
