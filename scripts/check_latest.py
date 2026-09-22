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


def compare(
    pinned: dict[str, str], latest: Callable[[str], str | None]
) -> tuple[list[str], list[str]]:
    """Return the pins that are behind, and the pins whose latest release could not be read.

    The two are kept apart on purpose: an unreachable index says nothing about the pin, and a
    check that fails for both teaches everyone to ignore it.
    """
    behind, unknown = [], []
    for name, pin in sorted(pinned.items()):
        newest = latest(name)
        if newest is None:
            unknown.append(f"{name}: pinned {pin}, latest release could not be read")
        elif newest != pin:
            behind.append(f"{name}: pinned {pin}, latest {newest}")
    return behind, unknown


def pypi_latest(name: str) -> str | None:
    """Return the newest release of a project, or None when it cannot be read."""
    try:
        with urllib.request.urlopen(
            f"https://pypi.org/pypi/{tool_versions.normalise(name)}/json",
            timeout=TIMEOUT_SECONDS,
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
        project = tomllib.loads(args.project.read_text(encoding="utf-8"))
        # The build backend decides how the released wheel is produced, so its pin is
        # compared too, even though the pipeline does not require it to be installed.
        pinned = tool_versions.pinned(project) | tool_versions.build_requirements(project)
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"check-latest: cannot read pins from {args.project}: {error}", file=sys.stderr)
        return 1
    behind, unknown = compare(pinned, pypi_latest)
    for line in unknown:
        print(f"check-latest: warning, {line}", file=sys.stderr)
    if behind:
        for line in behind:
            print(f"check-latest: {line}", file=sys.stderr)
        print(
            "check-latest: run the dependency update workflow, one commit per change",
            file=sys.stderr,
        )
        return 1
    checked = sorted(set(pinned) - {line.split(":", 1)[0] for line in unknown})
    if not checked:
        print("check-latest: no pin could be compared", file=sys.stderr)
        return 0
    print(
        "check-latest: " + ", ".join(f"{name}=={pinned[name]}" for name in checked) + " are current"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
