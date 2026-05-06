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
    """Reuse signals.accruals._compute_scores."""
    from signals.accruals import _compute_scores
    df = _compute_scores(stocks, qi_pit, bs_pit, cf_pit)
    out = df[["sid", "cf_accruals_ratio", "bs_accruals_ratio", "earnings_persistence"]].copy()
    out = out.rename(columns={
        "cf_accruals_ratio": "cf_accruals",
        "bs_accruals_ratio": "bs_accruals",
    })
    return out


def pit_promoter(stocks, sh_pit):
    """Reuse signals.promoter._compute_scores."""
    from signals.promoter import _compute_scores
    df = _compute_scores(stocks, sh_pit)
    return df[["sid", "promoter_qoq"]].copy()


def pit_forensic(stocks, qi_pit, bs_pit, cf_pit):
    """Reuse signals.forensic._compute_scores."""
    from signals.forensic import _compute_scores
    financial_sids = set(stocks[stocks["sector"].isin(FINANCIAL_SECTORS)]["sid"])
    df = _compute_scores(stocks, financial_sids, qi_pit, bs_pit, cf_pit)
    keep_cols = ["sid"]
    if "m_score" in df.columns:
        keep_cols.append("m_score")
    if "z_score" in df.columns:
        keep_cols.append("z_score")
    return df[keep_cols].copy()


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
    """PT revision YoY, EPS revision YoY, combined consensus signal.

    Uses forecast_history.{value, change} where metric IN ('price', 'eps').
    For each (sid, metric): find latest snapshot with date <= eval_date, then
    find the snapshot ~12 months prior; YoY = (latest/prior − 1).
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
        row = {"sid": sid}
        pt_yoy = _yoy(fh_by_sid_metric.get((sid, "price")))
        eps_yoy = _yoy(fh_by_sid_metric.get((sid, "eps")))
        if pt_yoy is not None:
            row["pt_revision_yoy"] = pt_yoy
        if eps_yoy is not None:
            row["eps_revision_yoy"] = eps_yoy
        # Combined: mean when both available, else single
        if pt_yoy is not None and eps_yoy is not None:
            row["consensus_signal_combined"] = round((pt_yoy + eps_yoy) / 2, 2)
        elif pt_yoy is not None:
            row["consensus_signal_combined"] = pt_yoy
        elif eps_yoy is not None:
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


def pit_pt_upside(stocks, fh_pit, close_df):
    """Implied upside from analyst price target.

    Uses forecast_history.value where metric='price' (NOT analyst_consensus, which
    is snapshot-only). For each sid: latest knowable PT / current close − 1.
    """
    if fh_pit.empty:
        return pd.DataFrame(columns=["sid", "pt_upside"])

    pt_only = fh_pit[fh_pit["metric"] == "price"]
    latest_pt = (pt_only.sort_values(["sid", "date"])
                 .groupby("sid")
                 .tail(1)[["sid", "value"]]
                 .rename(columns={"value": "latest_pt"}))

    merged = latest_pt.merge(close_df, on="sid", how="left")
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

    # ── Tier 3: pt_upside (uses forecast_history.price, not analyst_consensus) ──
    if "pt_upside" in signals_to_run:
        base = base.merge(pit_pt_upside(raw["stocks"], fh_pit, close_df), on="sid", how="left")

    # ── Tier 3: bulk_deal_signal (sparse — NULL for dates without bulk_deals data) ──
    if "bulk_deal" in signals_to_run and "bulk" in raw:
        bulk_pit = raw["bulk"][raw["bulk"]["deal_date"] <= eval_date.isoformat()]
        base = base.merge(pit_bulk_deal_signal(raw["stocks"], bulk_pit, px_pit, eval_date), on="sid", how="left")

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

    # Ensure every PIT_COLUMN exists (NaN for skipped signals)
    for col in PIT_COLUMNS:
        if col not in base.columns:
            base[col] = np.nan

    df = base[PIT_COLUMNS].copy()

    # ── Validation gate: clean ranges, drop infinities ──
    df, validation_summary = _validate_and_clean(df, PIT_COLUMNS)

    return df, validation_summary


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
    bulk = read_sql(
        "SELECT sid, deal_date, quantity, price, buy_sell FROM bulk_deals ORDER BY sid, deal_date"
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
    print(f"  stocks={len(stocks)} qi={len(qi)} bs={len(bs)} cf={len(cf)} sh={len(sh)} "
          f"prices={len(prices)} adj={len(adjustments)} fh={len(fh)} bulk={len(bulk)} "
          f"reg_events={len(reg_events)} reg_signals={len(reg_signals)} "
          f"macro_hist={len(macro_hist)} macro_map={len(macro_map)}")
    return {
        "stocks": stocks, "qi": qi, "bs": bs, "cf": cf, "sh": sh, "prices": prices,
        "adjustments": adjustments,
        "fh": fh, "bulk": bulk, "short": short, "news": news,
        "reg_events": reg_events, "reg_signals": reg_signals,
        "macro_hist": macro_hist, "macro_map": macro_map,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--months", type=int, default=7,
                        help="Number of monthly eval dates back from today (default 7)")
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
                                 "earnings_beat_rate", "news_volume"],
                        help="Compute only this signal (repeatable)")
    parser.add_argument("--skip-existing", action="store_true",
                        help="Skip eval dates that already have a SUCCESS row in pit_reconstruction_log")
    args = parser.parse_args()

    eval_dates = generate_eval_dates(months_back=args.months)
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
