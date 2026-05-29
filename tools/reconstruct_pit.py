"""
Alpha Signal v2 — Point-in-time signal reconstruction for backtesting.

For each monthly eval date, slices raw data to "what was knowable on that date"
given filing lags, then computes signals. Writes to daily_snapshots_pit table
(separate from daily_snapshots, which is the live snapshot stream).

Filing lags (from C13b reconstruction protocol):
    Annual fundamentals    → 75 days after period_end (SEBI deadline)
    Quarterly fundamentals → 60 days after period_end
    Shareholding           → 21 days after period_end

Signals reconstructed:
    piotroski_f, cf_accruals, bs_accruals, earnings_persistence,
    earnings_yield, book_to_price, promoter_qoq, mom_6m, mom_12m,
    forensic (m_score, z_score)

Skipped (data gaps documented):
    consensus_signal — analyst_consensus is snapshot-only; forecast_history-based
                       reconstruction is a follow-up
    smart_money      — bulk_deals depth is only 1 month
    sentiment_7d     — defer (need to assess news_articles depth)
    insider_signal   — already accumulates via signals/insider_signal.py
                       (29 monthly snapshots back to 2024-04)

Usage:
    python -m tools.reconstruct_pit                  # 7 monthly dates, all signals
    python -m tools.reconstruct_pit --months 12      # extend lookback
    python -m tools.reconstruct_pit --dry-run        # compute but don't write
    python -m tools.reconstruct_pit --signal piotroski   # one signal only
"""

import argparse
import calendar
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from db import get_db, read_sql, upsert_df
from config import SCREEN, BACKTEST

# ── Filing lags ──
ANNUAL_LAG = 75
QUARTERLY_LAG = 60
SHAREHOLDING_LAG = 21

# ── Momentum windows (must match signals/momentum.py) ──
SKIP_DAYS = BACKTEST["momentum_skip_days"]      # 22
WINDOW_6M = BACKTEST["momentum_6m_days"]        # 154
WINDOW_12M = BACKTEST["momentum_12m_days"]      # 252

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])


# ─────────────────────────── Schema ───────────────────────────

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS daily_snapshots_pit (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    snapshot_date    TEXT NOT NULL,
    cap_tier         TEXT,
    close_price      REAL,
    piotroski_f      INTEGER,
    cf_accruals      REAL,
    bs_accruals      REAL,
    earnings_persistence REAL,
    earnings_yield   REAL,
    book_to_price    REAL,
    promoter_qoq     REAL,
    promoter_trend_4q REAL,
    pledge_quality   REAL,
    mom_6m           REAL,
    mom_12m          REAL,
    mom_composite    REAL,
    macd_bullish     INTEGER,
    position_52w     REAL,
    avg_delivery_pct_30d REAL,
    delivery_anomaly_z REAL,
    fwd_return_20d   REAL,
    m_score          REAL,
    z_score          REAL,
    roe              REAL,
    roa              REAL,
    debt_to_equity   REAL,
    profit_margin    REAL,
    revenue_growth_yoy REAL,
    eps_growth_yoy   REAL,
    pt_revision_yoy  REAL,
    eps_revision_yoy REAL,
    consensus_signal_combined REAL,
    value_composite  REAL,
    quality_composite REAL,
    growth_composite REAL,
    -- Behavior tier — added 2026-05-24 (audit: were missing PIT helpers)
    insider_score    REAL,
    sentiment_7d     REAL,
    -- Track 2.2b — Financial sub-model (Banks + NBFCs only)
    financial_signal REAL,
    reconstructed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (sid, snapshot_date)
);
CREATE INDEX IF NOT EXISTS idx_pit_date ON daily_snapshots_pit(snapshot_date);
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

PIT_COLUMNS = [
    "sid", "snapshot_date", "cap_tier", "close_price",
    "piotroski_f", "cf_accruals", "bs_accruals", "earnings_persistence",
    "earnings_yield", "book_to_price",
    "promoter_qoq", "promoter_trend_4q", "pledge_quality",
    "mom_6m", "mom_12m", "mom_composite", "macd_bullish",
    "position_52w", "avg_delivery_pct_30d", "delivery_anomaly_z",
    "fwd_return_20d",
    "m_score", "z_score",
    # Tier 2 — fundamentals
    "roe", "roa", "debt_to_equity", "profit_margin",
    "revenue_growth_yoy", "eps_growth_yoy",
    # Tier 2 — consensus
    "pt_revision_yoy", "eps_revision_yoy", "consensus_signal_combined",
    # Tier 2 — composites
    "value_composite", "quality_composite", "growth_composite",
    # Tier 3 — unblocked
    "pt_upside", "bulk_deal_signal",
    # Tier 4 — new signal classes
    "short_selling_signal",
    # Tier 4 — quality + sentiment
    "earnings_beat_rate", "news_volume_7d",
    # Track 3 cluster (plan 0003) — sector-narrative-derived factors
    "revenue_cv_5y", "relative_turnover", "relative_growth", "share_momentum",
    # Behavior tier — added 2026-05-24 (audit: were missing PIT helpers)
    "insider_score",    # net-weighted insider buys/sells, last 90d
    "sentiment_7d",     # VADER compound score, mean over last 7d articles
    # Track 3 standalone factors
    "ccc",
    "margin_slope",
    "wc_intensity",
    "interest_coverage",
    "roic",
    "fcf_yield",
    "roiic",
    # Forensic / capital-allocation batch (plan 0002 §3.2.1)
    "dso_change_yoy", "dio_change_yoy", "nwc_to_revenue",
    "sloan_accruals_full", "sga_to_revenue_change",
    "fcf_margin", "capex_to_dep", "goodwill_to_assets",
    "debt_structure", "asset_tangibility",
    # Plan 0005 Phase E "full fix" — composite signals so historical PIT
    # replay can validate all 8 screener inputs end-to-end (not just the 4
    # that were derivable from raw cols).
    "accruals_signal", "promoter_signal", "forensic_penalty", "smart_money_score",
    # Track 2.2b (2026-05-29) — Financial sub-model. NULL for non-financials;
    # only Banks + NBFCs get a score. Scope clarification in ADR 0030.
    "financial_signal",
]


# ── Validation guardrails per signal ──
# (min_val, max_val, allow_nan). None means no bound.
VALIDATION_RANGES = {
    "close_price":           (0.01, 1_000_000, True),
    "piotroski_f":           (0, 9, True),
    "cf_accruals":           (-100, 100, True),
    "bs_accruals":           (-10, 10, True),
    "earnings_persistence":  (0, 1000, True),
    "earnings_yield":        (-10, 10, True),
    "book_to_price":         (-100, 1000, True),
    "promoter_qoq":          (-100, 100, True),
    "promoter_trend_4q":     (-100, 100, True),
    "pledge_quality":        (0, 1, True),
    "mom_6m":                (-100, 100, True),
    "mom_12m":               (-100, 100, True),
    "mom_composite":         (0, 1, True),
    "macd_bullish":          (0, 1, True),
    "position_52w":          (0, 1, True),
    "avg_delivery_pct_30d":  (0, 100, True),
    "delivery_anomaly_z":    (-5, 5, True),  # clip extreme z
    "fwd_return_20d":        (-1, 5, True),  # cap extreme returns
    "m_score":               (-20, 20, True),
    "z_score":               (-50, 100, True),
    # Tier 2 — fundamentals (TTM ratios; allow negatives for distressed names)
    "roe":                   (-200, 1000, True),   # negative-equity stocks → NaN
    "roa":                   (-100, 200, True),
    "debt_to_equity":        (0, 50, True),        # negative-equity → NaN
    "profit_margin":         (-100, 100, True),
    "revenue_growth_yoy":    (-100, 1000, True),
    "eps_growth_yoy":        (-1000, 1000, True),
    # Tier 2 — consensus
    "pt_revision_yoy":       (-100, 500, True),
    "eps_revision_yoy":      (-500, 500, True),
    "consensus_signal_combined": (-100, 500, True),
    # Tier 2 — composites (within-tier rank, in [0, 1])
    "value_composite":       (0, 1, True),
    "quality_composite":     (0, 1, True),
    "growth_composite":      (0, 1, True),
    # Tier 3
    "pt_upside":             (-1, 5, True),     # -100% (zero PT) to +500%
    "bulk_deal_signal":      (-100, 100, True), # net buy value normalized
    "short_selling_signal":  (0, 10, True),     # short qty / avg volume ratio
    # Tier 4 — quality + sentiment
    "earnings_beat_rate":    (0, 1, True),      # fraction of last-N quarters beating
    "news_volume_7d":        (0, 100, True),    # article count in last 7d
    "insider_score":         (-1, 1, True),     # weighted net buys/sells, clipped
    "sentiment_7d":          (-1, 1, True),     # VADER compound score, mean over 7d
    "financial_signal":      (-3, 3, True),     # z-composite, clipped to ±3 (signals.financial_signal)
    # Track 3 cluster (plan 0003)
    "revenue_cv_5y":         (0, 50, True),     # CV; >50 means mean ~ 0
    "relative_turnover":     (0, 20, True),     # ratio vs sector p50
    "relative_growth":       (-2, 5, True),     # growth − sector_median
    "share_momentum":        (-1, 5, True),     # share[t]/share[t-90d] − 1
    # Cash conversion cycle — in days. Real-world spans -100 to +400d.
    # Pad bounds to (-365, 730) to keep distressed outliers (huge unpaid
    # payables, near-zero turnover) without letting them dominate the rank.
    "ccc":                   (-365, 730, True),
    # Operating margin slope — percentage-points/year. ±50pp/yr is a
    # massive shift; anything beyond is data error.
    "margin_slope":          (-50, 50, True),
    # Working capital intensity — (Recv + Inv − Pay) / Sales. Real-world
    # band roughly -0.5 to +2; pad to (-2, 5) for distressed names.
    "wc_intensity":          (-2, 5, True),
    # Interest coverage — capped to ±200 in the signal itself.
    "interest_coverage":     (-200, 200, True),
    # ROIC — 3y median NOPAT/IC. Signal-side filter keeps roic > 0; pad bounds
    # to (-2, 5) so anything outside (200% return on capital) is data error.
    "roic":                  (-2, 5, True),
    # FCF Yield — 3y median FCF / market_cap. Real-world band ±0.5; pad to
    # (-2, 2) for negative-FCF growth names + tiny-cap blowups.
    "fcf_yield":             (-2, 2, True),
    # ROIIC — 5y marginal NOPAT/IC. Capped to ±5 in the scorer; range is
    # mirrored here so the validator is a no-op except for inf scrubbing.
    "roiic":                 (-5, 5, True),
    # Forensic / capital-allocation batch (§3.2.1) — bounds are intentionally
    # wide to keep distressed outliers without letting them dominate ranks.
    "dso_change_yoy":        (-365, 365, True),    # days
    "dio_change_yoy":        (-365, 365, True),    # days
    "nwc_to_revenue":        (-2, 5, True),        # ratio
    "sloan_accruals_full":   (-1, 1, True),        # ratio of avg total assets
    "sga_to_revenue_change": (-1, 1, True),        # YoY pp change in SGA intensity
    "fcf_margin":            (-2, 2, True),        # 3y median FCF/Sales
    "capex_to_dep":          (-20, 20, True),      # capped in scorer to ±20
    "goodwill_to_assets":    (0, 1, True),         # bounded ratio
    "debt_structure":        (0, 1, True),         # LT/total share
    "asset_tangibility":     (0, 1, True),         # Net Block/total
    # Plan 0005 Phase E composites (used by screener directly)
    "accruals_signal":       (0, 1, True),         # within-tier percentile blend
    "promoter_signal":       (0, 1, True),         # within-tier percentile blend
    "forensic_penalty":      (-1, 0, True),        # 0 / -0.10 / -0.20 / -0.30
    "smart_money_score":     (0, 100, True),       # min-max-normalised 0-100
    # Sector signals (separate table)
    "regulatory_score":      (-10, 10, True),
    "macro_score":           (-10, 10, True),
}


def _validate_and_clean(df, columns):
    """Apply per-column range gates. Out-of-range → NaN. Returns (df, summary).

    summary rows = {column: {n_valid, n_nan, n_out_of_range, min, max}}
    """
    summary = {}
    for col in columns:
        if col not in df.columns:
            continue
        rule = VALIDATION_RANGES.get(col)
        if rule is None:
            continue
        min_v, max_v, _allow_nan = rule
        n_total = len(df)
        before_nan = df[col].isna().sum()

        # Drop infinities first
        df[col] = df[col].replace([np.inf, -np.inf], np.nan)

        if min_v is not None and max_v is not None:
            out_of_range = ((df[col] < min_v) | (df[col] > max_v)).sum()
            df.loc[(df[col] < min_v) | (df[col] > max_v), col] = np.nan
        else:
            out_of_range = 0

        after_nan = df[col].isna().sum()
        n_valid = n_total - after_nan
        summary[col] = {
            "valid": int(n_valid),
            "nan": int(after_nan),
            "out_of_range": int(out_of_range),
            "min": float(df[col].min()) if n_valid else None,
            "max": float(df[col].max()) if n_valid else None,
        }
    return df, summary


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


# ─────────────────── Knowable-data slicers ───────────────────

def knowable_quarterly(qi, eval_date, lag=QUARTERLY_LAG):
    """Return rows where end_date + lag <= eval_date."""
    cutoff = (eval_date - timedelta(days=lag)).isoformat()
    return qi[qi["end_date"] <= cutoff].copy()


def knowable_annual(df, eval_date, lag=ANNUAL_LAG):
    cutoff = (eval_date - timedelta(days=lag)).isoformat()
    return df[df["end_date"] <= cutoff].copy()


def knowable_shareholding(sh, eval_date, lag=SHAREHOLDING_LAG):
    cutoff = (eval_date - timedelta(days=lag)).isoformat()
    return sh[sh["end_date"] <= cutoff].copy()


def knowable_screener(fund, eval_date, lag=ANNUAL_LAG):
    """Filter fundamentals_screener long-format rows knowable at eval_date."""
    cutoff = (eval_date - timedelta(days=lag)).isoformat()
    return fund[fund["period_end"] <= cutoff].copy()


def prices_through(prices, eval_date):
    cutoff = eval_date.isoformat()
    return prices[prices["date"] <= cutoff].copy()


def apply_pit_adjustments(prices_pit, adjustments, eval_date):
    """Add `adj_close` column to prices_pit using PIT-strict corporate adjustment.

    Only events with ex_date <= eval_date are visible. For each (sid, date),
    adj_close = close × Π factor[e] for e where e.sid == sid AND date < e.ex_date <= eval_date.

    Vectorized per-sid via reverse cumprod + searchsorted — O(N log M) per sid.
    """
    snap_str = eval_date.isoformat()
    visible = adjustments[adjustments["ex_date"] <= snap_str]
    out = prices_pit.copy()

    if visible.empty:
        out["adj_close"] = out["close"]
        return out

    out["adj_close"] = out["close"].astype(float)
    events_by_sid = dict(tuple(visible.groupby("sid")))

    closes = out["close"].astype(float).values
    adj_factors = np.ones(len(out), dtype=float)

    for sid, idxs in out.groupby("sid").indices.items():
        if sid not in events_by_sid:
            continue
        g = events_by_sid[sid].sort_values("ex_date")
        ex_dates = g["ex_date"].values
        factors = g["factor"].values.astype(float)

        n = len(factors)
        rev_cum = np.empty(n + 1)
        rev_cum[n] = 1.0
        for i in range(n - 1, -1, -1):
            rev_cum[i] = factors[i] * rev_cum[i + 1]

        sid_dates = out["date"].values[idxs]
        # side='right' → first event with ex_date > date; product of factors[idx:] applies
        idx_arr = np.searchsorted(ex_dates, sid_dates, side="right")
        adj_factors[idxs] = rev_cum[idx_arr]

    out["adj_close"] = (closes * adj_factors).round(4)
    return out


# ─────────────────────── Per-signal PIT calc ───────────────────────

def pit_close_price(prices_pit):
    """Most recent close per sid as of eval_date."""
    last = (prices_pit.sort_values(["sid", "date"])
            .groupby("sid")
            .tail(1)[["sid", "close"]])
    return last.rename(columns={"close": "close_price"})


def pit_piotroski(stocks, qi_pit, bs_pit, cf_pit):
    """Reuse signals.piotroski._compute_scores against pre-filtered inputs."""
    from signals.piotroski import _compute_scores
    df = _compute_scores(stocks, qi_pit, bs_pit, cf_pit)
    keep = ["sid", "f_score"]
    out = df[keep].rename(columns={"f_score": "piotroski_f"})
    return out


def pit_accruals(stocks, qi_pit, bs_pit, cf_pit):
    """Reuse signals.accruals._compute_scores. Keeps the composite `accruals_signal`
    alongside raw cf_/bs_ ratios so PIT replay can validate the full screener input."""
    from signals.accruals import _compute_scores
    df = _compute_scores(stocks, qi_pit, bs_pit, cf_pit)
    out = df[["sid", "cf_accruals_ratio", "bs_accruals_ratio", "earnings_persistence", "accruals_signal"]].copy()
    out = out.rename(columns={
        "cf_accruals_ratio": "cf_accruals",
        "bs_accruals_ratio": "bs_accruals",
    })
    return out


def pit_promoter(stocks, sh_pit):
    """Reuse signals.promoter._compute_scores. Keeps the composite `promoter_signal`."""
    from signals.promoter import _compute_scores
    df = _compute_scores(stocks, sh_pit)
    cols = ["sid", "promoter_qoq"]
    if "promoter_signal" in df.columns:
        cols.append("promoter_signal")
    return df[cols].copy()


def pit_forensic(stocks, qi_pit, bs_pit, cf_pit):
    """Reuse signals.forensic._compute_scores. Keeps the composite `forensic_penalty`."""
    from signals.forensic import _compute_scores
    financial_sids = set(stocks[stocks["sector"].isin(FINANCIAL_SECTORS)]["sid"])
    df = _compute_scores(stocks, financial_sids, qi_pit, bs_pit, cf_pit)
    keep_cols = ["sid"]
    for c in ("m_score", "z_score"):
        if c in df.columns:
            keep_cols.append(c)
    if "penalty" in df.columns:
        out = df[keep_cols + ["penalty"]].copy()
        out = out.rename(columns={"penalty": "forensic_penalty"})
        return out
    return df[keep_cols].copy()


def pit_smart_money(stocks, bulk_pit, prices_pit, eval_date, window_days=90):
    """Reuse signals.smart_money._compute_scores against date-filtered inputs.
    Produces smart_money_score for PIT. Bulk + delivery come from raw stores
    already loaded by the orchestrator. Returns DataFrame[sid, smart_money_score]."""
    from signals.smart_money import _compute_scores
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    cutoff = (pd.Timestamp(eval_str) - pd.Timedelta(days=window_days)).strftime("%Y-%m-%d")

    bulk = bulk_pit[(bulk_pit["deal_date"] >= cutoff) & (bulk_pit["deal_date"] <= eval_str)] \
        if bulk_pit is not None and not bulk_pit.empty else pd.DataFrame(
            columns=["sid", "symbol", "client_name", "buy_sell", "quantity", "price", "deal_date"]
        )
    if "delivery_pct" in prices_pit.columns:
        delivery = prices_pit[(prices_pit["date"] >= cutoff) & (prices_pit["date"] <= eval_str)][
            ["sid", "date", "delivery_pct", "close"]
        ].dropna(subset=["delivery_pct"])
    else:
        delivery = pd.DataFrame(columns=["sid", "date", "delivery_pct", "close"])

    df = _compute_scores(stocks[["sid", "cap_tier"]], bulk, delivery)
    if "smart_money_score" not in df.columns:
        return pd.DataFrame(columns=["sid", "smart_money_score"])
    return df[["sid", "smart_money_score"]].copy()


def pit_earnings_yield(qi_pit, close_df):
    """TTM EPS as of eval_date / close as of eval_date."""
    qi = qi_pit.copy()
    has_consol = set(qi[qi["reporting"] == "consolidated"]["sid"])
    qi = qi[
        ((qi["sid"].isin(has_consol)) & (qi["reporting"] == "consolidated"))
        | (~qi["sid"].isin(has_consol))
    ]

    rows = []
    for sid, group in qi.groupby("sid"):
        g = group.sort_values("end_date")
        if len(g) < 4:
            continue
        eps_sum = g.tail(4)["eps"].sum()
        if pd.notna(eps_sum):
            rows.append({"sid": sid, "ttm_eps": eps_sum})

    eps_df = pd.DataFrame(rows)
    if eps_df.empty:
        return pd.DataFrame(columns=["sid", "earnings_yield"])

    merged = eps_df.merge(close_df, on="sid", how="left")
    merged["earnings_yield"] = np.where(
        (merged["close_price"].notna()) & (merged["close_price"] > 0),
        (merged["ttm_eps"] / merged["close_price"]).round(6),
        np.nan,
    )
    return merged[["sid", "earnings_yield"]]


def pit_book_to_price(bs_pit, close_df):
    """Latest known book equity per share / close price as of eval_date.

    Per-share book value uses shares_outstanding from same balance sheet row.
    """
    if bs_pit.empty:
        return pd.DataFrame(columns=["sid", "book_to_price"])

    latest_bs = (bs_pit.sort_values(["sid", "end_date"])
                 .groupby("sid")
                 .tail(1)[["sid", "total_equity", "shares_outstanding"]])

    latest_bs["book_per_share"] = np.where(
        (latest_bs["shares_outstanding"].notna()) & (latest_bs["shares_outstanding"] > 0),
        latest_bs["total_equity"] / latest_bs["shares_outstanding"],
        np.nan,
    )

    merged = latest_bs.merge(close_df, on="sid", how="left")
    merged["book_to_price"] = np.where(
        (merged["close_price"].notna()) & (merged["close_price"] > 0)
        & (merged["book_per_share"].notna()),
        (merged["book_per_share"] / merged["close_price"]).round(6),
        np.nan,
    )
    return merged[["sid", "book_to_price"]]


def pit_position_52w(prices_pit, eval_date):
    """For each sid, position within trailing 252 trading days.
    Formula: (close - 52w_low) / (52w_high - 52w_low) — values in [0, 1].
    NaN if <60 trading days of price history (insufficient).
    Uses adj_close so a stock split inside the window doesn't artificially expand the range.
    """
    rows = []
    price_col = "adj_close" if "adj_close" in prices_pit.columns else "close"
    for sid, group in prices_pit.groupby("sid"):
        g = group.sort_values("date")
        # Take last 252 trading days
        recent = g.tail(252)
        if len(recent) < 60:
            rows.append({"sid": sid})
            continue
        closes = recent[price_col].values
        last = closes[-1]
        lo, hi = closes.min(), closes.max()
        if hi <= lo or hi <= 0:
            rows.append({"sid": sid})
            continue
        rows.append({"sid": sid, "position_52w": round((last - lo) / (hi - lo), 4)})
    return pd.DataFrame(rows)


def pit_avg_delivery(prices_pit, window=30):
    """Mean delivery_pct over trailing N trading days as of eval_date."""
    if "delivery_pct" not in prices_pit.columns:
        return pd.DataFrame(columns=["sid", "avg_delivery_pct_30d"])
    rows = []
    for sid, group in prices_pit.groupby("sid"):
        g = group.sort_values("date").tail(window)
        if len(g) < window // 2:  # require at least half the window
            rows.append({"sid": sid})
            continue
        m = g["delivery_pct"].dropna().mean()
        if pd.notna(m):
            rows.append({"sid": sid, "avg_delivery_pct_30d": round(float(m), 2)})
        else:
            rows.append({"sid": sid})
    return pd.DataFrame(rows)


def pit_delivery_anomaly_z(prices_pit, window=90):
    """Today's delivery % vs 90-day mean, normalized by 90-day std."""
    if "delivery_pct" not in prices_pit.columns:
        return pd.DataFrame(columns=["sid", "delivery_anomaly_z"])
    rows = []
    for sid, group in prices_pit.groupby("sid"):
        g = group.sort_values("date").tail(window)
        if len(g) < 30:
            rows.append({"sid": sid})
            continue
        deliv = g["delivery_pct"].dropna()
        if len(deliv) < 30:
            rows.append({"sid": sid})
            continue
        latest = deliv.iloc[-1]
        baseline = deliv.iloc[:-1]
        mean, std = baseline.mean(), baseline.std()
        if std and std > 0 and pd.notna(mean):
            z = (latest - mean) / std
            rows.append({"sid": sid, "delivery_anomaly_z": round(float(z), 3)})
        else:
            rows.append({"sid": sid})
    return pd.DataFrame(rows)


def pit_pledge_quality(stocks, sh_pit):
    """1 - (latest pledge_pct / 100). Higher is better."""
    rows = []
    sh_by_sid = dict(list(sh_pit.groupby("sid")))
    for sid in stocks["sid"]:
        g = sh_by_sid.get(sid)
        if g is None or g.empty:
            rows.append({"sid": sid})
            continue
        latest = g.sort_values("end_date").iloc[-1]
        pledge = latest.get("pledge_pct")
        if pd.notna(pledge):
            rows.append({"sid": sid, "pledge_quality": round(1.0 - float(pledge) / 100.0, 4)})
        else:
            rows.append({"sid": sid})
    return pd.DataFrame(rows)


def pit_promoter_trend_4q(stocks, sh_pit):
    """Latest promoter_pct − value 5 quarters earlier (1-year trend). Needs ≥5 quarters."""
    rows = []
    sh_by_sid = dict(list(sh_pit.groupby("sid")))
    for sid in stocks["sid"]:
        g = sh_by_sid.get(sid)
        if g is None or len(g) < 5:
            rows.append({"sid": sid})
            continue
        g = g.sort_values("end_date")
        latest = g.iloc[-1]["promoter_pct"]
        prior = g.iloc[-5]["promoter_pct"]
        if pd.notna(latest) and pd.notna(prior):
            rows.append({"sid": sid, "promoter_trend_4q": round(float(latest) - float(prior), 4)})
        else:
            rows.append({"sid": sid})
    return pd.DataFrame(rows)


def pit_macd_bullish(prices_pit):
    """MACD bullish state: 12-EMA − 26-EMA > 9-EMA-of-MACD. Binary 1/0.
    Needs ≥35 days of prices. Uses adj_close so a split inside the window
    doesn't fake a trend break.
    """
    rows = []
    price_col = "adj_close" if "adj_close" in prices_pit.columns else "close"
    for sid, group in prices_pit.groupby("sid"):
        g = group.sort_values("date").tail(252)
        if len(g) < 35:
            rows.append({"sid": sid})
            continue
        closes = g[price_col].astype(float)
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        if pd.isna(macd.iloc[-1]) or pd.isna(signal.iloc[-1]):
            rows.append({"sid": sid})
            continue
        bullish = 1 if macd.iloc[-1] > signal.iloc[-1] else 0
        rows.append({"sid": sid, "macd_bullish": bullish})
    return pd.DataFrame(rows)


def pit_fwd_return_20d(eval_date, raw_prices_full):
    """20-trading-day forward return per sid.

    Uses the FULL price history (not the PIT-filtered slice) since we need
    prices AFTER eval_date. NULL if 20 trading days haven't elapsed yet.
    """
    rows = []
    eval_str = eval_date.isoformat()

    # For each sid, find the close at the trading day on/after eval_date
    # and the close 20 trading days later.
    for sid, group in raw_prices_full.groupby("sid"):
        g = group.sort_values("date")
        # First trading day >= eval_date
        anchor_idx = g["date"].searchsorted(eval_str)
        if anchor_idx >= len(g):
            rows.append({"sid": sid})
            continue
        target_idx = anchor_idx + 20
        if target_idx >= len(g):
            rows.append({"sid": sid})
            continue
        p0 = g.iloc[anchor_idx]["close"]
        p1 = g.iloc[target_idx]["close"]
        if p0 > 0 and p1 > 0:
            rows.append({"sid": sid, "fwd_return_20d": round(float(p1 / p0 - 1), 4)})
        else:
            rows.append({"sid": sid})
    return pd.DataFrame(rows)


def pit_mom_composite(df_with_mom):
    """Equal-weight composite of mom_6m + mom_12m, ranked within cap_tier.

    Operates on a DataFrame that already has mom_6m, mom_12m, cap_tier columns
    (i.e. the assembled per-eval-date frame). Within-tier rank → [0, 1].
    """
    out = df_with_mom[["sid", "cap_tier", "mom_6m", "mom_12m"]].copy()
    # Within-tier percentile rank for each component
    out["_r6"] = out.groupby("cap_tier")["mom_6m"].rank(pct=True)
    out["_r12"] = out.groupby("cap_tier")["mom_12m"].rank(pct=True)
    # Equal-weight composite: 0.5/0.5 with NaN tolerance
    has6 = out["_r6"].notna()
    has12 = out["_r12"].notna()
    both = has6 & has12
    only6 = has6 & ~has12
    only12 = ~has6 & has12

    out["mom_composite"] = np.nan
    out.loc[both, "mom_composite"] = 0.5 * out.loc[both, "_r6"] + 0.5 * out.loc[both, "_r12"]
    out.loc[only6, "mom_composite"] = out.loc[only6, "_r6"]
    out.loc[only12, "mom_composite"] = out.loc[only12, "_r12"]
    out["mom_composite"] = out["mom_composite"].round(4)
    return out[["sid", "mom_composite"]]


def _ttm_qi_value(qi_g, column):
    """Sum of last 4 quarterly values for `column` in pre-sorted qi_g.
    Returns None if <4 quarters."""
    if qi_g is None or len(qi_g) < 4:
        return None
    last4 = qi_g.sort_values("end_date").tail(4)
    val = last4[column].sum()
    if pd.isna(val):
        return None
    return float(val)


def _prior_ttm_qi_value(qi_g, column):
    """Sum of quarters [-8:-4] (prior year TTM). Needs >=8 quarters."""
    if qi_g is None or len(qi_g) < 8:
        return None
    prior4 = qi_g.sort_values("end_date").iloc[-8:-4]
    val = prior4[column].sum()
    if pd.isna(val):
        return None
    return float(val)


def pit_quality_fundamentals(stocks, qi_pit, bs_pit, financial_sids):
    """ROE, ROA, debt_to_equity, profit_margin per stock as of eval_date.

    All TTM-based. Uses _consolidated_ qi if present.
    debt_to_equity is NaN for financial-sector stocks (D/E meaningless for banks).
    """
    # Filter qi to consolidated when available per stock
    has_consol = set(qi_pit[qi_pit["reporting"] == "consolidated"]["sid"])
    qi = qi_pit[
        ((qi_pit["sid"].isin(has_consol)) & (qi_pit["reporting"] == "consolidated"))
        | (~qi_pit["sid"].isin(has_consol))
    ]
    qi_by_sid = dict(list(qi.groupby("sid")))
    bs_by_sid = dict(list(bs_pit.groupby("sid")))

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid}
        qi_g = qi_by_sid.get(sid)
        bs_g = bs_by_sid.get(sid)

        ttm_ni = _ttm_qi_value(qi_g, "net_income")
        ttm_rev = _ttm_qi_value(qi_g, "revenue")

        # Latest BS row (already PIT-filtered)
        bs_latest = None
        if bs_g is not None and len(bs_g) >= 1:
            bs_latest = bs_g.sort_values("end_date").iloc[-1]

        if bs_latest is not None and ttm_ni is not None:
            equity = bs_latest.get("total_equity")
            assets = bs_latest.get("total_assets")
            debt = bs_latest.get("total_debt")

            if pd.notna(equity) and equity > 0:
                row["roe"] = round(ttm_ni / equity * 100, 2)
                if pd.notna(debt) and sid not in financial_sids:
                    row["debt_to_equity"] = round(debt / equity, 3)

            if pd.notna(assets) and assets > 0:
                row["roa"] = round(ttm_ni / assets * 100, 2)

        if ttm_ni is not None and ttm_rev is not None and ttm_rev > 0:
            row["profit_margin"] = round(ttm_ni / ttm_rev * 100, 2)

        rows.append(row)
    return pd.DataFrame(rows)


def pit_growth_fundamentals(stocks, qi_pit):
    """Revenue YoY and EPS YoY as of eval_date.

    Uses TTM (latest 4Q) vs prior TTM (quarters -8 to -4).
    """
    has_consol = set(qi_pit[qi_pit["reporting"] == "consolidated"]["sid"])
    qi = qi_pit[
        ((qi_pit["sid"].isin(has_consol)) & (qi_pit["reporting"] == "consolidated"))
        | (~qi_pit["sid"].isin(has_consol))
    ]
    qi_by_sid = dict(list(qi.groupby("sid")))

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid}
        qi_g = qi_by_sid.get(sid)
        if qi_g is None or len(qi_g) < 8:
            rows.append(row)
            continue

        ttm_rev = _ttm_qi_value(qi_g, "revenue")
        prior_rev = _prior_ttm_qi_value(qi_g, "revenue")
        if ttm_rev is not None and prior_rev is not None and prior_rev != 0:
            row["revenue_growth_yoy"] = round((ttm_rev / abs(prior_rev) - 1) * 100, 2)

        ttm_eps = _ttm_qi_value(qi_g, "eps")
        prior_eps = _prior_ttm_qi_value(qi_g, "eps")
        if ttm_eps is not None and prior_eps is not None and abs(prior_eps) > 0.01:
            row["eps_growth_yoy"] = round((ttm_eps / abs(prior_eps) - 1) * 100, 2)

        rows.append(row)
    return pd.DataFrame(rows)


def pit_consensus(stocks, fh_pit):
    """EPS revision YoY + combined consensus signal.

    `pt_revision_yoy` was DROPPED 2026-05-23 — `forecast_history.metric='price'`
    is current-close masquerading as PT, so its YoY = 1-year price return, not
    PT revision. The combined signal is now eps-revision only until the
    `analyst_consensus_snapshots` monthly history accumulates ≥12 months
    (calendar: 2027-05). See memory `forecast_history_price_contaminated`.
    """
    if fh_pit.empty:
        return pd.DataFrame(columns=["sid", "pt_revision_yoy", "eps_revision_yoy", "consensus_signal_combined"])

    fh_by_sid_metric = {}
    for (sid, metric), group in fh_pit.groupby(["sid", "metric"]):
        fh_by_sid_metric[(sid, metric)] = group.sort_values("date")

    def _yoy(series_df):
        """For a per-metric, per-sid sorted DataFrame: return YoY % change between latest and prior-year snapshot."""
        if series_df is None or len(series_df) < 2:
            return None
        latest = series_df.iloc[-1]
        latest_dt = latest["date"]
        # Find prior snapshot ~12 months earlier (between 9 and 18 months prior)
        latest_year = int(latest_dt[:4])
        prior_candidates = series_df[
            (series_df["date"] >= f"{latest_year - 2}-01-01")
            & (series_df["date"] < f"{latest_year}-{latest_dt[5:]}")
        ]
        if prior_candidates.empty:
            return None
        # Pick the one closest to latest_dt − 1 year
        target_year = latest_year - 1
        prior = prior_candidates.iloc[
            (prior_candidates["date"].str[:4].astype(int) - target_year).abs().argmin()
        ]
        latest_v = latest["value"]
        prior_v = prior["value"]
        if pd.isna(latest_v) or pd.isna(prior_v) or abs(prior_v) < 1e-9:
            return None
        return round((float(latest_v) / abs(float(prior_v)) - 1) * 100, 2)

    rows = []
    for sid in stocks["sid"]:
        row = {"sid": sid, "pt_revision_yoy": None}  # always NULL; data source contaminated
        eps_yoy = _yoy(fh_by_sid_metric.get((sid, "eps")))
        if eps_yoy is not None:
            row["eps_revision_yoy"] = eps_yoy
            row["consensus_signal_combined"] = eps_yoy
        rows.append(row)
    return pd.DataFrame(rows)


def _within_tier_rank_composite(df, components, name):
    """Generic NaN-tolerant within-cap_tier rank composite.

    components: list of (column_name, weight)
    Returns DataFrame with [sid, name].

    For each stock: rank each component within its tier, then weighted average
    of ranks where the rank exists. If all components are NaN, output is NaN.
    """
    cols = [c for c, _ in components]
    out = df[["sid", "cap_tier"] + cols].copy()
    for col in cols:
        out[f"_r_{col}"] = out.groupby("cap_tier")[col].rank(pct=True)

    weighted_score = pd.Series(0.0, index=out.index)
    weight_sum = pd.Series(0.0, index=out.index)
    for col, w in components:
        rank_col = out[f"_r_{col}"]
        has = rank_col.notna()
        weighted_score[has] += w * rank_col[has]
        weight_sum[has] += w

    composite = weighted_score / weight_sum.replace(0, np.nan)
    out[name] = composite.round(4)
    return out[["sid", name]]


def pit_value_composite(df_in_progress):
    """v1 screener: 40% earnings_yield + 35% book_to_price + 25% position_52w."""
    return _within_tier_rank_composite(df_in_progress, [
        ("earnings_yield", 0.40),
        ("book_to_price", 0.35),
        ("position_52w", 0.25),
    ], "value_composite")


def pit_quality_composite(df_in_progress):
    """v1 screener: 45% roe + 30% inverse-debt_to_equity + 25% profit_margin.

    For ranking, low D/E is better — so we rank ascending (lower percentile = higher rank).
    Implementation: rank `−debt_to_equity` so high values (low D/E) get high rank.
    """
    df = df_in_progress.copy()
    df["_inv_de"] = -df["debt_to_equity"]  # invert so higher = better
    return _within_tier_rank_composite(df, [
        ("roe", 0.45),
        ("_inv_de", 0.30),
        ("profit_margin", 0.25),
    ], "quality_composite")


def pit_growth_composite(df_in_progress):
    """v1 screener: 50% revenue_growth_yoy + 50% eps_growth_yoy."""
    return _within_tier_rank_composite(df_in_progress, [
        ("revenue_growth_yoy", 0.50),
        ("eps_growth_yoy", 0.50),
    ], "growth_composite")


def pit_pt_upside(stocks, fh_pit, close_df, acs_pit=None):
    """Implied upside from analyst price target.

    Source priority (most recent wins):
      1. analyst_consensus_snapshots — monthly snapshots of Yahoo's aggregate.
         Available from 2026-05 onwards. Most recent and most accurate.
      2. forecast_history (metric='price') — Tickertape year-end snapshots,
         ~1 per stock per year from 2022 onwards. Real PTs, but stale by up
         to 12 months. Used when no consensus_snapshots row precedes eval_date.

    PTs are episodic — sell-side analysts revise quarterly at best. The two
    sources combined cover (a) recent revisions (yfinance monthly) and
    (b) long-horizon history for backtest (Tickertape year-end). Daily price
    data masquerading as PT is filtered out at ingestion (see HANDOFF
    2026-05-22 for the rationale).
    """
    rows = []
    if acs_pit is not None and not acs_pit.empty:
        latest_acs = (acs_pit.sort_values(["sid", "snapshot_date"])
                      .groupby("sid")
                      .tail(1)[["sid", "target_mean"]]
                      .rename(columns={"target_mean": "latest_pt"}))
        rows.append(latest_acs.assign(_priority=1))

    if fh_pit is not None and not fh_pit.empty:
        pt_only = fh_pit[fh_pit["metric"] == "price"]
        if not pt_only.empty:
            latest_fh = (pt_only.sort_values(["sid", "date"])
                         .groupby("sid")
                         .tail(1)[["sid", "value"]]
                         .rename(columns={"value": "latest_pt"}))
            rows.append(latest_fh.assign(_priority=2))

    if not rows:
        return pd.DataFrame(columns=["sid", "pt_upside"])

    # Stack both sources, keep highest-priority (lowest _priority value) per sid
    combined = pd.concat(rows, ignore_index=True)
    combined = (combined.sort_values(["sid", "_priority"])
                .drop_duplicates(subset=["sid"], keep="first"))

    merged = combined.merge(close_df, on="sid", how="left")
    merged["pt_upside"] = np.where(
        (merged["close_price"].notna()) & (merged["close_price"] > 0)
        & (merged["latest_pt"].notna()) & (merged["latest_pt"] > 0),
        (merged["latest_pt"] / merged["close_price"] - 1).round(4),
        np.nan,
    )
    return merged[["sid", "pt_upside"]]


def pit_short_selling_signal(stocks, short_pit, prices_pit, eval_date, window_days=30):
    """Short interest ratio: trailing-30d short qty / 30d average daily volume.

    Higher = more bearish positioning = potential short squeeze candidate.
    NaN if stock has no shorts in window or insufficient volume data.
    """
    if short_pit is None or short_pit.empty:
        return pd.DataFrame(columns=["sid", "short_selling_signal"])

    cutoff = (eval_date - timedelta(days=window_days)).isoformat()
    eval_str = eval_date.isoformat()
    recent = short_pit[(short_pit["short_date"] >= cutoff) & (short_pit["short_date"] <= eval_str)]
    if recent.empty:
        return pd.DataFrame({"sid": stocks["sid"]})

    short_total = recent.groupby("sid")["quantity"].sum().reset_index()
    short_total = short_total.rename(columns={"quantity": "short_qty_30d"})

    # 30-day avg volume
    if "delivery_pct" in prices_pit.columns:
        # use delivery as proxy for volume context — compute avg close × delivery
        prices_30d = prices_pit.sort_values(["sid", "date"]).groupby("sid").tail(30)
        avg_close = prices_30d.groupby("sid")["close"].mean().reset_index().rename(columns={"close": "_avg_close"})
    else:
        avg_close = prices_pit.groupby("sid")["close"].mean().reset_index().rename(columns={"close": "_avg_close"})

    out = short_total.merge(avg_close, on="sid", how="left")
    # Normalized: short qty divided by 30 × avg close (rough volume proxy)
    out["short_selling_signal"] = (
        out["short_qty_30d"] / (30 * out["_avg_close"].replace(0, np.nan))
    ).round(4)
    return out[["sid", "short_selling_signal"]]


def pit_bulk_deal_signal(stocks, bulk_pit, prices_pit, eval_date, window_days=30):
    """Net bulk-deal buy value over trailing 30 calendar days, normalized.

    NaN for any (sid, eval_date) where bulk_deals has no rows in the window —
    naturally sparse for pre-2026-03 dates because bulk_deals starts then.

    Normalization: net_buy_value / (avg_30d_traded_value). Caps extreme values.
    """
    if bulk_pit is None or bulk_pit.empty:
        return pd.DataFrame(columns=["sid", "bulk_deal_signal"])

    cutoff = (eval_date - timedelta(days=window_days)).isoformat()
    eval_str = eval_date.isoformat()

    recent = bulk_pit[
        (bulk_pit["deal_date"] >= cutoff) & (bulk_pit["deal_date"] <= eval_str)
    ].copy()

    if recent.empty:
        # No deals in window — return all NaN
        return pd.DataFrame({"sid": stocks["sid"]})

    # Net buy value per sid: BUY = +qty*price, SELL = -qty*price
    recent["signed_value"] = recent["quantity"] * recent["price"] * np.where(
        recent["buy_sell"].str.upper() == "B", 1.0, -1.0
    )
    net_value = recent.groupby("sid")["signed_value"].sum().reset_index()
    net_value = net_value.rename(columns={"signed_value": "net_buy_value"})

    # Normalize by 30-day average traded value (close × volume) where available
    # Approximation: use close × ~1M (typical small-mid average volume) if missing.
    # Better: compute from prices_pit's last 30 days.
    avg_value = (prices_pit.sort_values(["sid", "date"])
                 .groupby("sid").tail(30)
                 .groupby("sid")
                 .agg(_avg_close=("close", "mean"))
                 .reset_index())

    out = net_value.merge(avg_value, on="sid", how="left")
    # Signal = net buy value (in crores) / avg close (in rupees) — gives a "shares-equivalent" tilt
    # Divide by 1e7 to scale to ~ ±10 range; the validator clamps to ±100.
    out["bulk_deal_signal"] = (
        out["net_buy_value"] / 1e7 / (out["_avg_close"].replace(0, np.nan))
    ).round(3)

    return out[["sid", "bulk_deal_signal"]]


def pit_regulatory_sector(reg_events_pit, reg_signals, sectors_list, eval_date,
                          half_life_days=90):
    """Per-sector regulatory score with time-decay.

    For sector S and eval_date D:
      score = Σ direction × magnitude_w × confidence_w × decay over events
              joined to classified regulatory_signals where event published <= D.
      decay = 0.5 ** ((D - published) / half_life)
    """
    MAG_W = {"minor": 1.0, "moderate": 2.0, "major": 3.0}
    CONF_W = {"low": 0.5, "medium": 0.75, "high": 1.0}

    if reg_events_pit.empty or reg_signals.empty:
        return [{"sector": s, "regulatory_score": None, "n_reg_events": 0} for s in sectors_list]

    # Join events ↔ classified signals
    joined = reg_events_pit.merge(reg_signals, on="event_id", how="inner")
    if joined.empty:
        return [{"sector": s, "regulatory_score": None, "n_reg_events": 0} for s in sectors_list]

    # Compute decay weights
    eval_ts = pd.Timestamp(eval_date)
    joined["pub_ts"] = pd.to_datetime(joined["published_at"], errors="coerce")
    joined = joined[joined["pub_ts"].notna()]
    joined["age_days"] = (eval_ts - joined["pub_ts"]).dt.total_seconds() / 86400
    joined = joined[joined["age_days"] >= 0]  # drop future events
    joined["decay"] = 0.5 ** (joined["age_days"] / half_life_days)

    joined["mag_w"] = joined["magnitude"].str.lower().map(MAG_W).fillna(1.0)
    joined["conf_w"] = joined["confidence"].str.lower().map(CONF_W).fillna(0.5)
    joined["weighted"] = (joined["direction"].fillna(0)
                          * joined["mag_w"] * joined["conf_w"] * joined["decay"])

    out = []
    for sector in sectors_list:
        sub = joined[joined["sector"] == sector]
        if sub.empty:
            out.append({"sector": sector, "regulatory_score": None, "n_reg_events": 0})
            continue
        score = sub["weighted"].sum()
        # Normalize by sqrt of count (keeps small samples conservative)
        n = len(sub)
        normalized = float(score / max(1, n ** 0.5))
        out.append({"sector": sector, "regulatory_score": round(normalized, 3),
                    "n_reg_events": int(n)})
    return out


def pit_macro_sector(macro_history_pit, macro_sector_map, sectors_list, eval_date):
    """Per-sector macro score from macro_history × macro_sector_map.

    For each sector: weighted sum of indicator changes (latest - 90d_prior).
    Normalized to ±10 range.
    """
    if macro_history_pit.empty or macro_sector_map.empty:
        return [{"sector": s, "macro_score": None, "n_macro_indicators": 0} for s in sectors_list]

    # Compute per-indicator change: latest known - value 90 days prior
    eval_str = eval_date.isoformat()
    cutoff_old = (eval_date - timedelta(days=120)).isoformat()
    cutoff_new = (eval_date - timedelta(days=60)).isoformat()
    relevant = macro_history_pit[macro_history_pit["date"] <= eval_str].copy()
    if relevant.empty:
        return [{"sector": s, "macro_score": None, "n_macro_indicators": 0} for s in sectors_list]

    # For each indicator, find latest value and ~90d-prior value
    latest = (relevant.sort_values(["indicator_id", "date"])
              .groupby("indicator_id").tail(1)[["indicator_id", "value"]]
              .rename(columns={"value": "latest"}))

    prior_window = relevant[(relevant["date"] >= cutoff_old) & (relevant["date"] <= cutoff_new)]
    prior = (prior_window.sort_values(["indicator_id", "date"])
             .groupby("indicator_id").tail(1)[["indicator_id", "value"]]
             .rename(columns={"value": "prior"}))

    changes = latest.merge(prior, on="indicator_id", how="inner")
    changes["pct_change"] = np.where(
        (changes["prior"].notna()) & (changes["prior"].abs() > 1e-9),
        (changes["latest"] / changes["prior"] - 1) * 100,
        np.nan,
    )

    # Join to sector map and aggregate
    joined = changes.merge(macro_sector_map, on="indicator_id", how="inner")
    if joined.empty:
        return [{"sector": s, "macro_score": None, "n_macro_indicators": 0} for s in sectors_list]

    joined["weighted_change"] = joined["pct_change"] * joined["direction"] * joined["weight"]

    out = []
    for sector in sectors_list:
        sub = joined[joined["sector"] == sector]
        if sub.empty:
            out.append({"sector": sector, "macro_score": None, "n_macro_indicators": 0})
            continue
        valid = sub["weighted_change"].dropna()
        if valid.empty:
            out.append({"sector": sector, "macro_score": None, "n_macro_indicators": 0})
            continue
        # Mean weighted change, scaled to a small range (typical pct_change is 1-20)
        score = float(valid.mean() / 10.0)
        out.append({"sector": sector, "macro_score": round(score, 3),
                    "n_macro_indicators": int(len(valid))})
    return out


def pit_earnings_beat_rate(stocks, qi_pit, n_quarters=8):
    """Fraction of last-N quarters with positive QoQ EPS growth.

    Proxy for "consistently beating" — we don't have analyst consensus per
    quarter, so we use prior-quarter run-rate as the benchmark.
    """
    rows = []
    sids = stocks["sid"].unique()
    qi_g = qi_pit[qi_pit["eps"].notna()].sort_values(["sid", "end_date"])
    for sid in sids:
        sub = qi_g[qi_g["sid"] == sid]
        if len(sub) < 4:
            continue
        eps = sub["eps"].tail(n_quarters + 1).values
        if len(eps) < 5:
            continue
        # Compare each quarter to prior quarter
        beats = sum(1 for i in range(1, len(eps)) if eps[i] > eps[i - 1])
        total = len(eps) - 1
        if total > 0:
            rows.append({"sid": sid, "earnings_beat_rate": round(beats / total, 3)})
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["sid", "earnings_beat_rate"])


def pit_news_volume(stocks, news_pit_with_sids, eval_date, window_days=7):
    """Count of articles tagged to each stock in the last `window_days`.

    `news_pit_with_sids` is a DataFrame with (sid, published_date) where
    published_date <= eval_date already.
    """
    if news_pit_with_sids is None or news_pit_with_sids.empty:
        return pd.DataFrame(columns=["sid", "news_volume_7d"])
    cutoff = (eval_date - timedelta(days=window_days)).isoformat()
    win = news_pit_with_sids[news_pit_with_sids["published_date"] >= cutoff]
    if win.empty:
        return pd.DataFrame(columns=["sid", "news_volume_7d"])
    counts = win.groupby("sid").size().reset_index(name="news_volume_7d")
    # Cap at validation max
    counts["news_volume_7d"] = counts["news_volume_7d"].clip(upper=100)
    return counts


def pit_sentiment_7d(news_text_pit, eval_date, window_days=7):
    """Mean VADER compound score of articles in last `window_days` per stock.

    `news_text_pit` has (sid, published_date, title, summary), already
    filtered to published_date <= eval_date. NULL for stocks with no
    articles in the window. Available from 2024-04-23 onwards (news_articles
    start date); pre-2024 eval dates produce empty output.
    """
    if news_text_pit is None or news_text_pit.empty:
        return pd.DataFrame(columns=["sid", "sentiment_7d"])
    cutoff = (eval_date - timedelta(days=window_days)).isoformat()
    win = news_text_pit[news_text_pit["published_date"] >= cutoff]
    if win.empty:
        return pd.DataFrame(columns=["sid", "sentiment_7d"])
    try:
        from nltk.sentiment.vader import SentimentIntensityAnalyzer
        sia = SentimentIntensityAnalyzer()
    except Exception:
        # nltk vader_lexicon missing — skip gracefully
        return pd.DataFrame(columns=["sid", "sentiment_7d"])
    # Score per article (cache by article_id since same article can tag multiple sids)
    article_scores = {}
    for _, r in win.drop_duplicates(subset=["article_id"]).iterrows():
        text = f"{r.get('title','') or ''} {r.get('summary','') or ''}"
        article_scores[r["article_id"]] = sia.polarity_scores(text)["compound"]
    win = win.copy()
    win["score"] = win["article_id"].map(article_scores)
    out = win.groupby("sid")["score"].mean().reset_index(name="sentiment_7d")
    out["sentiment_7d"] = out["sentiment_7d"].round(4)
    return out


def pit_insider_signal(stocks, insider_trades_pit, eval_date):
    """Net-weighted insider signal as of eval_date — reuses signals.insider_signal._compute_scores.

    insider_signal._compute_scores already accepts eval_date and a 90d
    lookback. We just route PIT-filtered trades through it and extract the
    score_impact column as the PIT value. Insider_trades depth from 2021-01
    covers all v1 PIT eval dates (2023-04+).
    """
    if insider_trades_pit is None or insider_trades_pit.empty:
        return pd.DataFrame(columns=["sid", "insider_score"])
    from signals.insider_signal import _compute_scores
    df = _compute_scores(insider_trades_pit, stocks, eval_date)
    if "score_impact" not in df.columns:
        return pd.DataFrame(columns=["sid", "insider_score"])
    out = df[["sid", "score_impact"]].rename(columns={"score_impact": "insider_score"})
    # Drop rows where signal didn't compute (no tracked-category activity)
    return out.dropna(subset=["insider_score"])


def pit_momentum(prices_pit):
    """Risk-adjusted 6M and 12M momentum as of eval_date.

    Uses `adj_close` (split/bonus-adjusted) when present, falls back to raw close.
    Mirrors signals/momentum.py logic but operates on date-bounded prices.
    """
    rows = []
    price_col = "adj_close" if "adj_close" in prices_pit.columns else "close"
    for sid, group in prices_pit.groupby("sid"):
        g = group.sort_values("date")
        closes = g[price_col].values
        n = len(closes)

        row = {"sid": sid}

        if n >= WINDOW_6M + SKIP_DAYS:
            p_skip = closes[-SKIP_DAYS - 1]
            p_6m = closes[-(WINDOW_6M + SKIP_DAYS)]
            if p_6m > 0 and p_skip > 0:
                ret_6m = p_skip / p_6m - 1
                window = closes[-(WINDOW_6M + SKIP_DAYS):(-SKIP_DAYS)]
                daily_rets = np.diff(window) / window[:-1]
                vol_6m = daily_rets.std()
                if vol_6m > 0:
                    row["mom_6m"] = round(ret_6m / vol_6m, 4)

        if n >= WINDOW_12M + SKIP_DAYS:
            p_skip = closes[-SKIP_DAYS - 1]
            p_12m = closes[-(WINDOW_12M + SKIP_DAYS)]
            if p_12m > 0 and p_skip > 0:
                ret_12m = p_skip / p_12m - 1
                window = closes[-(WINDOW_12M + SKIP_DAYS):(-SKIP_DAYS)]
                daily_rets = np.diff(window) / window[:-1]
                vol_12m = daily_rets.std()
                if vol_12m > 0:
                    row["mom_12m"] = round(ret_12m / vol_12m, 4)

        rows.append(row)

    return pd.DataFrame(rows)


# ───── Plan-0007 cluster: 4 factors derived from fundamentals_screener ─────

_REVCV_MIN_YEARS = 6
_REVCV_MIN_ABS_MEAN = 0.02
_FCLUSTER_SMOOTH = 3


def pit_revenue_cv(stocks, fund_pit):
    """Revenue volatility 5y CV — stdev/|mean| of last 5 YoY Sales growth rates."""
    sales = fund_pit[fund_pit["line_item"] == "Sales"]
    sales = sales.sort_values(["sid", "period_end"])
    rows = []
    for sid, g in sales.groupby("sid"):
        vals = g["value"].dropna().tolist()
        if len(vals) < _REVCV_MIN_YEARS:
            continue
        window = vals[-_REVCV_MIN_YEARS:]
        growth = []
        for i in range(1, len(window)):
            prev = window[i - 1]
            if prev is None or prev <= 0:
                continue
            growth.append(window[i] / prev - 1)
        if len(growth) < _REVCV_MIN_YEARS - 1:
            continue
        m = float(np.mean(growth))
        if abs(m) < _REVCV_MIN_ABS_MEAN:
            continue
        cv = float(np.std(growth, ddof=1) / abs(m))
        rows.append({"sid": sid, "revenue_cv_5y": round(cv, 4)})
    return pd.DataFrame(rows)


def pit_inventory_turnover(stocks, fund_pit):
    """Sales/Inventory, 3-yr median, ranked vs sector p50."""
    inv_excluded = set(FINANCIAL_SECTORS) | {"Information Technology",
                                             "Communication Services", "Utilities"}
    universe = stocks[~stocks["sector"].isin(inv_excluded)][["sid", "sector"]]
    fp = fund_pit[fund_pit["line_item"].isin(["Sales", "Inventory"])].copy()
    if fp.empty:
        return pd.DataFrame(columns=["sid", "relative_turnover"])
    wide = fp.pivot_table(index=["sid", "period_end"], columns="line_item",
                          values="value", aggfunc="first").reset_index()
    for col in ("Sales", "Inventory"):
        if col not in wide.columns:
            wide[col] = np.nan
    wide = wide.dropna(subset=["Sales", "Inventory"])
    wide = wide[(wide["Inventory"] >= 1.0) & (wide["Sales"] > 0)]
    wide["turnover_yr"] = wide["Sales"] / wide["Inventory"]
    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(_FCLUSTER_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        inventory_turnover=("turnover_yr", "median"),
        years_used=("turnover_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _FCLUSTER_SMOOTH]
    agg = agg.merge(universe, on="sid", how="inner")
    if agg.empty:
        return pd.DataFrame(columns=["sid", "relative_turnover"])
    p50 = agg.groupby("sector")["inventory_turnover"].median().to_dict()
    agg["sector_p50"] = agg["sector"].map(p50)
    agg["relative_turnover"] = agg["inventory_turnover"] / agg["sector_p50"]
    return agg[["sid", "relative_turnover"]].copy()


def pit_sales_growth_relative(stocks, fund_pit):
    """3-yr median YoY Sales growth minus sector median."""
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid", "sector"]]
    sales = fund_pit[fund_pit["line_item"] == "Sales"].copy()
    sales = sales.sort_values(["sid", "period_end"])
    sales["prev"] = sales.groupby("sid")["value"].shift(1)
    sales = sales.dropna(subset=["prev"])
    sales = sales[sales["prev"] > 0]
    sales["growth_yr"] = sales["value"] / sales["prev"] - 1
    last_n = sales.groupby("sid", as_index=False).tail(_FCLUSTER_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        sales_growth=("growth_yr", "median"),
        years_used=("growth_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _FCLUSTER_SMOOTH]
    agg = agg.merge(universe, on="sid", how="inner")
    if agg.empty:
        return pd.DataFrame(columns=["sid", "relative_growth"])
    sec_med = agg.groupby("sector")["sales_growth"].median().to_dict()
    agg["sector_median"] = agg["sector"].map(sec_med)
    agg["relative_growth"] = agg["sales_growth"] - agg["sector_median"]
    return agg[["sid", "relative_growth"]].copy()


def pit_share_momentum(stocks, fund_pit, prices_pit, eval_date,
                       window_days=90):
    """Δ market_cap_share within sector over `window_days` calendar days."""
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid", "sector"]]
    shares = fund_pit[fund_pit["line_item"] == "No. of Equity Shares"]
    if shares.empty or prices_pit.empty:
        return pd.DataFrame(columns=["sid", "share_momentum"])
    shares = (shares.sort_values(["sid", "period_end"])
                    .groupby("sid", as_index=False).tail(1)
                    [["sid", "value"]].rename(columns={"value": "shares"}))

    price_col = "adj_close" if "adj_close" in prices_pit.columns else "close"
    cutoff_t = eval_date.isoformat()
    cutoff_p = (eval_date - timedelta(days=int(window_days * 1.45))).isoformat()

    px = prices_pit[prices_pit["date"] <= cutoff_t]
    latest = px.sort_values(["sid", "date"]).groupby("sid", as_index=False).tail(1)
    latest = latest[["sid", price_col]].rename(columns={price_col: "close_t"})

    px_p = prices_pit[prices_pit["date"] <= cutoff_p]
    past = px_p.sort_values(["sid", "date"]).groupby("sid", as_index=False).tail(1)
    past = past[["sid", price_col]].rename(columns={price_col: "close_p"})

    df = (latest.merge(past, on="sid", how="inner")
                .merge(shares, on="sid", how="inner")
                .merge(universe, on="sid", how="inner"))
    if df.empty:
        return pd.DataFrame(columns=["sid", "share_momentum"])
    df["mc_t"] = df["close_t"] * df["shares"]
    df["mc_p"] = df["close_p"] * df["shares"]
    sec_t = df.groupby("sector")["mc_t"].sum().to_dict()
    sec_p = df.groupby("sector")["mc_p"].sum().to_dict()
    df["share_t"] = df["mc_t"] / df["sector"].map(sec_t)
    df["share_p"] = df["mc_p"] / df["sector"].map(sec_p)
    df = df[(df["share_p"] > 0) & df["share_p"].notna()]
    df["share_momentum"] = df["share_t"] / df["share_p"] - 1
    return df[["sid", "share_momentum"]].copy()


# ───── Cash Conversion Cycle (paired with signals/cash_conversion_cycle.py) ─────

_CCC_SMOOTH_YEARS = 3
_CCC_MIN_SALES_CR = 50.0
_CCC_ITEMS = ("Sales", "Receivables", "Inventory", "Trade Payables")


def pit_cash_conversion_cycle(stocks, fund_pit):
    """3-yr median CCC = DSO + DIO − DPO, all using Sales/365 as denominator.

    Mirrors signals/cash_conversion_cycle.py — see that module for the rationale
    on using Sales (not COGS) and the financial-sector exclusion.
    """
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_CCC_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "ccc"])

    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _CCC_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_CCC_ITEMS))
    wide = wide[wide["Sales"] >= _CCC_MIN_SALES_CR]
    if wide.empty:
        return pd.DataFrame(columns=["sid", "ccc"])

    daily_sales = wide["Sales"] / 365.0
    wide["ccc_yr"] = (
        wide["Receivables"] / daily_sales
        + wide["Inventory"] / daily_sales
        - wide["Trade Payables"] / daily_sales
    )

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(_CCC_SMOOTH_YEARS)
    agg = last_n.groupby("sid", as_index=False).agg(
        ccc=("ccc_yr", "median"),
        years_used=("ccc_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _CCC_SMOOTH_YEARS]
    agg = agg.merge(universe, on="sid", how="inner")
    return agg[["sid", "ccc"]].reset_index(drop=True)


# ───── Operating Margin Trend (paired with signals/operating_margin_trend.py) ─────

_OMTREND_WINDOW = 5
_OMTREND_MIN_SALES_CR = 50.0
_OMTREND_ITEMS = ("Sales", "Profit before tax", "Interest")


def pit_operating_margin_trend(stocks, fund_pit):
    """OLS slope (pp/yr) of last 5y EBIT/Sales per sid."""
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_OMTREND_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "margin_slope"])

    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _OMTREND_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_OMTREND_ITEMS))
    wide = wide[wide["Sales"] >= _OMTREND_MIN_SALES_CR].copy()
    wide["margin"] = (wide["Profit before tax"] + wide["Interest"]) / wide["Sales"]
    wide = wide[wide["margin"].between(-2.0, 2.0)]

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(_OMTREND_WINDOW)

    rows = []
    for sid, g in last_n.groupby("sid"):
        if len(g) < _OMTREND_WINDOW:
            continue
        x = np.arange(len(g), dtype=float)
        y = g["margin"].values
        slope_frac = np.polyfit(x, y, 1)[0]
        rows.append({"sid": sid, "margin_slope": float(slope_frac) * 100.0})
    if not rows:
        return pd.DataFrame(columns=["sid", "margin_slope"])
    out = pd.DataFrame(rows).merge(universe, on="sid", how="inner")
    return out[["sid", "margin_slope"]]


# ───── Working Capital Intensity (paired with signals/working_capital_intensity.py) ─────

_WCI_SMOOTH = 3
_WCI_MIN_SALES_CR = 50.0
_WCI_ITEMS = ("Sales", "Receivables", "Inventory", "Trade Payables")


def pit_working_capital_intensity(stocks, fund_pit):
    """3y median (Recv + Inv − Pay) / Sales per sid."""
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_WCI_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "wc_intensity"])

    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _WCI_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_WCI_ITEMS))
    wide = wide[wide["Sales"] >= _WCI_MIN_SALES_CR].copy()
    wide["wci_yr"] = (
        wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    ) / wide["Sales"]

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(_WCI_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        wc_intensity=("wci_yr", "median"),
        years_used=("wci_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _WCI_SMOOTH]
    agg = agg.merge(universe, on="sid", how="inner")
    return agg[["sid", "wc_intensity"]].reset_index(drop=True)


# ───── Interest Coverage (paired with signals/interest_coverage.py) ─────

_ICOV_SMOOTH = 3
_ICOV_MIN_INTEREST_CR = 1.0
_ICOV_CAP = 200.0
_ICOV_ITEMS = ("Profit before tax", "Interest")


def pit_interest_coverage(stocks, fund_pit):
    """3y median (PBT + Interest) / Interest per sid, capped at ±200."""
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_ICOV_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "interest_coverage"])

    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _ICOV_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_ICOV_ITEMS))
    wide = wide[wide["Interest"] >= _ICOV_MIN_INTEREST_CR].copy()
    wide["cov_yr"] = (
        (wide["Profit before tax"] + wide["Interest"]) / wide["Interest"]
    ).clip(-_ICOV_CAP, _ICOV_CAP)

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(_ICOV_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        interest_coverage=("cov_yr", "median"),
        years_used=("cov_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _ICOV_SMOOTH]
    agg = agg.merge(universe, on="sid", how="inner")
    return agg[["sid", "interest_coverage"]].reset_index(drop=True)


# ───── ROIC (paired with signals/roic.py) ─────

_ROIC_SMOOTH = 3
_ROIC_MIN_IC_CR = 50.0
_ROIC_ITEMS = (
    "Profit before tax", "Tax", "Interest",
    "Equity Share Capital", "Reserves", "Borrowings",
)


def pit_roic(stocks, fund_pit):
    """3y median ROIC = NOPAT / Invested Capital per sid.

    Mirrors signals/roic.py: NOPAT = (PBT + Interest) × (1 − Tax/PBT), tax
    rate clipped to [0, 1] when PBT > 0 and treated as 0 in loss years.
    Invested Capital = Equity Share Capital + Reserves + Borrowings.
    Financial sector excluded (semantics differ for banks).
    """
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_ROIC_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "roic"])

    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _ROIC_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_ROIC_ITEMS))

    pbt = wide["Profit before tax"]
    tax = wide["Tax"]
    interest = wide["Interest"]
    tax_rate = np.where(pbt > 0, (tax / pbt.replace(0, np.nan)).clip(0.0, 1.0), 0.0)
    wide["nopat"] = (pbt + interest) * (1 - tax_rate)
    wide["invested_capital"] = (
        wide["Equity Share Capital"] + wide["Reserves"] + wide["Borrowings"]
    )
    wide = wide[wide["invested_capital"] >= _ROIC_MIN_IC_CR].copy()
    wide["roic_yr"] = wide["nopat"] / wide["invested_capital"]

    wide = wide.sort_values(["sid", "period_end"])
    last_n = wide.groupby("sid", as_index=False).tail(_ROIC_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        roic=("roic_yr", "median"),
        years_used=("roic_yr", "count"),
    )
    agg = agg[(agg["years_used"] >= _ROIC_SMOOTH) & (agg["roic"] > 0)]
    agg = agg.merge(universe, on="sid", how="inner")
    return agg[["sid", "roic"]].reset_index(drop=True)


# ───── FCF Yield (paired with signals/fcf_yield.py) ─────

_FCFY_SMOOTH = 3
_FCFY_RUPEES_PER_CRORE = 1e7
_FCFY_MIN_MARKET_CAP_CR = SCREEN["min_market_cap_cr"]
_FCFY_ITEMS = (
    "Cash from Operating Activity",
    "Net Block",
    "Capital Work in Progress",
    "Depreciation",
)


_ROIIC_WINDOW = 5
_ROIIC_MIN_DELTA_IC_CR = 50.0
_ROIIC_CAP = 5.0
_ROIIC_ITEMS = (
    "Profit before tax", "Tax", "Interest",
    "Equity Share Capital", "Reserves", "Borrowings",
)


def pit_roiic(stocks, fund_pit):
    """5y endpoint ROIIC = (NOPAT_t − NOPAT_{t-5}) / (IC_t − IC_{t-5}) per sid.

    Mirrors signals/roiic.py: same NOPAT and IC formulas as pit_roic, but
    measured as a *change* over the trailing 5 annual periods. Drops sids
    where ΔIC < ₹50 cr (denominator blow-up + sign-inverted capital returners).
    Capped to ±5 to match the scorer.
    """
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_ROIIC_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "roiic"])

    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _ROIIC_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_ROIIC_ITEMS))
    if wide.empty:
        return pd.DataFrame(columns=["sid", "roiic"])

    pbt = wide["Profit before tax"]
    tax = wide["Tax"]
    interest = wide["Interest"]
    tax_rate = np.where(pbt > 0, (tax / pbt.replace(0, np.nan)).clip(0.0, 1.0), 0.0)
    wide["nopat"] = (pbt + interest) * (1 - tax_rate)
    wide["ic"] = (
        wide["Equity Share Capital"] + wide["Reserves"] + wide["Borrowings"]
    )

    wide = wide.sort_values(["sid", "period_end"])
    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < _ROIIC_WINDOW + 1:
            continue
        nopat_old = g["nopat"].iloc[-(_ROIIC_WINDOW + 1)]
        nopat_new = g["nopat"].iloc[-1]
        ic_old = g["ic"].iloc[-(_ROIIC_WINDOW + 1)]
        ic_new = g["ic"].iloc[-1]
        delta_ic = ic_new - ic_old
        if delta_ic < _ROIIC_MIN_DELTA_IC_CR:
            continue
        roiic = float(np.clip((nopat_new - nopat_old) / delta_ic, -_ROIIC_CAP, _ROIIC_CAP))
        rows.append({"sid": sid, "roiic": roiic})

    if not rows:
        return pd.DataFrame(columns=["sid", "roiic"])
    out = pd.DataFrame(rows).merge(universe, on="sid", how="inner")
    return out[["sid", "roiic"]].reset_index(drop=True)


# ───── Forensic / capital-allocation batch (plan 0002 §3.2.1) ─────
# All paired with signals/{name}.py — same formulas, just sourced from
# the PIT-filtered fund_pit slice instead of the live fundamentals_screener.

_FBATCH_MIN_SALES_CR = 50.0
_FBATCH_MIN_ASSETS_CR = 50.0
_FBATCH_MIN_BORROW_CR = 50.0
_FBATCH_MIN_DEP_CR = 1.0
_FBATCH_SMOOTH = 3
_CAPEX2DEP_CAP = 20.0


def _yoy_change_per_day(fund_pit, stocks, item_num, denom_item="Sales", out_col=None):
    """Generic YoY change in days: (item_t/(denom_t/365)) − (item_{t-1}/(denom_{t-1}/365))."""
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin([item_num, denom_item])]
    if fp.empty:
        return pd.DataFrame(columns=["sid", out_col])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in (item_num, denom_item):
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=[item_num, denom_item])
    wide = wide[wide[denom_item] >= _FBATCH_MIN_SALES_CR].copy()
    wide["days"] = wide[item_num] / (wide[denom_item] / 365.0)
    wide = wide.sort_values(["sid", "period_end"])
    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        rows.append({"sid": sid, out_col: float(g["days"].iloc[-1] - g["days"].iloc[-2])})
    if not rows:
        return pd.DataFrame(columns=["sid", out_col])
    return pd.DataFrame(rows).merge(universe, on="sid", how="inner")[["sid", out_col]]


def pit_dso_change_yoy(stocks, fund_pit):
    return _yoy_change_per_day(fund_pit, stocks, "Receivables", "Sales", "dso_change_yoy")


def pit_dio_change_yoy(stocks, fund_pit):
    return _yoy_change_per_day(fund_pit, stocks, "Inventory", "Sales", "dio_change_yoy")


_NWC2REV_ITEMS = ("Sales", "Receivables", "Inventory", "Trade Payables")


def pit_nwc_to_revenue(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_NWC2REV_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "nwc_to_revenue"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _NWC2REV_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_NWC2REV_ITEMS))
    wide = wide[wide["Sales"] >= _FBATCH_MIN_SALES_CR].copy()
    wide["nwc_to_revenue"] = (
        wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    ) / wide["Sales"]
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest.merge(universe, on="sid", how="inner")[["sid", "nwc_to_revenue"]].reset_index(drop=True)


_SLOAN_ITEMS = ("Receivables", "Inventory", "Trade Payables", "Depreciation", "Total")


def pit_sloan_accruals_full(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_SLOAN_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "sloan_accruals_full"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _SLOAN_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_SLOAN_ITEMS))
    wide = wide[wide["Total"] >= _FBATCH_MIN_ASSETS_CR].copy()
    wide["nwc"] = wide["Receivables"] + wide["Inventory"] - wide["Trade Payables"]
    wide = wide.sort_values(["sid", "period_end"])
    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        latest, prior = g.iloc[-1], g.iloc[-2]
        ta_avg = (latest["Total"] + prior["Total"]) / 2.0
        if ta_avg <= 0:
            continue
        sloan = (latest["nwc"] - prior["nwc"] - latest["Depreciation"]) / ta_avg
        rows.append({"sid": sid, "sloan_accruals_full": float(sloan)})
    if not rows:
        return pd.DataFrame(columns=["sid", "sloan_accruals_full"])
    return pd.DataFrame(rows).merge(universe, on="sid", how="inner")[["sid", "sloan_accruals_full"]]


_SGA_ITEMS = ("Sales", "Selling and admin")


def pit_sga_to_revenue_change(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_SGA_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "sga_to_revenue_change"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _SGA_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_SGA_ITEMS))
    wide = wide[wide["Sales"] >= _FBATCH_MIN_SALES_CR].copy()
    wide["sga_int"] = wide["Selling and admin"] / wide["Sales"]
    wide = wide.sort_values(["sid", "period_end"])
    rows = []
    for sid, g in wide.groupby("sid"):
        if len(g) < 2:
            continue
        rows.append({
            "sid": sid,
            "sga_to_revenue_change": float(g["sga_int"].iloc[-1] - g["sga_int"].iloc[-2]),
        })
    if not rows:
        return pd.DataFrame(columns=["sid", "sga_to_revenue_change"])
    return pd.DataFrame(rows).merge(universe, on="sid", how="inner")[["sid", "sga_to_revenue_change"]]


_FCFM_ITEMS = (
    "Sales", "Cash from Operating Activity", "Net Block",
    "Capital Work in Progress", "Depreciation",
)


def pit_fcf_margin(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_FCFM_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "fcf_margin"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index().sort_values(["sid", "period_end"])
    for item in _FCFM_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_FCFM_ITEMS))
    wide = wide[wide["Sales"] >= _FBATCH_MIN_SALES_CR].copy()
    wide["ppe"] = wide["Net Block"] + wide["Capital Work in Progress"]
    wide["ppe_prev"] = wide.groupby("sid")["ppe"].shift(1)
    wide = wide.dropna(subset=["ppe_prev"])
    delta_ppe = (wide["ppe"] - wide["ppe_prev"]).clip(lower=0.0)
    wide["capex"] = delta_ppe + wide["Depreciation"]
    wide["fcf_margin_yr"] = (wide["Cash from Operating Activity"] - wide["capex"]) / wide["Sales"]
    last_n = wide.groupby("sid", as_index=False).tail(_FBATCH_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        fcf_margin=("fcf_margin_yr", "median"),
        years_used=("fcf_margin_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _FBATCH_SMOOTH]
    return agg.merge(universe, on="sid", how="inner")[["sid", "fcf_margin"]].reset_index(drop=True)


_CAPEX_ITEMS = ("Net Block", "Capital Work in Progress", "Depreciation")


def pit_capex_to_dep(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_CAPEX_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "capex_to_dep"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index().sort_values(["sid", "period_end"])
    for item in _CAPEX_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_CAPEX_ITEMS))
    wide = wide[wide["Depreciation"] >= _FBATCH_MIN_DEP_CR].copy()
    wide["ppe"] = wide["Net Block"] + wide["Capital Work in Progress"]
    wide["ppe_prev"] = wide.groupby("sid")["ppe"].shift(1)
    wide = wide.dropna(subset=["ppe_prev"])
    delta_ppe = (wide["ppe"] - wide["ppe_prev"]).clip(lower=0.0)
    wide["capex"] = delta_ppe + wide["Depreciation"]
    wide["ratio_yr"] = (wide["capex"] / wide["Depreciation"]).clip(-_CAPEX2DEP_CAP, _CAPEX2DEP_CAP)
    last_n = wide.groupby("sid", as_index=False).tail(_FBATCH_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        capex_to_dep=("ratio_yr", "median"),
        years_used=("ratio_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _FBATCH_SMOOTH]
    return agg.merge(universe, on="sid", how="inner")[["sid", "capex_to_dep"]].reset_index(drop=True)


_GW_ITEMS = ("Intangible Assets", "Total")


def pit_goodwill_to_assets(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_GW_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "goodwill_to_assets"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _GW_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_GW_ITEMS))
    wide = wide[wide["Total"] >= _FBATCH_MIN_ASSETS_CR].copy()
    wide["goodwill_to_assets"] = wide["Intangible Assets"] / wide["Total"]
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest.merge(universe, on="sid", how="inner")[["sid", "goodwill_to_assets"]].reset_index(drop=True)


_DBT_ITEMS = ("Long term Borrowings", "Borrowings")


def pit_debt_structure(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_DBT_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "debt_structure"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _DBT_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_DBT_ITEMS))
    wide = wide[wide["Borrowings"] >= _FBATCH_MIN_BORROW_CR].copy()
    wide["debt_structure"] = (
        wide["Long term Borrowings"] / wide["Borrowings"]
    ).clip(0.0, 1.0)
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest.merge(universe, on="sid", how="inner")[["sid", "debt_structure"]].reset_index(drop=True)


_ASSTAN_ITEMS = ("Net Block", "Total")


def pit_asset_tangibility(stocks, fund_pit):
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_ASSTAN_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "asset_tangibility"])
    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index()
    for item in _ASSTAN_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_ASSTAN_ITEMS))
    wide = wide[wide["Total"] >= _FBATCH_MIN_ASSETS_CR].copy()
    wide["asset_tangibility"] = (wide["Net Block"] / wide["Total"]).clip(0.0, 1.0)
    wide = wide.sort_values(["sid", "period_end"])
    latest = wide.groupby("sid", as_index=False).tail(1)
    return latest.merge(universe, on="sid", how="inner")[["sid", "asset_tangibility"]].reset_index(drop=True)


def pit_fcf_yield(stocks, fund_pit, close_df):
    """3y median FCF / PIT market_cap_cr per sid.

    Mirrors signals/fcf_yield.py: FCF = OCF − (max(Δ(NetBlock+CWIP),0) +
    Depreciation). Market cap is reconstructed PIT as
    (close × No. of Equity Shares) / 1e7 (rupees → ₹cr) so the yield is
    dimensionless, matching the live signal's output.
    """
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid"]]
    fp = fund_pit[fund_pit["line_item"].isin(_FCFY_ITEMS)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "fcf_yield"])

    wide = fp.pivot_table(
        index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first"
    ).reset_index().sort_values(["sid", "period_end"])
    for item in _FCFY_ITEMS:
        if item not in wide.columns:
            wide[item] = np.nan
    wide = wide.dropna(subset=list(_FCFY_ITEMS))

    wide["ppe"] = wide["Net Block"] + wide["Capital Work in Progress"]
    wide["ppe_prev"] = wide.groupby("sid")["ppe"].shift(1)
    wide = wide.dropna(subset=["ppe_prev"])
    delta_ppe = (wide["ppe"] - wide["ppe_prev"]).clip(lower=0.0)
    wide["capex"] = delta_ppe + wide["Depreciation"]
    wide["fcf_yr"] = wide["Cash from Operating Activity"] - wide["capex"]

    last_n = wide.groupby("sid", as_index=False).tail(_FCFY_SMOOTH)
    agg = last_n.groupby("sid", as_index=False).agg(
        fcf=("fcf_yr", "median"),
        years_used=("fcf_yr", "count"),
    )
    agg = agg[agg["years_used"] >= _FCFY_SMOOTH]
    agg = agg.merge(universe, on="sid", how="inner")
    if agg.empty:
        return pd.DataFrame(columns=["sid", "fcf_yield"])

    # PIT market cap from close × latest-known shares (annual filing)
    shares = fund_pit[fund_pit["line_item"] == "No. of Equity Shares"]
    if shares.empty:
        return pd.DataFrame(columns=["sid", "fcf_yield"])
    shares = (shares.sort_values(["sid", "period_end"])
                    .groupby("sid", as_index=False).tail(1)
                    [["sid", "value"]].rename(columns={"value": "shares"}))
    shares = shares[shares["shares"] > 0]

    mc = (close_df.merge(shares, on="sid", how="inner"))
    mc["market_cap_cr"] = (mc["close_price"] * mc["shares"]) / _FCFY_RUPEES_PER_CRORE
    mc = mc[mc["market_cap_cr"] >= _FCFY_MIN_MARKET_CAP_CR]

    out = agg.merge(mc[["sid", "market_cap_cr"]], on="sid", how="inner")
    out["fcf_yield"] = out["fcf"] / out["market_cap_cr"]
    return out[["sid", "fcf_yield"]].reset_index(drop=True)


# ─────────────────────── Driver ───────────────────────

def reconstruct_one_date(eval_date, raw, signals_to_run):
    """Reconstruct all enabled signals for a single eval_date.

    `raw` is a dict of full-history DataFrames (loaded once, reused across dates).
    Returns one DataFrame with one row per stock.
    """
    qi_pit = knowable_quarterly(raw["qi"], eval_date)
    bs_pit = knowable_annual(raw["bs"], eval_date)
    cf_pit = knowable_annual(raw["cf"], eval_date)
    sh_pit = knowable_shareholding(raw["sh"], eval_date)
    px_pit = prices_through(raw["prices"], eval_date)
    px_pit = apply_pit_adjustments(px_pit, raw["adjustments"], eval_date)

    close_df = pit_close_price(px_pit)

    # Start with the universe + close + tier
    base = raw["stocks"][["sid", "cap_tier"]].merge(close_df, on="sid", how="left")
    base["snapshot_date"] = eval_date.isoformat()

    if "piotroski" in signals_to_run:
        base = base.merge(pit_piotroski(raw["stocks"], qi_pit, bs_pit, cf_pit), on="sid", how="left")

    if "accruals" in signals_to_run:
        base = base.merge(pit_accruals(raw["stocks"], qi_pit, bs_pit, cf_pit), on="sid", how="left")

    if "promoter" in signals_to_run:
        base = base.merge(pit_promoter(raw["stocks"], sh_pit), on="sid", how="left")

    if "forensic" in signals_to_run:
        base = base.merge(pit_forensic(raw["stocks"], qi_pit, bs_pit, cf_pit), on="sid", how="left")

    if "earnings_yield" in signals_to_run:
        base = base.merge(pit_earnings_yield(qi_pit, close_df), on="sid", how="left")

    if "book_to_price" in signals_to_run:
        base = base.merge(pit_book_to_price(bs_pit, close_df), on="sid", how="left")

    if "momentum" in signals_to_run:
        base = base.merge(pit_momentum(px_pit), on="sid", how="left")

    if "position_52w" in signals_to_run:
        base = base.merge(pit_position_52w(px_pit, eval_date), on="sid", how="left")

    if "delivery" in signals_to_run:
        base = base.merge(pit_avg_delivery(px_pit), on="sid", how="left")
        base = base.merge(pit_delivery_anomaly_z(px_pit), on="sid", how="left")

    if "pledge" in signals_to_run:
        base = base.merge(pit_pledge_quality(raw["stocks"], sh_pit), on="sid", how="left")

    if "promoter_trend" in signals_to_run:
        base = base.merge(pit_promoter_trend_4q(raw["stocks"], sh_pit), on="sid", how="left")

    if "macd" in signals_to_run:
        base = base.merge(pit_macd_bullish(px_pit), on="sid", how="left")

    if "fwd_return" in signals_to_run:
        base = base.merge(pit_fwd_return_20d(eval_date, raw["prices"]), on="sid", how="left")

    # ── Tier 2: fundamentals ──
    if "quality_fundamentals" in signals_to_run:
        financial_sids = set(raw["stocks"][raw["stocks"]["sector"].isin(FINANCIAL_SECTORS)]["sid"])
        base = base.merge(pit_quality_fundamentals(raw["stocks"], qi_pit, bs_pit, financial_sids), on="sid", how="left")

    if "growth_fundamentals" in signals_to_run:
        base = base.merge(pit_growth_fundamentals(raw["stocks"], qi_pit), on="sid", how="left")

    # ── Tier 2: consensus from forecast_history ──
    fh_pit = raw["fh"][raw["fh"]["date"] <= eval_date.isoformat()] if "fh" in raw else pd.DataFrame()
    if "consensus" in signals_to_run:
        base = base.merge(pit_consensus(raw["stocks"], fh_pit), on="sid", how="left")

    # ── Tier 3: pt_upside (analyst_consensus_snapshots preferred; year-end fallback) ──
    if "pt_upside" in signals_to_run:
        acs_pit = (raw["acs"][raw["acs"]["snapshot_date"] <= eval_date.isoformat()]
                   if "acs" in raw and not raw["acs"].empty else pd.DataFrame())
        base = base.merge(
            pit_pt_upside(raw["stocks"], fh_pit, close_df, acs_pit=acs_pit),
            on="sid", how="left",
        )

    # ── Tier 3: bulk_deal_signal (sparse — NULL for dates without bulk_deals data) ──
    if "bulk_deal" in signals_to_run and "bulk" in raw:
        bulk_pit = raw["bulk"][raw["bulk"]["deal_date"] <= eval_date.isoformat()]
        base = base.merge(pit_bulk_deal_signal(raw["stocks"], bulk_pit, px_pit, eval_date), on="sid", how="left")

    # ── Plan 0005 Phase E: composite smart_money for full screener-input replay ──
    if "smart_money" in signals_to_run and "bulk" in raw:
        bulk_pit = raw["bulk"][raw["bulk"]["deal_date"] <= eval_date.isoformat()]
        base = base.merge(pit_smart_money(raw["stocks"], bulk_pit, px_pit, eval_date), on="sid", how="left")

    # ── Tier 4: short_selling_signal (Jan 2024+ data) ──
    if "short_selling" in signals_to_run and "short" in raw:
        short_pit = raw["short"][raw["short"]["short_date"] <= eval_date.isoformat()]
        base = base.merge(pit_short_selling_signal(raw["stocks"], short_pit, px_pit, eval_date), on="sid", how="left")

    # ── Tier 4: earnings_beat_rate (proxy via QoQ-positive rate over last 8 quarters) ──
    if "earnings_beat_rate" in signals_to_run:
        base = base.merge(pit_earnings_beat_rate(raw["stocks"], qi_pit), on="sid", how="left")

    # ── Tier 4: news_volume_7d (article count tagged to each stock in last 7d) ──
    if "news_volume" in signals_to_run and "news" in raw:
        news_pit = raw["news"][raw["news"]["published_date"] <= eval_date.isoformat()]
        base = base.merge(pit_news_volume(raw["stocks"], news_pit, eval_date), on="sid", how="left")

    # ── Behavior tier: sentiment_7d (VADER on PIT-filtered articles, last 7d) ──
    # Pre-2024-04 eval dates: news_articles started 2024-04-23, output will be empty.
    if "sentiment_7d" in signals_to_run and "news_text" in raw:
        news_text_pit = raw["news_text"][raw["news_text"]["published_date"] <= eval_date.isoformat()]
        base = base.merge(pit_sentiment_7d(news_text_pit, eval_date), on="sid", how="left")

    # ── Behavior tier: insider_score (net-weighted Promoter/Director/KMP, 90d) ──
    if "insider_signal" in signals_to_run and "insider_trades" in raw:
        ins_pit = raw["insider_trades"][raw["insider_trades"]["trade_date"] <= eval_date.isoformat()]
        base = base.merge(pit_insider_signal(raw["stocks"], ins_pit, eval_date), on="sid", how="left")

    # ── Track 2.2b — Financial sub-model (Banks + NBFCs only) ──
    if "financial_signal" in signals_to_run and "banking_metrics" in raw:
        base = base.merge(pit_financial_signal(raw["banking_metrics"], eval_date),
                          on="sid", how="left")

    # ── Track 3 cluster (plan 0003) — sector-narrative-derived factors ──
    fund_pit = (knowable_screener(raw["fund_screener"], eval_date)
                if "fund_screener" in raw else pd.DataFrame())

    if "revenue_cv" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_revenue_cv(raw["stocks"], fund_pit), on="sid", how="left")

    if "inventory_turnover" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_inventory_turnover(raw["stocks"], fund_pit), on="sid", how="left")

    if "sales_growth_relative" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_sales_growth_relative(raw["stocks"], fund_pit), on="sid", how="left")

    if "share_momentum" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_share_momentum(raw["stocks"], fund_pit, px_pit, eval_date),
            on="sid", how="left",
        )

    if "cash_conversion_cycle" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_cash_conversion_cycle(raw["stocks"], fund_pit),
            on="sid", how="left",
        )

    if "operating_margin_trend" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_operating_margin_trend(raw["stocks"], fund_pit),
            on="sid", how="left",
        )

    if "working_capital_intensity" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_working_capital_intensity(raw["stocks"], fund_pit),
            on="sid", how="left",
        )

    if "interest_coverage" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_interest_coverage(raw["stocks"], fund_pit),
            on="sid", how="left",
        )

    if "roic" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_roic(raw["stocks"], fund_pit),
            on="sid", how="left",
        )

    if "fcf_yield" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_fcf_yield(raw["stocks"], fund_pit, close_df),
            on="sid", how="left",
        )

    if "roiic" in signals_to_run and not fund_pit.empty:
        base = base.merge(
            pit_roiic(raw["stocks"], fund_pit),
            on="sid", how="left",
        )

    # Forensic / capital-allocation batch (plan 0002 §3.2.1)
    if "dso_change_yoy" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_dso_change_yoy(raw["stocks"], fund_pit), on="sid", how="left")
    if "dio_change_yoy" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_dio_change_yoy(raw["stocks"], fund_pit), on="sid", how="left")
    if "nwc_to_revenue" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_nwc_to_revenue(raw["stocks"], fund_pit), on="sid", how="left")
    if "sloan_accruals_full" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_sloan_accruals_full(raw["stocks"], fund_pit), on="sid", how="left")
    if "sga_to_revenue_change" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_sga_to_revenue_change(raw["stocks"], fund_pit), on="sid", how="left")
    if "fcf_margin" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_fcf_margin(raw["stocks"], fund_pit), on="sid", how="left")
    if "capex_to_dep" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_capex_to_dep(raw["stocks"], fund_pit), on="sid", how="left")
    if "goodwill_to_assets" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_goodwill_to_assets(raw["stocks"], fund_pit), on="sid", how="left")
    if "debt_structure" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_debt_structure(raw["stocks"], fund_pit), on="sid", how="left")
    if "asset_tangibility" in signals_to_run and not fund_pit.empty:
        base = base.merge(pit_asset_tangibility(raw["stocks"], fund_pit), on="sid", how="left")

    # Composite: needs mom_6m + mom_12m already computed in `base`
    if "mom_composite" in signals_to_run and "mom_6m" in base.columns and "mom_12m" in base.columns:
        base = base.merge(pit_mom_composite(base), on="sid", how="left")

    # ── Tier 2: factor composites — must run AFTER all sub-signals ──
    if "value_composite" in signals_to_run and {"earnings_yield", "book_to_price", "position_52w"}.issubset(base.columns):
        base = base.merge(pit_value_composite(base), on="sid", how="left")

    if "quality_composite" in signals_to_run and {"roe", "debt_to_equity", "profit_margin"}.issubset(base.columns):
        base = base.merge(pit_quality_composite(base), on="sid", how="left")

    if "growth_composite" in signals_to_run and {"revenue_growth_yoy", "eps_growth_yoy"}.issubset(base.columns):
        base = base.merge(pit_growth_composite(base), on="sid", how="left")

    # Emit ONLY the columns the requested signals actually produced.
    #
    # Why: `upsert_df` uses INSERT … ON CONFLICT(pk) DO UPDATE SET col=excluded.col
    # — per-column. If we padded missing columns with NaN here, a `--signal X`
    # rerun on an existing date would write NULL into every OTHER column, wiping
    # the earlier full run. Keeping the dataframe narrow makes `--signal` safe
    # by construction: untouched columns stay untouched on UPDATE, and default
    # to NULL on fresh INSERT (which is the same as "not computed yet").
    #
    # On a full default run every signal runs, so all PIT_COLUMNS naturally
    # appear in `base` and the behavior is identical to before.
    cols_to_emit = [c for c in PIT_COLUMNS if c in base.columns]
    df = base[cols_to_emit].copy()

    # ── Validation gate: clean ranges, drop infinities ──
    df, validation_summary = _validate_and_clean(df, cols_to_emit)

    return df, validation_summary


def pit_financial_signal(banking_metrics_full, eval_date):
    """Reconstruct financial_signal at eval_date using PIT-filtered banking_metrics.

    Delegates to signals.financial_signal.compute_pit which applies the
    quarterly_lag (60d) + annual_lag (75d) filters internally and runs the
    same algorithm as the live signal (40% asset quality + 30% profitability
    + 15% capital [NULL pre-2.2c] + 15% funding, renormalized).

    Returns DataFrame[sid, financial_signal] — NULL for non-financials and
    for insufficient-data stocks. Caller merges onto base; the upsert into
    daily_snapshots_pit naturally leaves financial_signal NULL for stocks
    not in the (Banks ∪ NBFCs) universe.
    """
    if banking_metrics_full is None or banking_metrics_full.empty:
        return pd.DataFrame(columns=["sid", "financial_signal"])
    from signals.financial_signal import compute_pit
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    return compute_pit(eval_str, banking_metrics_full)


def load_raw():
    """Load all raw history once. Avoids re-querying per eval_date."""
    print("Loading raw data...")
    stocks = read_sql("SELECT sid, cap_tier, sector FROM stocks")
    qi = read_sql(
        "SELECT sid, period, end_date, reporting, revenue, operating_profit, "
        "net_income, eps, interest, pbt, ebitda "
        "FROM quarterly_income WHERE end_date IS NOT NULL ORDER BY sid, end_date"
    )
    bs = read_sql(
        "SELECT sid, period, end_date, total_assets, total_equity, total_debt, "
        "current_assets, current_liabilities, cash_and_equivalents, receivables, "
        "retained_earnings, net_ppe, total_liabilities, shares_outstanding, long_term_debt "
        "FROM annual_balance_sheet WHERE end_date IS NOT NULL ORDER BY sid, end_date"
    )
    cf = read_sql(
        "SELECT sid, period, end_date, operating_cash_flow, capex, free_cash_flow, "
        "investing_cash_flow, financing_cash_flow, working_capital_change, "
        "depreciation, net_change_in_cash "
        "FROM annual_cash_flow WHERE end_date IS NOT NULL ORDER BY sid, end_date"
    )
    sh = read_sql(
        "SELECT sid, end_date, promoter_pct, pledge_pct, fii_pct, mf_pct, dii_pct, "
        "public_pct, insurance_pct, retail_hni_pct, other_pct "
        "FROM shareholding ORDER BY sid, end_date"
    )
    prices = read_sql(
        "SELECT sid, date, close, delivery_pct "
        "FROM stock_prices WHERE close > 0 ORDER BY sid, date"
    )
    adjustments = read_sql(
        "SELECT sid, ex_date, factor FROM corporate_adjustments ORDER BY sid, ex_date"
    )
    fh = read_sql(
        "SELECT sid, metric, date, value, change FROM forecast_history "
        "WHERE metric IN ('price', 'eps') AND value IS NOT NULL ORDER BY sid, metric, date"
    )
    # Monthly analyst consensus snapshots — preferred source for pt_upside
    # (more recent than Tickertape's year-end series). See HANDOFF 2026-05-22.
    try:
        acs = read_sql(
            "SELECT sid, snapshot_date, source, target_mean, target_median, "
            "n_analysts, recommendation_mean "
            "FROM analyst_consensus_snapshots "
            "WHERE target_mean IS NOT NULL ORDER BY sid, snapshot_date"
        )
    except Exception:
        acs = pd.DataFrame()
    bulk = read_sql(
        "SELECT sid, deal_date, quantity, price, buy_sell, client_name, symbol "
        "FROM bulk_deals ORDER BY sid, deal_date"
    )
    short = read_sql(
        "SELECT sid, short_date, quantity FROM short_selling_data WHERE sid IS NOT NULL ORDER BY sid, short_date"
    )
    # News volume: join articles to stocks, keep only date (not full timestamp)
    news = read_sql(
        "SELECT na.article_id, nas.sid, "
        "       SUBSTR(na.published_at, 1, 10) AS published_date "
        "FROM news_articles na "
        "JOIN news_article_stocks nas ON na.article_id = nas.article_id "
        "WHERE na.published_at IS NOT NULL"
    )
    # News article text — needed for sentiment_7d PIT (VADER on title+summary)
    news_text = read_sql(
        "SELECT na.article_id, nas.sid, "
        "       SUBSTR(na.published_at, 1, 10) AS published_date, "
        "       na.title, na.summary "
        "FROM news_articles na "
        "JOIN news_article_stocks nas ON na.article_id = nas.article_id "
        "WHERE na.published_at IS NOT NULL"
    )
    # Insider trades — depth from 2021-01 supports v1 PIT eval dates (2023-04+)
    insider_trades = read_sql(
        "SELECT sid, person_category, transaction_type, shares, value_lakhs, trade_date "
        "FROM insider_trades WHERE trade_date IS NOT NULL"
    )
    reg_events = read_sql(
        "SELECT event_id, published_at FROM regulatory_events WHERE published_at IS NOT NULL"
    )
    reg_signals = read_sql(
        "SELECT event_id, sector, direction, magnitude, confidence FROM regulatory_signals "
        "WHERE is_regulatory = 1 AND direction IS NOT NULL"
    )
    macro_hist = read_sql(
        "SELECT indicator_id, date, value FROM macro_history WHERE value IS NOT NULL ORDER BY indicator_id, date"
    )
    macro_map = read_sql(
        "SELECT indicator_id, sector, direction, weight FROM macro_sector_map"
    )
    # Track 3 fundamentals (long-format) — annual rows only for the cluster
    fund_screener = read_sql(
        "SELECT sid, period_end, line_item, value FROM fundamentals_screener "
        "WHERE period_type = 'annual'"
    )
    # Track 2.2b — Banking metrics for financial_signal PIT reconstruction.
    # Only ~3,400 rows (158 stocks × ~25 periods), so load all and filter
    # per eval_date inside the helper.
    try:
        banking_metrics = read_sql(
            "SELECT sid, period_end, period_type, gross_npa_pct, net_npa_pct, "
            "       interest_earned, net_interest_income, net_profit, cost_of_funds_pct "
            "FROM banking_metrics"
        )
    except Exception:
        banking_metrics = pd.DataFrame()
    print(f"  stocks={len(stocks)} qi={len(qi)} bs={len(bs)} cf={len(cf)} sh={len(sh)} "
          f"prices={len(prices)} adj={len(adjustments)} fh={len(fh)} acs={len(acs)} "
          f"bulk={len(bulk)} "
          f"reg_events={len(reg_events)} reg_signals={len(reg_signals)} "
          f"macro_hist={len(macro_hist)} macro_map={len(macro_map)} "
          f"fund_screener={len(fund_screener)}")
    return {
        "stocks": stocks, "qi": qi, "bs": bs, "cf": cf, "sh": sh, "prices": prices,
        "adjustments": adjustments,
        "fh": fh, "acs": acs, "bulk": bulk, "short": short, "news": news,
        "news_text": news_text, "insider_trades": insider_trades,
        "fund_screener": fund_screener,
        "banking_metrics": banking_metrics,
        "reg_events": reg_events, "reg_signals": reg_signals,
        "macro_hist": macro_hist, "macro_map": macro_map,
    }


def main():
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
                        choices=["piotroski", "accruals", "promoter", "forensic",
                                 "earnings_yield", "book_to_price", "momentum",
                                 "position_52w", "delivery", "pledge",
                                 "promoter_trend", "macd", "fwd_return",
                                 "mom_composite",
                                 "quality_fundamentals", "growth_fundamentals",
                                 "consensus",
                                 "value_composite", "quality_composite", "growth_composite",
                                 "pt_upside", "bulk_deal", "sector_overlays",
                                 "short_selling",
                                 "earnings_beat_rate", "news_volume",
                                 "sentiment_7d", "insider_signal",
                                 "revenue_cv", "inventory_turnover",
                                 "sales_growth_relative", "share_momentum",
                                 "cash_conversion_cycle",
                                 "operating_margin_trend",
                                 "working_capital_intensity",
                                 "interest_coverage",
                                 "roic", "fcf_yield", "roiic",
                                 "dso_change_yoy", "dio_change_yoy",
                                 "nwc_to_revenue", "sloan_accruals_full",
                                 "sga_to_revenue_change",
                                 "fcf_margin", "capex_to_dep",
                                 "goodwill_to_assets", "debt_structure",
                                 "asset_tangibility",
                                 "smart_money",
                                 "financial_signal"],
                        help="Compute only this signal (repeatable)")
    parser.add_argument("--date", action="append", default=None,
                        help="Explicit eval date (YYYY-MM-DD, repeatable). "
                             "Overrides --months/--weeks/--cadence date generation.")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip eval dates that already have a SUCCESS row in pit_reconstruction_log")
    args = parser.parse_args()

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
    DEFAULT_SIGNALS = {
        "piotroski", "accruals", "promoter", "forensic",
        "earnings_yield", "book_to_price", "momentum",
        "position_52w", "delivery", "pledge", "promoter_trend",
        "macd", "fwd_return", "mom_composite",
        "quality_fundamentals", "growth_fundamentals", "consensus",
        "value_composite", "quality_composite", "growth_composite",
        # Tier 3 unblocks
        "pt_upside", "bulk_deal", "sector_overlays",
        # Tier 4 new signal classes
        "short_selling",
        # Tier 4 quality + sentiment
        "earnings_beat_rate", "news_volume",
        # Behavior tier — added 2026-05-24
        "sentiment_7d", "insider_signal",
        # Track 3 cluster (plan 0003)
        "revenue_cv", "inventory_turnover",
        "sales_growth_relative", "share_momentum",
        # Track 3 standalone factors
        "cash_conversion_cycle",
        "operating_margin_trend",
        "working_capital_intensity",
        "interest_coverage",
        "roic", "fcf_yield", "roiic",
        # Forensic / capital-allocation batch (plan 0002 §3.2.1)
        "dso_change_yoy", "dio_change_yoy",
        "nwc_to_revenue", "sloan_accruals_full", "sga_to_revenue_change",
        "fcf_margin", "capex_to_dep", "goodwill_to_assets",
        "debt_structure", "asset_tangibility",
        # Plan 0005 Phase E composite (smart_money — accruals/promoter/forensic
        # composites flow through their existing _compute_scores)
        "smart_money",
        # Track 2.2b (2026-05-29) — Financial sub-model for Banks + NBFCs
        "financial_signal",
    }
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
