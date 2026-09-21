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
