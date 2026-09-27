"""
Alpha Signal v2 — Data Sanity Audit (a view over checks/)

Catches the class of bug freshness/error checks miss: producers ran cleanly,
wrote rows, but the rows are semantically wrong (analyst PT == close, rank
duplicates, a column outside its legal range, a per-stock coverage hole).

The checks themselves live in checks/ (plan 0015 Phase 4): semantic checks in
checks/custom.py, column ranges once in checks/ranges.py, coverage gates in
tables.TABLES. checks.run() is the one runner; run() below returns its FAILING
verdicts in the violation-dict shape the health report and the ops console read.

Usage:
    python -m tools.data_sanity                # run all, print report
    python -m tools.data_sanity --json         # machine-readable
    python -m tools.data_sanity --check CODE   # one check by code
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import checks
from checks import CRITICAL, INFO, WARN  # noqa: F401  (re-exported: health_report)
from checks.custom import CHECKS  # noqa: F401  (re-exported: tools/regression_fixtures)

_VERDICT_ONLY = ("check_id", "target", "status", "detail", "n_bad", "pct")


def _violation(v):
    """A failing verdict in the historical violation-dict shape."""
    out = {k: val for k, val in v.items() if k not in _VERDICT_ONLY}
    out.update(n_violations=v["n_bad"], pct_violations=v["pct"])
    return out


def run(only_code=None):
    """Run all checks (or the one named `only_code`); return the violations.

    Each violation: {code, severity, table, column, message, n_violations,
    n_total, pct_violations, sample[, extra fields a function check returns]}.
    A check that raises is reported as a WARN violation, never swallowed.
    """
    return [_violation(v) for v in checks.run(only=only_code) if v["status"] != checks.PASS]


def format_terminal(violations):
    if not violations:
        return "✓ All sanity checks passed."
    by_sev = {CRITICAL: [], WARN: [], INFO: []}
    for v in violations:
        by_sev.get(v["severity"], by_sev[WARN]).append(v)

    lines = []
    summary = " · ".join(
        f"{len(by_sev[s])} {s}" for s in (CRITICAL, WARN, INFO) if by_sev[s]
    )
    lines.append(f"Data sanity audit — {summary or 'all clean'}")
    lines.append("=" * 80)
    for sev in (CRITICAL, WARN, INFO):
        for v in by_sev[sev]:
            marker = "❌" if sev == CRITICAL else ("⚠" if sev == WARN else "·")
            pct_str = f" ({v['pct_violations']:.1f}%)" if v.get("pct_violations") is not None else ""
            n_str = f"{v['n_violations']}/{v['n_total']}" if v.get("n_total") else f"{v['n_violations'] or 0}"
            lines.append(f"  {marker} [{sev}] {v['code']}")
            lines.append(f"      {v['message']}")
            lines.append(f"      table: {v.get('table')} · column: {v.get('column')} · {n_str}{pct_str}")
            if v.get("sample"):
                lines.append(f"      sample: {v['sample']}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--check", help="Run a single check by code")
    args = parser.parse_args()

    violations = run(only_code=args.check)
    if args.json:
        print(json.dumps(violations, indent=2, default=str))
    else:
        print(format_terminal(violations))

    # Exit non-zero on any CRITICAL — lets cron / CI signal
    return 1 if any(v["severity"] == CRITICAL for v in violations) else 0


if __name__ == "__main__":
    sys.exit(main())
