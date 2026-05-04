"""
Alpha Signal v2 — Import v1's frozen 36-month PIT reconstruction.

Loads /home/ubuntu/alpha-signal/data/backtest/reconstructed_signals.csv
into a new SQLite table `daily_snapshots_pit_v1` for backtesting consumption.

Why a separate table:
  - v1 reconstruction is FROZEN as of 2026-04-03 — it's the source-of-truth
    dataset that produced the C13b t-stats baked into CLAUDE.md.
  - v1 has columns v2 doesn't (fwd_return_20d, eps_cv, earnings_beat_rate,
    pledge_quality, avg_delivery_pct_30d) and lacks columns v2 has (m_score,
    z_score). Different schemas — separate tables.
  - Backtest harness can join/union across both.

Usage:
    python -m tools.import_v1_pit              # full import
    python -m tools.import_v1_pit --dry-run    # report what would import
"""

import argparse
from pathlib import Path

import pandas as pd

from db import get_db, upsert_df

V1_CSV = Path("/home/ubuntu/alpha-signal/data/backtest/reconstructed_signals.csv")
V1_IC_CSV = Path("/home/ubuntu/alpha-signal/data/backtest/reconstructed_ic_by_tier.csv")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_snapshots_pit_v1 (
    sid                  TEXT NOT NULL,
    snapshot_date        TEXT NOT NULL,
    ticker               TEXT,
    cap_tier             TEXT,
    sector               TEXT,
    price                REAL,
    fwd_return_20d       REAL,
    piotroski_f          INTEGER,
    cf_accruals          REAL,
    bs_accruals          REAL,
    eps_cv               REAL,
    earnings_beat_rate   REAL,
    book_to_price        REAL,
    earnings_yield       REAL,
    mom_6m               REAL,
    mom_12m              REAL,
    promoter_qoq         REAL,
    pledge_quality       REAL,
    avg_delivery_pct_30d REAL,
    imported_at          TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_pit_v1_date ON daily_snapshots_pit_v1(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_pit_v1_tier ON daily_snapshots_pit_v1(cap_tier);
"""

CREATE_IC_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS pit_ic_by_tier_v1 (
    signal           TEXT NOT NULL,
    cap_tier         TEXT NOT NULL,
    description      TEXT,
    n_periods        INTEGER,
    n_stocks_avg     INTEGER,
    mean_ic          REAL,
    std_ic           REAL,
    icir             REAL,
    t_stat           REAL,
    avg_ls_pct       REAL,
    verdict          TEXT,
    higher_better    INTEGER,
    imported_at      TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (signal, cap_tier)
);
"""

# v1 column → v2 column name normalization
COLUMN_MAP = {
    "eval_date":           "snapshot_date",
    "piotroski_f_score":   "piotroski_f",
    "cf_accruals_ratio":   "cf_accruals",
    "bs_accruals_ratio":   "bs_accruals",
    "mom_6m_adj":          "mom_6m",
    "mom_12m_adj":         "mom_12m",
    # ticker, cap_tier, sector, price, fwd_return_20d, eps_cv,
    # earnings_beat_rate, book_to_price, earnings_yield, promoter_qoq,
    # pledge_quality, avg_delivery_pct_30d  →  same name
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not V1_CSV.exists():
        raise SystemExit(f"v1 PIT CSV not found at {V1_CSV}")

    print(f"Loading {V1_CSV}...")
    df = pd.read_csv(V1_CSV)
    print(f"  rows={len(df)}  dates={df['eval_date'].nunique()}  stocks={df['sid'].nunique()}")

    df = df.rename(columns=COLUMN_MAP)
    expected = {
        "sid", "snapshot_date", "ticker", "cap_tier", "sector", "price",
        "fwd_return_20d", "piotroski_f", "cf_accruals", "bs_accruals",
        "eps_cv", "earnings_beat_rate", "book_to_price", "earnings_yield",
        "mom_6m", "mom_12m", "promoter_qoq", "pledge_quality",
        "avg_delivery_pct_30d",
    }
    missing = expected - set(df.columns)
    if missing:
        raise SystemExit(f"Missing columns after rename: {missing}")

    df = df[list(expected)]

    # piotroski_f → integer (with NaN tolerance)
    df["piotroski_f"] = df["piotroski_f"].astype("Int64")

    # SQLite NA handling
    df_to_write = df.astype(object).where(df.notna(), None)

    print(f"\nLoading {V1_IC_CSV}...")
    ic = pd.read_csv(V1_IC_CSV)
    print(f"  rows={len(ic)}")
    ic_to_write = ic.astype(object).where(ic.notna(), None)

    if args.dry_run:
        print("\n[dry-run] would write:")
        print(f"  daily_snapshots_pit_v1:  {len(df_to_write)} rows")
        print(f"  pit_ic_by_tier_v1:       {len(ic_to_write)} rows")
        return

    print("\nCreating tables...")
    with get_db() as conn:
        for stmt in (CREATE_TABLE_SQL + CREATE_IC_TABLE_SQL).split(";"):
            if stmt.strip():
                conn.execute(stmt)

    print("Writing daily_snapshots_pit_v1...")
    n = upsert_df(df_to_write, "daily_snapshots_pit_v1")
    print(f"  wrote {n} rows")

    print("Writing pit_ic_by_tier_v1...")
    n_ic = upsert_df(ic_to_write, "pit_ic_by_tier_v1")
    print(f"  wrote {n_ic} rows")

    print("\nDone.")


if __name__ == "__main__":
    main()
