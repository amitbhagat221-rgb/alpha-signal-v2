"""
Feature engineering — can a fast factor be turned into a slow one?  (READ-ONLY on the DB;
writes data/lh/v2/fast2slow.csv)

PRE-REGISTRATION (2026-10-13, before any result):
Fast factors (PIT panel, monthly anchors): delivery_anomaly_z, avg_delivery_pct_30d,
announcement_car, st_reversal_21d, max_lottery_21d, smart_money_score, closing_strength_1m,
short_selling_signal, bulk_deal_signal, sentiment_7d, relative_turnover,
intraday_range_compression, iv_skew_25d, vwap_deviation_5d.
Transforms, per stock over its own monthly series (current and past anchors only):
  raw       the anchor value (baseline)
  avg6      mean of the last 6 anchors (>= 4 present)
  avg12     mean of the last 12 anchors (>= 8 present)
  persist6  share of the last 6 anchors in the top tercile of its tier (>= 4 present)
  trend6    current value minus the mean of the previous 6 anchors (>= 4 present)
Test per tier (MID, SMALL): within-tier rank IC at 21 / 126 / 252 sessions (data/lh/labels.parquet),
Newey-West and non-overlap t at 126, IC by period 2020-22 / 2023-24 / 2025-26.
"Converted to slow" (pre-registered): non-overlap t at 126 with |t| >= 2.0, |IC126| >= |IC21| for
that transform, the sign held in every period with data, and |IC126| above the raw factor's |IC126|.
Family = 14 factors × 4 transforms × 2 tiers = 112 tests; Bonferroni |t| ≈ 3.5 reported alongside.

Usage: python -m tools.lh_fast2slow
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.backtest_pit import _aggregate, _compute_ic  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
FAST = ["delivery_anomaly_z", "avg_delivery_pct_30d", "announcement_car", "st_reversal_21d", "max_lottery_21d",
        "smart_money_score", "closing_strength_1m", "short_selling_signal", "bulk_deal_signal", "sentiment_7d",
        "relative_turnover", "intraday_range_compression", "iv_skew_25d", "vwap_deviation_5d"]
TRANSFORMS = ("raw", "avg6", "avg12", "persist6", "trend6")
HORIZONS = (21, 126, 252)
NW_LAG = {21: 1, 126: 6, 252: 12}
PERIODS = {"2020-22": ("0000", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "9999")}


def nonoverlap_t(rows, h):
    step = max(h // 21, 1)
    s = pd.Series([r[1] for r in rows], index=[r[0] for r in rows]).sort_index()
    ts = [x.mean() / (x.std() / np.sqrt(len(x))) for x in (s.iloc[o::step] for o in range(step))
          if len(x) >= 3 and x.std() > 0]
    return float(np.mean(ts)) if ts else np.nan


def main():
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"]
                          + [f"fwd_{h}" for h in HORIZONS])
    lab = lab[lab["cap_tier"].isin(["MID", "SMALL"])]
    anchors = sorted(lab["snapshot_date"].unique())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, {', '.join(FAST)} FROM daily_snapshots_pit "
                      f"WHERE snapshot_date IN ({ph})", con, params=anchors)
    con.close()
    df = lab.merge(pan, on=["sid", "snapshot_date"], how="left").sort_values(["sid", "snapshot_date"])
    g = df.groupby("sid")
    tier_g = df.groupby(["snapshot_date", "cap_tier"])
    for c in FAST:
        df[f"{c}__raw"] = df[c]
        df[f"{c}__avg6"] = g[c].transform(lambda s: s.rolling(6, min_periods=4).mean())
        df[f"{c}__avg12"] = g[c].transform(lambda s: s.rolling(12, min_periods=8).mean())
        top = (tier_g[c].rank(pct=True) >= 2 / 3).astype(float).where(df[c].notna())
        df[f"{c}__persist6"] = top.groupby(df["sid"]).transform(lambda s: s.rolling(6, min_periods=4).mean())
        prev = g[c].transform(lambda s: s.shift(1).rolling(6, min_periods=4).mean())
        df[f"{c}__trend6"] = df[c] - prev

    recs = []
    for c in FAST:
        for tr in TRANSFORMS:
            col = f"{c}__{tr}"
            for tier in ("MID", "SMALL"):
                tdf = df[df["cap_tier"] == tier]
                rec = dict(factor=c, transform=tr, tier=tier)
                for h in HORIZONS:
                    rows = _compute_ic(tdf, col, f"fwd_{h}")
                    r = _aggregate(rows, col, tier, "lh", cadence="monthly", nw_lag=NW_LAG[h]) if rows else None
                    rec[f"ic{h}"] = round(r["mean_ic"], 4) if r else np.nan
                    rec[f"n{h}"] = r["n_periods"] if r else 0
                    if h == 126 and r and r["t_stat"] is not None:
                        rec["t_nw126"] = round(r["t_stat"], 2)
                        rec["t_no126"] = round(nonoverlap_t(rows, 126), 2)
                        for p, (lo, hi) in PERIODS.items():
                            sub = [x[1] for x in rows if lo <= x[0] <= hi]
                            rec[f"ic126_{p}"] = round(float(np.mean(sub)), 4) if len(sub) >= 3 else np.nan
                recs.append(rec)
    t = pd.DataFrame(recs)
    raw126 = t[t["transform"] == "raw"].set_index(["factor", "tier"])["ic126"].abs()
    sign = np.sign(t["ic126"])
    held = pd.concat([np.sign(t[f"ic126_{p}"]).eq(sign) | t[f"ic126_{p}"].isna() for p in PERIODS], axis=1).all(axis=1)
    t["converted"] = ((t["transform"] != "raw") & (t["t_no126"].abs() >= 2.0) & (t["ic126"].abs() >= t["ic21"].abs())
                      & held & (t["ic126"].abs() > t.apply(lambda r: raw126.get((r["factor"], r["tier"]), 0), axis=1)))
    t["bonferroni"] = (t["transform"] != "raw") & (t["t_nw126"].abs() >= stats.t.isf(0.025 / 112, 60))
    t["slowness"] = (t["ic126"] / t["ic21"]).round(2)
    t.to_csv(LH / "v2" / "fast2slow.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["factor", "transform", "tier", "ic21", "ic126", "ic252", "slowness", "t_nw126", "t_no126",
            "ic126_2020-22", "ic126_2023-24", "ic126_2025-26", "converted", "bonferroni"]
    print(t[cols].sort_values(["tier", "factor", "transform"]).to_string(index=False))
    print("\nCONVERTED:")
    print(t[t["converted"]][cols].to_string(index=False))


if __name__ == "__main__":
    main()
