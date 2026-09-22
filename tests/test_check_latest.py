import contextlib
import io
import json
import urllib.error
import urllib.request

import check_latest


def test_only_pins_behind_their_release_are_reported():
    pinned = {"coverage": "7.16.1", "mypy": "2.3.1", "ruff": "0.16.8"}
    latest = {"coverage": "7.16.1", "mypy": "2.4.0", "ruff": None}
    assert check_latest.outdated(pinned, latest.get) == [
        "mypy: pinned 2.3.1, latest 2.4.0",
        "ruff: pinned 0.16.8, latest release unknown",
    ]
    assert check_latest.outdated(pinned, {**pinned}.get) == []


def test_the_newest_release_is_read_from_the_index(monkeypatch):
    def fake_urlopen(url, timeout=None):
        assert url == "https://pypi.org/pypi/ruff/json"
        assert timeout == check_latest.TIMEOUT_SECONDS
        body = {"info": {"version": "0.16.8"}, "releases": {"0.16.8": [{"yanked": False}]}}
        return contextlib.closing(io.BytesIO(json.dumps(body).encode()))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert check_latest.pypi_latest("ruff") == "0.16.8"


def test_an_unreachable_index_a_yanked_release_and_junk_are_all_unknown(monkeypatch):
    def unreachable(url, timeout=None):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr(urllib.request, "urlopen", unreachable)
    assert check_latest.pypi_latest("ruff") is None

    def answer(body):
        def fake_urlopen(url, timeout=None):
            return contextlib.closing(io.BytesIO(json.dumps(body).encode()))

        return fake_urlopen

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        answer({"info": {"version": "9.9.9"}, "releases": {"9.9.9": [{"yanked": True}]}}),
    )
    assert check_latest.pypi_latest("ruff") is None
    monkeypatch.setattr(urllib.request, "urlopen", answer({"info": {}}))
    assert check_latest.pypi_latest("ruff") is None
    monkeypatch.setattr(urllib.request, "urlopen", answer({"info": {"version": "1.0"}}))
    assert check_latest.pypi_latest("ruff") == "1.0"


def test_current_pins_pass_and_drift_fails(tmp_path, monkeypatch, capsys):
    project = tmp_path / "pyproject.toml"
    project.write_text('[project.optional-dependencies]\ndev = ["ruff==0.16.8", "mypy==2.3.1"]\n')
    monkeypatch.setattr(
        check_latest, "pypi_latest", lambda name: {"ruff": "0.16.8"}.get(name, "2.3.1")
    )
    assert check_latest.main(["--project", str(project)]) == 0
    assert "ruff==0.16.8" in capsys.readouterr().out

    monkeypatch.setattr(check_latest, "pypi_latest", lambda name: "9.9.9")
    assert check_latest.main(["--project", str(project)]) == 1
    error = capsys.readouterr().err
    assert "mypy: pinned 2.3.1, latest 9.9.9" in error
    assert "one commit per change" in error


def test_an_unreadable_project_file_is_reported(tmp_path, capsys):
    assert check_latest.main(["--project", str(tmp_path / "missing.toml")]) == 1
    assert "cannot read pins" in capsys.readouterr().err
