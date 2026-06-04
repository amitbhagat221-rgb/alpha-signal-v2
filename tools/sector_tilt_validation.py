"""
Alpha Signal v2 — Daily Sector-Tilt Validation (the gate before wiring daily_picks)

`tools/sector_signal_lab.py` proved a sector-momentum(6m) + macro ensemble predicts
SECTOR returns (t+3). Before tilting daily_picks toward tailwind sectors we must
answer the only question that matters for the PRODUCT: does the sector signal add
value ORTHOGONAL to the stock-level momentum the model already ranks on? A stock in
a hot sector already carries high stock momentum, so a sector tilt could be pure
redundancy (and would just double down on momentum risk).

Method — 2022+ month-end stock panel (`stock_prices`), GICS sectors:
  per month t, per stock:
    stock_mom6  = trailing 6m stock return                    (already in the model)
    sector_sig  = its sector's ensemble z(mom6) + z(macro_score)   (candidate tilt)
    fwd3        = forward 3m stock return                     (target)
  Two tests:
    1. Double-sort 3×3 (stock-mom tercile × sector-signal tercile) → mean fwd3,
       averaged over months. Orthogonal value = high-minus-low sector-signal spread
       WITHIN each stock-mom row (if it's flat, the tilt adds nothing new).
    2. Fama-MacBeth: per-month cross-sectional OLS of fwd3 on z(stock_mom) and
       z(sector_sig); average slopes + t across months. Compare the sector_sig slope
       UNIVARIATE vs WITH stock_mom in the regression — if it survives, the tilt is
       additive; if it collapses, it's redundant with momentum.

Usage:
    python -m tools.sector_tilt_validation
"""

import numpy as np
import pandas as pd

from db import read_sql

FWD_K = 3                     # forward months (the t+3 horizon the lab validated)
MOM_M = 6                     # trailing-momentum lookback (months)
MIN_STOCKS_PER_SECTOR = 5     # need a real basket to trust a sector's signal
MIN_STOCKS_PER_MONTH = 100    # need a real cross-section for the monthly regression


def _z(s):
    s = s.astype(float)
    sd = s.std(ddof=0)
    return (s - s.mean()) / sd if sd else s * 0.0


def _panel():
    px = read_sql("SELECT sid, date, close FROM stock_prices WHERE close > 0")
    px["date"] = pd.to_datetime(px["date"])
    px["ym"] = px["date"].dt.to_period("M")
    me = px.sort_values("date").groupby(["sid", "ym"], as_index=False).last()
    mat = me.pivot(index="ym", columns="sid", values="close").sort_index()
    sec = read_sql("SELECT sid, sector FROM stocks").dropna(subset=["sector"]).set_index("sid")["sector"]
    return mat, sec


def _sector_basket_ret(mat, sec):
    """Monthly sector-basket return [month × sector] = median per-stock return."""
    ret = mat / mat.shift(1) - 1.0
    sectors = sorted(sec.dropna().unique())
    out = pd.DataFrame(index=mat.index, columns=sectors, dtype=float)
    for s in sectors:
        cols = [c for c in mat.columns if sec.get(c) == s]
        if not cols:
            continue
        sub = ret[cols]
        med = sub.median(axis=1, skipna=True)
        med[sub.notna().sum(axis=1) < MIN_STOCKS_PER_SECTOR] = np.nan
        out[s] = med
    return out


def _macro():
    ms = read_sql("SELECT sector, snapshot_date, macro_score FROM macro_sector_signals_pit "
                  "WHERE macro_score IS NOT NULL")
    if ms.empty:
        return pd.DataFrame()
    ms["snap"] = pd.to_datetime(ms["snapshot_date"]).dt.to_period("M")
    return ms.pivot_table(index="snap", columns="sector", values="macro_score")


def _build_obs(mat, sec, basket, macro):
    """One stacked frame of (month, sid, stock_mom6, sector_sig, fwd3)."""
    months = list(mat.index)
    frames = []
    for ti in range(len(months)):
        if ti - MOM_M < 0 or ti + FWD_K >= len(months):
            continue
        mth = months[ti]

        # sector ensemble signal = z(sector trailing-6m) + z(macro_score)
        sec_mom6 = (1.0 + basket.iloc[ti - MOM_M + 1: ti + 1]).prod(axis=0) - 1.0
        parts = [_z(sec_mom6.dropna())]
        if not macro.empty and mth in macro.index:
            parts.append(_z(macro.loc[mth].dropna()))
        sig_by_sector = pd.concat(parts, axis=1).mean(axis=1)   # mean of available z's
        if sig_by_sector.dropna().shape[0] < 4:
            continue

        # per-stock trailing 6m + forward 3m
        stock_mom6 = mat.iloc[ti] / mat.iloc[ti - MOM_M] - 1.0
        fwd3 = mat.iloc[ti + FWD_K] / mat.iloc[ti] - 1.0
        df = pd.DataFrame({"stock_mom6": stock_mom6, "fwd3": fwd3})
        df["sector"] = df.index.map(sec)
        df["sector_sig"] = df["sector"].map(sig_by_sector)
        df = df.dropna(subset=["stock_mom6", "fwd3", "sector_sig"])
        if len(df) < MIN_STOCKS_PER_MONTH:
            continue
        df["month"] = mth
        frames.append(df.reset_index().rename(columns={"index": "sid"}))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _tercile(s):
    try:
        return pd.qcut(s, 3, labels=["low", "mid", "high"], duplicates="drop")
    except ValueError:
        return pd.Series(index=s.index, dtype=object)


def _pooled(series):
    a = np.array([x for x in series if x is not None and not np.isnan(x)])
    if len(a) < 3:
        return np.nan, np.nan, len(a)
    se = a.std(ddof=1) / np.sqrt(len(a))
    return a.mean(), (a.mean() / se if se else np.nan), len(a)


def run():
    mat, sec = _panel()
    basket = _sector_basket_ret(mat, sec)
    macro = _macro()
    obs = _build_obs(mat, sec, basket, macro)
    if obs.empty:
        print("No usable observations.")
        return

    months = sorted(obs["month"].unique())
    print(f"Panel: {len(months)} months {months[0]}..{months[-1]} | "
          f"{len(obs):,} stock-month obs | macro available: {not macro.empty}")
    print(f"Horizon: forward {FWD_K}m | stock momentum & sector momentum: trailing {MOM_M}m\n")

    # ── Test 1: double-sort 3×3, averaged over months ──
    print("=" * 74)
    print("TEST 1 — double-sort: mean forward 3m stock return (%), averaged over months")
    print("rows = stock-momentum tercile · cols = sector-signal tercile")
    print("=" * 74)
    cells = {(r, c): [] for r in ["low", "mid", "high"] for c in ["low", "mid", "high"]}
    row_spread = {r: [] for r in ["low", "mid", "high"]}   # high − low sector-sig within row
    for mth, g in obs.groupby("month"):
        g = g.copy()
        g["mt"] = _tercile(g["stock_mom6"])
        g["st"] = _tercile(g["sector_sig"])
        if g["mt"].isna().all() or g["st"].isna().all():
            continue
        for r in ["low", "mid", "high"]:
            for c in ["low", "mid", "high"]:
                v = g[(g["mt"] == r) & (g["st"] == c)]["fwd3"]
                if len(v):
                    cells[(r, c)].append(v.mean())
            hi = g[(g["mt"] == r) & (g["st"] == "high")]["fwd3"]
            lo = g[(g["mt"] == r) & (g["st"] == "low")]["fwd3"]
            if len(hi) and len(lo):
                row_spread[r].append(hi.mean() - lo.mean())

    print(f"{'stock-mom':>10s} | {'sec-sig low':>11s} {'sec-sig mid':>11s} {'sec-sig high':>12s} | "
          f"{'high−low':>9s} (t)")
    print("-" * 74)
    for r in ["low", "mid", "high"]:
        row = []
        for c in ["low", "mid", "high"]:
            m, _, _ = _pooled(cells[(r, c)])
            row.append(f"{m*100:>10.2f}" if not np.isnan(m) else "       n/a")
        sm, st, sn = _pooled(row_spread[r])
        print(f"{r:>10s} | {row[0]:>11s} {row[1]:>11s} {row[2]:>12s} | "
              f"{sm*100:>+8.2f}% ({st:+.1f})")
    print("\n↑ 'high−low' = sector-signal spread WITHIN a stock-momentum row = the ORTHOGONAL")
    print("  value. If it's ~0 / insignificant, the sector tilt is redundant with stock momentum.")

    # ── Test 2: Fama-MacBeth ──
    print("\n" + "=" * 74)
    print("TEST 2 — Fama-MacBeth: per-month cross-sectional OLS of forward 3m return")
    print("=" * 74)
    b_sig_uni, b_mom_biv, b_sig_biv = [], [], []
    for mth, g in obs.groupby("month"):
        if len(g) < MIN_STOCKS_PER_MONTH:
            continue
        y = g["fwd3"].values
        zmom = _z(g["stock_mom6"]).values
        zsig = _z(g["sector_sig"]).values
        n = len(y)
        # univariate sector_sig
        Xu = np.column_stack([np.ones(n), zsig])
        b_sig_uni.append(np.linalg.lstsq(Xu, y, rcond=None)[0][1])
        # bivariate: control for stock momentum
        Xb = np.column_stack([np.ones(n), zmom, zsig])
        bb = np.linalg.lstsq(Xb, y, rcond=None)[0]
        b_mom_biv.append(bb[1]); b_sig_biv.append(bb[2])

    su_m, su_t, su_n = _pooled(b_sig_uni)
    bm_m, bm_t, _ = _pooled(b_mom_biv)
    bs_m, bs_t, _ = _pooled(b_sig_biv)
    print(f"  sector_sig  (UNIVARIATE)            slope {su_m*100:+.3f}%/σ  t {su_t:+.2f}  (n={su_n} months)")
    print(f"  stock_mom6  (with sector_sig)       slope {bm_m*100:+.3f}%/σ  t {bm_t:+.2f}")
    print(f"  sector_sig  (controlling stock_mom) slope {bs_m*100:+.3f}%/σ  t {bs_t:+.2f}")
    shrink = (1 - bs_m / su_m) * 100 if su_m else float("nan")
    print(f"\n  Sector-signal slope shrinks {shrink:.0f}% once stock momentum is controlled.")
    verdict = ("ADDITIVE — wire the tilt (survives the control)" if (abs(bs_t) >= 2 and bs_m > 0)
               else "REDUNDANT / weak — do NOT wire (collapses under stock momentum)")
    print(f"  VERDICT: {verdict}")
    print("\n  Slopes are %% forward-3m return per 1σ of the (cross-sectionally z-scored) signal.")


if __name__ == "__main__":
    run()
