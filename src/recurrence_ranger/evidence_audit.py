"""Count direct theme mentions as an independent check on model tags."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from recurrence_ranger import derived
from recurrence_ranger.store import connect_read_only

OUTSIDE_OWN_PROJECTS = derived.outside_own_projects("project")

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
    # Phrasings observed in the corpus itself, not seeded from the original request.
    "FINISH_ALL": r"\bget\s+(?:it|this|that|them|all|everything)\b.{0,30}\bdone\b|"
    r"\bget\s+all\s+done\b|\ball\s+done\b",
    "PLAN_FIRST": r"\bmake\s+a\s+plan\b|\bplan\s+first\b|\bthen\s+plan\b|\bplan\s+it\b",
    "SELF_REVIEW": r"\breview\s+(?:yourself|your\s+own|it\s+yourself|your\s+idea)\b|"
    r"\bself.review\b|\breview\s+your\b",
    "FIX_ALL_FINDINGS": r"\bfix\s+(?:all|every|each|those|these)\b.{0,40}"
    r"\b(?:findings?|issues?|comments?|errors?|problems?|bugs?)\b|\bfix\s+all\b",
    "RELEASE": r"\bpublic\s+release\b|\bmake\s+a\s+release\b|\brelease\s+public\w*\b|"
    r"\bpush\b.{0,20}\brelease\b",
    "VERSION_BUMP": r"\bversion\s+bump\w*\b|\bbump\s+(?:the\s+)?version\b|\bsemver\b",
    "CRISP": r"\bcrisp\b|\bbrief\b|\bconcise\b|\bnot?\s+tons\b|\btoo\s+much\s+text\b",
    "WATCH_CI": r"\bwatch\b.{0,20}\b(?:ci|pipeline|mr)\b|\bover\s?watch\b|"
    r"\bcheck\b.{0,25}\bpipeline\b",
    "MINIMAL_CHANGE": r"\bminimal\s+changes?\b|\bleast\b.{0,25}\bchanges?\b|"
    r"\bleave\s+the\s+rest\s+alone\b|\bonly\s+th(?:is|ese)\s+file",
    "EVIDENCE": r"\bgive\s+evidence\b|\bevidence\b|\btestable\b|\bverif(?:y|iable|ied)\b",
    "PRIVACY_REDACT": r"\bredact\w*\b|\bsensitive\s+(?:information|data|stuff)\b|"
    r"\b(?:dont|do\s+not|never)\s+disclose\b",
    "DOCUMENT_DECISION": r"\bdocument\b.{0,25}\b(?:decision|result|findings?|evaluation)\b|"
    r"\bwrite\b.{0,30}\binto\b.{0,25}\.md\b",
    "TICKET_TRACE": r"\blink(?:ed)?\b.{0,25}\bticket\b|\bconnect\b.{0,25}\bticket\b|"
    r"\bclose\w*\b.{0,25}\bticket\b|\bmerge\s+request\b|\bMR\b",
}


def audit(path: Path) -> dict:
    path = path.expanduser().resolve()
    db = connect_read_only(path)
    try:
        patterns = {
            name: re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for name, pattern in PATTERNS.items()
        }
        matches: dict[str, list[tuple[int, str, str, str | None]]] = {name: [] for name in PATTERNS}
        rows = db.execute(
            f"""SELECT primary_record_id,profile,session,project,text FROM prompts
               WHERE authorship='human' AND {OUTSIDE_OWN_PROJECTS}
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
