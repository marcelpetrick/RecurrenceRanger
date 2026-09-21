import contextlib
import io
import json
import urllib.request

import pytest

from recurrence_ranger import localmodel


def test_only_a_loopback_endpoint_is_accepted():
    localmodel.require_loopback("http://127.0.0.1:11434/api/generate", "triage")
    for endpoint in ("http://example.com/api/generate", "https://127.0.0.1:11434/api/generate"):
        with pytest.raises(ValueError, match="triage endpoint must use local loopback"):
            localmodel.require_loopback(endpoint, "triage")


def test_a_request_carries_json_and_returns_the_decoded_answer(local_model):
    sent = local_model({"labels": ["I"]})
    assert localmodel.generate(
        {"model": "m", "prompt": "p"}, "http://127.0.0.1:1/api/generate"
    ) == {"labels": ["I"]}
    assert sent[0]["payload"] == {"model": "m", "prompt": "p"}
    assert sent[0]["timeout"] == localmodel.TIMEOUT_SECONDS


def test_an_envelope_without_an_answer_is_reported(monkeypatch):
    """A local server can answer 200 with an error payload instead of a completion."""

    def fake_urlopen(request, timeout=None):
        return contextlib.closing(io.BytesIO(json.dumps({"error": "model not found"}).encode()))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(KeyError):
        localmodel.generate({}, "http://127.0.0.1:1/api/generate")


def test_a_transport_failure_is_retried_then_reported(monkeypatch):
    attempts = []
    waits = []

    def failing_urlopen(request, timeout=None):
        attempts.append(request.full_url)
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", failing_urlopen)
    monkeypatch.setattr(localmodel.time, "sleep", waits.append)
    with pytest.raises(localmodel.EndpointUnavailable, match="did not answer after 3 attempts"):
        localmodel.generate({}, "http://127.0.0.1:1/api/generate")
    assert len(attempts) == localmodel.TRANSPORT_ATTEMPTS
    assert waits == [localmodel.BACKOFF_SECONDS, localmodel.BACKOFF_SECONDS * 2]


def test_a_recovered_endpoint_answers_after_one_retry(monkeypatch):
    calls = []

    def flaky_urlopen(request, timeout=None):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise TimeoutError("timed out")
        body = json.dumps({"response": json.dumps({"labels": ["I"]})}).encode()
        return contextlib.closing(io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", flaky_urlopen)
    monkeypatch.setattr(localmodel.time, "sleep", lambda _seconds: None)
    assert localmodel.generate({}, "http://127.0.0.1:1/api/generate") == {"labels": ["I"]}
    assert len(calls) == 2
