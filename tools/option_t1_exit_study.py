"""
Alpha Signal v2 — study: a decision at the close of the day BEFORE expiry (T-1) for the live strangle.

Amit 2026-11-03: "had the same decision model been run around 3 PM yesterday we would have killed the trade
yesterday itself" — on 2026-11-02 the 23500 CE sat 59 pts (0.25 %) from the close; the next morning gapped +0.6 %.

Every expiry 2019-26 (NIFTY) / 2024-26 (SENSEX): the live rule's trade opened at the T-2 settle
(option_book.open_trade: 0.05-delta strikes, fno_bhav settle), then at the T-1 settle one of these decisions:
  hold            — to settlement (the baseline, what the book does)
  dist d          — buy back a short leg when the index is within d % of its strike at the T-1 close
  prem k          — buy back a short leg when its T-1 settle is at least k x its entry price
  both-dist d     — buy back BOTH legs when either is within d %
  t1-close        — always buy back both at T-1 (a one-day trade)
Buy-backs pay the T-1 settle plus option_book.leg_cost (brokerage, charges, 1 % slippage). Held legs settle at
intrinsic on the expiry-day index. Rupees at TODAY's size: points per unit x 16 lots x the lot size of the day, so the
numbers read as "what this week would have been" (NIFTY 65 → 1,040 units; SENSEX 20 → 320). READ-ONLY. Decision taken from settle (15:30), the closest
free proxy for a 15:00 look; the 1-minute archive can refine it later.

Usage: python -m tools.option_t1_exit_study [--underlying NIFTY] [--out docs/studies/option-t1-exit-2026-11.md]
"""
from __future__ import annotations

import argparse
from datetime import date

import numpy as np
import pandas as pd

import option_book as ob
from db import read_sql

LOTS = 16                          # this week's size: rupee columns = points per unit x 16 lots x the lot size then
DIST = (0.25, 0.5, 0.75, 1.0, 1.5)
PREM = (2.0, 3.0, 5.0)


def sessions(u):
    return sorted(read_sql("SELECT DISTINCT trade_date FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO'",
                           params=[u]).trade_date)


def expiries(u):
    return sorted(read_sql("SELECT DISTINCT expiry_date FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                           "AND expiry_date <= (SELECT MAX(trade_date) FROM fno_bhav WHERE symbol = ?)", params=[u, u]).expiry_date)


def t1_prices(u, t1, expiry, kc, kp):
    df = read_sql("SELECT option_type, strike, settle, underlying_price FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                  "AND trade_date = ? AND expiry_date = ? AND strike IN (?, ?)", params=[u, t1, expiry, kc, kp])
    if df.empty:
        return None
    px = {(("C" if o == "CE" else "P"), float(k)): float(s) for o, k, s in zip(df.option_type, df.strike, df.settle)}
    if ("C", kc) not in px or ("P", kp) not in px:
        return None
    return px[("C", kc)], px[("P", kp)], float(df.underlying_price.iloc[0])


def settle_index(u, expiry):
    s = read_sql("SELECT MAX(underlying_price) AS s FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' AND trade_date = ?",
                 params=[u, expiry]).s.iloc[0]
    return None if s is None or pd.isna(s) else float(s)


def trades(u):
    hol = ob.holidays()
    sess = set(sessions(u))
    out = []
    for e in expiries(u):
        if e not in sess:
            continue
        t2, t1 = ob.entry_day(e, hol, 2), ob.entry_day(e, hol, 1)
        if t2 not in sess or t1 not in sess:
            continue
        try:
            tr = ob.open_trade(u, t2, e)
        except Exception:                       # noqa: BLE001 — a chain the IV solver cannot price
            tr = None
        if not tr:
            continue
        p = t1_prices(u, t1, e, tr["short_call"], tr["short_put"])
        S = settle_index(u, e)
        if p is None or S is None:
            continue
        c1, p1, s1 = p
        out.append({"underlying": u, "expiry": e, "entry": t2, "t1": t1, "F": tr["forward"], "lot": tr["lot"],
                    "kc": tr["short_call"], "kp": tr["short_put"], "ce": tr["call_entry"], "pe": tr["put_entry"],
                    "entry_cost": tr["entry_cost_pts"], "c1": c1, "p1": p1, "s1": s1, "S": S,
                    "dist_c": (tr["short_call"] - s1) / s1 * 100, "dist_p": (s1 - tr["short_put"]) / s1 * 100})
    return pd.DataFrame(out)


def pnl(r, rule, x=None):
    """Points per unit for one trade under a rule. Entry credit less entry costs, then each leg: bought back at T-1
    (settle + exit cost) or settled at intrinsic."""
    credit = r.ce + r.pe - r.entry_cost
    close_c = close_p = False
    if rule == "dist":
        close_c, close_p = r.dist_c <= x, r.dist_p <= x
    elif rule == "prem":
        close_c, close_p = r.c1 >= x * r.ce, r.p1 >= x * r.pe
    elif rule == "both-dist":
        close_c = close_p = (r.dist_c <= x or r.dist_p <= x)
    elif rule == "t1-close":
        close_c = close_p = True
    cost_c = (r.c1 + ob.leg_cost(r.c1, "buy", r.lot, ob.SLIP, r.t1)) if close_c else ob.intrinsic("C", r.kc, r.S)
    cost_p = (r.p1 + ob.leg_cost(r.p1, "buy", r.lot, ob.SLIP, r.t1)) if close_p else ob.intrinsic("P", r.kp, r.S)
    fired = close_c or close_p
    whip = fired and (ob.intrinsic("C", r.kc, r.S) == 0 if close_c else True) and (ob.intrinsic("P", r.kp, r.S) == 0 if close_p else True)
    return credit - cost_c - cost_p, fired, whip


RULES = [("hold", None)] + [("dist", d) for d in DIST] + [("prem", k) for k in PREM] + [("both-dist", d) for d in (0.25, 0.5, 1.0)] + [("t1-close", None)]


def evaluate(df):
    rows = []
    for rule, x in RULES:
        res = [pnl(r, rule, x) for r in df.itertuples()]
        p = np.array([a * r.lot * LOTS for (a, _, _), r in zip(res, df.itertuples())])
        fired = np.array([f for _, f, _ in res]); whip = np.array([w for _, _, w in res])
        rows.append({"rule": rule + (f" {x:g}" if x is not None else ""), "n": len(p), "fired %": fired.mean() * 100,
                     "whipsaw % of fired": (whip[fired].mean() * 100) if fired.any() else 0.0,
                     "mean ₹": p.mean(), "median ₹": np.median(p), "total ₹ L": p.sum() / 1e5,
                     "P(loss>50K)": (p < -50_000).mean() * 100, "P(loss>1L)": (p < -100_000).mean() * 100,
                     "5th pct ₹": np.percentile(p, 5), "worst ₹": p.min(),
                     "sharpe (weekly)": p.mean() / p.std() * np.sqrt(52) if p.std() else 0.0})
    return pd.DataFrame(rows).set_index("rule")


def fmt(t):
    with pd.option_context("display.float_format", lambda v: f"{v:,.0f}", "display.width", 200):
        return t.round({"fired %": 0, "whipsaw % of fired": 0, "P(loss>50K)": 1, "P(loss>1L)": 1, "total ₹ L": 1,
                        "sharpe (weekly)": 2}).to_string()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--underlying", default="NIFTY")
    ap.add_argument("--since", default="2019-01-01")
    ap.add_argument("--out")
    a = ap.parse_args()
    df = trades(a.underlying)
    df = df[df.expiry >= a.since]
    parts = []
    for label, sub in (("all", df), ("2019-23 (selection)", df[df.expiry < "2024-01-01"]), ("2024-26 (unseen)", df[df.expiry >= "2024-01-01"]),
                       ("T-1 close within 0.5 % of a strike (the 2026-11-02 situation)", df[(df.dist_c <= 0.5) | (df.dist_p <= 0.5)])):
        if len(sub) < 5:
            continue
        parts.append(f"\n=== {a.underlying} {label}: n={len(sub)} expiries ===\n" + fmt(evaluate(sub)))
    text = "\n".join(parts)
    print(text)
    if a.out:
        with open(a.out, "a") as f:
            f.write(f"\n```\n{text}\n```\n")


if __name__ == "__main__":
    main()
