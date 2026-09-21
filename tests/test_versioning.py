import os
import subprocess
import sys

import pytest
import versioning


def git(root, *args, when=None):
    """Fixed dates keep the reverse commit order deterministic."""
    environment = dict(os.environ)
    if when:
        environment["GIT_AUTHOR_DATE"] = environment["GIT_COMMITTER_DATE"] = when
    return subprocess.check_output(
        [
            "git",
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        text=True,
        env=environment,
    ).strip()


def write_version(root, version, *, project=True, package=True):
    (root / "VERSION").write_text(version + "\n")
    if project:
        (root / "pyproject.toml").write_text(f'[project]\nname = "x"\nversion = "{version}"\n')
    if package:
        target = root / "src" / "recurrence_ranger"
        target.mkdir(parents=True, exist_ok=True)
        (target / "__init__.py").write_text(f'__version__ = "{version}"\n')


def repo_with_versions(root, count, **kwargs):
    root.mkdir(parents=True, exist_ok=True)
    git(root, "init", "-q", "-b", "master")
    for number in range(1, count + 1):
        write_version(root, f"0.0.{number}", **kwargs)
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", f"commit {number}", when=f"2026-09-21T00:0{number}:00")
    return root


def test_bump_advances_every_version_file(tmp_path, monkeypatch):
    monkeypatch.setattr(versioning, "ROOT", tmp_path)
    write_version(tmp_path, "0.0.31")
    assert versioning.bump() == "0.0.32"
    assert (tmp_path / "VERSION").read_text() == "0.0.32\n"
    assert 'version = "0.0.32"' in (tmp_path / "pyproject.toml").read_text()
    assert (
        '__version__ = "0.0.32"'
        in (tmp_path / "src" / "recurrence_ranger" / "__init__.py").read_text()
    )


def test_bump_accepts_a_tree_without_package_version_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(versioning, "ROOT", tmp_path)
    write_version(tmp_path, "0.0.4", project=False, package=False)
    assert versioning.bump() == "0.0.5"
    assert (tmp_path / "VERSION").read_text() == "0.0.5\n"
    assert not (tmp_path / "pyproject.toml").exists()


def test_bump_rejects_a_version_outside_the_patch_sequence(tmp_path, monkeypatch):
    monkeypatch.setattr(versioning, "ROOT", tmp_path)
    write_version(tmp_path, "1.2.3")
    with pytest.raises(ValueError, match="invalid version"):
        versioning.bump()


def test_bump_rejects_an_ambiguous_version_field(tmp_path, monkeypatch):
    monkeypatch.setattr(versioning, "ROOT", tmp_path)
    write_version(tmp_path, "0.0.7")
    (tmp_path / "pyproject.toml").write_text('version = "0.0.7"\nversion = "0.0.7"\n')
    with pytest.raises(ValueError, match="exactly one version field"):
        versioning.bump()


def test_check_accepts_one_patch_per_commit(tmp_path, monkeypatch):
    root = repo_with_versions(tmp_path / "repo", 3)
    monkeypatch.setattr(versioning, "ROOT", root)
    assert versioning.check() == "0.0.3"


def test_check_rejects_a_skipped_patch_number(tmp_path, monkeypatch):
    root = repo_with_versions(tmp_path / "repo", 2)
    write_version(root, "0.0.9")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "wrong version")
    monkeypatch.setattr(versioning, "ROOT", root)
    with pytest.raises(ValueError, match="expected 0.0.3, found '0.0.9'"):
        versioning.check()


def test_check_rejects_a_commit_without_a_version_file(tmp_path, monkeypatch):
    root = repo_with_versions(tmp_path / "repo", 1)
    (root / "VERSION").unlink()
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "drop version")
    monkeypatch.setattr(versioning, "ROOT", root)
    with pytest.raises(ValueError, match="missing VERSION"):
        versioning.check()


def test_check_rejects_a_package_field_that_lags_behind(tmp_path, monkeypatch):
    root = repo_with_versions(tmp_path / "repo", 1)
    (root / "VERSION").write_text("0.0.2\n")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "version file only")
    monkeypatch.setattr(versioning, "ROOT", root)
    with pytest.raises(ValueError, match="pyproject.toml does not match 0.0.2"):
        versioning.check()


def test_check_rejects_a_merge_commit(tmp_path, monkeypatch):
    root = repo_with_versions(tmp_path / "repo", 1)
    git(root, "checkout", "-q", "-b", "side")
    write_version(root, "0.0.2")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "side work", when="2026-09-21T00:02:00")
    git(root, "checkout", "-q", "master")
    (root / "main.txt").write_text("main\n")
    write_version(root, "0.0.3")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "master work", when="2026-09-21T00:03:00")
    subprocess.run(["git", "merge", "--no-commit", "--no-ff", "side"], cwd=root, check=False)
    write_version(root, "0.0.4")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "merge side", when="2026-09-21T00:04:00")
    monkeypatch.setattr(versioning, "ROOT", root)
    with pytest.raises(ValueError, match="merge commit"):
        versioning.check()


def test_check_rejects_uncommitted_version_changes(tmp_path, monkeypatch):
    root = repo_with_versions(tmp_path / "repo", 1)
    (root / "VERSION").write_text("0.0.2\n")
    monkeypatch.setattr(versioning, "ROOT", root)
    with pytest.raises(ValueError, match="working tree VERSION differs"):
        versioning.check()


def test_command_line_bumps_and_checks(tmp_path, monkeypatch, capsys):
    root = repo_with_versions(tmp_path / "repo", 2)
    monkeypatch.setattr(versioning, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["versioning.py", "check"])
    assert versioning.main() == 0
    assert capsys.readouterr().out.strip() == "0.0.2"
    monkeypatch.setattr(sys, "argv", ["versioning.py", "bump"])
    assert versioning.main() == 0
    assert capsys.readouterr().out.strip() == "0.0.3"
    assert (root / "VERSION").read_text() == "0.0.3\n"


def test_check_reports_an_unborn_branch_instead_of_crashing(tmp_path, monkeypatch):
    root = tmp_path / "empty"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    monkeypatch.setattr(versioning, "ROOT", root)
    with pytest.raises(ValueError, match="no commits to check"):
        versioning.check()
