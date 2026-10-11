# ADR 0072 — Kite minute bars live in a Parquet archive with a SQLite manifest

**Status:** accepted 2026-10-11 (Amit: "agreed with all the 5 datasets", "start the harvester, the most expensive one first")

**Decision.** Every universe stock's 1-minute bars since 2015 come from Kite Connect
(`sources/kite_bars.py`) and are stored as Parquet under `config.INTRADAY_DIR/bars_1m/`,
four columns only — `sid, ts (UTC), close (paise), volume` — with one row per file in the
SQLite table `intraday_files`. Factors read a daily summary built from these files through
one reader, never the files or Kite directly. The Kite jobs take their own lock, not the
harvest lock.

## Why
- **Size.** ~1.1 bn bars. Measured on a real year (2026-10-11): plain SQLite 93 B/bar (102 GB),
  lean SQLite 29 B/bar (32 GB), Parquet zstd + delta encoding with close and volume only
  3.3 B/bar (3.6 GB). RELIANCE's full history is 1.08 M bars in 4 MB. A vector DB was
  ~300 GB and the wrong tool (nearest-neighbour search, not group-by-day).
- **Four columns.** The three intraday factors and a true VWAP need only close and volume per
  minute; daily high/low already exist in `stock_prices`. The fetch day sits in the manifest,
  not on a billion rows.
- **Own lock.** The harvest lock exists so two jobs never double the request rate to one site.
  Kite is a different site, and a Kite login lasts only until midnight UTC, so sharing the
  other harvesters' multi-hour windows would stretch a ~4-day backfill to weeks.

## Rules
- **Layout.** Backfill writes `_staging/sid=<SID>.parquet` (one file per stock); when it is done,
  compaction rewrites them as `month=YYYY-MM/part-0.parquet` (all stocks, sorted by sid, ts).
  Forward data arrives as day files and is compacted on the 1st. Closed months are immutable.
- **Writes** are atomic (temp file, then rename) and pass a contract first: no duplicate
  minute, bars only 09:00–20:00 IST (muhurat sessions are evenings), close > 0, volume ≥ 0,
  ≤ 400 bars a day. A failing stock is not written and the contract is never loosened.
  Two cleanings run before it, both found in Kite's 2015 history on the smoke test: bars with
  close 0 AND volume 0 before a session's first trade are dropped (no trade, no information),
  and bars stamped off the minute (11:54:38) take their minute unless it already has a bar
  (one was an exact copy). COFORGE lost 25 of 1,080,194 bars to them.
- **Prices are Kite-adjusted as of `fetched_on`.** Kite rewrites history for splits and bonuses
  (KOTAKBANK 2026-01-12: raw close 2133.3, Kite 426.7 after the 1:5 split). Ratios inside a day
  are unaffected; to compare levels with `stock_prices`, rescale with `corporate_actions` after
  `fetched_on`.
- **Survivors only.** Kite has no delisted stocks; every backtest on this data says so.
- **No login, no run.** The hourly `run.sh kite_bars` exits quietly without that day's login and
  starts no new stock after 23:50 UTC. Progress lives in the manifest, so it resumes anywhere.
- **Paths.** `INTRADAY_DIR` derives from `DB_PATH` (override `ALPHA_INTRADAY`), so a worktree with
  `ALPHA_DB` set never grows a second archive. `data/` is gitignored; `run.sh sweep` never touches it.
- **Backup.** The archive can be refetched (~4 days), so it is synced to Drive weekly once
  compacted; the daily summary table is in the nightly DB backup.

## Rejected
- SQLite for the bars (32–102 GB against 26 GB free on the day). A vector DB (above).
- One file per stock per day (~7 M tiny files). Keeping OHLC per minute (2× the size, unused).
