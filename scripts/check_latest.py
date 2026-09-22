"""Report pinned development tools that are behind their latest stable release.

This only reports; it never edits a pin. Updating is a change like any other here: it
needs its own commit, its own version bump and a passing pipeline.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

import tool_versions

TIMEOUT_SECONDS = 30


def outdated(pinned: dict[str, str], latest: Callable[[str], str | None]) -> list[str]:
    """Report one line per pin that is not the newest stable release."""
    behind = []
    for name, pin in sorted(pinned.items()):
        newest = latest(name)
        if newest is None:
            behind.append(f"{name}: pinned {pin}, latest release unknown")
        elif newest != pin:
            behind.append(f"{name}: pinned {pin}, latest {newest}")
    return behind


def pypi_latest(name: str) -> str | None:
    """Return the newest release of a project, or None when it cannot be read."""
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{name}/json", timeout=TIMEOUT_SECONDS
        ) as response:
            release = json.load(response)
    except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError):
        return None
    version = release.get("info", {}).get("version")
    if not isinstance(version, str):
        return None
    files = release.get("releases", {}).get(version) or []
    if any(entry.get("yanked") for entry in files):
        return None
    return version


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check-latest", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)
    try:
        pinned = tool_versions.pinned(tomllib.loads(args.project.read_text(encoding="utf-8")))
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"check-latest: cannot read pins from {args.project}: {error}", file=sys.stderr)
        return 1
    behind = outdated(pinned, pypi_latest)
    if behind:
        for line in behind:
            print(f"check-latest: {line}", file=sys.stderr)
        print(
            "check-latest: run the dependency update workflow, one commit per change",
            file=sys.stderr,
        )
        return 1
    print("check-latest: " + ", ".join(f"{name}=={pin}" for name, pin in sorted(pinned.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
