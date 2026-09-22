"""Verify that the installed check tools match the pinned development versions."""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Callable, Iterable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def exact(requirements: Iterable[str], what: str) -> dict[str, str]:
    """Read requirements that must all name one project and one exact version."""
    found = {}
    for requirement in requirements:
        name, separator, pin = requirement.partition("==")
        if not separator or not pin.strip():
            raise ValueError(f"{what} is not pinned: {requirement}")
        found[name.strip()] = pin.strip()
    return found


def pinned(project: dict) -> dict[str, str]:
    """Return the exactly pinned development dependencies of a parsed pyproject."""
    return exact(project["project"]["optional-dependencies"]["dev"], "development dependency")


def build_requirements(project: dict) -> dict[str, str]:
    """Return the exactly pinned build backend requirements of a parsed pyproject."""
    return exact(project["build-system"]["requires"], "build requirement")


def mismatches(expected: dict[str, str], installed: Callable[[str], str | None]) -> list[str]:
    """Report every pinned tool that is missing or installed at another version."""
    problems = []
    for name, pin in sorted(expected.items()):
        actual = installed(name)
        if actual != pin:
            problems.append(f"{name}: expected {pin}, found {actual or 'nothing installed'}")
    return problems


def _installed(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tool-versions", description=__doc__)
    parser.add_argument("--project", type=Path, default=Path("pyproject.toml"))
    args = parser.parse_args(argv)
    try:
        expected = pinned(tomllib.loads(args.project.read_text(encoding="utf-8")))
    except (OSError, KeyError, TypeError, ValueError) as error:
        print(f"tool-versions: cannot read pins from {args.project}: {error}", file=sys.stderr)
        return 1
    problems = mismatches(expected, _installed)
    if problems:
        for problem in problems:
            print(f"tool-versions: {problem}", file=sys.stderr)
        return 1
    print("tool-versions: " + ", ".join(f"{name}=={pin}" for name, pin in sorted(expected.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
