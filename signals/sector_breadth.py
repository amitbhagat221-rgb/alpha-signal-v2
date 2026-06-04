"""
Alpha Signal v2 — Sector Breadth (analyst-revision + news-sentiment)

Two monthly PIT producers that accumulate sector-level at-entry signals so they
become backtestable in ~12 months (sector-signal lab follow-up, 2026-06):

  compute_analyst()   — net analyst-revision breadth per sector, from the MoM
                        change in analyst_consensus_snapshots.target_mean.
                        Needs ≥2 monthly snapshots; writes one row-set per month
                        thereafter. → sector_analyst_breadth_pit
  compute_sentiment() — sector aggregate of stock-level 30d news sentiment,
                        snapshotting the last sentiment_scores row each month.
                        Backfills every month already present. → sector_sentiment_breadth_pit

Both INSERT-OR-REPLACE (upsert) so re-runs are idempotent and a monthly pipeline
run simply appends the new month. GICS sector from stocks.sector.

Usage:
    python -m signals.sector_breadth --analyst
    python -m signals.sector_breadth --sentiment
    python -m signals.sector_breadth --all --dry-run
"""

import argparse

import numpy as np
import pandas as pd

from db import read_sql, upsert_df


def _sectors():
    return read_sql("SELECT sid, sector FROM stocks WHERE sector IS NOT NULL")


# ───────── analyst-revision breadth ─────────

def compute_analyst(dry_run=False):
    """Net analyst price-target revision breadth per sector, month over month."""
    acs = read_sql(
        "SELECT sid, snapshot_date, source, target_mean, recommendation_mean "
        "FROM analyst_consensus_snapshots WHERE target_mean IS NOT NULL")
    if acs.empty:
        raise RuntimeError("analyst_consensus_snapshots empty — nothing to compute")

    # one source only (yfinance today); if multiple, prefer the most-covered one
    src = acs["source"].value_counts().idxmax()
    acs = acs[acs["source"] == src]
    sec = _sectors().set_index("sid")["sector"]
    dates = sorted(acs["snapshot_date"].unique())
    if len(dates) < 2:
        print(f"Only {len(dates)} monthly snapshot(s) in analyst_consensus_snapshots "
              f"({src}) — need ≥2 for a MoM breadth row. Skipping (clock starts next month).")
        return 0

    rows = []
    for prev_d, cur_d in zip(dates[:-1], dates[1:]):
        prev = acs[acs["snapshot_date"] == prev_d].set_index("sid")
        cur = acs[acs["snapshot_date"] == cur_d].set_index("sid")
        common = prev.index.intersection(cur.index)
        if len(common) < 20:
            continue
        d = pd.DataFrame({
            "sector": [sec.get(s) for s in common],
            "pt_prev": prev.loc[common, "target_mean"].values,
            "pt_cur": cur.loc[common, "target_mean"].values,
            "reco": cur.loc[common, "recommendation_mean"].values,
        }).dropna(subset=["sector"])
        d = d[d["pt_prev"] > 0]
        d["chg"] = d["pt_cur"] / d["pt_prev"] - 1.0
        for sector, g in d.groupby("sector"):
            if len(g) < 3:
                continue
            up, down = (g["chg"] > 0.001).mean(), (g["chg"] < -0.001).mean()
            rows.append({
                "sector": sector, "snapshot_date": cur_d, "n_covered": int(len(g)),
                "pct_pt_up": round(float(up), 4), "pct_pt_down": round(float(down), 4),
                "mean_pt_chg_pct": round(float(g["chg"].mean() * 100), 3),
                "mean_reco": round(float(g["reco"].mean()), 3) if g["reco"].notna().any() else None,
                "breadth": round(float(up - down), 4),
            })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No sector breadth rows (insufficient overlap).")
        return 0
    print(f"Analyst breadth: {len(df)} rows across {df['snapshot_date'].nunique()} month(s)")
    last = df[df["snapshot_date"] == df["snapshot_date"].max()].sort_values("breadth", ascending=False)
    for _, r in last.iterrows():
        print(f"  {r['sector']:24s} breadth {r['breadth']:+.2f}  "
              f"(up {r['pct_pt_up']:.0%} / dn {r['pct_pt_down']:.0%}, n={r['n_covered']})")
    if dry_run:
        print("Dry run — not saving.")
        return len(df)
    n = upsert_df(df, "sector_analyst_breadth_pit")
    print(f"Saved {n} rows to sector_analyst_breadth_pit")
    return n


# ───────── news-sentiment breadth ─────────

def compute_sentiment(dry_run=False):
    """Sector aggregate of 30d news sentiment, one snapshot per available month."""
    s = read_sql(
        "SELECT sid, snapshot_date, sentiment_30d, articles_30d "
        "FROM sentiment_scores WHERE sentiment_30d IS NOT NULL")
    if s.empty:
        raise RuntimeError("sentiment_scores empty — nothing to compute")

    s["ym"] = pd.to_datetime(s["snapshot_date"]).dt.to_period("M")
    # last snapshot date in each month = the month's representative cross-section
    last_in_month = s.groupby("ym")["snapshot_date"].transform("max")
    s = s[s["snapshot_date"] == last_in_month]
    sec = _sectors().set_index("sid")["sector"]
    s["sector"] = s["sid"].map(sec)
    s = s.dropna(subset=["sector"])

    rows = []
    for (snap, sector), g in s.groupby(["snapshot_date", "sector"]):
        sv = g["sentiment_30d"].astype(float)
        if len(sv) < 3:
            continue
        pos, neg = (sv > 0).mean(), (sv < 0).mean()
        rows.append({
            "sector": sector, "snapshot_date": snap, "n_stocks": int(len(g)),
            "mean_sent_30d": round(float(sv.mean()), 4),
            "pct_positive": round(float(pos), 4),
            "article_vol": int(g["articles_30d"].fillna(0).sum()),
            "sent_breadth": round(float(pos - neg), 4),
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No sentiment breadth rows.")
        return 0
    print(f"Sentiment breadth: {len(df)} rows across {df['snapshot_date'].nunique()} month(s)")
    last = df[df["snapshot_date"] == df["snapshot_date"].max()].sort_values("sent_breadth", ascending=False)
    for _, r in last.iterrows():
        print(f"  {r['sector']:24s} breadth {r['sent_breadth']:+.2f}  "
              f"(mean {r['mean_sent_30d']:+.2f}, n={r['n_stocks']}, {r['article_vol']} arts)")
    if dry_run:
        print("Dry run — not saving.")
        return len(df)
    n = upsert_df(df, "sector_sentiment_breadth_pit")
    print(f"Saved {n} rows to sector_sentiment_breadth_pit")
    return n


def compute(dry_run=False):
    """Run both (pipeline convenience)."""
    return (compute_analyst(dry_run=dry_run) or 0) + (compute_sentiment(dry_run=dry_run) or 0)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--analyst", action="store_true")
    p.add_argument("--sentiment", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.analyst:
        compute_analyst(dry_run=args.dry_run)
    elif args.sentiment:
        compute_sentiment(dry_run=args.dry_run)
    else:
        compute(dry_run=args.dry_run)
