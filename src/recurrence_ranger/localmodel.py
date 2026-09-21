"""Shared client for the local model endpoint used by the triage and extraction stages."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT_SECONDS = 300
TRANSPORT_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
CONTEXT_TOKENS = 8192
# Roughly four characters per token, leaving room for the instructions and the answer.
REQUEST_CHARS = 24_000
MINIMUM_ITEM_CHARS = 1_200


class EndpointUnavailable(RuntimeError):
    """The local model could not be reached; the caller must not record a decision."""


def require_loopback(endpoint: str, stage: str) -> None:
    """Refuse any endpoint that could send prompt text off the machine."""
    if not endpoint.startswith("http://127.0.0.1:"):
        raise ValueError(f"{stage} endpoint must use local loopback")


def item_chars(count: int) -> int:
    """Share the request budget between the prompts in one batch.

    A batch that exceeds the context window is silently truncated by the model, which
    then answers for fewer prompts than were sent and forces the caller to split and
    ask again. Sizing the excerpts to the batch avoids that round trip.
    """
    return max(MINIMUM_ITEM_CHARS, REQUEST_CHARS // count)


def generate(payload: dict, endpoint: str) -> Any:
    """Post one request and return the decoded model answer.

    A transport failure is retried and then reported as EndpointUnavailable, because
    labelling a prompt from a failed connection would record the model's silence as a
    decision. Malformed answers are a different problem and stay with the caller.
    """
    body = json.dumps(payload).encode()
    attempt = 0
    while True:
        attempt += 1
        request = urllib.request.Request(
            endpoint, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                answer = json.load(response)
            return json.loads(answer["response"])
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            if attempt == TRANSPORT_ATTEMPTS:
                raise EndpointUnavailable(
                    f"{endpoint} did not answer after {attempt} attempts: {error}"
                ) from error
            time.sleep(BACKOFF_SECONDS * attempt)
