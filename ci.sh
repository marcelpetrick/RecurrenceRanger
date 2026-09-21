#!/usr/bin/env sh
set -eu

if [ -x .venv/bin/ruff ] && [ -x .venv/bin/pytest ]; then
  RUFF=.venv/bin/ruff
  PYTEST=.venv/bin/pytest
else
  RUFF=ruff
  PYTEST=pytest
fi

"$RUFF" check src tests
"$RUFF" format --check src tests
"$PYTEST" -q
