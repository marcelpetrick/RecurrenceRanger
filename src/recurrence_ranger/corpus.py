"""Derive an auditable prompt corpus from a fixed raw-record watermark."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import cast

from recurrence_ranger import derived
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
    session_origin: str | None = None


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


def _decision(candidate: Candidate, raw: bytes | None) -> tuple[str, str]:
    text = candidate.text
    if candidate.session_origin == "subagent":
        return "excluded", "Codex subagent task"
    if candidate.session_origin == "exec":
        return "excluded", "automated Codex exec session"
    if candidate.tool == "claude" and candidate.kind == "user":
        # Only these records carry the flags that decide authorship, so the derivation
        # reads the stored bytes for them alone.
        try:
            record = json.loads(raw or b"")
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


def _previous_decisions(output: sqlite3.Connection) -> dict[tuple[str, str, str], dict]:
    """Read the model decisions of an earlier derivation, keyed by what identifies a prompt.

    Prompt ids belong to one derivation, so decisions are carried by profile, session and
    exact prompt text instead. Nothing is carried for a prompt whose text changed.
    """
    tables = {row[0] for row in output.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "prompts" not in tables or "relevance" not in tables:
        return {}
    carried: dict[tuple[str, str, str], dict] = {}
    for profile, session, prompt_text, *decision in output.execute(
        """SELECT p.profile,p.session,p.text,r.label,r.model,r.prompt_version,r.classified_at,
                  r.truncated,r.note
           FROM prompts p JOIN relevance r ON r.prompt_id=p.id"""
    ):
        carried[(profile, session, prompt_text)] = {"relevance": tuple(decision)}
    if "extraction_reviews" not in tables:
        return carried
    for profile, session, prompt_text, *review in output.execute(
        """SELECT p.profile,p.session,p.text,x.model,x.extractor_version,x.reviewed_at,x.note
           FROM prompts p JOIN extraction_reviews x ON x.prompt_id=p.id"""
    ):
        entry = carried.setdefault((profile, session, prompt_text), {})
        entry["review"] = tuple(review)
    if "guideline_occurrences" not in tables:
        return carried
    for profile, session, prompt_text, theme in output.execute(
        """SELECT p.profile,p.session,p.text,g.theme
           FROM prompts p JOIN guideline_occurrences g ON g.prompt_id=p.id"""
    ):
        entry = carried.setdefault((profile, session, prompt_text), {})
        entry.setdefault("themes", []).append(theme)
    return carried


def _carry(output: sqlite3.Connection, decisions: dict[tuple[str, str, str], dict]) -> int:
    """Re-attach carried decisions to the prompts of the new derivation."""
    if not decisions:
        return 0
    derived.create(output, *derived.MODEL_TABLES)
    carried = 0
    for prompt_id, profile, session, prompt_text in output.execute(
        "SELECT id,profile,session,text FROM prompts"
    ).fetchall():
        entry = decisions.get((profile, session, prompt_text))
        if not entry or "relevance" not in entry:
            continue
        output.execute(
            "INSERT INTO relevance VALUES (?,?,?,?,?,?,?)", (prompt_id, *entry["relevance"])
        )
        carried += 1
        if "review" in entry:
            output.execute(
                "INSERT INTO extraction_reviews VALUES (?,?,?,?,?)", (prompt_id, *entry["review"])
            )
            output.executemany(
                "INSERT INTO guideline_occurrences VALUES (?,?)",
                [(prompt_id, theme) for theme in entry.get("themes", ())],
            )
    return carried


def derive(
    source_path: Path,
    output_path: Path,
    watermark: int | None = None,
    *,
    carry_labels: bool = False,
) -> dict:
    """Replace a private derived database; the source is opened read-only.

    With carry_labels the model decisions of an earlier derivation are re-attached to
    prompts whose profile, session and text are unchanged, so a new watermark does not
    cost another full model run.
    """
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
        session_origins = {}
        headers = source.execute(
            """SELECT s.label,r.data FROM raw_records r
               JOIN generations g ON g.id=r.generation_id
               JOIN files f ON f.id=g.file_id JOIN sources s ON s.id=f.source_id
               WHERE s.tool='codex' AND r.start_offset=0 AND r.id<=?""",
            (watermark,),
        )
        for profile, raw in headers:
            try:
                record = json.loads(raw)
            except (UnicodeError, json.JSONDecodeError):
                continue
            if record.get("type") != "session_meta":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict) or not payload.get("id"):
                continue
            origin = payload.get("source")
            if isinstance(origin, dict) and "subagent" in origin:
                session_origins[(profile, str(payload["id"]))] = "subagent"
            elif origin == "exec":
                session_origins[(profile, str(payload["id"]))] = "exec"
        output_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        output = sqlite3.connect(output_path)
        try:
            output_path.chmod(0o600)
            output.execute("PRAGMA foreign_keys=ON")
            previous = _previous_decisions(output) if carry_labels else {}
            output.executescript(SCHEMA)
            with output:
                # sqlite3 opens its implicit transaction only at the first DELETE, so the
                # drops below would commit on their own and a later failure would lose the
                # model work. Begin explicitly so the whole replacement is one transaction.
                output.execute("BEGIN")
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
                              COALESCE(m.project,x.project),m.text,
                              CASE WHEN s.tool='claude' AND m.kind='user' THEN r.data END
                       FROM messages m JOIN raw_records r ON r.id=m.record_id
                       JOIN sessions x ON x.id=m.session_id
                       JOIN sources s ON s.id=x.source_id
                       WHERE m.role='user' AND r.id<=?""",
                    (watermark,),
                )
                candidates = []
                decisions = {}
                for record_id, profile, tool, session, kind, stamp, project, text, raw in rows:
                    candidate = Candidate(
                        record_id,
                        profile,
                        tool,
                        session,
                        kind,
                        stamp,
                        project,
                        text,
                        session_origins.get((profile, session)),
                    )
                    candidates.append(candidate)
                    decisions[record_id] = _decision(candidate, raw)
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
                            inserted = output.execute(
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
                            )
                            prompt_id = cast(int, inserted.lastrowid)
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
                carried = _carry(output, previous)
            return {
                "watermark": watermark,
                "parser_version": PARSER_VERSION,
                "carried_decisions": carried,
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
    parser.add_argument(
        "--carry-labels",
        action="store_true",
        help="keep model decisions for prompts whose profile, session and text are unchanged",
    )
    args = parser.parse_args(argv)
    print(
        json.dumps(
            derive(args.source, args.output, args.watermark, carry_labels=args.carry_labels),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
