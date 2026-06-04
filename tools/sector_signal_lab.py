"""
Alpha Signal v2 — Sector Signal Lab (at-entry sector-outlook validation)

Question: is there an AT-ENTRY, mechanical, sector-level signal that predicts
the forward sector return — usable to tilt daily picks (and, separately, the
multibagger screen) toward tailwind sectors?

This is the high-power complement to tools/multibagger_cohort.py: instead of 7
overlapping multi-year windows, it uses ~40 MONTHLY cross-sections of the 11
GICS sectors → far more independent observations.

Panel:
  - Sector basket monthly returns from `stock_prices` (2022-07+, 2447 sids).
    Basket return = MEDIAN per-stock simple return (robust to penny blow-ups),
    over stocks with a valid price at both endpoints.
  - At each month-end t, score each sector by a candidate AT-ENTRY signal,
    then measure forward sector return over [t, t+k].

Signals tested:
  (1) Trailing time-series momentum   — sector return over [t-m, t], m∈{1,3,6,12}
      → the daily-model-relevant lead (global evidence strongest at 1-12mo).
  (2) macro_score from macro_sector_signals_pit (2023-06+) — the EXISTING
      leading/lagging-macro→sector engine, never before validated.

Metric (per snapshot, cross-sectional across 11 sectors):
  - Spearman rho(signal, fwd_return); pooled = mean rho, t = mean/se, %positive.
  - Long-short: top-3 minus bottom-3 sectors by signal → mean forward spread, t.

Usage:
    python -m tools.sector_signal_lab            # full matrix
"""

import numpy as np
import pandas as pd

from db import read_sql

FWD_HORIZONS = [1, 3, 6]          # forward months to test
MOM_LOOKBACKS = [1, 3, 6, 12]     # trailing-momentum lookbacks (months)
MIN_STOCKS_PER_SECTOR = 5         # need a real basket


# ───────── build month-end sector-basket return panel ─────────

def _load_panel():
    """Return (me_close, sector) where me_close is a [month_end_date x sid] price
    matrix (month-end closes) and sector maps sid→GICS sector."""
    px = read_sql("SELECT sid, date, close FROM stock_prices WHERE close > 0")
    px["date"] = pd.to_datetime(px["date"])
    px["ym"] = px["date"].dt.to_period("M")
    # month-end = last trading row per (sid, month)
    px = px.sort_values("date")
    me = px.groupby(["sid", "ym"], as_index=False).last()
    mat = me.pivot(index="ym", columns="sid", values="close").sort_index()
    sectors = read_sql("SELECT sid, sector FROM stocks").dropna(subset=["sector"])
    sec = sectors.set_index("sid")["sector"]
    return mat, sec


def _basket_returns(mat, sec):
    """Monthly sector-basket return matrix [month x sector] (median stock return),
    plus the month-end periods index."""
    months = mat.index
    sectors = sorted(sec.unique())
    # per-stock month-over-month simple return
    ret = mat / mat.shift(1) - 1.0
    out = pd.DataFrame(index=months, columns=sectors, dtype=float)
    for s in sectors:
        cols = [c for c in mat.columns if sec.get(c) == s]
        sub = ret[cols]
        # require >=MIN stocks reporting that month
        med = sub.median(axis=1, skipna=True)
        cnt = sub.notna().sum(axis=1)
        med[cnt < MIN_STOCKS_PER_SECTOR] = np.nan
        out[s] = med
    return out


def _fwd_return(basket_ret, t_idx, k):
    """Compounded forward sector return over months (t, t+k] from monthly basket
    returns. basket_ret rows are monthly returns indexed by month-end period."""
    months = basket_ret.index
    if t_idx + k >= len(months):
        return None
    window = basket_ret.iloc[t_idx + 1: t_idx + 1 + k]   # returns for t+1..t+k
    return (1.0 + window).prod(axis=0) - 1.0             # Series over sectors


def _trailing_mom(basket_ret, t_idx, m):
    """Trailing m-month compounded sector return ending at month t (the signal)."""
    if t_idx - m + 1 < 0:
        return None
    window = basket_ret.iloc[t_idx - m + 1: t_idx + 1]
    return (1.0 + window).prod(axis=0) - 1.0


# ───────── cross-sectional evaluation ─────────

def _spearman(a, b):
    """Cross-sectional Spearman rho between two aligned Series (drop NaN)."""
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < 4:
        return np.nan
    return df.iloc[:, 0].rank().corr(df.iloc[:, 1].rank())


def _pool(rhos):
    r = np.array([x for x in rhos if x is not None and not np.isnan(x)])
    if len(r) < 3:
        return dict(n=len(r), mean=np.nan, t=np.nan, pos=np.nan)
    se = r.std(ddof=1) / np.sqrt(len(r))
    return dict(n=len(r), mean=r.mean(), t=(r.mean() / se if se else np.nan),
                pos=(r > 0).mean())


def _long_short(signal, fwd, n=3):
    """Top-n minus bottom-n sector forward-return spread for one month."""
    df = pd.concat([signal.rename("sig"), fwd.rename("fwd")], axis=1).dropna()
    if len(df) < 2 * n:
        return np.nan
    df = df.sort_values("sig", ascending=False)
    return df.head(n)["fwd"].mean() - df.tail(n)["fwd"].mean()


def _pool_ls(spreads):
    s = np.array([x for x in spreads if x is not None and not np.isnan(x)])
    if len(s) < 3:
        return dict(n=len(s), mean=np.nan, t=np.nan)
    se = s.std(ddof=1) / np.sqrt(len(s))
    return dict(n=len(s), mean=s.mean(), t=(s.mean() / se if se else np.nan))


# ───────── runners ─────────

def run():
    mat, sec = _load_panel()
    basket = _basket_returns(mat, sec)
    months = list(basket.index)
    print(f"Panel: {len(months)} month-ends {months[0]}..{months[-1]} × "
          f"{basket.shape[1]} sectors (median-stock basket returns)\n")

    # ── (1) trailing time-series momentum ──
    print("=" * 78)
    print("SIGNAL 1 — trailing sector momentum (does past sector return predict future?)")
    print("=" * 78)
    print(f"{'lookback':>9s} | " + " | ".join(f"fwd {k}m: rho  (t)  %+ " for k in FWD_HORIZONS))
    print("-" * 78)
    for m in MOM_LOOKBACKS:
        cells = []
        for k in FWD_HORIZONS:
            rhos = []
            for ti in range(len(months)):
                sig = _trailing_mom(basket, ti, m)
                fwd = _fwd_return(basket, ti, k)
                if sig is None or fwd is None:
                    continue
                rhos.append(_spearman(sig, fwd))
            p = _pool(rhos)
            cells.append(f"{p['mean']:+.2f} ({p['t']:+.1f}) {p['pos']*100:>3.0f}% n{p['n']:>2d}")
        print(f"{m:>7d}m  | " + " | ".join(cells))

    # ── momentum long-short (best lookback) ──
    print("\nLong-short (top-3 − bottom-3 sectors by trailing momentum), forward spread:")
    for m in MOM_LOOKBACKS:
        for k in FWD_HORIZONS:
            spreads = []
            for ti in range(len(months)):
                sig = _trailing_mom(basket, ti, m)
                fwd = _fwd_return(basket, ti, k)
                if sig is None or fwd is None:
                    continue
                spreads.append(_long_short(sig, fwd))
            ls = _pool_ls(spreads)
            ann = (ls['mean'] * 12 / k) if not np.isnan(ls['mean']) else np.nan
            print(f"  mom {m:>2d}m → fwd {k}m: mean spread {ls['mean']*100:+5.2f}%  "
                  f"(~{ann*100:+5.1f}%/yr, t {ls['t']:+.1f}, n{ls['n']})")

    # ── (2) macro_score engine (PIT) ──
    print("\n" + "=" * 78)
    print("SIGNAL 2 — macro_sector_signals_pit.macro_score (the existing CFA-macro engine)")
    print("=" * 78)
    ms = read_sql("SELECT sector, snapshot_date, macro_score FROM macro_sector_signals_pit "
                  "WHERE macro_score IS NOT NULL")
    ms["snap"] = pd.to_datetime(ms["snapshot_date"]).dt.to_period("M")
    macro = ms.pivot_table(index="snap", columns="sector", values="macro_score")
    # align macro snapshot month → our basket month index
    print(f"macro_score panel: {macro.shape[0]} monthly snapshots "
          f"{macro.index.min()}..{macro.index.max()}\n")
    print(f"{'':>9s} | " + " | ".join(f"fwd {k}m: rho  (t)  %+ " for k in FWD_HORIZONS))
    print("-" * 78)
    cells = []
    for k in FWD_HORIZONS:
        rhos = []
        for ti, mth in enumerate(months):
            if mth not in macro.index:
                continue
            sig = macro.loc[mth]
            fwd = _fwd_return(basket, ti, k)
            if fwd is None:
                continue
            rhos.append(_spearman(sig, fwd))
        p = _pool(rhos)
        cells.append(f"{p['mean']:+.2f} ({p['t']:+.1f}) {p['pos']*100:>3.0f}% n{p['n']:>2d}")
    print(f"macro_sc  | " + " | ".join(cells))

    print("\nLong-short (top-3 − bottom-3 sectors by macro_score), forward spread:")
    for k in FWD_HORIZONS:
        spreads = []
        for ti, mth in enumerate(months):
            if mth not in macro.index:
                continue
            fwd = _fwd_return(basket, ti, k)
            if fwd is None:
                continue
            spreads.append(_long_short(macro.loc[mth], fwd))
        ls = _pool_ls(spreads)
        ann = (ls['mean'] * 12 / k) if not np.isnan(ls['mean']) else np.nan
        print(f"  macro → fwd {k}m: mean spread {ls['mean']*100:+5.2f}%  "
              f"(~{ann*100:+5.1f}%/yr, t {ls['t']:+.1f}, n{ls['n']})")

    # ── (3) ensemble: is macro orthogonal to momentum? does combining help? ──
    print("\n" + "=" * 78)
    print("SIGNAL 3 — ensemble: zscore(mom 6m) + zscore(macro_score), apples-to-apples")
    print("=" * 78)

    def _z(s):
        s = s.astype(float)
        sd = s.std(ddof=0)
        return (s - s.mean()) / sd if sd else s * 0.0

    for k in [3, 6]:
        rho_mom, rho_mac, rho_ens, sig_corrs = [], [], [], []
        for ti, mth in enumerate(months):
            if mth not in macro.index:
                continue
            mom = _trailing_mom(basket, ti, 6)
            fwd = _fwd_return(basket, ti, k)
            if mom is None or fwd is None:
                continue
            mac = macro.loc[mth]
            common = mom.dropna().index.intersection(mac.dropna().index)
            if len(common) < 6:
                continue
            zmom, zmac = _z(mom[common]), _z(mac[common])
            ens = zmom + zmac
            rho_mom.append(_spearman(mom[common], fwd[common]))
            rho_mac.append(_spearman(mac[common], fwd[common]))
            rho_ens.append(_spearman(ens, fwd[common]))
            sig_corrs.append(zmom.rank().corr(zmac.rank()))
        pm, pa, pe = _pool(rho_mom), _pool(rho_mac), _pool(rho_ens)
        sc = np.nanmean(sig_corrs)
        print(f"  fwd {k}m (same {pm['n']} months):  "
              f"mom6 rho {pm['mean']:+.2f}(t{pm['t']:+.1f}) | "
              f"macro rho {pa['mean']:+.2f}(t{pa['t']:+.1f}) | "
              f"ENSEMBLE rho {pe['mean']:+.2f}(t{pe['t']:+.1f})  "
              f"| corr(mom,macro)={sc:+.2f}")

    print("\nrho = cross-sectional Spearman across 11 sectors, pooled mean over months "
          "(t = mean/se, %+ = share of months rho>0).")


if __name__ == "__main__":
    run()
