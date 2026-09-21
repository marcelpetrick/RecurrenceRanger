"""Bump the patch version and verify that every commit has the expected version."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_FILE = Path("VERSION")
PROJECT_FILE = Path("pyproject.toml")
PACKAGE_FILE = Path("src/recurrence_ranger/__init__.py")
VERSION_PATTERN = re.compile(r"0\.0\.[1-9][0-9]*\Z")
PROJECT_PATTERN = re.compile(r'(?m)^version = "[^"]+"$')
PACKAGE_PATTERN = re.compile(r'(?m)^__version__ = "[^"]+"$')


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _expected_text(path: Path, text: str, version: str) -> str:
    pattern = PROJECT_PATTERN if path == PROJECT_FILE else PACKAGE_PATTERN
    replacement = f'{"version" if path == PROJECT_FILE else "__version__"} = "{version}"'
    updated, count = pattern.subn(replacement, text)
    if count != 1:
        raise ValueError(f"expected exactly one version field in {path}, found {count}")
    return updated


def bump() -> str:
    current = (ROOT / VERSION_FILE).read_text().strip()
    if not VERSION_PATTERN.fullmatch(current):
        raise ValueError(f"invalid version in {VERSION_FILE}: {current!r}")
    version = f"0.0.{int(current.rsplit('.', 1)[1]) + 1}"
    updates = {
        VERSION_FILE: version + "\n",
        **{
            path: _expected_text(path, (ROOT / path).read_text(), version)
            for path in (PROJECT_FILE, PACKAGE_FILE)
            if (ROOT / path).is_file()
        },
    }
    for path, content in updates.items():
        (ROOT / path).write_text(content)
    return version


def check() -> str:
    commits = _git("rev-list", "--reverse", "HEAD").splitlines()
    if not commits:
        raise ValueError("no commits to check")
    for number, commit in enumerate(commits, start=1):
        parents = _git("rev-list", "--parents", "-n", "1", commit).split()[1:]
        if len(parents) > 1:
            raise ValueError(f"merge commit is incompatible with one patch per commit: {commit}")
        version = f"0.0.{number}"
        paths = set(_git("ls-tree", "-r", "--name-only", commit).splitlines())
        if str(VERSION_FILE) not in paths:
            raise ValueError(f"{commit}: missing {VERSION_FILE}")
        actual = _git("show", f"{commit}:{VERSION_FILE}")
        if actual != version:
            raise ValueError(f"{commit}: expected {version}, found {actual!r}")
        for path in (PROJECT_FILE, PACKAGE_FILE):
            if str(path) in paths:
                text = _git("show", f"{commit}:{path}")
                if _expected_text(path, text, version) != text:
                    raise ValueError(f"{commit}: {path} does not match {version}")
    head_version = f"0.0.{len(commits)}"
    for path in (VERSION_FILE, PROJECT_FILE, PACKAGE_FILE):
        if (ROOT / path).is_file():
            committed = _git("show", f"HEAD:{path}")
            if (ROOT / path).read_text().strip() != committed:
                raise ValueError(f"working tree {path} differs from HEAD")
    return head_version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("bump", "check"))
    action = parser.parse_args().action
    print(bump() if action == "bump" else check())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
