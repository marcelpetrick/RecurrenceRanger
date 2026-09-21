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

The extraction stage tags each instruction prompt with zero or more atomic project
expectations, over 5,013 eligible prompts (instruction-labelled plus recall candidates,
excluding this project and the wishlist project). It runs against the same local model and
was still in progress when this document was written; its counts are added to
[GUIDELINES.md](GUIDELINES.md) once the pass finishes. The tiers above rest on the
deterministic audit and the triage counts, both of which are complete.

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
Re-deriving the corpus resets model labels, because prompt identity depends on the
watermark.
