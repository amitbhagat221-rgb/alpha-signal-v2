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


# Endpoints to audit.
# `eligible_sql`: returns DISTINCT sids that SHOULD have data for this endpoint.
# If missing, the universe is "all stocks" (legacy behaviour). When supplied,
# we only count empties for sids that are in the eligible set — empty for an
# ineligible sid (e.g. insider_timeline for a stock with zero insider trades)
# is the CORRECT response, not a bug. Pre-fix the audit conflated the two,
# producing false-positive CRITICALs (insider_timeline at 53% empty was just
# 53% of universe having no insider trades — not a broken endpoint).
def _endpoint_callables():
    from cockpit import api
    return [
        {
            "label": "prices_extended",
            "fn":    lambda sid: api.get_price_series_extended(sid, days=365),
            "eligible_sql": "SELECT DISTINCT sid FROM stock_prices",
        },
        {
            "label": "quarterly",
            "fn":    api.get_quarterly_financials,
            "eligible_sql": "SELECT DISTINCT sid FROM quarterly_income",
        },
        {
            "label": "annual",
            "fn":    api.get_annual_financials,
            "eligible_sql": "SELECT DISTINCT sid FROM annual_balance_sheet",
        },
        {
            "label": "shareholding",
            "fn":    api.get_shareholding_history,
            "eligible_sql": "SELECT DISTINCT sid FROM shareholding",
        },
        {
            "label": "forecasts",
            "fn":    api.get_forecast_trend,
            "eligible_sql": "SELECT DISTINCT sid FROM forecast_history",
        },
        {
            "label": "insider_timeline",
            "fn":    api.get_insider_timeline,
            # Sparse by nature — only stocks with an insider trade in last 730d
            # should return non-empty. Don't flag a stock with no insider activity.
            "eligible_sql": "SELECT DISTINCT sid FROM insider_trades WHERE trade_date >= date('now', '-730 days')",
        },
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


def _log_audit_result(endpoint, n_empty, n_eligible, sample_sid, n_errors=0, n_ineligible=0):
    """Always insert a row — SUCCESS if clean, FAILED if violations. The cockpit
    reads the most-recent per-endpoint row, so we need to overwrite a stale
    FAILED with a fresh SUCCESS once the issue is fixed (otherwise the old
    CRITICAL leaks forever).
    """
    pct = round(100.0 * n_empty / n_eligible, 1) if n_eligible else 0
    now = datetime.now().isoformat(timespec="seconds")
    is_failure = bool(n_errors) or pct >= 5
    if not is_failure:
        # Clean run — write SUCCESS with a brief positive summary
        msg = (f"[OK] {n_eligible} eligible sids — 0% empty"
               + (f" (+{n_ineligible} ineligible-empty, correct)" if n_ineligible else ""))
        status = "SUCCESS"
    else:
        if n_errors:
            severity = "CRITICAL"
        elif pct >= 20:
            severity = "CRITICAL"
        else:
            severity = "WARN"
        msg = (f"[{severity}] {n_empty}/{n_eligible} ({pct}%) eligible sids return empty"
               + (f" + {n_errors} raised exceptions" if n_errors else "")
               + f" — sample: {sample_sid}")
        status = "FAILED"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO pipeline_log
               (run_date, step_name, status, started_at, finished_at, error_message)
               VALUES (date('now'), ?, ?, ?, ?, ?)""",
            (f"endpoint_audit_{endpoint}", status, now, now, msg),
        )


def audit(sample_size=30, json_output=False):
    sample = _stratified_sample(n_per_tier=sample_size)
    endpoints = _endpoint_callables()
    sample_sids = set(sample["sid"])

    results = []
    for spec in endpoints:
        label = spec["label"]
        fn    = spec["fn"]

        # Eligible universe for this endpoint (e.g. stocks with any insider trade).
        eligible_set = None
        if spec.get("eligible_sql"):
            try:
                df_elig = read_sql(spec["eligible_sql"])
                eligible_set = set(df_elig["sid"].dropna().astype(str))
            except Exception:
                eligible_set = None

        empties_eligible = []          # eligible sids that returned empty (real defect)
        empties_ineligible = 0         # ineligible sids that returned empty (correct, not a defect)
        errors = []                    # exceptions for any sid (always a defect)
        n_eligible_sampled = 0

        for _, row in sample.iterrows():
            sid = row["sid"]
            in_eligible = (eligible_set is None) or (sid in eligible_set)
            if in_eligible:
                n_eligible_sampled += 1
            try:
                empty = _is_empty(fn(sid))
            except Exception as e:
                errors.append((sid, row["ticker"], f"{row['cap_tier']} [ERR {type(e).__name__}: {str(e)[:60]}]"))
                continue
            if empty and in_eligible:
                empties_eligible.append((sid, row["ticker"], row["cap_tier"]))
            elif empty:
                empties_ineligible += 1

        # Defect rate is % of ELIGIBLE-and-sampled sids returning empty, NOT % of all sample.
        denom = n_eligible_sampled if n_eligible_sampled else len(sample)
        pct = round(100.0 * len(empties_eligible) / denom, 1) if denom else 0

        results.append({
            "endpoint": label,
            "sampled": len(sample),
            "eligible_sampled": n_eligible_sampled,
            "eligible_universe": len(eligible_set) if eligible_set is not None else None,
            "empty_eligible": len(empties_eligible),
            "empty_ineligible": empties_ineligible,
            "errors": len(errors),
            "pct_empty_of_eligible": pct,
            "by_tier": _count_by_tier(empties_eligible + errors),
            "sample_sids": [f"{s}({t},{c})" for s, t, c in (empties_eligible + errors)[:5]],
        })

        # Always write a row so "no news" = clean. Otherwise an old FAILED row
        # from a previous bad run remains the most-recent per-endpoint entry
        # forever, leaking into the cockpit's Health Center as a phantom CRITICAL.
        sample_sid_for_log = (empties_eligible[0][0] if empties_eligible
                              else errors[0][0] if errors else "")
        _log_audit_result(label, len(empties_eligible), denom, sample_sid_for_log,
                          n_errors=len(errors), n_ineligible=empties_ineligible)

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
    print("=" * 90)
    print(f"{'Endpoint':22s} {'Sampled':>8s} {'Eligible':>9s} {'Empty':>7s} {'%elig':>6s} {'Err':>4s}  By tier")
    print("-" * 90)
    for r in results:
        tier_str = " ".join(f"{t}={n}" for t, n in r["by_tier"].items()) or "—"
        pct = r["pct_empty_of_eligible"]
        marker = "✗" if (pct >= 20 or r["errors"]) else ("⚠" if pct >= 5 else "✓")
        print(f"{marker} {r['endpoint']:20s} {r['sampled']:>8d} {r['eligible_sampled']:>9d} "
              f"{r['empty_eligible']:>7d} {pct:>5.1f}% {r['errors']:>4d}  {tier_str}")
        if r["sample_sids"]:
            print(f"    sample: {', '.join(r['sample_sids'])}")
        if r["empty_ineligible"]:
            print(f"    (+{r['empty_ineligible']} ineligible-empty — correct, not a defect)")
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
