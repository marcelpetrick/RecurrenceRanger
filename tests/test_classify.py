import sqlite3

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
