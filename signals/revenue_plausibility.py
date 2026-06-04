"""
Alpha Signal v2 — Revenue-plausibility hard exclusion (tier-agnostic)

Why this exists
---------------
Our forensic suite (Beneish M, Altman Z, Sloan accruals, Piotroski) is built to
detect either *earnings-manipulation onset* (year-over-year statistical anomalies)
or *bankruptcy distress*. Rajesh Exports (REXP) — SEBI interim order 2026-06-03,
~₹15.15 lakh cr of fabricated revenue across FY21-25 (~99.8% of consolidated) —
is neither:
  • The fraud is steady-state (5+ years), so every YoY ratio is internally
    consistent → Beneish/Montier-C see no change → CLEAN.
  • The cash side was fabricated too (broker round-trip), and net income is ~zero,
    so the accrual terms (TATA, Sloan) read as cash-backed → "good".
  • The balance sheet looks debt-light → Altman Z = 13.7 ("safest" band).
On 2026-06-04 REXP sat in daily_picks at rank 79, UHS 90 TRUSTED.

What every model missed is the LEVEL, not the change: REXP reported ~₹7.8 lakh cr
of TTM revenue on ₹29,372 cr of assets — a ~26x asset turnover at ~0.01% net
margin. No legitimate business turns its entire asset base over 26 times a year at
zero profit; that is the signature of churned, fictitious revenue.

This module encodes exactly that "externally impossible" test as a hard exclusion.
It is deliberately a two-part AND (high turnover AND ~zero margin) so genuinely
high-turnover businesses — distribution (Redington), staffing (Quess, TeamLease),
agri-commodity (Gokul Agro), all ~5-6x at 1-3% margin — are NOT caught. On current
data it flags exactly one non-financial: REXP.

It is a hard exclusion (drops the stock from daily_picks), NOT a weighted alpha
factor, so it does not go through the t-stat ≥ 1.5 promotion gate (ADR 0017).

Usage:
    python -m signals.revenue_plausibility          # print flagged stocks
"""

import pandas as pd

from config import REVENUE_PLAUSIBILITY as RP
from db import read_sql


def flag_revenue_implausible(rev_ttm, ni_ttm, total_assets, sector, *, cfg=RP):
    """Pure predicate. Returns (is_implausible: bool, reason: str|None).

    Flagged iff (financials exempt, enough asset base to trust the ratio):
        turnover = rev_ttm / total_assets  >  cfg["turnover_max"]   AND
        |net_margin| = |ni_ttm / rev_ttm|  <  cfg["abs_net_margin_max"]

    Conservative by construction — anything with missing revenue/assets/income,
    a sub-floor asset base, or an unknown margin is NOT flagged. A hard exclusion
    must never drop a stock on absent evidence.
    """
    if sector == "Financials":
        return False, None  # turnover/margin semantics differ for lenders
    if rev_ttm is None or total_assets is None or pd.isna(rev_ttm) or pd.isna(total_assets):
        return False, None
    if rev_ttm <= 0 or total_assets < cfg["min_assets_cr"]:
        return False, None

    turnover = rev_ttm / total_assets
    if turnover <= cfg["turnover_max"]:
        return False, None

    if ni_ttm is None or pd.isna(ni_ttm):
        return False, None  # no margin evidence → don't exclude
    margin = ni_ttm / rev_ttm
    if abs(margin) >= cfg["abs_net_margin_max"]:
        return False, None

    reason = (
        f"revenue/assets={turnover:.1f}x (>{cfg['turnover_max']:.0f}x) at net "
        f"margin {margin * 100:.2f}% (<{cfg['abs_net_margin_max'] * 100:.1f}%) — "
        f"implausible asset turnover at ~zero profit"
    )
    return True, reason


def compute_revenue_plausibility():
    """Evaluate the whole universe.

    Returns DataFrame[sid, revenue_implausible(bool), implausible_reason(str|None)],
    one row per stock that has a full TTM (4 consolidated quarters) AND a balance
    sheet. Stocks without enough data simply don't appear (treated as not-flagged
    by the consumer's left-merge + fillna(False)).
    """
    rows = read_sql(
        """
        WITH ttm AS (
          SELECT sid, SUM(revenue) AS ttm_rev, SUM(net_income) AS ttm_ni, COUNT(*) AS nq
          FROM (
            SELECT sid, revenue, net_income,
                   ROW_NUMBER() OVER (PARTITION BY sid ORDER BY end_date DESC) AS rn
            FROM quarterly_income
            WHERE reporting = 'consolidated' AND revenue IS NOT NULL
          ) WHERE rn <= 4 GROUP BY sid HAVING nq = 4
        ),
        bs AS (
          SELECT sid, total_assets FROM (
            SELECT sid, total_assets,
                   ROW_NUMBER() OVER (PARTITION BY sid ORDER BY end_date DESC) AS rn
            FROM annual_balance_sheet WHERE total_assets IS NOT NULL
          ) WHERE rn = 1
        )
        SELECT s.sid, s.sector, t.ttm_rev, t.ttm_ni, b.total_assets
        FROM stocks s
        JOIN ttm t ON t.sid = s.sid
        JOIN bs  b ON b.sid = s.sid
        """
    )

    out = []
    for _, r in rows.iterrows():
        flagged, reason = flag_revenue_implausible(
            r["ttm_rev"], r["ttm_ni"], r["total_assets"], r["sector"]
        )
        out.append(
            {"sid": r["sid"], "revenue_implausible": flagged, "implausible_reason": reason}
        )

    df = pd.DataFrame(out, columns=["sid", "revenue_implausible", "implausible_reason"])
    if df.empty:
        df = pd.DataFrame(columns=["sid", "revenue_implausible", "implausible_reason"])
    return df


def main():
    df = compute_revenue_plausibility()
    flagged = df[df["revenue_implausible"]]
    print(f"Revenue-plausibility gate: {len(df)} stocks evaluated, "
          f"{len(flagged)} flagged implausible")
    for _, r in flagged.iterrows():
        print(f"  EXCLUDE {r['sid']}: {r['implausible_reason']}")


if __name__ == "__main__":
    main()
