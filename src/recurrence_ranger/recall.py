"""Flag possible software instructions missed by local relevance triage."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

from recurrence_ranger import derived

OUTSIDE_OWN_PROJECTS = derived.outside_own_projects("p.project")

RULE_VERSION = 1
SOFTWARE_TERMS = re.compile(
    r"\b(?:ci|pipeline|github actions|readme|badges?|tests?|coverage|commits?|"
    r"review|architecture|c4|docs?|documentation|dependenc\w*|robust|"
    r"plan|finish|privacy|secrets?|delegate|performance|workflow)\b",
    re.IGNORECASE,
)


def flag(path: Path) -> dict:
    path = path.expanduser()
    if not path.is_file():
        raise FileNotFoundError(path)
    db = sqlite3.connect(path)
    try:
        derived.create(db, derived.RECALL_CANDIDATES)
        rows = db.execute(
            f"""SELECT p.id,p.text FROM prompts p JOIN relevance r ON r.prompt_id=p.id
               WHERE p.authorship='human' AND r.label!='software_instruction'
               AND {OUTSIDE_OWN_PROJECTS}"""
        )
        found = []
        for row_id, text in rows:
            if match := SOFTWARE_TERMS.search(text[:750]):
                found.append((row_id, match.group(0).lower(), RULE_VERSION))
        with db:
            db.execute("DELETE FROM recall_candidates")
            db.executemany("INSERT INTO recall_candidates VALUES (?,?,?)", found)
        return {"flagged": len(found), "rule_version": RULE_VERSION}
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recurrence-ranger-recall")
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(flag(args.corpus), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
