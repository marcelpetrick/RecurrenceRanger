"""Count direct theme mentions as an independent check on model tags."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

PATTERNS = {
    "ATOMIC_COMMITS": r"\batomic\s+commits?\b|\bcommit\s+atomically\b",
    "CONVENTIONAL_COMMITS": r"\bconventional\s+commits?\b|\bconventional\s+commit\s+messages?\b",
    "CI_HOSTED": r"\bgithub\s+actions\b|\bgitlab\s+ci\b",
    "CI_LOCAL": r"\blocalpipeline(?:\.sh)?\b|\blocal\s+pipeline\b|\blocal\s+ci\b|\bci\.sh\b",
    "README_BADGES": r"\breadme.{0,120}\bbadges?\b|\bbadges?.{0,120}\breadme\b",
    "C4": r"\bc4.{0,100}(?:architecture|diagram|model|documentation)\b|"
    r"\b(?:architecture|diagram|model|documentation).{0,100}\bc4\b",
    "TESTS": r"\b(?:unit|integration|end.to.end)\s+tests?\b|\btestable\b",
    "COVERAGE": r"\bcoverage\b",
    "REVIEW_CODE_ARCH": r"\breview.{0,80}\b(?:code|architecture)\b|"
    r"\b(?:code|architecture).{0,80}\breview\b",
    "DEPENDENCIES": r"\bupdatedependencies\b|\bdependenc\w*.{0,50}(?:update|up.to.date|pin)\b",
    "ROBUST": r"\brobust\b",
    "DELEGATE": r"\bsubagents?\b|\bdelegate.{0,70}(?:smaller|lower|lesser)\s+models?\b",
}


def audit(path: Path) -> dict:
    path = path.expanduser().resolve()
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        patterns = {
            name: re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for name, pattern in PATTERNS.items()
        }
        matches = {name: [] for name in PATTERNS}
        rows = db.execute(
            """SELECT primary_record_id,profile,session,project,text FROM prompts
               WHERE authorship='human' AND COALESCE(project,'') NOT LIKE '%RecurrenceRanger%'
               AND COALESCE(project,'') NOT LIKE
                   '%20260921_MarcelsWishlistForSoftwareProjects%'
               ORDER BY primary_record_id"""
        )
        for record_id, profile, session, project, text in rows:
            # Most user instructions precede any pasted log or document.
            opening = text[:750]
            for name, pattern in patterns.items():
                if pattern.search(opening):
                    matches[name].append((record_id, profile, session, project))
        return {
            name: {
                "matching_prompts": len(items),
                "sessions": len({(profile, session) for _, profile, session, _ in items}),
                "projects_with_path": len({project for *_, project in items if project}),
                "profiles": len({profile for _, profile, _, _ in items}),
                "sample_raw_record_ids": [record_id for record_id, *_ in items[:8]],
            }
            for name, items in matches.items()
        }
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recurrence-ranger-evidence-audit")
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(audit(args.corpus), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
