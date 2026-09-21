"""Best-effort message views derived from retained raw JSONL records."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

PARSER_VERSION = 1
_ROLLOUT_ID = re.compile(r"([0-9a-f]{8}-[0-9a-f-]{27,})\.jsonl$")


@dataclass(frozen=True)
class Block:
    kind: str
    text: str | None
    data_json: str | None


@dataclass(frozen=True)
class Message:
    session: str
    source_message_id: str | None
    role: str
    kind: str
    timestamp: str | None
    project: str | None
    text: str | None
    parent_id: str | None
    blocks: tuple[Block, ...]


def _blocks(content: object) -> tuple[Block, ...]:
    if isinstance(content, str):
        return (Block("text", content, None),)
    if not isinstance(content, list):
        return ()
    blocks = []
    for item in content:
        if isinstance(item, str):
            blocks.append(Block("text", item, None))
        elif isinstance(item, dict):
            kind = str(item.get("type", "structured"))
            text = item.get("text")
            if not isinstance(text, str):
                text = None
            encoded = json.dumps(item, ensure_ascii=False)
            blocks.append(Block(kind, text, encoded if len(encoded) <= 16_384 else None))
    return tuple(blocks)


def _codex_session(path: Path) -> str:
    found = _ROLLOUT_ID.search(path.name)
    return found.group(1) if found else str(path)


def parse_record(tool: str, path: Path, data: bytes) -> tuple[str, str | None, Message | None]:
    """Return parse status, error, and optional message without discarding source bytes."""
    try:
        record = json.loads(data)
    except (UnicodeError, json.JSONDecodeError) as error:
        return "malformed", str(error)[:500], None
    if not isinstance(record, dict):
        return "unsupported", "JSON root is not an object", None
    kind = record.get("type")
    if not isinstance(kind, str):
        return "unsupported", "missing record type", None
    if tool == "claude":
        if kind not in {"user", "assistant"}:
            return "parsed", None, None
        inner = record.get("message")
        if not isinstance(inner, dict):
            return "unsupported", "message field is not an object", None
        blocks = _blocks(inner.get("content"))
        session = record.get("sessionId") or path.stem
        return "parsed", None, Message(
            str(session), str(record["uuid"]) if record.get("uuid") else None,
            str(inner.get("role") or kind), kind,
            str(record["timestamp"]) if record.get("timestamp") else None,
            str(record["cwd"]) if record.get("cwd") else None,
            "\n".join(block.text for block in blocks if block.text is not None) or None,
            str(record["parentUuid"]) if record.get("parentUuid") else None, blocks,
        )
    if tool == "codex":
        if kind != "response_item":
            return "parsed", None, None
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            return "parsed", None, None
        blocks = _blocks(payload.get("content"))
        return "parsed", None, Message(
            _codex_session(path), str(payload["id"]) if payload.get("id") else None,
            str(payload.get("role") or "unknown"), "message",
            str(record["timestamp"]) if record.get("timestamp") else None,
            None, "\n".join(block.text for block in blocks if block.text is not None) or None,
            None, blocks,
        )
    return "unsupported", f"unknown tool: {tool}", None
