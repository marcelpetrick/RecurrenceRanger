import json
import sqlite3

from recurrence_ranger.capture import Collector
from recurrence_ranger.corpus import Candidate, _decision, derive
from recurrence_ranger.sources import Source
from recurrence_ranger.store import Store


def _line(value):
    return json.dumps(value).encode() + b"\n"


def test_corpus_excludes_tool_results_and_reconciles_history(tmp_path):
    home = tmp_path / "claude"
    transcript = home / "projects" / "one.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(
        _line(
            {
                "type": "user",
                "sessionId": "s",
                "timestamp": "2026-09-21T00:00:00Z",
                "message": {"role": "user", "content": "add tests"},
            }
        )
        + _line(
            {
                "type": "user",
                "sessionId": "s",
                "timestamp": "2026-09-21T00:00:01Z",
                "toolUseResult": {"stdout": "secret"},
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "secret"}],
                },
            }
        )
        + _line(
            {
                "type": "user",
                "sessionId": "s",
                "timestamp": "2026-09-21T00:02:00Z",
                "message": {"role": "user", "content": "add tests"},
            }
        )
    )
    (home / "history.jsonl").write_bytes(
        _line({"sessionId": "s", "timestamp": 1789948800000, "display": "add tests"})
    )
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("claude", "Claude", home, "test")])
    store.close()
    output_path = tmp_path / "corpus.sqlite3"
    summary = derive(source_path, output_path)
    assert summary["watermark"] == 4
    with sqlite3.connect(output_path) as db:
        assert db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 2
        decisions = db.execute(
            "SELECT decision,COUNT(*) FROM occurrences GROUP BY decision"
        ).fetchall()
        assert decisions == [
            ("duplicate", 1),
            ("excluded", 1),
            ("human", 2),
        ]
        assert db.execute("SELECT COUNT(*) FROM prompts WHERE text='secret'").fetchone()[0] == 0
    assert output_path.stat().st_mode & 0o777 == 0o600


def test_generated_context_is_not_treated_as_human_input():
    claude = Candidate(1, "Claude", "claude", "s", "user", None, None, "run tests")
    raw = _line({"promptSource": "sdk", "message": {"content": "run tests"}})
    assert _decision(claude, raw) == ("excluded", "generated system or SDK prompt")
    codex = Candidate(
        2, "Codex", "codex", "s", "message", None, None, "# AGENTS.md instructions for /repo"
    )
    assert _decision(codex, b"{}") == ("excluded", "generated context or notification")
