import sqlite3

from recurrence_ranger.evidence_audit import audit


def test_audit_counts_distinct_sources_and_excludes_planning_prompts(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE prompts (
                 primary_record_id INTEGER, profile TEXT, session TEXT,
                 project TEXT, text TEXT, authorship TEXT)"""
        )
        db.executemany(
            "INSERT INTO prompts VALUES (?,?,?,?,?,?)",
            [
                (4, "claude", "one", "/a", "Use atomic commits and GitHub Actions.", "human"),
                (8, "claude", "one", "/a", "Use atomic commits.", "human"),
                (12, "codex", "two", "/b", "Use atomic commits.", "human"),
                (15, "codex", "three", "/RecurrenceRanger", "Use atomic commits.", "human"),
                (
                    20,
                    "codex",
                    "four",
                    "/20260921_MarcelsWishlistForSoftwareProjects",
                    "Use atomic commits.",
                    "human",
                ),
                (23, "claude", "five", "/c", "Use atomic commits.", "uncertain"),
                (
                    30,
                    "codex",
                    "six",
                    "/c",
                    "Unrelated opening. " + "x" * 750 + "atomic commits",
                    "human",
                ),
            ],
        )

    result = audit(path)
    assert result["ATOMIC_COMMITS"] == {
        "matching_prompts": 3,
        "sessions": 2,
        "projects_with_path": 2,
        "profiles": 2,
        "sample_raw_record_ids": [4, 8, 12],
    }
    assert result["CI_HOSTED"]["sample_raw_record_ids"] == [4]
    assert result["C4"]["matching_prompts"] == 0
