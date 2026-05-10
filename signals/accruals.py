"""
Alpha Signal v2 — Accruals Quality Signal

Four components:
  1. CF Accruals Ratio:  (LTM_NI - OCF_Y0) / avg_assets  (lower = better)
  2. BS Accruals Ratio:  Sloan 1996 balance-sheet accruals  (lower = better)
  3. EPS CV:             std(EPS_8Q) / |mean(EPS_8Q)|  (lower = better)
  4. Earnings Beat Rate: weighted YoY beat count  (higher = better)

Composite: within-segment percentile rank, weighted average with NaN tolerance.
Financial sector excluded from CF/BS accruals only (EPS CV + beat rate still computed).

Reads: quarterly_income, annual_balance_sheet, annual_cash_flow, stocks
Writes: accruals_scores

Usage:
    python -m signals.accruals            # compute and save
    python -m signals.accruals --dry-run  # compute but don't save
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN
from db import get_db, read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

# Composite weights
WEIGHTS = {"cf": 0.35, "bs": 0.35, "cv": 0.15, "beat": 0.15}

# Loss-year dampening threshold
LOSS_EPS_THRESHOLD = 0.50
LOSS_DAMPENING = 0.5

# Q4 (March end) down-weight for beat rate
Q4_WEIGHT = 0.6


def _load_data():
    """Load all inputs from DB."""
    stocks = read_sql("SELECT sid, sector, cap_tier FROM stocks")

    qi = read_sql(
        "SELECT sid, period, end_date, reporting, net_income, eps, pbt, interest "
        "FROM quarterly_income ORDER BY sid, end_date"
    )
    # Prefer consolidated
    has_consol = set(qi[qi["reporting"] == "consolidated"]["sid"])
    qi = qi[
        ((qi["sid"].isin(has_consol)) & (qi["reporting"] == "consolidated"))
        | (~qi["sid"].isin(has_consol))
    ]

    bs = read_sql(
        "SELECT sid, period, total_assets, current_assets, current_liabilities, "
        "total_debt, long_term_debt, cash_and_equivalents "
        "FROM annual_balance_sheet ORDER BY sid, period"
    )

    cf = read_sql(
        "SELECT sid, period, operating_cash_flow, depreciation "
        "FROM annual_cash_flow ORDER BY sid, period"
    )

    return stocks, qi, bs, cf


def _cf_accruals(qi_group, cf_group, bs_group):
    """CF accruals ratio = (LTM_NI - OCF_Y0) / avg_assets."""
    qi_sorted = qi_group.sort_values("end_date")
    if len(qi_sorted) < 4:
        return None

    ltm_ni = qi_sorted.tail(4)["net_income"].sum()
    if pd.isna(ltm_ni):
        return None

    cf_sorted = cf_group.sort_values("period")
    ocf_y0 = cf_sorted.iloc[-1]["operating_cash_flow"]
    if pd.isna(ocf_y0):
        return None

    bs_sorted = bs_group.sort_values("period")
    assets_y0 = bs_sorted.iloc[-1]["total_assets"]
    if pd.isna(assets_y0) or assets_y0 == 0:
        return None

    if len(bs_sorted) >= 2:
        assets_y1 = bs_sorted.iloc[-2]["total_assets"]
        avg_assets = (assets_y0 + assets_y1) / 2 if pd.notna(assets_y1) else assets_y0
    else:
        avg_assets = assets_y0

    if avg_assets == 0:
        return None

    return (ltm_ni - ocf_y0) / avg_assets


def _bs_accruals(bs_group, cf_group):
    """BS accruals ratio (Sloan 1996) = [(ΔCA-ΔCash) - (ΔCL-ΔSTD) - Dep] / avg_assets."""
    bs_sorted = bs_group.sort_values("period")
    if len(bs_sorted) < 2:
        return None

    y0 = bs_sorted.iloc[-1]
    y1 = bs_sorted.iloc[-2]

    # Need all balance sheet components
    for col in ["total_assets", "current_assets", "current_liabilities"]:
        if pd.isna(y0.get(col)) or pd.isna(y1.get(col)):
            return None

    delta_ca = y0["current_assets"] - y1["current_assets"]
    delta_cash = (y0.get("cash_and_equivalents") or 0) - (y1.get("cash_and_equivalents") or 0)
    delta_cl = y0["current_liabilities"] - y1["current_liabilities"]

    # Short-term debt = total_debt - long_term_debt
    std_y0 = (y0.get("total_debt") or 0) - (y0.get("long_term_debt") or 0)
    std_y1 = (y1.get("total_debt") or 0) - (y1.get("long_term_debt") or 0)
    delta_std = std_y0 - std_y1

    # Depreciation from cash flow
    cf_sorted = cf_group.sort_values("period")
    dep = cf_sorted.iloc[-1].get("depreciation") or 0 if len(cf_sorted) > 0 else 0

    avg_assets = (y0["total_assets"] + y1["total_assets"]) / 2
    if avg_assets == 0:
        return None

    return ((delta_ca - delta_cash) - (delta_cl - delta_std) - dep) / avg_assets


def _eps_cv(qi_group):
    """EPS coefficient of variation over last 8 quarters."""
    qi_sorted = qi_group.sort_values("end_date")
    eps_vals = qi_sorted.tail(8)["eps"].dropna()

    if len(eps_vals) < 4:
        return None, False

    mean_eps = eps_vals.mean()
    if mean_eps == 0:
        return None, False

    cv = eps_vals.std() / abs(mean_eps)

    # Loss-year dampening
    dampened = eps_vals.min() < LOSS_EPS_THRESHOLD
    if dampened:
        cv *= LOSS_DAMPENING

    return cv, dampened


def _beat_rate(qi_group):
    """Weighted YoY earnings beat rate over last 4 quarters (needs 8Q)."""
    qi_sorted = qi_group.sort_values("end_date")
    if len(qi_sorted) < 8:
        return None, False

    recent = qi_sorted.tail(8).reset_index(drop=True)
    total_weight = 0
    beat_weight = 0

    # Compare quarters 4-7 (recent) vs 0-3 (prior year)
    for i in range(4):
        ni_now = recent.iloc[i + 4]["net_income"]
        ni_prev = recent.iloc[i]["net_income"]

        if pd.isna(ni_now) or pd.isna(ni_prev):
            continue

        end_date_str = recent.iloc[i + 4].get("end_date", "")
        month = 0
        if end_date_str and len(str(end_date_str)) >= 7:
            try:
                month = int(str(end_date_str)[5:7])
            except (ValueError, IndexError):
                pass

        w = Q4_WEIGHT if month == 3 else 1.0
        total_weight += w
        if ni_now > ni_prev:
            beat_weight += w

    if total_weight == 0:
        return None, False

    rate = beat_weight / total_weight

    # Loss-year dampening
    eps_vals = qi_sorted.tail(8)["eps"].dropna()
    dampened = len(eps_vals) > 0 and eps_vals.min() < LOSS_EPS_THRESHOLD
    if dampened:
        rate *= LOSS_DAMPENING

    return rate, dampened


def _compute_composite(df):
    """Within-segment percentile rank → weighted average composite."""
    # Percentile rank within cap_tier
    # CF and BS: lower = better → invert
    # CV: lower = better → invert
    # Beat: higher = better → keep
    df = df.copy()

    for tier in df["cap_tier"].dropna().unique():
        mask = df["cap_tier"] == tier
        tier_df = df.loc[mask]

        df.loc[mask, "cf_score"] = 1 - tier_df["cf_accruals_ratio"].rank(pct=True)
        df.loc[mask, "bs_score"] = 1 - tier_df["bs_accruals_ratio"].rank(pct=True)
        df.loc[mask, "cv_score"] = 1 - tier_df["earnings_persistence"].rank(pct=True)
        df.loc[mask, "beat_score"] = tier_df["beat_rate"].rank(pct=True)

    # Weighted average with NaN tolerance
    score_cols = {"cf": "cf_score", "bs": "bs_score", "cv": "cv_score", "beat": "beat_score"}
    signals = []

    for _, row in df.iterrows():
        num, den = 0.0, 0.0
        for key, col in score_cols.items():
            val = row.get(col)
            if pd.notna(val):
                num += WEIGHTS[key] * val
                den += WEIGHTS[key]
        signals.append(round(num / den, 4) if den > 0 else None)

    df["accruals_signal"] = signals
    return df


def _compute_scores(stocks, qi, bs, cf):
    """Compute accruals signal for all stocks."""
    qi_by_sid = dict(list(qi.groupby("sid")))
    bs_by_sid = dict(list(bs.groupby("sid")))
    cf_by_sid = dict(list(cf.groupby("sid")))

    financial_sids = set(stocks[stocks["sector"].isin(FINANCIAL_SECTORS)]["sid"])
    tier_map = stocks.set_index("sid")["cap_tier"].to_dict()

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid, "cap_tier": tier_map.get(sid)}

        qi_g = qi_by_sid.get(sid)
        bs_g = bs_by_sid.get(sid)
        cf_g = cf_by_sid.get(sid)

        is_financial = sid in financial_sids

        # CF accruals (skip financials)
        if not is_financial and qi_g is not None and cf_g is not None and bs_g is not None:
            row["cf_accruals_ratio"] = _cf_accruals(qi_g, cf_g, bs_g)

        # BS accruals (skip financials)
        if not is_financial and bs_g is not None and cf_g is not None:
            row["bs_accruals_ratio"] = _bs_accruals(bs_g, cf_g)

        # EPS CV (all stocks)
        if qi_g is not None:
            cv, _ = _eps_cv(qi_g)
            row["earnings_persistence"] = cv

        # Beat rate (all stocks, internal only — used for composite)
        if qi_g is not None:
            rate, _ = _beat_rate(qi_g)
            row["beat_rate"] = rate

        rows.append(row)

    df = pd.DataFrame(rows)

    # Compute composite
    df = _compute_composite(df)

    # Financials route through the financial sub-model (CLAUDE.md). The
    # accrual ratios are already NaN for them; drop the partial composite
    # too, otherwise EPS-CV + beat-rate alone would still produce a signal.
    df.loc[df["sid"].isin(financial_sids), "accruals_signal"] = None

    out_cols = ["sid", "cf_accruals_ratio", "bs_accruals_ratio",
                "earnings_persistence", "accruals_signal"]
    return df[out_cols]


def compute(dry_run=False):
    """Main entry point. Returns row count."""
    stocks, qi, bs, cf = _load_data()
    df = _compute_scores(stocks, qi, bs, cf)

    snapshot = date.today().isoformat()
    df["snapshot_date"] = snapshot

    has_signal = df["accruals_signal"].notna().sum()
    has_cf = df["cf_accruals_ratio"].notna().sum()
    has_bs = df["bs_accruals_ratio"].notna().sum()

    print(f"Accruals: {len(df)} stocks, {has_signal} with signal")
    print(f"  CF accruals: {has_cf} stocks, BS accruals: {has_bs} stocks")
    if has_signal > 0:
        print(f"  Signal mean={df['accruals_signal'].mean():.3f}, median={df['accruals_signal'].median():.3f}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    rows = upsert_df(df, "accruals_scores")
    print(f"Saved {rows} rows to accruals_scores (snapshot={snapshot})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
