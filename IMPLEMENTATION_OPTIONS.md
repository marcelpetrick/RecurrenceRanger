# Two implementation plans for local conversation capture

Date: 2026-09-21

Status: proposals only. No collector has been implemented or started. Marcel will
provide the next direction after reviewing these documents.

## Shared objective

Backfill retained Claude, Claude DMO, Codex, and Codex DMO conversation history
into a private local SQLite database, then continuously capture new records.
Preserve all in-scope conversation records before filtering for software prompts
or guidelines. Follow [PLAN.md](PLAN.md) for scope and completion criteria.

Both options use a separate capture tool in a location to be decided before
implementation. Study and adapt the discovery approach in `tokenUsage2`; do not
change its usage-accounting application as part of this milestone. Inspect its
license before copying code. Its token parsers cannot supply the requested corpus.

## Shared database design

The following is a proposed model, to validate against actual local schemas:

| Entity | Purpose |
| --- | --- |
| Sources and aliases | Tool/profile, canonical location, discovered spellings, availability |
| Files and generations | File identity, replacement/truncation history, size and scan metadata |
| Raw records | Original record bytes, source generation, offset/line, digest, ingestion time, parse status |
| Sessions | Original session IDs, tool namespace, project, timestamps, parent/fork links when known |
| Messages and blocks | Source role/type, original text or structured content, message IDs and ordering |
| Provenance links | Connect normalized records to every original occurrence |
| Checkpoints | Last durably captured complete record for each file generation |
| Pending fragments | Observed incomplete bytes and offsets, reconciled as writes complete |
| Ingestion errors/runs | Failures, unsupported schemas, counters, parser version, backfill/live progress |

Store malformed complete records too, with their parse errors. A raw-record digest
helps compare copies but must not collapse identical text typed in separate turns.
Distinguish physical ingestion identity from logical message identity. Keep raw
data available for reparsing after schema or classification changes.

Preserve unknown record types before normalization and account for pending tails
separately from complete messages. Persist observed tail bytes without advancing
the complete-record checkpoint; reconcile them on append or mark them incomplete
if the file disappears or changes generation. Use an ingestion watermark and
parser version to define repeatable later analysis inputs.

Use a single database writer, transactions that include checkpoints, schema
migrations, and an explicit concurrency strategy for later readers. Evaluate
SQLite WAL mode during implementation. Provide a consistent database backup
procedure and verify restore; copying an active database file alone is not the
backup design. Exclude the database, sidecars, backups, and private exports from Git.

On disk-full, lock, or permission errors, report the failure and backlog, preserve
the last committed checkpoint, and retry where recoverable. Bound batches and
memory use so large records and historical files do not stall all other sources.

## Option A: periodic incremental collector

Run one long-lived process that repeatedly discovers sources and reads new bytes
from known files, separating complete records from pending tails. Use a configurable polling interval, initially
targeting roughly 5–15 seconds, then tune against measured corpus size and load.
This is a proposed target, not a measured capture guarantee.

### Work packages

1. Inventory homes and inspect schemas; create sanitized representative fixtures.
2. Implement the database, raw ingestion, source manifest, and one-shot backfill.
3. Add resumable offsets, file-generation tracking, and independent normalization
   adapters for the observed Claude/Codex formats.
4. Add a continuous polling loop, periodic source rediscovery, status reporting,
   orderly shutdown, and explicit error handling. Interleave historical batches
   and active-file reads from startup; do not require backfill to finish first.
5. Exercise interrupted writes, restarts, source changes, duplicates, and querying
   while collecting. Measure backfill time, steady-state disk activity, and lag.
6. Document manual operation, backup/restore, and an optional user-service setup.
   Register/start a persistent service only as part of the chosen implementation.

Commit each completed package locally after its relevant checks pass.

### Tradeoffs

This has fewer moving parts and offers the shortest route to a populated,
continuously updated database. Capture latency depends on the polling interval.
Repeated directory scans can become costly with many files; use file metadata
and a separate, slower full-discovery schedule, then measure the result.

## Option B: filesystem watcher plus reconciliation

Use filesystem notifications to schedule ingestion of changed files. Retain
periodic full reconciliation because notifications alone are not a durable record
of every change. The database and parsers are the same as in Option A.

### Work packages

1. Inventory sources and build the same transactional database, parser fixtures,
   and resumable one-shot backfill as Option A.
2. Establish watches and buffer change notifications while backfill runs; reconcile
   afterward to catch retained changes during startup. Process active-file reads
   between bounded historical batches rather than deferring them until backfill
   ends. Queue overflow must schedule reconciliation and produce visible status.
3. Add a bounded, coalescing queue that sends changed paths to one database writer.
   Retry incomplete trailing records after later writes.
4. Handle new directories, moves, replacement, watcher overflow, source outages,
   and restarts. Run periodic rediscovery and reconciliation regardless of events.
5. Test startup races, missed notifications, event bursts, queue pressure, and all
   shared ingestion cases. Measure latency and resource use against polling.
6. Document operations, backup/restore, and an optional user-service setup.

Commit each completed package locally after its relevant checks pass.

### Tradeoffs

This can reduce idle scanning and capture changes sooner, but adds watcher and
queue failure modes. It still needs the incremental reconciliation engine, so
there is more implementation and validation work before reliable operation.

## Comparison and recommendation

| Criterion | Option A: polling | Option B: watcher + reconciliation |
| --- | --- | --- |
| Historical backfill | Full retained corpus | Full retained corpus |
| New-data capture | At configured polling intervals | On events, with polling recovery |
| Recovery mechanism | Checkpoints and rescans | Checkpoints, event handling, and rescans |
| Initial complexity | Lower | Higher |
| Idle work | Repeated metadata checks | Watch handling plus less frequent reconciliation |
| Database reuse for analysis | Same model | Same model |

Recommend **Option A first**, keeping ingestion independent from scheduling so a
watcher can be added later if measured latency or scan costs justify it. SQLite
is the proposed first storage choice for this local capture and later-query task;
validate disk growth and reader/writer behavior on the actual corpus.

## Shared verification gate

- Reconcile source inventory, ingested raw records, normalization outcomes, and
  errors; provide per-profile coverage and capture lag.
- Rescan unchanged data and restart after a simulated crash without losing or
  duplicating physically ingested complete records.
- Append records in fragments, rotate/truncate/replace files, remove and restore
  a source, and confirm explicit recoverable behavior.
- Preserve unknown schemas and abandoned partial tails. Simulate disk-full,
  locked-database, and permission failures and verify checkpoint safety.
- Run live appends during a substantial backfill and verify neither workload
  starves; report measured collection lag separately from source discovery lag.
- Keep copied histories linked while preserving identical prompts from genuinely
  separate turns. Preserve injected context without calling it human authorship.
- Query sessions, original records, and candidate user inputs during capture.
- Verify a consistent backup can be restored and queried.

Both options depend on source retention: a file deleted before collection, or
changes wholly inside an outage, may be unrecoverable. Reconciliation can recover
retained data, not reconstruct missing bytes. Report detected gaps and these
limits in the capture status and inventory.

## Decisions and later work

Marcel's next input will determine the chosen option, implementation location,
database location, and whether persistent service installation belongs in the
first implementation pass. Source inventory will establish actual formats and
retained history. Attachment copying and any non-conversation data remain
separate scope decisions.

After capture works, plan relevance classification, atomic guideline extraction,
recurrence analysis, and reusable agent instructions using the retained database.
No semantic-analysis implementation is part of the current planning task.
