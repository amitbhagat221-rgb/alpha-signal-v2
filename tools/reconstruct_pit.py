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
import importlib
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import factors
from config import SCREEN
from db import get_db, read_sql, upsert_df
from signals import _annual
from signals._prices import apply_adjustments

# ── Filing lags ──
ANNUAL_LAG = 75
QUARTERLY_LAG = 60
SHAREHOLDING_LAG = 21

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])


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

# Columns + per-column validation ranges ((min, max, allow_nan), out-of-range → NaN)
# come from the factor registry (factors.py): a factor entry carries its
# "producer" and "pit_range". Never hand-edit a copy here.
PIT_COLUMNS = factors.PIT_COLUMNS
VALIDATION_RANGES = factors.VALIDATION_RANGES


def _validate_and_clean(df, columns):
    """Apply per-column range gates (factors.discard_out_of_range): ±inf and
    out-of-range → NaN. Returns (df, summary).

    summary rows = {column: {n_valid, n_nan, n_out_of_range, min, max}}
    """
    out_of_range = factors.discard_out_of_range(df, columns)
    summary = {}
    for col, n_out in out_of_range.items():
        n_valid = int(df[col].notna().sum())
        summary[col] = {
            "valid": n_valid,
            "nan": int(len(df) - n_valid),
            "out_of_range": n_out,
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
    """Add `adj_close` (PIT-strict corporate adjustment, ex_date ≤ eval_date) —
    signals._prices.apply_adjustments, shared with the live screener."""
    return apply_adjustments(prices_pit, adjustments, eval_date)


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
    """TTM EPS as of eval_date / close as of eval_date (signals.earnings_yield)."""
    from signals.earnings_yield import earnings_yield
    return earnings_yield(qi_pit, close_df)


def pit_book_to_price(bs_pit, close_df):
    """Latest known book equity per share / close as of eval_date (signals.book_to_price)."""
    from signals.book_to_price import book_to_price
    return book_to_price(bs_pit, close_df)


def pit_position_52w(prices_pit, eval_date):
    """(close − 52w_low) / (52w_high − 52w_low) over the trailing 252 trading days,
    NaN below 60 days (signals.value_composite.position_52w — the live function;
    adj_close, so a split inside the window does not stretch the range)."""
    from signals.value_composite import position_52w
    return position_52w(prices_pit)


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
    """Today's delivery % vs 90-day mean, normalized by 90-day std.
    Same function the live screener calls — one implementation, no twin drift."""
    from signals.delivery_anomaly import delivery_anomaly_z
    return delivery_anomaly_z(prices_pit, window=window)


def pit_delivery(prices_pit):
    """The `delivery` producer: avg_delivery_pct_30d + delivery_anomaly_z."""
    return pit_avg_delivery(prices_pit).merge(pit_delivery_anomaly_z(prices_pit), on="sid", how="outer")


def pit_pledge_quality(stocks, sh_pit):
    """1 - (latest pledge_pct / 100), from the live producer (signals.promoter) —
    plan 0015 Phase 3 replaced a copy here that rounded to 4dp."""
    from signals.promoter import _compute_scores
    df = _compute_scores(stocks, sh_pit)
    if "pledge_quality" not in df.columns:
        return pd.DataFrame({"sid": stocks["sid"]})
    return df[["sid", "pledge_quality"]].copy()


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


_FWD_MAX_GAP_DAYS = 7  # ≤5 trading days ≈ ≤7 calendar days (weekend/holiday slack)


def pit_fwd_return_20d(eval_date, raw_prices_full):
    """20-trading-day forward return per sid, with anchor-proximity guards.

    Uses the FULL price history (not the PIT-filtered slice) since we need
    prices AFTER eval_date. NULL if 20 trading days haven't elapsed yet.

    ANCHOR-PROXIMITY GUARD (2026-07-05, panel-integrity fix). A sid's forward
    return is valid ONLY IF:
      (a) its ENTRY price row (first row on/after eval_date) is within
          _FWD_MAX_GAP_DAYS calendar days of eval_date, AND
      (b) its EXIT price row (entry + 20 rows in the sid's own series) is
          within _FWD_MAX_GAP_DAYS calendar days of the target exit date —
          i.e. 20 trading days after eval_date on the MARKET calendar.
    Otherwise emit NULL for that sid/anchor.

    Why: the prior code anchored a sid that had NO price rows near an old
    eval_date at its FIRST LATER price row (via searchsorted), pairing old
    fundamentals with a wrong-period return. ~40% of response pairs at
    pre-2023 anchors were late-anchored (the 2020-22 jugaad backfill covers
    only ~70% of sids), so every fundamentals-based factor's pre-2023 IC was
    contaminated. Price-based factors were immune (their signal already
    requires a price at the anchor). The exit-side guard catches the
    symmetric case: a sid with a data gap between entry and exit whose
    "+20 rows" spans far more than 20 real trading days.
    """
    rows = []
    eval_str = eval_date.isoformat()
    eval_d = eval_date if isinstance(eval_date, date) else \
        datetime.strptime(eval_str[:10], "%Y-%m-%d").date()

    # Market trading calendar = sorted unique dates across ALL sids. Used to
    # define what "20 trading days after eval_date" means independent of any
    # single sid's (possibly gappy) coverage.
    cal = np.sort(raw_prices_full["date"].unique())
    m_anchor = int(np.searchsorted(cal, eval_str))
    all_sids = raw_prices_full["sid"].unique()
    # eval_date beyond history, or fewer than 20 market days of forward window
    # remaining → nothing is measurable this anchor.
    if m_anchor >= len(cal) or m_anchor + 20 >= len(cal):
        return pd.DataFrame({"sid": all_sids})
    target_exit_str = str(cal[m_anchor + 20])[:10]
    target_exit_d = datetime.strptime(target_exit_str, "%Y-%m-%d").date()

    # For each sid, find the close at the trading day on/after eval_date
    # and the close 20 trading days later.
    for sid, group in raw_prices_full.groupby("sid"):
        g = group.sort_values("date")
        dates = g["date"].values
        # First trading day >= eval_date
        anchor_idx = int(np.searchsorted(dates, eval_str))
        if anchor_idx >= len(g):
            rows.append({"sid": sid})
            continue
        # (a) ENTRY proximity guard
        entry_d = datetime.strptime(str(dates[anchor_idx])[:10], "%Y-%m-%d").date()
        if abs((entry_d - eval_d).days) > _FWD_MAX_GAP_DAYS:
            rows.append({"sid": sid})
            continue
        target_idx = anchor_idx + 20
        if target_idx >= len(g):
            rows.append({"sid": sid})
            continue
        # (b) EXIT proximity guard
        exit_d = datetime.strptime(str(dates[target_idx])[:10], "%Y-%m-%d").date()
        if abs((exit_d - target_exit_d).days) > _FWD_MAX_GAP_DAYS:
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

    `pt_revision_yoy` was DROPPED 2026-05-23 — `forecast_history.metric=price`
    is current-close masquerading as PT, so its YoY = 1-year price return, not
    PT revision. The combined signal is now eps-revision only until the
    `analyst_consensus_snapshots` monthly history accumulates ≥12 months
    (calendar: 2027-05). See memory `forecast_history_price_contaminated`.
    eps_revision_yoy is signals.eps_revision.eps_revision_yoy — the live producer.
    """
    if fh_pit.empty:
        return pd.DataFrame(columns=["sid", "pt_revision_yoy", "eps_revision_yoy", "consensus_signal_combined"])
    from signals.eps_revision import eps_revision_yoy
    eps = eps_revision_yoy(fh_pit[fh_pit["metric"] == "eps"])
    out = stocks[["sid"]].merge(eps, on="sid", how="left")
    out["pt_revision_yoy"] = None  # always NULL; data source contaminated
    out["consensus_signal_combined"] = out["eps_revision_yoy"]
    return out[["sid", "pt_revision_yoy", "eps_revision_yoy", "consensus_signal_combined"]]


def _within_tier_rank_composite(df, components, name):
    """NaN-tolerant within-cap_tier rank composite (signals.value_composite)."""
    from signals.value_composite import within_tier_rank_composite
    return within_tier_rank_composite(df, components, name)


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


def pit_pt_upside(stocks, close_df, acs_pit=None):
    """Implied upside from analyst price target.

    Source: analyst_consensus_snapshots ONLY — monthly snapshots of Yahoo's
    aggregate, available from 2026-05 onwards. `forecast_history` (metric=
    'price') is PERMANENTLY EXCLUDED: those "year-end" rows embed the
    YEAR-AHEAD realized close, not a real analyst PT (audit Factor-F1,
    CRITICAL — every pre-2026-05 pt_upside value was built from this
    contamination). For anchors with no analyst_consensus_snapshots row
    ≤ eval_date, pt_upside is correctly NULL — do not backfill from any
    other source.
    """
    if acs_pit is None or acs_pit.empty:
        return pd.DataFrame(columns=["sid", "pt_upside"])

    latest_acs = (acs_pit.sort_values(["sid", "snapshot_date"])
                  .groupby("sid")
                  .tail(1)[["sid", "target_mean"]]
                  .rename(columns={"target_mean": "latest_pt"}))

    merged = latest_acs.merge(close_df, on="sid", how="left")
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


def pit_sector_momentum(stocks, px_pit, macro_hist, eval_date):
    """Per-stock sector-momentum factor, PIT — Plan 0006 Phase E.

    Reuses signals.sector_momentum's core verbatim (the "ship factor + PIT as one
    unit" rule): the same constituent cap-weighted relative-strength-vs-NIFTY
    computation, fed PIT-frozen frames. px_pit is already filtered through
    eval_date; nifty50 history and the (current) sector/market_cap map are passed
    in. Returns DataFrame[sid, sector_momentum].
    """
    from signals.sector_momentum import (
        compute_sector_momentum, sector_momentum_for_stocks,
    )
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    if macro_hist is None or macro_hist.empty:
        return pd.DataFrame(columns=["sid", "sector_momentum"])
    nifty = (macro_hist[(macro_hist["indicator_id"] == "nifty50")
                        & (macro_hist["date"] <= eval_str)][["date", "value"]]
             .sort_values("date"))
    prices = px_pit[["sid", "date", "close"]].sort_values(["sid", "date"])
    stk = stocks[["sid", "sector", "market_cap_cr"]]
    sm = compute_sector_momentum(prices=prices, nifty=nifty, stocks=stk)
    return sector_momentum_for_stocks(sector_mom=sm, stocks=stocks[["sid", "sector"]])


def pit_sector_tilt(stocks, px_pit, macro_sector_full, eval_date):
    """Per-stock sector-tilt factor, PIT — the validated 6m-mom + macro ensemble (ADR 0041).

    Reuses signals.sector_tilt's core verbatim ("ship factor + PIT as one unit"):
      • px_pit is already filtered ≤ eval_date and corp-action-adjusted → the 6m
        basket-momentum leg.
      • macro_sector_full (the reconstructed macro_sector_signals_pit) is sliced to
        snapshot_date ≤ eval_date and reduced to the latest row per sector → the
        macro_score leg. Empty (before the first macro anchor, 2022-08) → the core
        falls back to the momentum z alone, matching the validation.

    Returns DataFrame[sid, sector_tilt].
    """
    from signals.sector_tilt import compute_sector_tilt
    cols = ["sid", "sector_tilt"]
    if px_pit is None or px_pit.empty:
        return pd.DataFrame(columns=cols)
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    if macro_sector_full is not None and not macro_sector_full.empty:
        ms = macro_sector_full[macro_sector_full["snapshot_date"] <= eval_str]
        ms = (ms.sort_values("snapshot_date").groupby("sector", as_index=False).last()
              [["sector", "macro_score"]]) if not ms.empty else pd.DataFrame(
                  columns=["sector", "macro_score"])
    else:
        ms = pd.DataFrame(columns=["sector", "macro_score"])
    prices = px_pit[["sid", "date", "close"]].sort_values(["sid", "date"])
    return compute_sector_tilt(prices=prices, macro_sector=ms,
                               stocks=stocks[["sid", "sector"]])


def pit_fno_oi(fno_pcr_full, eval_date):
    """F&O open-interest factors, PIT — Plan 0002 §3.2.2 (OI half).

    Reuses signals.fno_oi_factors's core verbatim, fed an as-of-frozen slice of
    fno_pcr_history (trade_date ≤ eval_date). The core itself takes the latest
    row per stock for the level factors and the most recent same-expiry prior row
    for oi_buildup — so passing the frozen frame is all the PIT-ness it needs.

    Returns DataFrame[sid, pcr_oi, pcr_volume, max_pain_distance, oi_buildup_signal].
    NULL for any date before the fno_pcr_history backfill begins (2025-11-27).
    """
    cols = ["sid", "pcr_oi", "pcr_volume", "max_pain_distance", "oi_buildup_signal"]
    if fno_pcr_full is None or fno_pcr_full.empty:
        return pd.DataFrame(columns=cols)
    from signals.fno_oi_factors import compute_oi_factors
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    pit = fno_pcr_full[fno_pcr_full["trade_date"] <= eval_str]
    return compute_oi_factors(pcr_hist=pit)


def pit_fno_iv(fno_iv_full, px_pit, eval_date):
    """F&O implied-volatility factors, PIT — Plan 0002 §3.2.2 (IV half).

    Reuses signals.fno_iv_factors's core verbatim, fed an as-of-frozen slice of
    fno_iv_history (≤ eval_date) for the skew/term/percentile inputs and the
    PIT-adjusted price frame for the realised-vol leg of iv_realised_spread.

    Returns DataFrame[sid, iv_skew_25d, iv_term_structure, iv_realised_spread,
    iv_percentile_1y]. NULL before the fno_iv_history backfill begins.
    """
    cols = ["sid", "iv_skew_25d", "iv_term_structure", "iv_realised_spread", "iv_percentile_1y"]
    if fno_iv_full is None or fno_iv_full.empty:
        return pd.DataFrame(columns=cols)
    from signals.fno_iv_factors import compute_iv_factors
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    iv_pit = fno_iv_full[fno_iv_full["trade_date"] <= eval_str]
    prices = px_pit[["sid", "date", "close"]] if px_pit is not None and not px_pit.empty else None
    from config import SCREEN
    return compute_iv_factors(iv_hist=iv_pit, prices=prices, as_of_date=eval_str,
                              max_age_days=SCREEN.get("max_signal_age_days", 45))


def pit_microstructure(ohlc_full, eval_date):
    """Daily microstructure factors, PIT — Plan 0002 §3.2.3 (the 6 daily-derivable).

    Reuses signals.microstructure's core verbatim, fed an as-of-frozen OHLCV slice
    (date ≤ eval_date). Raw (unadjusted) prices, same split stance as the live path.

    Returns DataFrame[sid, intraday_range_compression, closing_strength_1m,
    opening_gap_freq_1m, vwap_deviation_5d, bidask_spread_proxy, kyle_lambda].
    """
    from signals.microstructure import compute_microstructure, CLIPS
    cols = ["sid", *CLIPS.keys()]
    if ohlc_full is None or ohlc_full.empty:
        return pd.DataFrame(columns=cols)
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    pit = ohlc_full[ohlc_full["date"] <= eval_str]
    return compute_microstructure(prices=pit)


def pit_industry_id(stocks_full):
    """Industry identity code, PIT — Plan 0002 §3.2.6.

    Reuses signals.industry_id's frozen mapping. Industry is a static stock
    attribute, so there's no as-of slicing — the code is the same on every date.

    Returns DataFrame[sid, industry_id] (0 = unknown/NULL, 1..38 frozen).
    """
    from signals.industry_id import compute_industry_id
    if stocks_full is None or stocks_full.empty:
        return pd.DataFrame(columns=["sid", "industry_id"])
    return compute_industry_id(stocks=stocks_full)


def pit_macro_betas(px_pit, macro_hist_full, eval_date):
    """Per-stock macro betas, PIT — Plan 0002 §3.2.7.

    Reuses signals.macro_betas's core verbatim, fed the PIT-adjusted price frame
    (sid,date,close ≤ eval_date) and an as-of-frozen slice of macro_history
    (date ≤ eval_date). NULL for early anchors lacking ~1y of macro lookback
    (macro_history now reaches 2015-06; rate_beta computable from ~2017,
    credit_beta from ~2020 once the gilt/credit ETF series have 252d depth).

    Returns DataFrame[sid, oil_beta, metals_beta, inr_beta, gold_beta,
                      rate_beta, credit_beta].
    """
    from signals.macro_betas import compute_macro_betas, FACTORS
    cols = ["sid", *FACTORS]
    if px_pit is None or px_pit.empty or macro_hist_full is None or macro_hist_full.empty:
        return pd.DataFrame(columns=cols)
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    macro_pit = macro_hist_full[macro_hist_full["date"] <= eval_str]
    prices = px_pit[["sid", "date", "close"]]
    return compute_macro_betas(prices=prices, macro_hist=macro_pit)


def pit_pead(qi_pit, px_pit, macro_hist, corp_full, bse_results, eval_date):
    """Event-time / PEAD factors, PIT — Plan 0002 §3.2.5.

    qi_pit is the knowable-quarterly slice (announcement lag already applied);
    px_pit is prices ≤ eval (adjusted); nifty50 + corporate_actions filtered to
    ≤ eval. bse_results is the BSE 'Result' announcement-date stream [sid, ann_date]
    — compute_pead anchors the drift window to the real `dt_tm` and itself drops any
    row after eval (look-ahead safe), so passing the full frame is fine. Reuses
    signals.pead's core verbatim.

    Returns DataFrame[sid, earnings_surprise_std, pead_drift_60d,
    corporate_action_density, buyback_announcement_30d].
    """
    from signals.pead import compute_pead
    cols = ["sid", "earnings_surprise_std", "pead_drift_60d",
            "corporate_action_density", "buyback_announcement_30d"]
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    qi = qi_pit[["sid", "end_date", "eps"]].dropna(subset=["eps"]) if qi_pit is not None and not qi_pit.empty else pd.DataFrame()
    if qi.empty:
        return pd.DataFrame(columns=cols)
    nifty = (macro_hist[(macro_hist["indicator_id"] == "nifty50")
                        & (macro_hist["date"] <= eval_str)][["date", "value"]]
             if macro_hist is not None and not macro_hist.empty else pd.DataFrame(columns=["date", "value"]))
    prices = px_pit[["sid", "date", "close"]] if px_pit is not None and not px_pit.empty else pd.DataFrame()
    corp = (corp_full[corp_full["ex_date"] <= eval_str]
            if corp_full is not None and not corp_full.empty else pd.DataFrame(columns=["sid", "ex_date", "subject"]))
    ann = (bse_results[["sid", "ann_date"]]
           if bse_results is not None and not bse_results.empty
           else pd.DataFrame(columns=["sid", "ann_date"]))
    return compute_pead(qi=qi, prices=prices, nifty=nifty, corp_actions=corp,
                        announcements=ann, as_of_date=eval_str)


def pit_announcement_car(px_pit, macro_hist, bse_results, eval_date):
    """Announcement-window CAR, PIT — market-implied earnings surprise (Plan 0002 §3.2.5).

    px_pit is prices ≤ eval with PIT-strict adj_close already applied by the
    orchestrator (a split inside the 3-day event window would otherwise fake a CAR);
    macro_hist supplies the NIFTY-50 benchmark leg (filtered ≤ eval here); bse_results
    is the BSE 'Result' announcement-date stream [sid, ann_date] — compute_announcement_car
    applies the ≤ eval look-ahead filter itself, so the full frame is fine. NaN for names
    with no qualifying recent print (no 0-fill — a missing print is "no reading").

    Returns DataFrame[sid, announcement_car].
    """
    from signals.announcement_car import compute_announcement_car
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    cols = ["sid", "announcement_car"]
    if px_pit is None or px_pit.empty or bse_results is None or bse_results.empty:
        return pd.DataFrame(columns=cols)
    price_col = "adj_close" if "adj_close" in px_pit.columns else "close"
    prices = px_pit[["sid", "date", price_col]].rename(columns={price_col: "adj_close"})
    nifty = (macro_hist[(macro_hist["indicator_id"] == "nifty50")
                        & (macro_hist["date"] <= eval_str)][["date", "value"]]
             if macro_hist is not None and not macro_hist.empty else pd.DataFrame(columns=["date", "value"]))
    ann = bse_results[["sid", "ann_date"]]
    return compute_announcement_car(prices=prices, nifty=nifty, announcements=ann, as_of_date=eval_str)


def pit_governance_resignation(stocks, bse_gov, eval_date):
    """Governance/forensic resignation density, PIT — BSE event stream (ADR 0042).

    bse_gov is the resignation/cessation subcategory slice [sid, subcategory, ev_date];
    compute_governance_resignation filters ev_date ≤ eval itself (look-ahead safe via
    the `dt_tm`-derived date), so the full frame can be passed. Reindexed to the
    universe so non-event names score 0 (flagged-vs-unflagged contrast for the backtest).

    Returns DataFrame[sid, governance_resignation].
    """
    from signals.governance_events import compute_governance_resignation
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    universe = stocks["sid"].tolist() if stocks is not None and not stocks.empty else None
    ann = (bse_gov[["sid", "subcategory", "ev_date"]]
           if bse_gov is not None and not bse_gov.empty
           else pd.DataFrame(columns=["sid", "subcategory", "ev_date"]))
    return compute_governance_resignation(announcements=ann, universe_sids=universe,
                                          as_of_date=eval_str)


def pit_low_vol_252d(px_pit):
    """Low volatility (annualized 252d log-return std), PIT — audit Factor-F3 #1.

    px_pit is prices ≤ eval with PIT-strict adj_close already applied by the
    orchestrator; compute_low_vol_252d prefers adj_close so a split inside the
    window doesn't manufacture a fake vol spike. Same module, identical logic
    on the live path. Returns DataFrame[sid, low_vol_252d].
    """
    from signals.low_vol import compute_low_vol_252d
    return compute_low_vol_252d(prices=px_pit)


def pit_st_reversal_21d(px_pit):
    """Short-term reversal (trailing 21d total return), PIT — audit Factor-F3 #2.

    px_pit is prices ≤ eval with PIT-strict adj_close applied; the module
    prefers adj_close so a split inside the month doesn't read as a fake −50%.
    Returns DataFrame[sid, st_reversal_21d].
    """
    from signals.st_reversal import compute_st_reversal_21d
    return compute_st_reversal_21d(prices=px_pit)


def pit_residual_momentum_12_1(px_pit, macro_hist, eval_date):
    """12-1 momentum residualized against NIFTY-50 beta, PIT — plan 0012 C3 (WS2.6).

    px_pit is prices ≤ eval with PIT-strict adj_close applied; macro_hist is the
    full macro_history frame (filtered to indicator nifty50, date ≤ eval, inside
    the module). Returns DataFrame[sid, residual_momentum_12_1].
    """
    from signals.residual_momentum import compute_residual_momentum_12_1, NIFTY_ID
    eval_iso = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    nifty = macro_hist[
        (macro_hist["indicator_id"] == NIFTY_ID)
        & (macro_hist["value"] > 0)
        & (macro_hist["date"] <= eval_iso)
    ][["date", "value"]].sort_values("date") if macro_hist is not None and not macro_hist.empty else None
    return compute_residual_momentum_12_1(prices=px_pit, nifty=nifty, as_of_date=eval_iso)


def pit_max_lottery_21d(px_pit):
    """MAX lottery factor (mean of top-5 daily returns, trailing 21d), PIT —
    plan 0012 C4 (WS2.7). Returns DataFrame[sid, max_lottery_21d].
    """
    from signals.max_lottery import compute_max_lottery_21d
    return compute_max_lottery_21d(prices=px_pit)


def pit_asset_growth_yoy(stocks, bs_pit):
    """Asset growth YoY % (CMA investment factor), PIT — audit Factor-F3 #3.

    bs_pit is the knowable-annual slice (75d SEBI filing lag already applied by
    the orchestrator via knowable_annual — the exact book_to_price/piotroski
    convention); the module takes the two latest knowable annual rows per sid.
    Returns DataFrame[sid, asset_growth_yoy] (percent; non-financials only).
    """
    from signals.asset_growth import compute_asset_growth_yoy
    return compute_asset_growth_yoy(bs=bs_pit, stocks=stocks)


def pit_nlp_factors(stocks, nlp_scores, eval_date):
    """Earnings-call NLP factors, PIT — off nlp_scores (Plan 0002 §3.2.4).

    nlp_scores is the full enriched frame [sid, doc_date, available_date, net_tone,
    uncertainty_density, forward_looking_intensity]; compute_nlp_factors filters
    available_date ≤ eval and within FRESH_DAYS itself (look-ahead safe via the real
    BSE-filing date carried into available_date — Next-3 #1c). NaN for names with no
    recent transcript (no 0-fill — a missing call is "no data", not a reading).

    Returns DataFrame[sid, earnings_call_tone_qoq, forward_looking_intensity, uncertainty_word_density].
    """
    from signals.nlp_factors import compute_nlp_factors
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    universe = stocks["sid"].tolist() if stocks is not None and not stocks.empty else None
    nlp = (nlp_scores if nlp_scores is not None and not nlp_scores.empty
           else pd.DataFrame(columns=["sid", "doc_date", "available_date", "net_tone",
                                      "uncertainty_density", "forward_looking_intensity"]))
    return compute_nlp_factors(nlp=nlp, universe_sids=universe, as_of_date=eval_str)


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
    """Risk-adjusted 6M and 12M momentum as of eval_date (signals.momentum.momentum —
    the live function; adj_close preferred)."""
    from signals.momentum import momentum
    return momentum(prices_pit)


# ───── Screener-ratio factors (fundamentals_screener) ─────
# Each delegates to its signals/<name>.py `_compute` on the filing-lagged fund_pit
# slice, scoped to that module live universe/line items (signals/_annual.py) —
# one implementation per factor, live and PIT.

def _fund_factor(module, col, stocks, fund_pit, items=None, excluded=None):
    mod = importlib.import_module(f"signals.{module}")
    return _annual.pit_frame(mod._compute, stocks, fund_pit,
                             items if items is not None else mod.REQUIRED_ITEMS, col,
                             excluded if excluded is not None else _annual.FINANCIAL_SECTORS)


def pit_revenue_cv(stocks, fund_pit):
    """Revenue volatility 5y CV — stdev/|mean| of last 5 YoY Sales growth rates."""
    return _fund_factor("revenue_cv", "revenue_cv_5y", stocks, fund_pit, ["Sales"], set())


def pit_inventory_turnover(stocks, fund_pit):
    """Sales/Inventory, 3-yr median, ranked vs sector p50."""
    from signals.inventory_turnover import EXCLUDED_SECTORS
    return _fund_factor("inventory_turnover", "relative_turnover", stocks, fund_pit,
                        ["Sales", "Inventory"], EXCLUDED_SECTORS)


def pit_sales_growth_relative(stocks, fund_pit):
    """3-yr median YoY Sales growth minus sector median."""
    return _fund_factor("sales_growth_relative", "relative_growth", stocks, fund_pit, ["Sales"])


def pit_share_momentum(stocks, fund_pit, prices_pit, eval_date,
                       window_days=90):
    """Δ market_cap_share within sector over `window_days` calendar days
    (signals/share_momentum.sector_share_change on the as-of closes + latest known shares)."""
    from signals.share_momentum import sector_share_change
    universe = stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)][["sid", "sector"]]
    shares = fund_pit[fund_pit["line_item"] == "No. of Equity Shares"]
    if shares.empty or prices_pit.empty:
        return pd.DataFrame(columns=["sid", "share_momentum"])
    shares = (shares.sort_values(["sid", "period_end"])
                    .groupby("sid", as_index=False).tail(1)
                    [["sid", "value"]].rename(columns={"value": "shares_outstanding"}))

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
    return sector_share_change(df)[["sid", "share_momentum"]].copy()


def pit_cash_conversion_cycle(stocks, fund_pit):
    """3-yr median CCC = DSO + DIO − DPO, all using Sales/365 as denominator."""
    return _fund_factor("cash_conversion_cycle", "ccc", stocks, fund_pit)


def pit_operating_margin_trend(stocks, fund_pit):
    """OLS slope (pp/yr) of last 5y EBIT/Sales per sid."""
    return _fund_factor("operating_margin_trend", "margin_slope", stocks, fund_pit)


def pit_working_capital_intensity(stocks, fund_pit):
    """3y median (Recv + Inv − Pay) / Sales per sid."""
    return _fund_factor("working_capital_intensity", "wc_intensity", stocks, fund_pit)


def pit_interest_coverage(stocks, fund_pit):
    """3y median (PBT + Interest) / Interest per sid, capped at ±200."""
    return _fund_factor("interest_coverage", "interest_coverage", stocks, fund_pit)


def pit_roic(stocks, fund_pit):
    """3y median ROIC = NOPAT / Invested Capital per sid (signals/roic.py)."""
    return _fund_factor("roic", "roic", stocks, fund_pit)


def pit_gross_profitability(stocks, fund_pit):
    """3y-median gross-profits-to-assets per sid (signals/gross_profitability.py) —
    the Novy-Marx anchor of the multibagger funnel."""
    from signals.gross_profitability import ALL_ITEMS
    return _fund_factor("gross_profitability", "gross_profitability", stocks, fund_pit, ALL_ITEMS)


def pit_roiic(stocks, fund_pit):
    """5y endpoint ROIIC = ΔNOPAT / ΔIC per sid, capped ±5 (signals/roiic.py)."""
    return _fund_factor("roiic", "roiic", stocks, fund_pit)


# Forensic / capital-allocation batch (plan 0002 §3.2.1)

def pit_dso_change_yoy(stocks, fund_pit):
    return _fund_factor("dso_change_yoy", "dso_change_yoy", stocks, fund_pit)


def pit_dio_change_yoy(stocks, fund_pit):
    return _fund_factor("dio_change_yoy", "dio_change_yoy", stocks, fund_pit)


def pit_nwc_to_revenue(stocks, fund_pit):
    return _fund_factor("nwc_to_revenue", "nwc_to_revenue", stocks, fund_pit)


def pit_sloan_accruals_full(stocks, fund_pit):
    return _fund_factor("sloan_accruals_full", "sloan_accruals_full", stocks, fund_pit)


def pit_sga_to_revenue_change(stocks, fund_pit):
    return _fund_factor("sga_to_revenue_change", "sga_to_revenue_change", stocks, fund_pit)


def pit_fcf_margin(stocks, fund_pit):
    return _fund_factor("fcf_margin", "fcf_margin", stocks, fund_pit)


def pit_capex_to_dep(stocks, fund_pit):
    return _fund_factor("capex_to_dep", "capex_to_dep", stocks, fund_pit)


def pit_goodwill_to_assets(stocks, fund_pit):
    return _fund_factor("goodwill_to_assets", "goodwill_to_assets", stocks, fund_pit)


def pit_debt_structure(stocks, fund_pit):
    return _fund_factor("debt_structure", "debt_structure", stocks, fund_pit)


def pit_asset_tangibility(stocks, fund_pit):
    return _fund_factor("asset_tangibility", "asset_tangibility", stocks, fund_pit)


def pit_fcf_yield(stocks, fund_pit, close_df):
    """3y median FCF (signals/fcf_yield.fcf_median) / PIT market_cap_cr per sid.

    Market cap is reconstructed PIT as (close × No. of Equity Shares) / 1e7
    (rupees → ₹cr) so the yield is dimensionless — the live signal divides by
    the stocks table current market cap instead.
    """
    from signals.fcf_yield import MIN_MARKET_CAP_CR, REQUIRED_ITEMS, RUPEES_PER_CRORE, fcf_median
    _, fund_u = _annual.scope(stocks, fund_pit, REQUIRED_ITEMS)
    agg = fcf_median(fund_u)
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
    mc["market_cap_cr"] = (mc["close_price"] * mc["shares"]) / RUPEES_PER_CRORE
    mc = mc[mc["market_cap_cr"] >= MIN_MARKET_CAP_CR]

    out = agg.merge(mc[["sid", "market_cap_cr"]], on="sid", how="inner")
    out["fcf_yield"] = out["fcf"] / out["market_cap_cr"]
    return out[["sid", "fcf_yield"]].reset_index(drop=True)


# ─────────────────────── Driver ───────────────────────

def _pit_input(ctx, raw, key, eval_date):
    """One per-date input frame for the producers (factors.PIT_PRODUCERS "inputs"),
    sliced to what was knowable on eval_date on first use and memoised in `ctx`."""
    if key in ctx:
        return ctx[key]
    d = eval_date.isoformat()
    if key == "qi":
        v = knowable_quarterly(raw["qi"], eval_date)
    elif key in ("bs", "cf"):
        v = knowable_annual(raw[key], eval_date)
    elif key == "sh":
        v = knowable_shareholding(raw["sh"], eval_date)
    elif key == "fh":
        v = raw["fh"][raw["fh"]["date"] <= d] if "fh" in raw else pd.DataFrame()
    elif key == "acs":
        v = (raw["acs"][raw["acs"]["snapshot_date"] <= d]
             if "acs" in raw and not raw["acs"].empty else pd.DataFrame())
    elif key == "bulk":
        v = raw["bulk"][raw["bulk"]["deal_date"] <= d]
    elif key == "short":
        v = raw["short"][raw["short"]["short_date"] <= d]
    elif key in ("news", "news_text"):
        v = raw[key][raw[key]["published_date"] <= d]
    elif key == "insider_trades":
        v = raw["insider_trades"][raw["insider_trades"]["trade_date"] <= d]
    elif key == "fund":
        v = knowable_screener(raw["fund_screener"], eval_date) if "fund_screener" in raw else pd.DataFrame()
    elif key == "financial_sids":
        v = set(raw["stocks"][raw["stocks"]["sector"].isin(FINANCIAL_SECTORS)]["sid"])
    else:   # full-history frames the helpers filter themselves (or None when not loaded)
        v = raw.get(key)
    ctx[key] = v
    return v


def reconstruct_one_date(eval_date, raw, signals_to_run):
    """Reconstruct all enabled signals for a single eval_date. No DB writes.

    `raw` is a dict of full-history DataFrames (loaded once, reused across dates).
    Every producer in factors.PIT_PRODUCERS whose name (or alias) is in
    `signals_to_run` runs, in registry order, and merges its columns onto the
    universe frame. Returns (DataFrame one row per stock, validation summary).
    """
    px_pit = prices_through(raw["prices"], eval_date)
    px_pit = apply_pit_adjustments(px_pit, raw["adjustments"], eval_date)
    close_df = pit_close_price(px_pit)
    # Statement slices (qi/bs/cf/sh) are built lazily in _pit_input, so a caller
    # that loaded only some raw frames (load_raw(raw_keys_for(...))) still works.
    ctx = {
        "stocks": raw["stocks"],
        "px": px_pit,
        "close": close_df,
        "eval_date": eval_date,
    }

    # Start with the universe + close + tier
    base = raw["stocks"][["sid", "cap_tier"]].merge(close_df, on="sid", how="left")
    base["snapshot_date"] = eval_date.isoformat()

    for name, spec in factors.PIT_PRODUCERS.items():
        if not spec["fn"] or not ({name, *spec.get("aliases", ())} & set(signals_to_run)):
            continue
        if any(k not in raw for k in spec.get("needs", ())):
            continue
        if any(_pit_input(ctx, raw, k, eval_date) is None or _pit_input(ctx, raw, k, eval_date).empty
               for k in spec.get("nonempty", ())):
            continue
        if not set(spec.get("after", ())).issubset(base.columns):
            continue
        ctx["base"] = base
        args = [_pit_input(ctx, raw, k, eval_date) for k in spec["inputs"]]
        base = base.merge(globals()[spec["fn"]](*args), on="sid", how="left")

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
    """Reconstruct financial_quality + financial_recovery at eval_date.

    Delegates to signals.financial_signal.compute_pit which returns both signals
    (each is a renormalised weighted average; only the asset-quality direction
    differs — low NPA good for quality, high NPA good for recovery). The legacy
    `financial_signal` column is set to financial_quality as the back-compat
    alias.

    Returns DataFrame[sid, financial_signal, financial_quality, financial_recovery]
    — NULL for non-financials and for insufficient-data stocks. Caller merges
    onto base; the upsert into daily_snapshots_pit naturally leaves NULL for
    stocks not in the (Banks ∪ NBFCs) universe.
    """
    empty = pd.DataFrame(columns=["sid", "financial_signal", "financial_quality", "financial_recovery"])
    if banking_metrics_full is None or banking_metrics_full.empty:
        return empty
    from signals.financial_signal import compute_pit
    eval_str = eval_date.isoformat() if hasattr(eval_date, "isoformat") else str(eval_date)
    out = compute_pit(eval_str, banking_metrics_full)
    if out.empty:
        return empty
    # financial_signal alias = quality variant (back-compat for older consumers
    # of daily_snapshots_pit + the backtest_pit harness's SIGNAL_COLUMN_MAP).
    out = out.copy()
    out["financial_signal"] = out["financial_quality"]
    return out[["sid", "financial_signal", "financial_quality", "financial_recovery"]]


# ── The as-of datasets the PIT features read (Dataset block, ADR 0052) ──
# One query per raw frame; load_raw(keys) loads only what the requested
# producers need (raw_keys_for), so the live screener can use this path too.
RAW_SQL = {
    "stocks": 'SELECT sid, cap_tier, sector, industry, market_cap_cr FROM stocks',
    "qi": 'SELECT sid, period, end_date, reporting, revenue, operating_profit, net_income, eps, interest, pbt, ebitda FROM quarterly_income WHERE end_date IS NOT NULL ORDER BY sid, end_date',
    "bs": 'SELECT sid, period, end_date, total_assets, total_equity, total_debt, current_assets, current_liabilities, cash_and_equivalents, receivables, retained_earnings, net_ppe, total_liabilities, shares_outstanding, long_term_debt FROM annual_balance_sheet WHERE end_date IS NOT NULL ORDER BY sid, end_date',
    "cf": 'SELECT sid, period, end_date, operating_cash_flow, capex, free_cash_flow, investing_cash_flow, financing_cash_flow, working_capital_change, depreciation, net_change_in_cash FROM annual_cash_flow WHERE end_date IS NOT NULL ORDER BY sid, end_date',
    "sh": 'SELECT sid, end_date, promoter_pct, pledge_pct, fii_pct, mf_pct, dii_pct, public_pct, insurance_pct, retail_hni_pct, other_pct FROM shareholding ORDER BY sid, end_date',
    "prices": 'SELECT sid, date, close, delivery_pct FROM stock_prices WHERE close > 0 ORDER BY sid, date',
    "adjustments": 'SELECT sid, ex_date, factor FROM corporate_adjustments ORDER BY sid, ex_date',
    "fh": "SELECT sid, metric, date, value, change FROM forecast_history WHERE metric = 'eps' AND value IS NOT NULL ORDER BY sid, metric, date",
    "acs": 'SELECT sid, snapshot_date, source, target_mean, target_median, n_analysts, recommendation_mean FROM analyst_consensus_snapshots WHERE target_mean IS NOT NULL ORDER BY sid, snapshot_date',
    "bulk": 'SELECT sid, deal_date, quantity, price, buy_sell, client_name, symbol FROM bulk_deals ORDER BY sid, deal_date',
    "short": 'SELECT sid, short_date, quantity FROM short_selling_data WHERE sid IS NOT NULL ORDER BY sid, short_date',
    "news": 'SELECT na.article_id, nas.sid,        SUBSTR(na.published_at, 1, 10) AS published_date FROM news_articles na JOIN news_article_stocks nas ON na.article_id = nas.article_id WHERE na.published_at IS NOT NULL',
    "news_text": 'SELECT na.article_id, nas.sid,        SUBSTR(na.published_at, 1, 10) AS published_date,        na.title, na.summary FROM news_articles na JOIN news_article_stocks nas ON na.article_id = nas.article_id WHERE na.published_at IS NOT NULL',
    "insider_trades": 'SELECT sid, person_category, transaction_type, shares, value_lakhs, trade_date FROM insider_trades WHERE trade_date IS NOT NULL',
    "reg_events": 'SELECT event_id, published_at FROM regulatory_events WHERE published_at IS NOT NULL',
    "reg_signals": 'SELECT event_id, sector, direction, magnitude, confidence FROM regulatory_signals WHERE is_regulatory = 1 AND direction IS NOT NULL',
    "macro_hist": 'SELECT indicator_id, date, value FROM macro_history WHERE value IS NOT NULL ORDER BY indicator_id, date',
    "macro_map": 'SELECT indicator_id, sector, direction, weight FROM macro_sector_map',
    "macro_sector": 'SELECT sector, snapshot_date, macro_score FROM macro_sector_signals_pit WHERE macro_score IS NOT NULL ORDER BY sector, snapshot_date',
    "fund_screener": "SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type = 'annual'",
    "banking_metrics": 'SELECT sid, period_end, period_type, gross_npa_pct, net_npa_pct,        interest_earned, net_interest_income, net_profit, cost_of_funds_pct FROM banking_metrics',
    "fno_pcr": 'SELECT sid, trade_date, expiry_date, underlying_price, total_call_oi, total_put_oi, pcr_oi, pcr_volume, max_pain_distance FROM fno_pcr_history WHERE sid IS NOT NULL ORDER BY sid, trade_date',
    "fno_iv": 'SELECT sid, trade_date, atm_iv, iv_skew_25d, iv_term_structure FROM fno_iv_history WHERE sid IS NOT NULL ORDER BY sid, trade_date',
    "prices_ohlc": 'SELECT sid, date, open, high, low, close, volume FROM stock_prices WHERE close > 0 ORDER BY sid, date',
    "corp_actions": 'SELECT sid, ex_date, subject FROM corporate_actions WHERE ex_date IS NOT NULL AND sid IS NOT NULL ORDER BY sid, ex_date',
    "bse_results": "SELECT sid, date(dt_tm) AS ann_date FROM bse_announcements WHERE category='Result' AND sid IS NOT NULL AND dt_tm IS NOT NULL ORDER BY sid, dt_tm",
    "bse_gov": lambda: _bse_gov_sql(),
    "nlp": "SELECT sid, doc_date, available_date, net_tone, uncertainty_density, forward_looking_intensity FROM nlp_scores WHERE doc_type = 'transcript'",
}
RAW_OPTIONAL = ['acs', 'banking_metrics', 'bse_gov', 'bse_results', 'corp_actions', 'fno_iv', 'fno_pcr', 'macro_sector', 'nlp']   # empty frame when the table is absent/unreadable



def _bse_gov_sql():
    from signals.governance_events import RESIGNATION_WEIGHTS
    subcats = ", ".join("'" + s.replace("'", "''") + "'" for s in RESIGNATION_WEIGHTS)
    return (f"SELECT sid, subcategory, date(dt_tm) AS ev_date FROM bse_announcements "
            f"WHERE sid IS NOT NULL AND dt_tm IS NOT NULL AND subcategory IN ({subcats}) "
            f"ORDER BY sid, dt_tm")


# Per-date inputs (factors.PIT_PRODUCERS "inputs") → the raw frames they slice.
_INPUT_RAW = {"px": ("prices", "adjustments"), "close": ("prices", "adjustments"),
              "fund": ("fund_screener",), "financial_sids": ("stocks",),
              "eval_date": (), "base": ()}
_BASE_RAW = ("stocks", "prices", "adjustments")


def raw_keys_for(signals):
    """The raw frames the given PIT producers (or aliases) need."""
    keys = set(_BASE_RAW)
    for name, spec in factors.PIT_PRODUCERS.items():
        if {name, *spec.get("aliases", ())} & set(signals):
            for k in (*spec.get("inputs", ()), *spec.get("needs", ()), *spec.get("nonempty", ())):
                keys.update(_INPUT_RAW.get(k, (k,)))
    return {k for k in keys if k in RAW_SQL}


def load_raw(keys=None):
    """Load raw history once (all frames, or only `keys`). Avoids re-querying per eval_date."""
    keys = list(RAW_SQL) if keys is None else [k for k in RAW_SQL if k in set(keys)]
    print("Loading raw data...")
    raw = {}
    for k in keys:
        sql = RAW_SQL[k]() if callable(RAW_SQL[k]) else RAW_SQL[k]
        if k in RAW_OPTIONAL:
            try:
                raw[k] = read_sql(sql)
            except Exception:
                raw[k] = pd.DataFrame()
        else:
            raw[k] = read_sql(sql)
    print("  " + " ".join(f"{k}={len(v)}" for k, v in raw.items()))
    return raw



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
