"""
Alpha Signal v2 — the latest-knowable-quarter features the multibagger thesis' "business" part reads.

Pure functions over a DB connection, moved out of tools/lh_quarterly_nse.py (plan 0026 phase 2) so the live
desk (signals/multibagger.py) and the research tools compute the SAME numbers from one definition.

Sources, point in time: NSE XBRL `quarterly_results_nse` (first filing, knowable at `filed_at`) and Tickertape
`quarterly_income` (knowable at end_date + QUARTERLY_LAG). Every YoY is inside ONE source and ONE basis.
"""

import numpy as np
import pandas as pd

QUARTERLY_LAG = 60
QUARTER_F = ["q_rev_yoy", "q_rev_accel", "q_ebitda_chg", "q_profit_accel", "q_margin_chg",
             "q_margin_streak"]


def div(a, b):
    return np.where((b > 0) & np.isfinite(a) & np.isfinite(b), a / np.where(b > 0, b, 1), np.nan)


def features(q):
    """lh_growth.quarterly_history's formulas on one (sid, src, basis) series per group."""
    q = q.sort_values(["sid", "src", "basis", "period_end"]).reset_index(drop=True)
    key = [q["sid"], q["src"], q["basis"]]
    g = q.groupby(key)
    ed = pd.to_datetime(q["period_end"])
    lag4 = (ed - pd.to_datetime(g["period_end"].shift(4))).dt.days.between(350, 380)
    q["margin"] = div(q["ebitda"], q["revenue"])
    q["q_rev_yoy"] = np.where(lag4, div(q["revenue"], g["revenue"].shift(4)) - 1, np.nan)
    q["q_ebitda_chg"] = np.where(lag4, div(q["ebitda"] - g["ebitda"].shift(4), g["revenue"].shift(4)), np.nan)
    q["q_margin_chg"] = np.where(lag4, q["margin"] - g["margin"].shift(4), np.nan)
    g = q.groupby(key)
    q["q_rev_accel"] = q["q_rev_yoy"] - g["q_rev_yoy"].shift(1)
    q["q_profit_accel"] = q["q_ebitda_chg"] - g["q_ebitda_chg"].shift(1)
    up = (q["q_margin_chg"] > 0).astype(float).where(q["q_margin_chg"].notna())
    q["q_margin_streak"] = up.groupby(key).transform(lambda s: s.rolling(4, min_periods=4).sum())
    return q


def history(conn):
    nse = pd.read_sql("SELECT sid, period_end, basis, filed_at, revenue, other_income, finance_costs, "
                      "depreciation, pbt_pre_exceptional FROM quarterly_results_nse", conn)
    nse = nse.dropna(subset=["filed_at"]).sort_values("filed_at")
    nse = nse.drop_duplicates(["sid", "period_end", "basis"], keep="first")     # original filing only
    nse["ebitda"] = (nse["pbt_pre_exceptional"] + nse["finance_costs"].fillna(0)
                     + nse["depreciation"].fillna(0) - nse["other_income"].fillna(0))
    nse["known"] = pd.to_datetime(nse["filed_at"].str[:10], errors="coerce")
    nse["src"] = "nse"
    tt = pd.read_sql("SELECT sid, end_date AS period_end, reporting, revenue, ebitda FROM quarterly_income "
                     "WHERE end_date IS NOT NULL", conn)
    tt["basis"] = np.where(tt["reporting"] == "consolidated", "consolidated", "standalone")
    tt = tt.drop_duplicates(["sid", "period_end", "basis"], keep="last")
    tt["known"] = pd.to_datetime(tt["period_end"]) + pd.Timedelta(days=QUARTERLY_LAG)
    tt["src"] = "tt"
    cols = ["sid", "period_end", "basis", "src", "known", "revenue", "ebitda"]
    h = features(pd.concat([nse[cols], tt[cols]], ignore_index=True).dropna(subset=["known"]))
    h["pref"] = (h["src"] == "tt") * 2 + (h["basis"] == "standalone")          # 0 = NSE consolidated
    return h


def asof(h, anchors):
    """Per anchor, the latest knowable quarter per sid; within that quarter the preferred source/basis."""
    h = h.dropna(subset=["q_rev_yoy"]).sort_values(["sid", "known"])
    rows = []
    for a in anchors:
        k = h[h["known"] <= pd.Timestamp(a)]
        if k.empty:
            continue
        k = k.sort_values(["sid", "period_end", "pref"]).drop_duplicates(["sid", "period_end"], keep="first")
        k = k.drop_duplicates("sid", keep="last")              # latest quarter (sorted by period_end)
        rows.append(k.assign(snapshot_date=a)[["sid", "snapshot_date", "src"] + QUARTER_F])
    return pd.concat(rows, ignore_index=True)
