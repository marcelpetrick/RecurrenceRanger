# Marcel's recurring guidelines for software work with AI agents

Derived on 2026-09-22 from 7,882 likely human prompts across four local tool profiles
(Claude, Claude DMO, Codex, Codex DMO), 710 sessions and 202 project paths, captured
between 2026-04-10 and 2026-09-21. This project's own conversations and the original
wishlist project are excluded, so the guidelines cannot prove themselves.

Two independent methods measured the same corpus and agree on the ranking:

- **audit** — a deterministic search for explicit phrasings in every human prompt,
- **model** — a local model tagging atomic expectations in all 5,013 instruction and
  recall-flagged prompts, with zero unparsable answers.

Each guideline carries `audit N · model N (sessions / project paths)`. Details and limits
are in [EVIDENCE.md](EVIDENCE.md). Of the 7,882 prompts, **4,560 (58%) are instructions to
create or change software**: this is a working corpus, not a chat log.

## Tier 1 — the doctrine

### 1. Finish the whole authorized task, then report — `audit 463 · model 860 (316 / 128)`

Do the complete batch that was asked for, not the first step of it. Run the commands
yourself instead of handing back a list. When several requests are open, all of them get
done. Say what is finished and what is left.

The strongest theme by both methods, in 128 of 202 project paths and all four profiles.
Typical phrasing: *get all done*, *get it done and documented*, *run the commands
yourself*.

### 2. Plan before implementing, then execute the plan — `audit 182 · model 608 (287 / 120)`

Write the plan down first, say what you understood, compare options with reasons, and keep
the plan file current as the work proceeds. Confirmation happens once, about the direction.

### 3. Commit atomically, conventionally, with a version bump
`audit 128 version · 108 atomic · 98 conventional · model 593 commit · 446 atomic · 282 conventional`

One logical change per commit, a conventional subject, a body that says why, a patch
increment in the same commit, and only that change's files staged. Company merge requests
invert the shape: everything squashed into one conventional commit. The boundary is the
review process, not the preference.

### 4. Make the result verifiable — `audit 100 coverage · 85 tests · 46 evidence · model 458 verify · 279 tests · 103 coverage`

Check that the result actually works and show the evidence: the command that ran, the log,
the screenshot, the measured number. Tests exercise real behavior, coverage is measured and
gated. *If you can make your claim testable, then do.*

### 5. Review your own work, then fix every finding
`audit 169 review · 112 self-review · 64 fix-all · model 382 code review · 279 fix findings · 185 architecture review`

Review code, architecture and documentation against the current state, rank findings by
severity, then fix all of them — each with its own commit, and each review comment answered
with what changed or why it will not.

### 6. Report progress and results in a form someone can read — `model 362 (220 / 96)`

The second discovery of the model pass: a large share of instructions are about the
*communication* of work — a crisp summary, a merge request description about what changed,
a comment on the ticket, an overview for a meeting. Keep it short, factual and structured.
The deterministic audit missed this because it is phrased differently every time.

### 7. Stay inside the scope you were given — `audit 10 · model 244 (159 / 88)`

*Least changes*, *only this file*, *leave the rest alone*, *keep the text, only fix the
tags*. Rarely the main sentence of a prompt, which is why phrase matching almost missed it,
but present in 88 project paths and usually stated while correcting an agent that had
widened the scope on its own.

## Tier 2 — repeated, with clear conditions

### 8. Documentation: current, crisp, and it points to the details
`audit 61 crisp · 30 document-decisions · 29 badges · 18 C4 · model 390 docs · 148 README · 94 badges · 54 C4`

A README that states what the thing is, with status badges at the top, guiding to the other
documents for detail. Architecture documented, C4 where it fits, decisions and review
outcomes written into the repository. Keep the prose short: *don't write tons*, *two
sentences per finding*.

### 9. One pipeline, run locally, mirrored by CI, then watched
`audit 112 local · 55 hosted · 24 watch · model 236 local · 150 hosted`

One committed entry point runs formatting, lint, static analysis, tests and coverage;
hosted CI runs that same script rather than a second definition; after the push the
pipeline and the review comments are watched and answered.

### 10. Dependencies current, pinned exactly — `audit 81 · model 235 dependencies · 86 pin versions`

Check against the latest stable upstream release, pin exact versions, update, and commit
only when the project's own gate passes afterwards.

### 11. Ship it, and leave a trace — `audit 142 ticket · 72 release`

Work ends in a push and a public release. It is linked to the ticket or merge request that
asked for it, with the reviewer assigned, labels current and the outcome commented back
with the commit reference.

### 12. Reproducible setup and results — `model 117 (91 / 56)`

Someone else — or the same person on another machine — must be able to run it: pinned
versions, one entry point, copy-pasteable commands, recorded measurements rather than
impressions.

## Tier 3 — present, narrower, keep as conditional rules

- **Handle failure paths deliberately** — `audit 67 · model 83`: the error case, the empty
  case, the interrupted run; make the tool say what went wrong.
- **Usability and presentation** — `model 99`: polish what a person sees, including
  recorded demos and screenshots of the result.
- **Measure performance when it matters** — `model 86`: profile, record the data, document
  the evaluation. Asked for occasionally, always with numbers attached.
- **Delegate to the cheaper capable agent** — `audit 74 · model 63`: subagents and smaller
  local models where the task allows, with an eye on quota and cost.
- **Protect private data** — `audit 3 · model 35`: redact sensitive information in
  recordings, invent placeholder names, keep company and personal accounts and
  configuration apart.

## Conflicts and conditions worth respecting

- **Atomic commits versus one squashed commit.** Local work: many small commits. Company
  merge requests: one conventional commit with a description of what changed.
- **A patch version in every commit versus semantic versioning.** The version is used as a
  build counter, so `0.0.x` carries no maturity claim.
- **Thorough versus crisp.** The work should be complete; the writing about it should be
  short. Brevity applies to the prose, not to the scope.
- **Full autonomy versus confirmation.** *Run the commands yourself* and *full auto* sit
  beside *tell me if you understood*. Plan and confirm the direction once, then execute the
  whole batch.
- **Finish everything versus stay in scope.** The two strongest instincts in the corpus pull
  against each other: complete the batch, but do not invent work that was not asked for.
  The resolution in practice is the plan: what is in the plan gets finished, what is not
  gets proposed first.

## How to use this as agent instructions

Plan first and say what you understood. Work the whole batch, and nothing outside it.
Commit atomically with conventional messages and a version bump. Run the local pipeline and
make hosted CI run the same script. Keep tests meaningful, coverage measured, and every
claim backed by something checkable. Review your own result and fix every finding. Report
crisply what changed. Keep the README badged and the documents current, check dependencies,
then push, release and leave a trace on the ticket. Ask before widening scope, and keep
private data out of anything published.
