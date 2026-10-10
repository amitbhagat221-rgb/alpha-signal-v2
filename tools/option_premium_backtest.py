"""
Alpha Signal v2 — feasibility backtest: selling NIFTY weekly option premium.

Question (Amit 2026-10-09): can a rule that sells index option premium every week
(or every day) earn a small, steady return after costs, and how bad are its bad days?
Answered on the EOD option chain we already hold (`fno_bhav`, NIFTY, from 2024-07-15)
before anything is built for execution.

Method — READ-ONLY, writes nothing:
  • Entry at a day's `settle` (= the close for a traded strike), short strikes picked
    by Black-76 forward delta on that day's own prices (sources/fno_iv inversion,
    forward from put-call parity). Only strikes that traded that day (volume > 0).
  • Structures: short strangle (naked), iron condor (same shorts + long wings
    WING_PCT of the forward further out).
  • Holds: `exp{k}` = enter k trading days before the weekly expiry, hold to expiry
    (one trade per expiry); `daily` = every day sell the nearest expiry, buy back at
    the next day's settle (one trade per day).
  • Expiry settles at intrinsic value on `underlying_price` (on expiry day fno_bhav's
    `settle` column holds the index settlement, not the option price).
  • Costs per leg per side: brokerage + GST, exchange charge + GST, STT on the sell
    side, stamp duty on the buy side, and slippage max(tick, SLIP × price) because the
    chain has no bid/ask. STT on exercise for long wings that finish in the money.
  • Return = net P&L / margin per unit. Margin is an ASSUMPTION (no SPAN file):
    strangle MARGIN_STRANGLE_PCT of the forward, iron condor = the wider wing width.

The grid below was fixed on 2026-10-09 BEFORE any result was looked at. Every cell is
reported; do not tune it against the output (ADR 0043).

Limits this cannot see: intraday moves (a stop-loss could not be modelled; positions
are held through the session), bid/ask (slippage is assumed), the 2020 crash and the
June-2024 election day (the chain starts 2024-07-15), SENSEX options (BSE).

Usage:
  python -m tools.option_premium_backtest                 # the full pre-registered grid
  python -m tools.option_premium_backtest --stt 0.0015    # STT sensitivity
  python -m tools.option_premium_backtest --slip 0.03     # slippage sensitivity
  python -m tools.option_premium_backtest --trades out.csv
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from db import read_sql
import option_book as ob
from option_book import (LOT_SIZES, MARGIN_STRANGLE_PCT, SLIP, STT_EXERCISE, STT_SELL, leg_cost,
                         slice_deltas)
from option_book import years as _years

UNDERLYING = "NIFTY"
REGIME_START = "2024-11-20"     # SEBI: one weekly expiry per exchange, bigger contracts, upfront premium

# ── pre-registered grid (2026-10-09) ──
DELTAS = (0.05, 0.10, 0.15, 0.20)
HOLDS = ("exp1", "exp2", "exp3", "daily")
STRUCTURES = ("strangle", "condor")
WING_PCT = 0.01                 # condor long legs 1% of the forward beyond each short strike
# strike picker, costs, lot sizes: option_book (shared with the forward paper record, plan 0022)


def lot_size(d):
    return ob.lot_size(UNDERLYING, d)


VIX_BUCKETS = ((0, 12), (12, 15), (15, 20), (20, 999))


# ── pre-registered vetoes (2026-10-09; study §Pre-registration) ──
VIX_VETO = 25.0                 # config.VIX_REGIMES CAUTION boundary
BUDGET_DAYS = ("2019-02-01", "2019-07-05", "2020-02-01", "2021-02-01", "2022-02-01", "2023-02-01",
               "2024-02-01", "2024-07-23", "2025-02-01", "2026-02-01")
ELECTION_RESULT_DAYS = ("2019-05-23", "2024-06-04")
# RBI MPC decision days incl. off-cycle (2020-03-27, 2020-05-22, 2022-05-04); rbi.org.in press releases.
# The 2022-11-03 meeting is left out: it drafted the inflation-target report, no rate decision.
RBI_MPC_DAYS = (
    "2019-02-07", "2019-04-04", "2019-06-06", "2019-08-07", "2019-10-04", "2019-12-05",
    "2020-02-06", "2020-03-27", "2020-05-22", "2020-08-06", "2020-10-09", "2020-12-04",
    "2021-02-05", "2021-04-07", "2021-06-04", "2021-08-06", "2021-10-08", "2021-12-08",
    "2022-02-10", "2022-04-08", "2022-05-04", "2022-06-08", "2022-08-05", "2022-09-30",
    "2022-12-07", "2023-02-08", "2023-04-06", "2023-06-08", "2023-08-10", "2023-10-06",
    "2023-12-08", "2024-02-08", "2024-04-05", "2024-06-07", "2024-08-08", "2024-10-09",
    "2024-12-06", "2025-02-07", "2025-04-09", "2025-06-06", "2025-08-06", "2025-10-01",
    "2025-12-05", "2026-02-06", "2026-04-08", "2026-06-05", "2026-08-05", "2026-10-07",
)
# FOMC statement days (US date) incl. unscheduled 2020-03-03 and 2020-03-15; federalreserve.gov calendars.
# Released after the NSE close, so they land on the next Indian session.
FOMC_DAYS = (
    "2019-01-30", "2019-03-20", "2019-05-01", "2019-06-19", "2019-07-31", "2019-09-18",
    "2019-10-30", "2019-12-11", "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29",
    "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-05", "2020-12-16", "2021-01-27",
    "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03",
    "2021-12-15", "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27",
    "2022-09-21", "2022-11-02", "2022-12-14", "2023-02-01", "2023-03-22", "2023-05-03",
    "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13", "2024-01-31",
    "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07",
    "2024-12-18", "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30",
    "2025-09-17", "2025-10-29", "2025-12-10", "2026-01-28", "2026-03-18", "2026-04-29",
    "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28",
)


def event_in_hold(entry, expiry):
    """True when a scheduled event's result lands on a session inside (entry, expiry]."""
    india = BUDGET_DAYS + ELECTION_RESULT_DAYS + RBI_MPC_DAYS
    return any(entry < d <= expiry for d in india) or any(entry <= d < expiry for d in FOMC_DAYS)


def load_chain():
    df = read_sql(
        "SELECT trade_date, expiry_date, strike, option_type, settle, underlying_price, volume "
        "FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO'", (UNDERLYING,))
    df["strike"] = df["strike"].astype(float)
    return df


def load_vix():
    v = read_sql("SELECT date, vix FROM vix_history")
    return dict(zip(v["date"], v["vix"]))


def prices_of(sl):
    """({(cp, K): settle}, underlying) for one (day, expiry) slice."""
    px = {(("C" if o == "CE" else "P"), k): s for o, k, s in zip(sl.option_type, sl.strike, sl.settle)}
    return px, float(sl.underlying_price.iloc[0])


def pick_strikes(day, t, expiry, target):
    """Short call/put strikes nearest `target` delta, from strikes that traded on t.

    Returns (F, {'C': K, 'P': K}, prices dict keyed (cp, K)) or None.
    """
    d = day.deltas(t, expiry)
    if d is None:
        return None
    F, deltas = d
    best = {cp: min((abs(dl - target), K) for dl, K in deltas[cp])[1] for cp in ("C", "P")}
    return F, best, day.prices(t, expiry)[0]


class Chain:
    """The option chain by (day, expiry), with deltas and price maps computed once."""

    def __init__(self, chain):
        self.slices = {k: g for k, g in chain.groupby(["trade_date", "expiry_date"])}
        self._d, self._p = {}, {}

    def get(self, key):
        return self.slices.get(key)

    def deltas(self, t, e):
        if (t, e) not in self._d:
            self._d[(t, e)] = slice_deltas(self.slices[(t, e)], t, e)
        return self._d[(t, e)]

    def prices(self, t, e):
        if (t, e) not in self._p:
            self._p[(t, e)] = prices_of(self.slices[(t, e)])
        return self._p[(t, e)]


def wing_strikes(sl, F, shorts):
    """Long wings: first traded strike at least WING_PCT·F beyond each short strike."""
    ok = sl[(sl.settle > 0) & (sl.volume > 0)]
    calls = ok[(ok.option_type == "CE") & (ok.strike >= shorts["C"] + WING_PCT * F)].strike
    puts = ok[(ok.option_type == "PE") & (ok.strike <= shorts["P"] - WING_PCT * F)].strike
    if calls.empty or puts.empty:
        return None
    return {"C": float(calls.min()), "P": float(puts.max())}


def intrinsic(cp, K, S):
    return max(S - K, 0.0) if cp == "C" else max(K - S, 0.0)


def exit_prices(chain_by_day, t_exit, expiry, legs):
    """{(cp, K): price} at t_exit: intrinsic on expiry day, else that day's settle."""
    if chain_by_day.get((t_exit, expiry)) is None:
        return None
    px, S = chain_by_day.prices(t_exit, expiry)
    if t_exit == expiry:
        return {(cp, K): intrinsic(cp, K, S) for cp, K, _ in legs}
    out = {(cp, K): px.get((cp, K)) for cp, K, _ in legs}
    return None if any(v is None or v <= 0 for v in out.values()) else out


def one_trade(chain_by_day, days, t, t_exit, expiry, target, structure, slip, vix):
    sl = chain_by_day.get((t, expiry))
    if sl is None:
        return None
    picked = pick_strikes(chain_by_day, t, expiry, target)
    if picked is None:
        return None
    F, shorts, px = picked
    legs = [("C", shorts["C"], -1), ("P", shorts["P"], -1)]
    if structure == "condor":
        wings = wing_strikes(sl, F, shorts)
        if wings is None:
            return None
        legs += [("C", wings["C"], +1), ("P", wings["P"], +1)]
    lot = lot_size(t)
    entry = {(cp, K): px[(cp, K)] for cp, K, _ in legs}
    out = exit_prices(chain_by_day, t_exit, expiry, legs)
    if out is None:
        return None

    credit = sum(-q * entry[(cp, K)] for cp, K, q in legs)
    gross = sum(q * (out[(cp, K)] - entry[(cp, K)]) for cp, K, q in legs)
    cost = sum(leg_cost(entry[(cp, K)], "sell" if q < 0 else "buy", lot, slip, t) for cp, K, q in legs)
    if t_exit == expiry:   # cash-settled: no closing trade; long legs ITM pay STT on intrinsic
        cost += sum(STT_EXERCISE * out[(cp, K)] for cp, K, q in legs if q > 0)
    else:                  # closing trade on every leg
        cost += sum(leg_cost(out[(cp, K)], "buy" if q < 0 else "sell", lot, slip, t_exit) for cp, K, q in legs)

    # worst mark-to-market while held (settles on days strictly between entry and exit)
    worst_mtm = 0.0
    i0, i1 = days.index(t), days.index(t_exit)
    for d in days[i0 + 1:i1]:
        mid = exit_prices(chain_by_day, d, expiry, legs)
        if mid is not None:
            worst_mtm = min(worst_mtm, sum(q * (mid[(cp, K)] - entry[(cp, K)]) for cp, K, q in legs))

    if structure == "condor":
        margin = max(legs[2][1] - legs[0][1], legs[1][1] - legs[3][1])
    else:
        margin = MARGIN_STRANGLE_PCT * F
    net = gross - cost
    return {"entry": t, "exit": t_exit, "expiry": expiry, "F": F, "vix": vix.get(t),
            "short_call": shorts["C"], "short_put": shorts["P"],
            "credit": credit, "gross": gross, "cost": cost, "net": net, "margin": margin,
            "ret": net / margin, "worst_mtm_ret": worst_mtm / margin,
            "S_exit": chain_by_day.prices(t_exit, expiry)[1]}


def schedule(chain, hold):
    """[(entry_day, exit_day, expiry)] for one hold rule, no overlapping trades."""
    days = sorted(chain.trade_date.unique())
    expiries = sorted(chain.expiry_date.unique())
    front = {}
    for d in days:   # nearest expiry strictly after d (the "front week")
        nxt = [e for e in expiries if e > d]
        if nxt:
            front[d] = nxt[0]
    out = []
    if hold == "daily":
        for i, d in enumerate(days[:-1]):
            e = front.get(d)
            if e and days[i + 1] <= e:
                out.append((d, days[i + 1], e))
        return days, out
    k = int(hold[3:])
    last_exit = ""
    for e in sorted(set(front.values())):
        if e not in days:
            continue
        j = days.index(e) - k
        if j < 0 or days[j] < last_exit or front.get(days[j]) != e:
            continue
        out.append((days[j], e, e))
        last_exit = e
    return days, out


def summarize(tr, per_year):
    if tr.empty:
        return {}
    r = tr["ret"]
    cum = r.cumsum()
    dd = (cum - cum.cummax()).min()
    losses = r[r < 0].sort_values()
    tail = losses.head(max(1, int(len(r) * 0.05))).sum()
    return {"n": len(r), "win%": 100 * (r > 0).mean(),
            "credit_pts": tr["credit"].mean(), "cost/credit%": 100 * tr["cost"].sum() / tr["credit"].sum(),
            "mean%": 100 * r.mean(), "ann%": 100 * r.mean() * per_year,
            "sharpe": r.mean() / r.std() * np.sqrt(per_year) if r.std() > 0 else np.nan,
            "worst%": 100 * r.min(), "worst_day": tr.loc[r.idxmin(), "entry"],
            "worst_mtm%": 100 * min(tr["worst_mtm_ret"].min(), r.min()),
            "maxDD%": 100 * dd, "tail5%/gains": -tail / r[r > 0].sum() if (r > 0).any() else np.nan}


def run(chain, chain_by_day, vix, stt, slip, start, end="9999"):
    ob.STT_SELL = stt
    rows, all_trades = [], []
    for hold in HOLDS:
        days, sched = schedule(chain, hold)
        sched = [s for s in sched if start <= s[0] and s[1] <= end]
        per_year = 250 if hold == "daily" else 50
        for structure in STRUCTURES:
            for target in DELTAS:
                tr = [one_trade(chain_by_day, days, t, x, e, target, structure, slip, vix) for t, x, e in sched]
                skipped = sum(1 for x in tr if x is None)
                tr = pd.DataFrame([x for x in tr if x is not None])
                s = summarize(tr, per_year)
                rows.append({"hold": hold, "structure": structure, "delta": target, "skipped": skipped, **s})
                if not tr.empty:
                    tr["hold"], tr["structure"], tr["delta"] = hold, structure, target
                    all_trades.append(tr)
    return pd.DataFrame(rows), pd.concat(all_trades, ignore_index=True)


def by_vix(trades):
    t = trades.copy()
    t["vix_bucket"] = pd.cut(t["vix"], [b[0] for b in VIX_BUCKETS] + [VIX_BUCKETS[-1][1]], right=False,
                             labels=[f"{a}-{b}" if b < 999 else f"{a}+" for a, b in VIX_BUCKETS])
    g = t.groupby(["hold", "structure", "delta", "vix_bucket"], observed=True)["ret"]
    return pd.DataFrame({"n": g.size(), "win%": 100 * g.apply(lambda r: (r > 0).mean()),
                         "mean%": 100 * g.mean(), "worst%": 100 * g.min()}).reset_index()


def load_index():
    """NIFTY 50 close + India VIX by day from 2015 (macro_history; yfinance)."""
    n = read_sql("SELECT date, value AS close FROM macro_history WHERE indicator_id = 'nifty50' ORDER BY date")
    n["vix"] = n["date"].map(load_vix())
    return n.dropna().reset_index(drop=True)


def calibrate(trades):
    """Strike distance and credit in units of s = VIX·√T, from the real chain trades.

    Per (hold, structure, delta): median zC = ln(Kc/F)/s, zP = ln(F/Kp)/s, credit/F/s,
    and mean cost/F. VIX stands in for the weekly IV; the ratios absorb the gap.
    """
    t = trades[trades.hold != "daily"].copy()
    days = t.apply(lambda r: (date.fromisoformat(r.expiry) - date.fromisoformat(r.entry)).days, axis=1)
    s = t["vix"] / 100 * np.sqrt(days / 365)
    t["zC"], t["zP"] = np.log(t.short_call / t.F) / s, np.log(t.F / t.short_put) / s
    t["c"], t["k"] = t.credit / t.F / s, t.cost / t.F
    return t.groupby(["hold", "structure", "delta"])[["zC", "zP", "c", "k"]].agg(
        {"zC": "median", "zP": "median", "c": "median", "k": "mean"})


def stress(idx, cal, start, end):
    """Model P&L for every entry day in [start, end): hold `k` trading days to an assumed expiry.

    Returns one row per (hold, structure, delta, entry day) with ret = P&L / margin.
    """
    idx = idx.reset_index(drop=True)
    rows = []
    for (hold, structure, delta), p in cal.iterrows():
        k = int(hold[3:])
        for i in range(len(idx) - k):
            d0, d1 = idx.date[i], idx.date[i + k]
            if not (start <= d0 < end):
                continue
            days = (date.fromisoformat(d1) - date.fromisoformat(d0)).days
            s = idx.vix[i] / 100 * np.sqrt(days / 365)
            g = idx.close[i + k] / idx.close[i]            # S_exit / F  (carry ignored over 1–3 days)
            kc, kp = np.exp(p.zC * s), np.exp(-p.zP * s)
            loss = max(g - kc, 0) + max(kp - g, 0)
            if structure == "condor":
                loss -= max(g - kc * (1 + WING_PCT), 0) + max(kp * (1 - WING_PCT) - g, 0)
                margin = WING_PCT
            else:
                margin = MARGIN_STRANGLE_PCT
            rows.append({"hold": hold, "structure": structure, "delta": delta, "entry": d0, "exit": d1,
                         "move%": 100 * (g - 1), "vix": idx.vix[i], "ret": (p.c * s - loss - p.k) / margin})
    return pd.DataFrame(rows)


def stress_summary(st):
    g = st.groupby(["hold", "structure", "delta"])["ret"]
    out = pd.DataFrame({"n": g.size(), "win%": 100 * g.apply(lambda r: (r > 0).mean()),
                        "mean%": 100 * g.mean(), "ann%(50/yr)": 100 * 50 * g.mean(),
                        "p1%": 100 * g.quantile(0.01), "worst%": 100 * g.min(),
                        "worst_day": st.loc[g.idxmin(), "entry"].values,
                        "days<-50%": g.apply(lambda r: int((r < -0.5).sum()))})
    return out.reset_index()


def _book(r, per_year):
    cum = r.cumsum()
    return {"n": len(r), "mean%": 100 * r.mean(), "ann%": 100 * r.mean() * per_year,
            "worst%": 100 * r.min() if len(r) else np.nan, "maxDD%": 100 * (cum - cum.cummax()).min() if len(r) else np.nan}


def veto_report(trades, cells=None):
    """Base vs each pre-registered veto, per cell. A veto passes (a) when the trades it
    skips did worse than the trades it keeps, and (b) when worst trade and max drawdown
    both improve."""
    t = trades.sort_values("entry").copy()
    t["v_event"] = [event_in_hold(e, x) for e, x in zip(t.entry, t.exit)]
    t["v_vix"] = t["vix"] > VIX_VETO
    t["v_both"] = t.v_event | t.v_vix
    rows = []
    for (hold, structure, delta), g in t.groupby(["hold", "structure", "delta"]):
        if cells and (hold, structure, delta) not in cells:
            continue
        per_year = 250 if hold == "daily" else 50
        base = _book(g["ret"], per_year)
        for v in ("v_event", "v_vix", "v_both"):
            kept, skipped = g.loc[~g[v], "ret"], g.loc[g[v], "ret"]
            k = _book(kept, per_year)
            rows.append({"hold": hold, "structure": structure, "delta": delta, "veto": v[2:],
                         "skipped": len(skipped), "skip_mean%": 100 * skipped.mean() if len(skipped) else np.nan,
                         "kept_mean%": k["mean%"], "base_ann%": base["ann%"], "kept_ann%": k["ann%"],
                         "base_worst%": base["worst%"], "kept_worst%": k["worst%"],
                         "base_maxDD%": base["maxDD%"], "kept_maxDD%": k["maxDD%"],
                         "a": bool(len(skipped)) and skipped.mean() < kept.mean(),
                         "b": k["worst%"] > base["worst%"] and k["maxDD%"] > base["maxDD%"]})
    return pd.DataFrame(rows)


def main():
    global UNDERLYING
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--stt", type=float, default=STT_SELL)
    ap.add_argument("--slip", type=float, default=SLIP)
    ap.add_argument("--start", default=REGIME_START, help="first entry date (default: SEBI Nov-2024 regime)")
    ap.add_argument("--end", default="9999", help="last exit date")
    ap.add_argument("--underlying", default=UNDERLYING, choices=sorted(LOT_SIZES))
    ap.add_argument("--veto", action="store_true", help="also report the pre-registered vetoes")
    ap.add_argument("--trades", help="write every trade to this CSV")
    ap.add_argument("--vix", action="store_true", help="also print results by VIX at entry")
    ap.add_argument("--sensitivity", action="store_true",
                    help="also run STT 0.15%%, slippage 3%%, and entries from the first chain date")
    ap.add_argument("--stress", action="store_true",
                    help="extend to 2015 with a model calibrated on the chain trades (NIFTY + VIX history)")
    a = ap.parse_args()
    UNDERLYING = a.underlying
    pd.set_option("display.width", 220, "display.max_columns", 30, "display.max_rows", 300)
    chain, vix = load_chain(), load_vix()
    chain_by_day = Chain(chain)
    cases = [(a.stt, a.slip, a.start)]
    if a.sensitivity:
        cases += [(0.0015, a.slip, a.start), (a.stt, 0.03, a.start), (a.stt, a.slip, chain.trade_date.min())]
    for i, (stt, slip, start) in enumerate(cases):
        res, trades = run(chain, chain_by_day, vix, stt, slip, start, a.end)
        print(f"\n{UNDERLYING} premium selling · entries {start} → {a.end} · STT {stt:.4%} (after 2024-10) · slippage {slip:.1%}")
        print("returns are % of the assumed margin per trade; ann% = mean × trades/yr (no compounding)")
        print(res.round(2).to_string(index=False))
        if i == 0:
            if a.trades:
                trades.to_csv(a.trades, index=False)
            if a.veto:
                print("\nvetoes on the chain trades (pre-registered; a = skipped did worse, b = worst + maxDD improve)")
                print(veto_report(trades).round(2).to_string(index=False))
            if a.vix:
                print("\nby India VIX at entry")
                print(by_vix(trades).round(2).to_string(index=False))
            if a.stress:
                cal = calibrate(trades)
                idx = load_index()
                print("\ncalibration (strike distance and credit in units of VIX·√T)")
                print(cal.round(3).to_string())
                print(f"\nSTRESS — model on NIFTY + VIX, every entry day, check window {start} → (model vs chain above)")
                print(stress_summary(stress(idx, cal, start, "9999")).round(2).to_string(index=False))
                print(f"\nSTRESS — model on NIFTY + VIX, every entry day, {idx.date.min()} → {start} (out of sample)")
                oos = stress(idx, cal, idx.date.min(), start)
                print(stress_summary(oos).round(2).to_string(index=False))
                if a.veto:
                    print("\nvetoes on the model, every entry day before the window")
                    print(veto_report(oos[oos.structure == "strangle"]).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
