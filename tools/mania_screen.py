"""
Plan 0025 task 7.3 — a mania exclusion screen: an avoid list for every book.  (READ-ONLY on the DB;
writes data/lh/v2/mania_*)

Why: the doubler study (docs/studies/doubler-study-2026-10.md §3) found that speculation runs (Brightcom, TTML,
RattanIndia) had no fundamental signal and all ended in a SEBI action or a > 50 % crash, and that forensic-flagged
and penny names double about as often as the rest but halve twice as often. CAVEAT: those two profiles were read
from the same 2019-25 data, so the forensic / penny parts are not out of sample; the rule below is fixed before
any result of this tool.

PRE-REGISTRATION (2026-10-13, before any result of this tool):
Panel  monthly anchors 2019-12 … 2025-09 of data/lh/labels.parquet (a 12-month outcome exists), PIT tiers SMALL and
       MID; only stocks a book could buy: 20-session median traded value >= ₹1 crore. SMALL decides.
       Prices, momentum, liquidity and the label-artifact drop come from tools.theme_momentum.build().
Flags at anchor a (data dated before a, or on it):
  hot        6-month return (126 sessions, adjusted) in the top fifth of its (anchor, tier).
  no_fund    the latest annual statement knowable at a (tools.lh_growth: period end + 150 days) shows sales growth
             <= 0 AND core-EBIT change <= 0 (both known; Financials have no EBIT feature, so never no_fund).
  penny      raw close < ₹50 on the last session <= a.
  low_float  promoter holding >= 74.5 % in the latest shareholding filing with filed_at < a (at the SEBI 75 % cap).
  pref       a BSE 'Preferential Issue' or 'Allotment of Warrants' filing in [a − 365 days, a).
  forensic   forensic_penalty < 0 in daily_snapshots_pit at a (Beneish or Altman flag).
Screens (both pre-registered):
  BROAD   hot AND (no_fund OR penny OR low_float OR pref OR forensic)      — the plan's list, any one flag
  NARROW  hot AND no_fund AND (penny OR low_float OR pref OR forensic)     — momentum with no fundamentals plus a
                                                                             speculation marker
Comparison  flagged names vs the UNFLAGGED hot names of the same (anchor, tier): the names a momentum book would hold
       instead. Outcome fwd_252; excess = fwd_252 − the tier median at that anchor (all tier names, before the floor).
Bar (per screen, SMALL), all four:
  1. P(halve: fwd_252 <= −50 %) of flagged >= 1.5 × that of unflagged hot
  2. median excess of flagged < that of unflagged hot
  3. mean excess of flagged < that of unflagged hot (the screen does not throw away the winners that pay for the losers)
  4. (2) holds in both 2019-12 … 2022-12 and 2023-01 … 2025-09
  and >= 100 flagged stock-months, else "too few to judge".
Decision  a screen that passes becomes an avoid list for every book (paper sleeve, theme sleeve): no new buy while
       flagged (Amit to approve). Both pass → NARROW (fewer names excluded, lower cost of being wrong).
       Neither → no mania screen; the forensic flag stays a review prompt.
Diagnostics (never decide): each single flag (hot AND flag); flagged vs the whole tier; MID; P(double); the share of
the 7.1 theme top 20 that each screen would have excluded, and their outcome.

Usage: python -m tools.mania_screen
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.theme_momentum import FLOOR_INR, TIERS, build, scores  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
FROM, TO, SPLIT = "2019-12-01", "2025-09-01", "2023-01-01"
FLAGS = ("no_fund", "penny", "low_float", "pref", "forensic")
PREF_SUBS = ("Preferential Issue", "Allotment of Warrants")


def flags(d):
    anchors = sorted(d["snapshot_date"].unique())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(anchors))
    fr = pd.read_sql(f"SELECT sid, snapshot_date, forensic_penalty FROM daily_snapshots_pit WHERE snapshot_date IN ({ph})",
                     con, params=anchors)
    raw = pd.read_sql("SELECT sid, date, close FROM stock_prices WHERE close > 0 AND date >= '2019-11-01'", con)
    sh = pd.read_sql("SELECT sid, filed_at, promoter_pct FROM shareholding_categories WHERE filed_at IS NOT NULL", con)
    pr = pd.read_sql(f"SELECT sid, substr(dt_tm, 1, 10) AS d FROM bse_announcements WHERE sid IS NOT NULL AND "
                     f"subcategory IN ({','.join('?' * len(PREF_SUBS))})", con, params=list(PREF_SUBS))
    con.close()
    gf = pd.read_parquet(LH / "growth_features.parquet", columns=["sid", "snapshot_date", "a_sales_g1", "a_ebit_chg"])

    raw = raw.sort_values("date")
    sh = sh.sort_values("filed_at")
    parts = []
    for a in anchors:
        close = raw[(raw["date"] <= a) & (raw["date"] >= (pd.Timestamp(a) - pd.Timedelta(days=10)).date().isoformat())] \
            .groupby("sid")["close"].last()
        prom = sh[sh["filed_at"] < a].groupby("sid")["promoter_pct"].last()
        lo = (pd.Timestamp(a) - pd.Timedelta(days=365)).date().isoformat()
        pref = set(pr[(pr["d"] >= lo) & (pr["d"] < a)]["sid"])
        parts.append(pd.DataFrame({"sid": close.index.union(prom.index)}).assign(
            snapshot_date=a,
            raw_close=lambda x: x["sid"].map(close),
            promoter_pct=lambda x: x["sid"].map(prom),
            pref=lambda x: x["sid"].isin(pref)))
    f = pd.concat(parts, ignore_index=True)
    d = d.merge(f, on=["sid", "snapshot_date"], how="left").merge(fr, on=["sid", "snapshot_date"], how="left") \
         .merge(gf, on=["sid", "snapshot_date"], how="left")
    d["hot"] = d.groupby(["snapshot_date", "cap_tier"])["mom_6m"].rank(pct=True) > 0.8
    d["no_fund"] = (d["a_sales_g1"] <= 0) & (d["a_ebit_chg"] <= 0)
    d["penny"] = d["raw_close"] < 50
    d["low_float"] = d["promoter_pct"] >= 74.5
    d["pref"] = d["pref"].fillna(False).astype(bool)
    d["forensic"] = d["forensic_penalty"].fillna(0) < 0
    marker = d["penny"] | d["low_float"] | d["pref"] | d["forensic"]
    d["BROAD"] = d["hot"] & (d["no_fund"] | marker)
    d["NARROW"] = d["hot"] & d["no_fund"] & marker
    for c in FLAGS:
        d[f"hot&{c}"] = d["hot"] & d[c]
    return d


def stats(g):
    return dict(n=len(g), p_double=g["fwd_252"].ge(1.0).mean(), p_halve=g["fwd_252"].le(-0.5).mean(),
                median_ex=g["ex"].median(), mean_ex=g["ex"].mean())


def compare(d, col):
    rows = []
    periods = {"all": lambda x: x == x, "2019-22": lambda x: x < SPLIT, "2023-25": lambda x: x >= SPLIT}
    for tier in TIERS:
        t = d[d["cap_tier"] == tier]
        for per, f in periods.items():
            p = t[f(t["snapshot_date"])]
            fl, un = p[p[col]], p[p["hot"] & ~p[col]]
            a, b, w = stats(fl), stats(un), stats(p)
            rows.append(dict(screen=col, tier=tier, period=per, flagged_n=a["n"], unflagged_hot_n=b["n"],
                             **{f"flag_{k}": v for k, v in a.items() if k != "n"},
                             **{f"hot_{k}": v for k, v in b.items() if k != "n"},
                             tier_p_halve=w["p_halve"], tier_median_ex=w["median_ex"],
                             halve_ratio=a["p_halve"] / b["p_halve"] if b["p_halve"] else np.nan))
    return pd.DataFrame(rows)


def verdict(R, screen):
    s = R[(R["screen"] == screen) & (R["tier"] == "SMALL")].set_index("period")
    al = s.loc["all"]
    if al["flagged_n"] < 100:
        return dict(screen=screen, result="too few to judge", flagged_n=int(al["flagged_n"]))
    bars = {"halve_1.5x": bool(al["flag_p_halve"] >= 1.5 * al["hot_p_halve"]),
            "median_lower": bool(al["flag_median_ex"] < al["hot_median_ex"]),
            "mean_lower": bool(al["flag_mean_ex"] < al["hot_mean_ex"]),
            "median_lower_both_periods": bool((s.loc[["2019-22", "2023-25"], "flag_median_ex"]
                                               < s.loc[["2019-22", "2023-25"], "hot_median_ex"]).all())}
    return dict(screen=screen, bars=bars, passes=all(bars.values()), flagged_n=int(al["flagged_n"]))


def main():
    pd.set_option("display.width", 260)
    d = build()
    S = scores(d)
    d["theme_top20"] = False
    th = d.assign(s=S["theme"]).dropna(subset=["s"]).sort_values("s", ascending=False).groupby(
        ["snapshot_date", "cap_tier"]).head(20).index
    d.loc[th, "theme_top20"] = True
    d = flags(d)
    d = d[(d["snapshot_date"] >= FROM) & (d["snapshot_date"] <= TO) & (d["adtv"] >= FLOOR_INR)
          & d["fwd_252"].notna() & ~d["artifact"]]
    d.to_parquet(V2 / "mania_panel.parquet", index=False)
    print(f"panel {len(d):,} stock-months (floored, with outcome); hot share {d['hot'].mean():.3f}; "
          f"flag shares among hot: " + ", ".join(f"{c} {d.loc[d['hot'], c].mean():.3f}" for c in FLAGS)
          + f"; BROAD {d.loc[d['hot'], 'BROAD'].mean():.3f}, NARROW {d.loc[d['hot'], 'NARROW'].mean():.3f}")
    R = pd.concat([compare(d, c) for c in ["NARROW", "BROAD"] + [f"hot&{c}" for c in FLAGS]], ignore_index=True)
    R.to_csv(V2 / "mania_compare.csv", index=False)
    print(R.round(3).to_string(index=False))
    v = {s: verdict(R, s) for s in ("NARROW", "BROAD")}
    passing = [s for s in ("NARROW", "BROAD") if v[s].get("passes")]
    v["decision"] = (f"adopt {passing[0]} as an avoid list for every book (Amit to approve)" if passing
                     else "no mania screen; the forensic flag stays a review prompt")
    # diagnostic: what each screen would have removed from the 7.1 theme top 20
    tt = d[d["theme_top20"]]
    v["theme_top20"] = {s: dict(share_excluded=round(float(tt[s].mean()), 3),
                                excluded=stats(tt[tt[s]]), kept=stats(tt[~tt[s]])) for s in ("NARROW", "BROAD")
                        if len(tt)}
    (V2 / "mania_summary.json").write_text(json.dumps(v, indent=1, default=str))
    print(json.dumps(v, indent=1, default=str))


if __name__ == "__main__":
    main()
