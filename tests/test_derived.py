import sqlite3

from recurrence_ranger import derived


def test_the_stage_tables_are_created_once_and_are_idempotent(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY)")
        derived.create(db, *derived.MODEL_TABLES, derived.RECALL_CANDIDATES)
        derived.create(db, *derived.MODEL_TABLES, derived.RECALL_CANDIDATES)
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {
        "relevance",
        "extraction_reviews",
        "guideline_occurrences",
        "recall_candidates",
    } <= tables


def test_relevance_keeps_one_row_per_prompt(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY)")
        derived.create(db, derived.RELEVANCE)
        db.execute("INSERT INTO relevance VALUES (1,'software_instruction','m',2,'now',0,NULL)")
        try:
            db.execute("INSERT INTO relevance VALUES (1,'nonsoftware','m',2,'now',0,NULL)")
        except sqlite3.IntegrityError as error:
            assert "relevance.prompt_id" in str(error)
        else:
            raise AssertionError("a prompt must not carry two labels")
