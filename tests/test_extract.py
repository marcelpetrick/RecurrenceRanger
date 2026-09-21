import sqlite3

from recurrence_ranger import extract


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
