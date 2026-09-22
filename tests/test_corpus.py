import json
import sqlite3

import pytest

from recurrence_ranger import derived
from recurrence_ranger.capture import Collector
from recurrence_ranger.corpus import Candidate, _decision, derive
from recurrence_ranger.corpus import main as corpus_main
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
    subagent = Candidate(
        3, "Codex", "codex", "child", "message", None, None, "review the branch", "subagent"
    )
    assert _decision(subagent, b"{}") == ("excluded", "Codex subagent task")
    probe = Candidate(4, "Codex", "codex", "probe", "message", None, None, "1+1", "exec")
    assert _decision(probe, b"{}") == ("excluded", "automated Codex exec session")


def test_codex_session_metadata_excludes_subagent_prompts(tmp_path):
    session = "12345678-1234-1234-1234-123456789012"
    home = tmp_path / "codex"
    path = home / "sessions" / f"rollout-2026-09-21T00-00-00-{session}.jsonl"
    path.parent.mkdir(parents=True)
    path.write_bytes(
        _line(
            {"type": "session_meta", "payload": {"id": session, "source": {"subagent": "review"}}}
        )
        + _line(
            {
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "review the branch"}],
                },
            }
        )
    )
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("codex", "Codex", home, "test")])
    store.close()
    output_path = tmp_path / "corpus.sqlite3"
    derive(source_path, output_path)
    with sqlite3.connect(output_path) as db:
        assert db.execute("SELECT COUNT(*) FROM prompts").fetchone()[0] == 0
        assert db.execute("SELECT decision,reason FROM occurrences").fetchall() == [
            ("excluded", "Codex subagent task")
        ]


def test_uncertain_and_generated_records_are_kept_apart():
    def claude(record, text="run tests", kind="user"):
        return _decision(
            Candidate(1, "Claude", "claude", "s", kind, None, None, text), _line(record)
        )

    assert claude({"message": {"content": "run tests"}}) == (
        "human",
        "prompt-oriented source record",
    )
    assert _decision(
        Candidate(1, "Claude", "claude", "s", "user", None, None, "run tests"), b"{broken"
    ) == ("uncertain", "raw record cannot be parsed")
    assert claude({"toolUseResult": {"stdout": "x"}}) == ("excluded", "tool result")
    assert claude({"isCompactSummary": True}) == ("excluded", "generated compaction summary")
    assert claude({"isVisibleInTranscriptOnly": True}) == (
        "excluded",
        "generated compaction summary",
    )
    assert claude({"isMeta": True}) == ("excluded", "generated metadata")
    assert claude({"isSidechain": True}) == ("excluded", "subagent sidechain")
    assert claude({"message": {"content": [{"type": "image", "source": {}}]}}) == (
        "uncertain",
        "mixed or nontext content",
    )
    assert claude({"message": {"content": "  "}}, text="  ") == (
        "uncertain",
        "no text; inspect raw content or attachment",
    )
    assert claude({}, text=None) == ("uncertain", "no text; inspect raw content or attachment")
    assert claude({}, text="<command-message>compacting</command-message>") == (
        "uncertain",
        "command expansion or attachment",
    )
    assert claude({}, text="[Image: screenshot.png]") == (
        "uncertain",
        "command expansion or attachment",
    )


def test_prompts_without_comparable_timestamps_stay_separate(tmp_path):
    home = tmp_path / "claude"
    transcript = home / "projects" / "one.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(
        _line({"type": "user", "sessionId": "s", "message": {"role": "user", "content": "add CI"}})
    )
    (home / "history.jsonl").write_bytes(
        _line({"sessionId": "s", "timestamp": "not a timestamp", "display": "add CI"})
    )
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("claude", "Claude", home, "test")])
    store.close()
    output_path = tmp_path / "corpus.sqlite3"
    assert derive(source_path, output_path)["prompts"] == [("human", 2)]


def test_derivation_rejects_a_shared_path_and_a_negative_watermark(tmp_path):
    path = tmp_path / "capture.sqlite3"
    Store(path).close()
    with pytest.raises(ValueError, match="must differ"):
        derive(path, path)
    with pytest.raises(ValueError, match="watermark must be nonnegative"):
        derive(path, tmp_path / "corpus.sqlite3", -1)


def test_an_explicit_watermark_freezes_the_input(tmp_path):
    home = tmp_path / "claude"
    transcript = home / "projects" / "one.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(
        _line({"type": "user", "sessionId": "s", "message": {"role": "user", "content": "first"}})
        + _line(
            {"type": "user", "sessionId": "s", "message": {"role": "user", "content": "second"}}
        )
    )
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("claude", "Claude", home, "test")])
    store.close()
    summary = derive(source_path, tmp_path / "corpus.sqlite3", 1)
    assert summary["watermark"] == 1
    assert summary["prompts"] == [("human", 1)]


def test_unreadable_codex_headers_do_not_exclude_prompts(tmp_path):
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    message = _line(
        {
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "add tests"}],
            },
        }
    )
    uuid = "12345678-1234-1234-1234-12345678901"
    (sessions / f"rollout-a-{uuid}1.jsonl").write_bytes(b"not json\n" + message)
    (sessions / f"rollout-b-{uuid}2.jsonl").write_bytes(
        _line({"type": "session_meta", "payload": {"cwd": "/repo"}}) + message
    )
    (sessions / f"rollout-c-{uuid}3.jsonl").write_bytes(
        _line({"type": "event_msg", "payload": {"type": "token_count"}}) + message
    )
    (sessions / f"rollout-d-{uuid}4.jsonl").write_bytes(
        _line({"type": "session_meta", "payload": {"id": f"{uuid}4", "source": "exec"}}) + message
    )
    (sessions / f"rollout-e-{uuid}5.jsonl").write_bytes(
        _line({"type": "session_meta", "payload": {"id": f"{uuid}5", "source": {"cli": {}}}})
        + message
    )
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("codex", "Codex", home, "test")])
    store.close()
    output_path = tmp_path / "corpus.sqlite3"
    assert derive(source_path, output_path)["prompts"] == [("human", 4)]
    with sqlite3.connect(output_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM occurrences WHERE reason='automated Codex exec session'"
        ).fetchone() == (1,)


def test_corpus_command_prints_the_summary(tmp_path, capsys):
    home = tmp_path / "claude"
    transcript = home / "projects" / "one.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(
        _line({"type": "user", "sessionId": "s", "message": {"role": "user", "content": "add CI"}})
    )
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("claude", "Claude", home, "test")])
    store.close()
    output_path = tmp_path / "corpus.sqlite3"
    assert corpus_main([str(source_path), str(output_path), "--watermark", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["watermark"] == 1


def _capture_with(tmp_path, prompts):
    home = tmp_path / "claude"
    transcript = home / "projects" / "one.jsonl"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_bytes(
        b"".join(
            _line(
                {
                    "type": "user",
                    "sessionId": "s",
                    "uuid": f"u{number}",
                    "timestamp": f"2026-09-22T10:0{number}:00Z",
                    "message": {"role": "user", "content": text},
                }
            )
            for number, text in enumerate(prompts, start=1)
        )
    )
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("claude", "Claude", home, "test")])
    store.close()
    return source_path, transcript


def test_model_decisions_are_carried_across_a_rederivation(tmp_path):
    source_path, transcript = _capture_with(tmp_path, ["add tests", "write the README"])
    corpus_path = tmp_path / "corpus.sqlite3"
    derive(source_path, corpus_path)
    with sqlite3.connect(corpus_path) as db:
        db.execute(derived.RELEVANCE)
        db.execute(derived.EXTRACTION_REVIEWS)
        db.execute(derived.GUIDELINE_OCCURRENCES)
        for prompt_id, text in db.execute("SELECT id,text FROM prompts ORDER BY id").fetchall():
            db.execute(
                "INSERT INTO relevance VALUES (?,'software_instruction','m',2,'earlier',0,NULL)",
                (prompt_id,),
            )
            # Extraction had only reached the first prompt, as in a partially finished run.
            if "tests" in text:
                db.execute(
                    "INSERT INTO extraction_reviews VALUES (?,'m',1,'earlier',NULL)", (prompt_id,)
                )
                db.execute("INSERT INTO guideline_occurrences VALUES (?,'TESTS')", (prompt_id,))

    # A later session appends one more prompt, so the corpus is derived again.
    with transcript.open("ab") as handle:
        for number, later in enumerate(("pin the dependencies", "add the badges"), start=3):
            handle.write(
                _line(
                    {
                        "type": "user",
                        "sessionId": "s",
                        "uuid": f"u{number}",
                        "timestamp": f"2026-09-22T10:3{number}:00Z",
                        "message": {"role": "user", "content": later},
                    }
                )
            )
    store = Store(source_path)
    Collector(store).scan_once([Source("claude", "Claude", tmp_path / "claude", "test")])
    store.close()

    summary = derive(source_path, corpus_path, carry_labels=True)
    assert summary["carried_decisions"] == 2
    with sqlite3.connect(corpus_path) as db:
        assert db.execute(
            """SELECT p.text,r.label,r.classified_at FROM prompts p
               JOIN relevance r ON r.prompt_id=p.id ORDER BY p.text"""
        ).fetchall() == [
            ("add tests", "software_instruction", "earlier"),
            ("write the README", "software_instruction", "earlier"),
        ]
        assert db.execute(
            """SELECT p.text,g.theme FROM prompts p
               JOIN guideline_occurrences g ON g.prompt_id=p.id ORDER BY p.text"""
        ).fetchall() == [("add tests", "TESTS")]
        # The prompt that was labelled but not yet reviewed stays waiting for extraction.
        assert db.execute(
            """SELECT COUNT(*) FROM prompts p JOIN relevance r ON r.prompt_id=p.id
               LEFT JOIN extraction_reviews x ON x.prompt_id=p.id WHERE x.prompt_id IS NULL"""
        ).fetchone() == (1,)
        # The new prompts have no decision yet, so the next model run picks them up.
        assert db.execute(
            """SELECT COUNT(*) FROM prompts p LEFT JOIN relevance r ON r.prompt_id=p.id
               WHERE r.prompt_id IS NULL"""
        ).fetchone() == (2,)


def test_decisions_are_dropped_by_default_and_when_the_text_changed(tmp_path):
    source_path, _ = _capture_with(tmp_path, ["add tests"])
    corpus_path = tmp_path / "corpus.sqlite3"
    derive(source_path, corpus_path)
    with sqlite3.connect(corpus_path) as db:
        db.execute(derived.RELEVANCE)
        db.execute("INSERT INTO relevance VALUES (1,'software_instruction','m',2,'earlier',0,NULL)")
    assert derive(source_path, corpus_path)["carried_decisions"] == 0
    with sqlite3.connect(corpus_path) as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "relevance" not in tables

    other_source, _ = _capture_with(tmp_path / "second", ["add integration tests"])
    with sqlite3.connect(corpus_path) as db:
        db.execute(derived.RELEVANCE)
        db.execute("INSERT INTO relevance VALUES (1,'software_instruction','m',2,'earlier',0,NULL)")
    assert derive(other_source, corpus_path, carry_labels=True)["carried_decisions"] == 0


def test_the_command_can_carry_labels(tmp_path, capsys):
    source_path, _ = _capture_with(tmp_path, ["add tests"])
    corpus_path = tmp_path / "corpus.sqlite3"
    assert corpus_main([str(source_path), str(corpus_path), "--carry-labels"]) == 0
    assert json.loads(capsys.readouterr().out)["carried_decisions"] == 0


def test_a_corpus_without_extracted_themes_still_carries_its_labels(tmp_path):
    source_path, _ = _capture_with(tmp_path, ["add tests"])
    corpus_path = tmp_path / "corpus.sqlite3"
    derive(source_path, corpus_path)
    with sqlite3.connect(corpus_path) as db:
        db.execute(derived.RELEVANCE)
        db.execute(derived.EXTRACTION_REVIEWS)
        db.execute("INSERT INTO relevance VALUES (1,'software_other','m',2,'earlier',0,NULL)")
        db.execute("INSERT INTO extraction_reviews VALUES (1,'m',1,'earlier','no themes')")
    assert derive(source_path, corpus_path, carry_labels=True)["carried_decisions"] == 1
    with sqlite3.connect(corpus_path) as db:
        assert db.execute("SELECT label FROM relevance").fetchall() == [("software_other",)]
        assert db.execute("SELECT note FROM extraction_reviews").fetchall() == [("no themes",)]
        assert db.execute("SELECT COUNT(*) FROM guideline_occurrences").fetchone() == (0,)


def test_a_failed_rederivation_keeps_the_earlier_model_decisions(tmp_path, monkeypatch):
    source_path, _ = _capture_with(tmp_path, ["add tests"])
    corpus_path = tmp_path / "corpus.sqlite3"
    derive(source_path, corpus_path)
    with sqlite3.connect(corpus_path) as db:
        db.execute(derived.RELEVANCE)
        db.execute("INSERT INTO relevance VALUES (1,'software_instruction','m',2,'earlier',0,NULL)")

    def fail(*_args):
        raise sqlite3.IntegrityError("interrupted")

    monkeypatch.setattr("recurrence_ranger.corpus._carry", fail)
    with pytest.raises(sqlite3.IntegrityError, match="interrupted"):
        derive(source_path, corpus_path, carry_labels=True)
    with sqlite3.connect(corpus_path) as db:
        assert db.execute("SELECT prompt_id,label FROM relevance").fetchall() == [
            (1, "software_instruction")
        ]


def test_a_prompt_repeated_in_one_session_carries_one_set_of_decisions(tmp_path):
    source_path, _ = _capture_with(tmp_path, ["add tests", "add tests"])
    corpus_path = tmp_path / "corpus.sqlite3"
    derive(source_path, corpus_path)
    with sqlite3.connect(corpus_path) as db:
        for statement in derived.MODEL_TABLES:
            db.execute(statement)
        for prompt_id, label in ((1, "software_instruction"), (2, "uncertain")):
            db.execute(
                "INSERT INTO relevance VALUES (?,?,'m',2,'earlier',0,NULL)", (prompt_id, label)
            )
            db.execute(
                "INSERT INTO extraction_reviews VALUES (?,'m',1,'earlier',NULL)", (prompt_id,)
            )
        # Both earlier prompts carry the same theme, which used to be inserted twice.
        db.execute("INSERT INTO guideline_occurrences VALUES (1,'TESTS')")
        db.execute("INSERT INTO guideline_occurrences VALUES (2,'TESTS')")
        db.execute("INSERT INTO guideline_occurrences VALUES (2,'README')")

    assert derive(source_path, corpus_path, carry_labels=True)["carried_decisions"] == 2
    with sqlite3.connect(corpus_path) as db:
        assert db.execute("SELECT label FROM relevance ORDER BY prompt_id").fetchall() == [
            ("software_instruction",),
            ("software_instruction",),
        ]
        assert db.execute(
            "SELECT prompt_id,theme FROM guideline_occurrences ORDER BY prompt_id"
        ).fetchall() == [(1, "TESTS"), (2, "TESTS")]


def test_a_codex_header_nested_too_deeply_does_not_stop_the_derivation(tmp_path):
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    message = _line(
        {
            "type": "response_item",
            "payload": {"type": "message", "role": "user", "content": "add tests"},
        }
    )
    deep = b"[" * 1_000_000 + b"]" * 1_000_000 + b"\n"
    (sessions / "rollout-a-12345678-1234-1234-1234-123456789012.jsonl").write_bytes(deep + message)
    source_path = tmp_path / "capture.sqlite3"
    store = Store(source_path)
    Collector(store).scan_once([Source("codex", "Codex", home, "test")])
    store.close()
    assert derive(source_path, tmp_path / "corpus.sqlite3")["prompts"] == [("human", 1)]
