"""
Winners post-mortem step 1 — growth, acceleration and long-history quality as slow signals
(READ-ONLY on the DB).  docs/studies/winners-postmortem-2026-10.md

Why: NETWEB / SSWL / TIMETECHNO ran on growth that was speeding up; the model has no growth
input with history (the PIT growth columns start 2025-09). This builds the features straight
from the statements for every monthly anchor of data/lh/labels.parquet and tests them.

PIT rule (deliberately not pit._arrived: the vendor history was bulk-fetched 2026-05..10, so
_arrived would hide it): a statement is knowable when period_end + lag <= anchor.
  annual   fundamentals_screener (period_type annual)   lag 150 days (pit.VENDOR_ANNUAL_LAG)
  quarterly quarterly_income, prefer_consolidated        lag 60 days  (pit.QUARTERLY_LAG)
Known trap: vendor history can carry later restatements (merger, Ind-AS) — a look-ahead we
cannot see; flag, do not fix.  Universe: today's listed names (survivorship, as plan 0024).
Financials (config SCREEN financial_sectors) excluded from every EBIT / ROCE feature.

Pre-registered features (fixed before any result):
 Annual (core EBIT = PBT - Other Income + Interest, which drops one-offs Screener books in
 Other Income; margin = core EBIT / Sales):
  a_sales_g1          Sales_t / Sales_t-1 - 1
  a_sales_accel       a_sales_g1(t) - a_sales_g1(t-1)
  a_ebit_chg          (EBIT_t - EBIT_t-1) / Sales_t-1
  a_margin_chg        margin_t - margin_t-1
  a_sales_cagr3       (Sales_t / Sales_t-3)^(1/3) - 1
  a_growth_consist    years of positive sales growth among the last 5
  a_roce              EBIT_t / mean(capital_t, capital_t-1), capital = equity + reserves + borrowings
  a_roce_min5         minimum ROCE over the last 5 years (needs 4)
  a_roe               Net profit_t / mean(equity_t, equity_t-1)
  a_piotroski_lite    8 Piotroski tests (no current-ratio test): NI>0, CFO>0, dROA>0, CFO>NI,
                      d(Borrowings/Total)<0, shares not up, d(margin)>0, d(Sales/Total)>0
 Quarterly (latest knowable quarter q; YoY needs q-4):
  q_rev_yoy           rev_q / rev_q-4 - 1
  q_rev_accel         q_rev_yoy(q) - q_rev_yoy(q-1)
  q_ebitda_chg        (EBITDA_q - EBITDA_q-4) / rev_q-4
  q_profit_accel      q_ebitda_chg(q) - q_ebitda_chg(q-1)
  q_margin_chg        EBITDA margin_q - margin_q-4
  q_margin_streak     quarters among the last 4 with EBITDA margin up YoY
 Interactions (mean of within-tier percentiles; mom_6m / book_to_price from the PIT panel):
  x_growth_mom        a_sales_g1 & mom_6m
  x_accel_mom         a_sales_accel & mom_6m
  x_margin_mom        a_margin_chg & mom_6m
  x_quality_value     a_roce & book_to_price
  x_qaccel_mom        q_rev_accel & mom_6m

Test: within-tier monthly Spearman IC vs fwd_63 / fwd_126 / fwd_252 (tools.backtest_pit
helpers, Newey-West lag = horizon in months, as tools.lh_horizon), plus a non-overlap t
(mean of the h/21 every-k-th-anchor subsample t's) and the top-decile mean excess return vs
the tier median. Bar (as plan 0024 'slow'): n >= 12 anchors, |NW t| >= 2.5, sign held in
each period with data; Bonferroni over this family reported alongside.

Writes data/lh/growth_features.parquet and data/lh/growth_tests.csv.
Usage:  python -m tools.lh_growth [--reuse]
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
from signals._fundamentals import prefer_consolidated  # noqa: E402
from signals._quarterly import QUARTER_F, QUARTERLY_LAG, div as _div  # noqa: E402,F401
from tools.backtest_pit import _aggregate, _compute_ic  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
ANNUAL_LAG = 150
HORIZONS = (63, 126, 252)
NW_LAG = {63: 3, 126: 6, 252: 12}
TIERS = ("LARGE", "MID", "SMALL")
PERIODS = {"2020-22": ("0000", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "9999")}
ITEMS = {"Sales": "sales", "Profit before tax": "pbt", "Other Income": "oi", "Interest": "interest",
         "Net profit": "ni", "Equity Share Capital": "eq_cap", "Reserves": "reserves",
         "Borrowings": "borrow", "Total": "total", "Cash from Operating Activity": "cfo",
         "No. of Equity Shares": "shares"}
ANNUAL_F = ["a_sales_g1", "a_sales_accel", "a_ebit_chg", "a_margin_chg", "a_sales_cagr3",
            "a_growth_consist", "a_roce", "a_roce_min5", "a_roe", "a_piotroski_lite"]
INTER = {"x_growth_mom": ("a_sales_g1", "mom_6m"), "x_accel_mom": ("a_sales_accel", "mom_6m"),
         "x_margin_mom": ("a_margin_chg", "mom_6m"), "x_quality_value": ("a_roce", "book_to_price"),
         "x_qaccel_mom": ("q_rev_accel", "mom_6m")}
EBIT_F = {"a_ebit_chg", "a_margin_chg", "a_roce", "a_roce_min5", "a_piotroski_lite",
          "q_ebitda_chg", "q_profit_accel", "q_margin_chg", "q_margin_streak"}


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def annual_history(conn):
    """One row per (sid, period_end) with every derived annual quantity; features at t use
    rows t, t-1, … of the same sid, so each row's features need only knowable rows."""
    raw = pd.read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener "
                      "WHERE period_type='annual' AND line_item IN (%s)" % ",".join("?" * len(ITEMS)),
                      conn, params=list(ITEMS))
    w = raw.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="last")
    w = w.rename(columns=ITEMS).reset_index().sort_values(["sid", "period_end"])
    for c in ITEMS.values():
        if c not in w:
            w[c] = np.nan
    w["ebit"] = w["pbt"] - w["oi"].fillna(0) + w["interest"].fillna(0)
    w["margin"] = _div(w["ebit"], w["sales"])
    w["equity"] = w["eq_cap"].fillna(0) + w["reserves"]
    w["capital"] = w["equity"] + w["borrow"].fillna(0)
    g = w.groupby("sid")
    prev = lambda c, k=1: g[c].shift(k)  # noqa: E731
    # consecutive fiscal years only (330–400 days apart)
    gap = (pd.to_datetime(w["period_end"]) - pd.to_datetime(g["period_end"].shift(1))).dt.days
    w["consec"] = gap.between(330, 400)
    w["a_sales_g1"] = np.where(w["consec"], _div(w["sales"], prev("sales")) - 1, np.nan)
    w["a_sales_accel"] = w["a_sales_g1"] - g["a_sales_g1"].shift(1)
    w["a_ebit_chg"] = np.where(w["consec"], _div(w["ebit"] - prev("ebit"), prev("sales")), np.nan)
    w["a_margin_chg"] = np.where(w["consec"], w["margin"] - prev("margin"), np.nan)
    w["a_sales_cagr3"] = np.power(_div(w["sales"], prev("sales", 3)), 1 / 3) - 1
    pos = (w["a_sales_g1"] > 0).astype(float).where(w["a_sales_g1"].notna())
    w["a_growth_consist"] = pos.groupby(w["sid"]).transform(lambda s: s.rolling(5, min_periods=5).sum())
    w["a_roce"] = _div(w["ebit"], (w["capital"] + prev("capital")) / 2)
    w["a_roce_min5"] = w.groupby("sid")["a_roce"].transform(lambda s: s.rolling(5, min_periods=4).min())
    w["a_roe"] = _div(w["ni"], (w["equity"] + prev("equity")) / 2)
    roa = _div(w["ni"], w["total"])
    lev = _div(w["borrow"].fillna(0), w["total"])
    turn = _div(w["sales"], w["total"])
    tests = [w["ni"] > 0, w["cfo"] > 0, roa > pd.Series(roa).groupby(w["sid"]).shift(1),
             w["cfo"] > w["ni"], lev < pd.Series(lev).groupby(w["sid"]).shift(1),
             w["shares"] <= prev("shares"), w["margin"] > prev("margin"),
             turn > pd.Series(turn).groupby(w["sid"]).shift(1)]
    w["a_piotroski_lite"] = np.where(w["consec"] & w["ni"].notna() & w["cfo"].notna(),
                                     sum(np.asarray(t, dtype=float) for t in tests), np.nan)
    return w


def quarterly_history(conn):
    qi = pd.read_sql("SELECT sid, end_date, reporting, revenue, ebitda FROM quarterly_income "
                     "WHERE end_date IS NOT NULL", conn)
    qi = prefer_consolidated(qi).sort_values(["sid", "end_date"]).drop_duplicates(["sid", "end_date"], keep="last")
    g = qi.groupby("sid")
    ed = pd.to_datetime(qi["end_date"])
    lag4 = (ed - pd.to_datetime(g["end_date"].shift(4))).dt.days.between(350, 380)
    qi["margin"] = _div(qi["ebitda"], qi["revenue"])
    qi["q_rev_yoy"] = np.where(lag4, _div(qi["revenue"], g["revenue"].shift(4)) - 1, np.nan)
    qi["q_ebitda_chg"] = np.where(lag4, _div(qi["ebitda"] - g["ebitda"].shift(4), g["revenue"].shift(4)), np.nan)
    qi["q_margin_chg"] = np.where(lag4, qi["margin"] - g["margin"].shift(4), np.nan)
    g = qi.groupby("sid")
    qi["q_rev_accel"] = qi["q_rev_yoy"] - g["q_rev_yoy"].shift(1)
    qi["q_profit_accel"] = qi["q_ebitda_chg"] - g["q_ebitda_chg"].shift(1)
    up = (qi["q_margin_chg"] > 0).astype(float).where(qi["q_margin_chg"].notna())
    qi["q_margin_streak"] = up.groupby(qi["sid"]).transform(lambda s: s.rolling(4, min_periods=4).sum())
    return qi


def asof(hist, date_col, lag, anchors, cols):
    """Latest knowable row per sid at each anchor (date_col + lag <= anchor)."""
    h = hist[["sid", date_col] + cols].copy()
    h["known"] = pd.to_datetime(h[date_col]) + pd.Timedelta(days=lag)
    h = h.sort_values("known")
    a = pd.DataFrame({"snapshot_date": anchors, "t": pd.to_datetime(anchors)}).sort_values("t")
    out = []
    for sid, s in h.groupby("sid", sort=False):
        m = pd.merge_asof(a, s, left_on="t", right_on="known", direction="backward")
        m["sid"] = sid
        out.append(m[m["known"].notna()])
    return pd.concat(out)[["sid", "snapshot_date"] + cols]


def build():
    conn = ro()
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"]
                          + [f"fwd_{h}" for h in HORIZONS])
    lab = lab[lab["cap_tier"].isin(TIERS)]
    anchors = sorted(lab["snapshot_date"].unique())
    ann = asof(annual_history(conn), "period_end", ANNUAL_LAG, anchors, ANNUAL_F)
    qtr = asof(quarterly_history(conn), "end_date", QUARTERLY_LAG, anchors, QUARTER_F)
    ph = ",".join("?" * len(anchors))
    panel = pd.read_sql(f"SELECT sid, snapshot_date, mom_6m, book_to_price, piotroski_f, "
                        f"residual_momentum_12_1 FROM daily_snapshots_pit WHERE snapshot_date IN ({ph})",
                        conn, params=anchors)
    sector = pd.read_sql("SELECT sid, sector FROM stocks", conn)
    conn.close()
    df = (lab.merge(ann, on=["sid", "snapshot_date"], how="left")
             .merge(qtr, on=["sid", "snapshot_date"], how="left")
             .merge(panel, on=["sid", "snapshot_date"], how="left")
             .merge(sector, on="sid", how="left"))
    fin = df["sector"].isin(SCREEN["financial_sectors"])
    for c in EBIT_F:
        df.loc[fin, c] = np.nan
    for c in ANNUAL_F + QUARTER_F:   # winsorise 1/99 per anchor so a few absurd ratios don't matter
        q = df.groupby("snapshot_date")[c].transform
        df[c] = df[c].clip(q(lambda s: s.quantile(.01)), q(lambda s: s.quantile(.99)))
    grp = df.groupby(["snapshot_date", "cap_tier"])
    for name, (a, b) in INTER.items():
        df[name] = (grp[a].rank(pct=True) + grp[b].rank(pct=True)) / 2
    df.to_parquet(LH / "growth_features.parquet", index=False)
    return df


def nonoverlap_t(rows, h):
    step = h // 21
    ics = pd.Series([r[1] for r in rows], index=[r[0] for r in rows]).sort_index()
    ts = []
    for off in range(step):
        s = ics.iloc[off::step]
        if len(s) >= 3 and s.std() > 0:
            ts.append(s.mean() / (s.std() / np.sqrt(len(s))))
    return float(np.mean(ts)) if ts else None


def top_decile_excess(tdf, col, fwd):
    out = []
    for _, g in tdf[[col, fwd, "snapshot_date"]].dropna().groupby("snapshot_date"):
        if len(g) < 30:
            continue
        top = g[g[col] >= g[col].quantile(.9)]
        out.append(top[fwd].mean() - g[fwd].median())
    return float(np.mean(out)) if out else None


def test(df):
    feats = ANNUAL_F + QUARTER_F + list(INTER) + ["piotroski_f", "mom_6m", "residual_momentum_12_1"]
    recs = []
    for col in feats:
        for tier in TIERS:
            tdf = df[df["cap_tier"] == tier]
            for h in HORIZONS:
                rows = _compute_ic(tdf, col, f"fwd_{h}")
                r = _aggregate(rows, col, tier, "lh", cadence="monthly", nw_lag=NW_LAG[h]) if rows else None
                if not r:
                    continue
                rec = {"factor": col, "tier": tier, "h": h, "n": r["n_periods"], "ic": r["mean_ic"],
                       "t_nw": r["t_stat"], "t_nonoverlap": nonoverlap_t(rows, h),
                       "first": min(x[0] for x in rows)[:7], "stocks": r["n_stocks_avg"],
                       "top10_excess": top_decile_excess(tdf, col, f"fwd_{h}")}
                for p, (lo, hi) in PERIODS.items():
                    sub = [x[1] for x in rows if lo <= x[0] <= hi]
                    rec[f"ic_{p}"] = float(np.mean(sub)) if len(sub) >= 3 else None
                recs.append(rec)
    t = pd.DataFrame(recs)
    fam = t["factor"].isin(ANNUAL_F + QUARTER_F + list(INTER)) & (t["n"] >= 12)
    m = int(fam.sum())
    t["p"] = 2 * stats.t.sf(t["t_nw"].abs(), (t["n"] - 1).clip(lower=1))
    t["bonferroni_pass"] = fam & (t["p"] * m < 0.05)
    sign = np.sign(t["ic"])
    held = pd.concat([np.sign(t[f"ic_{p}"]).eq(sign) | t[f"ic_{p}"].isna() for p in PERIODS], axis=1).all(axis=1)
    t["passes_bar"] = fam & (t["t_nw"].abs() >= 2.5) & held
    t.to_csv(LH / "growth_tests.csv", index=False)
    print(f"family: {m} tests (n >= 12 anchors); Bonferroni |t| bar ~ "
          f"{stats.t.isf(0.025 / m, 60):.2f}")
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reuse", action="store_true")
    a = ap.parse_args()
    df = pd.read_parquet(LH / "growth_features.parquet") if a.reuse else build()
    cov = df.groupby("cap_tier")[ANNUAL_F + QUARTER_F].apply(lambda x: x.notna().mean()).T.round(2)
    first = {c: df.loc[df[c].notna(), "snapshot_date"].min() for c in ANNUAL_F + QUARTER_F}
    print("coverage (share of tier rows) and first anchor:")
    print(cov.assign(first=pd.Series(first)).to_string())
    t = test(df)
    pd.set_option("display.width", 220)
    show = ["factor", "tier", "h", "n", "first", "ic", "t_nw", "t_nonoverlap", "top10_excess",
            "ic_2020-22", "ic_2023-24", "ic_2025-26", "passes_bar", "bonferroni_pass"]
    for h in HORIZONS:
        print(f"\n=== horizon {h} sessions ===")
        print(t[t["h"] == h].sort_values(["tier", "t_nw"], ascending=[True, False])[show]
              .round(3).to_string(index=False))


if __name__ == "__main__":
    main()
