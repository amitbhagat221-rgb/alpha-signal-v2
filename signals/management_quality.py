"""
Alpha Signal v2 — Management Quality Scorecard (quick-win composite).

A per-stock, interpretable read on *how well a company is run* — composed from
factors we already compute + validate, organised into three pillars:

  A · Capital allocation  (lead, 0.45) — roic, roiic, fcf_margin
        "Do they compound capital?"  The strongest quant proxy for competence.
  B · Alignment           (0.30)       — promoter_trend, pledge_quality, promoter_signal
        "Skin in the game?"  Promoter accumulation + low pledging + insider confidence.
  C · Credibility         (0.25)       — f_score, accruals_quality, forensic_penalty(-)
        "Are the earnings real?"  Piotroski quality + cash-backed accruals + clean forensics.

Each component is z-scored within cap_tier (sign-adjusted so higher = better),
averaged into its pillar, then the pillars are weight-combined (renormalised over
those present) into `mgmt_quality_z` and a 0-100 within-tier percentile + letter grade.

This RE-AGGREGATES already-weighted model factors, so it is a DISPLAY/diagnostic
lens (the Management tab on /explorer), NOT a new SIGNAL_WEIGHTS factor — wiring it
would double-count the quality signals already in the model (orthogonality, ADR 0028).

Sources (current per-stock):
  Pillar A — latest populated monthly daily_snapshots_pit anchor (roic/roiic/fcf are
             slow-moving annual fundamentals; the last monthly anchor is fresh enough).
  Pillar B — promoter_signals (latest).
  Pillar C — piotroski_scores + forensic_scores (latest).

Writes: management_scores  (INSERT OR REPLACE; PK sid+snapshot_date)

Usage:
    python -m signals.management_quality              # compute + save
    python -m signals.management_quality --dry-run    # compute + print top/bottom 15
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, upsert_df

Z_CLIP = 3.0
PILLAR_WEIGHTS = {"capital_allocation": 0.45, "alignment": 0.30, "credibility": 0.25}

# (raw_column, sign):  sign=+1 higher is better, -1 lower is better
PILLARS = {
    "capital_allocation": [("roic", 1), ("roiic", 1), ("fcf_margin", 1)],
    "alignment":          [("promoter_trend", 1), ("pledge_quality", 1), ("promoter_signal", 1)],
    "credibility":        [("f_score", 1), ("accruals_quality", 1), ("forensic_penalty", -1)],
}
GRADE_BANDS = [(90, "A+"), (75, "A"), (50, "B"), (25, "C"), (0, "D")]


def _z_within_tier(values: pd.Series, tiers: pd.Series) -> pd.Series:
    """Z-score within cap_tier, clipped to ±Z_CLIP. NaN where the segment is degenerate."""
    out = pd.Series(np.nan, index=values.index)
    for t in tiers.dropna().unique():
        mask = tiers == t
        v = values[mask]
        mu, sd = v.mean(), v.std(ddof=0)
        if sd and sd > 0:
            out[mask] = ((v - mu) / sd).clip(-Z_CLIP, Z_CLIP)
    return out


def _grade(score):
    if pd.isna(score):
        return None
    for thr, g in GRADE_BANDS:
        if score >= thr:
            return g
    return "D"


def _load():
    # Financials (Banks/NBFCs) are excluded: roic/fcf are meaningless for them and
    # they're covered by the dedicated financial sub-model. Scoring a bank on alignment
    # alone distorts the ranking — see signals/financial_signal.py.
    stocks = read_sql(
        "SELECT sid, cap_tier, name, sector FROM stocks "
        "WHERE cap_tier IS NOT NULL AND ticker IS NOT NULL "
        "AND COALESCE(sector,'') NOT IN ('Financials','Financial Services')"
    )
    # Pillar A — latest monthly PIT anchor that actually carries roic.
    a_date = read_sql(
        "SELECT snapshot_date FROM daily_snapshots_pit WHERE roic IS NOT NULL "
        "GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 1"
    ).iloc[0]["snapshot_date"]
    A = read_sql(
        "SELECT sid, roic, roiic, fcf_margin FROM daily_snapshots_pit WHERE snapshot_date = ?",
        params=[a_date],
    )
    # Pillar B — latest promoter signals.
    b_date = read_sql("SELECT MAX(snapshot_date) d FROM promoter_signals").iloc[0]["d"]
    B = read_sql(
        "SELECT sid, promoter_trend, pledge_quality, promoter_signal "
        "FROM promoter_signals WHERE snapshot_date = ?", params=[b_date],
    )
    # Pillar C — latest Piotroski + forensic.
    p_date = read_sql("SELECT MAX(snapshot_date) d FROM piotroski_scores").iloc[0]["d"]
    P = read_sql(
        "SELECT sid, f_score, accruals_quality FROM piotroski_scores WHERE snapshot_date = ?",
        params=[p_date],
    )
    f_date = read_sql("SELECT MAX(snapshot_date) d FROM forensic_scores").iloc[0]["d"]
    F = read_sql(
        "SELECT sid, penalty AS forensic_penalty FROM forensic_scores WHERE snapshot_date = ?",
        params=[f_date],
    )
    df = (stocks.merge(A, on="sid", how="left")
                .merge(B, on="sid", how="left")
                .merge(P, on="sid", how="left")
                .merge(F, on="sid", how="left"))
    # promoter_trend is categorical → ordinal (accumulation good, reduction bad).
    df["promoter_trend"] = df["promoter_trend"].map(
        {"ACCUMULATING": 1.0, "STABLE": 0.0, "MIXED": 0.0, "REDUCING": -1.0})
    return df, str(max(b_date, p_date, f_date))


def compute(write: bool = True) -> pd.DataFrame:
    df, snapshot_date = _load()
    tiers = df["cap_tier"]

    # 1) pillar z-scores: each component z'd within tier (sign-adjusted), then averaged.
    for pillar, comps in PILLARS.items():
        zs = []
        for col, sign in comps:
            if col in df.columns and df[col].notna().any():
                vals = pd.to_numeric(df[col], errors="coerce")
                zs.append(_z_within_tier(sign * vals, tiers))
        df[f"{pillar}_z"] = pd.concat(zs, axis=1).mean(axis=1) if zs else np.nan

    # 2) weighted composite, renormalised over the pillars present per stock.
    num = pd.Series(0.0, index=df.index)
    wsum = pd.Series(0.0, index=df.index)
    npil = pd.Series(0, index=df.index)
    for pillar, w in PILLAR_WEIGHTS.items():
        z = df[f"{pillar}_z"]
        present = z.notna()
        num[present] += w * z[present]
        wsum[present] += w
        npil[present] += 1
    df["mgmt_quality_z"] = np.where(wsum > 0, num / wsum, np.nan)
    df["n_pillars"] = npil

    # 3) 0-100 percentile within cap_tier + letter grade.
    # Score only stocks with the capital-allocation anchor present (pillar A is the
    # lead; without it "management quality" is too thin to rank).
    df["mgmt_quality_score"] = np.nan
    scorable = df["mgmt_quality_z"].notna() & df["capital_allocation_z"].notna()
    for t in tiers.dropna().unique():
        mask = scorable & (tiers == t)
        if mask.sum() >= 5:
            df.loc[mask, "mgmt_quality_score"] = (df.loc[mask, "mgmt_quality_z"].rank(pct=True) * 100).round(1)
    df["grade"] = df["mgmt_quality_score"].apply(_grade)
    df["snapshot_date"] = snapshot_date

    out_cols = ["sid", "snapshot_date", "cap_tier",
                "capital_allocation_z", "alignment_z", "credibility_z",
                "mgmt_quality_z", "mgmt_quality_score", "grade",
                "roic", "roiic", "fcf_margin",
                "promoter_trend", "pledge_quality", "promoter_signal",
                "f_score", "accruals_quality", "forensic_penalty", "n_pillars"]
    out = df[df["mgmt_quality_score"].notna()][out_cols].copy()
    out = out.astype(object).where(pd.notna(out), None)

    if write and not out.empty:
        n = upsert_df(out, "management_scores")
        print(f"management_quality: wrote {n} rows @ {snapshot_date} "
              f"(pillars A/B/C present: {int(df['capital_allocation_z'].notna().sum())}/"
              f"{int(df['alignment_z'].notna().sum())}/{int(df['credibility_z'].notna().sum())})")
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="compute + print top/bottom, no write")
    args = ap.parse_args()
    df = compute(write=not args.dry_run)
    scored = df[df["mgmt_quality_score"].notna()].copy()
    show = ["name", "cap_tier", "mgmt_quality_score", "grade",
            "capital_allocation_z", "alignment_z", "credibility_z"]
    for tier in ["LARGE", "MID", "SMALL"]:
        t = scored[scored["cap_tier"] == tier].sort_values("mgmt_quality_score", ascending=False)
        if t.empty:
            continue
        pd.set_option("display.width", 200)
        print(f"\n===== {tier}: TOP 8 best-run =====")
        print(t.head(8)[show].to_string(index=False))
        print(f"----- {tier}: BOTTOM 5 -----")
        print(t.tail(5)[show].to_string(index=False))


if __name__ == "__main__":
    main()
