"""
Alpha Signal v2 — Amit's actual Zerodha holdings, snapshotted from Kite for the cockpit /book page.

The model book (portfolio_weights) is on paper. This records what the demat account really
holds, so /book can set the two side by side. Read-only: one `holdings()` call, never an order.

A Kite session exists only on days Amit logs in (the token expires ~06:00 IST and is renewed by
hand, plan 0022), so the snapshot is taken when one exists: at the login itself (ops cockpit
/kite/callback) and after the close by cron. A day without a login is not a failure: the page
shows the last snapshot with its date.

Writes broker_holdings: one row per holding per snapshot day. A re-snapshot replaces that day's
rows (a stock sold since the morning drops out). sid is the universe stock with that NSE ticker;
ETFs and gold bonds have none (the universe excludes them).

Writes broker_instrument_prices: daily closes of those non-universe holdings from Kite day candles
(a year back on first sight, then from the last stored day), so /book can value the whole real
book over the past year. Universe stocks need none: stock_prices has them, adjusted.

Usage:
    python -m sources.kite_holdings          # cron 10:15 UTC weekdays (15:45 IST)
"""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import runlog
from db import get_db, insert_df, read_sql, upsert_df
from sources import _http

IST = ZoneInfo("Asia/Kolkata")
BROKER = "zerodha"
HISTORY_DAYS = 400       # first fetch: a year of trading days plus the year-start base


def rows_from_holdings(holdings, ticker_sid, as_of, snapshot_at):
    """Kite `holdings()` records → broker_holdings rows (pure; tested)."""
    out = []
    for h in holdings:
        qty = int(h.get("quantity") or 0) + int(h.get("t1_quantity") or 0)
        if qty <= 0:
            continue
        out.append({
            "as_of_date": as_of, "broker": BROKER, "tradingsymbol": h["tradingsymbol"],
            "exchange": h.get("exchange"), "isin": h.get("isin"), "sid": ticker_sid.get(h["tradingsymbol"]),
            "quantity": qty, "t1_quantity": int(h.get("t1_quantity") or 0),
            "average_price": h.get("average_price"), "last_price": h.get("last_price"),
            "close_price": h.get("close_price"), "day_change_pct": h.get("day_change_percentage"),
            "pnl": h.get("pnl"), "snapshot_at": snapshot_at,
        })
    return pd.DataFrame(out)


def holdings(kc):
    """The account's holdings: one read-only Kite call."""
    with _http.pace("kite"):
        return kc.holdings()


def snapshot(holdings):
    """Replace today's snapshot with Kite `holdings()` records. Returns rows written."""
    now = datetime.now(IST)
    tick = read_sql("SELECT ticker, sid FROM stocks WHERE ticker IS NOT NULL")
    df = rows_from_holdings(holdings, dict(zip(tick["ticker"], tick["sid"])), now.date().isoformat(),
                            datetime.now(timezone.utc).isoformat(timespec="seconds"))
    if df.empty:
        raise RuntimeError("Kite returned no holdings — refusing to blank the book")
    with get_db() as conn:                   # one transaction: the day's rows are swapped, never half-written
        conn.execute("DELETE FROM broker_holdings WHERE as_of_date = ? AND broker = ?", (df["as_of_date"].iloc[0], BROKER))
        n = insert_df(df, "broker_holdings", conn=conn)
    value = (df["quantity"] * df["last_price"]).sum()
    print(f"kite_holdings {df['as_of_date'].iloc[0]}: {n} holdings, value ₹{value:,.0f} "
          f"({df['sid'].notna().sum()} in the universe)")
    return n


def candle_rows(candles, tradingsymbol, exchange, fetched_at):
    """Kite day candles → broker_instrument_prices rows (pure; tested)."""
    return pd.DataFrame([{"tradingsymbol": tradingsymbol, "date": str(c["date"])[:10], "exchange": exchange,
                          "close": float(c["close"]), "fetched_at": fetched_at} for c in candles if c.get("close")])


def fetch_history(kc, holdings):
    """Day closes for the non-universe holdings (sid None), from the day after the last stored one.
    holdings: Kite `holdings()` records with an instrument_token. Returns rows written."""
    tick = set(read_sql("SELECT ticker FROM stocks WHERE ticker IS NOT NULL")["ticker"])
    last = dict(read_sql("SELECT tradingsymbol, MAX(date) AS d FROM broker_instrument_prices GROUP BY 1").values)
    today, now = date.today(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    n, failed = 0, []
    for h in holdings:
        sym = h["tradingsymbol"]
        if sym in tick or not h.get("instrument_token"):
            continue
        start = date.fromisoformat(last[sym]) + timedelta(days=1) if sym in last else today - timedelta(days=HISTORY_DAYS)
        if start > today:
            continue
        try:
            with _http.pace("kite"):
                candles = kc.historical_data(h["instrument_token"], start.isoformat(), today.isoformat(), "day")
            df = candle_rows(candles, sym, h.get("exchange"), now)
            if not df.empty:
                n += upsert_df(df, "broker_instrument_prices")
        except Exception as e:                   # noqa: BLE001 — recorded in run_events, raised below
            runlog.item_error("kite_holdings", sym, e)
            failed.append(sym)
    print(f"kite_holdings: {n} day closes for holdings outside the universe")
    if failed:
        raise RuntimeError(f"Kite day candles failed for {', '.join(failed)}")
    return n


def run():
    from sources.kite_pull import NoKiteSession, kite
    try:
        kc = kite(cached_only=True)
    except NoKiteSession:
        last = read_sql("SELECT MAX(as_of_date) AS d FROM broker_holdings")["d"].iloc[0]
        print(f"kite_holdings: no Kite login today; /book keeps the snapshot of {last}")
        return 0
    h = holdings(kc)
    n = snapshot(h)
    fetch_history(kc, h)
    return n


if __name__ == "__main__":
    run()
