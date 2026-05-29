"""
Alpha Signal v2 — Financial Signal (Phase 2.2b)

Per-stock composite score for Banks + NBFCs (158 stocks). The main screener's
quality signals (Piotroski, accruals, ROIC) don't apply — banks have no
inventory, COGS, or operating margin in the conventional sense. This module
replaces them with a banking-specific lens per Plan 0001 §2.2 + v1's
financial_model reference doc.

SCORE STRUCTURE (Plan 0001 weights, renormalized over present components):

    Asset Quality   40%   ← -(gross_npa_pct + 2 × net_npa_pct)
    Profitability   30%   ← 0.67 × NII margin + 0.33 × net-profit margin
    Capital         15%   ← NULL until Phase 2.2c (RBI fallback for CAR/CRAR)
    Moat / Funding  15%   ← -cost_of_funds_pct (proxy: low COF = CASA-rich for
                              banks; low COF = funding edge for NBFCs)

Each component z-scored within (industry, cap_tier) — banks scored against
banks of the same tier, NBFCs against NBFCs of the same tier. Clip to ±3.

Composite = renormalized weighted average over PRESENT components.
< 2 of 4 components present → INSUFFICIENT (no signal published).

Reads:  banking_metrics (Phase 2.2a-ii output)
Writes: financial_signal_scores

INPUTS PER STOCK (latest quarterly + latest annual from banking_metrics):
    gross_npa_pct, net_npa_pct          — quarterly
    interest_earned, net_interest_income, net_profit  — quarterly
    cost_of_funds_pct                    — annual

NOT USED YET (Phase 2.2c will add via RBI/SEBI fallback):
    casa_pct, pcr_pct, car_pct, crar_pct

Benchmark cutoffs (diagnostic; the score is z-relative, not gated):
    Banks    ROA ≥ 1.0% · NIM ≥ 3% · GNPA ≤ 3% · NNPA ≤ 1% · CASA ≥ 40% · CAR ≥ 15%
    NBFCs    NIM ≥ 6%   · GNPA ≤ 4% · D/E ≤ 4x · CRAR ≥ 18%
Source: v1 financial_model_reference + MDPI 2025 (NIM β=+0.583, NNPA β=-0.251).

Usage:
    python -m signals.financial_signal              # compute + save today
    python -m signals.financial_signal --dry-run    # compute + print top/bottom 10
    python -m signals.financial_signal --date YYYY-MM-DD   # backfill one date
"""

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, upsert_df

BANKING_INDUSTRIES = ("Banks", "NBFCs / Finance")

# Component weights (sum to 1.0). Renormalized at score-time over present
# components per stock — if Capital is NULL today, the other three become
# 40/(40+30+15) etc.
WEIGHTS = {
    "asset_quality": 0.40,
    "profitability": 0.30,
    "capital":       0.15,
    "funding":       0.15,
}

# Minimum components present to publish a score (otherwise INSUFFICIENT).
MIN_COMPONENTS = 2

# z-score clip range. Beyond ±3 the values are usually parse anomalies or
# segment-of-1 artifacts (e.g. only one MICRO NBFC scoring → undefined z).
Z_CLIP = 3.0

# Diagnostic benchmarks (from financial_model_reference). Not gates.
BANK_BENCHMARKS = {
    "roa_pct":      {"good": 1.0,  "caution": 0.5,  "bad": 0.0,  "direction": "higher"},
    "nim_pct":      {"good": 3.0,  "caution": 2.0,  "bad": 1.0,  "direction": "higher"},
    "gross_npa_pct":{"good": 3.0,  "caution": 5.0,  "bad": 10.0, "direction": "lower"},
    "net_npa_pct":  {"good": 1.0,  "caution": 2.0,  "bad": 4.0,  "direction": "lower"},
    "casa_pct":     {"good": 40.0, "caution": 30.0, "bad": 20.0, "direction": "higher"},
    "car_pct":      {"good": 15.0, "caution": 11.5, "bad": 9.0,  "direction": "higher"},
}
NBFC_BENCHMARKS = {
    "nim_pct":      {"good": 6.0,  "caution": 3.0,  "bad": 1.0,  "direction": "higher"},
    "gross_npa_pct":{"good": 4.0,  "caution": 6.0,  "bad": 10.0, "direction": "lower"},
    "de_ratio":     {"good": 4.0,  "caution": 6.0,  "bad": 10.0, "direction": "lower"},
    "crar_pct":     {"good": 18.0, "caution": 15.0, "bad": 12.0, "direction": "higher"},
}


def _load_inputs():
    """Load latest quarterly + latest annual per sid, joined with stocks meta.

    Returns DataFrame indexed by sid with columns:
      industry, cap_tier,
      gross_npa_pct, net_npa_pct, nii_q, ie_q, np_q,   (from latest quarterly)
      cof_pct                                            (from latest annual)
    """
    stocks = read_sql(
        f"SELECT sid, industry, cap_tier FROM stocks "
        f"WHERE industry IN ({','.join('?' * len(BANKING_INDUSTRIES))})",
        params=list(BANKING_INDUSTRIES),
    )

    # Latest quarterly per sid
    quarterly = read_sql(
        """
        WITH latest AS (
            SELECT sid, MAX(period_end) AS p
            FROM banking_metrics
            WHERE period_type='quarterly'
            GROUP BY sid
        )
        SELECT b.sid, b.period_end AS q_period,
               b.gross_npa_pct, b.net_npa_pct,
               b.interest_earned AS ie_q,
               b.net_interest_income AS nii_q,
               b.net_profit AS np_q
        FROM banking_metrics b
        JOIN latest l ON b.sid=l.sid AND b.period_end=l.p
        WHERE b.period_type='quarterly'
        """
    )

    # Latest annual per sid (for COF)
    annual = read_sql(
        """
        WITH latest AS (
            SELECT sid, MAX(period_end) AS p
            FROM banking_metrics
            WHERE period_type='annual'
            GROUP BY sid
        )
        SELECT b.sid, b.period_end AS a_period, b.cost_of_funds_pct AS cof_pct
        FROM banking_metrics b
        JOIN latest l ON b.sid=l.sid AND b.period_end=l.p
        WHERE b.period_type='annual'
        """
    )

    df = stocks.merge(quarterly, on="sid", how="left").merge(annual, on="sid", how="left")
    # Drop stocks with no banking_metrics rows at all (the 17 404s)
    df = df.dropna(subset=["q_period", "a_period"], how="all").copy()
    return df


def _compute_raw_components(df: pd.DataFrame) -> pd.DataFrame:
    """Compute raw component values (NOT yet z-scored)."""
    df = df.copy()

    # Asset quality — more negative = worse (high NPA). We invert at z-score
    # so higher z = better quality.
    # AQ raw = gross_npa + 2 × net_npa. NULL if BOTH inputs NULL.
    def _aq_raw(row):
        g = row["gross_npa_pct"]
        n = row["net_npa_pct"]
        if pd.isna(g) and pd.isna(n):
            return np.nan
        # If only one is present, use it (double-weight on NNPA still applies
        # if NNPA alone is given since it's a more pointed risk metric).
        if pd.isna(g):
            return 2.0 * n
        if pd.isna(n):
            return g
        return g + 2.0 * n
    df["aq_raw"] = df.apply(_aq_raw, axis=1)

    # Profitability — NII margin + 0.5 × NP margin (both as % of interest earned).
    # Inverted later? No — higher margin = better, so direction is "higher".
    def _p_raw(row):
        ie = row["ie_q"]
        nii = row["nii_q"]
        np_ = row["np_q"]
        if pd.isna(ie) or ie is None or ie == 0:
            return np.nan
        nii_margin = (nii / ie) * 100 if not pd.isna(nii) else np.nan
        np_margin = (np_ / ie) * 100 if not pd.isna(np_) else np.nan
        if pd.isna(nii_margin) and pd.isna(np_margin):
            return np.nan
        if pd.isna(nii_margin):
            return 0.5 * np_margin
        if pd.isna(np_margin):
            return nii_margin
        return (2.0/3.0) * nii_margin + (1.0/3.0) * np_margin
    df["p_raw"] = df.apply(_p_raw, axis=1)

    # Capital — NULL until Phase 2.2c.
    df["c_raw"] = np.nan

    # Funding — cost of funds. Lower COF = better moat (CASA proxy for banks;
    # genuine funding edge for NBFCs). Direction: lower.
    df["f_raw"] = df["cof_pct"]

    # Convenience columns for the output table
    df["nii_margin_pct"] = df.apply(
        lambda r: round((r["nii_q"] / r["ie_q"]) * 100, 2)
        if not pd.isna(r["nii_q"]) and r["ie_q"] and r["ie_q"] != 0 else np.nan, axis=1
    )
    df["np_margin_pct"] = df.apply(
        lambda r: round((r["np_q"] / r["ie_q"]) * 100, 2)
        if not pd.isna(r["np_q"]) and r["ie_q"] and r["ie_q"] != 0 else np.nan, axis=1
    )

    return df


def _zscore_within(df: pd.DataFrame, col: str, group_cols=("industry", "cap_tier"),
                   direction="higher") -> pd.Series:
    """Z-score `col` within (industry, cap_tier). Clip to ±Z_CLIP.

    direction='higher' → high raw = high z (good)
    direction='lower'  → low raw = high z (good; inverted)

    Returns Series aligned with df.index. NaN when raw is NaN OR when the
    segment has fewer than 2 non-NaN values (z undefined).
    """
    out = pd.Series(np.nan, index=df.index)
    for keys, g in df.groupby(list(group_cols)):
        vals = g[col].dropna()
        if len(vals) < 2:
            continue
        mu = vals.mean()
        sd = vals.std(ddof=0)
        if sd == 0 or pd.isna(sd):
            continue
        z = (g[col] - mu) / sd
        if direction == "lower":
            z = -z
        out.loc[g.index] = z.clip(-Z_CLIP, Z_CLIP)
    return out


def _compute_composite(df: pd.DataFrame) -> pd.DataFrame:
    """Renormalize weights over present components → composite score.

    < MIN_COMPONENTS present → financial_signal = NULL, score_basis = INSUFFICIENT.
    """
    df = df.copy()
    label_map = {
        "asset_quality_z": ("asset_quality", "AQ"),
        "profitability_z": ("profitability", "P"),
        "capital_z":       ("capital",       "C"),
        "funding_z":       ("funding",       "F"),
    }
    composites = []
    bases = []
    n_presents = []
    for _, row in df.iterrows():
        present = []
        num = 0.0
        denom = 0.0
        for col, (weight_key, label) in label_map.items():
            v = row.get(col)
            if v is None or pd.isna(v):
                continue
            w = WEIGHTS[weight_key]
            num += w * v
            denom += w
            present.append(label)
        n_presents.append(len(present))
        if len(present) < MIN_COMPONENTS or denom == 0:
            composites.append(np.nan)
            bases.append("INSUFFICIENT")
        else:
            score = num / denom
            composites.append(round(float(np.clip(score, -Z_CLIP, Z_CLIP)), 4))
            bases.append("+".join(present))
    df["financial_signal"] = composites
    df["score_basis"] = bases
    df["components_present"] = n_presents
    return df


def compute(snapshot_date: str | None = None, dry_run: bool = False) -> int:
    snapshot_date = snapshot_date or date.today().isoformat()

    df = _load_inputs()
    if df.empty:
        print("⚠ no banking_metrics inputs available")
        return 0

    df = _compute_raw_components(df)

    # Z-score each component within (industry, cap_tier)
    df["asset_quality_z"] = _zscore_within(df, "aq_raw", direction="lower")
    df["profitability_z"] = _zscore_within(df, "p_raw",  direction="higher")
    df["capital_z"]       = _zscore_within(df, "c_raw",  direction="higher")
    df["funding_z"]       = _zscore_within(df, "f_raw",  direction="lower")

    df = _compute_composite(df)
    df["snapshot_date"] = snapshot_date
    df["computed_at"]   = datetime.now().isoformat(timespec="seconds")

    schema_cols = [
        "sid", "snapshot_date", "industry", "cap_tier",
        "asset_quality_z", "profitability_z", "capital_z", "funding_z",
        "components_present", "score_basis", "financial_signal",
        "gross_npa_pct", "net_npa_pct", "nii_margin_pct", "np_margin_pct",
        "cost_of_funds_pct",
        "computed_at",
    ]
    # Map cof_pct → cost_of_funds_pct
    df["cost_of_funds_pct"] = df["cof_pct"]
    out = df[schema_cols].copy()

    if dry_run:
        n_scored = (out["financial_signal"].notna()).sum()
        n_insufficient = (out["score_basis"] == "INSUFFICIENT").sum()
        print(f"✓ {len(out)} stocks processed · {n_scored} scored · "
              f"{n_insufficient} INSUFFICIENT (dry-run, not written)")
        # Print top/bottom 10 per industry
        for ind in ("Banks", "NBFCs / Finance"):
            sub = out[(out["industry"] == ind) & out["financial_signal"].notna()]
            if sub.empty:
                continue
            print(f"\n  --- {ind} top-5 by financial_signal ---")
            print(sub.nlargest(5, "financial_signal")[
                ["sid","cap_tier","financial_signal","gross_npa_pct",
                 "nii_margin_pct","cost_of_funds_pct","score_basis"]
            ].to_string(index=False))
            print(f"\n  --- {ind} bottom-5 by financial_signal ---")
            print(sub.nsmallest(5, "financial_signal")[
                ["sid","cap_tier","financial_signal","gross_npa_pct",
                 "nii_margin_pct","cost_of_funds_pct","score_basis"]
            ].to_string(index=False))
        return n_scored

    n = upsert_df(out, "financial_signal_scores")
    print(f"✓ wrote {n} financial_signal_scores rows ({snapshot_date})")
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="snapshot_date YYYY-MM-DD (default today)")
    parser.add_argument("--dry-run", action="store_true",
                        help="compute + print top/bottom; don't write")
    args = parser.parse_args()
    compute(snapshot_date=args.date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
