"""Aggregate private corpus coverage without printing prompt text."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from recurrence_ranger import derived
from recurrence_ranger.store import connect_read_only

OUTSIDE_OWN_PROJECTS = derived.outside_own_projects("p.project")


def summarize(path: Path) -> dict:
    path = path.expanduser().resolve()
    db = connect_read_only(path)
    try:
        snapshot = db.execute(
            "SELECT source_path,watermark,parser_version,created_at FROM corpus_runs"
        ).fetchone()
        if snapshot is None:
            raise ValueError("database has no corpus run")
        result = {
            "source_path": snapshot[0],
            "watermark": snapshot[1],
            "parser_version": snapshot[2],
            "created_at": snapshot[3],
            "occurrences": db.execute(
                "SELECT decision,COUNT(*) FROM occurrences GROUP BY decision ORDER BY decision"
            ).fetchall(),
            "prompts_by_profile": db.execute(
                "SELECT profile,authorship,COUNT(*) FROM prompts "
                "GROUP BY profile,authorship ORDER BY profile,authorship"
            ).fetchall(),
        }
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "relevance" in tables:
            result["relevance"] = db.execute(
                "SELECT label,COUNT(*) FROM relevance GROUP BY label ORDER BY label"
            ).fetchall()
            result["relevance_model_errors"] = db.execute(
                "SELECT COUNT(*) FROM relevance WHERE note LIKE 'model output error:%'"
            ).fetchone()[0]
            result["relevance_remaining"] = db.execute(
                """SELECT COUNT(*) FROM prompts p LEFT JOIN relevance r ON r.prompt_id=p.id
                   WHERE p.authorship='human' AND r.prompt_id IS NULL"""
            ).fetchone()[0]
        if "extraction_reviews" in tables:
            result["extraction_reviewed"] = db.execute(
                "SELECT COUNT(*) FROM extraction_reviews"
            ).fetchone()[0]
            result["extraction_model_errors"] = db.execute(
                "SELECT COUNT(*) FROM extraction_reviews WHERE note IS NOT NULL"
            ).fetchone()[0]
            result["themes"] = [
                {
                    "theme": row[0],
                    "prompts": row[1],
                    "sessions": row[2],
                    "projects_with_path": row[3],
                    "profiles": row[4],
                }
                for row in db.execute(
                    f"""SELECT g.theme,COUNT(*),
                              COUNT(DISTINCT p.profile||':'||p.session),
                              COUNT(DISTINCT p.project),COUNT(DISTINCT p.profile)
                       FROM guideline_occurrences g JOIN prompts p ON p.id=g.prompt_id
                       WHERE {OUTSIDE_OWN_PROJECTS}
                       GROUP BY g.theme ORDER BY COUNT(*) DESC,g.theme"""
                )
            ]
        return result
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recurrence-ranger-report")
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(summarize(args.corpus), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
