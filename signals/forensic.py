"""
Alpha Signal v2 — Forensic Guard (Beneish M-Score + Altman Z-Score)

Altman Z'' (emerging market, 4-factor):
  Full computation — all data available. ~2,385 stocks.

Beneish M-Score (reduced 6-factor):
  GMI (needs COGS) and SGAI (needs SGA) unavailable from Tickertape.
  Uses 6 of 8 components: DSRI, AQI, SGI, DEPI, TATA, LVGI.
  Thresholds adjusted conservatively for the reduced model.
  v1 covered only 399 stocks (yfinance). v2 covers ~2,000+ (Tickertape fundamentals).

Financial Services excluded (leverage ratios meaningless for banks).

Reads: quarterly_income, annual_balance_sheet, annual_cash_flow, stocks
Writes: forensic_scores

Usage:
    python -m signals.forensic            # compute and save
    python -m signals.forensic --dry-run  # compute but don't save
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SCREEN, FORENSIC
from db import read_sql, upsert_df

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

# Beneish full 8-factor coefficients (for reference)
# M = -4.84 + 0.920*DSRI + 0.528*GMI + 0.404*AQI + 0.892*SGI
#           + 0.115*DEPI - 0.172*SGAI + 4.679*TATA - 0.327*LVGI
#
# Reduced 6-factor (drop GMI, SGAI — unavailable from Tickertape):
# M_reduced = -4.84 + 0.920*DSRI + 0.404*AQI + 0.892*SGI
#                    + 0.115*DEPI + 4.679*TATA - 0.327*LVGI
#
# Missing GMI (~0.528 * ~1.0 = +0.53) and SGAI (~-0.172 * ~1.0 = -0.17)
# Net bias: reduced model is ~0.36 lower than full model on average.
# Conservative threshold adjustment: shift thresholds down by 0.36.

BENEISH_COEFFICIENTS = {
    "intercept": -4.84,
    "DSRI": 0.920,
    "AQI": 0.404,
    "SGI": 0.892,
    "DEPI": 0.115,
    "TATA": 4.679,
    "LVGI": -0.327,
}

# Adjusted thresholds for 6-factor model
# Dropping GMI (+0.53 avg) and SGAI (-0.17 avg) shifts scores down ~0.30.
# Raise thresholds (less negative) so that the shifted scores maintain similar flag rates.
# Conservative: +0.50 to reduce false positives in the broader universe.
BENEISH_GREY_6F = FORENSIC["beneish_grey"] + 0.50   # -1.72
BENEISH_RED_6F = FORENSIC["beneish_red"] + 0.50     # -1.28

# Altman Z'' (emerging market variant)
# Z'' = 3.25 + 6.56*X1 + 3.26*X2 + 6.72*X3 + 1.05*X4
ALTMAN_COEFFICIENTS = {
    "intercept": 3.25,
    "X1_WC_TA": 6.56,
    "X2_RE_TA": 3.26,
    "X3_EBIT_TA": 6.72,
    "X4_EQ_TL": 1.05,
}


def _load_data():
    """Load all inputs."""
    stocks = read_sql("SELECT sid, sector FROM stocks")
    financial_sids = set(stocks[stocks["sector"].isin(FINANCIAL_SECTORS)]["sid"])

    qi = read_sql(
        "SELECT sid, period, end_date, reporting, revenue, net_income, pbt, interest "
        "FROM quarterly_income ORDER BY sid, end_date"
    )
    # Prefer consolidated
    has_consol = set(qi[qi["reporting"] == "consolidated"]["sid"])
    qi = qi[
        ((qi["sid"].isin(has_consol)) & (qi["reporting"] == "consolidated"))
        | (~qi["sid"].isin(has_consol))
    ]

    bs = read_sql(
        "SELECT sid, period, total_assets, total_equity, current_assets, "
        "current_liabilities, receivables, retained_earnings, net_ppe, "
        "total_liabilities, long_term_debt "
        "FROM annual_balance_sheet ORDER BY sid, period"
    )

    cf = read_sql(
        "SELECT sid, period, operating_cash_flow, depreciation "
        "FROM annual_cash_flow ORDER BY sid, period"
    )

    return stocks, financial_sids, qi, bs, cf


def _safe_div(a, b):
    """Safe division — returns None if b is 0/None/NaN."""
    if b is None or pd.isna(b) or b == 0:
        return None
    if a is None or pd.isna(a):
        return None
    return a / b


def _compute_beneish(qi_group, bs_y0, bs_y1, cf_y0):
    """Compute reduced 6-factor Beneish M-Score."""
    if bs_y0 is None or bs_y1 is None:
        return None

    qi_sorted = qi_group.sort_values("end_date")
    if len(qi_sorted) < 8:
        return None

    # LTM revenue Y0 and Y-1
    rev_y0 = qi_sorted.tail(4)["revenue"].sum()
    rev_y1 = qi_sorted.iloc[-8:-4]["revenue"].sum()
    ni_y0 = qi_sorted.tail(4)["net_income"].sum()

    components = {}

    # DSRI: (Receivables_curr / Revenue_curr) / (Receivables_prev / Revenue_prev)
    dsri_num = _safe_div(bs_y0.get("receivables"), rev_y0)
    dsri_den = _safe_div(bs_y1.get("receivables"), rev_y1)
    components["DSRI"] = _safe_div(dsri_num, dsri_den) if dsri_num and dsri_den else None

    # AQI: (1 - (CA + PPE) / TA)_curr / (1 - (CA + PPE) / TA)_prev
    # Simplified: no securities term (unavailable)
    ta_y0, ta_y1 = bs_y0.get("total_assets"), bs_y1.get("total_assets")
    if ta_y0 and ta_y1 and ta_y0 != 0 and ta_y1 != 0:
        ca_ppe_y0 = (bs_y0.get("current_assets") or 0) + (bs_y0.get("net_ppe") or 0)
        ca_ppe_y1 = (bs_y1.get("current_assets") or 0) + (bs_y1.get("net_ppe") or 0)
        aqi_num = 1 - ca_ppe_y0 / ta_y0
        aqi_den = 1 - ca_ppe_y1 / ta_y1
        components["AQI"] = _safe_div(aqi_num, aqi_den)

    # SGI: Revenue_curr / Revenue_prev
    components["SGI"] = _safe_div(rev_y0, rev_y1)

    # DEPI: (Dep_prev / (Dep_prev + PPE_prev)) / (Dep_curr / (Dep_curr + PPE_curr))
    if cf_y0 is not None:
        dep_y0 = cf_y0.get("depreciation") or 0
        ppe_y0 = bs_y0.get("net_ppe") or 0
        ppe_y1 = bs_y1.get("net_ppe") or 0
        # We only have Y0 depreciation from cash flow; use same for both (conservative)
        # This slightly biases DEPI toward 1.0 (neutral)
        depi_num = _safe_div(dep_y0, dep_y0 + ppe_y1) if (dep_y0 + ppe_y1) != 0 else None
        depi_den = _safe_div(dep_y0, dep_y0 + ppe_y0) if (dep_y0 + ppe_y0) != 0 else None
        components["DEPI"] = _safe_div(depi_num, depi_den)

    # TATA: (NI - OCF) / TA
    if cf_y0 is not None and pd.notna(cf_y0.get("operating_cash_flow")) and ta_y0 and ta_y0 != 0:
        components["TATA"] = (ni_y0 - cf_y0["operating_cash_flow"]) / ta_y0

    # LVGI: ((CL + LTD) / TA)_curr / ((CL + LTD) / TA)_prev
    lev_y0 = _safe_div(
        (bs_y0.get("current_liabilities") or 0) + (bs_y0.get("long_term_debt") or 0), ta_y0
    )
    lev_y1 = _safe_div(
        (bs_y1.get("current_liabilities") or 0) + (bs_y1.get("long_term_debt") or 0), ta_y1
    )
    components["LVGI"] = _safe_div(lev_y0, lev_y1) if lev_y0 is not None and lev_y1 is not None else None

    # Clip component ratios to reasonable ranges (prevent division-by-tiny-number blowups)
    RATIO_CLIP = {"DSRI": (0, 5), "AQI": (-2, 5), "SGI": (0, 5),
                  "DEPI": (0, 5), "TATA": (-1, 1), "LVGI": (0, 5)}
    for k in list(components.keys()):
        v = components[k]
        if v is not None and not pd.isna(v):
            lo, hi = RATIO_CLIP.get(k, (-10, 10))
            components[k] = max(lo, min(hi, v))

    # Need at least 5 of 6 components to compute a score (pre-2026-05-24 it
    # was 4-of-6 with missing components substituted as 1.0=neutral — that
    # silently understated manipulation flags for partial-data stocks).
    valid = {k: v for k, v in components.items() if v is not None and not pd.isna(v)}
    if len(valid) < 5:
        return None

    # Compute M-Score. For the at-most-1 missing component, substitute 1.0
    # (Beneish's neutral ratio for multiplicative inputs). With a 5-of-6
    # floor, the rescaling impact of a single missing ratio is bounded.
    m = BENEISH_COEFFICIENTS["intercept"]
    for comp, coeff in BENEISH_COEFFICIENTS.items():
        if comp == "intercept":
            continue
        m += coeff * valid.get(comp, 1.0)

    return round(m, 4)


def _compute_altman(bs_y0, qi_group, cf_y0):
    """Compute Altman Z'' (emerging market variant)."""
    if bs_y0 is None:
        return None

    ta = bs_y0.get("total_assets")
    if not ta or pd.isna(ta) or ta == 0:
        return None

    # X1: Working Capital / Total Assets
    ca = bs_y0.get("current_assets")
    cl = bs_y0.get("current_liabilities")
    if pd.notna(ca) and pd.notna(cl):
        x1 = (ca - cl) / ta
    else:
        return None

    # X2: Retained Earnings / Total Assets
    re = bs_y0.get("retained_earnings")
    if pd.notna(re):
        x2 = re / ta
    else:
        # Fallback: equity * 0.5
        eq = bs_y0.get("total_equity")
        if pd.notna(eq):
            x2 = (eq * 0.5) / ta
        else:
            return None

    # X3: EBIT / Total Assets
    # Use LTM (pbt + interest) as EBIT proxy since operating_profit is 100% NULL
    qi_sorted = qi_group.sort_values("end_date") if qi_group is not None else pd.DataFrame()
    if len(qi_sorted) >= 4:
        pbt_ltm = qi_sorted.tail(4)["pbt"].sum()
        interest_ltm = qi_sorted.tail(4)["interest"].fillna(0).sum()
        ebit = pbt_ltm + interest_ltm
        x3 = ebit / ta
    else:
        return None

    # X4: Book Equity / Total Liabilities
    eq = bs_y0.get("total_equity")
    tl = bs_y0.get("total_liabilities")
    if pd.notna(eq) and pd.notna(tl) and tl != 0:
        x4 = eq / tl
    else:
        return None

    # Clip components to prevent extreme outliers from tiny denominators
    x1 = max(-1, min(1, x1))
    x2 = max(-2, min(2, x2))
    x3 = max(-1, min(1, x3))
    x4 = max(-5, min(20, x4))   # equity/liabilities can legitimately be high for debt-free cos

    z = (ALTMAN_COEFFICIENTS["intercept"]
         + ALTMAN_COEFFICIENTS["X1_WC_TA"] * x1
         + ALTMAN_COEFFICIENTS["X2_RE_TA"] * x2
         + ALTMAN_COEFFICIENTS["X3_EBIT_TA"] * x3
         + ALTMAN_COEFFICIENTS["X4_EQ_TL"] * x4)

    return round(z, 4)


def _flag_m_score(m):
    """Flag Beneish M-Score (using 6-factor adjusted thresholds)."""
    if m is None or pd.isna(m):
        return None
    if m > BENEISH_RED_6F:
        return "LIKELY_MANIPULATOR"
    if m > BENEISH_GREY_6F:
        return "POSSIBLE_MANIPULATOR"
    return "CLEAN"


def _flag_z_score(z):
    """Flag Altman Z-Score."""
    if z is None or pd.isna(z):
        return None
    if z < FORENSIC["altman_distress"]:
        return "DISTRESS"
    if z < FORENSIC["altman_grey"]:
        return "GREY_ZONE"
    return "SAFE"


def _compute_penalty(m_flag, z_flag):
    """Compute score penalty from forensic flags."""
    penalty = 0.0
    if m_flag == "LIKELY_MANIPULATOR":
        penalty -= 0.20
    elif m_flag == "POSSIBLE_MANIPULATOR":
        penalty -= 0.10
    if z_flag == "DISTRESS":
        penalty -= 0.20
    elif z_flag == "GREY_ZONE":
        penalty -= 0.10
    return penalty


def _compute_scores(stocks, financial_sids, qi, bs, cf):
    """Compute forensic scores for all non-financial stocks."""
    qi_by_sid = dict(list(qi.groupby("sid")))
    bs_by_sid = dict(list(bs.groupby("sid")))
    cf_by_sid = dict(list(cf.groupby("sid")))

    rows = []
    for _, stock in stocks.iterrows():
        sid = stock["sid"]

        if sid in financial_sids:
            rows.append({"sid": sid})
            continue

        row = {"sid": sid}

        qi_g = qi_by_sid.get(sid)
        bs_g = bs_by_sid.get(sid)
        cf_g = cf_by_sid.get(sid)

        bs_y0, bs_y1 = None, None
        if bs_g is not None and len(bs_g) >= 1:
            bs_sorted = bs_g.sort_values("period")
            bs_y0 = bs_sorted.iloc[-1]
            if len(bs_sorted) >= 2:
                bs_y1 = bs_sorted.iloc[-2]

        cf_y0 = None
        if cf_g is not None and len(cf_g) >= 1:
            cf_y0 = cf_g.sort_values("period").iloc[-1]

        # Beneish M-Score (reduced 6-factor)
        if qi_g is not None:
            m = _compute_beneish(qi_g, bs_y0, bs_y1, cf_y0)
            if m is not None:
                row["m_score"] = m
                row["m_score_flag"] = _flag_m_score(m)

        # Altman Z-Score
        z = _compute_altman(bs_y0, qi_g, cf_y0)
        if z is not None:
            row["z_score"] = z
            row["z_score_flag"] = _flag_z_score(z)

        # Penalty
        row["penalty"] = _compute_penalty(row.get("m_score_flag"), row.get("z_score_flag"))

        rows.append(row)

    df = pd.DataFrame(rows)

    out_cols = ["sid", "m_score", "m_score_flag", "z_score", "z_score_flag", "penalty"]
    for col in out_cols:
        if col not in df.columns:
            df[col] = None

    return df[out_cols]


def compute(dry_run=False):
    """Main entry point. Returns row count."""
    stocks, financial_sids, qi, bs, cf = _load_data()
    df = _compute_scores(stocks, financial_sids, qi, bs, cf)

    snapshot = date.today().isoformat()
    df["snapshot_date"] = snapshot

    has_m = df["m_score"].notna().sum()
    has_z = df["z_score"].notna().sum()

    print(f"Forensic: {len(df)} stocks")
    print(f"  M-Score (6-factor): {has_m} stocks (v1 had 399 via yfinance)")
    print(f"  Z-Score (Z''): {has_z} stocks")

    if has_m > 0:
        print(f"  M-Score flags: {df['m_score_flag'].value_counts().to_dict()}")
    if has_z > 0:
        print(f"  Z-Score flags: {df['z_score_flag'].value_counts().to_dict()}")

    penalized = (df["penalty"] < 0).sum()
    print(f"  Penalized stocks: {penalized}")

    if dry_run:
        print("\nDry run — not saving.")
        return len(df)

    rows = upsert_df(df, "forensic_scores")
    print(f"Saved {rows} rows to forensic_scores (snapshot={snapshot})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
