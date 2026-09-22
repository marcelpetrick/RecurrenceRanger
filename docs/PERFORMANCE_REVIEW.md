# Performance and robustness review

Date: 2026-09-22. Measured on the real local corpus: a 2.4 GB capture database with
385,404 raw records at the acceptance watermark, 44,592 candidate user messages and
7,882 likely human prompts. Machine: 20 cores, one GPU holding `qwen3.5:4b` (3.3 GB
of VRAM), Python 3.14.7.

## Where the time actually goes

| Stage | Before | After | How it was measured |
| --- | ---: | ---: | --- |
| Corpus derivation from the 2.4 GB capture | 4.56 s | 1.06 s | `derive` on the acceptance backup, repeated runs, identical output |
| Relevance triage per prompt | 1.26 s | 0.56 s | 25-prompt timed run, then the live run over thousands of prompts |
| Model request microbenchmark (4 batches of 5) | 0.87 s/prompt | 0.38 s/prompt | same prompts, 1 versus 4 concurrent requests |
| Triage on an otherwise idle machine | — | 0.42 s/prompt | 80 unlabelled prompts, batch 5, four workers |
| Guideline extraction | 12 s/prompt | 0.85 s/prompt | the live run before and after the schema bound the answer length |
| Continuous capture | 42 s CPU in 85 min | unchanged | collector service with a 10 s poll over 943 transcript files |

The extraction figure is the one that mattered most: the stage was not slow, it was
retrying. Once the answer schema required one entry per prompt, the same model did the same
work fourteen times faster and stopped discarding results.

Capture was already cheap: under one percent of one core keeps four profiles current,
because each cycle only stats files and reads appended bytes. The two expensive stages
were derivation, which read stored record bytes it did not need, and the model stages,
which left the GPU idle between requests. Neither was a hot loop in Python; both were
waiting on data.

## End-to-end run times

Measured on 2026-09-22 at version 0.0.96 against the live history of about 2.5 GB. The
fast stages were timed directly on private copies, which were deleted afterwards; the model
stages use the rates in the table above, because repeating them costs two hours of GPU time.

| Stage | Command | Time |
| --- | --- | ---: |
| First capture of all four profiles | `recurrence-ranger backfill` | 38.1 s wall, 29.0 s CPU, 88 MB peak memory, 42 cycles, 404,460 records |
| Keeping capture current | `recurrence-ranger run` | under 1% of one core; new records captured within 5.7 s median |
| Consistent online backup | `recurrence-ranger backup` | 4.9 s |
| Prompt corpus from the backup | `recurrence_ranger.corpus` | 1.2 s warm, 5.6 s with a cold cache |
| Relevance triage of 6,769 prompts | `recurrence_ranger.classify` | 47–63 min at 0.42–0.56 s per prompt |
| Recall safety net | `recurrence_ranger.recall` | 0.07 s |
| Theme extraction of 5,013 prompts | `recurrence_ranger.extract` | about 71 min at 0.85 s per prompt |
| Report | `recurrence_ranger.report` | 0.07 s |
| Evidence audit | `recurrence_ranger.evidence_audit` | 0.66 s |

The backfill ran with the transcript files in the page cache, so a first run on a cold
machine reads 2.5 GB from disk and takes longer. A complete analysis from nothing takes two
to two and a quarter hours, and over 99% of it is local model time. The first real run took
2 h 5 min for triage and 1 h 21 min for extraction by its recorded timestamps, because the
fixes behind the current rates landed during it. The summary page and the documents are not
a timed stage: they were written from the report and audit output, and no code generates
them.

## Findings and what was done

Ranked by impact. Every fix has its own commit and its own tests.

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 1 | High (performance) | Triage and extraction sent one request at a time, so the local model idled between batches. | Fetch several batches per round and answer them through a small thread pool, keeping all database writes on the calling thread. Four concurrent requests measured 2.3 times the throughput of one; eight were slower again, so `--concurrency` defaults to four. |
| 2 | High (robustness) | A refused connection, timeout or HTTP error was caught together with malformed model output, so a run against a stopped model wrote `uncertain` for every prompt, with a note, and still reported success. Thousands of labels could be silently wrong. | Retry transport failures with backoff, then raise `EndpointUnavailable`. The affected prompts stay unlabelled, the next run resumes them, and both commands exit 1 with the endpoint in the message. |
| 3 | Medium (performance) | Every prompt was sent with up to 6,000 characters, so a batch of five could exceed the 8,192-token context. The model then answered for fewer prompts than were sent, and the caller split the batch and asked again. Observed once during benchmarking. | Share one character budget across the batch, never below 1,200 characters per prompt. |
| 4 | Medium (performance) | Derivation fetched the stored JSONL bytes of all 44,592 candidate messages, although only Claude `user` records are parsed for the flags that decide authorship. | Select those bytes conditionally. Derivation is 4.3 times faster with identical output. |
| 5 | Medium (robustness) | The version-history check ran `git rev-list HEAD` directly, so a repository without commits failed with a `CalledProcessError` traceback instead of the script's own error. | Report it as a `ValueError` like every other verification failure. |
| 6 | Medium (robustness) | The pipeline used whichever ruff, mypy, pytest and coverage happened to be importable, so a local run could check the code with different tools than CI. This had already happened once with an unusable mypy in the user site. | `scripts/tool_versions.py` compares installed versions against the pinned development extra and fails with one line per drift. |
| 7 | Low (testability) | The collector command dispatch ended in a condition the argument parser already excluded, so its fall-through could never run or be tested. | Handle backup as the remaining case. |
| 8 | High (correctness and performance) | The structured-output schema accepted a theme array of any length, so the model could answer a five-prompt extraction batch with an empty array. That read as a wrong-length answer: the batch was split and re-asked down to single prompts, and 18% of reviewed prompts were finally recorded with **no themes at all** while costing four extra requests each. | Bound both answer schemas to the batch size with `minItems` and `maxItems`. Extraction went from 0.08 answers per second to 1.17, and the affected 73 prompts were reopened and re-reviewed. |
| 9 | Medium (cost) | Re-deriving the corpus dropped every model decision, so including newer sessions meant paying for the whole triage and extraction again — hours of local model time. | `--carry-labels` re-attaches decisions to prompts whose profile, session and text are unchanged. New, edited and partly processed prompts stay open for the next resumable run. |
| 10 | Low (portability) | One test called `git` without an identity, so it failed on machines without a global git configuration. GitHub Actions found this on the first hosted run. | Route it through the helper that carries the test identity. Verified with `GIT_CONFIG_GLOBAL=/dev/null`. |

## Workflow level: what makes the whole run faster

The pipeline is deliberately staged so that expensive work only sees data that needs it.

- **Capture is incremental.** Byte-range checkpoints commit with the records, so a restart
  reads only new bytes. Backfilling 2.4 GB happens once.
- **Derivation is a fixed snapshot.** Analysis runs against a watermark and a backup, so the
  live collector can keep writing without changing the input halfway through.
- **1,113 prompts never reach the model.** Exact short inputs such as `/exit`, `continue` and
  `/status` are labelled deterministically. That is 14% of the corpus answered instantly, and
  it also keeps those labels consistent.
- **Extraction only reads what triage selected.** Instruction-labelled prompts plus recall
  candidates, not all 7,882 prompts, and this project's own planning conversations are
  excluded from evidence by project path.
- **Both model stages are resumable per batch**, so an interrupted run costs at most one round.

Combined effect on a full analysis of the current corpus: derivation dropped from about
5 s to about 1 s, and the remaining triage of 5,306 prompts from roughly 1 h 50 min to
roughly 50 min, without changing any decision the pipeline records.

## Later findings, from the dependency and branch reviews

Reviewed after the analysis run, in the same style. Each fix is again its own commit with
its own tests, and the gate was re-run on both supported Python versions.

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 11 | Medium (supply chain) | Every Python dependency was pinned exactly, but the workflows referenced actions by release tag, and a tag can be moved to another commit. | Pin each action to the commit its release points at, with the version as a comment. |
| 12 | Medium (correctness of a claim) | `requires-python = ">=3.11"` was never exercised: hosted CI only ran 3.14, so the supported floor was a hope. | Run the pipeline on 3.11 and 3.14, with one coverage artifact per version. The whole suite passes on 3.11.15. |
| 13 | Medium (drift) | Exact pins never move by themselves, so an outdated pin was only noticed when somebody ran the update workflow by hand. | A weekly job compares every pin, including the build backend, against its latest stable release and fails when one is behind. It opens no pull request, because an update needs its own commit and patch version. |
| 14 | Medium (reproducibility) | The gate preferred `.venv/bin/python` whenever it existed, with no override, so the floor version that CI now tests could not be reproduced locally — an attempt to do so silently re-ran the repository venv. | `PYTHON` selects the interpreter, like `COVERAGE_MINIMUM` selects the threshold. |
| 15 | Medium (signal quality) | The drift check reported an unreachable index, a timeout and a yanked release exactly like a genuinely outdated pin, and failed the job for all of them. A check that goes red on an outage is a check people stop reading. | Warn for an unreadable release, fail only for a pin that is really behind. |
| 16 | Low (coverage of the check) | The drift check read only the development extra, so the `setuptools` pin that decides how the released wheel is built was never compared. | Compare the build requirements too, through one shared parser. |
| 17 | Low (input handling) | A requirement's name went into the index URL verbatim, so a future pin carrying an extra or a marker would have been queried as a project and reported as unreadable rather than as a malformed pin. | Require a bare project name and normalise it the way the index spells it. |

## Findings from the full-state review

A review of the whole code base as it stood at 0.0.87, rather than of one branch. Each
finding was reproduced before it was fixed, each fix is its own commit with a test that fails
without it, and the gate passed after every commit.

| # | Severity | Finding | Fix |
| --- | --- | --- | --- |
| 18 | High (data loss) | The derivation dropped the model tables before sqlite3 began its implicit transaction, so the drops committed on their own. Any failure afterwards restored the prompts but left every relevance label, review and theme deleted. | Begin the transaction explicitly, so the replacement commits or rolls back as one. |
| 19 | High (availability) | A deeply nested JSON line raised `RecursionError`, which capture did not catch. The line aborted the whole scan, and since it stays in the file, every later run stopped at it: capture of every source halted. | Report such a record as malformed and keep its bytes, in capture and in the derivation. |
| 20 | Medium (correctness) | Carrying decisions by profile, session and text merged the themes of two prompts that repeat the same text, inserted a shared theme twice and failed on the primary key; through finding 18 that also deleted the labels. | Take every carried decision for a key from the earliest earlier prompt. |
| 21 | Medium (design) | The exclusion of this analysis's own sessions was copied as raw SQL into five queries, so changing one copy would have made the extraction queue, its count and the reported themes disagree. | State the projects and the condition once, beside the shared table definitions. |
| 22 | Low (input handling) | Read-only databases were opened as an unescaped `file:` URI, so a path containing `#`, `?` or `%` opened a different file. | Open them through one helper that quotes the path. |
| 23 | Low (resource lifetime) | The backup target was opened in a `with` block, which commits but never closes a sqlite3 connection. | Close it explicitly. |
| 24 | Low (documentation) | The plan named a `ci.yml` workflow that does not exist, next to outdated coverage numbers. | Name `local-pipeline.yml` and state the current measurement. |

## Deliberately not done

- **Larger batches.** Measured against the real corpus at four concurrent requests: five
  prompts per request took 0.42 s per prompt, ten took 0.73 s and twenty took 1.04 s. The model
  spends longer producing a bigger structured answer than it saves in round trips, so five
  stays the default and throughput was bought with concurrency instead.
- **Running several triage processes.** Two writers on one SQLite corpus would race for the
  same unlabelled rows. Concurrency inside one process avoids that entirely.
- **Micro-optimising the JSON parsing** that dominates derivation. After finding 4, the whole
  derivation costs about a second; anything further would trade clarity for noise.
