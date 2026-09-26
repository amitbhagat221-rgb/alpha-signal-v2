"""
Alpha Signal v2 — Unified pulls via nselib + NSE direct cookie session.

One module, one set of helper functions, all the new sources from the
2026-05-03 discovery probe (see docs/reference/data-playbook.md):

  - nselib.capital_market.bulk_deal_data        (3+ years history)
  - nselib.capital_market.short_selling_data    (Jan 2024+)
  - nselib.capital_market.corporate_actions_for_equity   (2+ years)
  - nselib.derivatives.participant_wise_open_interest    (Dec 2025+)
  - NSE direct: fiidiiTradeReact                (cash flow, today's row)

MF NAV is NOT here: sources.mf_nav_daily (AMFI, daily) + sources.mf_nav_backfill
(mfapi.in history) own mf_nav_history / mf_schemes. The old `--source mf_nav`
(14 hand-listed codes, 2 of them duplicates) raced mf_nav_backfill's mf_schemes
upsert and was retired 2026-09-26.

All ingests:
  • Chunk long ranges by month (NSE rate limits + API timeouts)
  • 2-second floor between calls (NSE rule)
  • UNIQUE constraint on target tables → INSERT OR IGNORE for idempotency
  • Append per chunk → progress survives crashes mid-backfill

Usage:
    python -m sources.nselib_pull --source bulk      --months 12
    python -m sources.nselib_pull --source corp      --months 24
    python -m sources.nselib_pull --source short     --months 24
    python -m sources.nselib_pull --source fii_pos   # latest available (~5mo)
    python -m sources.nselib_pull --source fii_cash  # today's row (forward only)
    python -m sources.nselib_pull --source all       # everything (long-running)

    # Deep backfill (what sources/historical_backfill.py did, now archived):
    python -m sources.nselib_pull --source bulk    --start 2021-01-01
    python -m sources.nselib_pull --source short   --start 2022-01-01
    python -m sources.nselib_pull --source fii_pos --start 2022-01-01   # skips loaded dates
"""

import argparse
import time
from datetime import date, timedelta

import pandas as pd

from config import API
from db import get_db, insert_df, read_sql
from sources import _http

DELAY_SEC = 2.0  # NSE 2-second floor

NSE_HOME = "https://www.nseindia.com"
NSE_JSON_HEADERS = {"User-Agent": API["user_agent"], "Accept": "application/json"}


def _months_back(n_months):
    """Return list of (from_date, to_date) tuples covering N months back, monthly chunks."""
    today = date.today()
    chunks = []
    cursor = today
    for _ in range(n_months):
        end = cursor
        start = (end.replace(day=1) - timedelta(days=1)).replace(day=1)
        if start.month == cursor.month and start.year == cursor.year:
            start = cursor.replace(day=1)
        # Use the first of the chunk's month for `start`
        chunk_start = end.replace(day=1)
        chunks.append((chunk_start, end))
        cursor = chunk_start - timedelta(days=1)
    return list(reversed(chunks))


def _months_since(start):
    """Month count for _months_back() so its first chunk starts in `start`'s month."""
    today = date.today()
    return (today.year - start.year) * 12 + today.month - start.month + 1


def _insert_or_ignore(df, table):
    """INSERT OR IGNORE *without* db.insert_df's future-date guard. Only for the
    forward-dated earnings_calendar: its `date` column runs to today+30d, and
    insert_df drops rows dated > today+2d. Every other table uses insert_df."""
    if df.empty:
        return 0
    cols = list(df.columns)
    placeholders = ", ".join(["?"] * len(cols))
    sql = f"INSERT OR IGNORE INTO [{table}] ({', '.join(cols)}) VALUES ({placeholders})"
    with get_db() as conn:
        cur = conn.executemany(sql, df.values.tolist())
        return cur.rowcount


# ───────────────────────── Move 1: bulk deals backfill ─────────────────────────

def pull_bulk_deals(months=12):
    from nselib import capital_market as cm
    sid_map = _http.sid_map()
    chunks = _months_back(months)
    total = 0

    for start, end in chunks:
        from_str = start.strftime("%d-%m-%Y")
        to_str = end.strftime("%d-%m-%Y")
        try:
            df = cm.bulk_deal_data(from_date=from_str, to_date=to_str)
        except Exception as e:
            print(f"  bulk {from_str}→{to_str}: ❌ {str(e)[:100]}")
            time.sleep(DELAY_SEC)
            continue

        if df is None or df.empty:
            print(f"  bulk {from_str}→{to_str}: empty")
            time.sleep(DELAY_SEC)
            continue

        # Normalize columns to bulk_deals schema
        df.columns = [c.strip() for c in df.columns]
        out_rows = []
        for _, r in df.iterrows():
            sym = str(r.get("Symbol", "")).strip()
            sid = sid_map.get(sym)
            if not sid:
                continue
            qty = r.get("QuantityTraded", 0)
            try:
                qty = float(str(qty).replace(",", ""))
            except Exception:
                qty = 0
            # nselib's column is 'TradePrice/Wght.Avg.Price' (constants.bulk_deal_data_columns).
            # The old spaced spelling never matched → price=0 on all 12.8K rows this
            # wrote for 2025-26; historical_backfill (archived) had it right.
            price = r.get("TradePrice/Wght.Avg.Price", 0) or r.get("TradePrice / Wght. Avg.Price", 0)
            try:
                price = float(str(price).replace(",", ""))
            except Exception:
                price = 0
            deal_date_raw = str(r.get("Date", "")).strip()
            # Format: "01-APR-2026" → "2026-04-01"
            try:
                deal_date = pd.to_datetime(deal_date_raw, format="%d-%b-%Y").date().isoformat()
            except Exception:
                try:
                    deal_date = pd.to_datetime(deal_date_raw).date().isoformat()
                except Exception:
                    continue
            buy_sell = str(r.get("Buy/Sell", "")).strip().upper()
            client = str(r.get("ClientName", "")).strip()[:200]

            out_rows.append({
                "sid": sid, "symbol": sym, "client_name": client,
                "deal_type": "bulk", "buy_sell": buy_sell,
                "quantity": qty, "price": price, "deal_date": deal_date,
            })

        if out_rows:
            df_out = pd.DataFrame(out_rows)
            n = insert_df(df_out, "bulk_deals")
            total += n
            print(f"  bulk {from_str}→{to_str}: ✅ {len(out_rows)} parsed → {n} new rows")
        else:
            print(f"  bulk {from_str}→{to_str}: 0 valid rows")

        time.sleep(DELAY_SEC)
    return total


# ───────────────────────── Move 2: corporate actions ─────────────────────────

def pull_corporate_actions(months=24):
    from nselib import capital_market as cm
    sid_map = _http.sid_map()
    chunks = _months_back(months)
    total = 0
    n_ok = 0       # chunks where NSE returned a (possibly empty) frame
    n_err = 0      # chunks where the NSE call threw
    for start, end in chunks:
        from_str = start.strftime("%d-%m-%Y")
        to_str = end.strftime("%d-%m-%Y")
        try:
            df = cm.corporate_actions_for_equity(from_date=from_str, to_date=to_str)
            n_ok += 1
        except Exception as e:
            n_err += 1
            print(f"  corp {from_str}→{to_str}: ❌ {str(e)[:100]}")
            time.sleep(DELAY_SEC)
            continue
        if df is None or df.empty:
            time.sleep(DELAY_SEC)
            continue

        df.columns = [c.strip() for c in df.columns]
        out_rows = []
        for _, r in df.iterrows():
            sym = str(r.get("symbol", "")).strip()
            sid = sid_map.get(sym)
            ex_raw = str(r.get("exDate", "")).strip()
            try:
                ex_date = pd.to_datetime(ex_raw, format="%d-%b-%Y").date().isoformat()
            except Exception:
                try:
                    ex_date = pd.to_datetime(ex_raw).date().isoformat()
                except Exception:
                    continue

            subject = str(r.get("subject", "")).strip()[:300]
            # Classify
            sl = subject.lower()
            ind = (
                "SPLIT" if "split" in sl else
                "BONUS" if "bonus" in sl else
                "RIGHTS" if "right" in sl else
                "BUYBACK" if "buy" in sl and "back" in sl else
                "DIVIDEND" if "dividend" in sl else
                "OTHER"
            )
            try:
                fv = float(r.get("faceVal", 0) or 0)
            except Exception:
                fv = None

            out_rows.append({
                "sid": sid, "symbol": sym, "series": str(r.get("series", "")).strip(),
                "ind": ind, "face_value": fv, "subject": subject, "ex_date": ex_date,
            })

        if out_rows:
            n = insert_df(pd.DataFrame(out_rows), "corporate_actions")
            total += n
            print(f"  corp {from_str}→{to_str}: ✅ {len(out_rows)} parsed → {n} new")
        time.sleep(DELAY_SEC)

    # Silent-failure contract (CLAUDE.md): 0 NEW rows is normal (idempotent
    # INSERT OR IGNORE), but every chunk erroring means NSE was unreachable —
    # raise so the watchdog sees a real stall, not a flat fetched_at.
    if chunks and n_ok == 0:
        raise RuntimeError(
            f"corporate_actions: all {n_err} NSE chunks failed — endpoint unreachable"
        )
    return total


def compute_corp_actions(months=2):
    """Daily pipeline producer — refresh corporate_actions over a short
    trailing window (default 2 months, ~2 NSE calls) so Gate 3 temporal
    continuity can distinguish real splits/bonuses/special-dividends from
    sourcing artifacts via the corporate_actions escape hatch
    (validators.temporal_continuity._has_recent_corp_action).

    Short window keeps it cheap for daily cadence; INSERT OR IGNORE makes it
    idempotent. The monthly `--source corp --months 24` deep backfill still
    exists for first-load / gap repair. Returns rows newly inserted."""
    return pull_corporate_actions(months=months)


# ───────────────────────── Move 3: short selling ─────────────────────────

def pull_short_selling(months=24):
    from nselib import capital_market as cm
    sid_map = _http.sid_map()
    chunks = _months_back(months)
    total = 0
    for start, end in chunks:
        from_str = start.strftime("%d-%m-%Y")
        to_str = end.strftime("%d-%m-%Y")
        try:
            df = cm.short_selling_data(from_date=from_str, to_date=to_str)
        except Exception as e:
            print(f"  short {from_str}→{to_str}: ❌ {str(e)[:100]}")
            time.sleep(DELAY_SEC)
            continue
        if df is None or df.empty:
            time.sleep(DELAY_SEC)
            continue

        df.columns = [c.strip() for c in df.columns]
        out_rows = []
        for _, r in df.iterrows():
            sym = str(r.get("Symbol", "")).strip()
            sid = sid_map.get(sym)
            d_raw = str(r.get("Date", "")).strip()
            try:
                short_date = pd.to_datetime(d_raw, format="%d-%b-%Y").date().isoformat()
            except Exception:
                try:
                    short_date = pd.to_datetime(d_raw).date().isoformat()
                except Exception:
                    continue
            try:
                qty = float(str(r.get("Quantity", 0)).replace(",", ""))
            except Exception:
                qty = None
            out_rows.append({
                "sid": sid, "symbol": sym, "short_date": short_date, "quantity": qty,
            })

        if out_rows:
            n = insert_df(pd.DataFrame(out_rows), "short_selling_data")
            total += n
            print(f"  short {from_str}→{to_str}: ✅ {len(out_rows)} parsed → {n} new")
        time.sleep(DELAY_SEC)
    return total


# ───────────────────────── Move 3b: board-meeting / events calendar ─────────────────────────

def pull_event_calendar(days_back=3, days_forward=30):
    """Pull the NSE board-meeting / corporate-events calendar → earnings_calendar.

    `cm.event_calendar_for_equity(from_date, to_date)` returns the whole-market
    forthcoming-events frame (symbol, company, purpose, bm_desc, date) in one
    call — small enough not to chunk. We fetch a window that straddles today so
    the cockpit's "upcoming earnings" widget (date >= now, +14d) has runway,
    plus a few days back for just-passed meetings.

    earnings_calendar is forward-dated by nature, so a single daily run keeps it
    fresh; INSERT OR IGNORE on UNIQUE(symbol, date) makes re-runs idempotent and
    tolerates a meeting that gets rescheduled to a new date (lands as a new row).
    """
    from nselib import capital_market as cm
    sid_map = _http.sid_map()
    start = date.today() - timedelta(days=days_back)
    end = date.today() + timedelta(days=days_forward)
    from_str = start.strftime("%d-%m-%Y")
    to_str = end.strftime("%d-%m-%Y")

    try:
        df = cm.event_calendar_for_equity(from_date=from_str, to_date=to_str)
    except Exception as e:
        # Silent-failure contract (CLAUDE.md): the single call erroring means NSE
        # was unreachable — raise so the watchdog sees a real stall, not a flat
        # added_date. (0 parsed rows over a quiet window is handled below.)
        raise RuntimeError(
            f"event_calendar: NSE call {from_str}→{to_str} failed — {str(e)[:120]}"
        )

    if df is None or df.empty:
        print(f"  events {from_str}→{to_str}: 0 rows (quiet window)")
        return 0

    df.columns = [c.strip() for c in df.columns]
    today_iso = date.today().isoformat()
    out_rows = []
    for _, r in df.iterrows():
        sym = str(r.get("symbol", "")).strip()
        sid = sid_map.get(sym)
        if not sid:
            continue  # skip symbols outside our universe (FK is NOT NULL)
        d_raw = str(r.get("date", "")).strip()
        try:
            ev_date = pd.to_datetime(d_raw, format="%d-%b-%Y").date().isoformat()
        except Exception:
            try:
                ev_date = pd.to_datetime(d_raw).date().isoformat()
            except Exception:
                continue
        out_rows.append({
            "date": ev_date, "symbol": sym, "sid": sid,
            "company": str(r.get("company", "")).strip()[:100],
            "purpose": str(r.get("purpose", "")).strip(),
            "bm_desc": str(r.get("bm_desc", "")).strip(),
            "added_date": today_iso,
        })

    n = _insert_or_ignore(pd.DataFrame(out_rows), "earnings_calendar") if out_rows else 0
    print(f"  events {from_str}→{to_str}: ✅ {len(out_rows)} parsed → {n} new")
    return n


def compute_earnings_calendar(days_forward=30):
    """Daily pipeline producer — refresh the upcoming board-meeting calendar.

    One NSE call over [today-3d, today+30d]. Forward-dated rows keep the table
    fresh and feed the cockpit's upcoming-events widget. Idempotent."""
    return pull_event_calendar(days_back=3, days_forward=days_forward)


# ───────────────────────── Move 4a: FII/DII F&O positioning ─────────────────────────

def pull_fii_positioning(days_back=180):
    """Pull participant_wise_open_interest day by day.

    Endpoint accepts only single trade_date. Archive reaches back to 2022 (backfilled
    via `--start`). Skips weekends, "no data" days (typical NSE holidays) and dates
    already loaded — so a deep `--start` backfill is re-runnable.
    """
    from nselib import derivatives as dv
    today = date.today()
    total = 0
    dates_tried = 0
    have = set(read_sql("SELECT DISTINCT trade_date FROM fii_dii_positioning")["trade_date"])

    for delta in range(days_back):
        d = today - timedelta(days=delta)
        if d.weekday() >= 5 or d.isoformat() in have:  # Sat/Sun or already loaded
            continue
        d_str = d.strftime("%d-%m-%Y")
        try:
            df = dv.participant_wise_open_interest(trade_date=d_str)
        except Exception as e:
            # "No data available" is normal for non-trading days
            time.sleep(DELAY_SEC)   # was DELAY_SEC * 0.5 = 1s (below the 2s floor)
            continue
        if df is None or df.empty:
            time.sleep(DELAY_SEC)
            continue

        df.columns = [c.strip() for c in df.columns]
        rename = {
            "Client Type": "client_type",
            "Future Index Long": "future_index_long",
            "Future Index Short": "future_index_short",
            "Future Stock Long": "future_stock_long",
            "Future Stock Short": "future_stock_short",
            "Option Index Call Long": "option_index_call_long",
            "Option Index Put Long": "option_index_put_long",
            "Option Index Call Short": "option_index_call_short",
            "Option Index Put Short": "option_index_put_short",
            "Option Stock Call Long": "option_stock_call_long",
            "Option Stock Put Long": "option_stock_put_long",
            "Option Stock Call Short": "option_stock_call_short",
            "Option Stock Put Short": "option_stock_put_short",
            "Total Long Contracts": "total_long",
            "Total Short Contracts": "total_short",
        }
        df = df.rename(columns=rename)
        df["trade_date"] = d.isoformat()
        valid_cols = ["trade_date", "client_type"] + [v for v in rename.values() if v != "client_type"]
        df = df[[c for c in valid_cols if c in df.columns]]
        n = insert_df(df, "fii_dii_positioning")
        total += n
        dates_tried += 1
        if dates_tried % 10 == 0:
            print(f"  fii_pos checkpoint: {dates_tried} dates, {total} rows so far")
        time.sleep(DELAY_SEC)
    return total


# ───────────────────────── Move 4b: FII/DII cash flow ─────────────────────────

def pull_fii_cash_flow():
    """Today's FII + DII cash-segment flow from www.nseindia.com/api/fiidiiTradeReact.

    Forward-only (single-day endpoint) — set up daily cron to accumulate.
    """
    s = _http.warm_session(NSE_HOME, headers=NSE_JSON_HEADERS)
    r = _http.polite_get("https://www.nseindia.com/api/fiidiiTradeReact", session=s)
    if r is None:
        raise RuntimeError("fiidiiTradeReact returned 404")
    data = r.json()

    rows = []
    for entry in data:
        try:
            d_raw = entry.get("date")  # "30-Apr-2026"
            flow_date = pd.to_datetime(d_raw, format="%d-%b-%Y").date().isoformat()
        except Exception:
            continue
        rows.append({
            "flow_date": flow_date,
            "category": entry.get("category", "").strip(),
            "buy_value_cr": float(entry.get("buyValue", 0) or 0),
            "sell_value_cr": float(entry.get("sellValue", 0) or 0),
            "net_value_cr": float(entry.get("netValue", 0) or 0),
        })
    if not rows:
        print("  fii_cash: empty response")
        return 0
    df = pd.DataFrame(rows)
    n = insert_df(df, "fii_dii_cash_flow")
    print(f"  fii_cash: ✅ {len(rows)} rows fetched → {n} new")
    return n


# ───────────────────────── Move 6: NSE Smart-Beta indices history ─────────────────────────

# v1 plan-validated factor benchmark indices.
# Names below match NSE's index master exactly (verified via cm.index_data probe).
SMART_BETA_INDICES = [
    "NIFTY ALPHA 50",                # Alpha factor benchmark
    "NIFTY100 ALPHA 30",
    "NIFTY200 ALPHA 30",
    "NIFTY100 LOW VOLATILITY 30",    # Low-vol factor
    "NIFTY ALPHA LOW-VOLATILITY 30",
    "NIFTY200 QUALITY 30",           # Quality factor
    "NIFTY100 EQUAL WEIGHT",         # Equal-weight benchmark
    "NIFTY200 VALUE 30",             # Value factor
    "NIFTY50 VALUE 20",
    "NIFTY 50",                      # Benchmark
    "NIFTY 500",
    "NIFTY MIDCAP 150",
    "NIFTY SMALLCAP 250",
]


def pull_nse_indices(months=120):  # 10 years default
    """Pull daily history for smart-beta + benchmark indices."""
    from nselib import capital_market as cm
    chunks = _months_back(months)
    total = 0
    for idx in SMART_BETA_INDICES:
        idx_total = 0
        for start, end in chunks:
            from_str = start.strftime("%d-%m-%Y")
            to_str = end.strftime("%d-%m-%Y")
            try:
                df = cm.index_data(index=idx, from_date=from_str, to_date=to_str)
            except Exception as e:
                # Some indices have shorter history — skip silently
                time.sleep(DELAY_SEC)
                continue
            if df is None or df.empty:
                time.sleep(DELAY_SEC)
                continue
            df.columns = [c.strip() for c in df.columns]

            rows = []
            for _, r in df.iterrows():
                d_raw = str(r.get("TIMESTAMP", "")).strip()
                try:
                    d = pd.to_datetime(d_raw, format="%d-%b-%Y").date().isoformat()
                except Exception:
                    try:
                        d = pd.to_datetime(d_raw).date().isoformat()
                    except Exception:
                        continue
                rows.append({
                    "index_symbol": idx,
                    "trade_date": d,
                    "open": r.get("OPEN_INDEX_VAL"),
                    "high": r.get("HIGH_INDEX_VAL"),
                    "low": r.get("LOW_INDEX_VAL"),
                    "close": r.get("CLOSE_INDEX_VAL"),
                    "volume": r.get("TRADED_QTY"),
                    "traded_value": r.get("TURN_OVER"),
                })

            if rows:
                # Coerce numeric strings
                df_out = pd.DataFrame(rows)
                for c in ["open", "high", "low", "close", "volume", "traded_value"]:
                    if c in df_out.columns:
                        df_out[c] = pd.to_numeric(df_out[c], errors="coerce")
                n = insert_df(df_out, "nse_index_history")
                idx_total += n
            time.sleep(DELAY_SEC)
        print(f"  {idx}: ✅ {idx_total} new rows")
        total += idx_total
    return total


def compute_nse_indices():
    """Daily PIPELINE_STEPS wrapper — keep nse_index_history fresh with a short
    rolling window (the 120-month default is a one-off backfill, not a daily
    fetch). INSERT OR IGNORE makes this idempotent, so 0 new rows on a non-
    trading day is expected — staleness is caught by the freshness watchdog
    (nse_index_history is now a pipeline-output table, so it's tracked), not by
    raising here. Benchmark history feeds pick_outcomes' excess returns."""
    return pull_nse_indices(months=2)


# ───────────────────────── Move 4 (extended): surveillance + F&O ban ─────────────────────────

def pull_surveillance_today():
    """Snapshot of NSE ASM (long-term + short-term), GSM, F&O ban — today only.

    All of these are forward-only (no historical archive). Run daily via cron.
    """
    s = _http.warm_session(NSE_HOME, headers=NSE_JSON_HEADERS)

    sid_map = _http.sid_map()
    today_str = date.today().isoformat()
    inserted = 0

    # ASM long-term + short-term
    try:
        r = _http.polite_get("https://www.nseindia.com/api/reportASM", session=s, timeout=20)
        d = r.json()
        for stage_key, flag_type in [("longterm", "ASM_LT"), ("shortterm", "ASM_ST")]:
            stage_data = d.get(stage_key, {}).get("data", [])
            rows = []
            for item in stage_data:
                sym = (item.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                rows.append({
                    "sid": sid_map.get(sym),
                    "symbol": sym,
                    "flag_type": flag_type,
                    "flag_date": today_str,
                    "stage": item.get("stage") or item.get("Stage", ""),
                    "reason": (item.get("longterm_indicator") or "")[:200],
                })
            if rows:
                n = insert_df(pd.DataFrame(rows), "surveillance_flags")
                inserted += n
                print(f"  ASM {stage_key}: {n} new rows")
    except Exception as e:
        print(f"  ASM: ❌ {str(e)[:100]}")

    # GSM
    try:
        r = _http.polite_get("https://www.nseindia.com/api/reportGSM", session=s, timeout=20)
        d = r.json()
        items = d if isinstance(d, list) else d.get("data", [])
        rows = []
        for item in items:
            sym = (item.get("symbol") or "").strip().upper()
            if not sym:
                continue
            rows.append({
                "sid": sid_map.get(sym),
                "symbol": sym,
                "flag_type": "GSM",
                "flag_date": today_str,
                "stage": item.get("gsmStage") or item.get("stage") or item.get("Stage", ""),
                "reason": (item.get("survDesc") or "")[:200],
            })
        if rows:
            n = insert_df(pd.DataFrame(rows), "surveillance_flags")
            inserted += n
            print(f"  GSM: {n} new rows")
    except Exception as e:
        print(f"  GSM: ❌ {str(e)[:100]}")

    # F&O ban list. nselib currently returns a BARE list of symbol strings
    # (e.g. ['AMBER', 'KAYNES']) — pd.DataFrame(that) yields an integer column
    # label, which broke the old `c.strip()` ('int' has no attribute 'strip').
    # Normalize to a flat symbol list; tolerate list-of-dicts / DataFrame too in
    # case the upstream shape drifts back (it has before).
    try:
        from nselib import derivatives as dv
        out = dv.fno_security_in_ban_period(trade_date=date.today().strftime("%d-%m-%Y"))
        symbols = []
        if isinstance(out, pd.DataFrame):
            if not out.empty:
                out.columns = [str(c).strip() for c in out.columns]
                sym_col = next((c for c in out.columns if "symbol" in c.lower()), out.columns[0])
                symbols = [str(v) for v in out[sym_col].tolist()]
        elif isinstance(out, list):
            for item in out:
                if isinstance(item, dict):
                    symbols.append(str(item.get("symbol") or item.get("Symbol") or ""))
                else:
                    symbols.append(str(item))
        rows = []
        for sym in symbols:
            sym = sym.strip().upper()
            if not sym:
                continue
            rows.append({
                "sid": sid_map.get(sym),
                "symbol": sym,
                "flag_type": "FNO_BAN",
                "flag_date": today_str,
                "stage": "",
                "reason": "",
            })
        if rows:
            n = insert_df(pd.DataFrame(rows), "surveillance_flags")
            inserted += n
            print(f"  F&O ban: {n} new rows")
        else:
            print("  F&O ban: 0 symbols in ban period today")
    except Exception as e:
        print(f"  F&O ban: ❌ {str(e)[:100]}")

    return inserted


# ───────────────────────── Driver ─────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True,
                        choices=["bulk", "corp", "short", "events", "fii_pos", "fii_cash",
                                 "indices", "surveillance", "all", "daily_forward"])
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--days-back", type=int, default=180, help="for fii_pos")
    parser.add_argument("--start", help="YYYY-MM-DD: deep backfill from this date (overrides "
                                        "--months / --days-back; replaces sources.historical_backfill)")
    args = parser.parse_args()
    if args.start:
        start = date.fromisoformat(args.start)
        args.months = _months_since(start)
        args.days_back = (date.today() - start).days + 1

    if args.source in ("bulk", "all"):
        print(f"\n=== Bulk deals ({args.months} months) ===")
        n = pull_bulk_deals(months=args.months)
        print(f"  → {n} new bulk_deals rows")

    if args.source in ("corp", "all"):
        print(f"\n=== Corporate actions ({args.months} months) ===")
        n = pull_corporate_actions(months=args.months)
        print(f"  → {n} new corporate_actions rows")

    if args.source in ("short", "all"):
        print(f"\n=== Short selling ({args.months} months) ===")
        n = pull_short_selling(months=args.months)
        print(f"  → {n} new short_selling_data rows")

    if args.source in ("events", "all"):
        print("\n=== Board-meeting / events calendar (−3d → +30d) ===")
        n = pull_event_calendar(days_back=3, days_forward=30)
        print(f"  → {n} new earnings_calendar rows")

    if args.source in ("fii_pos", "all"):
        print(f"\n=== FII/DII F&O positioning ({args.days_back} days) ===")
        n = pull_fii_positioning(days_back=args.days_back)
        print(f"  → {n} new fii_dii_positioning rows")

    if args.source in ("fii_cash", "all"):
        print(f"\n=== FII/DII cash flow (today's row) ===")
        pull_fii_cash_flow()

    if args.source in ("indices", "all"):
        print(f"\n=== NSE Smart-Beta indices ({args.months} months back) ===")
        n = pull_nse_indices(months=args.months)
        print(f"  → {n} new nse_index_history rows")

    if args.source in ("surveillance", "all", "daily_forward"):
        print("\n=== NSE surveillance (ASM/GSM/FNO ban) — today snapshot ===")
        n = pull_surveillance_today()
        print(f"  → {n} new surveillance_flags rows")

    if args.source in ("daily_forward",):
        # The "daily forward accumulation" job — run via cron daily
        print("\n=== FII/DII cash flow (today) ===")
        pull_fii_cash_flow()
        print("\n=== FII/DII F&O positioning (yesterday's reading) ===")
        pull_fii_positioning(days_back=3)  # only check last few days
        # Short selling — NSE posts with a T+1 lag; a 1-month window each day is
        # idempotent (INSERT OR IGNORE) and backfills any late-posted rows. Wired
        # into the daily cron 2026-06-03 (was manual-only `--source short` → 10d stale).
        print("\n=== Short selling (last month, forward accumulation) ===")
        n = pull_short_selling(months=1)
        print(f"  → {n} new short_selling_data rows")


if __name__ == "__main__":
    main()
