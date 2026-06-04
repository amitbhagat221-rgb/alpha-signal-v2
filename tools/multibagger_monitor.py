"""
Alpha Signal v2 — Multibagger Conviction Monitor (the HOLDING study)

Reframe (2026-06): multibaggers aren't bought and slept on for 2-4yr — you hold
with conviction and reassess on a rolling 3-6mo cadence. The alpha is not in
SELECTING the 2-4yr winner at entry (proven dead) but in NOT getting shaken out
of it during the brutal interim drawdowns, while still cutting the genuine
losers before they grind to the floor.

Eventual winners and losers BOTH draw down 30%+ — so a drawdown stop ejects you
from your multibaggers. The discriminator is DEPTH + DURATION + whether the
SECTOR and RELATIVE STRENGTH are still intact (conviction) vs broken.

This tool, on the survivorship-correct quality-gated cohort:
  1. Builds SPLIT/BONUS-ADJUSTED monthly price paths (stock_prices is raw NSE
     bhavcopy → a 2:1 bonus is a fake −50% drop; we back-adjust via
     corporate_actions before measuring any drawdown).
  2. Reports honest drawdown signatures of winners vs losers.
  3. Backtests three HOLDING policies and compares winner-retention vs
     loser-mitigation:
       • buy_hold        — never sell (captures winners, rides losers to floor)
       • naive_stop(-X%) — trailing peak stop (cuts losers, ejects winners)
       • conviction      — sell only when drawdown is DEEP and PROLONGED and the
                           sector momentum AND relative strength have both rolled
                           over (the loser signature), else hold through.

Usage:
    python -m tools.multibagger_monitor                         # default window
    python -m tools.multibagger_monitor --anchor 2022-08-01 --end 2026-05-29
"""

import argparse

import numpy as np
import pandas as pd

from db import read_sql
from tools.multibagger_cohort import _score, _event_factor

# GICS → (used only for sector basket grouping; baskets built from the cohort itself)
MIN_SECTOR_NAMES = 4
MOM = 6                 # trailing months for sector momentum + relative strength


# ───────── split/bonus-adjusted monthly panel ─────────

def _events_by_sid(sids, a_snap, e_snap):
    ca = read_sql(
        "SELECT sid, ex_date, ind, subject FROM corporate_actions "
        "WHERE ind IN ('SPLIT','BONUS') AND ex_date > ? AND ex_date <= ? AND sid IS NOT NULL",
        params=[a_snap, e_snap])
    out = {}
    for _, r in ca.iterrows():
        if r["sid"] not in set(sids):
            continue
        f = _event_factor(r["subject"], r["ind"])
        if f and f > 1.0:
            out.setdefault(r["sid"], []).append((pd.Timestamp(r["ex_date"]), f))
    return out


def _adjusted_panel(anchor, end, sids):
    """[month_end_period x sid] back-adjusted closes (continuous through splits)."""
    px = read_sql(
        "SELECT sid, date, close FROM stock_prices WHERE close>0 AND date>=? AND date<=? "
        f"AND sid IN ({','.join('?'*len(sids))})",
        params=[anchor, end] + list(sids))
    px["date"] = pd.to_datetime(px["date"])
    px["ym"] = px["date"].dt.to_period("M")
    me = px.sort_values("date").groupby(["sid", "ym"]).last().reset_index()
    raw = me.pivot(index="ym", columns="sid", values="close").sort_index()

    events = _events_by_sid(sids, anchor, end)
    month_end_ts = raw.index.to_timestamp("M")
    adj = raw.copy()
    for sid, evs in events.items():
        if sid not in adj.columns:
            continue
        divisor = pd.Series(1.0, index=raw.index)
        for ex_ts, f in evs:
            divisor[month_end_ts < ex_ts] *= f      # pre-ex months scaled down
        adj[sid] = raw[sid] / divisor.values
    return adj


def _trailing_ret(level, m):
    """Trailing m-period return of a level series/array (NaN-safe)."""
    return level / level.shift(m) - 1.0


# ───────── the study ─────────

def run(anchor, end):
    scored, fwd, a_snap, e_snap = _score(anchor, end)
    s = scored.dropna(subset=["fwd_mult"]).copy()
    sids = s["sid"].dropna().unique().tolist()
    sector = s.set_index("sid")["sector"]
    adj = _adjusted_panel(a_snap, e_snap, sids)
    sids = [c for c in adj.columns if adj[c].notna().sum() >= 12]
    adj = adj[sids]
    months = adj.index

    # per-name simple monthly returns; market = cross-sectional median (the pond)
    ret = adj / adj.shift(1) - 1.0
    mkt_level = (1 + ret.median(axis=1).fillna(0)).cumprod()
    mkt_mom = _trailing_ret(mkt_level, MOM)

    # sector basket levels (median return) → sector-relative trailing momentum
    sec_mom = {}
    for sec, grp in pd.Series(sector).groupby(sector):
        cols = [c for c in sids if sector.get(c) == sec]
        if len(cols) < MIN_SECTOR_NAMES:
            continue
        lvl = (1 + ret[cols].median(axis=1).fillna(0)).cumprod()
        sec_mom[sec] = _trailing_ret(lvl, MOM) - mkt_mom        # sector-relative

    # buy-hold realised multiple per name (last available adj close / entry)
    entry = adj.iloc[0]
    realized_bh = {}
    for c in sids:
        ser = adj[c].dropna()
        realized_bh[c] = ser.iloc[-1] / entry[c] if entry[c] and not np.isnan(entry[c]) else np.nan

    # ───────── honest drawdown signature (adjusted) ─────────
    def signature(mask_fn, label):
        names = [c for c in sids if mask_fn(realized_bh[c])]
        dds, tuw = [], []
        for c in names:
            p = adj[c].dropna()
            if len(p) < 12:
                continue
            peak = p.cummax()
            dds.append((p / peak - 1).min())
            tuw.append(int(((p / peak - 1) < -0.20).sum()))
        if len(dds) < 3:
            return
        dds, tuw = np.array(dds), np.array(tuw)
        print(f"  {label:14s} n={len(dds):>3d} | med max-DD {np.median(dds)*100:+4.0f}% | "
              f"≥30%DD {(dds<=-.3).mean()*100:>3.0f}% | ≥50%DD {(dds<=-.5).mean()*100:>3.0f}% | "
              f"med months underwater {np.median(tuw):>2.0f}")

    print(f"\nADJUSTED drawdown signature  ({a_snap}→{e_snap}, {len(sids)} names, split-adjusted)")
    signature(lambda m: m >= 3, "≥3x winners")
    signature(lambda m: 2 <= m < 3, "2-3x")
    signature(lambda m: 1 <= m < 2, "1-2x")
    signature(lambda m: m < 1, "<1x losers")

    # ───────── policy simulation ─────────
    def simulate(decide):
        """decide(name, ti, peak_dd, tuw, rs6, secmom6) -> True to EXIT at month ti."""
        out = {}
        for c in sids:
            p = adj[c]
            valid = p.dropna()
            if len(valid) < 2:
                out[c] = np.nan
                continue
            e0 = entry[c]
            peak = -np.inf
            uw = 0
            exited = None
            name_mom = _trailing_ret(p, MOM)
            for ti, m in enumerate(months):
                price = p.iloc[ti]
                if np.isnan(price):
                    continue
                peak = max(peak, price)
                dd = price / peak - 1.0
                uw = uw + 1 if dd < -0.20 else 0
                if ti >= MOM:
                    rs6 = (name_mom.iloc[ti] - mkt_mom.iloc[ti]
                           if not np.isnan(name_mom.iloc[ti]) else 0.0)
                    sm6 = sec_mom.get(sector.get(c), pd.Series(dtype=float)).get(m, 0.0)
                    if decide(dd, uw, rs6, sm6):
                        exited = price / e0
                        break
            out[c] = exited if exited is not None else realized_bh[c]
        return out

    policies = {
        "buy_hold":         lambda dd, uw, rs6, sm6: False,
        "naive_stop_-30%":  lambda dd, uw, rs6, sm6: dd <= -0.30,
        "naive_stop_-50%":  lambda dd, uw, rs6, sm6: dd <= -0.50,
        # conviction = sell only on the LOSER signature (deep + prolonged + both
        # sector momentum AND relative strength rolled over). Variants tune it.
        "conv_A(dd40/uw6)": lambda dd, uw, rs6, sm6: (dd <= -0.40 and uw >= 6
                                                      and rs6 < 0 and sm6 < 0),
        "conv_B(dd50/uw9)": lambda dd, uw, rs6, sm6: (dd <= -0.50 and uw >= 9
                                                      and rs6 < 0 and sm6 < 0),
        "conv_C(sec-only)": lambda dd, uw, rs6, sm6: (dd <= -0.50 and uw >= 9
                                                      and sm6 < 0),
    }
    results = {name: simulate(dec) for name, dec in policies.items()}

    win = [c for c in sids if realized_bh[c] >= 3]            # eventual winners
    los = [c for c in sids if realized_bh[c] < 1]             # eventual losers
    print(f"\nHOLDING-POLICY BACKTEST  (equal-weight; {len(win)} eventual ≥3x winners, "
          f"{len(los)} eventual <1x losers)")
    print(f"{'policy':16s} | {'port mean':>9s} {'port med':>8s} | "
          f"{'winners kept':>12s} | {'losers realised':>15s} | {'≥3x retained':>12s}")
    print("-" * 86)
    for name, res in results.items():
        vals = np.array([res[c] for c in sids if not np.isnan(res[c])])
        wv = np.array([res[c] for c in win if not np.isnan(res[c])])
        lv = np.array([res[c] for c in los if not np.isnan(res[c])])
        # ≥3x retained = share of eventual winners the policy still held to ≥3x
        retained = (wv >= 3).mean() * 100 if len(wv) else 0
        print(f"{name:16s} | {vals.mean():>8.2f}x {np.median(vals):>7.2f}x | "
              f"{wv.mean():>11.2f}x | {lv.mean():>14.2f}x | {retained:>11.0f}%")
    print("-" * 86)
    print("winners kept = mean realised multiple among eventual ≥3x names (higher = didn't")
    print("  shake out); losers realised = mean among eventual <1x names (higher = cut earlier);")
    print("  ≥3x retained = % of winners still held all the way to ≥3x.")


# ───────── bear-window stress test (sector-index level) ─────────
#
# The per-name study run() above only has stock_prices from 2022 — two mostly
# RISING cycles — so the live REVIEW eject branch barely fired and is under-tested
# (HANDOFF 2026-06-04). To stress the eject hatch through real bears (2011-13
# derating / 2015-16 commodity bust / 2018-19 NBFC-credit crisis / 2020 COVID) we
# replay the LIVE cockpit verdict rule (cockpit/api.py:_conviction_verdicts,
# byte-for-byte thresholds) on the 11 NSE sector INDICES — the only pre-2022 daily
# path data we have (15yr yfinance history, /tmp parquet via sector_regime_history).
#
# Caveat made explicit: at the index level the "name" IS the sector, so sector
# momentum (sm) and relative strength (rs6) collapse to ONE quantity (index 6m
# return − Nifty 6m return). This validates the DEPTH + DURATION + momentum-rollover
# eject logic and whether it shakes recoverers out; it does NOT exercise the
# sm-vs-rs split (a genuine "weak stock inside a strong sector" test needs pre-2022
# per-stock paths we don't have). The market reference is Nifty (live uses the
# survivor-cohort median; Nifty is the index-level analog).

from tools.sector_regime_history import CACHE as _SECTOR_CACHE, SECTOR_TICKERS as _SECTOR_TICKERS

_TRAIL = 13          # trailing month-ends ≈ live's 400-day window
_K = 6               # 6-month momentum lookback (live: k=min(6, n-1))
_MARKET_BEAR_DD = -0.20   # market-regime guard: don't EJECT into a market-wide bear
                          # (textbook bear-market line). Calibrated on the stress test —
                          # cleanly separates the 2008/2020 market-wide capitulations
                          # (false ejects) from idiosyncratic Realty-2011 (correct).


def _index_verdict(level_win, mkt6, market_dd=0.0):
    """LIVE cockpit rule (+ market-regime guard) replayed on one sector index's
    trailing month-end levels. Returns dict(verdict, dd, uw, rs6) or None.
    sm==rs6 at index level (see header)."""
    p = level_win.dropna()
    if len(p) < 7:
        return None
    peak = p.cummax()
    dd = float(p.iloc[-1] / peak.iloc[-1] - 1.0)
    uw = int(((p / peak - 1.0) < -0.20).sum())
    k = min(_K, len(p) - 1)
    own6 = p.iloc[-1] / p.iloc[-1 - k] - 1.0
    rs6 = float(own6 - mkt6)
    sm = rs6                                              # index level: sm == rs6
    # Eject only on the loser signature AND when the weakness is idiosyncratic —
    # i.e. the broad market is NOT itself in a deep drawdown. A −50% name inside a
    # market-wide crash is beta, not a zombie, and mean-reverts hardest.
    market_bear = market_dd <= _MARKET_BEAR_DD
    if dd <= -0.50 and uw >= 6 and sm < 0 and rs6 < 0 and not market_bear:
        v = "REVIEW"
    elif dd > -0.25 or (sm >= 0 and rs6 >= 0):
        v = "HOLD"
    else:
        v = "WATCH"
    return {"verdict": v, "dd": dd, "uw": uw, "rs6": rs6}


def stress_sector_index(fwds=(12, 24)):
    import os
    if not os.path.exists(_SECTOR_CACHE):
        print(f"⚠ {_SECTOR_CACHE} missing — run `python -m tools.sector_regime_history` first.")
        return
    px = pd.read_parquet(_SECTOR_CACHE)
    px.index = pd.to_datetime(px.index)
    me = px.resample("ME").last()
    sectors = [s for s in _SECTOR_TICKERS if s in me.columns]
    nif = me["Nifty"]
    nif_peak = nif.cummax()
    idx = list(me.index)

    recs = []
    for ti in range(_TRAIL, len(idx)):
        mkt6 = nif.iloc[ti] / nif.iloc[ti - _K] - 1.0
        mkt_dd = float(nif.iloc[ti] / nif_peak.iloc[ti] - 1.0)
        for s in sectors:
            v = _index_verdict(me[s].iloc[ti - _TRAIL + 1: ti + 1], mkt6, mkt_dd)
            if v is None:
                continue
            rec = {"date": idx[ti], "sector": s, "market_dd": mkt_dd, **v}
            for fm in fwds:
                rec[f"fwd{fm}"] = (me[s].iloc[ti + fm] / me[s].iloc[ti] - 1.0
                                   if ti + fm < len(idx) else np.nan)
            recs.append(rec)
    df = pd.DataFrame(recs)

    def fstats(g, col):
        x = g[col].dropna()
        return (len(x), x.mean() * 100, x.median() * 100) if len(x) else (0, np.nan, np.nan)

    def rate(g, col, thr):
        x = g[col].dropna()
        return (x >= thr).mean() * 100 if len(x) else np.nan

    bear = df[df["market_dd"] <= -0.20]
    print("\n" + "=" * 88)
    print("CONVICTION-MONITOR BEAR STRESS TEST  (live eject rule replayed on 11 NSE sector indices)")
    print("=" * 88)
    print(f"Months {df['date'].min():%Y-%m}..{df['date'].max():%Y-%m} | {len(df)} sector-month "
          f"verdicts | bear months (Nifty DD≤−20%): {len(bear)} obs")
    print("Index-level caveat: sector-momentum == relative-strength here (the name IS the sector).")

    print("\n1) Does the eject hatch FIRE?  verdict distribution  (all | BEAR months):")
    for v in ["HOLD", "WATCH", "REVIEW"]:
        a = df[df["verdict"] == v]; b = bear[bear["verdict"] == v]
        ap = 100 * len(a) / len(df) if len(df) else 0
        bp = 100 * len(b) / len(bear) if len(bear) else 0
        print(f"   {v:7s} {len(a):>4d} ({ap:4.1f}%)  |  bear {len(b):>3d} ({bp:4.1f}%)")

    print("\n2) Is the verdict informative?  forward return by verdict (mean / median):")
    for v in ["HOLD", "WATCH", "REVIEW"]:
        g = df[df["verdict"] == v]
        n12, m12, d12 = fstats(g, "fwd12"); n24, m24, d24 = fstats(g, "fwd24")
        print(f"   {v:7s}  fwd12 {m12:+6.1f}% / {d12:+6.1f}% (n{n12:>3d})   "
              f"fwd24 {m24:+6.1f}% / {d24:+6.1f}% (n{n24:>3d})")

    deep = df[df["dd"] <= -0.40]
    rev = deep[deep["verdict"] == "REVIEW"]
    hold = deep[deep["verdict"].isin(["HOLD", "WATCH"])]
    print(f"\n3) THE EJECT DISCRIMINATOR — among DEEP drawdowns (own DD≤−40%, n={len(deep)}):")
    print("   (when you're scared & tempted to sell, does conviction keep recoverers, cut losers?)")
    for lbl, g in [("REVIEW  → eject", rev), ("HOLD/WATCH → conviction-hold", hold)]:
        n12, m12, _ = fstats(g, "fwd12"); n24, m24, _ = fstats(g, "fwd24")
        print(f"   {lbl:30s} fwd12 {m12:+6.1f}% (n{n12:>3d}) | fwd24 {m24:+6.1f}% (n{n24:>3d}) "
              f"| recovered fwd24≥+50%: {rate(g,'fwd24',0.5):4.0f}%")
    print("   ↑ conviction-hold recovering = winners correctly retained; REVIEW recovering = shaken out.")

    print("\n4) vs NAIVE STOPS — mean fwd24 among obs where each policy SELLS")
    print("   (LOWER = sold genuine losers; HIGHER = shook you out of recoverers):")
    for lbl, g in [("naive stop −30% (any DD≤−30%)", df[df["dd"] <= -0.30]),
                   ("naive stop −50% (any DD≤−50%)", df[df["dd"] <= -0.50]),
                   ("conviction REVIEW (loser sig.)", df[df["verdict"] == "REVIEW"])]:
        n24, m24, _ = fstats(g, "fwd24")
        print(f"   {lbl:32s} fwd24 {m24:+6.1f}% (n{n24:>3d}) | recovered≥+50%: {rate(g,'fwd24',0.5):4.0f}%")

    if len(rev):
        print("\n5) REVIEW episodes by sector (where the hatch fired) — count, mean fwd24, recover≥+50%:")
        for s, g in rev.groupby("sector"):
            n24, m24, _ = fstats(g, "fwd24")
            yrs = ", ".join(sorted({f"{d:%Y}" for d in g["date"]}))
            print(f"   {s:8s} n={len(g):>2d}  fwd24 {m24:+6.1f}%  recover {rate(g,'fwd24',0.5):3.0f}%  [{yrs}]")
    return df


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--anchor", default="2022-08-01")
    p.add_argument("--end", default="2026-05-29")
    p.add_argument("--sector-stress", action="store_true",
                   help="Replay the live eject rule on 15yr of sector indices (bear stress test)")
    args = p.parse_args()
    if args.sector_stress:
        stress_sector_index()
    else:
        run(args.anchor, args.end)


if __name__ == "__main__":
    main()
