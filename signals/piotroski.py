"""
Alpha Signal v2 — Piotroski F-Score (9-factor)

Reads: quarterly_income, annual_balance_sheet, annual_cash_flow, stocks
Writes: piotroski_scores

Each factor is binary (1 = met, 0 = not met, NULL = insufficient data).
F-Score = sum of non-NULL factors (0-9).

Financial Services sector is excluded (leverage/liquidity ratios meaningless for banks).

Usage:
    python -m signals.piotroski          # compute and save
    python -m signals.piotroski --dry-run  # compute but don't save
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import get_db, read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
DILUTION_TOLERANCE = 0.02  # 2% max share increase allowed
MIN_QUARTERS = 4           # for LTM computation
MIN_QUARTERS_YOY = 8       # for LTM Y0 vs Y-1


def _load_data():
    """Load all inputs from DB, pre-filter."""
    # Universe (exclude financial sector)
    stocks = read_sql(
        "SELECT sid, sector FROM stocks WHERE sector NOT IN "
        f"({','.join('?' for _ in FINANCIAL_SECTORS)})",
        params=list(FINANCIAL_SECTORS),
    )
    sids = set(stocks["sid"])

    # Quarterly income — prefer consolidated, LTM needs last 8 quarters
    qi = read_sql(
        "SELECT sid, period, end_date, reporting, revenue, net_income, pbt, interest "
        "FROM quarterly_income ORDER BY sid, end_date"
    )
    qi = qi[qi["sid"].isin(sids)].copy()

    # Keep consolidated where available, standalone otherwise
    has_consol = set(qi[qi["reporting"] == "consolidated"]["sid"])
    qi = qi[
        ((qi["sid"].isin(has_consol)) & (qi["reporting"] == "consolidated"))
        | (~qi["sid"].isin(has_consol))
    ]

    # Balance sheet — need last 2 years
    bs = read_sql(
        "SELECT sid, period, total_assets, current_assets, current_liabilities, "
        "long_term_debt, shares_outstanding "
        "FROM annual_balance_sheet ORDER BY sid, period"
    )
    bs = bs[bs["sid"].isin(sids)].copy()

    # Cash flow — need latest year
    cf = read_sql(
        "SELECT sid, period, operating_cash_flow "
        "FROM annual_cash_flow ORDER BY sid, period"
    )
    cf = cf[cf["sid"].isin(sids)].copy()

    return stocks, qi, bs, cf


def _compute_ltm(qi_group):
    """Compute LTM (last twelve months) sums for Y0 and Y-1."""
    # Sort by end_date, take most recent quarters
    g = qi_group.sort_values("end_date")
    n = len(g)

    result = {}

    if n >= MIN_QUARTERS:
        last4 = g.tail(4)
        result["revenue_y0"] = last4["revenue"].sum()
        result["ni_y0"] = last4["net_income"].sum()
        pbt_sum = last4["pbt"].sum()
        interest_sum = last4["interest"].fillna(0).sum()
        result["ebit_y0"] = pbt_sum + interest_sum

    if n >= MIN_QUARTERS_YOY:
        prev4 = g.iloc[-8:-4]
        result["revenue_y1"] = prev4["revenue"].sum()
        result["ni_y1"] = prev4["net_income"].sum()
        pbt_sum = prev4["pbt"].sum()
        interest_sum = prev4["interest"].fillna(0).sum()
        result["ebit_y1"] = pbt_sum + interest_sum

    return result


def _compute_scores(stocks, qi, bs, cf):
    """Compute Piotroski F-Score for each stock."""
    rows = []

    # Pre-group data
    qi_by_sid = dict(list(qi.groupby("sid")))
    bs_by_sid = dict(list(bs.groupby("sid")))
    cf_by_sid = dict(list(cf.groupby("sid")))

    for _, stock in stocks.iterrows():
        sid = stock["sid"]
        score = {"sid": sid}

        # ── Gather data ──
        qi_g = qi_by_sid.get(sid)
        bs_g = bs_by_sid.get(sid)
        cf_g = cf_by_sid.get(sid)

        if qi_g is None or len(qi_g) < MIN_QUARTERS:
            rows.append(score)
            continue

        ltm = _compute_ltm(qi_g)

        # Balance sheet: Y0 = most recent, Y-1 = second most recent
        bs_y0, bs_y1 = None, None
        if bs_g is not None and len(bs_g) >= 1:
            bs_sorted = bs_g.sort_values("period")
            bs_y0 = bs_sorted.iloc[-1]
            if len(bs_sorted) >= 2:
                bs_y1 = bs_sorted.iloc[-2]

        # Cash flow: Y0 = most recent
        cf_y0 = None
        if cf_g is not None and len(cf_g) >= 1:
            cf_y0 = cf_g.sort_values("period").iloc[-1]

        # ── F1: ROA positive ──
        if "ni_y0" in ltm and bs_y0 is not None and _nonzero(bs_y0.get("total_assets")):
            roa_y0 = ltm["ni_y0"] / bs_y0["total_assets"]
            score["roa_positive"] = int(roa_y0 > 0)
        else:
            roa_y0 = None

        # ── F2: Operating cash flow positive ──
        if cf_y0 is not None and pd.notna(cf_y0.get("operating_cash_flow")):
            score["cfo_positive"] = int(cf_y0["operating_cash_flow"] > 0)

        # ── F3: ROA improving ──
        if "ni_y1" in ltm and bs_y1 is not None and _nonzero(bs_y1.get("total_assets")):
            roa_y1 = ltm["ni_y1"] / bs_y1["total_assets"]
            if roa_y0 is not None:
                score["roa_improving"] = int(roa_y0 > roa_y1)

        # ── F4: Accruals quality (OCF > NI means accrual < 0) ──
        if (cf_y0 is not None and pd.notna(cf_y0.get("operating_cash_flow"))
                and "ni_y0" in ltm and bs_y0 is not None and _nonzero(bs_y0.get("total_assets"))):
            accrual = (ltm["ni_y0"] - cf_y0["operating_cash_flow"]) / bs_y0["total_assets"]
            score["accruals_quality"] = int(accrual < 0)

        # ── F5: Leverage decreased ──
        if (bs_y0 is not None and bs_y1 is not None
                and _nonzero(bs_y0.get("total_assets")) and _nonzero(bs_y1.get("total_assets"))):
            ltd_y0 = bs_y0.get("long_term_debt") or 0
            ltd_y1 = bs_y1.get("long_term_debt") or 0
            lev_y0 = ltd_y0 / bs_y0["total_assets"]
            lev_y1 = ltd_y1 / bs_y1["total_assets"]
            score["leverage_down"] = int(lev_y0 < lev_y1)

        # ── F6: Liquidity improved ──
        if (bs_y0 is not None and bs_y1 is not None
                and _nonzero(bs_y0.get("current_liabilities"))
                and _nonzero(bs_y1.get("current_liabilities"))):
            cr_y0 = bs_y0["current_assets"] / bs_y0["current_liabilities"]
            cr_y1 = bs_y1["current_assets"] / bs_y1["current_liabilities"]
            score["liquidity_up"] = int(cr_y0 > cr_y1)

        # ── F7: No dilution ──
        if (bs_y0 is not None and bs_y1 is not None
                and _nonzero(bs_y0.get("shares_outstanding"))
                and _nonzero(bs_y1.get("shares_outstanding"))):
            score["no_dilution"] = int(
                bs_y0["shares_outstanding"] <= bs_y1["shares_outstanding"] * (1 + DILUTION_TOLERANCE)
            )

        # ── F8: EBIT margin up ──
        if ("ebit_y0" in ltm and "ebit_y1" in ltm
                and _nonzero(ltm.get("revenue_y0")) and _nonzero(ltm.get("revenue_y1"))):
            margin_y0 = ltm["ebit_y0"] / ltm["revenue_y0"]
            margin_y1 = ltm["ebit_y1"] / ltm["revenue_y1"]
            score["gross_margin_up"] = int(margin_y0 > margin_y1)

        # ── F9: Asset turnover up ──
        if ("revenue_y0" in ltm and "revenue_y1" in ltm
                and bs_y0 is not None and bs_y1 is not None
                and _nonzero(bs_y0.get("total_assets")) and _nonzero(bs_y1.get("total_assets"))):
            at_y0 = ltm["revenue_y0"] / bs_y0["total_assets"]
            at_y1 = ltm["revenue_y1"] / bs_y1["total_assets"]
            score["asset_turnover_up"] = int(at_y0 > at_y1)

        # ── F-Score: sum of non-null factors ──
        factor_cols = [
            "roa_positive", "cfo_positive", "roa_improving", "accruals_quality",
            "leverage_down", "liquidity_up", "no_dilution", "gross_margin_up",
            "asset_turnover_up",
        ]
        factor_vals = [score.get(c) for c in factor_cols if score.get(c) is not None]
        if factor_vals:
            score["f_score"] = sum(factor_vals)

        rows.append(score)

    df = pd.DataFrame(rows)

    # Ensure all columns exist
    all_cols = [
        "sid", "f_score", "roa_positive", "cfo_positive", "roa_improving",
        "accruals_quality", "leverage_down", "liquidity_up", "no_dilution",
        "gross_margin_up", "asset_turnover_up",
    ]
    for col in all_cols:
        if col not in df.columns:
            df[col] = None

    # Convert factor columns to nullable int
    int_cols = all_cols[1:]  # everything except sid
    for col in int_cols:
        df[col] = df[col].astype("Int64")  # pandas nullable integer

    return df[all_cols]


def _nonzero(val):
    """Check value is not None, not NaN, and not zero."""
    if val is None:
        return False
    if isinstance(val, float) and (np.isnan(val) or val == 0):
        return False
    return val != 0


def compute(dry_run=False):
    """Main entry point. Returns row count."""
    stocks, qi, bs, cf = _load_data()
    df = _compute_scores(stocks, qi, bs, cf)

    snapshot = date.today().isoformat()
    df["snapshot_date"] = snapshot

    # Convert nullable Int64 to Python int/None for SQLite
    int_cols = [
        "f_score", "roa_positive", "cfo_positive", "roa_improving",
        "accruals_quality", "leverage_down", "liquidity_up", "no_dilution",
        "gross_margin_up", "asset_turnover_up",
    ]
    for col in int_cols:
        df[col] = df[col].apply(lambda x: int(x) if pd.notna(x) else None)

    scored = df["f_score"].notna().sum()
    mean_f = df["f_score"].dropna().mean()

    print(f"Piotroski: {len(df)} stocks, {scored} scored, mean F={mean_f:.1f}")
    print(f"F-Score distribution:")
    print(df["f_score"].value_counts().sort_index().to_string())

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    rows = upsert_df(df, "piotroski_scores")
    print(f"Saved {rows} rows to piotroski_scores (snapshot={snapshot})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
