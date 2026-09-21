import json
import sqlite3

from recurrence_ranger.evidence_audit import audit, main


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


def test_audit_command_prints_counts_without_prompt_text(tmp_path, capsys):
    path = tmp_path / "corpus.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE prompts (
                 primary_record_id INTEGER, profile TEXT, session TEXT,
                 project TEXT, text TEXT, authorship TEXT)"""
        )
        db.execute(
            "INSERT INTO prompts VALUES (5,'claude','one','/a',?,'human')",
            ("Run the localpipeline.sh before every commit, and keep it robust.",),
        )
    assert main([str(path)]) == 0
    printed = capsys.readouterr().out
    assert "localpipeline" not in printed
    counts = json.loads(printed)
    assert counts["CI_LOCAL"]["sample_raw_record_ids"] == [5]
    assert counts["ROBUST"]["matching_prompts"] == 1
    assert counts["COVERAGE"]["matching_prompts"] == 0


def test_patterns_observed_in_the_corpus_are_matched(tmp_path):
    path = tmp_path / "corpus.sqlite3"
    examples = {
        "FINISH_ALL": "ok, get all done, run the commands yourself",
        "PLAN_FIRST": "make a plan first, then implement it",
        "SELF_REVIEW": "fix the findings and review yourself",
        "FIX_ALL_FINDINGS": "fix all the high and medium findings, one by one",
        "RELEASE": "push and make a public release",
        "VERSION_BUMP": "atomic commits, and bump the version each time",
        "CRISP": "keep the description crisp, this is way too much text",
        "WATCH_CI": "then watch the CI because i started a new run",
        "MINIMAL_CHANGE": "get it done with minimal changes, leave the rest alone",
        "EVIDENCE": "if you can make your claim testable, then do",
        "PRIVACY_REDACT": "record the demo but redact sensitive information",
        "DOCUMENT_DECISION": "document the decision, then commit",
        "TICKET_TRACE": "make a merge request linked to the ticket",
    }
    with sqlite3.connect(path) as db:
        db.execute(
            """CREATE TABLE prompts (
                 primary_record_id INTEGER, profile TEXT, session TEXT,
                 project TEXT, text TEXT, authorship TEXT)"""
        )
        db.executemany(
            "INSERT INTO prompts VALUES (?,'claude',?,'/work',?,'human')",
            [(number, name, text) for number, (name, text) in enumerate(examples.items(), start=1)],
        )
    result = audit(path)
    for name in examples:
        assert result[name]["matching_prompts"] >= 1, name
    assert result["C4"]["matching_prompts"] == 0
