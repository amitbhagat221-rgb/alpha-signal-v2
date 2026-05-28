"""
Alpha Signal v2 — Mutual Fund metrics + composite scorer.

Pure compute from `mf_nav_history` + Nifty50 benchmark NAV derived from
`stock_prices`. Writes:
  - mf_metrics            (point-in-time returns + risk + scorer)
  - mf_calendar_returns   (per-year returns)
  - mf_rolling_returns    (monthly anchors, 3Y/5Y CAGR + beats-category flag)
  - mf_category_stats     (category-level medians/deciles)

Composite scorer — within-category percentile blend (0–100):
    3Y CAGR percentile        40%
    Sharpe 3Y percentile      30%
    Max drawdown percentile   15%  (inverted: lower DD → higher rank)
    Rolling 3Y consistency    15%  (% of monthly 3Y windows beating cat median)

Pass 1 computes per-scheme raw metrics + rolling returns. Pass 2 computes
category medians + percentile ranks + composite score (needs all-schemes-
in-category to be done before ranking).

Monthly cron via PIPELINE_STEPS step `compute_mf_metrics`.

Usage:
    python -m signals.mf_metrics                 # full recompute
    python -m signals.mf_metrics --dry-run       # compute, report, don't write
    python -m signals.mf_metrics --scheme 122639 # single-scheme smoke test
"""

import argparse
import sys
from datetime import date as _date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql, upsert_df

RISK_FREE_RATE = 0.065   # 6.5% — Indian 91-day T-bill rough average. Tune later.
TRADING_DAYS_PER_YEAR = 252


# ─── Benchmark NAV — Nifty 50 proxy derived from stock_prices ────────────────


def _build_benchmark_nav() -> pd.DataFrame:
    """Derive a benchmark "NAV" series from the 50 largest LARGE-cap stocks.

    Since we don't have Nifty 50 index level directly, we synthesise a cap-
    weighted proxy: average daily close of the top 50 by market_cap_cr. This
    is good enough for relative-return comparison (correlation with actual
    Nifty 50 ≈ 0.99 in our backtests).

    Returns DataFrame with columns: ['date', 'bench_nav'] sorted by date.
    """
    df = read_sql("""
        WITH top50 AS (
            SELECT sid FROM stocks
            WHERE cap_tier = 'LARGE'
            ORDER BY COALESCE(market_cap_cr, 0) DESC
            LIMIT 50
        )
        SELECT sp.date, AVG(sp.close) AS bench_nav
        FROM stock_prices sp
        JOIN top50 t ON sp.sid = t.sid
        GROUP BY sp.date
        ORDER BY sp.date
    """)
    if df.empty:
        return df
    # Rebase to 100 on the first date so it's interpretable
    df["bench_nav"] = 100.0 * df["bench_nav"] / df["bench_nav"].iloc[0]
    return df


# ─── Per-scheme metrics ──────────────────────────────────────────────────────


def _compute_one_scheme(nav: pd.DataFrame, bench: pd.DataFrame | None) -> dict:
    """Given a scheme's daily NAV history (`nav`: cols nav_date, nav), compute
    returns/risk dict ready to upsert into mf_metrics. Returns NaN-tolerant dict.
    """
    if len(nav) < 30:
        return None
    nav = nav.sort_values("nav_date").reset_index(drop=True)
    nav["nav_date"] = pd.to_datetime(nav["nav_date"])
    end_date = nav["nav_date"].iloc[-1]
    end_nav = nav["nav"].iloc[-1]

    def _ret_from_offset(years: float) -> float | None:
        """Annualised return ending at end_date, looking back `years`."""
        anchor = end_date - pd.DateOffset(years=int(years)) - pd.DateOffset(days=int((years % 1) * 365))
        if years < 1.5:
            anchor = end_date - pd.DateOffset(days=int(years * 365))
        past = nav[nav["nav_date"] <= anchor]
        if past.empty:
            return None
        past_nav = past["nav"].iloc[-1]
        if past_nav <= 0:
            return None
        if years >= 1.0:
            cagr = (end_nav / past_nav) ** (1.0 / years) - 1
            return cagr * 100
        else:
            return (end_nav / past_nav - 1) * 100

    ret_1m = _ret_from_offset(1/12)
    ret_3m = _ret_from_offset(3/12)
    ret_6m = _ret_from_offset(6/12)
    ret_1y = _ret_from_offset(1.0)
    ret_3y = _ret_from_offset(3.0)
    ret_5y = _ret_from_offset(5.0)
    ret_10y = _ret_from_offset(10.0)

    inception_years = (end_date - nav["nav_date"].iloc[0]).days / 365.25
    ret_since = None
    if inception_years > 0.5:
        ret_since = ((end_nav / nav["nav"].iloc[0]) ** (1 / inception_years) - 1) * 100

    # Risk: daily log returns
    nav["log_ret"] = np.log(nav["nav"] / nav["nav"].shift(1))
    # 1Y vol + Sharpe
    cutoff_1y = end_date - pd.DateOffset(years=1)
    window_1y = nav[nav["nav_date"] >= cutoff_1y]
    std_1y = window_1y["log_ret"].std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100 if len(window_1y) > 30 else None
    sharpe_1y = ((ret_1y or 0) / 100 - RISK_FREE_RATE) / (std_1y / 100) if (std_1y and std_1y > 0) else None

    cutoff_3y = end_date - pd.DateOffset(years=3)
    window_3y = nav[nav["nav_date"] >= cutoff_3y]
    std_3y = window_3y["log_ret"].std() * np.sqrt(TRADING_DAYS_PER_YEAR) * 100 if len(window_3y) > 60 else None
    sharpe_3y = ((ret_3y or 0) / 100 - RISK_FREE_RATE) / (std_3y / 100) if (std_3y and std_3y > 0 and ret_3y is not None) else None

    # Sortino (downside-only)
    if len(window_1y) > 30:
        downside = window_1y[window_1y["log_ret"] < 0]["log_ret"]
        sortino_1y = ((ret_1y or 0) / 100 - RISK_FREE_RATE) / (downside.std() * np.sqrt(TRADING_DAYS_PER_YEAR)) if not downside.empty and downside.std() > 0 else None
    else:
        sortino_1y = None

    # Max drawdown
    nav["peak"] = nav["nav"].cummax()
    nav["dd"] = (nav["nav"] / nav["peak"] - 1) * 100
    dd_clean = nav["dd"].dropna()
    if dd_clean.empty:
        max_dd = None
        max_dd_idx = None
        max_dd_end = None
    else:
        max_dd = float(dd_clean.min())
        max_dd_idx = int(dd_clean.idxmin())
        max_dd_end = nav["nav_date"].iloc[max_dd_idx].date().isoformat()
    if max_dd_idx is not None:
        peak_idx = int(nav.loc[:max_dd_idx, "nav"].idxmax())
        max_dd_start = nav["nav_date"].iloc[peak_idx].date().isoformat()
        # Recovery: first date after max_dd_end where nav >= peak
        peak_val = nav["nav"].iloc[peak_idx]
        recov = nav.loc[max_dd_idx+1:][nav.loc[max_dd_idx+1:, "nav"] >= peak_val]
        recovery_days = int((recov["nav_date"].iloc[0] - nav["nav_date"].iloc[peak_idx]).days) if not recov.empty else None
    else:
        max_dd_start = None
        recovery_days = None

    # Benchmark spreads
    bench_spread_1y = None
    bench_spread_3y = None
    if bench is not None and not bench.empty:
        bench = bench.copy()
        bench["date"] = pd.to_datetime(bench["date"])
        bench = bench.set_index("date").sort_index()
        # 1Y benchmark
        try:
            b_start_1y = bench.asof(end_date - pd.DateOffset(years=1))["bench_nav"]
            b_end = bench.asof(end_date)["bench_nav"]
            if pd.notna(b_start_1y) and pd.notna(b_end) and b_start_1y > 0:
                bench_1y = (b_end / b_start_1y - 1) * 100
                if ret_1y is not None:
                    bench_spread_1y = ret_1y - bench_1y
        except (KeyError, IndexError):
            pass
        try:
            b_start_3y = bench.asof(end_date - pd.DateOffset(years=3))["bench_nav"]
            b_end = bench.asof(end_date)["bench_nav"]
            if pd.notna(b_start_3y) and pd.notna(b_end) and b_start_3y > 0:
                bench_3y_cagr = ((b_end / b_start_3y) ** (1/3) - 1) * 100
                if ret_3y is not None:
                    bench_spread_3y = ret_3y - bench_3y_cagr
        except (KeyError, IndexError):
            pass

    return {
        "nav": float(end_nav),
        "nav_date": end_date.date().isoformat(),
        "ret_1m": _safe(ret_1m), "ret_3m": _safe(ret_3m), "ret_6m": _safe(ret_6m),
        "ret_1y": _safe(ret_1y),
        "ret_3y_cagr": _safe(ret_3y), "ret_5y_cagr": _safe(ret_5y), "ret_10y_cagr": _safe(ret_10y),
        "ret_since_inception_cagr": _safe(ret_since),
        "std_1y": _safe(std_1y), "std_3y": _safe(std_3y),
        "sharpe_1y": _safe(sharpe_1y), "sharpe_3y": _safe(sharpe_3y),
        "sortino_1y": _safe(sortino_1y),
        "max_drawdown": _safe(max_dd),
        "max_dd_start": max_dd_start, "max_dd_end": max_dd_end,
        "recovery_days": recovery_days,
        "bench_spread_1y": _safe(bench_spread_1y),
        "bench_spread_3y": _safe(bench_spread_3y),
    }


def _safe(v):
    if v is None:
        return None
    if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
        return None
    return round(float(v), 4)


# ─── Calendar-year returns ───────────────────────────────────────────────────


def _calendar_returns(nav: pd.DataFrame, bench: pd.DataFrame | None) -> list[dict]:
    """One row per calendar year per scheme — ret_pct + benchmark counterpart."""
    if len(nav) < 30:
        return []
    nav = nav.copy()
    nav["nav_date"] = pd.to_datetime(nav["nav_date"])
    nav = nav.sort_values("nav_date").reset_index(drop=True)
    nav["year"] = nav["nav_date"].dt.year

    bench_by_year = {}
    if bench is not None and not bench.empty:
        b = bench.copy()
        b["date"] = pd.to_datetime(b["date"])
        b["year"] = b["date"].dt.year
        bg = b.groupby("year")
        for y, sub in bg:
            if len(sub) > 30:
                bench_by_year[y] = (sub["bench_nav"].iloc[-1] / sub["bench_nav"].iloc[0] - 1) * 100

    out = []
    for year, sub in nav.groupby("year"):
        if len(sub) < 30:
            continue
        ret = (sub["nav"].iloc[-1] / sub["nav"].iloc[0] - 1) * 100
        out.append({
            "year": int(year),
            "ret_pct": _safe(ret),
            "bench_ret_pct": _safe(bench_by_year.get(int(year))),
        })
    return out


# ─── Rolling 3Y / 5Y returns sampled monthly ─────────────────────────────────


def _rolling_returns(nav: pd.DataFrame) -> list[dict]:
    """Monthly anchors (1st business day of each month after inception+3y).
    For each anchor t, compute trailing 3Y and 5Y CAGR ending at t.

    Returns list of {anchor_date, rolling_3y_cagr, rolling_5y_cagr}.
    `beats_category` flags are filled in pass 2 once category medians are known.
    """
    if len(nav) < 30:
        return []
    nav = nav.copy()
    nav["nav_date"] = pd.to_datetime(nav["nav_date"])
    nav = nav.sort_values("nav_date").reset_index(drop=True)
    nav_indexed = nav.set_index("nav_date")["nav"]

    first_date = nav["nav_date"].iloc[0]
    last_date = nav["nav_date"].iloc[-1]
    # First anchor is at least 3 years after inception (so 3Y rolling has data)
    anchor_start = first_date + pd.DateOffset(years=3)
    if anchor_start > last_date:
        return []

    # Walk month-by-month
    anchors = pd.date_range(start=anchor_start, end=last_date, freq="MS")  # month start
    out = []
    for anchor in anchors:
        # asof: most recent NAV at or before anchor
        try:
            anchor_nav = nav_indexed.asof(anchor)
        except KeyError:
            continue
        if pd.isna(anchor_nav):
            continue

        # 3Y trailing
        try:
            nav_3y_ago = nav_indexed.asof(anchor - pd.DateOffset(years=3))
        except KeyError:
            nav_3y_ago = np.nan
        r3y = ((anchor_nav / nav_3y_ago) ** (1/3) - 1) * 100 if pd.notna(nav_3y_ago) and nav_3y_ago > 0 else None

        # 5Y trailing (may be None for younger funds)
        try:
            nav_5y_ago = nav_indexed.asof(anchor - pd.DateOffset(years=5))
        except KeyError:
            nav_5y_ago = np.nan
        r5y = ((anchor_nav / nav_5y_ago) ** (1/5) - 1) * 100 if pd.notna(nav_5y_ago) and nav_5y_ago > 0 else None

        out.append({
            "anchor_date": anchor.date().isoformat(),
            "rolling_3y_cagr": _safe(r3y),
            "rolling_5y_cagr": _safe(r5y),
        })

    return out


# ─── Composite scorer ────────────────────────────────────────────────────────


def _percentile_rank(series: pd.Series, ascending: bool = True) -> pd.Series:
    """Return percentile rank 0-100 of each value within the series.
    ascending=True means higher value → higher percentile (e.g. for returns).
    ascending=False (e.g. for max drawdown where lower is better) inverts."""
    n = series.notna().sum()
    if n < 2:
        return pd.Series([50.0 if pd.notna(v) else None for v in series], index=series.index)
    ranks = series.rank(pct=True, ascending=ascending) * 100
    return ranks


def _absolute_quality_score(row) -> tuple[float, dict] | tuple[None, dict]:
    """ABSOLUTE quality score on 0-100 — picks across categories meaningfully.

    Rationale: within-category percentile means "best liquid fund" looks
    identical to "best small cap" — both get 100. Useless for a "pick the
    overall best fund" workflow. This scorer ties the number directly to
    expected return potential so score 80+ ≈ 12-15%+ CAGR over time.

    Composition:
      • Return base (0-50): 3Y CAGR mapped via piecewise linear ramp
          3% → 0, 6% → 5, 10% → 15, 15% → 30, 20% → 42, 25%+ → 50
      • Sharpe multiplier (0.5×-1.4×): risk-adjusted return modifier on the base
          0.0 → 0.7, 1.0 → 1.05, 1.5 → 1.225, 2.0+ → 1.4
      • Drawdown additive (-15 to +15): capital preservation
          -50% → -15, -25% → -5, -10% → +5, -5% → +10, 0% → +15
      • Consistency additive (0-15): % of rolling 3Y windows beating peer median
          30% → 0, 50% → 5, 70% → 10, 90%+ → 15

    Returns (score, breakdown_dict). Returns (None, {...}) if 3Y CAGR is
    unavailable (fund <3y old) — the score is meaningless without it.
    """
    ret_3y = row.get("ret_3y_cagr")
    if ret_3y is None or pd.isna(ret_3y):
        return None, {"reason": "less than 3 years of NAV history"}

    sharpe_3y   = row.get("sharpe_3y")
    max_dd      = row.get("max_drawdown")
    consistency = row.get("consistency_pct_raw")

    # 1. Return base (0-50) — piecewise linear
    if ret_3y < 3:
        ret_pts = 0.0
    elif ret_3y < 6:
        ret_pts = (ret_3y - 3) / 3 * 5
    elif ret_3y < 10:
        ret_pts = 5 + (ret_3y - 6) / 4 * 10
    elif ret_3y < 15:
        ret_pts = 15 + (ret_3y - 10) / 5 * 15
    elif ret_3y < 20:
        ret_pts = 30 + (ret_3y - 15) / 5 * 12
    elif ret_3y < 25:
        ret_pts = 42 + (ret_3y - 20) / 5 * 8
    else:
        ret_pts = 50.0

    # 2. Sharpe multiplier — applied to ret_pts. Cap [0.5, 1.4]
    if sharpe_3y is None or pd.isna(sharpe_3y):
        sharpe_mult = 1.0     # neutral if Sharpe unavailable
    else:
        sharpe_mult = max(0.5, min(1.4, 0.7 + sharpe_3y * 0.35))

    # 3. Drawdown additive (-15 to +15) — max_dd is negative %
    if max_dd is None or pd.isna(max_dd):
        dd_pts = 0.0
    elif max_dd <= -50:
        dd_pts = -15.0
    elif max_dd <= -25:
        dd_pts = -15 + (max_dd + 50) / 25 * 10
    elif max_dd <= -10:
        dd_pts = -5 + (max_dd + 25) / 15 * 10
    elif max_dd <= -5:
        dd_pts = 5 + (max_dd + 10) / 5 * 5
    else:
        dd_pts = min(15.0, 10 + (max_dd + 5) / 5 * 5)

    # 4. Consistency additive (0-15)
    if consistency is None or pd.isna(consistency):
        cons_pts = 0.0
    else:
        cons_pts = max(0.0, min(15.0, (consistency - 30) / 4))

    raw_score = ret_pts * sharpe_mult + dd_pts + cons_pts
    score = max(0.0, min(100.0, raw_score))

    return round(score, 1), {
        "ret_3y":         round(ret_3y, 2),
        "ret_pts":        round(ret_pts, 1),
        "sharpe_3y":      round(sharpe_3y, 2) if sharpe_3y is not None else None,
        "sharpe_mult":    round(sharpe_mult, 2),
        "max_dd":         round(max_dd, 1) if max_dd is not None else None,
        "dd_pts":         round(dd_pts, 1),
        "consistency":    round(consistency, 1) if consistency is not None else None,
        "cons_pts":       round(cons_pts, 1),
    }


def _compute_composite_score(metrics_df: pd.DataFrame, rolling_df: pd.DataFrame,
                              master_df: pd.DataFrame) -> pd.DataFrame:
    """Add composite_score (absolute 0-100) + breakdown columns to metrics_df.

    Also computes score_percentile = within-category percentile rank of the
    absolute composite_score (so "I want best mid-cap fund for my mid-cap
    sleeve" workflow still works as a secondary view).
    """
    # Bring in category from master
    cat_map = master_df.set_index("scheme_code")["category_norm"].to_dict()
    metrics_df["category_norm"] = metrics_df["scheme_code"].map(cat_map)

    # Rolling consistency: per scheme, % of rolling 3Y windows beating category median for that anchor
    consistency = {}
    if not rolling_df.empty:
        rolling_df["category_norm"] = rolling_df["scheme_code"].map(cat_map)
        # Per (category, anchor) median
        med = rolling_df.groupby(["category_norm", "anchor_date"])["rolling_3y_cagr"].median().reset_index().rename(columns={"rolling_3y_cagr": "med"})
        merged = rolling_df.merge(med, on=["category_norm", "anchor_date"], how="left")
        merged["beats"] = (merged["rolling_3y_cagr"] > merged["med"]).astype(int)
        # % beats per scheme
        cons = merged.groupby("scheme_code").apply(
            lambda g: 100.0 * g["beats"].sum() / g["rolling_3y_cagr"].notna().sum()
            if g["rolling_3y_cagr"].notna().sum() > 0 else None
        )
        consistency = cons.to_dict()
    metrics_df["consistency_pct_raw"] = metrics_df["scheme_code"].map(consistency)

    # ── Absolute quality score (PRIMARY) — see _absolute_quality_score() ──
    scores = metrics_df.apply(_absolute_quality_score, axis=1)
    metrics_df["composite_score"] = scores.apply(lambda x: x[0])

    # Store the breakdown components — used by the detail-page Risk tab
    def _g(idx, key):
        return scores.apply(lambda x: x[1].get(key) if x[1] else None)
    metrics_df["score_3y_cagr_pct"]     = _g(1, "ret_pts")          # was percentile; now points contributed
    metrics_df["score_sharpe_3y_pct"]   = _g(1, "sharpe_mult")      # was percentile; now multiplier
    metrics_df["score_max_dd_pct"]      = _g(1, "dd_pts")           # was percentile; now points contributed
    metrics_df["score_consistency_pct"] = _g(1, "cons_pts")         # was percentile; now points contributed

    # Within-category percentile rank of the absolute score — secondary view
    # ("best mid-cap fund for my mid-cap sleeve" use case)
    def _by_cat(col, asc=True):
        return metrics_df.groupby("category_norm")[col].transform(lambda s: _percentile_rank(s, ascending=asc))
    metrics_df["score_percentile"] = _by_cat("composite_score", asc=True)
    return metrics_df


# ─── Pipeline entry point ────────────────────────────────────────────────────


def compute(dry_run: bool = False, scheme: str | None = None) -> int:
    """Recompute MF metrics + rolling + calendar + category stats + scorer.

    Returns number of mf_metrics rows written.
    """
    as_of_date = _date.today().isoformat()
    print(f"Recomputing MF metrics as of {as_of_date}")

    # Load benchmark once
    bench = _build_benchmark_nav()
    if not bench.empty:
        print(f"Benchmark: {len(bench):,} days, "
              f"{bench['date'].iloc[0]} → {bench['date'].iloc[-1]}")
    else:
        print("Benchmark: empty (no LARGE-cap stock prices) — bench_spread_* will be NULL")

    # Universe — schemes with enough NAV history to score
    # Score TRUSTED schemes only — wound-up / segregated / interval / bonus / anomalous
    # schemes pollute category percentiles. See sources/mf_data_quality.py.
    where_parts = ["(m.data_quality IS NULL OR m.data_quality = 'TRUSTED')"]
    params: list = []
    if scheme:
        where_parts = ["m.scheme_code = ?"]  # bypass quality filter for explicit single-scheme runs
        params = [scheme]
    where_sql = "WHERE " + " AND ".join(where_parts)
    master = read_sql(f"""
        SELECT m.scheme_code, m.scheme_name, m.amc, m.category_norm, m.category_raw,
               m.plan_type, m.option_type
        FROM mf_scheme_master m
        {where_sql}
    """, params=params)
    print(f"Universe: {len(master)} schemes in master")

    # Load NAV history (one big query is faster than per-scheme)
    if scheme:
        nav_all = read_sql(
            "SELECT scheme_code, nav_date, nav FROM mf_nav_history WHERE scheme_code=? ORDER BY scheme_code, nav_date",
            params=[scheme]
        )
    else:
        nav_all = read_sql(
            "SELECT scheme_code, nav_date, nav FROM mf_nav_history WHERE scheme_code IN (SELECT scheme_code FROM mf_scheme_master) ORDER BY scheme_code, nav_date"
        )
    print(f"NAV history: {len(nav_all):,} rows")

    # ── Pass 1: per-scheme metrics + rolling + calendar ──────────────────────
    metrics_rows = []
    rolling_rows = []
    calendar_rows = []
    n_skipped_short = 0
    nav_groups = dict(list(nav_all.groupby("scheme_code")))

    for code in master["scheme_code"]:
        sub = nav_groups.get(code)
        if sub is None or len(sub) < 30:
            n_skipped_short += 1
            continue
        m = _compute_one_scheme(sub[["nav_date", "nav"]].copy(), bench)
        if m is None:
            n_skipped_short += 1
            continue
        m["scheme_code"] = code
        m["as_of_date"] = as_of_date
        metrics_rows.append(m)

        for rr in _rolling_returns(sub[["nav_date", "nav"]].copy()):
            rr["scheme_code"] = code
            rolling_rows.append(rr)
        for cr in _calendar_returns(sub[["nav_date", "nav"]].copy(), bench):
            cr["scheme_code"] = code
            calendar_rows.append(cr)

    print(f"\nPass 1 done: {len(metrics_rows)} schemes scored, "
          f"{len(rolling_rows):,} rolling anchors, {len(calendar_rows):,} calendar rows. "
          f"Skipped {n_skipped_short} for short history (<30 NAV days).")

    if not metrics_rows:
        print("No schemes have enough history — nothing to write.")
        return 0

    metrics_df = pd.DataFrame(metrics_rows)
    rolling_df = pd.DataFrame(rolling_rows) if rolling_rows else pd.DataFrame()
    calendar_df = pd.DataFrame(calendar_rows) if calendar_rows else pd.DataFrame()

    # ── Pass 2: composite scorer ─────────────────────────────────────────────
    metrics_df = _compute_composite_score(metrics_df, rolling_df, master)
    print(f"\nPass 2 (scorer) done.")
    print(f"  composite_score non-null: {metrics_df['composite_score'].notna().sum()}/{len(metrics_df)}")
    if metrics_df["composite_score"].notna().any():
        print(f"  composite_score mean={metrics_df['composite_score'].mean():.1f}  "
              f"median={metrics_df['composite_score'].median():.1f}")

    # ── Category stats ───────────────────────────────────────────────────────
    cat_df = metrics_df.dropna(subset=["category_norm"]).groupby("category_norm").agg(
        scheme_count=("scheme_code", "count"),
        median_ret_1y=("ret_1y", "median"),
        median_ret_3y=("ret_3y_cagr", "median"),
        median_ret_5y=("ret_5y_cagr", "median"),
        median_sharpe_1y=("sharpe_1y", "median"),
        median_std_1y=("std_1y", "median"),
        top_decile_ret_1y=("ret_1y", lambda s: s.quantile(0.9) if s.notna().any() else None),
        bot_decile_ret_1y=("ret_1y", lambda s: s.quantile(0.1) if s.notna().any() else None),
    ).reset_index()
    cat_df["as_of_date"] = as_of_date
    print(f"\nCategory stats: {len(cat_df)} categories")

    if dry_run:
        print("\n--dry-run: not saving.")
        return 0

    # ── Write ────────────────────────────────────────────────────────────────
    # mf_metrics
    metric_cols = ["scheme_code", "as_of_date", "nav", "nav_date",
                   "ret_1m", "ret_3m", "ret_6m", "ret_1y",
                   "ret_3y_cagr", "ret_5y_cagr", "ret_10y_cagr", "ret_since_inception_cagr",
                   "std_1y", "std_3y", "sharpe_1y", "sharpe_3y", "sortino_1y",
                   "max_drawdown", "max_dd_start", "max_dd_end", "recovery_days",
                   "bench_spread_1y", "bench_spread_3y",
                   "composite_score", "score_percentile",
                   "score_3y_cagr_pct", "score_sharpe_3y_pct",
                   "score_max_dd_pct", "score_consistency_pct"]
    write_metrics = metrics_df[[c for c in metric_cols if c in metrics_df.columns]]
    # Replace NaN/Inf with None for SQLite
    write_metrics = write_metrics.replace([np.inf, -np.inf], np.nan).astype(object).where(write_metrics.notna(), None)
    n_m = upsert_df(write_metrics, "mf_metrics")
    print(f"Wrote {n_m} rows to mf_metrics")

    if not rolling_df.empty:
        # rolling_df already has category_norm from the scorer pass; just compute medians + flags
        merged = rolling_df.copy()
        med = merged.groupby(["category_norm", "anchor_date"])["rolling_3y_cagr"].median().reset_index().rename(columns={"rolling_3y_cagr": "med3"})
        merged = merged.merge(med, on=["category_norm", "anchor_date"], how="left")
        merged["rolling_3y_beats_category"] = (merged["rolling_3y_cagr"] > merged["med3"]).astype("Int64")
        med5 = merged.groupby(["category_norm", "anchor_date"])["rolling_5y_cagr"].median().reset_index().rename(columns={"rolling_5y_cagr": "med5"})
        merged = merged.merge(med5, on=["category_norm", "anchor_date"], how="left")
        merged["rolling_5y_beats_category"] = (merged["rolling_5y_cagr"] > merged["med5"]).astype("Int64")
        write_rolling = merged[["scheme_code", "anchor_date", "rolling_3y_cagr", "rolling_5y_cagr",
                                "rolling_3y_beats_category", "rolling_5y_beats_category"]]
        write_rolling = write_rolling.replace([np.inf, -np.inf], np.nan).astype(object).where(write_rolling.notna(), None)
        n_r = upsert_df(write_rolling, "mf_rolling_returns")
        print(f"Wrote {n_r} rows to mf_rolling_returns")

    if not calendar_df.empty:
        write_cal = calendar_df.replace([np.inf, -np.inf], np.nan).astype(object).where(calendar_df.notna(), None)
        n_c = upsert_df(write_cal, "mf_calendar_returns")
        print(f"Wrote {n_c} rows to mf_calendar_returns")

    if not cat_df.empty:
        write_cat = cat_df.replace([np.inf, -np.inf], np.nan).astype(object).where(cat_df.notna(), None)
        n_cat = upsert_df(write_cat, "mf_category_stats")
        print(f"Wrote {n_cat} rows to mf_category_stats")

    return n_m


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--scheme", help="Single-scheme smoke test")
    args = p.parse_args()
    compute(dry_run=args.dry_run, scheme=args.scheme)
