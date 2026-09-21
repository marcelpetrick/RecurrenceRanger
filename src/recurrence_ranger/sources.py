"""Discover conversation homes without reading credentials or transcript text."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Source:
    tool: str
    label: str
    home: Path
    origin: str
    aliases: tuple[str, ...] = ()

    @property
    def id(self) -> str:
        return f"{self.tool}:{self.home.resolve()}"

    @property
    def exists(self) -> bool:
        roots = ("projects",) if self.tool == "claude" else ("sessions", "archived_sessions")
        return any((self.home / root).is_dir() for root in roots)


def load_manifest(path: Path) -> list[Source]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or not isinstance(data.get("sources"), list):
        raise ValueError("unsupported source manifest")
    found = []
    for row in data["sources"]:
        tool = row["tool"]
        if tool not in {"claude", "codex"}:
            raise ValueError(f"unsupported tool: {tool}")
        found.append(Source(tool, row["label"], Path(row["home"]).expanduser(), "manifest"))
    return found


_ASSIGNMENT = re.compile(
    r"(?:^|[\s;])(?:export\s+)?(CLAUDE_CONFIG_DIR|CODEX_HOME)=[\"']?([^\s\"';]+)"
)


def discover(manifest: Path | None = None, *, home: Path | None = None) -> list[Source]:
    """Return configured, launcher, environment and default homes, including unavailable ones."""
    home = home or Path.home()
    candidates: list[Source] = load_manifest(manifest) if manifest else []
    for variable, tool in (("CLAUDE_CONFIG_DIR", "claude"), ("CODEX_HOME", "codex")):
        if value := os.environ.get(variable):
            candidates.append(
                Source(tool, Path(value).name, Path(value).expanduser(), "environment")
            )
    for rc in (".zshrc", ".zshenv", ".bashrc", ".profile", ".config/fish/config.fish"):
        try:
            content = (home / rc).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in content.splitlines():
            if line.lstrip().startswith("#"):
                continue
            for variable, value in _ASSIGNMENT.findall(line):
                tool = "claude" if variable == "CLAUDE_CONFIG_DIR" else "codex"
                path = Path(os.path.expandvars(value)).expanduser()
                candidates.append(Source(tool, path.name, path, f"launcher:{rc}"))
    for tool, name in (("claude", ".claude"), ("codex", ".codex")):
        candidates.append(Source(tool, name.lstrip("."), home / name, "default"))
    for tool, pattern in (("claude", ".claude*"), ("codex", ".codex*")):
        for path in home.glob(pattern):
            roots = ("projects",) if tool == "claude" else ("sessions", "archived_sessions")
            if any((path / root).is_dir() for root in roots):
                candidates.append(Source(tool, path.name.lstrip("."), path, "home scan"))
    unique: dict[str, Source] = {}
    for source in candidates:
        previous = unique.get(source.id)
        if previous:
            unique[source.id] = Source(
                previous.tool,
                previous.label,
                previous.home,
                previous.origin,
                (*previous.aliases, str(source.home)),
            )
        else:
            unique[source.id] = source
    return list(unique.values())


def conversation_files(source: Source) -> list[Path]:
    """Walk only transcript trees; do not follow directory symlinks."""
    roots = (
        [source.home / "projects"]
        if source.tool == "claude"
        else [source.home / "sessions", source.home / "archived_sessions"]
    )
    files: list[Path] = []
    for root in roots:
        for directory, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
            files.extend(
                Path(directory) / name
                for name in names
                if name.endswith(".jsonl")
                and (source.tool == "claude" or name.startswith("rollout-"))
            )
    history = source.home / "history.jsonl"
    if history.is_file():
        files.append(history)
    return files
