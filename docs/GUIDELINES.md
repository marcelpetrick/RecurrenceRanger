# Marcel's recurring guidelines for software work with AI agents

Derived on 2026-09-22 from 7,882 likely human prompts across four local tool profiles
(Claude, Claude DMO, Codex, Codex DMO), 710 sessions and 202 project paths, captured
between 2026-04-10 and 2026-09-21. This project's own conversations and the original
wishlist project are excluded, so the guidelines cannot prove themselves.

Counts in brackets are **matching prompts / sessions / project paths / profiles** from the
deterministic phrase audit over every human prompt. They are search aids, not semantic
truth: a match can be a question or a one-off, and a differently worded instruction is
missed. Evidence and limits are in [EVIDENCE.md](EVIDENCE.md).

Of the 7,882 prompts, **4,560 (58%) are instructions to create or change software**. This
is a working corpus, not a chat log.

## Tier 1 — broad and repeated across projects, tools and months

### 1. Finish the whole authorized task [463 / 188 / 95 / 4]

Do the complete batch of work that was asked for, not the first step of it. Run the
commands yourself instead of handing back a list. When several requests are open, work
through all of them. Report what is done and what is left, explicitly.

This is the single strongest signal in the corpus, present in 95 different project paths
and all four profiles. Typical phrasing: *get all done*, *get it done and documented*,
*run the commands yourself*, *then we see the next days*.

### 2. Plan before implementing, then execute the plan [182 / 120 / 66 / 4]

Write the plan down first, say what you understood, choose between options with reasons,
and only then build. Keep the plan file current as work proceeds — the plan is a living
document, not a one-time artifact.

### 3. Review your own work, then fix everything the review found
[self review 112 / 84 / 48 / 4 · code and architecture review 169 / 118 / 48 / 4 ·
fix all findings 64 / 50 / 31 / 4]

Review code, architecture and documentation against the current state, rank findings by
severity, then fix them one by one. Fix all of them, not the convenient ones. When a
review comment is answered, say what changed or why it will not change. Reviews are
expected to produce commits, not a report.

### 4. Commit atomically, conventionally, with a version bump every time
[atomic 108 / 77 / 44 / 4 · conventional messages 98 / 84 / 43 / 4 · version bump
128 / 79 / 34 / 4]

One logical change per commit, a conventional-commit subject, a body that explains the
reason, and a patch version increment in the same commit. Stage only that change's files.

### 5. Traceability to the ticket or merge request [142 / 56 / 18 / 4]

Link the change to its ticket so merging closes it, assign the reviewer, keep labels
current, and post the outcome as a comment with the commit reference. Screenshots and
pipeline results belong on the ticket, not only in chat.

### 6. A local pipeline is the gate; hosted CI runs the same thing; then watch it
[local 112 / 61 / 36 / 4 · hosted 55 / 43 / 31 / 4 · watch 24 / 19 / 12 / 4]

One committed entry point runs formatting, lint, static analysis, tests and coverage.
Hosted CI runs that same script rather than a parallel definition. After pushing, watch
the pipeline and the review comments, and fix what they report.

### 7. Tests that mean something, coverage that is measured, results that are verifiable
[tests 85 / 55 / 25 / 4 · coverage 100 / 46 / 22 / 4 · evidence 46 / 36 / 27 / 3]

Tests must exercise real behavior, coverage is a measured number with a gate, and claims
come with evidence: a command that was run, a log, a screenshot, a profiling figure.
*If you can make your claim testable, then do.*

## Tier 2 — repeated, with clear conditions

### 8. Ship it: push and publish a release [72 / 47 / 17 / 4]

Finished work is pushed and released publicly, with the release notes naming what was
verified. A release is the normal end of a work session, not a special event.

### 9. Dependencies current and pinned exactly [81 / 58 / 29 / 4]

Check dependencies against the latest stable upstream release, pin exact versions, update
them, and only commit when the project's own gate passes afterwards.

### 10. Documentation: crisp, current, and it points to the details
[crisp 61 / 50 / 26 / 4 · README badges 29 / 24 / 19 / 4 · C4 18 / 18 / 14 / 2 ·
document decisions 30 / 25 / 23 / 4]

A README that states what the thing is, with status badges at the top, guiding to the
other documents for detail. Architecture documented, C4 where it fits. Decisions and
review outcomes written down in the repository. Keep it short: *don't write tons*, *two
sentences per finding*, *this is way too much*.

### 11. Handle failure paths deliberately [67 / 52 / 39 / 4]

Robustness is asked for by name across 39 project paths: handle the error case, the empty
case, the interrupted run; make the tool say what went wrong; do not let a failure pass
silently.

### 12. Delegate to the cheaper capable agent [74 / 46 / 27 / 3]

Use subagents and smaller local models where the task allows it, keep an eye on quota and
cost, and let several agents work in parallel when the work is separable.

## Tier 3 — present, narrower, keep as conditional rules

- **Minimal, scoped changes** [10 / 10 / 7 / 4]: *least changes*, *only this file*,
  *leave the rest alone*. Stated rarely but sharply, usually while correcting an agent
  that had widened the scope.
- **Redaction and separation of private data** [3 / 3 / 2 / 3]: redact sensitive
  information in recordings and demos, invent placeholder names, keep company and
  personal accounts and configuration apart. Rare as a phrase, but it shapes whole
  projects, including this one.

## Conflicts and conditions worth respecting

- **Atomic commits versus one squashed commit.** Local work: many small commits. Company
  merge requests: squash to a single conventional commit with a description of what
  changed. Both appear repeatedly; the boundary is the review process, not the preference.
- **A patch version in every commit versus semantic versioning.** The version is used as a
  build counter, so it carries no semantic meaning. Do not read `0.0.x` as a maturity
  claim.
- **Thorough versus crisp.** The work should be complete; the writing about it should be
  short. When both are asked for in one session, brevity applies to the prose, not the
  scope.
- **Full autonomy versus confirmation.** *Run the commands yourself* and *full auto* sit
  beside *tell me if you understood* and *make a plan first*. The pattern is: plan and
  confirm the direction once, then execute the whole batch without further prompting.

## How to use this as agent instructions

Start a project with: plan first and say what you understood; work the whole batch; commit
atomically with conventional messages and a version bump; run the local pipeline and make
hosted CI run the same script; keep tests meaningful and coverage measured; review your own
result, fix every finding, and report with evidence; keep the README crisp and badged and
the documents current; check dependencies; then push and release. Ask before widening
scope, and keep private data out of anything published.
