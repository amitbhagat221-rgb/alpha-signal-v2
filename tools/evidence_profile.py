"""
Alpha Signal v2 — Evidence profile of the wired factors (plan 0020, study §5 items 3-5). READ-ONLY.

The evidence table gives one number per (factor, tier): the t of the 20-day rank IC over
whatever history the factor has. This puts beside it what that number hides:

  t_common     the t on the window every wired factor shares (from the latest first
               anchor among them), so factors with 2 and 6 years of history compare
  t_full_mkt   the t with dead and never-listed names added (price factors only;
               tools/unlisted_panel)
  rank_ac      median rank correlation of the factor between consecutive monthly anchors
               (1.0 = the ranking never changes; a daily re-rank then adds noise only)
  turnover     share of the top fifth that is not in the top fifth a month later
  spread       mean 20-day return of the top tenth minus the bottom tenth, in the
               weight's direction (percent)
  sector_t     for a factor with one value per sector: the t of its IC across sectors
               against the sector's average return — the test such a factor deserves,
               instead of a stock-level IC on ties

Usage:
    python -m tools.evidence_profile
    python -m tools.evidence_profile --md docs/studies/evidence-profile-2026-10.md
"""
import argparse
from datetime import date

import numpy as np
import pandas as pd

import factors
from config import PICKABLE_TIERS
from db import read_sql
from tools.backtest_pit import FULL_MARKET, _aggregate, _compute_ic, _is_month_start_anchor, _nw_lag_for, iter_panels
from tools.walk_forward import _md, _ranked_col

LABEL = "fwd_return_20d"


def _t(ics, sig=None, cadence="monthly"):
    """t of a mean IC series — Newey-West at the backtest's lag for the factor's cadence."""
    ics = list(ics)
    if len(ics) < 3:
        return None
    r = _aggregate([(i, ic, 50) for i, ic in enumerate(ics)], sig, None, "profile", cadence=cadence,
                   nw_lag=_nw_lag_for(sig, cadence) if sig else 0)
    return r["t_stat"] if r else None


def _monthly(df):
    return df[[_is_month_start_anchor(date.fromisoformat(d)) for d in df["snapshot_date"]]]


def profile():
    wired = [(t, k, _ranked_col(k, t), w) for t, ws in factors.SIGNAL_WEIGHTS.items() for k, w in ws.items()]
    cols = sorted({c for *_, c, _ in wired})
    sel = ", ".join(f'"{c}"' for c in ["sid", "snapshot_date", "cap_tier", "sector", LABEL, *cols] if c != "sector")
    panel = read_sql(f"SELECT {sel} FROM daily_snapshots_pit").merge(read_sql("SELECT sid, sector FROM stocks"), on="sid", how="left")
    full = read_sql("SELECT signal, cap_tier, t_stat FROM pit_ic_by_tier_v2 WHERE source LIKE ?", params=[FULL_MARKET + "%"])
    full = {(r.signal, r.cap_tier): r.t_stat for r in full.itertuples()}

    series, cadence = {}, {}
    for tier, key, col, w in wired:
        sig = factors.signal_for(key, tier)
        for _, cad, _, _, tier_, tdf in iter_panels(panel.iloc[:0], panel, [(sig, (None, col))]):
            if tier_ == tier:
                series[(tier, key)] = pd.Series({d: ic for d, ic, _ in _compute_ic(tdf, col, LABEL)}).sort_index()
                cadence[(tier, key)] = cad
    common = {t: max(s.index.min() for (tt, _), s in series.items() if tt == t and len(s)) for t in PICKABLE_TIERS}

    rows = []
    for tier, key, col, w in wired:
        s = series.get((tier, key), pd.Series(dtype=float))
        m = _monthly(panel[panel["cap_tier"] == tier])
        piv = m.pivot_table(index="sid", columns="snapshot_date", values=col)
        ac, to = [], []
        for a, b in zip(piv.columns[:-1], piv.columns[1:]):
            x = piv[[a, b]].dropna()
            if len(x) >= 20:
                ac.append(x[a].rank().corr(x[b].rank()))
                top = lambda c: set(x.index[x[c].rank(pct=True) > 0.8]) if w > 0 else set(x.index[x[c].rank(pct=True) <= 0.2])
                ta = top(a)
                to.append(len(ta - top(b)) / len(ta) if ta else np.nan)
        spreads, sector_ics = [], []
        for d, g in m.groupby("snapshot_date"):
            g = g.dropna(subset=[col, LABEL])
            if len(g) >= 20:
                r = g[col].rank(pct=True) if w > 0 else 1 - g[col].rank(pct=True)
                spreads.append(g.loc[r > 0.9, LABEL].mean() - g.loc[r <= 0.1, LABEL].mean())
            per = g.groupby("sector").agg(f=(col, "mean"), r=(LABEL, "mean"), n=(col, "size"), k=(col, "nunique"))
            if len(per) >= 8 and (per["k"] == 1).mean() > 0.9:          # one value per sector: a sector factor
                sector_ics.append(per["f"].rank().corr(per["r"].rank()))
        sig, cad = factors.signal_for(key, tier), cadence.get((tier, key), "monthly")
        rows.append({"tier": tier, "factor": key, "weight": f"{w:+.2f}", "anchors": len(s), "t": _t(s.values, sig, cad),
                     "from": s.index.min() if len(s) else None,
                     "t_common": _t(s[s.index >= common[tier]].values, sig, cad),
                     "t_full_mkt": full.get((factors.signal_for(key, tier), tier)),
                     "rank_ac": round(float(np.nanmedian(ac)), 2) if ac else None,
                     "turnover": round(float(np.nanmean(to)), 2) if to else None,
                     "spread_pct": round(float(np.mean(spreads)) * 100, 2) if spreads else None,
                     "sector_t": _t(sector_ics) if len(sector_ics) >= 12 else None})
    return pd.DataFrame(rows), common


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--md")
    a = ap.parse_args()
    df, common = profile()
    print(df.to_string(index=False))
    print("\ncommon window starts:", common)
    if a.md:
        open(a.md, "w").write(
            "# Evidence profile of the wired factors\n\nGenerated by `python -m tools.evidence_profile` "
            f"(t on the 20-day rank IC; common window from {common}).\n\n{_md(df)}\n")
