"""End-to-end runs of the shipped commands as separate processes."""

import json
import os
import sqlite3
import subprocess
import sys
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CLAUDE_SESSION = "11111111-2222-3333-4444-555555555555"
CODEX_SESSION = "66666666-7777-8888-9999-aaaaaaaaaaaa"
PROMPT = "add tests and a README with badges"
SECOND_PROMPT = "pin every dependency"


def _line(value):
    return json.dumps(value).encode() + b"\n"


def run(*arguments, cwd, home):
    """Run a module of the installed package the way an operator would."""
    environment = {**os.environ, "HOME": str(home), "PYTHONPATH": str(Path("src").resolve())}
    environment.pop("CLAUDE_CONFIG_DIR", None)
    environment.pop("CODEX_HOME", None)
    completed = subprocess.run(
        [sys.executable, "-m", *arguments],
        cwd=cwd,
        env=environment,
        text=True,
        capture_output=True,
        timeout=180,
    )
    assert completed.returncode == 0, completed.stderr
    return completed


def _last_json(printed):
    """The resumable stages print progress lines before their final summary."""
    return json.loads(printed[printed.index("{\n") :])


def _profiles(home):
    claude = home / ".claude"
    transcript = claude / "projects" / "work-project" / f"{CLAUDE_SESSION}.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(
        _line(
            {
                "type": "user",
                "sessionId": CLAUDE_SESSION,
                "uuid": "u1",
                "timestamp": "2026-09-22T08:00:00Z",
                "cwd": "/work/project",
                "message": {"role": "user", "content": PROMPT},
            }
        )
        + _line(
            {
                "type": "assistant",
                "sessionId": CLAUDE_SESSION,
                "uuid": "a1",
                "timestamp": "2026-09-22T08:00:05Z",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            }
        )
        + _line({"type": "queue-operation", "sessionId": CLAUDE_SESSION})
    )
    (claude / "history.jsonl").write_bytes(
        _line(
            {
                "display": PROMPT,
                "sessionId": CLAUDE_SESSION,
                "project": "/work/project",
                "timestamp": 1790064000000,
            }
        )
    )
    codex = home / ".codex"
    rollout = codex / "sessions" / f"rollout-2026-09-22T09-00-00-{CODEX_SESSION}.jsonl"
    rollout.parent.mkdir(parents=True)
    rollout.write_bytes(
        _line({"type": "session_meta", "payload": {"id": CODEX_SESSION, "cwd": "/work/other"}})
        + _line(
            {
                "type": "response_item",
                "timestamp": "2026-09-22T09:00:01Z",
                "payload": {
                    "type": "message",
                    "id": "m1",
                    "role": "user",
                    "content": [{"type": "input_text", "text": SECOND_PROMPT}],
                },
            }
        )
        + _line(b'{"type": "broken"'.decode() + "\n")
    )
    manifest = home / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sources": [
                    {"label": "Claude", "tool": "claude", "home": str(claude)},
                    {"label": "Codex", "tool": "codex", "home": str(codex)},
                    {"label": "Codex DMO", "tool": "codex", "home": str(home / ".codex-dmo")},
                ],
            }
        )
    )
    return manifest, transcript


def test_capture_to_report_runs_end_to_end(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    repository = Path(__file__).resolve().parent.parent
    manifest, transcript = _profiles(home)
    database = home / "private" / "conversations.sqlite3"
    common = ["recurrence_ranger", "--db", str(database), "--manifest", str(manifest)]

    inventory = json.loads(run(*common, "inventory", cwd=repository, home=home).stdout)
    profiles = {row["label"]: row for row in inventory["sources"]}
    assert profiles["Claude"]["available"] is True
    assert profiles["Codex"]["files"] == 1
    assert profiles["Codex DMO"]["available"] is False

    run(*common, "backfill", cwd=repository, home=home)

    # A second prompt arrives while the collector is not running.
    with transcript.open("ab") as handle:
        handle.write(
            _line(
                {
                    "type": "user",
                    "sessionId": CLAUDE_SESSION,
                    "uuid": "u2",
                    "timestamp": "2026-09-22T08:10:00Z",
                    "cwd": "/work/project",
                    "message": {"role": "user", "content": SECOND_PROMPT},
                }
            )
        )
    run(*common, "scan", cwd=repository, home=home)

    status = json.loads(run(*common, "status", cwd=repository, home=home).stdout)
    assert status["ingestion_watermark"] == 8
    assert status["missing_files"] == 0
    assert status["abandoned_fragments"] == 0
    captured = {row["label"]: row for row in status["sources"]}
    assert captured["Claude"]["records"] == 5
    assert captured["Codex"]["records"] == 3
    assert captured["Claude"]["open_errors"] == 0
    assert PROMPT not in json.dumps(status)

    verified = json.loads(run(*common, "verify", cwd=repository, home=home).stdout)
    assert verified == {"integrity": "ok", "checkpoint_gaps": [], "raw_records": 8}

    backup = home / "private" / "backup.sqlite3"
    run(*common, "backup", str(backup), cwd=repository, home=home)
    restored = json.loads(
        run(*common, "restore-check", str(backup), cwd=repository, home=home).stdout
    )
    assert restored == {"integrity": "ok", "raw_records": 8}

    corpus = home / "private" / "corpus.sqlite3"
    derived = json.loads(
        run("recurrence_ranger.corpus", str(backup), str(corpus), cwd=repository, home=home).stdout
    )
    assert derived["watermark"] == 8
    assert dict(derived["prompts"]) == {"human": 3}
    assert dict(derived["occurrences"])["duplicate"] == 1

    report = json.loads(
        run("recurrence_ranger.report", str(corpus), cwd=repository, home=home).stdout
    )
    assert dict((profile, count) for profile, _, count in report["prompts_by_profile"]) == {
        "Claude": 2,
        "Codex": 1,
    }
    assert "relevance" not in report

    audit = json.loads(
        run("recurrence_ranger.evidence_audit", str(corpus), cwd=repository, home=home).stdout
    )
    assert audit["README_BADGES"]["matching_prompts"] == 1
    assert audit["COVERAGE"]["matching_prompts"] == 0

    with sqlite3.connect(corpus) as connection:
        texts = [row[0] for row in connection.execute("SELECT text FROM prompts ORDER BY id")]
    assert sorted(texts) == sorted([PROMPT, SECOND_PROMPT, SECOND_PROMPT])
    assert database.stat().st_mode & 0o777 == 0o600
    assert corpus.stat().st_mode & 0o777 == 0o600


class _ModelHandler(BaseHTTPRequestHandler):
    """Answer the two model stages the way a local Ollama instance would."""

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        items = json.loads(request["prompt"][request["prompt"].index("\n[") + 1 :])
        if "themes" in request["format"]["properties"]:
            body = {
                "themes": [
                    ["TESTS", "README", "BADGES"] if "README" in item["text"] else ["PIN_VERSIONS"]
                    for item in items
                ]
            }
        else:
            body = {"labels": ["I" for _ in items]}
        payload = json.dumps({"response": json.dumps(body)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        return


@contextmanager
def local_model_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ModelHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/api/generate"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_model_stages_run_end_to_end_against_a_local_server(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    repository = Path(__file__).resolve().parent.parent
    manifest, _ = _profiles(home)
    database = home / "private" / "conversations.sqlite3"
    corpus = home / "private" / "corpus.sqlite3"
    run(
        "recurrence_ranger",
        "--db",
        str(database),
        "--manifest",
        str(manifest),
        "backfill",
        cwd=repository,
        home=home,
    )
    run("recurrence_ranger.corpus", str(database), str(corpus), cwd=repository, home=home)

    with local_model_server() as endpoint:
        triage = _last_json(
            run(
                "recurrence_ranger.classify",
                str(corpus),
                "--endpoint",
                endpoint,
                "--model",
                "test-model",
                "--batch-size",
                "2",
                cwd=repository,
                home=home,
            ).stdout
        )
        assert triage["remaining"] == 0
        assert dict(triage["labels"]) == {"software_instruction": 2}
        flagged = json.loads(
            run("recurrence_ranger.recall", str(corpus), cwd=repository, home=home).stdout
        )
        assert flagged == {"flagged": 0, "rule_version": 1}
        extraction = _last_json(
            run(
                "recurrence_ranger.extract",
                str(corpus),
                "--endpoint",
                endpoint,
                "--model",
                "test-model",
                cwd=repository,
                home=home,
            ).stdout
        )
        assert extraction["remaining"] == 0
        assert dict(extraction["themes"]) == {
            "BADGES": 1,
            "PIN_VERSIONS": 1,
            "README": 1,
            "TESTS": 1,
        }

    report = json.loads(
        run("recurrence_ranger.report", str(corpus), cwd=repository, home=home).stdout
    )
    assert report["relevance_remaining"] == 0
    assert report["relevance_model_errors"] == 0
    assert report["extraction_reviewed"] == 2
    assert [theme["theme"] for theme in report["themes"]] == [
        "BADGES",
        "PIN_VERSIONS",
        "README",
        "TESTS",
    ]
    assert all(theme["prompts"] == 1 for theme in report["themes"])
