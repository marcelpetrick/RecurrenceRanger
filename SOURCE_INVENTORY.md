# Source inventory

Observed on 2026-09-21, before ingestion. Sizes and modification dates are
filesystem observations, not proof of complete conversation coverage. The
machine-readable discovery specification is [sources.json](sources.json).

| Profile | Home | JSONL files | Bytes | File modification dates (UTC) |
| --- | --- | ---: | ---: | --- |
| Claude | `~/.claude` | 455 | 361,672,320 | 2026-08-07 to 2026-09-21 |
| Claude DMO | `~/.claude-dmo` | 106 | 127,803,397 | 2026-09-18 to 2026-09-21 |
| Codex | `~/.codex` | 341 | 1,446,050,664 | 2026-04-10 to 2026-09-21 |
| Codex DMO | `~/.codex-dmo` | 31 | 97,096,928 | 2026-09-03 to 2026-09-21 |

Claude files were found below `projects/`; Codex files below `sessions/`.
Each profile also has a `history.jsonl` (four additional files, about 2.8 MB)
with prompt-oriented records. The collector includes these as supplemental
history. The Codex enumerator also checks `archived_sessions/`; none were
present in this inventory. The two DMO homes are referenced by shell launchers in
`~/.zshrc`. Symlinked JSONL files were not observed in the four homes.

Representative top-level Claude record types include `user`, `assistant`,
`attachment`, `system`, `queue-operation`, and metadata records. Codex has
`session_meta`, `response_item`, `event_msg`, `turn_context`, and additional
event types. Codex message content occurs inside `response_item` payloads;
Claude message content occurs inside `message`. This is a schema sample, not
an exhaustive schema claim. Preserve all complete raw JSONL records even when
no normalizer understands their type.

The launcher check and file inventory did not read every record or verify
whether older history was deleted. Other configured homes, copied archives,
and history indexes need continued discovery. Codex also has
`thread_history_1.sqlite`, a projection with `thread_items` and `thread_turns`;
the primary capture source is rollout JSONL. Source labels need continued
validation; records are never assigned human authorship solely from a
transport `user` role.
