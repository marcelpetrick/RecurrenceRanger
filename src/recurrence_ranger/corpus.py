"""Derive an auditable prompt corpus from a fixed raw-record watermark."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from recurrence_ranger.normalize import PARSER_VERSION
from recurrence_ranger.store import utc_now

SCHEMA_VERSION = 1
GENERATED_PREFIXES = (
    "# AGENTS.md instructions",
    "This session is being continued from a previous conversation",
    "Base directory for this skill:",
    "- You are a conversation title generator",
    "-\nYou are a conversation title generator",
    "You are a conversation title generator",
    "<environment_context>",
    "<subagent_notification>",
    "<recommended_plugins>",
    "<turn_aborted>",
    "<task-notification>",
    "<local-command-",
    "<skill>",
    "<user_action>",
    "<user_shell_command>",
    "<bash-",
    "<codex_internal_context",
    "<command-name>",
    "[Request interrupted",
    "[SYSTEM NOTIFICATION - NOT USER INPUT]",
    "[Your previous response had no visible output.",
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_runs (
  id INTEGER PRIMARY KEY, source_path TEXT NOT NULL, watermark INTEGER NOT NULL,
  parser_version INTEGER NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prompts (
  id INTEGER PRIMARY KEY, profile TEXT NOT NULL, session TEXT NOT NULL,
  timestamp TEXT, project TEXT, text TEXT NOT NULL, primary_record_id INTEGER NOT NULL UNIQUE,
  authorship TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS occurrences (
  record_id INTEGER PRIMARY KEY, profile TEXT NOT NULL, session TEXT NOT NULL,
  origin TEXT NOT NULL, decision TEXT NOT NULL, reason TEXT NOT NULL,
  prompt_id INTEGER REFERENCES prompts(id)
);
CREATE INDEX IF NOT EXISTS idx_occurrences_prompt ON occurrences(prompt_id);
CREATE INDEX IF NOT EXISTS idx_prompts_profile ON prompts(profile);
"""


@dataclass(frozen=True)
class Candidate:
    record_id: int
    profile: str
    tool: str
    session: str
    kind: str
    timestamp: str | None
    project: str | None
    text: str | None


def _seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        if value.isdigit():
            number = int(value)
            return number / 1000 if number > 10**12 else float(number)
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return None


def _decision(candidate: Candidate, raw: bytes) -> tuple[str, str]:
    text = candidate.text
    if candidate.tool == "claude" and candidate.kind == "user":
        try:
            record = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            return "uncertain", "raw record cannot be parsed"
        if record.get("toolUseResult") is not None:
            return "excluded", "tool result"
        if record.get("promptSource") in {"system", "sdk"}:
            return "excluded", "generated system or SDK prompt"
        if record.get("isCompactSummary") or record.get("isVisibleInTranscriptOnly"):
            return "excluded", "generated compaction summary"
        if record.get("isMeta"):
            return "excluded", "generated metadata"
        if record.get("isSidechain"):
            return "excluded", "subagent sidechain"
        content = (record.get("message") or {}).get("content")
        if isinstance(content, list) and any(
            not isinstance(block, dict) or block.get("type") != "text" for block in content
        ):
            return "uncertain", "mixed or nontext content"
    if not text or not text.strip():
        return "uncertain", "no text; inspect raw content or attachment"
    stripped = text.lstrip()
    if stripped.startswith(GENERATED_PREFIXES):
        return "excluded", "generated context or notification"
    if stripped.startswith(("<command-message>", "<image", "[Image:")):
        return "uncertain", "command expansion or attachment"
    return "human", "prompt-oriented source record"


def derive(source_path: Path, output_path: Path, watermark: int | None = None) -> dict:
    """Replace a private derived database; the source is opened read-only."""
    source_path = source_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    if source_path == output_path:
        raise ValueError("source and output paths must differ")
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    try:
        if watermark is None:
            watermark = source.execute("SELECT COALESCE(MAX(id),0) FROM raw_records").fetchone()[0]
        if watermark < 0:
            raise ValueError("watermark must be nonnegative")
        output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output = sqlite3.connect(output_path)
        try:
            output_path.chmod(0o600)
            output.execute("PRAGMA foreign_keys=ON")
            output.executescript(SCHEMA)
            with output:
                # Derived labels are tied to prompt IDs and this exact watermark.
                output.execute("DROP TABLE IF EXISTS guideline_occurrences")
                output.execute("DROP TABLE IF EXISTS extraction_reviews")
                output.execute("DROP TABLE IF EXISTS recall_candidates")
                output.execute("DROP TABLE IF EXISTS relevance")
                output.execute("DELETE FROM occurrences")
                output.execute("DELETE FROM prompts")
                output.execute("DELETE FROM corpus_runs")
                output.execute(
                    "INSERT INTO corpus_runs(source_path,watermark,parser_version,created_at) "
                    "VALUES (?,?,?,?)",
                    (str(source_path), watermark, PARSER_VERSION, utc_now()),
                )
                rows = source.execute(
                    """SELECT r.id,s.label,s.tool,x.source_session_id,m.kind,m.timestamp,
                              COALESCE(m.project,x.project),m.text,r.data
                       FROM messages m JOIN raw_records r ON r.id=m.record_id
                       JOIN sessions x ON x.id=m.session_id
                       JOIN sources s ON s.id=x.source_id
                       WHERE m.role='user' AND r.id<=?""",
                    (watermark,),
                )
                candidates = []
                decisions = {}
                for row in rows:
                    candidate = Candidate(*row[:-1])
                    candidates.append(candidate)
                    decisions[candidate.record_id] = _decision(candidate, row[-1])
                priority = {"user": 0, "message": 0, "user_message": 1, "history": 2}
                candidates.sort(key=lambda c: (priority.get(c.kind, 3), c.record_id))
                existing: dict[tuple[str, str, str], list[tuple[int, str, float | None]]] = {}
                for candidate in candidates:
                    decision, reason = decisions[candidate.record_id]
                    prompt_id = None
                    if decision != "excluded" and candidate.text:
                        key = (candidate.profile, candidate.session, candidate.text)
                        when = _seconds(candidate.timestamp)
                        for previous_id, previous_kind, previous_when in existing.get(key, []):
                            if (
                                candidate.kind != previous_kind
                                and when is not None
                                and previous_when is not None
                                and abs(when - previous_when) <= 60
                            ):
                                prompt_id = previous_id
                                reason = f"same prompt as {previous_kind} within 60 seconds"
                                decision = "duplicate"
                                break
                        if prompt_id is None:
                            prompt_id = output.execute(
                                """INSERT INTO prompts(profile,session,timestamp,project,text,
                                                       primary_record_id,authorship)
                                   VALUES (?,?,?,?,?,?,?)""",
                                (
                                    candidate.profile,
                                    candidate.session,
                                    candidate.timestamp,
                                    candidate.project,
                                    candidate.text,
                                    candidate.record_id,
                                    decision,
                                ),
                            ).lastrowid
                            existing.setdefault(key, []).append((prompt_id, candidate.kind, when))
                    output.execute(
                        "INSERT INTO occurrences VALUES (?,?,?,?,?,?,?)",
                        (
                            candidate.record_id,
                            candidate.profile,
                            candidate.session,
                            candidate.kind,
                            decision,
                            reason,
                            prompt_id,
                        ),
                    )
            return {
                "watermark": watermark,
                "parser_version": PARSER_VERSION,
                "occurrences": output.execute(
                    "SELECT decision,COUNT(*) FROM occurrences GROUP BY decision ORDER BY decision"
                ).fetchall(),
                "prompts": output.execute(
                    "SELECT authorship,COUNT(*) FROM prompts "
                    "GROUP BY authorship ORDER BY authorship"
                ).fetchall(),
            }
        finally:
            output.close()
    finally:
        source.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="recurrence-ranger-corpus")
    parser.add_argument("source", type=Path, help="captured SQLite database or fixed backup")
    parser.add_argument("output", type=Path, help="private derived SQLite database")
    parser.add_argument("--watermark", type=int)
    args = parser.parse_args(argv)
    print(json.dumps(derive(args.source, args.output, args.watermark), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
