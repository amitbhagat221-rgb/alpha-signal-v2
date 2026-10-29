"""
Combined book (Amit 2026-10-28): ₹75 L split between a liquid fund and a SMALL equity book (slow or
fast), both pledged at Zerodha as collateral for the live weekly strangle (exp2, 0.05 delta, NIFTY +
SENSEX, naked or with 1.75 % wings), after costs and Indian tax. READ-ONLY on the DB; writes
data/lh/v2/combined_*.

FIXED BEFORE ANY RESULT (2026-10-28):
  Capital    ₹75 L = ₹5 L cash (kept; topped up / swept monthly) + ₹70 L split: liquid share w of it
             in Axis Liquid Fund direct growth (scheme 120389), the rest in the SMALL book.
             Grid w = 0, 0.25, 0.5, 0.75, 1.0 · book = slow | fast · options = naked | winged.
  Books      tools.lh_book unchanged (measured costs, STCG / LTCG at today's rates with set-off,
             forensic red-flag sale), at the sleeve's own capital:
               slow  slow_v2 · monthly · top 20 · sell below 60 · 3-month average · 12-month min hold
               fast  monthly · top 20 · sell below 40 · raw · no min hold · no tax deferral
             Window L 2019-12 → 2026-10: slow_v2 and fast_v1 (fast_v1 = today's live weights on
             history: IN-SAMPLE, flatters the fast book). Window S 2022-06 → 2026-10: slow_v2 and
             fast_select (walk-forward, honest). Window S decides "fast vs slow".
             Between monthly anchors the book's value moves with the NIFTY SMALLCAP 250 index.
  Options    tools.option_premium_backtest.one_trade (EOD settle prices, 1 % slippage, date-correct
             charges), exp2 schedule, NIFTY every week, SENSEX from 2024-01. Winged = the same shorts
             + longs 1.75 % of the forward beyond (WING_PCT). Lots each entry:
             floor((collateral − spare − margin already in use) / margin per lot), spare = 15 % of
             collateral, at most 60; VIX ≥ 30 no entry, > 27 half.
             Margin per lot (Kite 2026-10-28, VIX ~16): naked entry 9.9 % (NIFTY) / 11.1 % (SENSEX)
             of notional × max(1, VIX / 16); winged 5.7 % / 5.8 %, not scaled; from 2024-11-20
             + the expiry-day 2 % ELM on both short legs (4 % of notional).
  Collateral liquid fund 90 % of value, SMALL book 65 % (haircut + unpledgeable names), cash 100 %.
             The fast book replaces ~75 % of its names a month: for 3 sessions after each monthly
             entry only 25 % of its collateral counts (new shares are pledged after delivery).
  Charges    50:50 rule: interest 0.035 %/day on (margin in use / 2 − cash-like collateral) when
             positive; debit interest 0.05 %/day on negative cash. Pledge fees ignored.
  Tax        per FY: options P&L − interest + the liquid fund's gain (taxed as if redeemed each FY)
             at the new-regime slabs (FY 2025-26 schedule for every year), 87A rebate ≤ ₹12 L,
             10 % / 15 % surcharge above ₹50 L / ₹1 Cr, 4 % cess; a net loss is carried forward.
             The SMALL book's own capital-gains tax is inside lh_book (final value = its ATLV).
  Stress     at every entry: the loss if the index gapped −13.9 % through the open strangles (naked:
             put intrinsic − credit; winged: capped at the 1.75 % wing) and the SMALL book fell 25 %, as a
             share of total value then → mean and max over the window. Nothing in 2020-26 tested this
             while positions were open (the VIX guard sat out March-May 2020).
  Reported   after-tax CAGR, max drawdown (daily total value), worst calendar year,
             worst week, margin-shortfall days (collateral < margin in use), lots used.
Not modelled: intraday margin calls and forced exits (counted, not acted on), wing fill quality
(settle prices; far strikes can cost more), the paper sleeve's ₹1 Cr liquidity floor.

    python -m tools.combined_book_study           # full grid, both windows (~15 min)
    python -m tools.combined_book_study --smoke   # one cell, prints the path
"""

import argparse
import math
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import option_book as ob  # noqa: E402
import tools.lh_book as B  # noqa: E402
import tools.option_premium_backtest as opb  # noqa: E402

LH = ROOT / "data" / "lh"
V2 = LH / "v2"
DB = ROOT / "data" / "alpha_signal.db"

CAPITAL, CASH0 = 7_500_000.0, 500_000.0
LIQUID_SCHEME = "120389"
W_GRID = (0.0, 0.25, 0.5, 0.75, 1.0)
HAIRCUT = {"liquid": 0.90, "equity": 0.65, "cash": 1.0}
FAST_PLEDGE_GAP = (3, 0.25)            # sessions after a monthly entry, share of the fast book's collateral counted
SPARE_PCT = 0.15
STRESS_BUDGET = None                   # --stress-budget b: lots also limited so the stress loss stays ≤ b × total value
LOTS_MAX = 10_000                      # no cap by default (--lots-max): lot sizes changed 75 → 50 → 25 → 75 → 65
VIX_HALT, VIX_HALVE = 30.0, 27.0
NAKED = {"NIFTY": 0.099, "SENSEX": 0.111}
WINGED = {"NIFTY": 0.057, "SENSEX": 0.058}
ELM_FROM, ELM = "2024-11-20", 0.04
WING = 0.0175
STRESS = (0.139, 0.25)                 # stress at every entry: index −13.9 % gap (2020-03-23), SMALL book −25 %
SHORTFALL_RATE, DEBIT_RATE = 0.00035, 0.0005
BOOKS = {"slow": dict(reb="M", N=20, k=3, score="avg3", min_hold=12, defer=True),
         "fast": dict(reb="M", N=20, k=2, score="raw", min_hold=0, defer=False)}
WINDOWS = {"L": dict(dir=V2 / "win_B", slow="slow_v2", fast="fast_v1"),
           "S": dict(dir=LH, slow="slow_v2", fast="fast_select", slow_dir=V2 / "win_A")}
SLABS = ((400_000, 0.0), (800_000, 0.05), (1_200_000, 0.10), (1_600_000, 0.15), (2_000_000, 0.20),
         (2_400_000, 0.25), (math.inf, 0.30))


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


# ───────────────────────────── tax (pure) ─────────────────────────────

def slab_tax(income):
    """New-regime tax on normal income (FY 2025-26 slabs, 87A rebate, surcharge, 4 % cess)."""
    if income <= 1_200_000:
        return 0.0
    tax, lo = 0.0, 0.0
    for hi, r in SLABS:
        tax += max(0.0, min(income, hi) - lo) * r
        lo = hi
        if income <= hi:
            break
    sur = 0.15 if income > 10_000_000 else 0.10 if income > 5_000_000 else 0.0
    return tax * (1 + sur) * 1.04


# ───────────────────────────── inputs ─────────────────────────────

def option_trades(underlying, structure, start):
    """exp2 0.05-delta trades → entry, expiry, F, lot, net (points per unit), vix."""
    opb.UNDERLYING = underlying
    opb.WING_PCT = WING
    chain, vix = opb.load_chain(), opb.load_vix()
    cb = opb.Chain(chain)
    days, sched = opb.schedule(chain, "exp2")
    rows = []
    for t, x, e in sched:
        if t < start:
            continue
        r = opb.one_trade(cb, days, t, x, e, 0.05, structure, ob.SLIP, vix)
        if r is not None:
            rows.append({"underlying": underlying, "entry": t, "expiry": e, "F": r["F"], "net": r["net"],
                         "credit": r["credit"], "vix": r["vix"], "lot": ob.lot_size(underlying, t, e),
                         "short_put": r["short_put"], "short_call": r["short_call"]})
    return pd.DataFrame(rows)


def all_trades(structure, start):
    f = V2 / f"combined_trades_{structure}.parquet"
    if f.exists():
        t = pd.read_parquet(f)
        if t.entry.min() <= start:
            return t[t.entry >= start].reset_index(drop=True)
    t = pd.concat([option_trades(u, structure, "2019-01-01") for u in ("NIFTY", "SENSEX")], ignore_index=True)
    t = t.sort_values(["entry", "underlying"]).reset_index(drop=True)
    t.to_parquet(f, index=False)
    return t[t.entry >= start].reset_index(drop=True)


def equity_books(window, capitals):
    """{(book, capital): monthly DataFrame (entry, nav, atlv)} from lh_book, one Data() per score dir
    (cached in data/lh/v2/combined_books_<window>.parquet)."""
    w = WINDOWS[window]
    cache = V2 / f"combined_books_{window}.parquet"
    if cache.exists():
        c = pd.read_parquet(cache)
        have = {(b, float(k)): g[["entry", "nav", "atlv"]].reset_index(drop=True) for (b, k), g in c.groupby(["book", "capital"])}
        if all(("slow", float(k)) in have and ("fast", float(k)) in have for k in capitals if k > 0):
            return {(b, k): have[(b, float(k))] for b in ("slow", "fast") for k in capitals if k > 0}
    out = {}
    for book in ("slow", "fast"):
        B.LH = w.get(f"{book}_dir", w["dir"])
        D = B.Data()
        for cap in capitals:
            if cap <= 0:
                continue
            v = dict(BOOKS[book], method=w[book], capital=cap, block="combined")
            bench = B.benchmark(D, "SMALL", cap0=cap)
            r, m = B.simulate(D, "SMALL", v, bench)
            out[(book, cap)] = m[["entry", "nav", "atlv"]].assign(entry=lambda d: pd.to_datetime(d.entry))
            print(f"  {window} {book} ₹{cap / 1e5:.1f} L: CAGR after tax {r['cagr_after_tax']:.3f}, "
                  f"index {r['bench_cagr_after_tax']:.3f}, turnover {r['turnover_pa']:.2f}/yr")
    B.LH = LH
    pd.concat([m.assign(book=b, capital=float(k)) for (b, k), m in out.items()]).to_parquet(cache, index=False)
    return out


def daily_series(start, end):
    con = ro()
    liq = pd.read_sql("SELECT nav_date AS d, nav FROM mf_nav_history WHERE scheme_code = ? ORDER BY 1", con,
                      params=[LIQUID_SCHEME]).set_index("d")["nav"]
    idx = pd.read_sql("SELECT trade_date AS d, close FROM nse_index_history WHERE index_symbol = 'NIFTY SMALLCAP 250' "
                      "ORDER BY 1", con).set_index("d")["close"]
    days = pd.read_sql("SELECT DISTINCT trade_date AS d FROM nse_index_history WHERE index_symbol = 'NIFTY 50' "
                       "AND trade_date BETWEEN ? AND ? ORDER BY 1", con, params=[start, end])["d"].tolist()
    con.close()
    liq.index, idx.index = pd.to_datetime(liq.index), pd.to_datetime(idx.index)
    d = pd.to_datetime(days)
    return d, liq.reindex(liq.index.union(d)).ffill().reindex(d), idx.reindex(idx.index.union(d)).ffill().reindex(d)


def equity_path(m, days, idx):
    """Daily book value: the monthly NAV, moved with the Smallcap 250 between entries; ATLV at the end."""
    m = m.dropna(subset=["entry"]).sort_values("entry")
    val = pd.Series(np.nan, index=days)
    anchors = m.set_index("entry")
    last_nav, last_idx = None, None
    first = anchors.index.min()
    for d in days:
        if d in anchors.index:
            last_nav, last_idx = float(anchors.loc[d, "nav"]), float(idx.loc[d])
        if last_nav is not None and d >= first:
            val[d] = last_nav * float(idx.loc[d]) / last_idx
    return val, float(m["atlv"].iloc[-1]), set(anchors.index)


# ───────────────────────────── the combined book ─────────────────────────────

def margin_per_lot(tr, structure):
    pct = (WINGED if structure == "condor" else NAKED)[tr.underlying]
    if structure != "condor" and pd.notna(tr.vix):
        pct *= max(1.0, tr.vix / 16.0)
    if tr.entry >= ELM_FROM:
        pct += ELM
    return pct * tr.F * tr.lot


def crash_loss(tr, structure):
    """₹ per unit lost if the index gaps STRESS[0] down through the open strangle (premium kept)."""
    S = tr.F * (1 - STRESS[0])
    hit = max(0.0, tr.short_put - S)
    if structure == "condor":
        hit = min(hit, WING * tr.F)
    return max(0.0, hit - tr.credit)


def guard(vix, lots):
    """The live VIX guard: unknown or ≥ 30 no entry, > 27 half the lots (at least 1)."""
    if pd.isna(vix) or vix >= VIX_HALT:
        return 0
    return (max(1, lots // 2) if lots else 0) if vix > VIX_HALVE else lots


def simulate(w, book, structure, trades, days, liq, eq):
    """One cell → (metrics dict, daily DataFrame). Options P&L lands in cash at expiry; cash above ₹5 L
    is swept into the liquid fund on the first session of each month (and topped up from it)."""
    liquid0 = w * (CAPITAL - CASH0)
    equity0 = CAPITAL - CASH0 - liquid0
    eq_val, eq_atlv, eq_entries = eq if equity0 > 0 else (pd.Series(0.0, index=days), 0.0, set())
    gap = set()
    if book == "fast" and equity0 > 0:
        for x in eq_entries:
            if x in days:
                gap.update(range(days.get_loc(x), days.get_loc(x) + FAST_PLEDGE_GAP[0]))
    by_entry = {d: g for d, g in trades.groupby("entry")}
    st = {"units": liquid0 / float(liq.iloc[0]), "basis": liquid0, "cash": CASH0, "fy_inc": 0.0, "carry": 0.0,
          "tax": 0.0, "interest": 0.0}
    open_, rows, lots_used, shortfall_days, fy, month, stress = [], [], [], 0, None, None, []

    def liquid_value(px):
        return st["units"] * px

    def move_to_liquid(amount, px):                         # amount < 0: redeem (at cost-basis share)
        if amount < 0:
            amount = max(amount, -liquid_value(px))
            if liquid_value(px) > 0:
                st["basis"] *= 1 + amount / liquid_value(px)
        else:
            st["basis"] += amount
        st["units"] += amount / px
        st["cash"] -= amount

    def pay_tax(px):
        gain = liquid_value(px) - st["basis"]               # taxed as if redeemed each FY
        st["basis"] = liquid_value(px)
        income = st["fy_inc"] + gain - st["carry"]
        t = slab_tax(income) if income > 0 else 0.0
        st["carry"] = max(0.0, -income)
        st["tax"] += t
        st["cash"] -= t
        st["fy_inc"] = 0.0

    for i, d in enumerate(days):
        ds, px = d.date().isoformat(), float(liq.iloc[i])
        cur_fy = d.year if d.month >= 4 else d.year - 1
        if fy is not None and cur_fy != fy:
            pay_tax(px)
        fy = cur_fy
        if month != (d.year, d.month):
            if month is not None:
                move_to_liquid(st["cash"] - CASH0, px)
            month = (d.year, d.month)
        for p in [p for p in open_ if p["expiry"] <= ds]:   # expiries first: the buy-back frees margin
            st["cash"] += p["pnl"]
            st["fy_inc"] += p["pnl"]
            open_.remove(p)
        e_now = float(eq_val.iloc[i]) if pd.notna(eq_val.iloc[i]) else equity0
        e_coll = HAIRCUT["equity"] * e_now * (FAST_PLEDGE_GAP[1] if i in gap else 1.0)
        coll = HAIRCUT["liquid"] * liquid_value(px) + e_coll + st["cash"]
        used = sum(p["margin"] for p in open_)
        for tr in (by_entry[ds].itertuples() if ds in by_entry else []):
            mpl = margin_per_lot(tr, structure)
            lots = max(0, min(LOTS_MAX, math.floor((coll * (1 - SPARE_PCT) - used) / mpl)))
            if STRESS_BUDGET is not None:
                total = liquid_value(px) + st["cash"] + e_now
                room = STRESS_BUDGET * total - STRESS[1] * e_now - sum(p["crash"] for p in open_)
                per = tr.lot * crash_loss(tr, structure)
                lots = min(lots, max(0, math.floor(room / per))) if per > 0 else lots
            lots = guard(tr.vix, lots)
            if lots:
                open_.append({"expiry": tr.expiry, "margin": lots * mpl, "pnl": lots * tr.net * tr.lot,
                              "crash": lots * tr.lot * crash_loss(tr, structure)})
                used += lots * mpl
                total = liquid_value(px) + st["cash"] + e_now
                stress.append((sum(p["crash"] for p in open_) + STRESS[1] * e_now) / total)
            lots_used.append(lots)
        cash_like = HAIRCUT["liquid"] * liquid_value(px) + max(st["cash"], 0.0)
        charge = max(0.0, used / 2 - cash_like) * SHORTFALL_RATE + max(0.0, -st["cash"]) * DEBIT_RATE
        st["cash"] -= charge
        st["interest"] += charge
        st["fy_inc"] -= charge
        shortfall_days += used > coll
        rows.append({"d": d, "liquid": liquid_value(px), "cash": st["cash"], "equity": e_now, "used": used,
                     "coll": coll, "total": liquid_value(px) + st["cash"] + e_now})
    pay_tax(float(liq.iloc[-1]))                            # the last FY, part-year
    path = pd.DataFrame(rows).set_index("d")
    years = (days[-1] - days[0]).days / 365.25
    final_after = liquid_value(float(liq.iloc[-1])) + st["cash"] + (eq_atlv if equity0 > 0 else 0.0)
    tot = path["total"]
    yr = tot.groupby(tot.index.year).agg(["first", "last"])
    yr = yr["last"] / yr["first"] - 1
    wk = tot.resample("W").last().pct_change().dropna()
    traded = [x for x in lots_used if x]
    return {"w_liquid": w, "book": book if equity0 > 0 else "-", "options": "winged" if structure == "condor" else "naked",
            "years": round(years, 2), "cagr_after_tax": (final_after / CAPITAL) ** (1 / years) - 1,
            "final_after_tax_rs": final_after, "max_dd": float((tot / tot.cummax() - 1).min()),
            "worst_year": float(yr.min()), "worst_year_at": int(yr.idxmin()), "worst_week": float(wk.min()),
            "tax_paid_rs": st["tax"], "interest_rs": st["interest"], "shortfall_days": int(shortfall_days),
            "avg_lots": float(np.mean(traded)) if traded else 0.0,
            "skipped_entries": int(len(lots_used) - len(traded)),
            "stress_mean": float(np.mean(stress)) if stress else 0.0, "stress_max": float(np.max(stress)) if stress else 0.0}, path


def run(window, smoke=False):
    w = WINDOWS[window]
    start = "2019-12-03" if window == "L" else "2022-06-02"
    caps = sorted({round((1 - x) * (CAPITAL - CASH0)) for x in (W_GRID if not smoke else (0.5,)) if x < 1})
    books = equity_books(window, caps)
    end = min(m["entry"].max() for m in books.values()).date().isoformat()
    days, liq, idx = daily_series(start, end)
    res = []
    for structure in ("strangle", "condor"):
        trades = all_trades(structure, start)
        trades = trades[trades.expiry <= end]
        for x in (W_GRID if not smoke else (0.5,)):
            for book in (("slow", "fast") if x < 1 else ("slow",)):
                cap = round((1 - x) * (CAPITAL - CASH0))
                eq = equity_path(books[(book, cap)], days, idx) if cap > 0 else None
                r, path = simulate(x, book, structure, trades, days, liq, eq)
                r.update(window=window, start=start, end=end)
                res.append(r)
                print(f"{window} w={x:.2f} {r['book']:4s} {r['options']:6s}: after tax {r['cagr_after_tax']:+.1%}/yr, "
                      f"max DD {r['max_dd']:.1%}, worst year {r['worst_year']:+.1%} "
                      f"({r['worst_year_at']}), lots ~{r['avg_lots']:.0f}, shortfall days {r['shortfall_days']}")
                if smoke:
                    print(path.iloc[::60].round(0).to_string())
    return pd.DataFrame(res)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--window", choices=["L", "S", "both"], default="both")
    ap.add_argument("--lots-max", type=int, default=LOTS_MAX)
    ap.add_argument("--tag", default="")
    ap.add_argument("--stress-budget", type=float, default=None)
    a = ap.parse_args()
    globals()["LOTS_MAX"] = a.lots_max
    globals()["STRESS_BUDGET"] = a.stress_budget
    out = []
    for w in (("L", "S") if a.window == "both" else (a.window,)):
        out.append(run(w, smoke=a.smoke))
    df = pd.concat(out, ignore_index=True)
    if not a.smoke:
        f = V2 / f"combined_results{a.tag}.csv"
        df.assign(lots_max=a.lots_max, stress_budget=a.stress_budget).to_csv(f, index=False)
        print(f"wrote {f}")


if __name__ == "__main__":
    main()
