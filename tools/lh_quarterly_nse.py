"""
Plan 0025 task 5.1 (last step) — re-test the quarterly growth features on NSE filings back to 2017
(READ-ONLY on the DB).  Writes data/lh/v2/qnse_features.parquet and data/lh/v2/qnse_tests.csv.

Why: tools/lh_growth.py found quarterly margin expansion the one fundamental lead (q_margin_chg MID
126: non-overlap t 2.71, top decile +12.9 %), but its quarters come from Tickertape `quarterly_income`,
which starts 2023, so the features only exist from 2024-ish anchors (~3 independent 6-month windows,
one regime). quarterly_results_nse (NSE XBRL, 2017-06 → 2024-12, task 5.1) now passes the data gate.

PRE-REGISTRATION (written 2026-10-14 before any result; nothing below changes after the first run):
Features: exactly lh_growth's six quarterly features, same formulas —
  q_rev_yoy, q_rev_accel, q_ebitda_chg, q_profit_accel, q_margin_chg, q_margin_streak
  (YoY needs the quarter 350–380 days earlier; accel = change vs the previous quarter's YoY).
Sources, point in time:
  NSE  quarterly_results_nse. Each (sid, period_end, basis) uses its FIRST filing, knowable at
       that filing's `filed_at` (later restatements are ignored: no look-ahead).
       "EBITDA" = pbt_pre_exceptional + finance_costs + depreciation − other_income
       (operating profit before one-offs, as tools/winner_hunter.py).
  TT   quarterly_income (Tickertape), knowable at end_date + 60 days, `ebitda` as reported.
  Every YoY / acceleration is computed inside ONE source and ONE basis (never NSE vs TT). Per sid
  and quarter: NSE before TT, consolidated before standalone. At each anchor the latest knowable
  quarter's features are used.
Universe / labels: data/lh/labels.parquet (LARGE / MID / SMALL; fwd_63 / 126 / 252); Financials
  excluded; winsorised 1/99 per anchor — all as lh_growth.
Test (lh_growth's machinery): within-tier monthly Spearman IC, Newey-West t (lag = h/21), the
  non-overlap t (headline, plan 0025 ground rule 3), top-decile excess vs the tier median, sign by
  period 2020-22 / 2023-24 / 2025-26.
Bar per feature × tier × horizon: n >= 24 anchors, non-overlap |t| >= 2.0, NW |t| >= 2.5, and the
  sign held in every period. Bonferroni over the family reported alongside.
Decision: a feature that passes in a tier → FACTOR_LIBRARY candidate + promotion review (ADR 0043
  haircut, signal-weights.md). No weights from this tool. The question it settles: does
  q_margin_chg MID (the forward-test lead) hold on 2020-26 anchors?
Source check (reported, not deciding): for quarters both sources hold (2023-24), the Spearman
  correlation of NSE vs TT q_rev_yoy and q_margin_chg (CLAUDE.md: a column's meaning is checked
  against a second source).

Usage:  python -m tools.lh_quarterly_nse [--reuse]
"""

import argparse
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import SCREEN  # noqa: E402
from tools.backtest_pit import _aggregate, _compute_ic  # noqa: E402
from signals._quarterly import QUARTER_F, asof, history  # noqa: E402  (plan 0026: one definition, shared with the live desk)
from tools.lh_growth import HORIZONS, NW_LAG, PERIODS, TIERS, nonoverlap_t, top_decile_excess  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
MIN_N, BAR_NONOVERLAP, BAR_NW = 24, 2.0, 2.5


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def source_check(h):
    both = h[h["period_end"].between("2023-01-01", "2024-12-31")]
    out = {}
    for c in ("q_rev_yoy", "q_margin_chg"):
        p = both.pivot_table(index=["sid", "period_end", "basis"], columns="src", values=c, aggfunc="first").dropna()
        if len(p) >= 30 and {"nse", "tt"} <= set(p.columns):
            out[c] = dict(n=len(p), spearman=round(float(stats.spearmanr(p["nse"], p["tt"])[0]), 3))
    return out


def build():
    conn = ro()
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"]
                          + [f"fwd_{h}" for h in HORIZONS])
    lab = lab[lab["cap_tier"].isin(TIERS)]
    anchors = sorted(lab["snapshot_date"].unique())
    h = history(conn)
    sector = pd.read_sql("SELECT sid, sector FROM stocks", conn)
    conn.close()
    print("source check (2023-24 quarters held by both):", source_check(h))
    df = lab.merge(asof(h, anchors), on=["sid", "snapshot_date"], how="left").merge(sector, on="sid", how="left")
    df.loc[df["sector"].isin(SCREEN["financial_sectors"]), QUARTER_F] = np.nan
    for c in QUARTER_F:
        q = df.groupby("snapshot_date")[c].transform
        df[c] = df[c].clip(q(lambda s: s.quantile(.01)), q(lambda s: s.quantile(.99)))
    V2.mkdir(parents=True, exist_ok=True)
    df.to_parquet(V2 / "qnse_features.parquet", index=False)
    return df


def test(df):
    recs = []
    for col in QUARTER_F:
        for tier in TIERS:
            tdf = df[df["cap_tier"] == tier]
            for hz in HORIZONS:
                rows = _compute_ic(tdf, col, f"fwd_{hz}")
                r = _aggregate(rows, col, tier, "lh", cadence="monthly", nw_lag=NW_LAG[hz]) if rows else None
                if not r:
                    continue
                rec = {"factor": col, "tier": tier, "h": hz, "n": r["n_periods"], "ic": r["mean_ic"],
                       "t_nw": r["t_stat"], "t_nonoverlap": nonoverlap_t(rows, hz),
                       "first": min(x[0] for x in rows)[:7], "stocks": r["n_stocks_avg"],
                       "top10_excess": top_decile_excess(tdf, col, f"fwd_{hz}")}
                for p, (lo, hi) in PERIODS.items():
                    sub = [x[1] for x in rows if lo <= x[0] <= hi]
                    rec[f"ic_{p}"] = float(np.mean(sub)) if len(sub) >= 3 else None
                recs.append(rec)
    t = pd.DataFrame(recs)
    fam = t["n"] >= MIN_N
    m = int(fam.sum())
    t["p"] = 2 * stats.t.sf(t["t_nw"].abs(), (t["n"] - 1).clip(lower=1))
    t["bonferroni_pass"] = fam & (t["p"] * m < 0.05)
    sign = np.sign(t["ic"])
    held = pd.concat([np.sign(t[f"ic_{p}"]).eq(sign) | t[f"ic_{p}"].isna() for p in PERIODS], axis=1).all(axis=1)
    t["passes_bar"] = (fam & (t["t_nonoverlap"].abs() >= BAR_NONOVERLAP) & (t["t_nw"].abs() >= BAR_NW) & held)
    t.to_csv(V2 / "qnse_tests.csv", index=False)
    print(f"family: {m} tests (n >= {MIN_N} anchors); Bonferroni |t| bar ~ {stats.t.isf(0.025 / m, 60):.2f}")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    df = pd.read_parquet(V2 / "qnse_features.parquet") if a.reuse else build()
    cov = df.groupby("cap_tier")[QUARTER_F].apply(lambda x: x.notna().mean()).T.round(2)
    first = {c: df.loc[df[c].notna(), "snapshot_date"].min() for c in QUARTER_F}
    print("coverage (share of tier rows) and first anchor:")
    print(cov.assign(first=pd.Series(first)).to_string())
    print("source of the feature row, share by period:")
    print(df.dropna(subset=["src"]).assign(y=df["snapshot_date"].str[:4]).groupby("y")["src"]
          .value_counts(normalize=True).unstack().round(2).to_string())
    t = test(df)
    pd.set_option("display.width", 220)
    show = ["factor", "tier", "h", "n", "first", "ic", "t_nw", "t_nonoverlap", "top10_excess",
            "ic_2020-22", "ic_2023-24", "ic_2025-26", "passes_bar", "bonferroni_pass"]
    for hz in HORIZONS:
        print(f"\n=== horizon {hz} sessions ===")
        print(t[t["h"] == hz].sort_values(["tier", "t_nw"], ascending=[True, False])[show]
              .round(3).to_string(index=False))


if __name__ == "__main__":
    main()
