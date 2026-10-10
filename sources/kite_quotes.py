"""
Alpha Signal v2 — live option quotes from Kite at 15:20 IST on paper-book entry days (plan 0022).

The paper book (option_book.py) prices its trades at the exchange settle. This snapshot
records what the same rule would see live 10 minutes before the close: the strikes it
would pick from live mids, their bid/ask/last, and Kite's basket margin for the
strangle. Settle minus live bid is the slippage the backtest assumed at 1%.

Runs only on an entry day (2 sessions before the front weekly expiry, from the stored
chain + market_holidays), so a Kite login is needed only on those days (about 2 a week).
Without one it fails loudly (NoKiteSession → exit 1 → FAILED in pipeline_log) with the
login link. Read-only on the account: quotes and a margin query, never an order.

Writes option_live_quotes: every quoted strike within the band, `chosen = 1` on the two
legs the rule picks (those carry the basket margin).

Usage:
    python -m sources.kite_quotes            # cron 09:50 UTC on weekdays
    python -m sources.kite_quotes --force    # snapshot even if today is not an entry day
"""

import argparse
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import option_book as ob
from db import insert_df, read_sql
from sources import _http

IST = ZoneInfo("Asia/Kolkata")
MARKETS = (("NIFTY", "NFO", "NSE:NIFTY 50"), ("SENSEX", "BFO", "BSE:SENSEX"))


def front_expiry(underlying, today):
    """The nearest stored weekly expiry after `today` (from the last loaded chain)."""
    e = read_sql("SELECT MIN(expiry_date) AS e FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                 "AND expiry_date > ? AND trade_date = (SELECT MAX(trade_date) FROM fno_bhav "
                 "WHERE symbol = ? AND instrument_type = 'IDO')", params=[underlying, today, underlying])["e"].iloc[0]
    return e


def snapshot_one(kc, underlying, exch, spot_key, today, expiry):
    """Quote the band around spot for `expiry`, pick the rule's strikes, query margin → rows."""
    with _http.pace("kite"):
        ins = pd.DataFrame(kc.instruments(exch))
    ins = ins[(ins["name"] == underlying) & ins["instrument_type"].isin(["CE", "PE"])]
    ins = ins[ins["expiry"].astype(str) == expiry]
    if ins.empty:
        raise RuntimeError(f"{underlying}: Kite lists no options for expiry {expiry}")
    with _http.pace("kite"):
        spot = kc.ltp([spot_key])[spot_key]["last_price"]
    ins = ins[(ins["strike"] - spot).abs() <= ob.STRIKE_BAND * spot]
    keys = [f"{exch}:{t}" for t in ins["tradingsymbol"]]
    quotes = {}
    for i in range(0, len(keys), 200):
        with _http.pace("kite"):
            quotes.update(kc.quote(keys[i:i + 200]))
    rows = []
    for r in ins.itertuples():
        q = quotes.get(f"{exch}:{r.tradingsymbol}")
        if not q:
            continue
        depth = q.get("depth") or {}
        bid = (depth.get("buy") or [{}])[0].get("price") or None
        ask = (depth.get("sell") or [{}])[0].get("price") or None
        last = q.get("last_price")
        mid = (bid + ask) / 2 if bid and ask else last
        rows.append({"tradingsymbol": r.tradingsymbol, "option_type": r.instrument_type, "strike": float(r.strike),
                     "bid": bid, "ask": ask, "last": last, "mid": mid, "oi": q.get("oi"),
                     "volume": q.get("volume") or 0, "lot": int(r.lot_size)})
    df = pd.DataFrame(rows)
    sl = df.rename(columns={"mid": "settle"})[["option_type", "strike", "settle", "volume"]]
    d = ob.slice_deltas(sl, today, expiry)
    if d is None:
        raise RuntimeError(f"{underlying} {expiry}: live chain gave no usable deltas")
    F, deltas = d
    k = ob.nearest(deltas, ob.RULE["delta"])
    dmap = {(cp, K): dl for cp in ("C", "P") for dl, K in deltas[cp]}
    df["delta"] = [dmap.get(("C" if o == "CE" else "P", s)) for o, s in zip(df.option_type, df.strike)]
    df["chosen"] = [int((o == "CE" and s == k["C"]) or (o == "PE" and s == k["P"]))
                    for o, s in zip(df.option_type, df.strike)]
    legs = df[df.chosen == 1]
    orders = [{"exchange": exch, "tradingsymbol": t, "transaction_type": "SELL", "variety": "regular",
               "product": "NRML", "order_type": "MARKET", "quantity": int(n), "price": 0, "trigger_price": 0}
              for t, n in zip(legs.tradingsymbol, legs.lot)]
    with _http.pace("kite"):
        m = kc.basket_order_margins(orders, consider_positions=False, mode="compact")
    margin = (m.get("final") or m.get("initial") or {}).get("total")
    df["basket_margin"] = [margin if c else None for c in df.chosen]
    df["trade_date"], df["underlying"], df["expiry"], df["spot"] = today, underlying, expiry, spot
    df["snapshot_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return df.drop(columns=["mid", "lot"]), legs, margin, spot


def run(force=False):
    from sources.kite_pull import kite
    now = datetime.now(IST)
    today = now.date().isoformat()
    hol = ob.holidays()
    if not ob.is_session(now.date(), hol):
        print(f"kite_quotes {today}: not a trading session")
        return 0
    due = []
    for underlying, exch, spot_key in MARKETS:
        e = front_expiry(underlying, today)
        if e and (force or ob.entry_day(e, hol) == today):
            due.append((underlying, exch, spot_key, e))
    if not due:
        print(f"kite_quotes {today}: not an entry day for {', '.join(m[0] for m in MARKETS)}")
        return 0
    kc = kite(cached_only=True)                    # NoKiteSession → exit 1 with the login link
    total = 0
    for underlying, exch, spot_key, e in due:
        df, legs, margin, spot = snapshot_one(kc, underlying, exch, spot_key, today, e)
        total += insert_df(df, "option_live_quotes")
        legs_txt = " + ".join(f"{t} bid {b} ask {a}" for t, b, a in zip(legs.tradingsymbol, legs.bid, legs.ask))
        print(f"kite_quotes {underlying} {e} (spot {spot:,.2f}): {len(df)} strikes · sell {legs_txt} · "
              f"Kite margin ₹{margin:,.0f}")
    return total


def main():
    ap = argparse.ArgumentParser(description="Kite live option quotes on paper-book entry days")
    ap.add_argument("--force", action="store_true", help="snapshot even if today is not an entry day")
    run(ap.parse_args().force)


if __name__ == "__main__":
    main()
