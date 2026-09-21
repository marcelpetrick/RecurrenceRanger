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
| Continuous capture | 42 s CPU in 85 min | unchanged | collector service with a 10 s poll over 943 transcript files |

Capture was already cheap: under one percent of one core keeps four profiles current,
because each cycle only stats files and reads appended bytes. The two expensive stages
were derivation, which read stored record bytes it did not need, and the model stages,
which left the GPU idle between requests. Neither was a hot loop in Python; both were
waiting on data.

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
| 8 | Medium (cost) | Re-deriving the corpus dropped every model decision, so including newer sessions meant paying for the whole triage and extraction again — hours of local model time. | `--carry-labels` re-attaches decisions to prompts whose profile, session and text are unchanged. New, edited and partly processed prompts stay open for the next resumable run. |
| 9 | Low (portability) | One test called `git` without an identity, so it failed on machines without a global git configuration. GitHub Actions found this on the first hosted run. | Route it through the helper that carries the test identity. Verified with `GIT_CONFIG_GLOBAL=/dev/null`. |

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

## Deliberately not done

- **Larger batches.** Measured against the real corpus at four concurrent requests: five
  prompts per request took 0.42 s per prompt, ten took 0.73 s and twenty took 1.04 s. The model
  spends longer producing a bigger structured answer than it saves in round trips, so five
  stays the default and throughput was bought with concurrency instead.
- **Running several triage processes.** Two writers on one SQLite corpus would race for the
  same unlabelled rows. Concurrency inside one process avoids that entirely.
- **Micro-optimising the JSON parsing** that dominates derivation. After finding 4, the whole
  derivation costs about a second; anything further would trade clarity for noise.
