"""
Alpha Signal v2 — write the point-in-time panel (daily_snapshots_pit) for anchor dates.

The computation lives in pit.py (shared with the live screener); this is the batch
writer + checkpoint log + the weekly refresh step.

Usage:
    python -m tools.reconstruct_pit                  # 7 monthly dates, all signals
    python -m tools.reconstruct_pit --months 12      # extend lookback
    python -m tools.reconstruct_pit --dry-run        # compute but don't write
    python -m tools.reconstruct_pit --signal piotroski   # one signal only
    python -m tools.reconstruct_pit --date 2025-12-01    # explicit date(s)
"""

import argparse
from datetime import date, datetime, timedelta

import pandas as pd

import factors
from db import get_db, read_sql, upsert_df
from pit import (PIT_COLUMNS, load_raw, pit_macro_sector, pit_regulatory_sector,
                 reconstruct_one_date)


# ─────────────────────────── Schema ───────────────────────────

CREATE_TABLE_SQL = (
    "CREATE TABLE IF NOT EXISTS daily_snapshots_pit (\n"
    "    sid              TEXT NOT NULL REFERENCES stocks(sid),\n"
    "    snapshot_date    TEXT NOT NULL,\n"
    "    cap_tier         TEXT,\n"
    + "".join(f"    {c} {factors.PIT_COLUMN_TYPES.get(c, 'REAL')},\n"
              for c in factors.PIT_COLUMNS[3:])
    + "    reconstructed_at TEXT DEFAULT (datetime('now')),\n"
    "    PRIMARY KEY (sid, snapshot_date)\n"
    ");\n"
    """CREATE INDEX IF NOT EXISTS idx_pit_date ON daily_snapshots_pit(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_pit_tier ON daily_snapshots_pit(cap_tier);

CREATE TABLE IF NOT EXISTS pit_reconstruction_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_date        TEXT NOT NULL,
    signals_run      TEXT NOT NULL,
    rows_attempted   INTEGER,
    rows_written     INTEGER,
    validation_summary TEXT,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    duration_sec     REAL,
    status           TEXT CHECK(status IN ('RUNNING', 'SUCCESS', 'FAILED', 'SKIPPED')),
    error_message    TEXT
);
CREATE INDEX IF NOT EXISTS idx_pit_log_date ON pit_reconstruction_log(eval_date);
"""
)


# ─────────────────────── Eval-date generator ───────────────────────

def generate_eval_dates(months_back=7, today=None):
    """
    Generate monthly eval dates: first business day of each of the last N months.
    Default 7 dates, ending in the current month.

    Example for today=2026-05-03 and months_back=7:
        2025-11-03, 2025-12-01, 2026-01-02, 2026-02-02,
        2026-03-02, 2026-04-01, 2026-05-01
    """
    if today is None:
        today = date.today()

    dates = []
    for offset in range(months_back - 1, -1, -1):
        # Walk back `offset` months from current
        y = today.year
        m = today.month - offset
        while m <= 0:
            m += 12
            y -= 1
        d = date(y, m, 1)
        # First business day (skip Sat=5, Sun=6)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        dates.append(d)
    return dates


def generate_weekly_eval_dates(weeks_back=104, today=None):
    """Generate weekly eval dates: every Friday close, last N weeks.

    Default 104 weeks (~2 years). For behavioral/news signals that warrant
    weekly cadence per BACKTEST_CADENCE in db.py. Friday choice = end-of-week
    market state, consistent across signals.
    """
    if today is None:
        today = date.today()
    # Walk back to find the most-recent past Friday (weekday 4)
    days_since_fri = (today.weekday() - 4) % 7
    last_friday = today - timedelta(days=days_since_fri)
    dates = []
    for offset in range(weeks_back - 1, -1, -1):
        dates.append(last_friday - timedelta(weeks=offset))
    return dates



def refresh(today=None):
    """Pipeline entry point (plan 0015 Phase 0): keep the PIT panel current.

    The panel was only ever rebuilt by hand, so it froze at 2026-07-01 while the
    monthly backtest cron kept re-scoring it. This re-runs the recent anchors —
    their fwd_return_20d fills in only once 20 trading days have passed — and
    catches up any anchors missed since the last run: monthly (first business day)
    and weekly (Friday), all producers. Raises if any date fails.
    """
    today = today or date.today()
    def _last(where):
        d = read_sql(f"SELECT MAX(snapshot_date) AS d FROM daily_snapshots_pit WHERE {where}")["d"].iloc[0]
        return date.fromisoformat(d[:10]) if d else today - timedelta(days=365)
    last_m = _last("CAST(strftime('%d', snapshot_date) AS INTEGER) <= 7")   # monthly anchors
    last_w = _last("strftime('%w', snapshot_date) = '5'")                   # Friday anchors
    months_back = max(3, (today.year - last_m.year) * 12 + today.month - last_m.month + 1)
    weeks_back = max(10, (today - last_w).days // 7 + 1)
    dates = sorted(set(generate_eval_dates(months_back, today))
                   | set(generate_weekly_eval_dates(weeks_back, today)))
    argv = [a for d in dates for a in ("--date", d.isoformat())]
    stats = {}
    n = main(argv, stats=stats)
    if stats.get("failed"):
        raise RuntimeError(f"PIT refresh: {stats['failed']} of {len(dates)} dates FAILED: {stats['failed_dates']}")
    if not n:
        raise RuntimeError(f"PIT refresh wrote 0 rows for {len(dates)} dates")
    return n


def main(argv=None, stats=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=7,
                        help="Number of monthly eval dates back from today (default 7). Ignored when --cadence weekly.")
    parser.add_argument("--cadence", choices=["monthly", "weekly"], default="monthly",
                        help="Eval-date frequency. weekly = every Friday close (use for behavioral/news signals; see db.BACKTEST_CADENCE).")
    parser.add_argument("--weeks", type=int, default=104,
                        help="Number of weekly eval dates back from today (default 104 = 2yr). Only used when --cadence weekly.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Compute but don't write to daily_snapshots_pit")
    parser.add_argument("--signal", action="append", default=None,
                        choices=factors.PIT_SIGNALS,
                        help="Compute only this signal (repeatable)")
    parser.add_argument("--date", action="append", default=None,
                        help="Explicit eval date (YYYY-MM-DD, repeatable). "
                             "Overrides --months/--weeks/--cadence date generation.")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip eval dates that already have a SUCCESS row in pit_reconstruction_log")
    args = parser.parse_args(argv)
    stats = stats if stats is not None else {}
    stats.update(failed=0, failed_dates=[])

    if args.date:
        from datetime import date as _date
        eval_dates = [_date.fromisoformat(d) for d in args.date]
        print(f"  Explicit dates · {len(eval_dates)}: {eval_dates}")
    elif args.cadence == "weekly":
        eval_dates = generate_weekly_eval_dates(weeks_back=args.weeks)
        print(f"  Cadence: weekly · {len(eval_dates)} Friday eval dates · {eval_dates[0]} → {eval_dates[-1]}")
    else:
        eval_dates = generate_eval_dates(months_back=args.months)
        print(f"  Cadence: monthly · {len(eval_dates)} dates · {eval_dates[0]} → {eval_dates[-1]}")
    # Default run = every producer in the registry (factors.PIT_PRODUCERS).
    DEFAULT_SIGNALS = set(factors.PIT_PRODUCERS)
    signals_to_run = set(args.signal) if args.signal else DEFAULT_SIGNALS
    signals_label = ",".join(sorted(signals_to_run))

    print(f"PIT reconstruction — {len(eval_dates)} dates × {len(signals_to_run)} signals")
    print(f"  Eval dates: {[d.isoformat() for d in eval_dates]}")
    print(f"  Signals:    {sorted(signals_to_run)}")
    print()

    # Ensure tables exist (incl. checkpoint log)
    if not args.dry_run:
        with get_db() as conn:
            for stmt in CREATE_TABLE_SQL.strip().split(";"):
                if stmt.strip():
                    conn.execute(stmt)

    # ── Skip-existing: query checkpoint log to find dates already done ──
    skip_dates = set()
    if args.skip_existing and not args.dry_run:
        try:
            done = read_sql(
                "SELECT DISTINCT eval_date FROM pit_reconstruction_log "
                "WHERE status = 'SUCCESS' AND signals_run = ?",
                params=(signals_label,),
            )
            skip_dates = set(done["eval_date"].tolist())
            if skip_dates:
                print(f"  Skipping {len(skip_dates)} already-done dates (per checkpoint log)")
        except Exception as e:
            print(f"  (skip-existing check failed: {e})")

    raw = load_raw()

    total_rows = 0
    started_overall = datetime.now()

    for eval_date in eval_dates:
        eval_str = eval_date.isoformat()

        if eval_str in skip_dates:
            print(f"[{eval_str}] SKIPPED (already in checkpoint log)")
            continue

        # Open a RUNNING checkpoint row before any work — so a crash mid-way leaves a trail
        log_id = None
        started_at = datetime.now()
        if not args.dry_run:
            try:
                with get_db() as conn:
                    cur = conn.execute(
                        "INSERT INTO pit_reconstruction_log "
                        "(eval_date, signals_run, started_at, status) VALUES (?, ?, ?, 'RUNNING')",
                        (eval_str, signals_label, started_at.isoformat()),
                    )
                    log_id = cur.lastrowid
            except Exception as e:
                print(f"[{eval_str}] (checkpoint write failed: {e}) — continuing anyway")

        print(f"[{eval_str}] reconstructing...", end=" ", flush=True)
        try:
            df, validation = reconstruct_one_date(eval_date, raw, signals_to_run)
        except Exception as e:
            # Mark the checkpoint FAILED so a future --skip-existing run doesn't skip
            if log_id is not None:
                try:
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE pit_reconstruction_log SET status='FAILED', "
                            "finished_at=?, duration_sec=?, error_message=? WHERE id=?",
                            (datetime.now().isoformat(),
                             (datetime.now() - started_at).total_seconds(),
                             str(e)[:500], log_id),
                        )
                except Exception:
                    pass
            print(f"FAILED — {e}")
            stats["failed"] += 1
            stats["failed_dates"].append(eval_str)
            continue

        # Diagnostic: how many stocks have at least one signal?
        signal_cols = [c for c in df.columns if c not in {"sid", "snapshot_date", "cap_tier", "close_price"}]
        n_with_any = (df[signal_cols].notna().any(axis=1)).sum()

        n_written = 0
        if not args.dry_run:
            # SQLite can't bind pandas NA — replace with Python None
            df_to_write = df.astype(object).where(df.notna(), None)
            n_written = upsert_df(df_to_write, "daily_snapshots_pit")
            total_rows += n_written

            # Close the checkpoint row as SUCCESS — guaranteed before next iteration
            if log_id is not None:
                import json
                try:
                    finished = datetime.now()
                    with get_db() as conn:
                        conn.execute(
                            "UPDATE pit_reconstruction_log SET status='SUCCESS', "
                            "rows_attempted=?, rows_written=?, finished_at=?, "
                            "duration_sec=?, validation_summary=? WHERE id=?",
                            (len(df), n_written, finished.isoformat(),
                             (finished - started_at).total_seconds(),
                             json.dumps(validation), log_id),
                        )
                except Exception as e:
                    print(f"(log update failed: {e})", end=" ")

        # ── Sector overlays (separate table macro_sector_signals_pit) ──
        n_sectors_written = 0
        if "sector_overlays" in signals_to_run:
            try:
                sectors_list = sorted(raw["stocks"]["sector"].dropna().unique().tolist())
                # PIT slices for the sector signals
                reg_events_pit = raw["reg_events"][raw["reg_events"]["published_at"] <= eval_str]
                macro_hist_pit = raw["macro_hist"][raw["macro_hist"]["date"] <= eval_str]

                reg_rows = pit_regulatory_sector(reg_events_pit, raw["reg_signals"],
                                                 sectors_list, eval_date)
                mac_rows = pit_macro_sector(macro_hist_pit, raw["macro_map"],
                                            sectors_list, eval_date)

                # Merge by sector
                reg_by_sector = {r["sector"]: r for r in reg_rows}
                mac_by_sector = {r["sector"]: r for r in mac_rows}
                sector_records = []
                for s in sectors_list:
                    rr = reg_by_sector.get(s, {})
                    mr = mac_by_sector.get(s, {})
                    sector_records.append({
                        "sector": s,
                        "snapshot_date": eval_str,
                        "regulatory_score": rr.get("regulatory_score"),
                        "macro_score": mr.get("macro_score"),
                        "n_reg_events": rr.get("n_reg_events", 0),
                        "n_macro_indicators": mr.get("n_macro_indicators", 0),
                    })

                if not args.dry_run:
                    sec_df = pd.DataFrame(sector_records)
                    sec_to_write = sec_df.astype(object).where(sec_df.notna(), None)
                    n_sectors_written = upsert_df(sec_to_write, "macro_sector_signals_pit")
            except Exception as e:
                print(f"(sector overlay failed: {e})", end=" ")

        # Validation summary: any column with >5% out_of_range entries gets flagged
        flags = [c for c, v in validation.items() if v.get("out_of_range", 0) > len(df) * 0.05]
        flag_str = (" ⚠ ranged-out:" + ",".join(flags)) if flags else ""
        sector_str = f" sectors={n_sectors_written}" if n_sectors_written else ""
        if not args.dry_run:
            print(f"rows={len(df)} with_signal={n_with_any} written={n_written}{sector_str}{flag_str}")
        else:
            print(f"rows={len(df)} with_signal={n_with_any} (dry-run){sector_str}{flag_str}")

    print()
    elapsed = (datetime.now() - started_overall).total_seconds()
    print(f"Done. {total_rows} rows written to daily_snapshots_pit in {elapsed:.1f}s.")
    return total_rows


if __name__ == "__main__":
    main()
