"""
Alpha Signal v2 — option-premium paper book (plan 0022).

One rule, pre-registered 2026-10-10, recorded forward from the first entry day after it:
sell a 0.05-delta strangle (one call, one put, no wings) on NIFTY and SENSEX at the close
2 trading sessions before the weekly expiry, hold to expiry, 1 lot each.

This module is also the core the backtest uses (tools/option_premium_backtest.py imports
the strike picker, costs and lot sizes from here), so the forward record and the
backtest are one implementation.

    python -m option_book --record    # morning run: write new entry days, settle expired trades
    python -m option_book --show      # print the book

Reads:  fno_bhav (EOD chain, NSE + BSE), market_holidays (F&O sessions),
        option_live_quotes (15:20 IST Kite snapshot: live strikes, bid/ask, Kite margin)
Writes: option_paper_trades (one row per underlying × expiry; settled in place)
"""

import argparse
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from db import read_sql, upsert_df
from sources.fno_iv import _forward_delta, _implied_forward, _invert_iv

# ── the rule (plan 0022 §1; do not change during the test) ──
RULE = {"id": "strangle_d05_s2", "delta": 0.05, "sessions_before_expiry": 2,
        "underlyings": ("NIFTY", "SENSEX"), "lots": 1}
FIRST_ENTRY = "2026-10-09"      # first entry day after the rule was fixed (its expiry, 2026-10-13, was unknown)

STRIKE_BAND = 0.10              # only strikes within 10% of the forward are considered

# ── costs (Zerodha + exchange, as understood 2026-10) ──
BROKERAGE_RS = 20.0             # per executed order
GST = 0.18                      # on brokerage + exchange charge
EXCHANGE = 0.0003503            # options transaction charge, of premium
STT_SELL = 0.001                # STT on option premium, sell side (raised Oct 2024)
STT_SELL_BEFORE = (("2024-10-01", 0.000625),)
STT_EXERCISE = 0.00125          # STT on intrinsic value, long legs exercised at expiry
STAMP_BUY = 0.00003             # stamp duty, buy side
SLIP = 0.01                     # slippage, fraction of price per leg per side
TICK = 0.05
MARGIN_STRANGLE_PCT = 0.12      # of the forward, when no Kite margin was captured (Kite: 11.8% / 10.7%)

# lot size from (first trade date it applies, lot). NIFTY measured from the legacy
# archive's futures turnover 2019-01 → 2024-04 (75, then 50 from mid-2021), NSE circulars
# after; SENSEX from BSE files (10 on 2024-01-11, 20 on 2026-10-08; change date assumed).
LOT_SIZES = {
    "NIFTY": (("2015-01-01", 75), ("2021-07-01", 50), ("2024-04-26", 25), ("2024-12-26", 75), ("2025-12-30", 65)),
    "SENSEX": (("2023-01-01", 10), ("2025-01-01", 20)),
}


def lot_size(underlying, d):
    sizes = LOT_SIZES[underlying]
    lot = sizes[0][1]
    for since, n in sizes:
        if d >= since:
            lot = n
    return lot


def stt_sell(d):
    for until, rate in STT_SELL_BEFORE:
        if d < until:
            return rate
    return STT_SELL


def years(t0, t1):
    return (date.fromisoformat(t1) - date.fromisoformat(t0)).days / 365.0


def leg_cost(price, side, lot, slip, d):
    """Points per unit for trading one leg once (side = 'sell' | 'buy')."""
    c = BROKERAGE_RS * (1 + GST) / lot
    c += price * EXCHANGE * (1 + GST)
    c += price * (stt_sell(d) if side == "sell" else STAMP_BUY)
    c += max(TICK, slip * price)
    return c


def intrinsic(cp, K, S):
    return max(S - K, 0.0) if cp == "C" else max(K - S, 0.0)


def slice_deltas(sl, t, expiry):
    """(F, {'C': [(|delta|, K)], 'P': [...]}) for the OTM strikes that traded on t, or None.

    `sl`: one (day, expiry) chain with columns option_type (CE/PE), strike, settle, volume.
    The forward comes from put-call parity at the money (sources.fno_iv)."""
    T = years(t, expiry)
    ce = sl[sl.option_type == "CE"].set_index("strike")["settle"]
    pe = sl[sl.option_type == "PE"].set_index("strike")["settle"]
    F, _ = _implied_forward(ce[ce > 0], pe[pe > 0], T)
    if F is None:
        return None
    traded = sl[(sl.volume > 0) & (sl.settle > 0) & ((sl.strike - F).abs() <= STRIKE_BAND * F)]
    deltas = {}
    for cp, side in (("C", traded[(traded.option_type == "CE") & (traded.strike > F)]),
                     ("P", traded[(traded.option_type == "PE") & (traded.strike < F)])):
        deltas[cp] = []
        for K, px in zip(side.strike, side.settle):
            iv = _invert_iv(px, F, K, T, cp)
            if np.isfinite(iv):
                deltas[cp].append((abs(_forward_delta(F, K, T, iv, cp)), K))
        if not deltas[cp]:
            return None
    return F, deltas


def nearest(deltas, target):
    """{'C': K, 'P': K}: the strike whose |delta| is nearest `target` on each side."""
    return {cp: min((abs(dl - target), K) for dl, K in deltas[cp])[1] for cp in ("C", "P")}


# ── sessions ──

def holidays():
    """F&O holidays (ISO dates) from market_holidays. Raises when the list is empty:
    without it an entry day cannot be placed (plan 0022 §1)."""
    h = read_sql("SELECT holiday_date FROM market_holidays WHERE segment = 'FO'")
    if h.empty:
        raise RuntimeError("market_holidays has no F&O rows — run `python -m sources.nse_holidays`")
    return set(h["holiday_date"])


def is_session(d, hol):
    return d.weekday() < 5 and d.isoformat() not in hol


def entry_day(expiry, hol, n=RULE["sessions_before_expiry"]):
    """The trading session n sessions before `expiry` (ISO in, ISO out)."""
    d, seen = date.fromisoformat(expiry), 0
    while seen < n:
        d -= timedelta(days=1)
        if is_session(d, hol):
            seen += 1
    return d.isoformat()


# ── the book ──

def _chain(underlying, t, expiry):
    return read_sql("SELECT option_type, strike, settle, volume, underlying_price FROM fno_bhav "
                    "WHERE symbol = ? AND instrument_type = 'IDO' AND trade_date = ? AND expiry_date = ?",
                    params=[underlying, t, expiry])


def _live(underlying, t, expiry):
    """The 15:20 IST Kite snapshot's chosen legs for this entry, or None."""
    q = read_sql("SELECT option_type, strike, bid, ask, last, basket_margin FROM option_live_quotes "
                 "WHERE underlying = ? AND trade_date = ? AND expiry = ? AND chosen = 1",
                 params=[underlying, t, expiry])
    if len(q) != 2:
        return None
    return {r.option_type: r for r in q.itertuples()}


def open_trade(underlying, t, expiry):
    """The rule's trade at the close of t, as a row dict, or None when the chain lacks it."""
    sl = _chain(underlying, t, expiry)
    if sl.empty:
        return None
    sl["strike"] = sl["strike"].astype(float)
    d = slice_deltas(sl, t, expiry)
    if d is None:
        return None
    F, deltas = d
    k = nearest(deltas, RULE["delta"])
    px = {(("C" if o == "CE" else "P"), s): v for o, s, v in zip(sl.option_type, sl.strike, sl.settle)}
    lot = lot_size(underlying, t)
    call, put = px[("C", k["C"])], px[("P", k["P"])]
    row = {"rule_id": RULE["id"], "underlying": underlying, "expiry": expiry, "entry_date": t,
           "forward": F, "lot": lot, "short_call": k["C"], "short_put": k["P"],
           "call_entry": call, "put_entry": put, "credit_pts": call + put,
           "entry_cost_pts": leg_cost(call, "sell", lot, SLIP, t) + leg_cost(put, "sell", lot, SLIP, t),
           "margin_rs": MARGIN_STRANGLE_PCT * F * lot, "margin_source": "12pct", "status": "OPEN",
           "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    live = _live(underlying, t, expiry)
    if live is not None:
        row.update({"live_call_strike": live["CE"].strike, "live_put_strike": live["PE"].strike,
                    "live_call_bid": live["CE"].bid, "live_put_bid": live["PE"].bid,
                    "live_credit_pts": (live["CE"].bid or 0) + (live["PE"].bid or 0)})
        if live["CE"].basket_margin:
            row.update({"margin_rs": float(live["CE"].basket_margin), "margin_source": "kite"})
    return row


def settle_trade(tr, S):
    """Settle an open trade at index settlement S (cash-settled, no closing trade)."""
    call_exit, put_exit = intrinsic("C", tr["short_call"], S), intrinsic("P", tr["short_put"], S)
    gross = tr["credit_pts"] - call_exit - put_exit
    net = gross - tr["entry_cost_pts"]
    return {"rule_id": tr["rule_id"], "underlying": tr["underlying"], "expiry": tr["expiry"],
            "status": "SETTLED", "settle_index": S, "call_exit": call_exit, "put_exit": put_exit,
            "gross_pts": gross, "net_pts": net, "net_rs": net * tr["lot"],
            "ret_on_margin": net * tr["lot"] / tr["margin_rs"],
            "settled_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def record(today=None):
    """Write every entry day whose close is loaded, settle every trade whose expiry is loaded.
    Raises when an entry day's chain is loaded but the rule cannot be applied to it."""
    import runlog
    hol = holidays()
    have = read_sql("SELECT underlying, expiry, status FROM option_paper_trades WHERE rule_id = ?",
                    params=[RULE["id"]])
    done = {(u, e) for u, e in zip(have.underlying, have.expiry)}
    new, settled, missing = [], [], []
    for u in RULE["underlyings"]:
        last = read_sql("SELECT MAX(trade_date) AS d FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO'",
                        params=[u])["d"].iloc[0]
        if not last:
            continue
        exps = read_sql("SELECT DISTINCT expiry_date FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                        "AND trade_date >= ?", params=[u, FIRST_ENTRY])["expiry_date"]
        for e in sorted(exps):
            t = entry_day(e, hol)
            if t < FIRST_ENTRY or t > last or (u, e) in done:
                continue
            front = read_sql("SELECT MIN(expiry_date) AS e FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                             "AND trade_date = ? AND expiry_date > ?", params=[u, t, t])["e"].iloc[0]
            if front != e:                         # the rule trades the front weekly only
                continue
            row = open_trade(u, t, e)
            if row is None:
                missing.append(f"{u} {e} (entry {t})")
                runlog.item_failed("option_book", f"{u} {e}", f"no usable chain on entry day {t}")
                continue
            new.append(row)
    if new:
        upsert_df(pd.DataFrame(new), "option_paper_trades")
    opened = read_sql("SELECT * FROM option_paper_trades WHERE rule_id = ? AND status = 'OPEN'", params=[RULE["id"]])
    for tr in opened.to_dict("records"):
        s = read_sql("SELECT MAX(underlying_price) AS s FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                     "AND trade_date = ? AND expiry_date = ?", params=[tr["underlying"], tr["expiry"], tr["expiry"]])["s"].iloc[0]
        if s:
            settled.append(settle_trade(tr, float(s)))
    if settled:
        upsert_df(pd.DataFrame(settled), "option_paper_trades")
    print(f"option_book: {len(new)} opened, {len(settled)} settled, {len(missing)} missing")
    for row in new:
        print(f"  OPEN  {row['underlying']} {row['expiry']}: sell {row['short_call']:.0f} CE {row['call_entry']} "
              f"+ {row['short_put']:.0f} PE {row['put_entry']} = {row['credit_pts']:.2f} pts × {row['lot']} "
              f"(margin ₹{row['margin_rs']:,.0f}, {row['margin_source']})")
    for row in settled:
        print(f"  SETTLED {row['underlying']} {row['expiry']}: index {row['settle_index']:.2f} → "
              f"net {row['net_pts']:+.2f} pts = ₹{row['net_rs']:+,.0f} ({100 * row['ret_on_margin']:+.2f}% of margin)")
    if missing:
        raise RuntimeError(f"option_book: entry day loaded but no usable chain for {', '.join(missing)}")
    return len(new), len(settled)


def book():
    """The book with open trades marked at the latest settle (for the page and --show)."""
    tr = read_sql("SELECT * FROM option_paper_trades WHERE rule_id = ? ORDER BY entry_date, underlying",
                  params=[RULE["id"]])
    marks = []
    for r in tr.itertuples():
        if r.status != "OPEN":
            marks.append(None)
            continue
        m = read_sql("SELECT trade_date, option_type, strike, settle, underlying_price FROM fno_bhav "
                     "WHERE symbol = ? AND instrument_type = 'IDO' AND expiry_date = ? AND trade_date = "
                     "(SELECT MAX(trade_date) FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' AND expiry_date = ?) "
                     "AND ((option_type = 'CE' AND strike = ?) OR (option_type = 'PE' AND strike = ?))",
                     params=[r.underlying, r.expiry, r.underlying, r.expiry, r.short_call, r.short_put])
        if len(m) == 2:
            now = m.settle.sum()
            marks.append({"mark_date": m.trade_date.iloc[0], "index": float(m.underlying_price.iloc[0]),
                          "mtm_rs": (r.credit_pts - now - r.entry_cost_pts) * r.lot})
        else:
            marks.append(None)
    tr["mark"] = marks
    return tr


# Backtest reference for the page (study, real prices; % of margin per trade).
BACKTEST = {"NIFTY": {"window": "2019-02 → 2026-10", "trades": 378, "mean_pct": 0.49, "worst_pct": -8.9},
            "SENSEX": {"window": "2024-01 → 2026-10", "trades": 142, "mean_pct": 0.38, "worst_pct": -7.6}}
PASS_BAR_TRADES = 25


def page_data():
    """Everything the /options page shows (plan 0022). The page renders this, decides nothing."""
    from sources.kite_pull import TOKEN_CACHE
    import json
    b = book()
    trades = []
    for r in b.to_dict("records"):
        r = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()}
        trades.append(r)
    settled = [t for t in trades if t["status"] == "SETTLED"]
    rets = [t["ret_on_margin"] for t in settled]
    slips = []
    for t in trades:
        if t.get("live_credit_pts") is not None and t["live_call_strike"] == t["short_call"] \
                and t["live_put_strike"] == t["short_put"] and t["credit_pts"]:
            slips.append((t["credit_pts"] - t["live_credit_pts"]) / t["credit_pts"])
    try:
        with open(TOKEN_CACHE) as f:
            kite_day = json.load(f).get("date")
    except (OSError, ValueError):
        kite_day = None
    hol = holidays()
    upcoming = []
    today = date.today().isoformat()
    for u in RULE["underlyings"]:
        exps = read_sql("SELECT DISTINCT expiry_date FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                        "AND expiry_date > ? AND trade_date = (SELECT MAX(trade_date) FROM fno_bhav WHERE symbol = ? "
                        "AND instrument_type = 'IDO') ORDER BY expiry_date", params=[u, today, u])["expiry_date"]
        for e in exps:
            if entry_day(e, hol) >= today:
                upcoming.append({"underlying": u, "expiry": e, "entry": entry_day(e, hol)})
                break
    return {
        "rule": RULE, "first_entry": FIRST_ENTRY, "backtest": BACKTEST, "pass_bar_trades": PASS_BAR_TRADES,
        "trades": trades[::-1],
        "summary": {"n": len(trades), "open": len(trades) - len(settled), "settled": len(settled),
                    "wins": sum(1 for x in rets if x > 0),
                    "net_rs": sum(t["net_rs"] or 0 for t in settled),
                    "mean_pct": 100 * float(np.mean(rets)) if rets else None,
                    "worst_pct": 100 * min(rets) if rets else None,
                    "slip_median_pct": 100 * float(np.median(slips)) if slips else None, "n_slip": len(slips)},
        "kite": {"logged_in_today": kite_day == date.today().isoformat(), "last_login_day": kite_day},
        "upcoming": sorted(upcoming, key=lambda x: x["entry"]),
    }


def main():
    ap = argparse.ArgumentParser(description="Option-premium paper book (plan 0022)")
    ap.add_argument("--record", action="store_true", help="write new entry days and settle expired trades")
    ap.add_argument("--show", action="store_true", help="print the book")
    a = ap.parse_args()
    if a.record:
        record()
    if a.show or not a.record:
        b = book()
        pd.set_option("display.width", 200, "display.max_columns", 30)
        print(b[["underlying", "entry_date", "expiry", "short_call", "short_put", "credit_pts", "lot",
                 "margin_rs", "status", "settle_index", "net_rs", "ret_on_margin", "mark"]].to_string(index=False))


if __name__ == "__main__":
    main()
