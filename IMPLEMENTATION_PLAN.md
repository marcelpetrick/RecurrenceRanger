# Option A implementation handoff: local conversation capture

Date: 2026-09-21

Decision: implement the periodic incremental collector described in
[IMPLEMENTATION_OPTIONS.md](IMPLEMENTATION_OPTIONS.md).

Status: planning only; no corpus inventory, collector, database, or service has
been created.

## Goal and boundary

Build a separate local tool that captures all discoverable conversation records
from Marcel's Claude, Claude DMO, Codex, and Codex DMO profiles into a private,
queryable SQLite database. Backfill retained history and collect new records
continuously, including while backfill is running. Preserve original record
bytes, source provenance, and enough normalized structure for later analysis.
Guideline extraction, semantic classification, attachment copying, and changes
to `tokenUsage2` are outside this milestone. Follow the scope and completion
criteria in [PLAN.md](PLAN.md).

This document is the handoff for a later implementation tool. Treat values
marked *initial* as defaults to measure, not guarantees. Do not claim records
deleted before observation can be recovered.

## Decisions for the implementation

- Create a separate project for the collector. Keep its code, fixtures, and
  documentation in version control; keep the database, WAL/SHM files, backups,
  raw exports, and real transcript samples out of Git. Pick its repository and
  private data directory before writing real records, and verify permissions.
- Start with one process and one SQLite writer. Offer a one-shot catch-up mode
  and a long-running polling mode that share the same ingestion engine. Do not
  build a watcher in this milestone.
- Use `tokenUsage2` only as a discovery reference. Its `discover.py` considers
  config, environment, shell launchers, process environment, defaults, and home
  scans; `ingest.py` enumerates Claude `projects/**/*.jsonl` and Codex
  `sessions/` plus `archived_sessions/` rollout JSONL. Its usage parsers do not
  preserve the requested conversation corpus. Check its GPL-3.0-or-later
  license before copying code; an independent implementation can use the
  observed discovery behavior as a specification.
- Use raw records as the durable source of truth. Normalization may be revised
  or rerun from the database without rereading original logs. Preserve records
  of unknown type and malformed complete records with parse status and errors.
- Treat names such as “DMO” as labels to verify against actual homes and
  launchers. A directory name or account label alone is insufficient proof of
  which profile produced a record.

## Architecture and data contract

The collector has five modules: source discovery, bounded file scheduler,
byte-level JSONL capture, transactional SQLite store, and optional
normalization adapters. Status and backup commands read through the same
database contract. The polling loop periodically rediscovers homes and files,
checks known file metadata more frequently, and schedules bounded reads. An
initial 5–15 second active-file poll is a tuning target; full rediscovery can
run less often after measurement. No part of the system relies on a filesystem
notification.

Design the schema after inspecting real samples, with these minimum entities:

| Entity | Required content |
| --- | --- |
| `sources`, `source_aliases` | Tool/profile, stable source ID, canonical home, observed path spellings, discovery origin, availability and last seen time. |
| `files`, `file_generations` | Source, path, physical identity where available, generation, size/times, scan state and replacement/truncation reason. |
| `raw_records` | Generation, start/end byte offsets, original bytes including line ending, digest, capture time, parse status and error. |
| `pending_fragments` | Observed incomplete bytes and origin offset, last observation, resolution or abandoned reason. |
| `sessions`, `messages`, `content_blocks` | Original IDs and roles/types, ordering, timestamps, text/structured content, project and parent/fork references where available. |
| `provenance` | Links from normalized objects to every original occurrence; no loss of copied-location evidence. |
| `checkpoints`, `ingestion_runs`, `errors` | Last durably captured complete offset per generation, parser/schema versions, backfill/live progress and actionable failures. |

Use a uniqueness constraint on physical capture location, for example
`(file_generation_id, start_offset, end_offset)`. A content hash helps compare
copies but must never be the sole identity: two separate turns can contain
identical text. Keep source-assigned message IDs in their tool namespace, not
as globally unique IDs. Record the raw-to-normalized mapping so reparsing can
replace derived rows without multiplying messages. The source record's
transport role is data; later human-authorship classification must distinguish
actual prompts from tool returns, injected context, replay and subagent tasks.

Each transaction inserts complete raw records and advances the associated
checkpoint together. If normalization fails, retain the raw record and mark it
for reprocessing. If the database write fails, roll back both data and
checkpoint, expose the backlog, and retry recoverable failures. Persist an
observed trailing fragment separately; it never advances the complete-record
checkpoint. On later append, reconcile it against the source bytes. If the file
vanishes or changes generation, retain it with an incomplete status.

Use SQLite schema migrations and a single-writer lock or equivalent ownership
rule. Evaluate WAL mode with concurrent reader queries on the actual filesystem;
set a finite busy timeout and report persistent lock failures. Provide a
database version and parser version. A later analysis run must select a stable
ingestion watermark and parser version, rather than querying a moving corpus.

## Capture algorithm

1. Discover candidate homes from explicit configuration, current environment,
   shell launchers, running process hints when readable, defaults, and bounded
   home scans. Record every candidate as found, missing, or inaccessible.
   Resolve symlinks/aliases without erasing their observed spellings. Inventory
   only in-scope conversation files; check history indexes and archives for
   useful records rather than assuming every index holds full text.
2. Prioritize active files at startup. Build a queue of historical files, then
   alternate bounded historical work with fresh active-file checks and
   rediscovery. Limit work by bytes and elapsed time per turn, not just file
   count, so one huge rollout cannot monopolize the loop. Maintain separate
   live and historical progress counters.
3. For each file, open it and obtain identity plus a size snapshot. Compare
   with the stored generation and complete-record checkpoint. Read from that
   checkpoint to the snapshot bound, emitting only newline-terminated records.
   Preserve bytes exactly and decode only for parsing. A trailing segment is
   pending. Recheck identity/size before declaring the scan current; if it
   changed during reading, schedule another pass.
4. Treat path replacement, truncation, and evidence of in-place rewrite as a
   new generation; never overwrite previously captured raw records. Record the
   reason and any coverage uncertainty. `tokenUsage2` samples a consumed prefix
   to detect some rewrites, but sampling is not a proof that every in-place edit
   was seen. Choose and document a bounded revalidation policy after measuring
   cost; flag edits that cannot be proved complete.
5. Commit in small batches with the source generation, record locations,
   pending state, and checkpoints consistent. Restart from the last committed
   checkpoint after a crash. Rereading a batch must be idempotent through
   location uniqueness; a reused inode alone must not merge distinct file
   generations.
6. Normalize stored raw records using Claude and Codex adapters based on
   observed schemas. Preserve unknown event types and content blocks. Keep
   normalization separate enough to rerun it from SQLite after a parser fix.

Define how the implementation handles a single very large record before
ingesting real history: stream or spool it with bounded memory, or report a
specific size failure while leaving the checkpoint recoverable. Never silently
skip bytes or truncate content. Avoid symlink loops and repeatedly scanning the
collector's own database directory.

## Work packages and commit gates

Each package ends with a focused local commit and a short progress note. Keep
the collector uninstalled until its continuous-mode gate passes.

| Package | Deliverable | Gate before commit |
| --- | --- | --- |
| 0. Inventory and decisions | `SOURCE_INVENTORY.md`, machine-readable manifest, source samples redacted into synthetic fixtures; chosen code/data paths and runtime. | All four requested profiles have found/missing/inaccessible status; counts, sizes, date ranges, archives, aliases and observed schemas are recorded without committing private content. |
| 1. Project and database | CLI skeleton, migration, private data path, Git ignores, SQLite ownership and backup design. | Fresh and upgraded databases open; two simultaneous writers cannot corrupt state; private files remain untracked. |
| 2. Raw capture and catch-up | Byte-preserving JSONL reader, generations, pending tails, checkpoints, errors, one-shot command. | Fixture backfill, malformed/unknown records, interrupted transaction, restart, identical content in distinct turns, and copied paths behave as specified. |
| 3. Continuous polling | Rediscovery, fair live/history scheduler, resumable long-running command, signals and status. | Append during substantial backfill; neither queue starves; observed lag and discovery lag are separately reported. |
| 4. Normalization and queries | Schema-specific adapters, sessions/messages/blocks/provenance, parser version and reparse path. | Representative Claude/Codex fixtures query correctly; parser failure leaves raw data available; no false human-authorship assertion. |
| 5. Operations and final verification | Status/coverage, backup/restore, runbook, optional user service after approval of install location. | Full test matrix below passes; restore is queryable; measured disk use and lag are documented. |

Suggested CLI surface, to settle during package 0: `inventory`, `backfill`,
`run`, `status`, `verify`, `backup`, and `restore-check`. Configuration needs
explicit include/exclude homes, profile labels, database path, poll intervals,
batch budgets, and log verbosity. Default diagnostics must show paths and
counters without printing prompt text or secrets. A status command should be
usable even when the collector is stopped.

## Common blockers and response

| Blocker | Planned response |
| --- | --- |
| A DMO profile is absent, relocated, or hidden behind a launcher. | Inspect configuration, launcher assignments and current process hints; allow explicit homes; report unresolved profile coverage rather than relabeling a different home. |
| A discovered home contains no full transcripts, only history indexes or token totals. | Record the limitation and inspect other retained/archive sources; do not infer missing message text. |
| Claude/Codex records vary by version, role, or content shape. | Inventory representative schemas first; store every complete raw line, version adapters, and mark unsupported normalization explicitly. |
| Logs are appended while backfill runs, or old files disappear under retention. | Capture active files from startup, interleave bounded work, track lag and detected gaps; acknowledge bytes deleted before observation cannot be recovered. |
| Same path is rotated, truncated, or rewritten; aliases point to the same home. | Track file generations and aliases separately, preserve old occurrences, rescan on identity/checkpoint mismatch, and show uncertainty for undetectable rewrites. |
| Partial writes or abandoned tails. | Store pending bytes with offset, retry on append, and retain abandoned fragments without counting them as complete messages. |
| Disk space, permissions, SQLite locks, or process crash interrupt capture. | Roll back affected transaction, keep last durable checkpoint, retry where recoverable, and expose failure plus pending backlog; provide a clean stop. |
| SQLite grows too large or active readers block writes. | Measure corpus and growth early; batch inserts, index only required queries, test WAL and reader behavior, and use an online backup operation. |
| A copied log creates duplicate prompts, while repeated real prompts matter. | Keep physical occurrences and provenance; reconcile logical messages using source IDs/context, never content hash alone. |
| Real fixtures contain private text or credentials. | Create synthetic/sanitized fixtures, restrict local data permissions, and inspect `git diff --cached` before each commit. |
| Reusing `tokenUsage2` implementation introduces license or coupling issues. | Check GPL-3.0-or-later compatibility before code copying; otherwise implement discovery independently and test the same cases. |

## Verification matrix and exit criteria

Use small synthetic fixtures for deterministic behavior, then a private local
acceptance run over the actual retained corpus. Tests should assert outcomes,
not restate implementation internals.

- **Completeness:** Compare discovered files and byte ranges with captured
  records, pending fragments, explicit errors, and unsupported formats. Report
  counts and date coverage per profile. No software-keyword filter is allowed.
- **Durability:** Kill between read and commit, restart, and rescan; no committed
  complete record disappears or gains a second physical row. Failed writes do
  not advance checkpoints.
- **Changing sources:** Append a record in fragments; replace, truncate and
  remove/reintroduce files; test symlink aliases, copied files and same-text
  separate turns. State any change pattern the chosen detection cannot prove.
- **Fairness and latency:** Append during a large backfill and measure active
  capture delay, discovery delay, historical throughput and resource use.
  Adjust polling and batch budgets from these measurements; publish the
  observed target and any outliers.
- **Queries:** While polling, read sessions, raw records, messages, provenance,
  parse failures and per-source status. Verify parser changes can reprocess raw
  records without source logs.
- **Recovery:** Simulate disk-full, permission and locked-database failures;
  test checkpoint safety and visible backlog. Back up the live database with a
  consistent SQLite backup mechanism, restore to a separate path, run an
  integrity check and query it.

The milestone is done when all [PLAN.md](PLAN.md) capture criteria are met,
with actual results and limitations recorded, code and docs committed locally,
and the database private. Defer guideline analysis until this gate passes.

## First session for the next tool

1. Read `PLAN.md`, `IMPLEMENTATION_OPTIONS.md`, and this handoff; keep Option A
   and the capture-only scope.
2. Inspect the proposed repository and its instructions. Choose the separate
   collector location and private database path; record them before writing data.
3. Inventory the four profiles and real schemas without committing raw content.
   Produce package 0 outputs and synthetic fixtures, then commit that package.
4. Implement packages 1–5 in order, verifying and committing each. Report the
   commit IDs and acceptance results; do not push or start a persistent service
   without the relevant direction from Marcel.
