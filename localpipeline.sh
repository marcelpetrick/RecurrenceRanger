#!/usr/bin/env sh
# Single entry point for every code change: formatting, lint, static analysis,
# tests, a measured coverage report, the coverage gate and the version history.
set -eu

COVERAGE_MINIMUM=${COVERAGE_MINIMUM:-98}
COVERAGE_REPORT=${COVERAGE_REPORT:-coverage.json}

if [ -x .venv/bin/python ]; then
  PYTHON=.venv/bin/python
else
  PYTHON=python3
fi

echo "== formatting =="
"$PYTHON" -m ruff format --check src tests scripts

echo "== lint =="
"$PYTHON" -m ruff check src tests scripts

echo "== static analysis =="
"$PYTHON" -m mypy

echo "== tests and coverage =="
"$PYTHON" -m coverage erase
"$PYTHON" -m coverage run -m pytest -q
"$PYTHON" -m coverage report
"$PYTHON" -m coverage json -q -o "$COVERAGE_REPORT"

echo "== coverage gate =="
"$PYTHON" scripts/coverage_gate.py "$COVERAGE_REPORT" --minimum "$COVERAGE_MINIMUM"

echo "== version history =="
"$PYTHON" scripts/versioning.py check
