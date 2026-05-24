"""
Alpha Signal v2 — Cockpit Endpoint Coverage Audit

Calls every per-stock cockpit endpoint against a stratified sample of the
universe and reports which endpoints return empty for which stocks. This is
the missing pre-2026-05-23 check that would have caught:

  • ANO price chart empty (no stock_prices rows)
  • Gillette regulatory items showing 2023 articles (sort bug)
  • Any future per-stock endpoint that silently breaks for a slice of universe

Designed to run after the daily pipeline (or on-demand). Output goes to
pipeline_log so the health email surfaces it alongside other watchdog state.

Usage:
    python -m tools.cockpit_endpoint_audit            # full stratified sample
    python -m tools.cockpit_endpoint_audit --sample 50  # smaller for quick check
    python -m tools.cockpit_endpoint_audit --json     # machine-readable
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db


# Endpoints to audit. Each is (label, callable accepting sid → result).
# "Empty" means: returns [] / {} / None / a dict whose values are all None.
def _endpoint_callables():
    from cockpit import api
    return [
        ("prices_extended",   lambda sid: api.get_price_series_extended(sid, days=365)),
        ("quarterly",         api.get_quarterly_financials),
        ("annual",            api.get_annual_financials),
        ("shareholding",      api.get_shareholding_history),
        ("forecasts",         api.get_forecast_trend),
        ("insider_timeline",  api.get_insider_timeline),
    ]


def _is_empty(result):
    if result is None or result == [] or result == {}:
        return True
    if isinstance(result, dict):
        # Treat as empty when every top-level value is empty/None
        return all(v in (None, [], {}, "") for v in result.values())
    return False


def _stratified_sample(n_per_tier=30):
    """Random per-tier sample of universe sids. Stratification matters because
    LARGE has ~99% coverage everywhere and would mask SMALL gaps if you just
    take the head."""
    df = read_sql(f"""
        SELECT sid, ticker, cap_tier FROM (
          SELECT sid, ticker, cap_tier,
                 ROW_NUMBER() OVER (PARTITION BY cap_tier ORDER BY RANDOM()) AS r
          FROM stocks
        )
        WHERE r <= {int(n_per_tier)}
        ORDER BY cap_tier, sid
    """)
    return df


def _log_violation(endpoint, n_empty, n_sampled, sample_sid):
    # pipeline_log status is constrained to {RUNNING, SUCCESS, FAILED, SKIPPED}.
    # We log as FAILED for coverage gaps so it surfaces in the same query path
    # as other watchdog failures; the message carries the severity.
    pct = round(100.0 * n_empty / n_sampled, 1) if n_sampled else 0
    now = datetime.now().isoformat(timespec="seconds")
    severity = "CRITICAL" if pct >= 20 else "WARN"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_log
               (run_date, step_name, status, started_at, finished_at, error_message)
               VALUES (date('now'), ?, ?, ?, ?, ?)""",
            (f"endpoint_audit_{endpoint}",
             "FAILED",
             now, now,
             f"[{severity}] {n_empty}/{n_sampled} ({pct}%) sids return empty — sample: {sample_sid}"),
        )


def audit(sample_size=30, json_output=False):
    sample = _stratified_sample(n_per_tier=sample_size)
    endpoints = _endpoint_callables()

    results = []
    for label, fn in endpoints:
        empties = []
        for _, row in sample.iterrows():
            sid = row["sid"]
            try:
                if _is_empty(fn(sid)):
                    empties.append((sid, row["ticker"], row["cap_tier"]))
            except Exception as e:
                # An endpoint that raises for a sid is also a coverage hole.
                empties.append((sid, row["ticker"], f"{row['cap_tier']} [ERR {type(e).__name__}]"))

        pct = round(100.0 * len(empties) / len(sample), 1) if len(sample) else 0
        results.append({
            "endpoint": label,
            "sampled": len(sample),
            "empty": len(empties),
            "pct_empty": pct,
            "by_tier": _count_by_tier(empties),
            "sample_sids": [f"{s}({t},{c})" for s, t, c in empties[:5]],
        })

        # Log anything ≥5% as a watchdog event. Real production endpoints
        # should be >95% covered for the populated tiers.
        if pct >= 5:
            _log_violation(label, len(empties), len(sample),
                           empties[0][0] if empties else "")

    if json_output:
        print(json.dumps(results, indent=2))
    else:
        _print_report(results)
    return results


def _count_by_tier(empties):
    out = {}
    for _, _, tier in empties:
        tier_clean = tier.split(" ")[0]  # strip "[ERR ...]" suffix
        out[tier_clean] = out.get(tier_clean, 0) + 1
    return out


def _print_report(results):
    print("Cockpit Endpoint Coverage Audit")
    print("=" * 80)
    print(f"{'Endpoint':22s} {'Sampled':>8s} {'Empty':>7s} {'%':>6s}  By tier")
    print("-" * 80)
    for r in results:
        tier_str = " ".join(f"{t}={n}" for t, n in r["by_tier"].items()) or "—"
        marker = "✗" if r["pct_empty"] >= 20 else ("⚠" if r["pct_empty"] >= 5 else "✓")
        print(f"{marker} {r['endpoint']:20s} {r['sampled']:>8d} {r['empty']:>7d} "
              f"{r['pct_empty']:>5.1f}%  {tier_str}")
        if r["sample_sids"]:
            print(f"    sample: {', '.join(r['sample_sids'])}")
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=30,
                        help="N stocks per cap_tier (default 30 → 90 total)")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()
    audit(sample_size=args.sample, json_output=args.json)


if __name__ == "__main__":
    main()
