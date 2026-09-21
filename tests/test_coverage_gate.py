import json

import coverage_gate


def _report(tmp_path, percent, missing_lines=0, missing_branches=0):
    path = tmp_path / "coverage.json"
    path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": percent,
                    "missing_lines": missing_lines,
                    "missing_branches": missing_branches,
                }
            }
        )
    )
    return path


def test_the_gate_requires_more_than_the_minimum():
    assert coverage_gate.passes(98.01, 98.0) is True
    assert coverage_gate.passes(98.0, 98.0) is False
    assert coverage_gate.passes(97.9, 98.0) is False


def test_measured_values_come_from_the_report_totals(tmp_path):
    report = json.loads(_report(tmp_path, 99.5, 3, 2).read_text())
    assert coverage_gate.measured(report) == (99.5, 3, 2)
    assert coverage_gate.measured({"totals": {"percent_covered": 100, "missing_lines": 0}}) == (
        100.0,
        0,
        0,
    )


def test_coverage_above_the_minimum_passes(tmp_path, capsys):
    assert coverage_gate.main([str(_report(tmp_path, 100.0))]) == 0
    printed = capsys.readouterr().out
    assert "coverage 100.00%" in printed
    assert "above 98.00%" in printed


def test_coverage_at_the_minimum_fails(tmp_path, capsys):
    assert coverage_gate.main([str(_report(tmp_path, 98.0, 12, 4))]) == 1
    error = capsys.readouterr().err
    assert "12 uncovered statements and 4 uncovered branches" in error
    assert "not above 98.00%" in error


def test_a_custom_minimum_is_honoured(tmp_path):
    report = _report(tmp_path, 99.0)
    assert coverage_gate.main([str(report), "--minimum", "99.5"]) == 1
    assert coverage_gate.main([str(report), "--minimum", "90"]) == 0


def test_an_unusable_report_fails_the_gate(tmp_path, capsys):
    assert coverage_gate.main([str(tmp_path / "missing.json")]) == 1
    assert "unusable report" in capsys.readouterr().err
    broken = tmp_path / "broken.json"
    broken.write_text('{"totals": {}}')
    assert coverage_gate.main([str(broken)]) == 1
    assert "unusable report" in capsys.readouterr().err
