from importlib.metadata import version

import tool_versions


def test_pins_are_read_from_the_development_extra():
    project = {"project": {"optional-dependencies": {"dev": ["pytest==9.1.1", "ruff==0.15.20"]}}}
    assert tool_versions.pinned(project) == {"pytest": "9.1.1", "ruff": "0.15.20"}


def test_an_unpinned_dependency_is_rejected():
    for requirement in ("ruff>=0.15", "ruff", "ruff=="):
        project = {"project": {"optional-dependencies": {"dev": [requirement]}}}
        try:
            tool_versions.pinned(project)
        except ValueError as error:
            assert "not pinned" in str(error)
        else:
            raise AssertionError(f"{requirement} should be rejected")


def test_missing_and_drifted_tools_are_reported():
    expected = {"coverage": "7.16.1", "mypy": "2.3.1", "ruff": "0.15.20"}
    installed = {"coverage": "7.16.1", "ruff": "0.16.8"}
    assert tool_versions.mismatches(expected, installed.get) == [
        "mypy: expected 2.3.1, found nothing installed",
        "ruff: expected 0.15.20, found 0.16.8",
    ]
    assert tool_versions.mismatches(expected, {**expected}.get) == []


def test_this_environment_matches_the_pinned_tools(capsys):
    assert tool_versions.main([]) == 0
    printed = capsys.readouterr().out
    assert "ruff==" in printed and "mypy==" in printed


def test_drift_fails_with_one_line_per_tool(tmp_path, capsys):
    project = tmp_path / "pyproject.toml"
    project.write_text(
        '[project.optional-dependencies]\ndev = ["ruff==0.0.1", "sqlite-nonexistent==1.0"]\n'
    )
    assert tool_versions.main(["--project", str(project)]) == 1
    errors = capsys.readouterr().err.splitlines()
    assert errors == [
        f"tool-versions: ruff: expected 0.0.1, found {version('ruff')}",
        "tool-versions: sqlite-nonexistent: expected 1.0, found nothing installed",
    ]


def test_an_unreadable_project_file_fails(tmp_path, capsys):
    assert tool_versions.main(["--project", str(tmp_path / "missing.toml")]) == 1
    assert "cannot read pins" in capsys.readouterr().err
    empty = tmp_path / "pyproject.toml"
    empty.write_text("[project]\nname = 'x'\n")
    assert tool_versions.main(["--project", str(empty)]) == 1
    assert "cannot read pins" in capsys.readouterr().err
