"""
Missed winners, 2019-12 → 2025-10: every stock that at least doubled in the 12 months after a monthly
anchor, and how our model saw it at the start.  (READ-ONLY on the DB; writes
docs/studies/missed-winners-2019-2025.csv)

Definition (fixed before looking at the list, 2026-10-13):
  run       a (stock, anchor) with fwd_252 >= +100 % (data/lh/labels.parquet, adjusted, next-session entry).
            One row per stock: its FIRST qualifying anchor (the start of its first doubling run),
            plus how many anchors qualified and the best 12-month return seen.
  tiers     LARGE / MID / SMALL at that anchor (MICRO excluded, never pickable).
  model     the live model as configured until 2026-10-13: today's weights on the PIT panel with the
            forensic penalty (data/lh/v2/scores_all.parquet `fast_v1`), percentile within tier
            (1.0 = top). In-sample by construction (the weights were set on this history), so if
            anything it flatters the model.
  flags     penalty   forensic_penalty < 0 at the anchor
            new       listed < 12 months before the anchor (first price in stock_prices; 2010+ history)
            no_mom    residual_momentum_12_1 missing at the anchor (too little history)
  research  slow_v2 percentile, 6-month momentum percentile (does momentum see it?).
  verdict   CAUGHT = live percentile >= 0.90 (top tenth) · MIDDLE = 0.50–0.90 · MISSED = < 0.50.

Usage: python -m tools.missed_winners
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
OUT = PROJECT_ROOT / "docs" / "studies" / "missed-winners-2019-2025.csv"


def main():
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_252"])
    lab = lab[lab["cap_tier"].isin(["LARGE", "MID", "SMALL"]) & lab["fwd_252"].notna()]
    sc = pd.read_parquet(LH / "v2" / "scores_all.parquet")
    sc = sc[sc["method"].isin(["fast_v1", "slow_v2"])]
    sc["pct"] = sc.groupby(["method", "snapshot_date", "cap_tier"])["score"].rank(pct=True)
    piv = sc.pivot_table(index=["sid", "snapshot_date"], columns="method", values="pct").reset_index()
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    anchors = sorted(lab["snapshot_date"].unique())
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, cap_tier, forensic_penalty, residual_momentum_12_1, mom_6m "
                      f"FROM daily_snapshots_pit WHERE snapshot_date IN ({ph})", con, params=anchors)
    first = pd.read_sql("SELECT sid, MIN(date) AS first_price FROM stock_prices GROUP BY sid", con)
    names = pd.read_sql("SELECT sid, ticker, name, sector FROM stocks", con)
    con.close()
    pan["mom6_pct"] = pan.groupby(["snapshot_date", "cap_tier"])["mom_6m"].rank(pct=True)
    d = lab.merge(piv, on=["sid", "snapshot_date"], how="left").merge(
        pan.drop(columns=["cap_tier", "mom_6m"]), on=["sid", "snapshot_date"], how="left").merge(first, on="sid", how="left")
    runs = d[d["fwd_252"] >= 1.0].sort_values(["sid", "snapshot_date"])
    best = runs.groupby("sid")["fwd_252"].max().rename("best_12m")
    n = runs.groupby("sid").size().rename("anchors_doubling")
    first_run = runs.groupby("sid").head(1).set_index("sid").join(best).join(n).reset_index()
    first_run["new_listing"] = (pd.to_datetime(first_run["snapshot_date"]) - pd.to_datetime(first_run["first_price"])).dt.days < 365
    first_run.loc[first_run["first_price"] <= "2010-01-05", "new_listing"] = False
    first_run["penalty"] = first_run["forensic_penalty"].fillna(0) < 0
    first_run["no_momentum_data"] = first_run["residual_momentum_12_1"].isna()
    first_run["verdict"] = np.select([first_run["fast_v1"] >= 0.9, first_run["fast_v1"] >= 0.5], ["CAUGHT", "MIDDLE"], "MISSED")
    out = first_run.merge(names, on="sid", how="left")[[
        "ticker", "name", "sector", "cap_tier", "snapshot_date", "fwd_252", "best_12m", "anchors_doubling", "fast_v1",
        "verdict", "penalty", "forensic_penalty", "new_listing", "no_momentum_data", "slow_v2", "mom6_pct"]]
    out = out.rename(columns={"snapshot_date": "run_start", "fwd_252": "first_12m", "fast_v1": "live_pct",
                              "slow_v2": "slow_v2_pct"}).sort_values("best_12m", ascending=False)
    for c in ("first_12m", "best_12m", "live_pct", "slow_v2_pct", "mom6_pct", "forensic_penalty"):
        out[c] = out[c].round(2)
    out.to_csv(OUT, index=False)
    print(f"{len(out)} stocks doubled within 12 months at least once (anchors 2019-12 → 2025-10)")
    print(out["verdict"].value_counts().to_string())
    m = out[out["verdict"] == "MISSED"]
    print(f"\nMISSED {len(m)}: penalty {m['penalty'].mean():.0%} · new listing {m['new_listing'].mean():.0%} · "
          f"no momentum data {m['no_momentum_data'].mean():.0%} · momentum top-30 % at the start {(m['mom6_pct'] >= 0.7).mean():.0%}")
    print("by tier:\n", pd.crosstab(out["cap_tier"], out["verdict"]).to_string())
    print("by year of run start:\n", pd.crosstab(out["run_start"].str[:4], out["verdict"]).to_string())
    pd.set_option("display.width", 220)
    print(out.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
