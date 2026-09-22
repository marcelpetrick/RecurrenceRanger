# Evidence behind the guidelines

What was measured, how, and what the numbers do not prove. No prompt text is reproduced
here: the corpus stays on the machine that collected it, and this document reports counts
and source references only.

## The corpus

| Property | Value |
| --- | --- |
| Capture database | 2.4 GB, 385,404 raw records at the fixed watermark |
| Watermark / parser version | 385404 / 1 |
| Profiles | Claude, Claude DMO, Codex, Codex DMO (all four available) |
| Candidate user messages | 44,592 |
| Excluded occurrences | 31,755 (tool results, generated context, subagent and exec sessions, notifications) |
| Duplicate representations reconciled | 4,829 (transcript and history entries of one prompt within 60 s) |
| Likely human prompts | 7,882 |
| Uncertain authorship, kept separate | 126 |
| Sessions / project paths | 710 / 202 |
| Prompt dates | 2026-04-10 to 2026-09-21 |

Prompts per profile: Claude 4,739, Codex 2,412, Claude DMO 519, Codex DMO 212.

## Stage 1: relevance triage by a local model

`qwen3.5:4b` through local Ollama on `127.0.0.1`, prompt version 2, batches of five,
four concurrent requests, no prompt text leaving the machine. All 7,882 human prompts
have a label; 1,113 exact short inputs (`/exit`, `continue`, `/status`, …) were labelled
deterministically without the model.

| Label | Prompts | Share |
| --- | ---: | ---: |
| software_instruction | 4,560 | 58% |
| nonsoftware | 1,331 | 17% |
| software_other (question or discussion) | 1,240 | 16% |
| uncertain | 751 | 10% |

Instruction prompts per profile: Claude 2,474, Codex 1,638, Claude DMO 321, Codex DMO 127.
Across the whole run the model produced **no unparsable answers**: every batch that came
back malformed was split and re-asked until each prompt had a decision, and the notes
column contains only the deterministic marker.

## Stage 2: recall check

A deterministic pass re-reads every prompt the model did *not* call an instruction and
flags those whose first 750 characters contain an explicit software term. It flagged
**471** prompts for extraction to inspect anyway. The most frequent triggers were
`review` (98), `commit` (95), `test` (68), `plan` (41) and `ci` (27) — evidence that a
single model label should not be the only gate.

## Stage 3: direct phrase audit over every human prompt

Independent of the model. Each pattern is searched in the opening 750 characters of every
likely human prompt, because instructions normally precede pasted logs. This project and
the original wishlist project are excluded.

| Theme | Prompts | Sessions | Project paths | Profiles |
| --- | ---: | ---: | ---: | ---: |
| FINISH_ALL | 463 | 188 | 95 | 4 |
| PLAN_FIRST | 182 | 120 | 66 | 4 |
| REVIEW_CODE_ARCH | 169 | 118 | 48 | 4 |
| TICKET_TRACE | 142 | 56 | 18 | 4 |
| VERSION_BUMP | 128 | 79 | 34 | 4 |
| CI_LOCAL | 112 | 61 | 36 | 4 |
| SELF_REVIEW | 112 | 84 | 48 | 4 |
| ATOMIC_COMMITS | 108 | 77 | 44 | 4 |
| COVERAGE | 100 | 46 | 22 | 4 |
| CONVENTIONAL_COMMITS | 98 | 84 | 43 | 4 |
| TESTS | 85 | 55 | 25 | 4 |
| DEPENDENCIES | 81 | 58 | 29 | 4 |
| DELEGATE | 74 | 46 | 27 | 3 |
| RELEASE | 72 | 47 | 17 | 4 |
| ROBUST | 67 | 52 | 39 | 4 |
| FIX_ALL_FINDINGS | 64 | 50 | 31 | 4 |
| CRISP | 61 | 50 | 26 | 4 |
| CI_HOSTED | 55 | 43 | 31 | 4 |
| EVIDENCE | 46 | 36 | 27 | 3 |
| DOCUMENT_DECISION | 30 | 25 | 23 | 4 |
| README_BADGES | 29 | 24 | 19 | 4 |
| WATCH_CI | 24 | 19 | 12 | 4 |
| C4 | 18 | 18 | 14 | 2 |
| MINIMAL_CHANGE | 10 | 10 | 7 | 4 |
| PRIVACY_REDACT | 3 | 3 | 2 | 3 |

Twelve of these patterns cover the four seed categories from the original request; the
other thirteen were added after reading the corpus, so the ranking is not limited to what
was expected at the start. Notably, the strongest theme — finishing the whole task — was
not in the seed list at all, and two seed categories (README badges, C4 architecture) rank
near the bottom.

## Stage 4: model-tagged guideline occurrences

All **5,013** eligible prompts were reviewed — instruction-labelled plus recall candidates,
excluding this project and the wishlist project — with **zero unparsable answers**. Each
prompt received zero or more atomic expectations.

| Theme | Prompts | Sessions | Project paths | Profiles |
| --- | ---: | ---: | ---: | ---: |
| COMPLETE | 860 | 316 | 128 | 4 |
| PLAN | 608 | 287 | 120 | 4 |
| COMMIT | 593 | 287 | 128 | 4 |
| VERIFY | 458 | 257 | 103 | 4 |
| ATOMIC_COMMITS | 446 | 246 | 106 | 4 |
| DOCS | 390 | 225 | 110 | 4 |
| REVIEW_CODE | 382 | 237 | 98 | 4 |
| COMMUNICATE | 362 | 220 | 96 | 4 |
| OTHER | 319 | 210 | 102 | 4 |
| CONVENTIONAL_COMMITS | 282 | 190 | 93 | 4 |
| FIX_FINDINGS | 279 | 177 | 75 | 4 |
| TESTS | 279 | 169 | 83 | 4 |
| SCOPE | 244 | 159 | 88 | 4 |
| CI_LOCAL | 236 | 161 | 77 | 4 |
| DEPENDENCIES | 235 | 151 | 77 | 4 |
| REVIEW_ARCH | 185 | 145 | 74 | 4 |
| CI_HOSTED | 150 | 96 | 47 | 4 |
| README | 148 | 101 | 64 | 4 |
| REPRODUCIBLE | 117 | 91 | 56 | 3 |
| COVERAGE | 103 | 66 | 32 | 4 |
| UX | 99 | 75 | 49 | 4 |
| BADGES | 94 | 71 | 48 | 4 |
| PERFORMANCE | 86 | 69 | 50 | 4 |
| PIN_VERSIONS | 86 | 68 | 40 | 4 |
| ROBUST | 83 | 69 | 46 | 3 |
| DELEGATE | 63 | 45 | 32 | 4 |
| C4 | 54 | 42 | 30 | 3 |
| PRIVACY | 35 | 30 | 24 | 2 |

### Where the two methods agree, and where they do not

The top two themes are the same under both methods, which is the strongest statement this
corpus supports: finishing the whole task and planning first are not artefacts of one
measurement. Commit discipline, verification and review follow in both.

Two themes are much larger under the model than under phrase matching, and the model is
right about them:

- **COMMUNICATE** (362) has no phrase pattern at all. Instructions about *how the work is
  reported* — a crisp summary, a merge request description, a ticket comment, an overview
  for a meeting — are phrased differently every time.
- **SCOPE** (244 versus 10 for the `MINIMAL_CHANGE` phrases): scope-limiting intent is
  usually expressed in context (*only this file*, *keep the text*), not with a keyword.

Two themes are larger under the model than under phrase matching for a duller reason:
`BADGES` (94 versus 29) and `C4` (54 versus 18) catch prompts where the subject is
mentioned in passing. Their rank stays low under both methods.

### Label quality, checked by hand

A sample of labels was read directly. `nonsoftware` and `software_other` are mostly right.
The instructive error is in `uncertain` (751 prompts): it absorbs short follow-ups such as
*until all done* or *continue, get it done* — which are exactly the strongest theme in the
corpus, stated without context. Model labels alone would therefore **under-count
completion**, which is why the deterministic audit runs over every prompt regardless of its
label, and why the recall pass exists.

## What these numbers do not prove

- A phrase match is not a guideline. It can be a question, a quote from a review bot, a
  one-time request, or a correction of something an agent did wrong.
- A missing match is not an absent preference. Different wording, other languages and
  typo-heavy phrasing are missed; the corpus contains a lot of fast typing.
- Counts are per prompt. A preference stated once but honoured silently in every project
  scores low; a preference repeated because agents keep getting it wrong scores high. The
  ranking measures *what gets said*, which is close to but not identical with *what
  matters*.
- Transport-level identity: `messages.role='user'` includes tool results and injected
  context, so authorship was decided by record flags and content, and 126 prompts remain
  explicitly uncertain rather than being forced into a bucket.
- The corpus ends at the watermark. Sessions from the evening of 2026-09-21 onward,
  including the work that produced these documents, are captured but deliberately outside
  the analysed snapshot.

## Reproducing this

```sh
.venv/bin/recurrence-ranger backup ~/private/backup.sqlite3
.venv/bin/python -m recurrence_ranger.corpus ~/private/backup.sqlite3 ~/private/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.classify ~/private/corpus.sqlite3 --concurrency 4
.venv/bin/python -m recurrence_ranger.recall ~/private/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.extract ~/private/corpus.sqlite3 --concurrency 4
.venv/bin/python -m recurrence_ranger.report ~/private/corpus.sqlite3
.venv/bin/python -m recurrence_ranger.evidence_audit ~/private/corpus.sqlite3
```

Timings and the cost of each stage are in [PERFORMANCE_REVIEW.md](PERFORMANCE_REVIEW.md).
The full run over this corpus took about 50 minutes of triage and 70 minutes of extraction
on one local GPU.
Re-deriving the corpus resets model labels, because prompt identity depends on the
watermark.
