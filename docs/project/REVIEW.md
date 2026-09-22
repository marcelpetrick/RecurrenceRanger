# Planning review

Date: 2026-09-21

Scope: review `PLAN.md` and `IMPLEMENTATION_OPTIONS.md` against Marcel's requested
sequence: document the plan, compare two implementations, commit each step
locally, then wait for further input. The first future implementation milestone
is historical and continuous database capture; guideline analysis follows later.

## Findings and fixes

| Finding | Resolution |
| --- | --- |
| The later corpus stage still instructed reading source logs, undermining database reuse after logs expire. | Derive analysis inputs from stored records with an ingestion watermark and parser version. |
| Backfill was described as preceding live capture, allowing a large archive to delay collection of active logs. | Require interleaved bounded historical and live ingestion, including startup and a starvation check for both options. |
| The complete-record model left incomplete tails, unknown schemas, and storage failures underspecified. | Preserve raw unknown records and pending fragments; require checkpoint safety and visible backlog on storage failures, with corresponding verification cases. |

Also clarified that reconciliation cannot recover bytes deleted before they were
observed. Coverage reports must distinguish captured data, pending fragments,
known failures, and retention limits.

## Verification and disposition

- Checked both documents for consistency of scope, sequencing, database reuse,
  capture behavior, and completion criteria after the fixes.
- Checked the Markdown diff for whitespace errors and relative document links
  for existing targets.
- No code changed, so runtime tests were not applicable. Capture behavior remains
  a proposed requirement, not verified implementation behavior.
- No remaining blocking findings in these planning documents. Actual log schemas,
  corpus size, and performance remain unverified until implementation work.

Planning and the two-option comparison are complete. No collector was built or
started, no conversation corpus was scanned, and no service was installed.
The next implementation step awaits Marcel's direction.
