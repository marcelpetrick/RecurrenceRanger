import json
from pathlib import Path

from recurrence_ranger.normalize import codex_session_project, parse_record

CLAUDE = Path("/home/user/.claude/projects/repo/session.jsonl")
ROLLOUT = Path("rollout-2026-09-21T00-00-00-12345678-1234-1234-1234-123456789012.jsonl")
HISTORY = Path("/home/user/.claude/history.jsonl")


def _line(value):
    return json.dumps(value).encode()


def test_malformed_and_unsupported_records_keep_their_bytes():
    status, error, message = parse_record("claude", CLAUDE, b"{not json")
    assert (status, message) == ("malformed", None)
    assert error
    assert parse_record("claude", CLAUDE, b"[1,2]") == (
        "unsupported",
        "JSON root is not an object",
        None,
    )
    assert parse_record("claude", CLAUDE, _line({"sessionId": "s"})) == (
        "unsupported",
        "missing record type",
        None,
    )
    assert parse_record("claude", CLAUDE, _line({"type": "user", "message": "text"})) == (
        "unsupported",
        "message field is not an object",
        None,
    )
    assert parse_record("nushell", CLAUDE, _line({"type": "user"})) == (
        "unsupported",
        "unknown tool: nushell",
        None,
    )


def test_claude_metadata_records_parse_without_a_message():
    assert parse_record("claude", CLAUDE, _line({"type": "queue-operation"})) == (
        "parsed",
        None,
        None,
    )


def test_claude_user_record_keeps_identifiers_and_mixed_blocks():
    status, error, message = parse_record(
        "claude",
        CLAUDE,
        _line(
            {
                "type": "user",
                "sessionId": "session-1",
                "uuid": "uuid-1",
                "parentUuid": "uuid-0",
                "timestamp": "2026-09-21T10:00:00Z",
                "cwd": "/repo",
                "message": {
                    "role": "user",
                    "content": [
                        "plain string block",
                        {"type": "text", "text": "add tests"},
                        {"type": "image", "source": {"data": "..."}},
                        42,
                    ],
                },
            }
        ),
    )
    assert (status, error) == ("parsed", None)
    assert message.session == "session-1"
    assert message.source_message_id == "uuid-1"
    assert message.parent_id == "uuid-0"
    assert message.project == "/repo"
    assert message.timestamp == "2026-09-21T10:00:00Z"
    assert message.text == "plain string block\nadd tests"
    assert [block.kind for block in message.blocks] == ["text", "text", "image"]
    assert message.blocks[2].text is None
    assert json.loads(message.blocks[2].data_json)["type"] == "image"


def test_an_oversized_block_keeps_its_text_without_the_encoded_copy():
    _, _, message = parse_record(
        "claude",
        CLAUDE,
        _line(
            {
                "type": "assistant",
                "sessionId": "s",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "x" * 20000}],
                },
            }
        ),
    )
    assert message.blocks[0].data_json is None
    assert len(message.blocks[0].text) == 20000
    assert message.source_message_id is None
    assert message.timestamp is None


def test_a_claude_record_without_content_has_no_text():
    _, _, message = parse_record(
        "claude",
        CLAUDE,
        _line({"type": "user", "message": {"role": "user", "content": {"unexpected": True}}}),
    )
    assert message.session == "session"
    assert message.text is None
    assert message.blocks == ()


def test_history_entries_use_each_tool_field():
    _, _, claude = parse_record(
        "claude", HISTORY, _line({"display": "add tests", "sessionId": "s", "timestamp": 1})
    )
    assert (claude.kind, claude.role, claude.text) == ("history", "user", "add tests")
    assert claude.timestamp == "1"
    _, _, codex = parse_record(
        "codex", HISTORY, _line({"text": "add CI", "session_id": "c", "ts": 2, "project": "/repo"})
    )
    assert (codex.session, codex.text, codex.project) == ("c", "add CI", "/repo")
    assert parse_record("claude", HISTORY, _line({"sessionId": "s"})) == (
        "unsupported",
        "history entry has no text",
        None,
    )


def test_a_history_entry_without_a_session_is_marked_unknown():
    _, _, message = parse_record("claude", HISTORY, _line({"display": "add tests"}))
    assert (message.session, message.timestamp, message.project) == ("unknown", None, None)


def test_codex_events_and_response_items():
    _, _, user_event = parse_record(
        "codex",
        ROLLOUT,
        _line({"type": "event_msg", "payload": {"type": "user_message", "message": "add tests"}}),
    )
    assert (user_event.role, user_event.kind) == ("user", "user_message")
    assert user_event.session == "12345678-1234-1234-1234-123456789012"
    _, _, agent_event = parse_record(
        "codex",
        ROLLOUT,
        _line({"type": "event_msg", "payload": {"type": "agent_message", "message": "done"}}),
    )
    assert agent_event.role == "assistant"
    assert parse_record(
        "codex", ROLLOUT, _line({"type": "event_msg", "payload": {"type": "token_count"}})
    ) == ("parsed", None, None)
    assert parse_record(
        "codex",
        ROLLOUT,
        _line({"type": "event_msg", "payload": {"type": "user_message", "message": [1]}}),
    ) == ("parsed", None, None)
    assert parse_record("codex", ROLLOUT, _line({"type": "turn_context"})) == ("parsed", None, None)
    assert parse_record(
        "codex", ROLLOUT, _line({"type": "response_item", "payload": {"type": "reasoning"}})
    ) == ("parsed", None, None)
    _, _, item = parse_record(
        "codex",
        ROLLOUT,
        _line(
            {
                "type": "response_item",
                "timestamp": "2026-09-21T11:00:00Z",
                "payload": {
                    "type": "message",
                    "id": "msg-1",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "add CI"}],
                },
            }
        ),
    )
    assert (item.source_message_id, item.role, item.text) == ("msg-1", "user", "add CI")
    _, _, unnamed = parse_record(
        "codex",
        ROLLOUT,
        _line({"type": "response_item", "payload": {"type": "message", "content": "hi"}}),
    )
    assert (unnamed.role, unnamed.source_message_id) == ("unknown", None)


def test_an_unnamed_rollout_file_falls_back_to_its_path():
    path = Path("/tmp/sessions/other.jsonl")
    _, _, message = parse_record(
        "codex",
        path,
        _line({"type": "event_msg", "payload": {"type": "user_message", "message": "hi"}}),
    )
    assert message.session == str(path)


def test_session_project_is_read_only_from_a_rollout_header():
    assert codex_session_project(ROLLOUT, b"{broken") is None
    assert codex_session_project(ROLLOUT, b"[]") is None
    assert codex_session_project(ROLLOUT, _line({"type": "event_msg"})) is None
    assert codex_session_project(ROLLOUT, _line({"type": "session_meta", "payload": None})) is None
    assert (
        codex_session_project(ROLLOUT, _line({"type": "session_meta", "payload": {"id": "x"}}))
        is None
    )
    assert codex_session_project(
        ROLLOUT, _line({"type": "session_meta", "payload": {"id": "x", "cwd": "/repo"}})
    ) == ("12345678-1234-1234-1234-123456789012", "/repo")


# Far deeper than any interpreter stack allows, so decoding always overflows.
TOO_DEEP = b'{"type":"user","message":' + b"[" * 1_000_000 + b"]" * 1_000_000 + b"}"


def test_a_record_nested_too_deeply_is_malformed_not_fatal():
    assert parse_record("claude", CLAUDE, TOO_DEEP) == (
        "malformed",
        "record nests too deeply to decode",
        None,
    )
    assert codex_session_project(ROLLOUT, TOO_DEEP) is None
