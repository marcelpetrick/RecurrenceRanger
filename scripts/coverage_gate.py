"""Fail unless measured coverage is strictly above the required minimum."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def measured(report: dict) -> tuple[float, int, int]:
    """Return the overall percentage plus uncovered statement and branch counts."""
    totals = report["totals"]
    return (
        float(totals["percent_covered"]),
        int(totals["missing_lines"]),
        int(totals.get("missing_branches", 0)),
    )


def passes(percent: float, minimum: float) -> bool:
    """The gate requires coverage strictly greater than the minimum, not equal to it."""
    return percent > minimum


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coverage-gate", description=__doc__)
    parser.add_argument("report", type=Path, help="coverage JSON report")
    parser.add_argument("--minimum", type=float, default=98.0)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
        percent, statements, branches = measured(report)
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"coverage-gate: unusable report {args.report}: {error}", file=sys.stderr)
        return 1
    summary = (
        f"coverage {percent:.2f}% with {statements} uncovered statements "
        f"and {branches} uncovered branches"
    )
    if not passes(percent, args.minimum):
        print(f"coverage-gate: {summary}, not above {args.minimum:.2f}%", file=sys.stderr)
        return 1
    print(f"coverage-gate: {summary}, above {args.minimum:.2f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
