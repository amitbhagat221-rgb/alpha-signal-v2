"""
Alpha Signal v2 — Small-Cap Quality Gate

Three-tier graduated design:
  Tier 1 HARD EXCLUSION: uninvestable (~15%)
  Tier 2 HEAVY PENALTY: high risk, stays in universe (capped -0.60)
  Tier 3 QUALITY COMPOSITE: positive quality signal

Only applied to SMALL cap stocks. LARGE/MID pass through unchanged.

Reads: piotroski_scores, forensic_scores, shareholding, quarterly_income,
       annual_cash_flow, stock_prices, stocks
Writes: Returns gate results (consumed by screener, not stored separately)

Usage:
    python -m scoring.quality_gate            # compute and print stats
    python -m scoring.quality_gate --dry-run  # same
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import QUALITY_GATE as QG
from db import read_sql


def _load_data():
    """Load all data needed for quality gate."""
    stocks = read_sql("SELECT sid, cap_tier FROM stocks WHERE cap_tier = 'SMALL'")

    piotroski = read_sql(
        "SELECT sid, f_score FROM piotroski_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM piotroski_scores GROUP BY sid)"
    )

    forensic = read_sql(
        "SELECT sid, m_score, m_score_flag, z_score, z_score_flag FROM forensic_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM forensic_scores GROUP BY sid)"
    )

    # Latest shareholding (pledge %)
    shareholding = read_sql(
        "SELECT sid, pledge_pct FROM shareholding "
        "WHERE (sid, end_date) IN (SELECT sid, MAX(end_date) FROM shareholding GROUP BY sid)"
    )

    # Annual income for loss detection — last 3 years
    qi = read_sql(
        "SELECT sid, period, net_income FROM quarterly_income ORDER BY sid, period"
    )

    # FCF for last 3 years
    cf = read_sql(
        "SELECT sid, period, free_cash_flow FROM annual_cash_flow ORDER BY sid, period"
    )

    # Price data existence check
    has_price = read_sql(
        "SELECT DISTINCT sid FROM stock_prices WHERE close > 0"
    )

    return stocks, piotroski, forensic, shareholding, qi, cf, has_price


def compute_quality_gate():
    """
    Compute quality gate for all SMALL cap stocks.
    Returns DataFrame: sid, gate_status, quality_penalty, quality_composite
    """
    stocks, piotroski, forensic, shareholding, qi, cf, has_price = _load_data()

    price_sids = set(has_price["sid"])
    pio_map = piotroski.set_index("sid")["f_score"].to_dict()
    forensic_map = forensic.set_index("sid").to_dict("index")
    pledge_map = shareholding.set_index("sid")["pledge_pct"].to_dict()

    # Compute annual net income per stock (sum of 4 quarters per year)
    # Simple: check if latest 3 fiscal years had net losses
    qi_by_sid = dict(list(qi.groupby("sid")))
    cf_by_sid = dict(list(cf.groupby("sid")))

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid, "gate_status": "PASS", "quality_penalty": 0.0, "quality_composite": None}

        # ── TIER 1: HARD EXCLUSIONS ──

        # No price data
        if sid not in price_sids:
            row["gate_status"] = "EXCLUDED"
            rows.append(row)
            continue

        # 3yr consecutive loss
        qi_g = qi_by_sid.get(sid)
        if qi_g is not None and len(qi_g) >= 12:
            # Check last 3 fiscal years (each = 4 quarters)
            sorted_qi = qi_g.sort_values("period")
            recent_12 = sorted_qi.tail(12)
            year_sums = [recent_12.iloc[i*4:(i+1)*4]["net_income"].sum() for i in range(3)]
            if all(s < 0 for s in year_sums if pd.notna(s)) and len([s for s in year_sums if pd.notna(s)]) >= 2:
                row["gate_status"] = "EXCLUDED"
                rows.append(row)
                continue

        # Negative equity (from forensic Z-score context)
        fdata = forensic_map.get(sid, {})
        z = fdata.get("z_score")
        if z is not None and z < QG["min_altman_z_exclude"]:
            row["gate_status"] = "EXCLUDED"
            rows.append(row)
            continue

        # Piotroski F <= 1
        f_score = pio_map.get(sid)
        if f_score is not None and f_score <= QG["min_piotroski_exclude"]:
            row["gate_status"] = "EXCLUDED"
            rows.append(row)
            continue

        # ── TIER 2: HEAVY PENALTIES ──
        penalty = 0.0

        # Loss in majority of years (2/3)
        if qi_g is not None and len(qi_g) >= 8:
            sorted_qi = qi_g.sort_values("period")
            recent_8 = sorted_qi.tail(8)
            y1 = recent_8.iloc[:4]["net_income"].sum()
            y2 = recent_8.iloc[4:8]["net_income"].sum()
            loss_count = sum(1 for s in [y1, y2] if pd.notna(s) and s < 0)
            if loss_count >= 1 and qi_g is not None and len(qi_g) >= 12:
                recent_12 = qi_g.sort_values("period").tail(12)
                y3 = recent_12.iloc[:4]["net_income"].sum()
                total_loss = sum(1 for s in [y1, y2, y3] if pd.notna(s) and s < 0)
                if total_loss >= 2:
                    penalty += QG["penalty_loss_majority"]

        # Negative 3yr cumulative FCF
        cf_g = cf_by_sid.get(sid)
        if cf_g is not None and len(cf_g) >= 3:
            cf_sorted = cf_g.sort_values("period")
            fcf_3yr = cf_sorted.tail(3)["free_cash_flow"].sum()
            if pd.notna(fcf_3yr) and fcf_3yr < 0:
                penalty += QG["penalty_neg_fcf_3yr"]

        # Pledge > 50%
        pledge = pledge_map.get(sid)
        if pd.notna(pledge) and pledge > QG["pledge_high_pct"]:
            penalty += QG["penalty_pledge_high"]

        # Piotroski F = 2-3
        if f_score is not None and QG["piotroski_low_range"][0] <= f_score <= QG["piotroski_low_range"][1]:
            penalty += QG["penalty_low_piotroski"]

        # Altman Z grey zone (0.5-1.1)
        if z is not None and QG["altman_grey_range"][0] <= z <= QG["altman_grey_range"][1]:
            penalty += QG["penalty_altman_grey"]

        # Beneish M > -1.78 (use 6-factor adjusted threshold from forensic)
        m_flag = fdata.get("m_score_flag")
        if m_flag == "LIKELY_MANIPULATOR":
            penalty += QG["penalty_beneish_flag"]

        # Cap total penalty
        penalty = max(penalty, QG["penalty_cap"])

        if penalty < 0:
            row["gate_status"] = "PENALISED"
            row["quality_penalty"] = round(penalty, 4)

        # ── TIER 3: QUALITY COMPOSITE ──
        # (computed for all non-excluded stocks, used as a positive signal)
        composite_parts = {}
        weights = QG["composite_weights"]

        if f_score is not None:
            composite_parts["piotroski"] = f_score / 9.0  # normalize to 0-1

        if cf_g is not None and len(cf_g) >= 1:
            cf_latest = cf_g.sort_values("period").iloc[-1]
            # CFO/EBITDA proxy: use operating_cash_flow / (abs(net_income) + 1) as rough proxy
            # since we don't have EBITDA per stock here
            ocf = cf_latest.get("free_cash_flow")  # use FCF as proxy
            if pd.notna(ocf):
                composite_parts["cfo_ebitda"] = min(1.0, max(0.0, 0.5 + ocf / 1000))  # rough scaling

        if z is not None:
            composite_parts["altman_z"] = min(1.0, max(0.0, z / 10.0))  # scale to 0-1

        if pd.notna(pledge):
            composite_parts["pledge"] = 1.0 - pledge / 100.0

        if cf_g is not None and len(cf_g) >= 3:
            cf_sorted = cf_g.sort_values("period")
            fcf_positive = (cf_sorted.tail(3)["free_cash_flow"] > 0).sum()
            composite_parts["fcf_years"] = fcf_positive / 3.0

        m = fdata.get("m_score")
        if m is not None:
            composite_parts["beneish"] = min(1.0, max(0.0, (-m - 1.0) / 5.0))  # scale: lower M = better

        # Weighted average
        if composite_parts:
            num = sum(weights.get(k, 0) * v for k, v in composite_parts.items())
            den = sum(weights.get(k, 0) for k in composite_parts)
            if den > 0:
                row["quality_composite"] = round(num / den, 4)

        rows.append(row)

    return pd.DataFrame(rows)


def compute(dry_run=False):
    """Main entry point."""
    df = compute_quality_gate()

    excluded = (df["gate_status"] == "EXCLUDED").sum()
    penalised = (df["gate_status"] == "PENALISED").sum()
    passed = (df["gate_status"] == "PASS").sum()
    total = len(df)

    print(f"Quality Gate (SMALL cap only): {total} stocks")
    print(f"  EXCLUDED:  {excluded} ({excluded/total*100:.1f}%)")
    print(f"  PENALISED: {penalised} ({penalised/total*100:.1f}%)")
    print(f"  PASS:      {passed} ({passed/total*100:.1f}%)")

    if df["quality_composite"].notna().any():
        print(f"  Composite: mean={df['quality_composite'].dropna().mean():.3f}")

    return len(df)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
