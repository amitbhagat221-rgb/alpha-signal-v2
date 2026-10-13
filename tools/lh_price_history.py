"""
Plan 0025 task 5.2 — price signals on the full NSE market, 2010 → 2026, delisted names included.
(READ-ONLY on the DB; writes data/lh/v2/pricehist_*)

PRE-REGISTRATION (2026-10-13, after the legacy bhavcopy backfill, before any result):

Prices: stock_prices (today's universe, 2010+, split/bonus/dividend adjusted by corporate_adjustments
via signals._prices.apply_adjustments) + stock_prices_unlisted series EQ/BE (delisted, merged and
non-universe names, keyed "U:<symbol>"). Unlisted names have no corporate-action record, so a
one-day move beyond what the price band allows (close ratio < 0.70 or > 1.45 between sessions at most
7 calendar days apart) is treated as a split/bonus and neutralised by back-adjustment. Longer gaps
(suspensions) and multi-day falls are kept as real.

Anchors: the first trading session of each month, 2011-01 → the last with a 126-session label.
Size groups (market cap is unknown for delisted names): rank by 126-session median traded value
(close × volume, nominal ₹) among names that traded on >= 80 % of those sessions:
  T1 = ranks 1-100, T2 = 101-250, T3 = 251-1000 (stand-ins for LARGE / MID / SMALL).
Signals at the anchor close (>= 252 sessions of history, >= 200 prices):
  mom_12_1 = P(t−21) / P(t−252) − 1     mom_6m = P(t) / P(t−126) − 1
  pos_52w  = P(t) / max P(t−252 … t)    low_vol = −std(daily returns, 252)
  rev_21   = −(P(t) / P(t−21) − 1)      (short-term reversal, sign so higher = expected better)
Label: entry at the next session's close; exit 126 sessions later, or the last traded close if the
name stops trading first (delisting return kept, never dropped).
Tests per group: within-group rank IC at 126 (and 21, 252), non-overlap t (every 6th anchor,
averaged over offsets), top-decile excess vs the group median, IC by period 2011-14 / 2015-19 /
2020-22 / 2023-26; the same on SURVIVORS ONLY (names in today's universe) to measure the bias.
Pass ("robust over 15 years"): full-market non-overlap t >= 2.0 at 126 in T3 AND the sign held in >= 3 of
the 4 periods.
Price-crash monitor, full market: last month's return in the group's bottom 5 % → 126-session median
excess, false-alarm rate (share beating the group median), and the share that stopped trading
within 126 sessions (vs every name).

Usage: python -m tools.lh_price_history
"""

import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from signals._prices import apply_adjustments  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
V2 = PROJECT_ROOT / "data" / "lh" / "v2"
H = 126
GROUPS = {"T1": (1, 100), "T2": (101, 250), "T3": (251, 1000)}
PERIODS = {"2011-14": ("2011", "2014-12-31"), "2015-19": ("2015", "2019-12-31"),
           "2020-22": ("2020", "2022-12-31"), "2023-26": ("2023", "2026-12-31")}
SIGNALS = ["mom_12_1", "mom_6m", "pos_52w", "low_vol", "rev_21"]


def load():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    px = pd.read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date >= '2009-06-01'", con)
    adj = pd.read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments", con)
    un = pd.read_sql("SELECT symbol, date, close, volume FROM stock_prices_unlisted WHERE close > 0 AND series IN ('EQ','BE') "
                     "AND date >= '2009-06-01'", con)
    con.close()
    px = apply_adjustments(px, adj, date.max)
    px["id"] = px["sid"]
    un["id"] = "U:" + un["symbol"]
    un = un.sort_values(["id", "date"]).drop_duplicates(["id", "date"], keep="last")
    un["adj_close"] = un["close"]
    # neutralise impossible one-day moves (unrecorded splits / bonuses) in unlisted names
    g = un.groupby("id")
    r = un["close"] / g["close"].shift(1)
    gap = (pd.to_datetime(un["date"]) - pd.to_datetime(g["date"].shift(1))).dt.days
    jump = ((r < 0.70) | (r > 1.45)) & (gap <= 7)
    fac = pd.Series(np.where(jump, r, 1.0), index=un.index)
    # back-adjust: every price before a jump is scaled by the product of later jump factors
    un["adj_close"] = un["close"] * fac.groupby(un["id"]).transform(lambda s: s[::-1].cumprod()[::-1].shift(-1).fillna(1.0))
    n_jumps = int(jump.sum())
    allp = pd.concat([px[["id", "date", "adj_close", "close", "volume"]], un[["id", "date", "adj_close", "close", "volume"]]])
    allp["tv"] = allp["close"] * allp["volume"]
    P = allp.pivot_table(index="date", columns="id", values="adj_close", aggfunc="last").sort_index()
    TV = allp.pivot_table(index="date", columns="id", values="tv", aggfunc="last").reindex(P.index)
    survivors = set(px["sid"])
    print(f"prices: {P.shape[1]} names ({len(survivors)} in today's universe), {P.shape[0]} sessions "
          f"{P.index[0]} → {P.index[-1]}; unlisted split-like jumps neutralised: {n_jumps}", flush=True)
    return P.astype("float32"), TV.astype("float32"), survivors


def panel(P, TV, survivors):
    dates = P.index
    month_first = pd.Series(dates, index=pd.to_datetime(dates)).groupby(pd.to_datetime(dates).to_period("M")).first()
    anchors = [d for d in month_first.values if d >= "2011-01-01"]
    pos = {d: i for i, d in enumerate(dates)}
    R = P.pct_change(fill_method=None)
    rows = []
    for a in anchors:
        i = pos[a]
        if i + 1 + H >= len(dates) or i < 252:
            continue
        win = P.iloc[i - 252:i + 1]
        tvw = TV.iloc[i - 125:i + 1]
        traded = tvw.notna().mean()
        adtv = tvw.median()
        ok = (win.notna().sum() >= 200) & (traded >= 0.8) & P.iloc[i].notna()
        ids = ok[ok].index
        rank = adtv[ids].rank(ascending=False, method="first")
        p_t, p21, p126, p252 = P.iloc[i][ids], P.iloc[i - 21][ids], P.iloc[i - 126][ids], P.iloc[i - 252][ids]
        f = pd.DataFrame({"id": ids, "rank": rank.values,
                          "mom_12_1": (p21 / p252 - 1).values, "mom_6m": (p_t / p126 - 1).values,
                          "pos_52w": (p_t / win[ids].max()).values,
                          "low_vol": (-R.iloc[i - 251:i + 1][ids].std()).values,
                          "rev_21": (-(p_t / p21 - 1)).values,
                          "last_month": (p_t / p21 - 1).values})
        # label: entry next session close, exit +126 sessions or the last traded close (delisting)
        fut = P.iloc[i + 1:i + 2 + H][ids]
        entry = fut.iloc[0]
        exit_ = fut.iloc[-1].where(fut.iloc[-1].notna(), fut.ffill().iloc[-1])
        stopped = fut.iloc[-1].isna() & entry.notna()
        f["fwd"] = (exit_ / entry - 1).values
        f["stopped"] = stopped.values
        fut21 = P.iloc[i + 1:i + 2 + 21][ids]
        f["fwd21"] = (fut21.ffill().iloc[-1] / fut21.iloc[0] - 1).values
        f["anchor"] = a
        f["survivor"] = f["id"].isin(survivors)
        f["group"] = np.select([f["rank"] <= 100, f["rank"] <= 250, f["rank"] <= 1000], ["T1", "T2", "T3"], "out")
        rows.append(f[f["group"] != "out"].dropna(subset=["fwd"]))
    df = pd.concat(rows, ignore_index=True)
    print(f"panel: {len(df):,} rows, {df['anchor'].nunique()} anchors {df['anchor'].min()} → {df['anchor'].max()}, "
          f"delisted-or-outside names {(~df['survivor']).mean():.1%} of rows", flush=True)
    return df


def nonoverlap_t(s, step=6):
    s = s.dropna().sort_index()
    ts = [x.mean() / (x.std() / np.sqrt(len(x))) for x in (s.iloc[o::step] for o in range(step)) if len(x) >= 3 and x.std() > 0]
    return float(np.mean(ts)) if ts else np.nan


def tests(df):
    recs = []
    for universe, d0 in (("full", df), ("survivors", df[df["survivor"]])):
        for grp, d in d0.groupby("group"):
            for sig in SIGNALS:
                ic = d.groupby("anchor").apply(lambda x: x[sig].rank().corr(x["fwd"].rank()) if x[sig].notna().sum() >= 30 else np.nan).dropna()
                ic21 = d.groupby("anchor").apply(lambda x: x[sig].rank().corr(x["fwd21"].rank()) if x[sig].notna().sum() >= 30 else np.nan).dropna()
                top = d.groupby("anchor").apply(lambda x: x.loc[x[sig] >= x[sig].quantile(.9), "fwd"].mean() - x["fwd"].median()).dropna()
                rec = dict(universe=universe, group=grp, signal=sig, anchors=len(ic), ic126=round(ic.mean(), 4),
                           t_no126=round(nonoverlap_t(ic), 2), ic21=round(ic21.mean(), 4), top10_excess=round(top.mean(), 4))
                for p, (lo, hi) in PERIODS.items():
                    sub = ic[(ic.index >= lo) & (ic.index <= hi)]
                    rec[f"ic_{p}"] = round(sub.mean(), 4) if len(sub) >= 6 else np.nan
                rec["periods_positive"] = int(sum((rec[f"ic_{p}"] or 0) > 0 for p in PERIODS))
                rec["robust"] = bool(universe == "full" and grp == "T3" and rec["t_no126"] >= 2.0 and rec["periods_positive"] >= 3)
                recs.append(rec)
    t = pd.DataFrame(recs)
    # price-crash monitor (full market)
    crash = []
    for grp, d in df.groupby("group"):
        d = d.copy()
        d["ex"] = d["fwd"] - d.groupby("anchor")["fwd"].transform("median")
        d["crash"] = d.groupby("anchor")["last_month"].rank(pct=True) <= 0.05
        c = d[d["crash"]]
        per = c.groupby("anchor")["ex"].mean()
        crash.append(dict(group=grp, events=len(c), median_excess=round(c["ex"].median(), 4),
                          mean_excess=round(c["ex"].mean(), 4), false_alarm=round((c["ex"] > 0).mean(), 3),
                          t_no=round(nonoverlap_t(per), 2), stopped_trading=round(c["stopped"].mean(), 4),
                          stopped_all=round(d["stopped"].mean(), 4)))
    return t, pd.DataFrame(crash)


def main():
    P, TV, survivors = load()
    df = panel(P, TV, survivors)
    df.to_parquet(V2 / "pricehist_panel.parquet", index=False)
    t, crash = tests(df)
    t.to_csv(V2 / "pricehist_tests.csv", index=False)
    crash.to_csv(V2 / "pricehist_crash.csv", index=False)
    pd.set_option("display.width", 230)
    print(t.to_string(index=False))
    print("\nprice-crash monitor (full market):\n", crash.to_string(index=False))


if __name__ == "__main__":
    main()
