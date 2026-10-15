"""
Alpha Signal v2 — Quarterly profit growth, year on year (plan 0025 task 5.1, promoted 2026-10-15).

`q_ebitda_chg` — the latest quarter's operating profit minus the same quarter a year
earlier, divided by that year-ago quarter's revenue:

    (EBITDA_q − EBITDA_q−4) / revenue_q−4

Scaling by revenue (not by the year-ago profit) keeps loss-to-profit turns and tiny bases
finite and puts every company on one "profit gained per rupee of sales" scale.

Construction (per sid, as of eval_date D):
  - Two quarterly sources, never mixed inside one comparison:
      NSE  quarterly_results_nse (XBRL, 2017-06 → 2024-12). Each (quarter, basis) uses its
           FIRST filing, knowable from its filed_at date (strictly before D); later
           restatements are ignored. EBITDA = pbt_pre_exceptional + finance_costs +
           depreciation − other_income (operating profit before one-offs).
      TT   quarterly_income (Tickertape), already sliced by pit.knowable_quarterly
           (quarter end + 60 days, and our copy held it); `ebitda` as reported.
  - The year-ago quarter must be 350–380 days earlier, from the SAME source and basis.
  - Per quarter: NSE before TT, consolidated before standalone. The latest quarter with a
    value is used, if it ended within STALE_DAYS of D (else NULL: no 2024 quarter carried
    into a live 2026 score). Financials → NULL (bank "revenue" and "EBITDA" are not this).

Expected sign: POSITIVE. Evidence (docs/studies/quarterly-nse-2026-10.md, 77 monthly anchors
2019-12 → 2026-10): SMALL 126-session non-overlap t 3.85 (NW 6.12), same sign 2020-22 /
2023-24 / 2025-26, Bonferroni pass; 2.14 net of announcement_car + momentum. MID / LARGE ≈ 0.

Reads:   quarterly_results_nse (pit.RAW_SQL['nse_q']), quarterly_income (pit 'qi'), stocks
Returns: DataFrame[sid, q_ebitda_chg]

The live path and pit.py:pit_q_ebitda_chg run this same function.

Usage:
    python -m signals.quarterly_growth     # live compute + print stats (input via pit.load_raw)
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from config import SCREEN

STALE_DAYS = 270          # latest usable quarter must end within this many days of D
YOY_DAYS = (350, 380)     # the year-ago quarter's distance
NSE_SQL = ("SELECT sid, period_end, basis, filed_at, revenue, other_income, finance_costs, "
           "depreciation, pbt_pre_exceptional FROM quarterly_results_nse "
           "WHERE filed_at IS NOT NULL ORDER BY sid, period_end")
COLS = ["sid", "q_ebitda_chg"]


def _nse_quarters(nse: pd.DataFrame, as_of: str) -> pd.DataFrame:
    n = nse[nse["filed_at"].str[:10] < as_of]
    n = n.sort_values("filed_at").drop_duplicates(["sid", "period_end", "basis"], keep="first")
    ebitda = (n["pbt_pre_exceptional"] + n["finance_costs"].fillna(0) + n["depreciation"].fillna(0)
              - n["other_income"].fillna(0))
    return pd.DataFrame({"sid": n["sid"], "period_end": n["period_end"], "basis": n["basis"],
                         "src": 0, "revenue": n["revenue"], "ebitda": ebitda})


def _tt_quarters(qi: pd.DataFrame) -> pd.DataFrame:
    basis = np.where(qi["reporting"] == "consolidated", "consolidated", "standalone")
    t = pd.DataFrame({"sid": qi["sid"], "period_end": qi["end_date"], "basis": basis,
                      "src": 1, "revenue": qi["revenue"], "ebitda": qi["ebitda"]})
    return t.drop_duplicates(["sid", "period_end", "basis"], keep="last")


def compute_q_ebitda_chg(
    stocks: pd.DataFrame,
    nse: pd.DataFrame | None,
    qi: pd.DataFrame | None,
    as_of_date: str | None = None,
) -> pd.DataFrame:
    """`nse` = rows of NSE_SQL, `qi` = knowable quarterly_income rows; signals/ never reads the DB."""
    as_of = as_of_date or date.today().isoformat()
    parts = []
    if nse is not None and not nse.empty:
        parts.append(_nse_quarters(nse, as_of))
    if qi is not None and not qi.empty:
        parts.append(_tt_quarters(qi))
    if not parts:
        return pd.DataFrame(columns=COLS)
    q = pd.concat(parts, ignore_index=True).dropna(subset=["period_end"])
    q = q.sort_values(["sid", "src", "basis", "period_end"]).reset_index(drop=True)

    g = q.groupby(["sid", "src", "basis"])
    gap = (pd.to_datetime(q["period_end"]) - pd.to_datetime(g["period_end"].shift(4))).dt.days
    rev4, e4 = g["revenue"].shift(4), g["ebitda"].shift(4)
    ok = gap.between(*YOY_DAYS) & (rev4 > 0) & q["ebitda"].notna() & e4.notna()
    q["q_ebitda_chg"] = np.where(ok, (q["ebitda"] - e4) / rev4.where(rev4 > 0, 1), np.nan)

    q = q.dropna(subset=["q_ebitda_chg"])
    q = q[q["period_end"] >= (date.fromisoformat(as_of) - timedelta(days=STALE_DAYS)).isoformat()]
    q["pref"] = q["src"] * 2 + (q["basis"] == "standalone")
    q = q.sort_values(["sid", "period_end", "pref"]).drop_duplicates(["sid", "period_end"], keep="first")
    q = q.drop_duplicates("sid", keep="last")                 # the latest quarter per sid

    fin = set(stocks.loc[stocks["sector"].isin(SCREEN["financial_sectors"]), "sid"])
    q = q[~q["sid"].isin(fin)]
    return pd.DataFrame({"sid": q["sid"].values, "q_ebitda_chg": q["q_ebitda_chg"].round(5).values},
                        columns=COLS)


if __name__ == "__main__":
    import pit
    raw = pit.load_raw(["stocks", "nse_q", "qi"])
    today = date.today()
    res = compute_q_ebitda_chg(raw["stocks"], raw["nse_q"], pit.knowable_quarterly(raw["qi"], today),
                               today.isoformat())
    s = res["q_ebitda_chg"].dropna()
    print(f"q_ebitda_chg — {len(s):,} stocks; median {s.median():.4f}, "
          f"p10 {s.quantile(.1):.4f}, p90 {s.quantile(.9):.4f}")
