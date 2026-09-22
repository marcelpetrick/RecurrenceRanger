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
        [(3, "run the local pipeline with tests"), (4, "z" * (localmodel.REQUEST_CHARS + 1))],
        "qwen3.5:4b",
        "http://127.0.0.1:11434/api/generate",
    )
    assert themes == {3: ["TESTS", "CI_LOCAL"], 4: []}
    payload = sent[0]["payload"]
    assert payload["options"]["num_predict"] == 400
    themes_schema = payload["format"]["properties"]["themes"]
    assert (themes_schema["minItems"], themes_schema["maxItems"]) == (2, 2)
    items = json.loads(payload["prompt"][payload["prompt"].index("\n[") + 1 :])
    assert len(items[1]["text"]) == localmodel.item_chars(2)


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


def test_concurrent_extraction_records_every_batch(tmp_path, monkeypatch):
    rows = [(number, f"add tests for {number}") for number in range(1, 7)]
    path = _corpus_with_prompts(tmp_path / "corpus.sqlite3", rows)
    seen = []

    def fake_request(rows, model, endpoint):
        seen.append(tuple(row_id for row_id, _ in rows))
        return {row_id: ["TESTS"] for row_id, _ in rows}

    monkeypatch.setattr(extract, "_request", fake_request)
    summary = extract.extract(path, batch_size=2, concurrency=3)
    assert summary["remaining"] == 0
    assert sorted(seen) == [(1, 2), (3, 4), (5, 6)]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM guideline_occurrences").fetchone() == (6,)


def test_extraction_concurrency_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="concurrency must be positive"):
        extract.extract(tmp_path / "corpus.sqlite3", concurrency=-1)


def test_the_answer_schema_demands_one_theme_list_per_prompt():
    """An unbounded array let the model answer with none at all for the whole batch."""
    schema = extract._format(5)["properties"]["themes"]
    assert (schema["minItems"], schema["maxItems"]) == (5, 5)
    assert set(schema["items"]["items"]["enum"]) == set(extract.THEMES)


def test_a_repeated_text_is_extracted_once_and_tagged_alike(tmp_path, monkeypatch):
    path = _corpus_with_prompts(
        tmp_path / "corpus.sqlite3",
        [(1, "add tests and CI"), (2, "move button"), (3, "add tests and CI"), (4, "move button")],
    )
    calls = []

    def fake_request(rows, model, endpoint):
        calls.append([row_id for row_id, _ in rows])
        return {row_id: ["TESTS", "CI_LOCAL"] if "tests" in text else [] for row_id, text in rows}

    monkeypatch.setattr(extract, "_request", fake_request)
    summary = extract.extract(path, batch_size=2, concurrency=1)
    assert calls == [[1, 2]]
    assert summary["reused_same_text"] == 2
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT prompt_id,theme FROM guideline_occurrences ORDER BY prompt_id,theme"
        ).fetchall() == [(1, "CI_LOCAL"), (1, "TESTS"), (3, "CI_LOCAL"), (3, "TESTS")]
        assert db.execute(
            "SELECT COUNT(*) FROM extraction_reviews WHERE note IS NULL"
        ).fetchone() == (4,)


def test_an_earlier_theme_list_is_reused_but_a_failed_one_is_asked_again(tmp_path, monkeypatch):
    path = _corpus_with_prompts(
        tmp_path / "corpus.sqlite3",
        [(1, "add tests"), (2, "pin versions"), (3, "add tests"), (4, "pin versions")],
    )
    with sqlite3.connect(path) as db:
        extract.derived.create(
            db, extract.derived.EXTRACTION_REVIEWS, extract.derived.GUIDELINE_OCCURRENCES
        )
        db.execute(
            "INSERT INTO extraction_reviews VALUES (1,'qwen3.5:4b',?,'earlier',NULL)",
            (extract.EXTRACTOR_VERSION,),
        )
        db.execute("INSERT INTO guideline_occurrences VALUES (1,'TESTS')")
        db.execute(
            "INSERT INTO extraction_reviews VALUES "
            "(2,'qwen3.5:4b',?,'earlier','model output error: KeyError')",
            (extract.EXTRACTOR_VERSION,),
        )
    calls = []

    def fake_request(rows, model, endpoint):
        calls.append([row_id for row_id, _ in rows])
        return {row_id: ["PIN_VERSIONS"] for row_id, _ in rows}

    monkeypatch.setattr(extract, "_request", fake_request)
    assert extract.extract(path)["reused_same_text"] == 1
    assert calls == [[4]]
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT prompt_id,theme FROM guideline_occurrences WHERE prompt_id>2 ORDER BY prompt_id"
        ).fetchall() == [(3, "TESTS"), (4, "PIN_VERSIONS")]


def test_a_failed_theme_list_is_not_reused_for_a_later_repeat(tmp_path, monkeypatch):
    path = _corpus_with_prompts(tmp_path / "corpus.sqlite3", [(1, "add tests"), (2, "add tests")])
    calls = []

    def fails_once(rows, model, endpoint):
        calls.append([row_id for row_id, _ in rows])
        if len(calls) == 1:
            raise ValueError("model returned an unknown theme")
        return {row_id: ["TESTS"] for row_id, _ in rows}

    monkeypatch.setattr(extract, "_request", fails_once)
    assert extract.extract(path, batch_size=1, concurrency=1)["reused_same_text"] == 0
    assert calls == [[1], [2]]
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT prompt_id,note FROM extraction_reviews ORDER BY prompt_id"
        ).fetchall() == [(1, "model output error: ValueError"), (2, None)]


def test_the_earliest_of_several_earlier_theme_lists_is_reused(tmp_path, monkeypatch):
    path = _corpus_with_prompts(
        tmp_path / "corpus.sqlite3", [(1, "add tests"), (2, "add tests"), (3, "add tests")]
    )
    with sqlite3.connect(path) as db:
        extract.derived.create(
            db, extract.derived.EXTRACTION_REVIEWS, extract.derived.GUIDELINE_OCCURRENCES
        )
        for prompt_id, theme in ((1, "TESTS"), (2, "COVERAGE")):
            db.execute(
                "INSERT INTO extraction_reviews VALUES (?,'qwen3.5:4b',?,'earlier',NULL)",
                (prompt_id, extract.EXTRACTOR_VERSION),
            )
            db.execute("INSERT INTO guideline_occurrences VALUES (?,?)", (prompt_id, theme))
    monkeypatch.setattr(extract, "_request", lambda *args: pytest.fail("must not ask"))
    assert extract.extract(path)["reused_same_text"] == 1
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT theme FROM guideline_occurrences WHERE prompt_id=3"
        ).fetchall() == [("TESTS",)]
