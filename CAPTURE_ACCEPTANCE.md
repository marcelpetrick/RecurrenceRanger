# Capture acceptance snapshot

Date: 2026-09-21. This report uses the private online backup at
`~/.local/share/recurrence-ranger/acceptance-backup.sqlite3` and its fixed
raw-record watermark 385404. No transcript text is included here.

| Profile | Files | Raw records | Complete bytes | Observed bytes |
| --- | ---: | ---: | ---: | ---: |
| Claude | 457 | 130,973 | 363,177,049 | 363,180,786 |
| Claude DMO | 109 | 31,696 | 129,036,840 | 129,036,840 |
| Codex | 343 | 199,563 | 1,449,257,557 | 1,449,257,557 |
| Codex DMO | 32 | 23,172 | 97,136,962 | 97,136,962 |

All four profiles were available. The 3,737-byte difference for Claude was one
active incomplete JSONL tail; it remained pending rather than being counted as
a complete record. There were no open capture errors, missing files, or
abandoned fragments at this watermark. The backup occupied 2,423,013,376 bytes.

`verify` reported `integrity: ok`, zero checkpoint gaps, and 385,404 raw
records. `restore-check` queried the online backup and found the same record
count. The enabled user service was running with a ten-second poll interval.
For 149 recent normalized messages observed after its latest start, the median
event-to-capture interval was 5.7 seconds and the largest was 17.2 seconds.
These samples measure current operation, not an upper bound under every load.

The raw database is the source of truth. Normalization remains best effort,
and `messages.role='user'` includes tool results and generated context. The
derived corpus stage must classify authorship before counting prompts. In-place
rewrites that do not change sampled bytes may escape detection, and logs deleted
before first observation cannot be recovered. Attachment bytes outside JSONL
records are not copied. The capture service continues polling while analysis
uses this fixed backup.
