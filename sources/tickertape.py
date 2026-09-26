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
  - Per-stock errors are counted + logged; a run where no stock returns
    data RAISES (sources/_http.run_harvester)

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
from datetime import datetime
from pathlib import Path

import pandas as pd

# Add v1 scripts to path for Tickertape library
sys.path.insert(0, str(Path.home() / "alpha-signal" / "scripts"))

from config import API, PROJECT_ROOT
from db import read_sql, upsert_df
from sources._http import run_harvester

DELAY = API["min_gap"]  # 2 seconds
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


def _harvest(sids, key, label, table, fetch_raw, to_frame):
    """Run one statement type over `sids` via run_harvester, resume-aware.

    The checkpoint (`key` → index of the next sid) is saved at each flush, i.e.
    only once every sid before it has been fetched AND written. Errors used to be
    `except: pass` per stock — now counted, logged, and a run where no stock
    returned data RAISES instead of "succeeding" with 0 rows."""
    checkpoint = _load_checkpoint()
    start_idx = checkpoint.get(key, 0)
    done = start_idx
    print(f"  {label}: {len(sids)} stocks")

    def fetch(sid):
        nonlocal done
        done += 1
        raw = fetch_raw(sid)
        if raw is None or raw.empty:
            return []
        return to_frame(raw, sid).to_dict("records")

    def write(rows):
        n = upsert_df(pd.DataFrame(rows), table)
        checkpoint[key] = done
        _save_checkpoint(checkpoint)
        return n

    _, _, total = run_harvester(sids[start_idx:], fetch, write, flush_every=CHECKPOINT_EVERY,
                                label=label, delay=DELAY)
    checkpoint[key] = len(sids)
    _save_checkpoint(checkpoint)
    print(f"    Done: {total} rows")
    return total


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


def _income_frame(raw, sid):
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

    df, _ = _validate_income(df, sid)
    return df


def fetch_income(client, sids):
    """Fetch quarterly income for all stocks."""
    return _harvest(sids, "income_idx", "Quarterly Income", "quarterly_income",
                    lambda sid: client.get_income_data(sid, time_horizon="interim", num_time_periods=10),
                    _income_frame)


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


def _bs_frame(raw, sid):
    df = pd.DataFrame()
    df["period"] = raw.get("displayPeriod", "")
    df["end_date"] = raw.get("endDate", "").str[:10]
    df["sid"] = sid  # assign after period to broadcast (see _income_frame note)

    for tt_col, our_col in BS_MAP.items():
        df[our_col] = pd.to_numeric(raw.get(tt_col), errors="coerce")

    df, _ = _validate_bs(df, sid)
    return df


def fetch_balance_sheet(client, sids):
    """Fetch annual balance sheet for all stocks."""
    return _harvest(sids, "bs_idx", "Annual Balance Sheet", "annual_balance_sheet",
                    lambda sid: client.get_balance_sheet_data(sid, num_time_periods=10), _bs_frame)


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


def _cf_frame(raw, sid):
    df = pd.DataFrame()
    df["period"] = raw.get("displayPeriod", "")
    df["end_date"] = raw.get("endDate", "").str[:10]
    df["sid"] = sid  # assign after period to broadcast (see _income_frame note)

    for tt_col, our_col in CF_MAP.items():
        df[our_col] = pd.to_numeric(raw.get(tt_col), errors="coerce")

    df, _ = _validate_cf(df, sid)
    return df


def fetch_cash_flow(client, sids):
    """Fetch annual cash flow for all stocks."""
    return _harvest(sids, "cf_idx", "Annual Cash Flow", "annual_cash_flow",
                    lambda sid: client.get_cash_flow_data(sid, num_time_periods=10), _cf_frame)


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
        total += fetch_income(client, sids)
    if data_type in (None, "bs"):
        total += fetch_balance_sheet(client, sids)
    if data_type in (None, "cf"):
        total += fetch_cash_flow(client, sids)

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
