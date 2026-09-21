import contextlib
import io
import json
import urllib.request

import pytest


@pytest.fixture
def local_model(monkeypatch):
    """Answer local Ollama generate calls with canned responses and record what was sent."""
    sent = []

    def install(*responses):
        answers = list(responses)

        def fake_urlopen(request, timeout=None):
            sent.append(
                {
                    "url": request.full_url,
                    "payload": json.loads(request.data),
                    "timeout": timeout,
                }
            )
            body = answers.pop(0) if len(answers) > 1 else answers[0]
            encoded = json.dumps({"response": json.dumps(body)}).encode()
            return contextlib.closing(io.BytesIO(encoded))

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return sent

    return install
