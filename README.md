# Recurrence Ranger

Recurrence Ranger keeps a private, reusable SQLite copy of local Claude and
Codex conversation records. It captures retained history and polls for new
records while backfill is still running. The database preserves original JSONL
bytes and exposes a best-effort message view for later guideline analysis.

The first milestone is **capture**. Message rows retain the source role and
are marked `unclassified` for human authorship; a transport `user` role alone
does not prove that Marcel typed the text. Semantic guideline extraction is
planned in [PLAN.md](PLAN.md).

## Sources and privacy

The checked-in [sources.json](sources.json) names the four requested profiles:
Claude, Claude DMO, Codex, and Codex DMO. Discovery also checks relevant
environment variables, shell launchers, default homes, and `~/.claude*` /
`~/.codex*` directories. Run `inventory` to inspect what is available on the
current machine. Claude `projects/**/*.jsonl`, Codex rollout files under
`sessions/` and `archived_sessions/`, and each profile's `history.jsonl` are
included. The latter is supplemental and may duplicate transcript prompts.

The default database is
`~/.local/share/recurrence-ranger/conversations.sqlite3` in a private directory.
Its contents, SQLite sidecars, backups, and exports must never be committed or
pushed. Diagnostic commands print paths, counts, and errors, not prompt text.
The raw data may still contain secrets; protect backups to the same standard.
Measured capture coverage and its limits are in
[CAPTURE_ACCEPTANCE.md](CAPTURE_ACCEPTANCE.md).

## Setup and first run

Requires Python 3.11 or newer. From this repository:

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/recurrence-ranger --manifest sources.json inventory
.venv/bin/recurrence-ranger --manifest sources.json backfill
.venv/bin/recurrence-ranger status
.venv/bin/recurrence-ranger verify
```

`backfill` resumes from durable checkpoints and repeatedly scans bounded
batches until no complete retained records remain. It reads active files
between older batches. `scan` performs one bounded cycle; `run` polls
continuously. For a manual continuous run:

```sh
.venv/bin/recurrence-ranger --manifest sources.json run --poll-seconds 10
```

`Ctrl+C` stops cleanly. The command uses one writer lock per database, so a
second collector cannot run against the same file. `status` shows source
availability, observed and captured bytes, raw record counts, pending
fragments, open errors, missing files, and an ingestion watermark. Use
`--db /private/path/name.sqlite3` before the subcommand to select another
database. `--max-files` and `--file-budget-mib` bound work per scan; the
10-second interval is an initial target to measure on this corpus.

For automatic startup, a sample systemd user unit is in
[deploy/recurrence-ranger.service](deploy/recurrence-ranger.service). Inspect
its paths, then link and start it:

```sh
systemctl --user link "$PWD/deploy/recurrence-ranger.service"
systemctl --user enable --now recurrence-ranger.service
systemctl --user status recurrence-ranger.service
```

To keep a user service running after logout, the host may need user lingering
enabled. Check the service status and collection lag after startup.

## Checks, backup, and restore

Run the same local gate used by CI:

```sh
./ci.sh
```

`verify` runs SQLite integrity checking and confirms that captured byte ranges
are contiguous up to each generation's committed checkpoint. For a consistent
backup while collection is active:

```sh
.venv/bin/recurrence-ranger backup ~/private-backups/conversations.sqlite3
.venv/bin/recurrence-ranger restore-check ~/private-backups/conversations.sqlite3
```

The backup command uses SQLite's online backup API. Do not copy only the live
database file while WAL mode is active. `restore-check` opens the backup
read-only, checks integrity, and confirms raw rows can be queried. To restore,
stop the service, copy the verified backup to a private new database path, then
use `--db` to query it before replacing the normal database.

## How capture works and what it cannot recover

Every complete JSONL line is stored with its source, file generation, byte
range, hash, parse status, and parser version. The record insert and checkpoint
move commit together. Incomplete tails remain pending until appended; a tail
left by a replaced or deleted file is recorded as abandoned. Unknown records
and malformed JSON are retained as raw bytes. Normalized sessions, messages,
and content blocks are query aids; raw rows remain authoritative.

The collector detects replacement and truncation, and samples the committed
prefix for common in-place rewrites. A rewrite that leaves file size, mtime,
and sampled bytes unchanged may escape detection. It cannot reconstruct a
record deleted before the collector observed it or data lost during an outage.
`SOURCE_INVENTORY.md` gives the initial observed coverage. Codex's
`thread_history_1.sqlite` is a derived projection whose rows are not yet
ingested separately; rollout JSONL is the primary Codex source. The final
capture report should name any missing profiles, failed files, and gaps.

## Development

Implementation details and work packages are in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). The code uses Python's
standard library at runtime. Test fixtures are synthetic; no real transcript
belongs in this repository. Commit implementation steps locally with
conventional messages. Do not push private data.
