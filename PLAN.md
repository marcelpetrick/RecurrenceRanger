# Extract Marcel's software-project guidelines from local AI history

Date: 2026-09-21

## Objective

Find the software-development guidelines Marcel repeatedly gives AI agents and
turn them into an evidence-backed, reusable set of project expectations. Inspect
all discoverable local user inputs from Claude, Claude DMO, Codex, and Codex DMO.
One prompt can express several independent guidelines; extract each separately.

The immediate work is documenting the plan and comparing two implementation
approaches, with a local commit for each step. Marcel will then provide input
on how to proceed. Do not start implementing or scanning the conversation corpus
during this planning stage.

The first implementation milestone is continuous capture into a reusable local
database, with SQLite as the proposed storage. Backfill all retained in-scope
history, then keep collecting new records as the tools run. Guideline extraction
and synthesis are later milestones to plan in detail after capture is established.

## Capture milestone and storage boundary

"All data" means the discoverable conversation/session records for the four
requested tool profiles, including the surrounding context needed for later
analysis, not only prompts matching today's software-related keywords. Preserve
raw records alongside normalized messages so future analyses do not depend on
today's filters. Inventory other source formats before deciding how to ingest
them; token totals alone cannot reconstruct lost conversations.

Proposed SQLite entities are sources/files, ingestion checkpoints, sessions,
raw records, normalized messages/content blocks, provenance links, and parse
errors. Preserve roles, original text, timestamps, project/profile metadata,
schema/parser versions, and relationships wherever the source supplies them.
User-authorship decisions can be revised later without discarding source data.
Embedded content remains in raw records; external attachment references are
recorded, with attachment copying a separate scope decision.

Continuous capture must support an initial backfill, incremental reads, safe
restart, partial writes, file replacement/truncation, and duplicate locations.
Commit records and their checkpoints together so crashes cannot silently skip
data. Preserve provenance even when logical duplicate messages are reconciled.
The database is a private local artifact, excluded from Git along with exports
and SQLite sidecar files. Keep capture independent from later AI analysis.

## Starting hypotheses, not findings

The examples in the request provide initial categories:

- CI, including GitHub Actions and a local CI entry point.
- A polished README with useful badges.
- Meaningful testing, coverage, and verifiable results.
- Project documentation and C4 architecture documentation.

Discover additional categories from the history. Do not limit extraction to these
keywords or count this planning conversation as historical evidence for them.

## Preliminary inspection of tokenUsage2

The local project at `/home/mpetrick/repos/tokenUsage2` provides a starting point:

- `src/tokenusage2/discover.py` discovers Claude/Codex homes using configuration,
  environment variables, shell launchers, running processes, default locations,
  and home-directory scans. It resolves aliases and symlinks for account identity.
- `src/tokenusage2/ingest.py`, particularly `files_for`, enumerates Claude
  `projects/**/*.jsonl` and Codex rollout files in both `sessions/` and
  `archived_sessions/`.
- `src/tokenusage2/parsers.py` extracts assistant usage records for Claude and
  token-count events plus context for Codex. These parsers do not extract the
  requested user-input corpus.

Reuse the discovery knowledge and relevant ingestion techniques. User-message
parsing and deduplication need their own rules; token-accounting identifiers and
filters are insufficient. Actual local log schemas and availability remain to
be inspected. No conversation corpus has been scanned during this planning step.

## Work sequence

### 1. Document the investigation plan

Write this file with scope, stages, evidence requirements, and completion criteria.
Commit this step locally.

### 2. Compare two implementation plans

Create `IMPLEMENTATION_OPTIONS.md` with two concrete alternatives for historical
and continuous SQLite capture, their work packages, tradeoffs, verification
strategy, and a recommendation. Commit it separately. Wait for Marcel's input
before implementation. Defer detailed analysis-system design.

### 3. Inventory sources and inspect schemas

- Find the actual homes for all four requested profiles, including custom
  locations and aliases. Report each profile as found, missing, or inaccessible.
- Inventory retained sessions, archives, history files, and relevant backups
  where present. Record file counts, sizes, date ranges where available, and
  duplicate locations. Treat history indexes as possible supplements, not as
  proof that full transcripts survive.
- Inspect representative records from each observed schema and identify genuine
  human inputs, message identifiers, timestamps, session IDs, and project paths.
- Distinguish human prompts from tool results, injected instructions, skill
  expansions, compaction summaries, replayed context, and subagent tasks, even
  when their transport role is `user`.
- Record a scan cutoff and file metadata so active logs and future reruns can be
  reconciled. State missing or deleted history explicitly.

Deliverable: `SOURCE_INVENTORY.md` and a machine-readable source manifest.

### 4. Build historical and continuous database capture

- Capture all in-scope conversation records before applying software-relevance
  filters. Store original records and normalized representations in SQLite.
- Backfill retained history, then continuously ingest new files and appended
  records. Provide one-shot catch-up and resumable continuous operation.
- Track file identity, generations, offsets, parser versions, and ingestion
  status. Handle rotation/replacement and report collection failures visibly.
- Verify restart behavior, transactional checkpoints, deduplication, and reading
  the database for later analysis while capture is active.

Deliverable: a populated reusable local database, working continuous collector,
capture status/coverage report, and operational instructions. This is the first
implementation milestone. Review its results with Marcel before planning the
analysis stages below in detail.

### 5. Later: derive a traceable user-input corpus from the database

- Read source logs without changing them. Stream large files and report malformed
  records and incomplete trailing lines rather than silently losing them.
- Preserve original text and provenance: tool/profile, file, line or byte offset,
  session, message ID when present, timestamp, and project.
- Reconcile duplicate representations of one message, copied homes, resumed or
  forked sessions, and history/transcript overlap. Keep genuinely repeated prompts
  in separate turns; repetition is the signal we want to measure.
- Keep uncertain authorship separate for review. Record attachment references
  and unavailable/nontext content without inventing what they contain.
- Store corpus and intermediate evidence locally; avoid committing raw private
  transcripts or secrets. Commit extraction code and sanitized documentation.

Deliverable: a normalized local corpus, exclusion/error ledger, and extraction
statistics with stable IDs linking all later results to source records.

### 6. Later: extract individual software guidelines

- Examine every extracted human input for software relevance, using nearby
  conversation context when a short follow-up depends on it. Do not make keyword
  matches the only inclusion gate.
- Handle typos, abbreviations, and any languages found in the corpus.
- Split each relevant prompt into atomic instructions while preserving qualifiers
  such as "for this project," "before committing," "when applicable," or "never."
- Separate reusable preferences from one-time feature requests, questions,
  examples, quoted material, and assistant suggestions that Marcel did not adopt.
- Preserve evidence excerpts and prompt IDs for every extracted instruction;
  record uncertain interpretations instead of turning them into hard rules.

Deliverable: structured guideline occurrences, each linked to its source prompt.

### 7. Later: consolidate recurring preferences

- Group semantically equivalent instructions without erasing useful distinctions
  such as hosted CI versus local CI, tests versus coverage, or README versus
  architecture documentation.
- Count distinct supporting prompts, sessions, and projects; report profile/date
  coverage. Count a guideline once per prompt even if phrased twice within it.
- Show broadly repeated preferences separately from project-specific or one-off
  requirements. Retain one-off guidelines in the evidence catalog.
- Surface exceptions, conflicting instructions, and changes over time. Do not
  silently choose a universal rule where the history is conditional.
- Distinguish explicit user requirements from inferred preferences, and explain
  confidence using evidence rather than unsupported numerical scores.

Deliverable: a ranked catalog with evidence, counts, scope, and conflicts.

### 8. Later: validate coverage and write the reusable guidance

- Test extraction against representative schemas, mixed content blocks,
  duplicates, injected context, malformed records, and multiple rules per prompt.
- Audit both included and excluded prompts across profiles, projects, dates, and
  schemas. Review uncertain cases and missed guidelines; refine and rerun.
- Reconcile discovered files, processed records, retained prompts, exclusions,
  and failures. Separate measured coverage from unavailable history and remaining
  uncertainty; do not claim perfect semantic recall.
- Produce `GUIDELINES.md` as a concise reusable set of agent instructions, and
  `EVIDENCE.md` as the supporting catalog with safe excerpts and source references.
- Document how to reproduce the extraction and update it with new sessions.

## Capture milestone completion criteria

- All four requested profiles have an explicit inventory result.
- All discovered in-scope retained records are stored, or failures and unsupported
  formats are explicitly accounted for, without a software-keyword filter.
- New records are collected continuously within a documented target delay.
- Restarting or rescanning neither loses complete records nor creates duplicate
  physical ingestion records; source aliases retain their provenance.
- Partial writes, truncation/replacement, malformed records, and unavailable
  sources have tested behavior and visible status.
- SQLite can be queried for sessions, user messages, and original records, with
  traceable source locations; backup and restore instructions are documented.
- Code, schema, checks, and documentation are committed locally; database contents
  and private exports remain outside version control.

## Eventual guideline-analysis completion criteria

- All four requested profiles have an explicit inventory result.
- Every discovered in-scope source is processed or has a recorded reason it was
  not processed; all extracted human prompts receive a relevance decision.
- Multi-guideline prompts produce multiple independently traceable occurrences.
- Duplicate log copies do not inflate recurrence, while genuine repetition does.
- Every final guideline has evidence, scope, and an explicit confidence rationale.
- The report includes new themes beyond the seed categories where the data
  supports them, along with contradictions and coverage limitations.
- Each completed work step has a separate local commit; nothing is pushed.

## Local commit practice

Review each step's diff and run checks appropriate to its contents before
committing. Stage only that step's files. Keep source logs unchanged and private
corpus artifacts untracked/ignored. Record the local commit for each completed
step in the progress report to Marcel.
