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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--anchor", default="2022-08-01")
    p.add_argument("--end", default="2026-05-29")
    args = p.parse_args()
    run(args.anchor, args.end)


if __name__ == "__main__":
    main()
