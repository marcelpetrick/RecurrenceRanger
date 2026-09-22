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


def test_the_own_project_condition_excludes_both_projects_and_keeps_the_rest():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE prompts (id INTEGER PRIMARY KEY, project TEXT)")
    db.executemany(
        "INSERT INTO prompts VALUES (?,?)",
        [
            (1, "/home/user/repos/RecurrenceRanger"),
            (2, "/home/user/20260921_MarcelsWishlistForSoftwareProjects/sub"),
            (3, "/home/user/repos/Other"),
            (4, None),
        ],
    )
    condition = derived.outside_own_projects("p.project")
    assert db.execute(f"SELECT p.id FROM prompts p WHERE {condition} ORDER BY p.id").fetchall() == [
        (3,),
        (4,),
    ]
