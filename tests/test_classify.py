import json
import sqlite3

import pytest

from recurrence_ranger import classify, localmodel


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
        [(7, "add tests"), (9, "x" * (localmodel.REQUEST_CHARS + 1))],
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
    labels_schema = payload["format"]["properties"]["labels"]
    assert (labels_schema["minItems"], labels_schema["maxItems"]) == (2, 2)
    items = json.loads(payload["prompt"][payload["prompt"].index("\n[") + 1 :])
    assert [item["id"] for item in items] == [7, 9]
    assert len(items[1]["text"]) == localmodel.item_chars(2)


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
        db.execute(
            "INSERT INTO prompts VALUES (1,?,'human')",
            ("y" * (localmodel.item_chars(1) + 1),),
        )
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
    assert (
        classify.main(
            [
                str(path),
                "--batch-size",
                "2",
                "--limit",
                "5",
                "--endpoint",
                "http://127.0.0.1:9/api/generate",
            ]
        )
        == 0
    )
    printed = capsys.readouterr().out
    assert json.loads(printed[printed.index("{\n") :])["labels"] == [["software_instruction", 1]]


def test_an_unreachable_endpoint_leaves_prompts_unlabelled(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.execute("INSERT INTO prompts VALUES (1,'add tests','human')")

    def dead_endpoint(rows, model, endpoint):
        raise localmodel.EndpointUnavailable("http://127.0.0.1:1/api/generate did not answer")

    monkeypatch.setattr(classify, "_request", dead_endpoint)
    with pytest.raises(localmodel.EndpointUnavailable):
        classify.classify(path)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM relevance").fetchone() == (0,)


def test_the_command_reports_an_unreachable_endpoint(tmp_path, monkeypatch, capsys):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.execute("INSERT INTO prompts VALUES (1,'add tests','human')")

    def dead_endpoint(rows, model, endpoint):
        raise localmodel.EndpointUnavailable("no model listening")

    monkeypatch.setattr(classify, "_request", dead_endpoint)
    assert classify.main([str(path)]) == 1
    assert "no model listening" in capsys.readouterr().err


def test_concurrent_batches_are_all_recorded(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,'human')",
            [(number, f"add feature {number}") for number in range(1, 9)],
        )
    seen = []

    def fake_request(rows, model, endpoint):
        seen.append(tuple(row_id for row_id, _ in rows))
        return {row_id: "software_instruction" for row_id, _ in rows}

    monkeypatch.setattr(classify, "_request", fake_request)
    summary = classify.classify(path, batch_size=2, concurrency=4)
    assert summary["remaining"] == 0
    assert sorted(seen) == [(1, 2), (3, 4), (5, 6), (7, 8)]
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT COUNT(*) FROM relevance").fetchone() == (8,)


def test_concurrency_must_be_positive(tmp_path):
    with pytest.raises(ValueError, match="concurrency must be positive"):
        classify.classify(tmp_path / "corpus.sqlite3", concurrency=0)


def test_the_answer_schema_demands_one_label_per_prompt():
    schema = classify._format(3)["properties"]["labels"]
    assert (schema["minItems"], schema["maxItems"]) == (3, 3)
    assert set(schema["items"]["enum"]) == set(classify.LABELS)


def test_a_repeated_text_is_asked_once_and_labelled_alike(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,'human')",
            [(1, "add tests"), (2, "weather"), (3, "add tests"), (4, "add tests"), (5, "weather")],
        )
    calls = []

    def fake_request(rows, model, endpoint):
        calls.append([row_id for row_id, _ in rows])
        return {
            row_id: "software_instruction" if "tests" in text else "nonsoftware"
            for row_id, text in rows
        }

    monkeypatch.setattr(classify, "_request", fake_request)
    # Two prompts per round, so repeats arrive both within a round and in later rounds.
    summary = classify.classify(path, batch_size=2, concurrency=1)
    assert calls == [[1, 2]]
    assert summary["reused_same_text"] == 3
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT prompt_id,label,note FROM relevance ORDER BY prompt_id"
        ).fetchall() == [
            (1, "software_instruction", None),
            (2, "nonsoftware", None),
            (3, "software_instruction", None),
            (4, "software_instruction", None),
            (5, "nonsoftware", None),
        ]


def test_an_earlier_answer_is_reused_only_from_the_same_model_and_without_error(
    tmp_path, monkeypatch
):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,'human')",
            [
                (1, "add tests"),
                (2, "add CI"),
                (3, "add docs"),
                (4, "add tests"),
                (5, "add CI"),
                (6, "add docs"),
            ],
        )
    with sqlite3.connect(path) as db:
        classify.derived.create(db, classify.derived.RELEVANCE)
        db.executemany(
            "INSERT INTO relevance VALUES (?,?,?,?,'earlier',?,?)",
            [
                (1, "software_instruction", "qwen3.5:4b", classify.PROMPT_VERSION, 1, None),
                (
                    2,
                    "uncertain",
                    "qwen3.5:4b",
                    classify.PROMPT_VERSION,
                    0,
                    "model output error: KeyError",
                ),
                (3, "software_other", "another-model", classify.PROMPT_VERSION, 0, None),
            ],
        )
    calls = []

    def fake_request(rows, model, endpoint):
        calls.append([row_id for row_id, _ in rows])
        return {row_id: "software_instruction" for row_id, _ in rows}

    monkeypatch.setattr(classify, "_request", fake_request)
    assert classify.classify(path)["reused_same_text"] == 1
    assert calls == [[5, 6]]
    with sqlite3.connect(path) as db:
        # The reused answer keeps its truncation flag; the failed and foreign ones are asked.
        assert db.execute(
            "SELECT prompt_id,label,model,truncated FROM relevance WHERE prompt_id>3 "
            "ORDER BY prompt_id"
        ).fetchall() == [
            (4, "software_instruction", "qwen3.5:4b", 1),
            (5, "software_instruction", "qwen3.5:4b", 0),
            (6, "software_instruction", "qwen3.5:4b", 0),
        ]


def test_a_failed_answer_is_not_reused_for_a_later_repeat(tmp_path, monkeypatch):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY,text TEXT,authorship TEXT)")
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,'human')", [(1, "add tests"), (2, "add tests")]
        )
    calls = []

    def fails_once(rows, model, endpoint):
        calls.append([row_id for row_id, _ in rows])
        if len(calls) == 1:
            raise ValueError("model returned wrong number of labels")
        return {row_id: "software_instruction" for row_id, _ in rows}

    monkeypatch.setattr(classify, "_request", fails_once)
    assert classify.classify(path, batch_size=1, concurrency=1)["reused_same_text"] == 0
    assert calls == [[1], [2]]
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT prompt_id,label,note FROM relevance ORDER BY prompt_id"
        ).fetchall() == [
            (1, "uncertain", "model output error: ValueError"),
            (2, "software_instruction", None),
        ]
