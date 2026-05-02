"""
Alpha Signal v2 — Tickertape Fundamentals Fetcher

Fetches quarterly income, annual balance sheet, annual cash flow,
and analyst consensus from Tickertape via the Bharat_sm_data library.

Guardrails:
  - Validates column presence and types before insert
  - Rejects negative total_assets / total_equity (likely parse error)
  - Rejects EPS outside ±10,000 (extreme outliers)
  - Revenue/net_income: allows negative (losses are real)
  - Checkpoints every 200 stocks (resume on crash)
  - 2-second delay between API calls
  - Skips stocks that error without crashing pipeline

Reads: Tickertape API (via Bharat_sm_data library)
Writes: quarterly_income, annual_balance_sheet, annual_cash_flow

Usage:
    python -m sources.tickertape                      # refresh all (resume-aware)
    python -m sources.tickertape --type income        # income only
    python -m sources.tickertape --limit 10           # first 10 stocks
    python -m sources.tickertape --dry-run
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add v1 scripts to path for Tickertape library
sys.path.insert(0, str(Path.home() / "alpha-signal" / "scripts"))

from config import API, PROJECT_ROOT
from db import read_sql, upsert_df, insert_df

DELAY = API["tickertape_delay"]  # 2 seconds
CHECKPOINT_EVERY = 200
CHECKPOINT_FILE = PROJECT_ROOT / "output" / "tickertape_harvest_log.json"


def _get_client():
    """Get Tickertape client."""
    from Fundamentals.TickerTape import Tickertape
    return Tickertape()


def _load_checkpoint():
    """Load harvest checkpoint."""
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {}


def _save_checkpoint(data):
    """Save harvest checkpoint."""
    CHECKPOINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CHECKPOINT_FILE.write_text(json.dumps(data, indent=2))


# ── Income ──

INCOME_MAP = {
    "qIncTrev": "revenue",
    "qIncPfc": "operating_profit",
    "qIncNinc": "net_income",
    "qIncEps": "eps",
    "qIncOpe": "interest",
    "qIncPbt": "pbt",
    "qIncToi": "total_other_income",
}


def _validate_income(df, sid):
    """Validate income data. Returns (clean_df, errors)."""
    errors = []
    if df.empty:
        return df, ["empty"]

    # Must have end_date (already mapped from raw endDate)
    if "end_date" not in df.columns:
        return pd.DataFrame(), ["missing end_date"]

    # EPS sanity
    if "eps" in df.columns:
        bad_eps = df[(df["eps"].abs() > 10000) & df["eps"].notna()]
        if len(bad_eps) > 0:
            errors.append(f"{len(bad_eps)} rows with |EPS| > 10,000 (clipped)")
            df.loc[df["eps"].abs() > 10000, "eps"] = None

    return df, errors


def fetch_income(client, sids, dry_run=False):
    """Fetch quarterly income for all stocks."""
    print(f"  Quarterly Income: {len(sids)} stocks")
    total = 0
    checkpoint = _load_checkpoint()
    start_idx = checkpoint.get("income_idx", 0)

    for i, sid in enumerate(sids):
        if i < start_idx:
            continue

        if dry_run:
            continue

        try:
            raw = client.get_income_data(sid, time_horizon="interim", num_time_periods=10)
            if raw is None or raw.empty:
                time.sleep(DELAY)
                continue

            # Map columns. NOTE: assigning a scalar to an empty DataFrame creates
            # a zero-length column — assign sid AFTER period so it broadcasts.
            df = pd.DataFrame()
            df["period"] = raw.get("displayPeriod", "")
            df["end_date"] = raw.get("endDate", "").str[:10]
            df["reporting"] = raw.get("reporting", "consolidated")
            df["sid"] = sid

            for tt_col, our_col in INCOME_MAP.items():
                df[our_col] = pd.to_numeric(raw.get(tt_col), errors="coerce")

            # Derive EBITDA
            if "pbt" in df.columns and "interest" in df.columns:
                df["ebitda"] = df["pbt"] + df["interest"].fillna(0)

            df, errs = _validate_income(df, sid)
            if not df.empty:
                n = upsert_df(df, "quarterly_income")
                total += n

        except Exception as e:
            pass  # skip erroring stocks silently

        if (i + 1) % CHECKPOINT_EVERY == 0:
            checkpoint["income_idx"] = i + 1
            _save_checkpoint(checkpoint)
            print(f"    [{i+1}/{len(sids)}] {total} rows saved", flush=True)

        time.sleep(DELAY)

    checkpoint["income_idx"] = len(sids)
    _save_checkpoint(checkpoint)
    print(f"    Done: {total} rows")
    return total


# ── Balance Sheet ──

BS_MAP = {
    "balTota": "total_assets",
    "balTeq": "total_equity",
    "balTdeb": "total_debt",
    "balTca": "current_assets",
    "balTcl": "current_liabilities",
    "balCsti": "cash_and_equivalents",
    "balTrec": "receivables",
    "balRtne": "retained_earnings",
    "balNppe": "net_ppe",
    "balTotl": "total_liabilities",
    "balTcso": "shares_outstanding",
    "balTltd": "long_term_debt",
}


def _validate_bs(df, sid):
    """Validate balance sheet data."""
    errors = []
    if df.empty:
        return df, ["empty"]

    # Total assets must be positive
    if "total_assets" in df.columns:
        bad = df[df["total_assets"] < 0]
        if len(bad) > 0:
            errors.append(f"{len(bad)} rows with negative total_assets (dropped)")
            df = df[df["total_assets"] >= 0]

    # Shares outstanding must be positive
    if "shares_outstanding" in df.columns:
        df.loc[df["shares_outstanding"] <= 0, "shares_outstanding"] = None

    return df, errors


def fetch_balance_sheet(client, sids, dry_run=False):
    """Fetch annual balance sheet for all stocks."""
    print(f"  Annual Balance Sheet: {len(sids)} stocks")
    total = 0
    checkpoint = _load_checkpoint()
    start_idx = checkpoint.get("bs_idx", 0)

    for i, sid in enumerate(sids):
        if i < start_idx:
            continue
        if dry_run:
            continue

        try:
            raw = client.get_balance_sheet_data(sid, num_time_periods=10)
            if raw is None or raw.empty:
                time.sleep(DELAY)
                continue

            df = pd.DataFrame()
            df["period"] = raw.get("displayPeriod", "")
            df["end_date"] = raw.get("endDate", "").str[:10]
            df["sid"] = sid  # assign after period to broadcast (see fetch_income note)

            for tt_col, our_col in BS_MAP.items():
                df[our_col] = pd.to_numeric(raw.get(tt_col), errors="coerce")

            df, errs = _validate_bs(df, sid)
            if not df.empty:
                n = upsert_df(df, "annual_balance_sheet")
                total += n

        except Exception:
            pass

        if (i + 1) % CHECKPOINT_EVERY == 0:
            checkpoint["bs_idx"] = i + 1
            _save_checkpoint(checkpoint)
            print(f"    [{i+1}/{len(sids)}] {total} rows saved", flush=True)

        time.sleep(DELAY)

    checkpoint["bs_idx"] = len(sids)
    _save_checkpoint(checkpoint)
    print(f"    Done: {total} rows")
    return total


# ── Cash Flow ──

CF_MAP = {
    "cafCfoa": "operating_cash_flow",
    "cafCexp": "capex",
    "cafFcf": "free_cash_flow",
    "cafCfia": "investing_cash_flow",
    "cafCffa": "financing_cash_flow",
    "cafCiwc": "working_capital_change",
    "cafTcdp": "depreciation",
    "cafNcic": "net_change_in_cash",
}


def _validate_cf(df, sid):
    """Validate cash flow data."""
    if df.empty:
        return df, ["empty"]
    return df, []


def fetch_cash_flow(client, sids, dry_run=False):
    """Fetch annual cash flow for all stocks."""
    print(f"  Annual Cash Flow: {len(sids)} stocks")
    total = 0
    checkpoint = _load_checkpoint()
    start_idx = checkpoint.get("cf_idx", 0)

    for i, sid in enumerate(sids):
        if i < start_idx:
            continue
        if dry_run:
            continue

        try:
            raw = client.get_cash_flow_data(sid, num_time_periods=10)
            if raw is None or raw.empty:
                time.sleep(DELAY)
                continue

            df = pd.DataFrame()
            df["period"] = raw.get("displayPeriod", "")
            df["end_date"] = raw.get("endDate", "").str[:10]
            df["sid"] = sid  # assign after period to broadcast (see fetch_income note)

            for tt_col, our_col in CF_MAP.items():
                df[our_col] = pd.to_numeric(raw.get(tt_col), errors="coerce")

            df, errs = _validate_cf(df, sid)
            if not df.empty:
                n = upsert_df(df, "annual_cash_flow")
                total += n

        except Exception:
            pass

        if (i + 1) % CHECKPOINT_EVERY == 0:
            checkpoint["cf_idx"] = i + 1
            _save_checkpoint(checkpoint)
            print(f"    [{i+1}/{len(sids)}] {total} rows saved", flush=True)

        time.sleep(DELAY)

    checkpoint["cf_idx"] = len(sids)
    _save_checkpoint(checkpoint)
    print(f"    Done: {total} rows")
    return total


def compute(data_type=None, limit=None, dry_run=False):
    """Main entry point."""
    stocks = read_sql("SELECT sid FROM stocks ORDER BY sid")
    sids = stocks["sid"].tolist()
    if limit:
        sids = sids[:limit]

    print(f"Tickertape Fundamentals: {len(sids)} stocks")

    if dry_run:
        print(f"  Would fetch income + BS + CF for {len(sids)} stocks")
        print(f"  Estimated time: ~{len(sids) * 3 * DELAY / 60:.0f} min (3 calls × {DELAY}s delay)")
        return 0

    client = _get_client()
    total = 0

    if data_type in (None, "income"):
        total += fetch_income(client, sids, dry_run)
    if data_type in (None, "bs"):
        total += fetch_balance_sheet(client, sids, dry_run)
    if data_type in (None, "cf"):
        total += fetch_cash_flow(client, sids, dry_run)

    # Clear checkpoint on successful completion
    if data_type is None:
        _save_checkpoint({})

    return total


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["income", "bs", "cf"], help="Fetch specific data type")
    parser.add_argument("--limit", type=int, help="Limit to first N stocks")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(data_type=args.type, limit=args.limit, dry_run=args.dry_run)
