"""Definitions of the tables the analysis stages add to a derived corpus.

Each stage creates the tables it writes, and the derivation needs the same definitions to
carry decisions across a re-derivation, so they are stated once here.
"""

from __future__ import annotations

import sqlite3

RELEVANCE = """CREATE TABLE IF NOT EXISTS relevance (
  prompt_id INTEGER PRIMARY KEY REFERENCES prompts(id),
  label TEXT NOT NULL, model TEXT NOT NULL,
  prompt_version INTEGER NOT NULL, classified_at TEXT NOT NULL,
  truncated INTEGER NOT NULL DEFAULT 0, note TEXT)"""

EXTRACTION_REVIEWS = """CREATE TABLE IF NOT EXISTS extraction_reviews (
  prompt_id INTEGER PRIMARY KEY REFERENCES prompts(id),
  model TEXT NOT NULL, extractor_version INTEGER NOT NULL,
  reviewed_at TEXT NOT NULL, note TEXT)"""

GUIDELINE_OCCURRENCES = """CREATE TABLE IF NOT EXISTS guideline_occurrences (
  prompt_id INTEGER NOT NULL REFERENCES prompts(id), theme TEXT NOT NULL,
  PRIMARY KEY(prompt_id,theme))"""

RECALL_CANDIDATES = """CREATE TABLE IF NOT EXISTS recall_candidates (
  prompt_id INTEGER PRIMARY KEY REFERENCES prompts(id),
  matched_term TEXT NOT NULL, rule_version INTEGER NOT NULL)"""

MODEL_TABLES = (RELEVANCE, EXTRACTION_REVIEWS, GUIDELINE_OCCURRENCES)

# Sessions spent building this analysis talk about the themes it measures, so every stage
# that queues, counts or audits prompts leaves them out, and all of them must agree.
OWN_PROJECTS = ("RecurrenceRanger", "20260921_MarcelsWishlistForSoftwareProjects")


def outside_own_projects(column: str) -> str:
    """Return the SQL condition that excludes prompts from this analysis's own projects."""
    return " AND ".join(f"COALESCE({column},'') NOT LIKE '%{name}%'" for name in OWN_PROJECTS)


def create(db: sqlite3.Connection, *statements: str) -> None:
    for statement in statements:
        db.execute(statement)
