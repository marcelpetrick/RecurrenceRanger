"""Shared client for the local model endpoint used by the triage and extraction stages."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_SECONDS = 300


def require_loopback(endpoint: str, stage: str) -> None:
    """Refuse any endpoint that could send prompt text off the machine."""
    if not endpoint.startswith("http://127.0.0.1:"):
        raise ValueError(f"{stage} endpoint must use local loopback")


def generate(payload: dict, endpoint: str) -> Any:
    """Post one request and return the decoded model answer."""
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        answer = json.load(response)
    return json.loads(answer["response"])
