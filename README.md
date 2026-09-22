# Recurrence Ranger

[![Local Pipeline](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/local-pipeline.yml/badge.svg?branch=master)](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/local-pipeline.yml)
[![Quality](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/quality.yml/badge.svg?branch=master)](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/quality.yml)
[![Manual Release](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/manual-release.yml/badge.svg)](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/manual-release.yml)
[![Dependency Drift](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/dependency-drift.yml/badge.svg)](https://github.com/marcelpetrick/RecurrenceRanger/actions/workflows/dependency-drift.yml)
[![Latest Release](https://img.shields.io/github/v/release/marcelpetrick/RecurrenceRanger?sort=semver)](https://github.com/marcelpetrick/RecurrenceRanger/releases/latest)
[![License: GPL v3 or later](https://img.shields.io/badge/license-GPLv3%20or%20later-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776ab.svg)](https://www.python.org/)
[![Coverage: 100%](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](localpipeline.sh)
[![Checked with mypy](https://img.shields.io/badge/mypy-checked-2a6db2.svg)](https://mypy-lang.org/)
[![Linted with ruff](https://img.shields.io/badge/ruff-linted-d7ff64.svg)](https://docs.astral.sh/ruff/)

Recurrence Ranger keeps a private, reusable SQLite copy of local Claude and
Codex conversation records, derives an auditable corpus of the prompts a human
actually typed, and turns that corpus into an evidence-backed set of recurring
software-project guidelines. Capture preserves the original JSONL bytes; every
later stage is reproducible from a recorded watermark.

**Author: Marcel Petrick <mail@marcelpetrick.it>**

**License: GPLv3 or later. See [`LICENSE`](LICENSE).**

**Note: project is generated with AI.**

All stages are implemented and have been run over the real local history:
385,404 captured records, 7,882 likely human prompts, every prompt classified
and every instruction prompt reviewed for the expectations it states. The
results are in [docs/](docs/); the plan and its history are in
[PLAN.md](docs/project/PLAN.md).

Authorship stays explicit rather than assumed: captured message rows keep the
source role and are marked `unclassified`, because a transport `user` role alone
does not prove that a human typed the text. The derivation decides authorship
from record flags and content, and keeps 126 prompts as uncertain.

## Results at a glance

The summary page [docs/agentic-view.html](docs/agentic-view.html) presents the
findings, the ranked themes and ten antitheses. GitHub shows it as source; open
the file in a browser or through
[htmlpreview](https://htmlpreview.github.io/?https://github.com/marcelpetrick/RecurrenceRanger/blob/master/docs/agentic-view.html).

[![Key findings: 58% of prompts change software, "get all done" is the most repeated instruction](docs/images/key-findings.png)](docs/agentic-view.html)

[![Every theme ranked by matching prompts, sessions and project paths](docs/images/theme-ranking.png)](docs/agentic-view.html)

## How it works

```mermaid
flowchart TD
    logs["Claude and Codex JSONL logs<br/>four local profiles"]
    raw[("conversations.sqlite3<br/>original bytes, checkpoints")]
    snap[("backup at a fixed<br/>raw-record watermark")]
    corpus[("corpus.sqlite3<br/>likely human prompts")]
    labels["relevance label<br/>per prompt"]
    recall["recall candidates<br/>keyword safety net"]
    themes["theme tags<br/>per instruction prompt"]
    audit["phrase counts<br/>deterministic search"]
    docs["docs/: guidelines, evidence,<br/>summary page"]

    logs -->|"capture: backfill, then poll every 10 s"| raw
    raw -->|backup| snap
    snap -->|"corpus: authorship, duplicates"| corpus
    corpus -->|"classify: local model"| labels
    labels -->|recall| recall
    labels -->|"extract: local model"| themes
    recall --> themes
    corpus -->|evidence_audit| audit
    themes -->|report| docs
    audit --> docs
```

Capture runs continuously and never changes the analysis input: every later
stage reads a backup frozen at one raw-record watermark, so a result can be
reproduced from it. The two model stages use a local Ollama model on loopback
only, and both resume where they stopped. The documents in `docs/`, including
the summary page, were written from the `report` and `evidence_audit` output;
no stage generates them.

### How long a run takes

Measured on the real history (about 2.5 GB, 400,000 raw records, 7,882 likely
human prompts) on a 20-core laptop with one GPU holding `qwen3.5:4b`:

| Stage | Command | Time |
| --- | --- | ---: |
| First capture of all four profiles | `recurrence-ranger backfill` | 38 s for 404,460 records, file cache warm |
| Keeping capture current | `recurrence-ranger run` (systemd service) | under 1% of one core, new records within 6 s median |
| Consistent online backup | `recurrence-ranger backup` | 5 s |
| Prompt corpus from the backup | `recurrence_ranger.corpus` | about 1 s |
| Relevance triage of 6,769 prompts | `recurrence_ranger.classify` | 47–63 min (0.42–0.56 s per prompt) |
| Recall safety net | `recurrence_ranger.recall` | under 1 s |
| Theme extraction of 5,013 prompts | `recurrence_ranger.extract` | about 71 min (0.85 s per prompt) |
| Report and evidence audit | `recurrence_ranger.report`, `recurrence_ranger.evidence_audit` | under 1 s |
| Summary page | open `docs/agentic-view.html` | instant, static HTML |

A complete analysis from nothing therefore takes two to two and a quarter
hours, almost all of it local model time. The other 1,113 prompts are exact
short inputs such as `/exit` or `continue`, labelled without the model. With
`corpus --carry-labels`, a later run sends only new or changed prompts to the
model. The model rates come from
[PERFORMANCE_REVIEW.md](docs/PERFORMANCE_REVIEW.md). The first real run took
longer, 2 h 5 min for triage and 1 h 21 min for extraction by the recorded
timestamps, because the fixes behind those rates landed during it.

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
[CAPTURE_ACCEPTANCE.md](docs/project/CAPTURE_ACCEPTANCE.md).

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

Run the same pipeline that hosted CI runs. It checks the pinned tool versions,
formatting, lint, static analysis, every test, a measured coverage report, the
coverage gate and the version history:

```sh
./localpipeline.sh
```

The gate fails unless overall statement and branch coverage is strictly above
98%. `COVERAGE_MINIMUM` and `COVERAGE_REPORT` override the threshold and the
report path, and `PYTHON` selects the interpreter, so the same gate can be run on
the oldest supported version:

```sh
PYTHON=python3.11 ./localpipeline.sh
```

The coverage report itself is not committed.

Three GitHub workflows mirror this locally run script:

- **Local Pipeline** runs `./localpipeline.sh` on every push and pull request,
  on Python 3.11 and 3.14 so the supported floor stays checked, and keeps each
  coverage report as an artifact.
- **Quality** runs the pinned tool check, ruff formatting and lint, and mypy
  for fast feedback without the test suite.
- **Manual Release** is started by hand for a chosen version. It only publishes
  after the version matches every version field, the pipeline passes, and the
  built wheel installs and runs.

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
[SOURCE_INVENTORY.md](docs/project/SOURCE_INVENTORY.md) gives the initial
observed coverage. Codex's `thread_history_1.sqlite` is a derived projection
whose rows are not yet ingested separately; rollout JSONL is the primary Codex
source. The final capture report should name any missing profiles, failed
files, and gaps.

## Development

Implementation details and work packages are in
[IMPLEMENTATION_PLAN.md](docs/project/IMPLEMENTATION_PLAN.md). The code uses
Python's standard library at runtime. Test fixtures are synthetic; no real
transcript belongs in this repository. Commit implementation steps locally with
conventional messages. Do not push private data.

Every commit advances the patch version by one, beginning at `0.0.1` in the
root commit. `VERSION` is the history marker; `pyproject.toml` and the package
`__version__` match it whenever they exist. Before each new commit, run
`python3 scripts/versioning.py bump` and stage all three version files with the
work. After committing, `./localpipeline.sh` verifies the complete linear history
and the package version fields. CI fetches full history for the same check.

## Fixed corpus and local relevance triage

Derive an auditable prompt corpus from a consistent private backup, then run
optional local model triage. The output SQLite file stays outside this repo.
The corpus records a raw-record watermark and parser version, keeps each source
occurrence and its exclusion reason, and links near-time transcript/history
representations of one prompt. Repeated turns remain separate.

```sh
.venv/bin/python -m recurrence_ranger.corpus \
  ~/.local/share/recurrence-ranger/acceptance-backup.sqlite3 \
  ~/.local/share/recurrence-ranger/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.classify \
  ~/.local/share/recurrence-ranger/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.recall \
  ~/.local/share/recurrence-ranger/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.extract \
  ~/.local/share/recurrence-ranger/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.report \
  ~/.local/share/recurrence-ranger/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.evidence_audit \
  ~/.local/share/recurrence-ranger/corpus.sqlite3
```

The classifier uses an installed `qwen3.5:4b` model through local Ollama on
`127.0.0.1`; `--model` and `--endpoint` select another local model or port, and
a non-loopback endpoint is rejected. `--concurrency` sets how many requests the
model answers at once; four was about twice as fast as one on a single local GPU,
and eight was slower again. If the endpoint stops answering, both stages retry,
then stop with an error and leave those prompts unlabelled for the next run
instead of recording the silence as a decision. Labels are provisional and
resumable. It sends no prompt text
to a remote endpoint. Review uncertain authorship, model decisions, and source
evidence before writing reusable guidance. The extraction pass tags each
instruction prompt with zero or more atomic project-expectation themes, and
records empty decisions as well. The recall pass flags prompts where a model
non-instruction label conflicts with an explicit software term, so extraction
can inspect them too. Its tags also need evidence review. Re-deriving
the corpus clears old model decisions because prompt IDs and the watermark may
change. `--carry-labels` keeps them for every prompt whose profile, session and
text are unchanged, so a new watermark does not cost another full model run;
prompts that are new, edited or only partly processed stay open for the next
resumable run.

The active planning conversations for this investigation remain in the private
corpus but are excluded from guideline evidence, so the seed examples in the
request cannot prove themselves by repetition.

Derived results live in [docs/](docs/): the ranked guideline catalog
([GUIDELINES.md](docs/GUIDELINES.md)), the evidence and its limits
([EVIDENCE.md](docs/EVIDENCE.md)), the performance and robustness review
([PERFORMANCE_REVIEW.md](docs/PERFORMANCE_REVIEW.md)) and a summary page
([agentic-view.html](docs/agentic-view.html)) with the counter-analysis.

The evidence audit independently searches the opening 750 characters of likely
human prompts for explicit theme phrases. It reports matched prompt, session,
project-path, and profile counts plus a few raw-record IDs, without printing
prompt text. It excludes this project and the original wishlist project. A
match can be a question, quote, or one-off request, while a differently worded
instruction may not match. Review the linked source records before treating
these counts as support for a reusable guideline.
