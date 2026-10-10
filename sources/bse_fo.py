"""
Alpha Signal v2 — BSE index derivatives EOD (SENSEX, BANKEX) into fno_bhav.

BSE's derivatives bhavcopy in the UDiFF layout NSE uses (same column names), one
plain CSV per trading day, from ~2024-01-05. The older BSE file (to 2024-07-05)
carries no settlement price and no index level, so it is not read.

Same rows as sources.fno_pull writes for NSE, for SENSEX's weekly expiry (BSE's
side of SEBI's one-weekly-expiry-per-exchange rule):
  • index options + futures only (IDO / IDF), contracts with OI or volume
  • volume in LOTS and OI in units, as in fno_bhav (BSE's TtlTradgVol is units: ÷ NewBrdLotQty)
  • on expiry day an option's SttlmPric is the index settlement, as on NSE

A missing day comes back as HTTP 200 with an HTML page, so a body must start with
`TradDt` to count as a file.

Usage:
    python -m sources.bse_fo --start 2024-01-05 --end 2026-10-08 --budget-min 60
"""

import argparse
import io
from datetime import date, timedelta

import pandas as pd

from db import insert_df, read_sql
from sources import _http

URL = "https://www.bseindia.com/download/BhavCopy/Derivative/BhavCopy_BSE_FO_0_0_0_{ymd}_F_0000.CSV"
SYMBOLS = ("SENSEX", "BANKEX")
FIRST_FILE = "2024-01-05"


def parse(content):
    """One BSE UDiFF CSV → fno_bhav rows for SYMBOLS (empty frame when nothing to keep)."""
    df = pd.read_csv(io.BytesIO(content))
    df.columns = [c.strip() for c in df.columns]
    df = df[df["FinInstrmTp"].isin(("IDO", "IDF")) & df["TckrSymb"].astype(str).str.strip().isin(SYMBOLS)]
    oi = pd.to_numeric(df["OpnIntrst"], errors="coerce").fillna(0)
    units = pd.to_numeric(df["TtlTradgVol"], errors="coerce").fillna(0)
    df = df[(oi > 0) | (units > 0)]
    if df.empty:
        return pd.DataFrame()
    lot = pd.to_numeric(df["NewBrdLotQty"], errors="coerce")
    return pd.DataFrame({
        "sid": None,
        "symbol": df["TckrSymb"].astype(str).str.strip(),
        "instrument_type": df["FinInstrmTp"],
        "expiry_date": pd.to_datetime(df["XpryDt"]).dt.date.astype(str),
        "strike": pd.to_numeric(df["StrkPric"], errors="coerce").fillna(0.0),
        "option_type": df["OptnTp"].astype(str).str.strip().replace({"": "XX", "nan": "XX"}),
        "trade_date": pd.to_datetime(df["TradDt"]).dt.date.astype(str),
        "close": pd.to_numeric(df["ClsPric"], errors="coerce"),
        "settle": pd.to_numeric(df["SttlmPric"], errors="coerce"),
        "underlying_price": pd.to_numeric(df["UndrlygPric"], errors="coerce"),
        "oi": oi[df.index].astype("int64"),
        "chg_oi": pd.to_numeric(df["ChngInOpnIntrst"], errors="coerce").fillna(0).astype("int64"),
        "volume": (units[df.index] // lot).astype("int64"),
        "num_trades": pd.to_numeric(df["TtlNbOfTxsExctd"], errors="coerce").astype("Int64"),
    })


def backfill(start, end, budget_min=None):
    """Load [start, end] into fno_bhav. Resumable: days already holding SENSEX rows are
    skipped. Raises when every day tried failed. Returns new rows."""
    import runlog
    have = set(read_sql("SELECT DISTINCT trade_date FROM fno_bhav WHERE symbol = 'SENSEX' "
                        "AND trade_date BETWEEN ? AND ?", params=[start, end])["trade_date"])
    s, e = date.fromisoformat(max(start, FIRST_FILE)), date.fromisoformat(end)
    todo = [d for d in (s + timedelta(days=i) for i in range((e - s).days + 1))
            if d.weekday() < 5 and d.isoformat() not in have]
    print(f"BSE F&O {s} → {e}: {len(todo)} weekdays not yet loaded ({len(have)} loaded)")
    out_of_time = _http.time_budget("bse", budget_min) if budget_min else (lambda: False)
    total = n_days = n_bad = n_none = 0
    for d in todo:
        if out_of_time():
            print(f"  stopped at the {budget_min:.0f}-min budget — rerun to resume")
            break
        try:
            resp = _http.polite_get(URL.format(ymd=d.strftime("%Y%m%d")), timeout=40)
            if resp is None or not resp.content.startswith(b"TradDt"):
                n_none += 1                        # holiday: BSE answers 200 + an HTML page
                continue
            df = parse(resp.content)
        except Exception as ex:                    # noqa: BLE001 — one bad day must not stop the range
            n_bad += 1
            runlog.item_error("bse_fo_bhav", d.isoformat(), ex)
            continue
        if df.empty:
            n_bad += 1
            runlog.item_failed("bse_fo_bhav", d.isoformat(), "0 SENSEX/BANKEX contracts in the file")
            continue
        total += insert_df(df, "fno_bhav", lock_retries=5)
        runlog.item_ok()
        n_days += 1
        if n_days % 50 == 0:
            print(f"  {d}: {n_days} days loaded, {total} rows", flush=True)
    print(f"BSE F&O: {n_days} days loaded, {total} new rows, {n_none} no file, {n_bad} bad days")
    if todo and n_days == 0 and (n_bad or n_none == len(todo)):
        raise RuntimeError(f"BSE F&O: 0 of {len(todo)} days loaded — URL moved or blocked?")
    return total


def main():
    ap = argparse.ArgumentParser(description="BSE index derivatives bhavcopy → fno_bhav")
    ap.add_argument("--start", default=FIRST_FILE)
    ap.add_argument("--end", default=(date.today() - timedelta(days=1)).isoformat())
    ap.add_argument("--budget-min", type=float)
    a = ap.parse_args()
    backfill(a.start, a.end, a.budget_min)


if __name__ == "__main__":
    main()
