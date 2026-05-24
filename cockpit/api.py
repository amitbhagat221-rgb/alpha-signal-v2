"""
Alpha Signal Cockpit — Data Layer

All data queries live here. Called by app.py routes.
Imports db.read_sql directly — no ORM, no new abstractions.
"""

import functools
import glob
import json
import sys
import time as _time
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db


# In-process TTL cache for read-only functions.
# Pages call these on every render, but the underlying SQLite tables only
# change when the daily cron pipeline runs — so a 60s TTL is invisible to
# users and shaves 1-2 seconds off /system, /command, /model, /actions, /portfolio.
# Args are tuple-keyed; pass `_force=True` to bypass.
def _ttl_cache(ttl_seconds, max_entries=512):
    def decorator(fn):
        cache: dict = {}

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            force = kwargs.pop("_force", False)
            key = (args, tuple(sorted(kwargs.items())))
            now = _time.time()
            entry = cache.get(key)
            if not force and entry is not None and (now - entry[1]) < ttl_seconds:
                return entry[0]
            value = fn(*args, **kwargs)
            cache[key] = (value, now)
            # Bound memory: evict oldest entries if over max_entries.
            if len(cache) > max_entries:
                oldest = sorted(cache.items(), key=lambda kv: kv[1][1])[: len(cache) - max_entries]
                for k, _ in oldest:
                    cache.pop(k, None)
            return value

        wrapper.cache_clear = lambda: cache.clear()
        return wrapper

    return decorator


# ═══════════════════════════════════════════════════
# A1-A12: NEW DATA FUNCTIONS
# ═══════════════════════════════════════════════════

@_ttl_cache(60)
def get_stock_price_metrics(sid):
    """A1: Returns, RSI-14, 52W high/low from stock_prices."""
    df = read_sql(
        "SELECT date, close FROM stock_prices WHERE sid = ? AND close > 0 ORDER BY date DESC LIMIT 260",
        params=[sid],
    )
    if df.empty or len(df) < 5:
        return {}

    closes = df.sort_values("date")["close"]
    latest = closes.iloc[-1]
    result = {"close_price": round(latest, 2), "price_date": df.sort_values("date")["date"].iloc[-1]}

    # Returns
    for label, offset in [("1m", 22), ("3m", 65), ("6m", 130), ("1y", 252)]:
        if len(closes) > offset:
            old = closes.iloc[-(offset + 1)]
            if old > 0:
                result[f"return_{label}"] = round((latest / old - 1) * 100, 1)

    # 52W high/low
    result["high_52w"] = round(closes.max(), 2)
    result["low_52w"] = round(closes.min(), 2)
    if result["high_52w"] > 0:
        result["pct_from_52w_high"] = round((latest / result["high_52w"] - 1) * 100, 1)

    # RSI-14
    if len(closes) >= 15:
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss
        rsi_series = 100 - (100 / (1 + rs))
        result["rsi_14"] = round(rsi_series.iloc[-1], 1)

    return result


@_ttl_cache(60)
def get_analyst_consensus(sid):
    """A2: Price target, analyst count, buy%, growth from analyst_consensus.

    Includes Tier-1 extended yfinance fields (added 2026-05-23): median PT,
    high/low range, rating mix counts, qualitative recommendation key.
    """
    row = read_sql(
        "SELECT price_target, price_target_median, price_target_high, price_target_low, "
        "total_analysts, buy_pct, eps_growth_pct, revenue_growth_pct, forward_eps, "
        "recommendation_key, recommendation_mean, "
        "n_strong_buy, n_buy, n_hold, n_sell, n_strong_sell, "
        "pt_source, next_earnings_date, rating_mix_history, "
        "price_target_prev, price_target_changed_at, fetched_at "
        "FROM analyst_consensus WHERE sid = ?",
        params=[sid],
    )
    if row.empty:
        return {}
    r = row.iloc[0].to_dict()

    # PT-freshness derived fields (added 2026-05-23)
    import json as _json
    from datetime import date as _date_, datetime as _dt_
    today = _date_.today()

    # 1. Next earnings days delta
    if r.get("next_earnings_date"):
        try:
            ne = _dt_.fromisoformat(r["next_earnings_date"]).date()
            r["days_to_earnings"] = (ne - today).days   # positive=future, negative=past
        except Exception:
            pass

    # 2. PT change recency
    if r.get("price_target_changed_at") and r.get("price_target_prev"):
        try:
            chg_dt = _dt_.fromisoformat(r["price_target_changed_at"][:10]).date()
            r["days_since_pt_change"] = (today - chg_dt).days
            prev_pt = float(r["price_target_prev"])
            if prev_pt > 0 and r.get("price_target"):
                r["pt_change_pct"] = round((r["price_target"] / prev_pt - 1) * 100, 1)
        except Exception:
            pass

    # 3. Rating-mix trend (now vs ~3mo ago)
    if r.get("rating_mix_history"):
        try:
            hist = _json.loads(r["rating_mix_history"])
            if len(hist) >= 2:
                # First entry is oldest, last is newest
                def _bullish_pct(row):
                    _, sb, b, h, s, ss = row
                    tot = sb + b + h + s + ss
                    return ((sb + b) / tot * 100) if tot else None
                pct_old = _bullish_pct(hist[0])
                pct_new = _bullish_pct(hist[-1])
                if pct_old is not None and pct_new is not None:
                    r["bullish_pct_now"]    = round(pct_new, 0)
                    r["bullish_pct_old"]    = round(pct_old, 0)
                    r["bullish_pct_delta"]  = round(pct_new - pct_old, 0)
                    r["bullish_old_period"] = hist[0][0]   # e.g. '-3m'
            r["rating_mix_periods"] = hist     # parsed for template
        except Exception:
            pass
    # Compute upside vs current price (use median when available — robust to outliers)
    price = read_sql(
        "SELECT close FROM stock_prices WHERE sid = ? ORDER BY date DESC LIMIT 1",
        params=[sid],
    )
    if not price.empty and price.iloc[0]["close"]:
        cmp = price.iloc[0]["close"]
        if cmp > 0:
            r["current_price"] = round(cmp, 2)
            if r.get("price_target"):
                r["pt_upside_pct"] = round((r["price_target"] / cmp - 1) * 100, 1)
            if r.get("price_target_median"):
                r["pt_upside_median_pct"] = round((r["price_target_median"] / cmp - 1) * 100, 1)
            if r.get("price_target_high"):
                r["pt_upside_high_pct"] = round((r["price_target_high"] / cmp - 1) * 100, 1)
            if r.get("price_target_low"):
                r["pt_upside_low_pct"] = round((r["price_target_low"] / cmp - 1) * 100, 1)
    return r


def get_shareholding_history(sid):
    """A3: Last 6 quarters of ownership breakdown with QoQ changes."""
    df = read_sql(
        "SELECT end_date, promoter_pct, fii_pct, mf_pct, dii_pct, "
        "public_pct, pledge_pct, insurance_pct, retail_hni_pct "
        "FROM shareholding WHERE sid = ? AND end_date > '1900-01-01' "
        "ORDER BY end_date DESC LIMIT 6",
        params=[sid],
    )
    if df.empty:
        return []

    # Compute QoQ changes (older quarter is in the next row since we're DESC)
    quarters = df.to_dict("records")
    for i, q in enumerate(quarters):
        if i + 1 < len(quarters):
            prior = quarters[i + 1]
            for col in ["promoter_pct", "fii_pct", "mf_pct", "dii_pct"]:
                if q.get(col) is not None and prior.get(col) is not None:
                    q[f"{col}_qoq"] = round(q[col] - prior[col], 2)
    return quarters


@_ttl_cache(60)
def get_insider_activity(sid):
    """A4: Recent trades + signal summary."""
    trades = read_sql(
        "SELECT person_category, transaction_type, shares, value_lakhs, trade_date "
        "FROM insider_trades WHERE sid = ? AND trade_date >= date('now', '-180 days') "
        "ORDER BY trade_date DESC LIMIT 10",
        params=[sid],
    )
    signal = read_sql(
        "SELECT signal_type, strength, score_impact, description "
        "FROM insider_signals WHERE sid = ? ORDER BY snapshot_date DESC LIMIT 1",
        params=[sid],
    )
    return {
        "trades": trades.to_dict("records") if not trades.empty else [],
        "signal": signal.iloc[0].to_dict() if not signal.empty else {},
    }


def get_stock_news(sid):
    """A5: Latest 5 news articles for a stock."""
    df = read_sql(
        "SELECT na.title, na.source, na.published_at, na.url "
        "FROM news_articles na "
        "JOIN news_article_stocks nas ON na.article_id = nas.article_id "
        "WHERE nas.sid = ? ORDER BY na.published_at DESC LIMIT 5",
        params=[sid],
    )
    return df.to_dict("records") if not df.empty else []


def get_bulk_deals(sid):
    """A6: Recent bulk/block deals for a stock."""
    df = read_sql(
        "SELECT client_name, buy_sell, quantity, price, deal_date, deal_type "
        "FROM bulk_deals WHERE sid = ? ORDER BY deal_date DESC LIMIT 10",
        params=[sid],
    )
    return df.to_dict("records") if not df.empty else []


def get_regulatory_for_sector(sector):
    """A7: Recent regulatory events affecting a sector.

    Two bugs fixed 2026-05-23 after Gillette dossier showed 2023 articles:
      1. `published_at` is stored RFC 2822 ("Wed, 27 Sep 2023..."). Naive
         ORDER BY does lexicographic sort, which puts "W"-day articles from
         2023 above "S"-day articles from 2025. Use julianday() to parse.
      2. No recency cutoff. Sector regulatory has 32 years of history; the
         dossier shows operational signal, not archive. 90-day window matches
         the regulatory.py DECAY_RATE half-life.
      3. Sector taxonomy: regulatory_signals carries "Financial Services" /
         "IT" while stocks uses "Financials" / "Information Technology". Map
         both ways so a query never silently misses 1.6k rows.
    """
    if not sector:
        return []
    sector_aliases = {
        "Financials": ["Financials", "Financial Services"],
        "Information Technology": ["Information Technology", "IT"],
    }.get(sector, [sector])
    placeholders = ",".join(["?"] * len(sector_aliases))
    df = read_sql(
        f"SELECT rs.direction, rs.magnitude, rs.time_horizon, rs.confidence, "
        f"rs.ai_reasoning, re.title, re.published_at "
        f"FROM regulatory_signals rs "
        f"JOIN regulatory_events re ON rs.event_id = re.event_id "
        f"WHERE rs.sector IN ({placeholders}) "
        f"  AND rs.magnitude IN ('major', 'moderate') "
        f"  AND rs.confidence IN ('high', 'medium') "
        f"  AND julianday('now') - julianday(re.published_at) <= 90 "
        f"ORDER BY julianday(re.published_at) DESC LIMIT 8",
        params=list(sector_aliases),
    )
    return df.to_dict("records") if not df.empty else []


def get_earnings_upcoming(sid=None):
    """A8: Upcoming earnings events."""
    if sid:
        df = read_sql(
            "SELECT date, purpose, bm_desc FROM earnings_calendar "
            "WHERE sid = ? AND date >= date('now') ORDER BY date LIMIT 3",
            params=[sid],
        )
    else:
        df = read_sql(
            "SELECT ec.date, ec.symbol, s.name, ec.purpose, ec.sid "
            "FROM earnings_calendar ec JOIN stocks s ON ec.sid = s.sid "
            "WHERE ec.date >= date('now') AND ec.date <= date('now', '+14 days') "
            "ORDER BY ec.date LIMIT 10",
        )
    return df.to_dict("records") if not df.empty else []


DOSSIER_MAX_AGE_DAYS = 3  # honest staleness cap; matches data_health "daily" threshold


@_ttl_cache(60)
def get_dossier(sid):
    """A9: AI investment dossier from latest JSON file.

    Refuses to serve theses older than DOSSIER_MAX_AGE_DAYS — previously this
    function walked back through history until it found ANY thesis, which
    silently surfaced 20-day-old text as if it were current (see HALC bug
    2026-05-22).
    """
    import re
    from datetime import datetime as _dt
    dossier_dir = PROJECT_ROOT / "output"
    files = sorted(glob.glob(str(dossier_dir / "dossiers_*.json")), reverse=True)
    today = _dt.now().date()
    for f in files:
        # File-date from filename for honest "as_of" labeling. If the filename
        # doesn't carry a date, skip — the dossier card can't be honest.
        m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(f).name)
        if not m:
            continue
        file_date = _dt.strptime(m.group(1), "%Y-%m-%d").date()
        age_days = (today - file_date).days
        if age_days > DOSSIER_MAX_AGE_DAYS:
            # Anything older isn't current truth — bail. The template's
            # `{% if dos.get("thesis") %}` will hide the card.
            return {}
        try:
            with open(f) as fh:
                dossiers = json.load(fh)
            for d in dossiers:
                if d.get("sid") == sid and d.get("thesis"):
                    # Reject hallucinated/invalid dossiers — see output/dossier.py
                    # _validate_dossier. Dossiers without a `validation` block
                    # are legacy (pre-validator) and we tolerate them but mark
                    # them as such so the template can show a notice.
                    v = d.get("validation")
                    if v and not v.get("ok", False):
                        return {}
                    return {
                        **d,
                        "as_of": file_date.isoformat(),
                        "age_days": age_days,
                        "validated": bool(v and v.get("ok")),
                    }
        except (json.JSONDecodeError, IOError):
            continue
    return {}


@_ttl_cache(60)
def get_sector_averages():
    """A10: Per-sector average metrics for comparison."""
    df = read_sql("""
        SELECT dp.sector,
               COUNT(*) as stock_count,
               ROUND(AVG(ds.earnings_yield), 4) as avg_ey,
               ROUND(AVG(ds.piotroski_f), 1) as avg_piotroski,
               ROUND(AVG(dp.final_score), 3) as avg_score,
               ROUND(AVG(ds.consensus_signal), 3) as avg_consensus
        FROM daily_picks dp
        JOIN daily_snapshots ds ON dp.sid = ds.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        AND ds.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
        AND dp.sector IS NOT NULL
        GROUP BY dp.sector
    """)
    return {r["sector"]: r for r in df.to_dict("records")} if not df.empty else {}


def get_portfolio_analytics(portfolio_data, regime):
    """A11: Portfolio-level analytics."""
    all_stocks = []
    for key in ["large", "mid", "small"]:
        all_stocks.extend(portfolio_data.get(key, []))

    if not all_stocks:
        return {}

    # Sector allocation
    sector_weights = {}
    for s in all_stocks:
        sec = s.get("sector", "Unknown")
        sector_weights[sec] = sector_weights.get(sec, 0) + s.get("weight", 0)
    sector_alloc = sorted(sector_weights.items(), key=lambda x: -x[1])

    # Expected return from analyst consensus
    upsides = []
    for s in all_stocks:
        ac = get_analyst_consensus(s["sid"])
        if ac.get("pt_upside_pct") is not None:
            upsides.append(ac["pt_upside_pct"])

    avg_upside = round(sum(upsides) / len(upsides), 1) if upsides else None
    avg_score = round(sum(s.get("final_score", 0) for s in all_stocks) / len(all_stocks) * 100, 0) if all_stocks else 0

    # Universe average score
    univ = read_sql("SELECT AVG(final_score) as avg FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)")
    univ_avg = round(univ.iloc[0]["avg"] * 100, 0) if not univ.empty and univ.iloc[0]["avg"] else 0

    return {
        "sector_allocation": sector_alloc,
        "expected_return": avg_upside,
        "stocks_with_targets": len(upsides),
        "avg_score": avg_score,
        "universe_avg_score": univ_avg,
        "score_premium": avg_score - univ_avg,
        "total_stocks": len(all_stocks),
        "top3_weight": sum(s.get("weight", 0) for s in sorted(all_stocks, key=lambda x: -x.get("weight", 0))[:3]),
    }


# Signal tooltips — what each signal means, why it matters
SIGNAL_TOOLTIPS = {
    "Consensus": "Analyst consensus: combines price target upside, EPS growth, and revenue growth forecasts. Strongest predictor for large-caps (t=3.52).",
    "Promoter": "Promoter shareholding changes: QoQ change in insider stake. When promoters buy, it signals confidence. Strongest for small-caps (t=3.20).",
    "Piotroski F": "9-point financial health checklist: profitability (3), leverage (3), efficiency (3). Score 7-9 = strong, 4-6 = average, 0-3 = weak.",
    "Accruals": "Earnings quality: measures if cash flow confirms reported earnings. High cash vs accruals = trustworthy. Strongest for mid-caps (t=3.20).",
    "Smart Money": "Institutional buying: detects accumulation via bulk/block deals and delivery percentage. Score 70+ = strong institutional interest.",
    "Earnings Yield": "E/P ratio (inverse of P/E). Higher = cheaper valuation. Handles negative earnings correctly unlike P/E.",
    "Forensic — Beneish": "Beneish M-Score: detects earnings manipulation using 8 financial ratios. Score > -1.78 flags likely manipulation. Prof. Beneish, Indiana University.",
    "Forensic — Altman": "Altman Z-Score: predicts bankruptcy risk using 4 ratios. Below 1.10 = distress. 1.10-2.60 = grey zone. Above 2.60 = safe.",
}


# One-line descriptions shown directly under signal labels (not hidden in tooltip)
SIGNAL_DESCRIPTIONS = {
    "Consensus": "Combines analyst price target upside, EPS growth and revenue growth forecasts.",
    "Promoter": "Tracks promoter shareholding changes. Buying signals insider confidence.",
    "Piotroski F": "9-point checklist covering profitability, leverage, and operating efficiency.",
    "Accruals": "Measures whether reported earnings are backed by real cash flow.",
    "Smart Money": "Detects institutional accumulation via bulk deals and delivery percentage.",
    "Earnings Yield": "Earnings/Price ratio. Higher = cheaper relative to earnings power.",
}


# Tooltips for each fundamental metric on the Financials tab
METRIC_TOOLTIPS = {
    "market_cap": "Total market value = share price × shares outstanding. Large >20K Cr, Mid 5-20K Cr, Small <5K Cr.",
    "pe_ratio": "Price-to-Earnings: How many years of current earnings the market prices in. Lower = cheaper. Compare within sector.",
    "earnings_yield": "Earnings/Price (inverse of P/E). Higher = cheaper. Handles negative earnings gracefully unlike P/E.",
    "de_ratio": "Debt-to-Equity: Total borrowings vs shareholder equity. <0.5 = conservative. >1.5 = highly leveraged.",
    "roe": "Return on Equity: Profit per rupee of shareholder capital. >15% is strong. Compare within sector.",
    "roa": "Return on Assets: Profit per rupee of total assets. >5% is strong. Measures asset efficiency.",
    "ebitda_margin": "EBITDA as % of revenue. Operational efficiency before interest, tax, depreciation. Higher = more efficient.",
    "pat_margin": "Net profit as % of revenue. Bottom-line efficiency after all costs. Higher = better cost control.",
    "book_value": "Net assets per share. If price < book value (P/B < 1), stock may be undervalued or distressed.",
    "fcf_yield": "Free cash flow / Market cap. Real cash generation vs price. >5% is attractive.",
    "current_ratio": "Current assets / Current liabilities. >1.5 = healthy short-term liquidity. <1 = potential cash crunch.",
    "revenue_growth": "Year-over-year revenue increase. Compares same quarter to remove seasonality.",
    "pat_growth": "Year-over-year net profit increase. Earnings growth is ultimately what drives long-term returns.",
    "piotroski": "9-point financial health checklist: profitability (3), leverage (3), efficiency (3). 7-9 = strong, 0-3 = weak.",
}


# Piotroski 9 factors with categories and human descriptions
PIOTROSKI_FACTORS = [
    ("roa_positive", "ROA > 0", "Profitability", "Company is profitable on assets"),
    ("cfo_positive", "CFO > 0", "Profitability", "Operating cash flow is positive"),
    ("roa_improving", "ROA improving", "Profitability", "Return on assets increased YoY"),
    ("accruals_quality", "CFO > Net Income", "Profitability", "Cash flow exceeds reported earnings — clean accounting"),
    ("leverage_down", "Leverage decreased", "Leverage", "Long-term debt ratio fell — deleveraging"),
    ("liquidity_up", "Current ratio up", "Leverage", "Short-term liquidity improved"),
    ("no_dilution", "No share dilution", "Leverage", "No new equity issued — existing shareholders not diluted"),
    ("gross_margin_up", "Gross margin up", "Efficiency", "Gross margin expanded YoY — pricing power"),
    ("asset_turnover_up", "Asset turnover up", "Efficiency", "Revenue per rupee of assets grew — better utilization"),
]


def get_changes(days=1):
    """Get recent change events from diff engine."""
    df = read_sql(
        "SELECT * FROM daily_changes WHERE change_date >= date('now', ?) "
        "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, id DESC",
        params=[f"-{days} days"],
    )
    if df.empty:
        # Fall back to computing live if table is empty
        try:
            from output.diff_engine import compute_changes
            return compute_changes()
        except Exception:
            return []
    return df.to_dict("records")


def get_regime():
    """Current VIX regime + allocation weights."""
    row = read_sql("SELECT * FROM regime_state WHERE id = 1")
    if row.empty:
        return {"regime": "UNKNOWN", "vix_latest": 0, "vix_20d_avg": 0,
                "alloc_large": 0.4, "alloc_mid": 0.3, "alloc_small": 0.3}
    r = row.iloc[0].to_dict()
    # Add color mapping
    colors = {"CALM": "green", "NORMAL": "blue", "CAUTION": "amber", "CRISIS": "red"}
    r["color"] = colors.get(r.get("regime"), "blue")
    return r


def get_top_picks(tier=None, top=5):
    """Top picks by tier with stock metadata."""
    where = f"AND dp.cap_tier = '{tier}'" if tier else ""
    df = read_sql(f"""
        SELECT dp.sid, dp.final_score, dp.rank, dp.cap_tier, dp.sector,
               dp.base_score, dp.forensic_adj,
               s.ticker, s.name, s.market_cap_cr, s.pe_ratio, s.roe
        FROM daily_picks dp
        JOIN stocks s ON dp.sid = s.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        {where}
        ORDER BY dp.cap_tier, dp.rank
    """)
    # NaN in numeric columns survives `to_dict` and breaks JSON serialization.
    import math
    def _records(d):
        out = []
        for r in d.to_dict("records"):
            out.append({k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in r.items()})
        return out

    if tier:
        return _records(df.head(top))

    # Group by tier, top N each
    result = {}
    for t in ["LARGE", "MID", "SMALL"]:
        result[t] = _records(df[df["cap_tier"] == t].head(top))
    return result


def get_pick_date():
    """Latest pick date."""
    row = read_sql("SELECT MAX(pick_date) as d FROM daily_picks")
    return row.iloc[0]["d"] if not row.empty else "unknown"


def get_stock_count():
    """Total scored stocks."""
    row = read_sql("SELECT COUNT(*) as n FROM daily_picks WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)")
    return row.iloc[0]["n"] if not row.empty else 0


def get_dominant_signal(sid):
    """Find the strongest signal for a stock (for display under ticker)."""
    # Check each signal table for the stock's strongest value
    signals = {}

    for table, col, label in [
        ("consensus_signals", "consensus_signal", "Consensus"),
        ("promoter_signals", "promoter_signal", "Promoter"),
        ("piotroski_scores", "f_score", "Piotroski"),
        ("accruals_scores", "accruals_signal", "Accruals"),
        ("insider_signals", "score_impact", "Insider"),
    ]:
        try:
            row = read_sql(f"""
                SELECT [{col}] as val FROM [{table}]
                WHERE sid = ? ORDER BY snapshot_date DESC LIMIT 1
            """, params=[sid])
            if not row.empty and row.iloc[0]["val"] is not None:
                signals[label] = float(row.iloc[0]["val"])
        except Exception:
            pass

    if not signals:
        return ""

    # Return top 2 signals by value
    sorted_sigs = sorted(signals.items(), key=lambda x: abs(x[1]), reverse=True)
    parts = []
    for name, val in sorted_sigs[:2]:
        if name == "Piotroski":
            parts.append(f"{name}: {int(val)}/9")
        else:
            parts.append(f"{name}: {val:.2f}")
    return " | ".join(parts)


def get_heatmap_data():
    """All stocks grouped by tier with scores for heat map."""
    df = read_sql("""
        SELECT dp.sid, s.ticker, s.name, dp.final_score as score, dp.cap_tier
        FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        ORDER BY dp.cap_tier, dp.final_score DESC
    """)
    result = {}
    for tier in ["LARGE", "MID", "SMALL"]:
        tier_df = df[df["cap_tier"] == tier]
        result[tier] = tier_df[["sid", "ticker", "name", "score"]].to_dict("records")
    return result


def get_explorer_table():
    """Ranked table view for explorer with enriched data."""
    df = read_sql("""
        SELECT dp.sid, s.ticker, s.name, dp.sector, dp.cap_tier, dp.rank,
               dp.final_score, ds.consensus_signal, ds.piotroski_f,
               ds.earnings_yield
        FROM daily_picks dp
        JOIN stocks s ON dp.sid = s.sid
        LEFT JOIN daily_snapshots ds ON dp.sid = ds.sid
            AND ds.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        ORDER BY dp.cap_tier, dp.rank
        LIMIT 100
    """)
    return df.to_dict("records") if not df.empty else []


def search_stocks(query):
    """Search stocks by ticker or name."""
    q = f"%{query}%"
    df = read_sql(
        "SELECT sid, ticker, name, sector, cap_tier FROM stocks "
        "WHERE ticker LIKE ? OR name LIKE ? LIMIT 20",
        params=[q, q],
    )
    return df.to_dict("records")


def get_stock_detail(sid):
    """Full stock data bundle for detail view."""
    stock = read_sql("SELECT * FROM stocks WHERE sid = ?", params=[sid])
    if stock.empty:
        return None

    detail = stock.iloc[0].to_dict()

    # Latest pick
    pick = read_sql(
        "SELECT final_score, rank, cap_tier FROM daily_picks "
        "WHERE sid = ? ORDER BY pick_date DESC LIMIT 1", params=[sid]
    )
    if not pick.empty:
        detail.update(pick.iloc[0].to_dict())

    # All signals
    signal_tables = [
        ("piotroski_scores", ["f_score", "roa_positive", "cfo_positive", "roa_improving",
                              "accruals_quality", "leverage_down", "liquidity_up",
                              "no_dilution", "gross_margin_up", "asset_turnover_up"]),
        ("accruals_scores", ["cf_accruals_ratio", "bs_accruals_ratio", "accruals_signal"]),
        ("consensus_signals", ["pt_upside", "pt_revision_1yr", "eps_growth", "revenue_growth", "consensus_signal"]),
        ("promoter_signals", ["promoter_qoq", "promoter_trend", "pledge_quality", "promoter_signal"]),
        ("forensic_scores", ["m_score", "m_score_flag", "z_score", "z_score_flag", "penalty"]),
        ("smart_money_scores", ["smart_money_score", "bulk_score", "delivery_score"]),
        ("sentiment_scores", ["sentiment_7d", "articles_7d"]),
        ("insider_signals", ["signal_type", "strength", "score_impact", "description"]),
    ]

    for table, cols in signal_tables:
        try:
            col_str = ", ".join(f"[{c}]" for c in cols)
            row = read_sql(
                f"SELECT {col_str} FROM [{table}] WHERE sid = ? ORDER BY snapshot_date DESC LIMIT 1",
                params=[sid],
            )
            if not row.empty:
                detail.update(row.iloc[0].to_dict())
        except Exception:
            pass

    # Latest price
    price = read_sql(
        "SELECT close, date FROM stock_prices WHERE sid = ? ORDER BY date DESC LIMIT 1",
        params=[sid],
    )
    if not price.empty:
        detail["close_price"] = price.iloc[0]["close"]
        detail["price_date"] = price.iloc[0]["date"]

    return detail


def get_price_series(sid, days=365):
    """Price time series for charts."""
    df = read_sql(
        "SELECT date, close, volume FROM stock_prices "
        "WHERE sid = ? ORDER BY date DESC LIMIT ?",
        params=[sid, days],
    )
    return df.sort_values("date").to_dict("records") if not df.empty else []


def get_price_series_extended(sid, days=365):
    """Extended price series with OHLCV + delivery % for technicals tab."""
    df = read_sql(
        "SELECT date, open, high, low, close, volume, delivery_pct "
        "FROM stock_prices WHERE sid = ? AND close > 0 "
        "ORDER BY date DESC LIMIT ?",
        params=[sid, days],
    )
    return df.sort_values("date").to_dict("records") if not df.empty else []


def get_quarterly_financials(sid):
    """10 quarters of income statement + TTM aggregates + YoY growth."""
    df = read_sql(
        "SELECT period, end_date, revenue, net_income, eps, ebitda, "
        "operating_profit, pbt, interest "
        "FROM quarterly_income WHERE sid = ? AND reporting = 'consolidated' "
        "ORDER BY end_date DESC LIMIT 10",
        params=[sid],
    )
    if df.empty:
        df = read_sql(
            "SELECT period, end_date, revenue, net_income, eps, ebitda, "
            "operating_profit, pbt, interest "
            "FROM quarterly_income WHERE sid = ? AND reporting = 'standalone' "
            "ORDER BY end_date DESC LIMIT 10",
            params=[sid],
        )
    if df.empty:
        return {"quarters": [], "ttm": {}, "yoy": {}}

    # The Tickertape `qIncOpe` field maps to operating expenses, not interest expense
    # (loader at sources/tickertape.py:72 mislabels it). The stored `ebitda` column is
    # therefore unreliable. Approximate EBITDA as revenue − opex for display.
    df["ebitda"] = (df["revenue"] - df["interest"].fillna(0)).where(df["interest"].notna())
    df["ebitda_margin"] = (df["ebitda"] / df["revenue"] * 100).round(1)
    df["pat_margin"] = (df["net_income"] / df["revenue"] * 100).round(1)

    # YoY growth: compare each quarter to the same quarter 4 quarters ago
    quarters = df.sort_values("end_date").to_dict("records")
    for i, q in enumerate(quarters):
        if i >= 4:
            prior = quarters[i - 4]
            if prior.get("revenue") and prior["revenue"] > 0:
                q["revenue_yoy"] = round((q["revenue"] / prior["revenue"] - 1) * 100, 1)
            if prior.get("net_income") and prior["net_income"] != 0:
                q["pat_yoy"] = round((q["net_income"] / prior["net_income"] - 1) * 100, 1)

    # TTM (last 4 quarters, latest first)
    ttm = {}
    if len(df) >= 4:
        last4 = df.head(4)
        ttm["revenue"] = round(last4["revenue"].sum(), 0)
        ttm["pat"] = round(last4["net_income"].sum(), 0)
        ttm["ebitda"] = round(last4["ebitda"].sum(), 0)
        ttm["eps"] = round(last4["eps"].sum(), 2)
        if ttm["revenue"] > 0:
            ttm["ebitda_margin"] = round(ttm["ebitda"] / ttm["revenue"] * 100, 1)
            ttm["pat_margin"] = round(ttm["pat"] / ttm["revenue"] * 100, 1)

    # YoY at latest quarter
    yoy = {}
    if quarters:
        latest = quarters[-1]
        yoy["revenue_growth"] = latest.get("revenue_yoy")
        yoy["pat_growth"] = latest.get("pat_yoy")

    return {
        "quarters": list(reversed(quarters)),  # most recent first for display
        "ttm": ttm,
        "yoy": yoy,
    }


def get_annual_financials(sid):
    """Annual balance sheet + cash flow + computed ratios."""
    bs = read_sql(
        "SELECT period, end_date, total_assets, total_equity, total_debt, "
        "current_assets, current_liabilities, shares_outstanding, long_term_debt, "
        "cash_and_equivalents, total_liabilities "
        "FROM annual_balance_sheet WHERE sid = ? ORDER BY end_date DESC LIMIT 5",
        params=[sid],
    )
    cf = read_sql(
        "SELECT period, end_date, operating_cash_flow, capex, free_cash_flow, "
        "depreciation, financing_cash_flow, investing_cash_flow "
        "FROM annual_cash_flow WHERE sid = ? ORDER BY end_date DESC LIMIT 5",
        params=[sid],
    )

    ratios = {}
    if not bs.empty:
        latest = bs.iloc[0]
        if latest.get("total_equity") and latest["total_equity"] > 0:
            ratios["de_ratio"] = round((latest.get("total_debt") or 0) / latest["total_equity"], 2)
            if latest.get("shares_outstanding") and latest["shares_outstanding"] > 0:
                # Equity in Cr, shares_outstanding in Cr → BV per share in Rs
                ratios["book_value"] = round(latest["total_equity"] / latest["shares_outstanding"], 2)
        if latest.get("current_liabilities") and latest["current_liabilities"] > 0:
            ratios["current_ratio"] = round((latest.get("current_assets") or 0) / latest["current_liabilities"], 2)
        ratios["total_equity"] = latest.get("total_equity")
        ratios["total_debt"] = latest.get("total_debt")
        ratios["total_assets"] = latest.get("total_assets")

    if not cf.empty:
        latest_cf = cf.iloc[0]
        ratios["fcf"] = latest_cf.get("free_cash_flow")
        ratios["ocf"] = latest_cf.get("operating_cash_flow")
        ratios["capex"] = latest_cf.get("capex")
        if latest_cf.get("operating_cash_flow") and latest_cf["operating_cash_flow"] != 0:
            ratios["capex_ratio"] = round(abs(latest_cf.get("capex") or 0) / abs(latest_cf["operating_cash_flow"]), 2)

    # ROE and ROA need TTM PAT — fetch latest 4 quarters
    quarterly = read_sql(
        "SELECT net_income FROM quarterly_income WHERE sid = ? "
        "AND reporting = 'consolidated' ORDER BY end_date DESC LIMIT 4",
        params=[sid],
    )
    if quarterly.empty:
        quarterly = read_sql(
            "SELECT net_income FROM quarterly_income WHERE sid = ? "
            "AND reporting = 'standalone' ORDER BY end_date DESC LIMIT 4",
            params=[sid],
        )
    if len(quarterly) >= 4 and not bs.empty:
        ttm_pat = quarterly["net_income"].sum()
        latest_eq = bs.iloc[0].get("total_equity")
        latest_assets = bs.iloc[0].get("total_assets")
        if latest_eq and latest_eq > 0:
            ratios["roe"] = round(ttm_pat / latest_eq * 100, 1)
        if latest_assets and latest_assets > 0:
            ratios["roa"] = round(ttm_pat / latest_assets * 100, 1)

    return {
        "balance_sheet": bs.to_dict("records") if not bs.empty else [],
        "cash_flow": cf.to_dict("records") if not cf.empty else [],
        "ratios": ratios,
    }


def get_forecast_trend(sid):
    """Analyst forecast revisions over time (PT, EPS, Revenue)."""
    df = read_sql(
        "SELECT metric, date, value, change FROM forecast_history "
        "WHERE sid = ? ORDER BY date ASC",
        params=[sid],
    )
    if df.empty:
        return {"price_target": [], "eps": [], "revenue": []}

    # Replace NaN with None for JSON compatibility
    df = df.where(pd.notna(df), None)

    result = {"price_target": [], "eps": [], "revenue": []}
    for _, r in df.iterrows():
        m = (r.get("metric") or "").lower()
        val = r["value"]
        # Skip rows with no value
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        entry = {
            "date": r["date"],
            "value": float(val),
            "change": float(r["change"]) if r.get("change") is not None and not (isinstance(r["change"], float) and pd.isna(r["change"])) else None,
        }
        if "price" in m or "target" in m or m == "pt":
            result["price_target"].append(entry)
        elif "eps" in m:
            result["eps"].append(entry)
        elif "revenue" in m or "sales" in m:
            result["revenue"].append(entry)
    return result


def get_insider_timeline(sid):
    """Monthly aggregated insider buy/sell activity for timeline chart."""
    df = read_sql(
        "SELECT strftime('%Y-%m', trade_date) as month, "
        "SUM(CASE WHEN transaction_type = 'Buy' THEN value_lakhs ELSE 0 END) as buy_value, "
        "SUM(CASE WHEN transaction_type = 'Sell' THEN value_lakhs ELSE 0 END) as sell_value, "
        "COUNT(*) as trade_count "
        "FROM insider_trades "
        "WHERE sid = ? AND trade_date >= date('now', '-730 days') "
        "AND trade_date <= date('now') "
        "GROUP BY month ORDER BY month",
        params=[sid],
    )
    return df.to_dict("records") if not df.empty else []


def get_sector_comparison(sid, sector):
    """Sector median values for fundamentals comparison."""
    if not sector:
        return {}
    df = read_sql(
        """
        SELECT
            ROUND(AVG(ds.earnings_yield), 4) as avg_ey,
            ROUND(AVG(ds.piotroski_f), 1) as avg_piotroski,
            ROUND(AVG(dp.final_score), 3) as avg_score,
            ROUND(AVG(ds.consensus_signal), 3) as avg_consensus,
            COUNT(*) as stock_count
        FROM daily_picks dp
        JOIN daily_snapshots ds ON dp.sid = ds.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        AND ds.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
        AND dp.sector = ?
        """,
        params=[sector],
    )
    base = df.iloc[0].to_dict() if not df.empty else {}

    # Sector median D/E from latest balance sheet per stock in sector
    de_df = read_sql(
        """
        SELECT AVG(CASE WHEN abs.total_equity > 0
                        THEN abs.total_debt / abs.total_equity
                        ELSE NULL END) as avg_de
        FROM annual_balance_sheet abs
        JOIN stocks s ON abs.sid = s.sid
        WHERE s.sector = ?
        AND abs.end_date = (SELECT MAX(end_date) FROM annual_balance_sheet WHERE sid = abs.sid)
        """,
        params=[sector],
    )
    if not de_df.empty and de_df.iloc[0]["avg_de"] is not None:
        base["avg_de"] = round(float(de_df.iloc[0]["avg_de"]), 2)

    return base


def get_active_signals():
    """Get stocks with strong active signals, grouped by signal type."""
    signals = {}

    # Promoter Buying
    df = read_sql("""
        SELECT ps.sid, s.ticker, s.name, s.cap_tier, ps.promoter_qoq, ps.promoter_signal,
               ps.promoter_trend, ps.pledge_quality
        FROM promoter_signals ps JOIN stocks s ON ps.sid = s.sid
        WHERE ps.snapshot_date = (SELECT MAX(snapshot_date) FROM promoter_signals)
        AND ps.promoter_qoq > 0.5
        ORDER BY ps.promoter_qoq DESC LIMIT 20
    """)
    signals["Promoter Buying"] = [
        {**r, "explanation": f"Promoters increased stake by +{r['promoter_qoq']:.2f}% QoQ. Trend: {r.get('promoter_trend', 'N/A')}",
         "strength": r["promoter_signal"], "color": "green"}
        for r in df.to_dict("records")
    ]

    # Consensus Upgrade
    df = read_sql("""
        SELECT cs.sid, s.ticker, s.name, s.cap_tier, cs.consensus_signal,
               cs.pt_upside, cs.eps_growth, cs.revenue_growth
        FROM consensus_signals cs JOIN stocks s ON cs.sid = s.sid
        WHERE cs.snapshot_date = (SELECT MAX(snapshot_date) FROM consensus_signals)
        AND cs.consensus_signal > 0.65
        ORDER BY cs.consensus_signal DESC LIMIT 20
    """)
    signals["Consensus Upgrade"] = [
        {**r, "explanation": f"Strong analyst consensus ({r['consensus_signal']:.2f}). EPS growth: {r.get('eps_growth', 0):.0f}%",
         "strength": r["consensus_signal"], "color": "green"}
        for r in df.to_dict("records")
    ]

    # Forensic Alert
    df = read_sql("""
        SELECT fs.sid, s.ticker, s.name, s.cap_tier, fs.m_score, fs.m_score_flag,
               fs.z_score, fs.z_score_flag, fs.penalty
        FROM forensic_scores fs JOIN stocks s ON fs.sid = s.sid
        WHERE fs.snapshot_date = (SELECT MAX(snapshot_date) FROM forensic_scores)
        AND (fs.m_score_flag = 'LIKELY_MANIPULATOR' OR fs.z_score_flag = 'DISTRESS')
        ORDER BY fs.penalty ASC LIMIT 20
    """)
    signals["Forensic Alert"] = [
        {**r, "explanation": f"M-Score: {r.get('m_score', 'N/A')} ({r.get('m_score_flag', '')}), Z-Score: {r.get('z_score', 'N/A')} ({r.get('z_score_flag', '')})",
         "strength": abs(r.get("penalty") or 0), "color": "red"}
        for r in df.to_dict("records")
    ]

    # Insider Activity
    df = read_sql("""
        SELECT iss.sid, s.ticker, s.name, s.cap_tier, iss.signal_type, iss.strength,
               iss.score_impact, iss.description
        FROM insider_signals iss JOIN stocks s ON iss.sid = s.sid
        WHERE iss.snapshot_date = (SELECT MAX(snapshot_date) FROM insider_signals)
        AND iss.signal_type IN ('STRONG_BUY', 'STRONG_SELL')
        ORDER BY ABS(iss.score_impact) DESC LIMIT 20
    """)
    signals["Insider Activity"] = [
        {**r, "explanation": r.get("description", f"{r['signal_type']}"),
         "strength": abs(r.get("score_impact") or 0),
         "color": "green" if "BUY" in r.get("signal_type", "") else "red"}
        for r in df.to_dict("records")
    ]

    # Smart Money
    df = read_sql("""
        SELECT sm.sid, s.ticker, s.name, s.cap_tier, sm.smart_money_score,
               sm.delivery_score, sm.net_buy_qty
        FROM smart_money_scores sm JOIN stocks s ON sm.sid = s.sid
        WHERE sm.snapshot_date = (SELECT MAX(snapshot_date) FROM smart_money_scores)
        AND sm.smart_money_score > 70
        ORDER BY sm.smart_money_score DESC LIMIT 20
    """)
    signals["Smart Money"] = [
        {**r, "explanation": f"Smart money score: {r['smart_money_score']:.0f}/100. Delivery: {r.get('delivery_score', 0):.0f}",
         "strength": r["smart_money_score"] / 100, "color": "green"}
        for r in df.to_dict("records")
    ]

    # Regulatory
    df = read_sql("""
        SELECT rs.sector, rs.direction, rs.magnitude, rs.ai_reasoning, re.title,
               re.published_at
        FROM regulatory_signals rs
        JOIN regulatory_events re ON rs.event_id = re.event_id
        WHERE rs.magnitude IN ('major', 'moderate')
        AND re.published_at >= date('now', '-7 days')
        ORDER BY re.published_at DESC LIMIT 15
    """)
    signals["Regulatory"] = [
        {**r, "explanation": r.get("ai_reasoning", r.get("title", "")),
         "ticker": r["sector"], "name": r.get("title", "")[:80],
         "strength": 1.0 if r.get("magnitude") == "major" else 0.6,
         "color": "green" if r.get("direction", 0) > 0 else "red",
         "cap_tier": r.get("magnitude", "").upper()}
        for r in df.to_dict("records")
    ]

    return signals


@_ttl_cache(60)
def get_action_candidates():
    """Stocks categorized into Buy/Watch/Exit based on signals + changes."""
    changes = get_changes(days=7)

    buy, watch, exit_list = [], [], []

    # Consider Buying: entered top picks recently + strong signals
    entries = [c for c in changes if c.get("change_type") == "ENTRY" and c.get("color") == "green"]
    for e in entries[:10]:
        sid = e.get("sid")
        if not sid:
            continue
        detail = get_stock_detail(sid)
        if detail:
            buy.append({
                "sid": sid, "ticker": detail.get("ticker", sid),
                "name": detail.get("name", ""), "cap_tier": detail.get("cap_tier", ""),
                "score": detail.get("final_score", 0), "rank": detail.get("rank"),
                "reason": e.get("headline", ""),
                "detail": e.get("detail", ""),
            })

    # Consider Exiting: dropped from top picks
    exits = [c for c in changes if c.get("change_type") == "EXIT" and c.get("color") == "red"]
    for e in exits[:10]:
        sid = e.get("sid")
        if not sid:
            continue
        detail = get_stock_detail(sid)
        if detail:
            exit_list.append({
                "sid": sid, "ticker": detail.get("ticker", sid),
                "name": detail.get("name", ""), "cap_tier": detail.get("cap_tier", ""),
                "score": detail.get("final_score", 0),
                "reason": e.get("headline", ""),
                "detail": e.get("detail", ""),
            })

    # Watch: forensic alerts on top picks
    forensic_alerts = read_sql("""
        SELECT fs.sid, s.ticker, s.name, dp.rank, dp.cap_tier, fs.m_score_flag, fs.z_score_flag
        FROM forensic_scores fs
        JOIN stocks s ON fs.sid = s.sid
        JOIN daily_picks dp ON fs.sid = dp.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        AND dp.rank <= 20
        AND (fs.m_score_flag = 'LIKELY_MANIPULATOR' OR fs.z_score_flag = 'DISTRESS')
        ORDER BY dp.rank LIMIT 10
    """)
    for _, r in forensic_alerts.iterrows():
        flags = []
        if r.get("m_score_flag") == "LIKELY_MANIPULATOR":
            flags.append("Beneish M-Score flagged")
        if r.get("z_score_flag") == "DISTRESS":
            flags.append("Altman Z-Score distress")
        watch.append({
            "sid": r["sid"], "ticker": r["ticker"], "name": r["name"],
            "cap_tier": r["cap_tier"], "rank": r["rank"],
            "reason": f"Forensic alert on Top {int(r['rank'])} {r['cap_tier']}",
            "detail": "; ".join(flags),
        })

    return {"buy": buy, "watch": watch, "exit": exit_list}


@_ttl_cache(60)
def get_model_portfolio():
    """Model portfolio: top stocks per tier with position weights."""
    regime = get_regime()
    picks_per_tier = {"LARGE": 10, "MID": 10, "SMALL": 10}

    result = {"large": [], "mid": [], "small": []}

    for tier, key, n in [("LARGE", "large", 10), ("MID", "mid", 10), ("SMALL", "small", 10)]:
        alloc = regime.get(f"alloc_{key}", 0.33)
        stocks = get_top_picks(tier=tier, top=n)
        if stocks:
            weight_per = (alloc * 100) / len(stocks) if stocks else 0
            for s in stocks:
                s["weight"] = round(weight_per, 1)
        result[key] = stocks

    return result


def get_sector_overview():
    """Sector scores + stock counts. avg_score is MARKET-CAP WEIGHTED."""
    df = read_sql("""
        SELECT dp.sector,
               COUNT(*) AS stocks,
               ROUND(
                 SUM(dp.final_score * s.market_cap_cr) /
                 NULLIF(SUM(s.market_cap_cr), 0),
                 3
               ) AS avg_score,
               MIN(dp.rank) as best_rank
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        AND dp.sector IS NOT NULL
        GROUP BY dp.sector
        ORDER BY avg_score DESC NULLS LAST
    """)

    # Merge with macro sector signals (latest snapshot only — table keeps history)
    macro = read_sql("""
        SELECT sector, macro_score, macro_signal, macro_detail
        FROM macro_sector_signals
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM macro_sector_signals)
    """)
    if not macro.empty:
        df = df.merge(macro, on="sector", how="left")

    # Tab 1 polish: breadth + top-3 tickers per sector
    breadth = read_sql("""
        SELECT sector,
               ROUND(100.0 * SUM(CASE WHEN final_score >= 0.55 THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS breadth_pct
        FROM daily_picks
        WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)
          AND sector IS NOT NULL
        GROUP BY sector
    """)
    if not breadth.empty:
        df = df.merge(breadth, on="sector", how="left")

    top_n = read_sql("""
        WITH ranked AS (
            SELECT dp.sector, s.ticker, dp.final_score,
                   ROW_NUMBER() OVER (PARTITION BY dp.sector ORDER BY dp.final_score DESC) AS r
            FROM daily_picks dp
            JOIN stocks s ON s.sid = dp.sid
            WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
              AND dp.sector IS NOT NULL
        )
        SELECT sector, ticker, final_score
        FROM ranked WHERE r <= 3
    """)
    top_by_sector = {}
    if not top_n.empty:
        for _, r in top_n.iterrows():
            top_by_sector.setdefault(r["sector"], []).append(r["ticker"])
    df["top_3"] = df["sector"].map(lambda s: ", ".join(top_by_sector.get(s, [])))

    return df.to_dict("records")


def get_sector_list():
    """Sorted list of sectors that have any stocks in the universe."""
    df = read_sql(
        "SELECT DISTINCT sector FROM stocks "
        "WHERE sector IS NOT NULL AND ticker IS NOT NULL "
        "ORDER BY sector"
    )
    return df["sector"].tolist()


def get_sector_metadata(sector):
    """Pull the latest sector_metadata payload for a sector. Manual override
    wins over auto. Returns None if no narrative has been generated yet."""
    df = read_sql(
        "SELECT industry, source, generated_at, payload FROM sector_metadata "
        "WHERE sector = ? "
        "ORDER BY CASE source WHEN 'manual' THEN 0 ELSE 1 END, generated_at DESC "
        "LIMIT 1",
        params=[sector],
    )
    if df.empty:
        return None
    row = df.iloc[0]
    try:
        payload = json.loads(row["payload"])
    except json.JSONDecodeError:
        return None
    payload["_industry"] = row["industry"]
    payload["_source"] = row["source"]
    payload["_generated_at"] = row["generated_at"]
    return payload


def get_sector_top_players(sector, n=10):
    """Top n players in this sector by market cap, with our composite score
    if available."""
    df = read_sql(
        """
        SELECT s.sid, s.ticker, s.name, s.market_cap_cr,
               COALESCE(dp.final_score, 0) AS final_score,
               COALESCE(dp.rank, NULL)     AS rank
        FROM stocks s
        LEFT JOIN daily_picks dp
          ON dp.sid = s.sid
         AND dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        WHERE s.sector = ? AND s.ticker IS NOT NULL
        ORDER BY s.market_cap_cr DESC
        LIMIT ?
        """,
        params=[sector, n],
    )
    if df.empty:
        return []
    # Convert market_cap from raw rupees → ₹cr (column is misnamed)
    df["market_cap_cr"] = (df["market_cap_cr"] / 1e7).round(0)
    sector_total = df["market_cap_cr"].sum()
    df["share_pct"] = (100.0 * df["market_cap_cr"] / sector_total if sector_total else 0).round(1)
    return df.to_dict("records")


def get_sector_picks(sector, top_n=10, bottom_n=5):
    """Top-N picks (highest composite) and bottom-N (lowest composite) within a sector."""
    df = read_sql(
        """
        SELECT s.sid, s.ticker, s.name, dp.final_score, dp.cap_tier
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE dp.sector = ?
          AND dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        ORDER BY dp.final_score DESC
        """,
        params=[sector],
    )
    if df.empty:
        return {"top": [], "bottom": []}
    return {
        "top":    df.head(top_n).to_dict("records"),
        "bottom": df.tail(bottom_n).iloc[::-1].to_dict("records"),
    }


def get_sector_factor_means(sector):
    """Mean of each factor (from latest daily_snapshots_pit) across stocks in
    this sector. Used in Tab 2 v1 as a descriptive 'which factors are working
    here' table — until per-sector IC backtest extension lands."""
    df = read_sql(
        """
        SELECT pit.*
        FROM daily_snapshots_pit pit
        JOIN stocks s ON s.sid = pit.sid
        WHERE s.sector = ?
          AND pit.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots_pit)
        """,
        params=[sector],
    )
    if df.empty:
        return []
    excluded = {"sid", "snapshot_date", "cap_tier", "close_price",
                "reconstructed_at", "fwd_return_20d"}
    factor_cols = [c for c in df.columns if c not in excluded]
    rows = []
    for c in factor_cols:
        vals = df[c].dropna()
        if vals.empty:
            continue
        rows.append({
            "factor": c,
            "n_stocks": int(vals.shape[0]),
            "mean": float(round(vals.mean(), 4)),
            "median": float(round(vals.median(), 4)),
        })
    rows.sort(key=lambda r: -abs(r["mean"]))
    return rows


def get_sector_macro_contributors(sector):
    """The macro_indicator → sector_weight map for this sector, joined with
    latest macro indicator values."""
    df = read_sql(
        """
        SELECT msm.indicator_id, msm.weight, msm.direction,
               mh.value AS latest_value, mh.date AS latest_date
        FROM macro_sector_map msm
        LEFT JOIN (
            SELECT indicator_id, value, date,
                   ROW_NUMBER() OVER (PARTITION BY indicator_id ORDER BY date DESC) AS r
            FROM macro_history
        ) mh ON mh.indicator_id = msm.indicator_id AND mh.r = 1
        WHERE msm.sector = ?
        ORDER BY ABS(msm.weight) DESC
        """,
        params=[sector],
    )
    return df.to_dict("records") if not df.empty else []


def get_sector_recent_regulatory(sector, n=10):
    """Recent regulatory events for stocks in this sector.

    Same RFC-2822-sort + taxonomy fixes as get_regulatory_for_sector
    (2026-05-23 Gillette bug).
    """
    sector_aliases = {
        "Financials": ["Financials", "Financial Services"],
        "Information Technology": ["Information Technology", "IT"],
    }.get(sector, [sector])
    placeholders = ",".join(["?"] * len(sector_aliases))
    df = read_sql(
        f"""
        SELECT re.event_id, re.published_at, re.title, rs.direction, rs.magnitude
        FROM regulatory_events re
        JOIN regulatory_signals rs ON rs.event_id = re.event_id
        WHERE rs.sector IN ({placeholders}) AND rs.direction IS NOT NULL
          AND julianday('now') - julianday(re.published_at) <= 90
        ORDER BY julianday(re.published_at) DESC
        LIMIT ?
        """,
        params=list(sector_aliases) + [n],
    )
    return df.to_dict("records") if not df.empty else []


def get_industry_overview():
    """Per-industry rollup. avg_score is MARKET-CAP WEIGHTED across stocks
    with a daily_picks score, so a ₹10L cr leader doesn't get diluted by 50
    micro-caps. Stocks without a final_score (NULL daily_picks join) are
    excluded from the weighted average.
    """
    df = read_sql("""
        SELECT s.industry AS industry, s.sector AS sector,
               COUNT(*) AS stocks,
               ROUND(
                 SUM(dp.final_score * s.market_cap_cr) /
                 NULLIF(SUM(CASE WHEN dp.final_score IS NOT NULL THEN s.market_cap_cr ELSE 0 END), 0),
                 3
               ) AS avg_score
        FROM stocks s
        LEFT JOIN daily_picks dp
          ON dp.sid = s.sid
         AND dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        WHERE s.industry IS NOT NULL AND s.ticker IS NOT NULL
        GROUP BY s.industry, s.sector
        ORDER BY avg_score DESC NULLS LAST
    """)
    if df.empty:
        return []

    # Macro signal inherited from parent sector
    macro = read_sql("""
        SELECT sector, macro_score, macro_signal, macro_detail
        FROM macro_sector_signals
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM macro_sector_signals)
    """)
    if not macro.empty:
        df = df.merge(macro, on="sector", how="left")

    # Breadth per industry
    breadth = read_sql("""
        SELECT s.industry,
               ROUND(100.0 * SUM(CASE WHEN dp.final_score >= 0.55 THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS breadth_pct
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
          AND s.industry IS NOT NULL
        GROUP BY s.industry
    """)
    if not breadth.empty:
        df = df.merge(breadth, on="industry", how="left")

    # Top-3 tickers per industry
    top_n = read_sql("""
        WITH ranked AS (
            SELECT s.industry, s.ticker, dp.final_score,
                   ROW_NUMBER() OVER (PARTITION BY s.industry ORDER BY dp.final_score DESC) AS r
            FROM daily_picks dp
            JOIN stocks s ON s.sid = dp.sid
            WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
              AND s.industry IS NOT NULL
        )
        SELECT industry, ticker FROM ranked WHERE r <= 3
    """)
    top_by_ind = {}
    if not top_n.empty:
        for _, r in top_n.iterrows():
            top_by_ind.setdefault(r["industry"], []).append(r["ticker"])
    df["top_3"] = df["industry"].map(lambda i: ", ".join(top_by_ind.get(i, [])))

    return df.to_dict("records")


def get_industry_list():
    """Sorted list of industries that have any stocks."""
    df = read_sql(
        "SELECT DISTINCT industry FROM stocks "
        "WHERE industry IS NOT NULL AND ticker IS NOT NULL "
        "ORDER BY industry"
    )
    return df["industry"].tolist()


def get_industry_metadata(industry):
    """Same as get_sector_metadata but keyed by industry name (which is
    stored in sector_metadata.sector — the column is named for legacy
    reasons; we treat its value as 'taxonomy key', be it sector or industry)."""
    return get_sector_metadata(industry)


def get_industry_parent_sector(industry):
    """Return the GICS sector this industry rolls up to."""
    df = read_sql(
        "SELECT DISTINCT sector FROM stocks "
        "WHERE industry = ? AND sector IS NOT NULL LIMIT 1",
        params=[industry],
    )
    return df["sector"].iloc[0] if not df.empty else None


def get_industry_top_players(industry, n=10):
    """Listed-only top players within an industry.

    Notes on shares:
      - Drops rows with NaN market cap (those tickers have no fundamentals data).
      - Denominator is the full LISTED industry market cap (not the top-N sum),
        so a single dominant ticker won't show 100% if other listed peers exist.
      - This is "share of LISTED universe" — for true industry share that
        includes private/unlisted players, see get_industry_competitive_landscape.
    """
    df = read_sql(
        """
        SELECT s.sid, s.ticker, s.name, s.market_cap_cr,
               COALESCE(dp.final_score, 0) AS final_score,
               COALESCE(dp.rank, NULL)     AS rank
        FROM stocks s
        LEFT JOIN daily_picks dp
          ON dp.sid = s.sid
         AND dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        WHERE s.industry = ?
          AND s.ticker IS NOT NULL
          AND s.market_cap_cr IS NOT NULL
        ORDER BY s.market_cap_cr DESC
        LIMIT ?
        """,
        params=[industry, n],
    )
    if df.empty:
        return []
    df["market_cap_cr"] = (df["market_cap_cr"] / 1e7).round(0)
    # Denominator = full listed industry mcap, not just top-N's sum.
    total_listed = read_sql(
        "SELECT COALESCE(SUM(market_cap_cr), 0) / 1e7 AS total "
        "FROM stocks WHERE industry = ? AND market_cap_cr IS NOT NULL",
        params=[industry],
    )["total"].iloc[0]
    if total_listed and total_listed > 0:
        df["share_pct"] = (100.0 * df["market_cap_cr"] / total_listed).round(1)
    else:
        df["share_pct"] = 0.0
    return df.to_dict("records")


def get_industry_competitive_landscape(industry):
    """Real industry concentration including private / unlisted players.

    Sourced from the narrative payload (`competitive_landscape.players`),
    then enriched: any listed player whose ticker matches a row in `stocks`
    is given a SID + our composite score for navigation. Private players
    are marked listed=False and have no SID.

    Returns {share_basis, as_of, players: [...]} or None if no narrative
    or the narrative doesn't carry this field yet.
    """
    narr = get_industry_metadata(industry)
    if not narr:
        return None
    cl = narr.get("competitive_landscape")
    if not cl or not isinstance(cl, dict) or not cl.get("players"):
        return None

    # Build a ticker -> stock-row map for quick enrichment
    df = read_sql(
        """
        SELECT s.sid, s.ticker, s.name, s.market_cap_cr,
               COALESCE(dp.final_score, 0) AS final_score
        FROM stocks s
        LEFT JOIN daily_picks dp
          ON dp.sid = s.sid
         AND dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        WHERE s.industry = ? AND s.ticker IS NOT NULL
        """,
        params=[industry],
    )
    by_ticker = {row["ticker"]: row for _, row in df.iterrows()}

    enriched = []
    for pl in cl.get("players", []):
        out = {
            "name": pl.get("name"),
            "share_pct": pl.get("share_pct"),
            "listed": bool(pl.get("listed")),
            "note": pl.get("note") or "",
            "ticker": pl.get("ticker"),
            "sid": None,
            "final_score": None,
            "market_cap_cr": None,
        }
        # Only enrich via EXPLICIT ticker match. Name-token fuzzy matching
        # is too dangerous (e.g. "Reliance Jio" → ticker RCOM which is the
        # defunct Reliance Communications). If Claude doesn't provide a
        # ticker, treat the player as not-clickable rather than guess.
        if out["ticker"] and out["ticker"] in by_ticker:
            match = by_ticker[out["ticker"]]
            out["sid"] = match["sid"]
            out["final_score"] = float(match["final_score"]) if match["final_score"] is not None else None
            mcap = match["market_cap_cr"]
            out["market_cap_cr"] = round(mcap / 1e7, 0) if mcap is not None and mcap == mcap else None
            out["listed"] = True  # if we found a row, it's listed in our DB
        elif pl.get("ticker"):
            # Claude claimed a ticker but it's not in our universe — could be
            # a foreign listing or a misremembered symbol. Keep its `listed`
            # value but don't make it clickable.
            pass
        enriched.append(out)

    # Compute "other" residual so totals visibly add to ≤100
    covered = sum((p["share_pct"] or 0) for p in enriched)
    other = round(max(0.0, 100.0 - covered), 1)

    return {
        "share_basis": cl.get("share_basis") or "industry share",
        "as_of": cl.get("as_of") or "",
        "players": enriched,
        "other_pct": other,
    }


def get_industry_picks(industry, top_n=10, bottom_n=5):
    df = read_sql(
        """
        SELECT s.sid, s.ticker, s.name, dp.final_score, dp.cap_tier
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE s.industry = ?
          AND dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        ORDER BY dp.final_score DESC
        """,
        params=[industry],
    )
    if df.empty:
        return {"top": [], "bottom": []}
    return {
        "top":    df.head(top_n).to_dict("records"),
        "bottom": df.tail(bottom_n).iloc[::-1].to_dict("records"),
    }


def get_industry_factor_means(industry):
    df = read_sql(
        """
        SELECT pit.*
        FROM daily_snapshots_pit pit
        JOIN stocks s ON s.sid = pit.sid
        WHERE s.industry = ?
          AND pit.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots_pit)
        """,
        params=[industry],
    )
    if df.empty:
        return []
    excluded = {"sid", "snapshot_date", "cap_tier", "close_price",
                "reconstructed_at", "fwd_return_20d"}
    factor_cols = [c for c in df.columns if c not in excluded]
    rows = []
    for c in factor_cols:
        vals = df[c].dropna()
        if vals.empty:
            continue
        rows.append({
            "factor": c,
            "n_stocks": int(vals.shape[0]),
            "mean": float(round(vals.mean(), 4)),
            "median": float(round(vals.median(), 4)),
        })
    rows.sort(key=lambda r: -abs(r["mean"]))
    return rows


def get_sector_trend(months=12):
    """Sector-avg composite over time, monthly snapshots — Tab 3 source."""
    df = read_sql(
        """
        SELECT pick_date, sector, ROUND(AVG(final_score), 3) AS avg_score,
               COUNT(*) AS n_stocks
        FROM daily_picks
        WHERE pick_date >= date('now', :since)
          AND sector IS NOT NULL
        GROUP BY pick_date, sector
        ORDER BY pick_date, sector
        """,
        params={"since": f"-{months * 31} days"},
    )
    return df.to_dict("records") if not df.empty else []


def get_pipeline_status(days=7):
    """Pipeline log for last N days — deduped to one row per (date, step) showing the FINAL state.

    The pipeline writes 2 rows per step: a 'RUNNING' row when the step starts, then a
    'SUCCESS' or 'FAILED' row when it finishes. We only want to show the latest state.
    Also: a step is only treated as RUNNING if its started_at is recent (last 5 minutes)
    AND there's no completion row for it — otherwise it's a stale RUNNING row from a
    previous run that crashed before writing its completion."""
    df = read_sql(
        """
        WITH ranked AS (
            SELECT id, run_date, step_name, status, rows_affected, duration_sec,
                   error_message, started_at, finished_at,
                   ROW_NUMBER() OVER (
                       PARTITION BY run_date, step_name
                       ORDER BY
                           CASE status
                               WHEN 'SUCCESS' THEN 1
                               WHEN 'FAILED'  THEN 2
                               WHEN 'RUNNING' THEN 3
                               ELSE 4
                           END,
                           id DESC
                   ) AS rn
            FROM pipeline_log
            WHERE run_date >= date('now', ?)
        )
        SELECT run_date, step_name, status, rows_affected, duration_sec,
               error_message, started_at, finished_at
        FROM ranked
        WHERE rn = 1
        ORDER BY started_at DESC
        """,
        params=[f"-{days} days"],
    )

    # Mark stale RUNNING rows as ABORTED — they're from runs that crashed mid-step
    if not df.empty:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(minutes=5)).isoformat()
        df.loc[(df["status"] == "RUNNING") & (df["started_at"] < cutoff), "status"] = "ABORTED"

    return df.to_dict("records")


def run_sql_query(query, max_rows=500):
    """Execute a read-only SQL query via the SQL console.
    Returns: {"columns": [...], "rows": [...], "error": str|None, "row_count": int}"""
    from db import safe_read_sql
    df, error = safe_read_sql(query, max_rows=max_rows)
    if error:
        return {"columns": [], "rows": [], "error": error, "row_count": 0}
    if df is None or df.empty:
        return {"columns": list(df.columns) if df is not None else [],
                "rows": [], "error": None, "row_count": 0}
    # Convert to JSON-safe values. Order matters: check NaN/None first because
    # numpy NaN is a float and would bypass the float branch otherwise.
    import math
    rows = []
    for record in df.to_dict("records"):
        clean = {}
        for k, v in record.items():
            if v is None:
                clean[k] = None
            elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                clean[k] = None
            elif isinstance(v, (int, float, str, bool)):
                clean[k] = v
            else:
                try:
                    if pd.isna(v):
                        clean[k] = None
                        continue
                except (TypeError, ValueError):
                    pass
                clean[k] = str(v)
        rows.append(clean)
    return {
        "columns": list(df.columns),
        "rows": rows,
        "error": None,
        "row_count": len(rows),
    }


@_ttl_cache(60)
def get_data_freshness():
    """Data health from db.data_health(). NaN floats are coerced to None so the
    payload is JSON-safe (Jinja's tojson preserves NaN literals which break
    JSON.parse in the browser)."""
    import math
    from db import data_health
    df = data_health()
    records = df.to_dict("records")
    for r in records:
        for k, v in r.items():
            if isinstance(v, float) and math.isnan(v):
                r[k] = None
    return records


@_ttl_cache(60)
def get_db_summary():
    """High-level health verdict for the system page header."""
    from db import db_summary
    return db_summary()


# ═══════════════════════════════════════════════════
# Model + Flow pages
# ═══════════════════════════════════════════════════

# v1 holds the C13b 18-period reconstructed validation. v2 doesn't have its
# own backtest yet — we surface the v1 file as the canonical signal map.
V1_BACKTEST_DIR = Path("/home/ubuntu/alpha-signal/data/backtest")


@_ttl_cache(60)
def get_model_overview():
    """Tier weight tables, signal validation, regime rules. Used by /model."""
    from config import SIGNAL_WEIGHTS, VIX_REGIMES, QUALITY_GATE, PORTFOLIO, TRANSACTION_COSTS_BPS

    # Per-tier signal weights — convert dict to ordered list of (signal, weight, pct).
    tiers = {}
    for tier, weights in SIGNAL_WEIGHTS.items():
        total = sum(weights.values()) or 1
        rows = sorted(weights.items(), key=lambda kv: -kv[1])
        tiers[tier] = [
            {"signal": s, "weight": w, "pct": round(100 * w / total, 1)}
            for s, w in rows
        ]

    # VIX regime → allocation table.
    regimes = []
    for name, (vlo, vhi, large, mid, small) in VIX_REGIMES.items():
        regimes.append({
            "regime": name,
            "vix_lo": vlo, "vix_hi": vhi,
            "alloc_large": large, "alloc_mid": mid, "alloc_small": small,
        })

    # Current regime so the page can highlight the active row.
    cur = read_sql("SELECT regime, vix_latest FROM regime_state WHERE id = 1")
    current_regime = cur.iloc[0].to_dict() if not cur.empty else {}

    # Validation t-stats from v1 backtest (PIT reconstruction, 18 periods).
    validation_csv = V1_BACKTEST_DIR / "reconstructed_ic_by_tier.csv"
    validation_rows = []
    validation_meta = {}
    if validation_csv.exists():
        try:
            v = pd.read_csv(validation_csv)
            validation_meta = {
                "periods": int(v["n_periods"].max()) if "n_periods" in v.columns else None,
                "source": "v1 reconstructed_ic_by_tier.csv",
            }
            for _, row in v.iterrows():
                validation_rows.append({
                    "signal": row.get("signal"),
                    "description": row.get("description"),
                    "cap_tier": row.get("cap_tier"),
                    "n_stocks_avg": _safe_int(row.get("n_stocks_avg")),
                    "mean_ic": _safe_float(row.get("mean_ic"), 4),
                    "icir": _safe_float(row.get("icir"), 3),
                    "t_stat": _safe_float(row.get("t_stat"), 2),
                    "verdict": row.get("verdict"),
                })
        except Exception:
            pass

    return {
        "tiers": tiers,
        "regimes": regimes,
        "current_regime": current_regime,
        "validation": {"rows": validation_rows, "meta": validation_meta},
        "quality_gate": QUALITY_GATE,
        "portfolio": PORTFOLIO,
        "transaction_costs_bps": TRANSACTION_COSTS_BPS,
        "backtest_roster": get_backtest_roster(),
    }


def get_backtest_roster():
    """Signal-level backtest readiness for /model.

    For each entry in db.BACKTEST_SIGNALS, enriches with live data:
      - C13b verdict + t-stat per cap_tier (from pit_ic_by_tier_v1)
      - Coverage snapshot (max history available, n_periods)

    Returns a dict with:
      signals: list of enriched signal rows
      response: info on the response variable (fwd_return_20d)
      pit_tables: summary of the PIT tables themselves
      summary: count by status (READY / PARTIAL / MISSING)
    """
    from db import BACKTEST_SIGNALS, get_db, read_sql

    # ── Existing PIT tables ──
    with get_db() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    has_pit_v1 = "daily_snapshots_pit_v1" in names
    has_pit_v2 = "daily_snapshots_pit" in names
    has_ic = "pit_ic_by_tier_v1" in names

    # ── IC table — group by signal for fast lookup ──
    ic_by_signal = {}
    if has_ic:
        ic_rows = read_sql("SELECT signal, cap_tier, t_stat, verdict, n_periods FROM pit_ic_by_tier_v1")
        for _, r in ic_rows.iterrows():
            sig = r["signal"]
            ic_by_signal.setdefault(sig, {})[r["cap_tier"]] = {
                "t_stat": _safe_float(r["t_stat"], 2),
                "verdict": r["verdict"],
                "n_periods": _safe_int(r["n_periods"]),
            }

    # ── Coverage per PIT column ──
    def _coverage(table, column):
        if not column or table not in names:
            return None
        try:
            df = read_sql(f"""
                SELECT COUNT(DISTINCT snapshot_date) AS n_dates,
                       MIN(snapshot_date) AS first_date,
                       MAX(snapshot_date) AS last_date,
                       AVG(CASE WHEN [{column}] IS NOT NULL THEN 1.0 ELSE 0 END) AS pct_filled
                FROM [{table}]
                WHERE [{column}] IS NOT NULL
            """)
            if df.empty or df.iloc[0]["n_dates"] == 0:
                return None
            r = df.iloc[0]
            return {
                "n_dates": _safe_int(r["n_dates"]),
                "first_date": r["first_date"],
                "last_date": r["last_date"],
                "pct_filled": round(float(r["pct_filled"]) * 100, 1) if pd.notna(r["pct_filled"]) else None,
            }
        except Exception:
            return None

    # ── Enrich each signal ──
    signals = []
    for s in BACKTEST_SIGNALS:
        cov_v1 = _coverage("daily_snapshots_pit_v1", s.get("pit_column_v1"))
        cov_v2 = _coverage("daily_snapshots_pit", s.get("pit_column_v2"))
        cov_ext = None
        if s.get("external_table"):
            ext_tbl = s["external_table"]
            if ext_tbl in names:
                try:
                    df = read_sql(f"SELECT COUNT(DISTINCT snapshot_date) AS n, MIN(snapshot_date) AS f, MAX(snapshot_date) AS l FROM [{ext_tbl}]")
                    if not df.empty and df.iloc[0]["n"] > 0:
                        cov_ext = {
                            "n_dates": _safe_int(df.iloc[0]["n"]),
                            "first_date": df.iloc[0]["f"],
                            "last_date": df.iloc[0]["l"],
                            "table": ext_tbl,
                        }
                except Exception:
                    pass

        # Pick the deeper coverage as the headline
        depths = []
        if cov_v1 and cov_v1["n_dates"]: depths.append(("v1 archive", cov_v1["n_dates"], cov_v1["first_date"], cov_v1["last_date"]))
        if cov_v2 and cov_v2["n_dates"]: depths.append(("v2 recompute", cov_v2["n_dates"], cov_v2["first_date"], cov_v2["last_date"]))
        if cov_ext:                       depths.append((cov_ext["table"], cov_ext["n_dates"], cov_ext["first_date"], cov_ext["last_date"]))

        max_dates = max((d[1] for d in depths), default=0)
        first_date = min((d[2] for d in depths), default=None)
        last_date = max((d[3] for d in depths), default=None)
        sources = ", ".join(d[0] for d in depths) or "—"

        signals.append({
            **s,
            "ic_by_tier": ic_by_signal.get(s["signal"], {}),
            "coverage_v1": cov_v1,
            "coverage_v2": cov_v2,
            "coverage_external": cov_ext,
            "max_dates": max_dates,
            "first_date": first_date,
            "last_date": last_date,
            "live_source": sources,
        })

    # ── Response variable ──
    response = {"variable": "fwd_return_20d", "computed_from": "stock_prices.close",
                "horizon_days": 20, "available_in": []}
    if has_pit_v1:
        try:
            df = read_sql("SELECT COUNT(*) AS n, MIN(snapshot_date) AS f, MAX(snapshot_date) AS l FROM daily_snapshots_pit_v1 WHERE fwd_return_20d IS NOT NULL")
            if not df.empty and df.iloc[0]["n"] > 0:
                response["available_in"].append({
                    "table": "daily_snapshots_pit_v1",
                    "rows": _safe_int(df.iloc[0]["n"]),
                    "first_date": df.iloc[0]["f"],
                    "last_date": df.iloc[0]["l"],
                    "note": "precomputed",
                })
        except Exception:
            pass
    response["available_in"].append({
        "table": "stock_prices",
        "rows": None,
        "note": "Compute on the fly: close on (eval_date + 20 trading days) / close on eval_date − 1",
    })

    # ── PIT table summary ──
    pit_tables = []
    for tbl in ["daily_snapshots_pit_v1", "daily_snapshots_pit", "pit_ic_by_tier_v1"]:
        if tbl not in names:
            continue
        try:
            r = read_sql(f"SELECT COUNT(*) AS rows FROM [{tbl}]").iloc[0]
            entry = {"table": tbl, "rows": _safe_int(r["rows"])}
            if tbl != "pit_ic_by_tier_v1":
                d = read_sql(f"SELECT COUNT(DISTINCT snapshot_date) AS n_dates, MIN(snapshot_date) AS f, MAX(snapshot_date) AS l, COUNT(DISTINCT sid) AS sids FROM [{tbl}]").iloc[0]
                entry.update({
                    "n_dates": _safe_int(d["n_dates"]),
                    "first_date": d["f"],
                    "last_date": d["l"],
                    "n_stocks": _safe_int(d["sids"]),
                })
            pit_tables.append(entry)
        except Exception:
            pass

    # ── Summary counts by status ──
    summary = {"READY": 0, "PARTIAL": 0, "MISSING": 0, "PROPOSED": 0, "BLOCKED": 0}
    for s in signals:
        summary[s["status"]] = summary.get(s["status"], 0) + 1

    # ── Grouped (by signal.group) for the page layout ──
    from collections import OrderedDict
    GROUP_ORDER = ["Value", "Quality", "Growth", "Momentum", "Ownership",
                   "Forensic", "Smart Money", "Consensus", "Sentiment",
                   "Regulatory", "Macro", "Composite"]
    grouped = OrderedDict((g, []) for g in GROUP_ORDER)
    for s in signals:
        g = s.get("group") or "Other"
        grouped.setdefault(g, []).append(s)

    return {
        "signals": signals,
        "groups": [{"name": g, "signals": gs} for g, gs in grouped.items() if gs],
        "response": response,
        "pit_tables": pit_tables,
        "summary": summary,
    }



def _safe_int(v):
    try:
        if pd.isna(v): return None
        return int(v)
    except Exception:
        return None


def _safe_float(v, places=2):
    try:
        if pd.isna(v): return None
        return round(float(v), places)
    except Exception:
        return None


def get_flow_overview():
    """Pipeline DAG: source → raw → signals → scoring → output. Used by /flow.

    Builds the layered flow from PIPELINE_STEPS with the latest pipeline_log
    status overlaid so the page shows what last ran and how it went.
    """
    from config import PIPELINE_STEPS

    # Latest status per step from pipeline_log.
    latest = read_sql("""
        SELECT step_name, status, rows_affected, finished_at, duration_sec, error_message
        FROM pipeline_log p
        WHERE p.id = (SELECT MAX(id) FROM pipeline_log
                      WHERE step_name = p.step_name)
    """)
    status_by_step = {r["step_name"]: r.to_dict() for _, r in latest.iterrows()}

    # Layer assignment based on the step's role.
    LAYERS = {
        "fetch_macro_market": "Sources",
        "fetch_macro_gov":    "Sources",
        "fetch_insider":      "Sources",
        "fetch_bulk_deals":   "Sources",
        "fetch_bhavcopy":     "Sources",
        "fetch_news":         "Sources",
        "universe_liveness":  "Sources",
        "signal_sentiment":   "Signals",
        "signal_insider":     "Signals",
        "signal_forensic":    "Signals",
        "signal_piotroski":   "Signals",
        "signal_accruals":    "Signals",
        "signal_consensus":   "Signals",
        "signal_promoter":    "Signals",
        "signal_smart_money": "Signals",
        "signal_macro":       "Signals",
        "signal_regulatory":  "Signals",
        "quality_gate":       "Scoring",
        "regime_update":      "Scoring",
        "screener":           "Scoring",
        "snapshot":           "Output",
        "diff_engine":        "Output",
        "dossier":            "Output",
        "email":              "Output",
    }
    LAYER_ORDER = ["Sources", "Signals", "Scoring", "Output"]

    layers = {ln: [] for ln in LAYER_ORDER}
    for step in PIPELINE_STEPS:
        name = step["name"]
        layer = LAYERS.get(name, "Other")
        if layer not in layers:
            layers[layer] = []
        last = status_by_step.get(name, {})
        layers[layer].append({
            "name": name,
            "module": step["module"],
            "function": step["function"],
            "table": step.get("table"),
            "source": step.get("source"),
            "frequency": step.get("frequency"),
            "critical": step.get("critical", False),
            "last_status": last.get("status"),
            "last_finished_at": last.get("finished_at"),
            "last_duration_sec": last.get("duration_sec"),
            "last_rows": last.get("rows_affected"),
            "last_error": last.get("error_message"),
        })

    layered = [{"name": ln, "steps": layers[ln]} for ln in LAYER_ORDER if layers[ln]]

    return {
        "layers": layered,
        "step_count": sum(len(v) for v in layers.values()),
        "failures": [
            s for layer in layered for s in layer["steps"]
            if s.get("last_status") in ("FAILED", "ABORTED")
        ],
    }


# ── Step rerun (UI button on /flow) ──────────────────────────────────────

def rerun_step(step_name: str) -> dict:
    """Spawn `python pipeline.py --step <name>` as a detached subprocess.

    Returns immediately so the HTTP request doesn't block. The pipeline writes
    its RUNNING/SUCCESS/FAILED rows to pipeline_log; the /flow page picks them
    up on its next auto-refresh.

    Refuses if (a) the step name isn't in PIPELINE_STEPS, or (b) a RUNNING row
    for that step is younger than 5 minutes (treat older as crashed / stale).
    """
    import subprocess
    import sys
    from datetime import datetime, timedelta
    from pathlib import Path
    from config import PIPELINE_STEPS, LOG_PATH

    valid = {s["name"] for s in PIPELINE_STEPS}
    if step_name not in valid:
        return {"ok": False, "error": f"unknown step: {step_name}"}

    recent = read_sql(
        """SELECT started_at FROM pipeline_log
           WHERE step_name = ? AND status = 'RUNNING'
           ORDER BY id DESC LIMIT 1""",
        params=[step_name],
    )
    if not recent.empty:
        try:
            started = datetime.fromisoformat(recent.iloc[0]["started_at"])
            if datetime.now() - started < timedelta(minutes=5):
                return {"ok": False, "error": f"{step_name} is already RUNNING"}
        except (ValueError, TypeError):
            pass

    project_root = Path(__file__).resolve().parent.parent
    rerun_log = project_root / "output" / "rerun.log"
    rerun_log.parent.mkdir(parents=True, exist_ok=True)
    log_fp = open(rerun_log, "ab")

    subprocess.Popen(
        [sys.executable, "pipeline.py", "--step", step_name],
        cwd=project_root,
        stdout=log_fp,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return {"ok": True, "step": step_name, "log": str(rerun_log)}


def get_data_health_scores(force=False):
    """Comprehensive per-table data health from health.compute_db_health().

    Pass force=True to bypass the 5-minute TTL cache.
    """
    from health import compute_db_health
    return compute_db_health(force=force)


# ═══════════════════════════════════════════════════
# Factor Health — sister to data-health, but per-factor
# ═══════════════════════════════════════════════════

def get_factor_health():
    """Return one row per registered factor with health metrics + grade.

    Per-factor metrics:
      - coverage_pct   : stocks with non-null score / eligible universe
      - freshness_days : days since last snapshot
      - best_abs_t     : best |t-stat| across cap-tiers from pit_ic_by_tier_v2
      - pit_ready      : factor has PIT helper + appears in daily_snapshots_pit
      - in_model       : marked production-ready
    Aggregated 0-100 grade with letter (A+/A/B/C/D/F).
    """
    from db import BACKTEST_SIGNALS, get_backtest_cadence as _bt_cadence

    # Track 3 extras list — all entries were duplicates of BACKTEST_SIGNALS
    # rows as of 2026-05-24 (Track 3 factors got promoted to BACKTEST_SIGNALS
    # when they shipped). Keeping them here double-counted each one and the
    # duplicate showed as F (cockpit looked up by score_table which sometimes
    # failed silently). Cleaned out; new Track 3 factors should be registered
    # directly in BACKTEST_SIGNALS with pit_column_v2.
    TRACK3_EXTRAS = []

    PROMOTION_T = 1.5

    # Universe baselines for coverage normalisation
    with get_db() as conn:
        uni_total = conn.execute(
            "SELECT COUNT(*) FROM stocks WHERE ticker IS NOT NULL"
        ).fetchone()[0]
        uni_excl_fin = conn.execute(
            "SELECT COUNT(*) FROM stocks WHERE ticker IS NOT NULL AND sector != 'Financials'"
        ).fetchone()[0]

        # Best |t| per signal (preferring v2_recompute over v1_archive when both exist)
        ic = read_sql(
            "SELECT signal, source, t_stat, n_periods FROM pit_ic_by_tier_v2"
        )
        if ic.empty:
            best_by_signal = {}
        else:
            ic = ic.assign(
                abst=lambda d: d["t_stat"].abs(),
                _src=lambda d: d["source"].map({"v2_recompute": 0, "v1_archive": 1}).fillna(2),
            )
            best_by_signal = (ic.sort_values(["_src", "abst"], ascending=[True, False])
                                .drop_duplicates("signal", keep="first")
                                .set_index("signal")
                                .to_dict("index"))

        # PIT columns actually populated in daily_snapshots_pit (latest snapshot).
        # NOTE: daily_snapshots_pit is the *backtest* reconstruction, only refreshed
        # when tools/reconstruct_pit.py runs (manually, periodically). Use this
        # only for PIT-readiness flag (does the column exist) — NOT for factor
        # freshness shown in the UI. For production freshness see latest_live below.
        try:
            latest_pit = conn.execute(
                "SELECT MAX(snapshot_date) FROM daily_snapshots_pit"
            ).fetchone()[0]
        except Exception:
            latest_pit = None

        # Live production snapshot — written by scoring/screener.py + output/snapshot.py
        # on every daily pipeline run. This is what "factor freshness" should reflect.
        try:
            latest_live = conn.execute(
                "SELECT MAX(snapshot_date) FROM daily_snapshots"
            ).fetchone()[0]
        except Exception:
            latest_live = None

        # Per-column coverage at THAT COLUMN's latest non-null date.
        # ADR 0022 split cadence (weekly behavioural vs monthly fundamentals).
        # The latest table-wide snapshot_date is a Friday with ONLY the 6 behavioural
        # columns populated — using it for coverage gave 0/2448 for every monthly
        # fundamental, falsely grading 56 factors as F (2026-05-24).
        # Now each column reports coverage at its own most-recent populated date.
        pit_coverage = {}
        pit_latest_for_col = {}
        if latest_pit:
            cols = [r[1] for r in conn.execute(
                "PRAGMA table_info(daily_snapshots_pit)"
            ).fetchall()]
            skip = {"sid", "snapshot_date", "cap_tier", "close_price",
                    "reconstructed_at", "fwd_return_20d"}
            for c in cols:
                if c in skip:
                    continue
                try:
                    row = conn.execute(
                        f"SELECT MAX(snapshot_date) AS d, COUNT(*) AS n "
                        f"FROM daily_snapshots_pit "
                        f"WHERE [{c}] IS NOT NULL "
                        f"  AND snapshot_date = ("
                        f"      SELECT MAX(snapshot_date) FROM daily_snapshots_pit WHERE [{c}] IS NOT NULL"
                        f"  )"
                    ).fetchone()
                    pit_coverage[c] = int(row[1] or 0)
                    pit_latest_for_col[c] = row[0]
                except Exception:
                    pit_coverage[c] = 0
                    pit_latest_for_col[c] = None

        # Per-table count + freshness for Track 3 score tables
        def _table_stats(table, col):
            try:
                latest_snap = conn.execute(
                    f"SELECT MAX(snapshot_date) FROM {table}"
                ).fetchone()[0]
                cnt = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE snapshot_date = ? AND [{col}] IS NOT NULL",
                    (latest_snap,)
                ).fetchone()[0] if latest_snap else 0
                return latest_snap, int(cnt)
            except Exception:
                return None, 0

    today = pd.Timestamp.today().date()

    def _grade(score):
        for thr, letter, color in [
            (90, "A+", "#2ecc71"),
            (80, "A",  "#27ae60"),
            (70, "B",  "#4d8eff"),
            (60, "C",  "#f1c40f"),
            (40, "D",  "#e67e22"),
        ]:
            if score >= thr:
                return letter, color
        return "F", "#e74c3c"

    def _build_row(name, signal, group, status, status_reason, in_model_flag,
                   coverage_n, eligible_n, latest_snap_str,
                   t_stat, n_periods, ic_source, pit_ready, track):
        # Coverage score: % of eligible universe scored
        if eligible_n > 0:
            coverage_pct = round(100 * coverage_n / eligible_n, 1)
            coverage_score = min(100, coverage_pct * 1.05)  # cap at 100
        else:
            coverage_pct, coverage_score = 0.0, 0

        # Freshness score
        freshness_days = None
        if latest_snap_str:
            try:
                latest_d = pd.to_datetime(latest_snap_str).date()
                freshness_days = (today - latest_d).days
            except Exception:
                pass
        if freshness_days is None:
            freshness_score = 0
        elif freshness_days <= 1:
            freshness_score = 100
        elif freshness_days <= 7:
            freshness_score = 90 - (freshness_days - 1) * 5  # 90 → 60
        elif freshness_days <= 30:
            freshness_score = max(0, 60 - (freshness_days - 7) * 2)
        else:
            freshness_score = 0

        # Backtest score — |t-stat| capped at 3.0, scaled to 0-100
        if t_stat is None or pd.isna(t_stat):
            backtest_score = 0
        else:
            abs_t = min(3.0, abs(float(t_stat)))
            backtest_score = round(100 * abs_t / 3.0, 1)

        # PIT-readiness — boolean, becomes 100 or 0
        pit_score = 100 if pit_ready else 0

        # In-model badge — adds a 100% to overall (already-validated factor)
        # but doesn't count if factor isn't built yet
        model_score = 100 if in_model_flag else (0 if status in ("PROPOSED", "BLOCKED") else 50)

        # Two separate grades — pre-2026-05-24 these were conflated into one
        # composite. Caused user confusion: a factor with perfect data but a
        # DROP-verdict backtest would show 'F' as if the data were broken.
        #
        # data_health: is the signal COMPUTING properly? (data side)
        # validation:  is the signal PREDICTIVE in backtest? (alpha side)
        data_health = (
            0.65 * coverage_score +   # was 0.35; renormalized after removing backtest
            0.25 * freshness_score +  # was 0.15
            0.10 * pit_score          # was 0.10 + 0.10 model_score (model = rotation, not health)
        )
        data_health = round(data_health, 1)
        data_grade, data_color = _grade(data_health)

        # Validation verdict — purely t-stat based, independent of data quality
        if t_stat is None or pd.isna(t_stat):
            validation_verdict, validation_color = "NONE", "var(--text-muted)"
        else:
            abs_t = abs(float(t_stat))
            if abs_t >= 2.5:
                validation_verdict, validation_color = "KEEP", "#2ecc71"
            elif abs_t >= 1.5:
                validation_verdict, validation_color = "WEAK", "#4d8eff"
            else:
                validation_verdict, validation_color = "DROP", "#e74c3c"

        # Back-compat: keep `overall` field but redirect callers to data_health
        overall = data_health
        letter, color = data_grade, data_color

        # Per-signal sparseness expectations (some signals are LOW-coverage by
        # nature — sparse data ≠ broken). Tagged here so the issue chip uses
        # an honest reason instead of "many stocks unscored" implying bug.
        SPARSE_BY_NATURE = {
            "bulk_deal_signal",
            "sentiment_7d", "news_volume",
            "insider_signal",      # only stocks with recent insider trades
        }
        # Sector-level signals: don't measure per-stock coverage
        SECTOR_LEVEL = {"regulatory_sector_signal", "macro_sector_signal"}
        # End-state composite — backtest-via-portfolio (Track 2.4), not as a factor
        COMPOSITE_NOT_FACTOR = {"screener_final_composite"}
        # Data-depth gapped signals — known short history (needs NSE archive backfill)
        DATA_DEPTH_LIMITED = {"fii_dii_cash_net", "fii_dii_fno_positioning"}

        issues = []
        if signal in SECTOR_LEVEL:
            issues.append("sector-level signal — per-stock coverage not applicable")
        elif signal in COMPOSITE_NOT_FACTOR:
            issues.append("composite output — backtest via portfolio (Track 2.4), not as factor")
        elif signal in DATA_DEPTH_LIMITED:
            issues.append("data depth limited — needs NSE archive backfill for backtest window")
        elif coverage_n == 0:
            issues.append("no scores in source table")
        elif coverage_pct < 40 and signal in SPARSE_BY_NATURE:
            issues.append(f"sparse by nature — {coverage_pct}% of universe has the underlying event")
        elif coverage_pct < 40:
            issues.append(f"coverage {coverage_pct}% — many stocks unscored")

        if freshness_days is not None and freshness_days > 7:
            issues.append(f"stale ({freshness_days}d)")
        if t_stat is None or pd.isna(t_stat):
            if signal not in COMPOSITE_NOT_FACTOR | DATA_DEPTH_LIMITED:
                issues.append("no backtest t-stat yet")
        elif abs(float(t_stat)) < 0.5:
            issues.append(f"t-stat near zero ({float(t_stat):+.2f})")
        if not pit_ready and signal not in COMPOSITE_NOT_FACTOR:
            issues.append("no PIT helper — can't be backtested")

        return {
            "name": name,
            "signal": signal,
            "group": group,
            "track": track,
            "status": status,
            "status_reason": status_reason,
            "in_model": in_model_flag,
            "coverage_n": coverage_n,
            "eligible_n": eligible_n,
            "coverage_pct": coverage_pct,
            "freshness_days": freshness_days,
            "latest_snap": latest_snap_str,
            "t_stat": float(t_stat) if t_stat is not None and not pd.isna(t_stat) else None,
            "n_periods": int(n_periods) if n_periods is not None and not pd.isna(n_periods) else None,
            "ic_source": ic_source,
            "pit_ready": pit_ready,
            "scores": {
                "coverage": int(round(coverage_score)),
                "freshness": int(round(freshness_score)),
                "backtest": int(round(backtest_score)),
                "pit": int(pit_score),
                "model": int(model_score),
            },
            "overall": overall,         # = data_health (back-compat alias)
            "grade": letter,            # = data_grade (back-compat alias)
            "grade_color": color,
            "data_health": data_health,
            "data_grade": data_grade,
            "data_grade_color": data_color,
            "validation_verdict": validation_verdict,
            "validation_color": validation_color,
            "backtest_cadence": _bt_cadence(signal),
            "issues": issues,
        }

    out = []

    # ── BACKTEST_SIGNALS (legacy + already-registered) ──
    for spec in BACKTEST_SIGNALS:
        signal = spec["signal"]
        ic_row = best_by_signal.get(signal, {})
        t_stat = ic_row.get("t_stat")
        v2_col = spec.get("pit_column_v2")
        coverage_n = pit_coverage.get(v2_col, 0) if v2_col else 0
        # Freshness: prefer the column's own latest non-null date (handles
        # weekly+monthly cadence correctly). Fall back to global latest_live
        # only when the column has never been populated.
        col_latest = pit_latest_for_col.get(v2_col) if v2_col else None
        eligible = uni_total  # legacy signals span the whole universe
        in_model = (spec.get("status") == "READY"
                    and t_stat is not None and abs(t_stat) >= PROMOTION_T)
        out.append(_build_row(
            name=spec["label"],
            signal=signal,
            group=spec.get("group", "—"),
            status=spec.get("status"),
            status_reason=(spec.get("status_reason") or "")[:200],
            in_model_flag=in_model,
            coverage_n=coverage_n,
            eligible_n=eligible,
            latest_snap_str=col_latest or latest_live,
            t_stat=t_stat,
            n_periods=ic_row.get("n_periods"),
            ic_source=ic_row.get("source", "—"),
            pit_ready=bool(v2_col),
            track="legacy",
        ))

    # ── Track 3 extras ──
    for spec in TRACK3_EXTRAS:
        signal = spec["signal"]
        ic_row = best_by_signal.get(signal, {})
        t_stat = ic_row.get("t_stat")
        # Coverage: prefer per-snapshot table count over PIT column
        latest_snap_str, coverage_n = _table_stats(
            spec["score_table"], spec["score_col"]
        )
        # Eligible universe: most Track 3 factors exclude financials
        eligible = uni_excl_fin
        in_model = (t_stat is not None and abs(t_stat) >= PROMOTION_T)
        out.append(_build_row(
            name=spec["label"],
            signal=signal,
            group=spec.get("group", "Track 3"),
            status="READY",
            status_reason="",
            in_model_flag=in_model,
            coverage_n=coverage_n,
            eligible_n=eligible,
            latest_snap_str=latest_snap_str,
            t_stat=t_stat,
            n_periods=ic_row.get("n_periods"),
            ic_source=ic_row.get("source", "—"),
            pit_ready=signal in pit_coverage,  # PIT helper added if column exists
            track="f-track",
        ))

    # Aggregate summary — two distinct distributions
    n = len(out)
    by_data_grade = {}
    by_validation = {}
    for r in out:
        by_data_grade[r["data_grade"]] = by_data_grade.get(r["data_grade"], 0) + 1
        by_validation[r["validation_verdict"]] = by_validation.get(r["validation_verdict"], 0) + 1
    avg_data_health = round(sum(r["data_health"] for r in out) / n, 1) if n else 0
    summary = {
        "total": n,
        "in_model": sum(1 for r in out if r["in_model"]),
        "in_library": sum(1 for r in out if not r["in_model"] and r["coverage_n"] > 0),
        "not_built": sum(1 for r in out if r["coverage_n"] == 0),
        "with_t_stat": sum(1 for r in out if r["t_stat"] is not None),
        "pit_ready": sum(1 for r in out if r["pit_ready"]),
        # Back-compat aliases (template still reads these)
        "avg_overall": avg_data_health,
        "grade_dist": by_data_grade,
        # New, clearer fields
        "avg_data_health": avg_data_health,
        "data_grade_dist": by_data_grade,
        "validation_dist": by_validation,
    }

    return {"summary": summary, "factors": out}


# ═══════════════════════════════════════════════════
# Command Centre — overview of plans, factors, data layer, pending actions
# ═══════════════════════════════════════════════════

FACTOR_COUNT_TARGET = 100


def _read_md_section(md_path: Path, header: str) -> str | None:
    """Return the body of an H2 section by header text, or None."""
    if not md_path.exists():
        return None
    text = md_path.read_text()
    needle = f"\n## {header}"
    start = text.find(needle)
    if start < 0:
        return None
    body_start = start + len(needle)
    end = text.find("\n## ", body_start)
    return text[body_start:end if end > 0 else len(text)].strip()


def _parse_plan_frontmatter(md_path: Path) -> dict:
    """Parse YAML-ish frontmatter at top of a plan or ADR markdown file."""
    text = md_path.read_text()
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        if ":" in line and not line.startswith(" "):
            key, _, val = line.partition(":")
            fm[key.strip().lower()] = val.strip()
    return fm


@_ttl_cache(60)
def get_command_centre():
    """Assemble the command-centre payload — plans, factor library, data layer,
    pending actions. Server-rendered; no live polling."""
    project_root = Path(__file__).resolve().parent.parent

    # ── Plans ────────────────────────────────────────────────
    plans = []
    for p in sorted((project_root / "docs" / "plans").glob("000*.md")):
        fm = _parse_plan_frontmatter(p)
        title_match = None
        for line in p.read_text().splitlines():
            if line.startswith("# "):
                title_match = line[2:].strip()
                break
        plans.append({
            "file": p.name,
            "title": title_match or p.stem,
            "status": fm.get("status") or "—",
            "last_updated": fm.get("last updated") or "—",
            "implementation": fm.get("implementation") or "",
        })

    # ── ADRs ─────────────────────────────────────────────────
    adrs = []
    for a in sorted((project_root / "docs" / "decisions").glob("0*.md")):
        first_lines = a.read_text().splitlines()[:10]
        title = next((l[2:].strip() for l in first_lines if l.startswith("# ")), a.stem)
        status_line = next((l for l in first_lines if l.startswith("**Status:")), "")
        date_line = next((l for l in first_lines if l.startswith("**Date:")), "")
        adrs.append({
            "file": a.name,
            "title": title,
            "status": status_line.replace("**Status:**", "").strip().rstrip("*").strip() or "—",
            "date": date_line.replace("**Date:**", "").strip().rstrip("*").strip() or "—",
        })

    # ── Factor library ───────────────────────────────────────
    # Source of truth: BACKTEST_SIGNALS in db.py (42 v1-derived signals) plus
    # Track 3 additions (ROIC, FCF Yield, …). Each factor's t-stat is looked
    # up from pit_ic_by_tier_v2 by `signal` column.
    from db import BACKTEST_SIGNALS

    # Track 3 factors not yet in BACKTEST_SIGNALS (no PIT helper yet, so no
    # entry in the v1-shaped registry). Same fields shape, so they render
    # uniformly.
    TRACK3_EXTRAS = [
        {
            "signal": "roic",
            "label": "ROIC (Track 3)",
            "group": "Track 3 / Quality",
            "status": "READY",
            "status_reason": "",
            "track": "f-track",
            "score_table": "roic_scores",
        },
        {
            "signal": "fcf_yield",
            "label": "FCF Yield (Track 3)",
            "group": "Track 3 / Cash",
            "status": "READY",
            "status_reason": "",
            "track": "f-track",
            "score_table": "fcf_yield_scores",
        },
    ]

    # Promotion criterion: if pit_ic_by_tier_v2 has a row with |t| >= 1.5 in
    # any cap-tier (preferring v2_recompute over v1_archive when both exist),
    # the factor is "in model"; otherwise "library".
    PROMOTION_T_THRESHOLD = 1.5

    factors = []
    with get_db() as conn:
        try:
            ic = read_sql(
                "SELECT signal, cap_tier, t_stat, mean_ic, source, n_periods "
                "FROM pit_ic_by_tier_v2"
            )
            # Best |t| across cap_tier per signal — prefer v2_recompute over v1_archive.
            ic = ic.assign(
                abst=lambda d: d["t_stat"].abs(),
                src_priority=lambda d: d["source"].map(
                    {"v2_recompute": 0, "v1_archive": 1}
                ).fillna(2),
            )
            best = (
                ic.sort_values(["src_priority", "abst"], ascending=[True, False])
                  .drop_duplicates("signal", keep="first")
                  .set_index("signal")
                  .to_dict("index")
            )
        except Exception:
            best = {}

        # Score-table count helper (cached per table in this call)
        score_table_counts: dict[str, int] = {}

        def _stocks_in(table_name: str | None) -> int:
            if not table_name:
                return 0
            if table_name in score_table_counts:
                return score_table_counts[table_name]
            try:
                row = conn.execute(
                    f"SELECT COUNT(DISTINCT sid) FROM {table_name}"
                ).fetchone()
                n = int(row[0]) if row and row[0] is not None else 0
            except Exception:
                n = 0
            score_table_counts[table_name] = n
            return n

        # ── BACKTEST_SIGNALS (42 v1-derived) ──
        for spec in BACKTEST_SIGNALS:
            signal = spec["signal"]
            ic_row = best.get(signal, {})
            t_stat = ic_row.get("t_stat")
            n_periods = ic_row.get("n_periods")
            ic_source = ic_row.get("source")

            # Coverage: prefer the v2 PIT column count over generic table counts
            v2_col = spec.get("pit_column_v2")
            stocks = 0
            if v2_col:
                try:
                    row = conn.execute(
                        f"SELECT COUNT(DISTINCT sid) FROM daily_snapshots_pit "
                        f"WHERE {v2_col} IS NOT NULL"
                    ).fetchone()
                    stocks = int(row[0]) if row and row[0] is not None else 0
                except Exception:
                    stocks = 0

            in_production = (
                spec["status"] == "READY"
                and t_stat is not None
                and abs(t_stat) >= PROMOTION_T_THRESHOLD
            )

            factors.append({
                "name": spec["label"],
                "signal": signal,
                "group": spec.get("group", "—"),
                "status": spec.get("status"),
                "status_reason": spec.get("status_reason", "")[:240],
                "stocks": stocks,
                "t_stat": float(t_stat) if t_stat is not None else None,
                "n_periods": int(n_periods) if n_periods is not None else None,
                "ic_source": ic_source or "—",
                "in_production": in_production,
                "track": "legacy",
                "table": v2_col or "—",
            })

        # ── Track 3 extras (ROIC, FCF Yield, …) ──
        for spec in TRACK3_EXTRAS:
            signal = spec["signal"]
            ic_row = best.get(signal, {})
            t_stat = ic_row.get("t_stat")
            stocks = _stocks_in(spec.get("score_table"))
            in_production = (
                t_stat is not None and abs(t_stat) >= PROMOTION_T_THRESHOLD
            )
            factors.append({
                "name": spec["label"],
                "signal": signal,
                "group": spec.get("group", "Track 3"),
                "status": spec.get("status"),
                "status_reason": spec.get("status_reason", ""),
                "stocks": stocks,
                "t_stat": float(t_stat) if t_stat is not None else None,
                "n_periods": int(ic_row["n_periods"]) if ic_row.get("n_periods") is not None else None,
                "ic_source": ic_row.get("source") or "—",
                "in_production": in_production,
                "track": "f-track",
                "table": spec.get("score_table"),
            })

    # "Built" = has scores OR has a t-stat. "In model" = passes promotion.
    n_built = len([f for f in factors if f["stocks"] > 0 or f["t_stat"] is not None])
    n_in_prod = len([f for f in factors if f["in_production"]])
    n_in_library = n_built - n_in_prod

    # ── Data layer (lightweight, for the architecture flow header stats) ──
    data_layer = {}
    with get_db() as conn:
        for tbl in [
            "fundamentals_screener", "stock_prices", "quarterly_income",
            "annual_balance_sheet", "annual_cash_flow", "shareholding",
            "insider_trades", "bulk_deals", "regulatory_events", "news_articles",
        ]:
            try:
                cnt = conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
                stocks_cnt = None
                try:
                    stocks_cnt = conn.execute(
                        f"SELECT COUNT(DISTINCT sid) FROM {tbl}"
                    ).fetchone()[0]
                except Exception:
                    pass
                data_layer[tbl] = {
                    "rows": int(cnt),
                    "stocks": int(stocks_cnt) if stocks_cnt is not None else None,
                }
            except Exception:
                data_layer[tbl] = {"rows": 0, "stocks": None}
        try:
            tp = conn.execute(
                "SELECT COUNT(DISTINCT sid) FROM fundamentals_screener "
                "WHERE line_item='Trade Payables'"
            ).fetchone()[0]
            data_layer["fundamentals_screener"]["trade_payables_stocks"] = int(tp)
        except Exception:
            pass

    # ── Full data model (every table — schema, columns, row counts, source) ──
    # Logical grouping for the brain-map. Each table gets PRAGMA table_info.
    DATA_MODEL_GROUPS = [
        ("Universe & Reference", [
            ("stocks",                 "NSE/BSE master + Tickertape SID, sector, cap_tier, market_cap_cr"),
            ("nse_index_history",      "Nifty 50/100/500/Smallcap + smart-beta indices — daily OHLCV"),
            ("vix_history",            "India VIX — daily, regime input"),
        ]),
        ("Prices & Adjustments", [
            ("stock_prices",           "Daily OHLCV — NSE bhavcopy + nselib"),
            ("corporate_adjustments",  "Pre-multiplied split+bonus+dividend factors per (sid, ex_date) — ADR 0010"),
            ("corporate_actions",      "Raw corporate events (splits, bonuses, dividends, buybacks, M&A) from NSE"),
        ]),
        ("Fundamentals", [
            ("fundamentals_screener",  "Track 3 long-format — Screener Premium xlsx + schedules JSON. PK (sid, period_end, period_type, line_item)"),
            ("quarterly_income",       "Tickertape — quarterly income (legacy wide format)"),
            ("annual_balance_sheet",   "Tickertape — annual balance sheet"),
            ("annual_cash_flow",       "Tickertape — annual cash flow"),
            ("shareholding",           "Tickertape — quarterly promoter / FII / DII / public splits"),
        ]),
        ("Ownership Flows", [
            ("insider_trades",         "NSE PIT API — secAcq/secVal are the real values, not buy/sell qty"),
            ("bulk_deals",             "NSE bulk-deals daily snapshot — append-only, today-only API"),
            ("fii_dii_cash_flow",      "FII/DII cash market positioning — daily"),
            ("fii_dii_positioning",    "FII/DII F&O + cash positioning — by participant type"),
            ("short_selling_data",     "NSE short-selling — F&O-eligible names only"),
        ]),
        ("Analyst Forecasts", [
            ("analyst_consensus",          "Current snapshot — yfinance-sourced price_target + Tickertape-sourced eps/revenue. PK=sid, daily refresh."),
            ("analyst_consensus_snapshots", "Monthly history of yfinance aggregate — drives pt_revision signals. PK=(sid, snapshot_date, source). New 2026-05-22."),
            ("forecast_history",           "Tickertape year-end PT/EPS/Revenue snapshots (~1/yr per stock 2022-2025). Daily 'today' entries filtered at ingest."),
        ]),
        ("Events & News", [
            ("regulatory_events",      "BSE/NSE filings — raw + classifier_status (6 terminal states)"),
            ("regulatory_signals",     "Sector-level tailwind/headwind from AI-classified events (5,687 of 16,523 classified)"),
            ("news_articles",          "Google News RSS — title+source+published_at"),
            ("news_article_stocks",    "M2M join — article ↔ stock"),
            ("earnings_calendar",      "Upcoming filings schedule — used for daily-incremental Screener pulls"),
        ]),
        ("Macro & Sectors", [
            ("macro_indicators",       "Active per-indicator macro values"),
            ("macro_history",          "Long-format historical series — per-indicator monthly observations"),
            ("macro_indicator_meta",   "Indicator name → unit, transform, source registry"),
            ("macro_sector_map",       "Indicator → sector weights (30 mappings)"),
            ("macro_sector_signals",   "Per-sector macro signal output (today)"),
            ("macro_sector_signals_pit", "PIT version — 11 sectors × 7 dates"),
        ]),
        ("Surveillance", [
            ("surveillance_flags",     "ASM (LT/ST), GSM, F&O ban — append-only daily snapshot"),
        ]),
        ("Mutual Fund NAV", [
            ("mf_schemes",             "AMFI scheme master — 4,048 schemes"),
            ("mf_nav_history",         "Per-scheme NAV history from mfapi.in — ~13 yr daily"),
        ]),
        ("Computed Signals (per-stock)", [
            ("piotroski_scores",       "F-Score 0-9 — quality"),
            ("forensic_scores",        "M-Score (earnings manipulation) + Z-Score (distress)"),
            ("accruals_scores",        "CF + BS accruals + EPS CV + composite"),
            ("consensus_signals",      "PT upside, PT revision YoY, EPS revision YoY, combined"),
            ("promoter_signals",       "Promoter QoQ + 4q trend"),
            ("smart_money_scores",     "Bulk-deal + delivery anomaly composite"),
            ("insider_signals",        "Insider trades signal — 29 monthly snapshots"),
            ("sentiment_scores",       "News-based sentiment proxy — 7d volume + (FinBERT pending plan-0002)"),
            ("roic_scores",            "Track 3 ROIC — 1,501 stocks (NOPAT/IC, 3yr median, IC≥₹50cr)"),
            ("fcf_yield_scores",       "Track 3 FCF Yield — 1,195 stocks"),
        ]),
        ("Daily Output", [
            ("daily_picks",            "Top picks per cap-tier per snapshot_date — what the screener emits"),
            ("daily_changes",          "Day-over-day diff in picks (entered/exited)"),
            ("daily_snapshots",        "Today-only snapshot of all factors per stock — current cross-section"),
        ]),
        ("PIT Snapshots & Backtest", [
            ("daily_snapshots_pit",    "v2 PIT archive — 7 monthly dates × 26 signals × 2,448 stocks"),
            ("daily_snapshots_pit_v1", "Frozen v1 archive — port-correctness reference per ADR 0012"),
            ("pit_ic_by_tier_v1",      "v1 backtest IC table (older, for cross-checking)"),
            ("pit_ic_by_tier_v2",      "Backtest output — IC, t-stat, n_periods per (signal, cap_tier, source)"),
            ("pit_reconstruction_log", "Run-log of tools.reconstruct_pit invocations"),
        ]),
        ("Pipeline & Logging", [
            ("pipeline_log",           "Per-step run log (started_at, status, rows, duration)"),
            ("regime_state",           "Daily regime classifier output (Bullish/Neutral/Bearish)"),
            ("screener_pull_errors",   "Track 3 scrape audit trail — error_type ∈ {auth, http, parse, thin, empty, fetch}"),
        ]),
    ]
    data_model = []
    with get_db() as conn:
        # Get list of actually-existing tables once
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}

        for group_name, table_specs in DATA_MODEL_GROUPS:
            group_tables = []
            for tbl, desc in table_specs:
                if tbl not in existing:
                    continue
                # Columns
                try:
                    cols = [
                        {
                            "name": r[1], "type": r[2], "notnull": bool(r[3]),
                            "pk": int(r[5]),
                        }
                        for r in conn.execute(f"PRAGMA table_info({tbl})").fetchall()
                    ]
                except Exception:
                    cols = []
                # Indexes (skip auto-pk indexes)
                try:
                    idxs = [
                        r[1] for r in conn.execute(f"PRAGMA index_list({tbl})").fetchall()
                        if not r[1].startswith("sqlite_autoindex")
                    ]
                except Exception:
                    idxs = []
                # Foreign keys
                try:
                    fks = [
                        {"col": r[3], "ref_table": r[2], "ref_col": r[4]}
                        for r in conn.execute(f"PRAGMA foreign_key_list({tbl})").fetchall()
                    ]
                except Exception:
                    fks = []
                # Row count
                try:
                    rows = int(conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0])
                except Exception:
                    rows = 0
                # Distinct stocks if `sid` column present
                stocks = None
                if any(c["name"] == "sid" for c in cols) and rows > 0:
                    try:
                        stocks = int(conn.execute(
                            f"SELECT COUNT(DISTINCT sid) FROM {tbl}"
                        ).fetchone()[0])
                    except Exception:
                        pass
                # Latest timestamp if a candidate column exists
                latest = None
                for ts_col in ("fetched_at", "snapshot_date", "attempted_at",
                                "started_at", "created_at", "date", "ex_date"):
                    if any(c["name"] == ts_col for c in cols):
                        try:
                            r = conn.execute(
                                f"SELECT MAX({ts_col}) FROM {tbl}"
                            ).fetchone()
                            if r and r[0]:
                                latest = str(r[0])[:19]
                                break
                        except Exception:
                            pass

                pk_cols = [c["name"] for c in cols if c["pk"]]
                group_tables.append({
                    "name": tbl,
                    "desc": desc,
                    "cols": cols,
                    "n_cols": len(cols),
                    "pk": pk_cols,
                    "fks": fks,
                    "indexes": idxs,
                    "rows": rows,
                    "stocks": stocks,
                    "latest": latest,
                    "group": group_name,
                })
            if group_tables:
                data_model.append({
                    "name": group_name,
                    "tables": group_tables,
                    "n_tables": len(group_tables),
                    "n_rows": sum(t["rows"] for t in group_tables),
                })

    # ── To Do (synthesized — top-level "what needs to happen") ──
    todos = []

    # Schedules scrape progress
    try:
        import subprocess
        is_running = bool(subprocess.run(
            ["pgrep", "-f", "screener_schedules"], capture_output=True
        ).stdout.strip())
    except Exception:
        is_running = False
    tp_n = data_layer.get("fundamentals_screener", {}).get("trade_payables_stocks", 0)
    if is_running:
        todos.append({
            "title": "F1.2 universe scrape running",
            "detail": f"Trade Payables landed for {tp_n} stocks so far (target ~2,000). Detached process — claude won't notify. Check `ps -ef | grep screener_schedules`.",
            "status": "in-flight",
        })
    elif tp_n < 1500:
        todos.append({
            "title": "F1.2 universe scrape needs to finish or restart",
            "detail": f"Only {tp_n} stocks have Trade Payables; expected ~1,800–2,000. May have stopped early — check screener_pull_errors.",
            "status": "blocked",
        })

    # Factors built without PIT helpers (can't be backtested)
    f_track_no_pit = [
        f for f in factors
        if f["track"] == "f-track" and f["t_stat"] is None and f["stocks"] > 0
    ]
    for f in f_track_no_pit:
        todos.append({
            "title": f"Add PIT helper for {f['name']}",
            "detail": f"Has {f['stocks']} stocks scored today but no `pit_{f['signal']}(sid, eval_date)` in tools/reconstruct_pit.py — can't be backtested. Pair the module with its PIT version on next ship.",
            "status": "todo",
        })

    # Factor count progress
    todos.append({
        "title": f"Build remaining {FACTOR_COUNT_TARGET - n_built} factors toward 100",
        "detail": f"At {n_built}/{FACTOR_COUNT_TARGET} ({round(100*n_built/FACTOR_COUNT_TARGET)}%). Next batch (data already in fundamentals_screener): cash_conversion_cycle, gross_margin_trend, roiic, working_capital_intensity, debt_structure, asset_tangibility. ~30 min each from the ROIC/FCF Yield template.",
        "status": "todo",
    })

    # Operational debt
    todos.append({
        "title": "Wire screener_pull + screener_schedules into weekly cron",
        "detail": "Both currently manual-run only. Schedule for Sunday 02:00 IST (clear of daily 03:30 UTC pipeline). Cookie-health probe on cockpit /system. Use earnings_calendar for daily incremental.",
        "status": "todo",
    })

    # Library surface
    todos.append({
        "title": "Build factor-library exploration surface",
        "detail": "Once 30+ factors exist, add a per-factor drill-down (IC by tier, distribution, top/bottom names). Notebook first; cockpit page after.",
        "status": "later",
    })

    # market_cap_cr rename
    todos.append({
        "title": "stocks.market_cap_cr is misnamed (actually rupees, not crores)",
        "detail": "RELI shows 1.83e13 in the column (= ₹18.3L cr in rupees). Fixed locally in signals/fcf_yield.py with /1e7 divisor. Other consumers (cockpit/api.py, output/email_sender.py) treat the value as-is and could be displaying wrong units. Defer until a slow session.",
        "status": "later",
    })

    # ── Pending actions + open questions from HANDOFF ────────
    handoff = project_root / "HANDOFF.md"
    next_actions_md = _read_md_section(handoff, "Next 3 actions (in order, concrete)") or ""
    open_questions_md = _read_md_section(handoff, "Open questions for me (decisions you need to make)") or ""
    where_md = _read_md_section(handoff, "Where I am") or ""

    # ── Recent commits ───────────────────────────────────────
    import subprocess
    try:
        log_out = subprocess.check_output(
            ["git", "log", "--pretty=format:%h|%s|%cr", "-15"],
            cwd=str(project_root), text=True, timeout=5,
        )
        commits = [
            dict(zip(["sha", "subject", "when"], line.split("|", 2)))
            for line in log_out.splitlines() if line
        ]
    except Exception:
        commits = []

    # ── Architecture flow (mother plan, layered) ─────────────
    # 4 vertical stages, each expandable. Counts pulled from real data so
    # the diagram updates as the system grows.
    factors_by_group = {}
    for f in factors:
        factors_by_group.setdefault(f["group"], []).append(f)

    arch_data_layer = [
        {
            "name": "Market data",
            "summary": f"{data_layer.get('stock_prices',{}).get('rows', 0):,} daily price rows · {data_layer.get('stock_prices',{}).get('stocks', 0):,} stocks",
            "items": [
                ("stock_prices", "Daily OHLCV — NSE bhavcopy + nselib"),
                ("daily_snapshots_pit", "PIT-reconstructed signal snapshots — 7 monthly dates"),
                ("daily_snapshots_pit_v1", "Frozen v1 archive — 36 monthly periods, port-correctness reference"),
            ],
        },
        {
            "name": "Fundamentals",
            "summary": f"{data_layer.get('fundamentals_screener',{}).get('rows', 0):,} long-format rows · {data_layer.get('quarterly_income',{}).get('rows', 0):,} quarterly · 2 sources",
            "items": [
                ("fundamentals_screener", "Screener Premium — 36 annual line items, 9 quarterly. Long-format (Track 3)"),
                ("quarterly_income", "Tickertape — quarterly income statement (legacy wide format)"),
                ("annual_balance_sheet", "Tickertape — annual balance sheet"),
                ("annual_cash_flow", "Tickertape — annual cash flow"),
                ("shareholding", "Tickertape — quarterly promoter / FII / DII / public splits"),
            ],
        },
        {
            "name": "Ownership & flows",
            "summary": f"insider trades, bulk deals, FII/DII positioning",
            "items": [
                ("insider_trades", f"NSE PIT API — {data_layer.get('insider_trades',{}).get('rows', 0):,} rows"),
                ("bulk_deals", f"NSE bulk-deals daily snapshot — {data_layer.get('bulk_deals',{}).get('rows', 0):,} rows"),
                ("fii_dii_cash", "FII/DII cash market positioning — daily"),
                ("fii_fno_positioning", "FII F&O positioning — daily"),
                ("short_selling_data", "NSE short-selling — daily, F&O-eligible names"),
            ],
        },
        {
            "name": "Events & news",
            "summary": f"{data_layer.get('regulatory_events',{}).get('rows', 0):,} regulatory events · {data_layer.get('news_articles',{}).get('rows', 0):,} news articles",
            "items": [
                ("regulatory_events", "BSE/NSE filings — AI-classified into per-sector signals"),
                ("regulatory_signals", "Sector-level regulatory tailwind/headwind (5,687 of 16,523 classified)"),
                ("corporate_actions", "Splits, bonuses, dividends — composed at signal-compute time per ADR 0010"),
                ("news_articles", "Google News RSS — 100/query, 2026-03+ dense"),
                ("earnings_calendar", "Upcoming filings schedule"),
            ],
        },
        {
            "name": "Macro",
            "summary": "Inflation, GDP, sector indicators — government & RBI",
            "items": [
                ("macro_indicators", "data.gov.in core sector index, RBI rates, monthly"),
                ("vix_history", "India VIX — regime classifier input"),
                ("benchmark_indices", "Nifty 50/100/500/Smallcap/Midcap + smart-beta indices"),
            ],
        },
    ]

    # Signals — group → factor list with counts
    arch_signals = []
    canonical_order = [
        "Value", "Quality", "Growth", "Momentum", "Ownership",
        "Smart Money", "Consensus", "Forensic", "Sentiment",
        "Regulatory", "Macro", "Composite",
        "Track 3 / Quality", "Track 3 / Cash",
    ]
    for grp in canonical_order:
        if grp in factors_by_group:
            in_group = factors_by_group[grp]
            in_model = sum(1 for f in in_group if f["in_production"])
            arch_signals.append({
                "name": grp,
                "n_total": len(in_group),
                "n_model": in_model,
                "items": [
                    (f["name"], f"{f['t_stat']:.2f}" if f["t_stat"] is not None else "—",
                     "model" if f["in_production"] else "library")
                    for f in in_group
                ],
            })

    arch_model = [
        {
            "name": "Quality gate",
            "summary": "Excludes F-Score ≤ 1, distress flags, dilution",
            "items": [
                ("scoring/quality_gate.py", "Hard exclusions before scoring"),
                ("Penalty: low Piotroski (F=2-3) → −0.15", "Soft penalty"),
                ("Penalty: distress (Z<1.81) → fixed", "Forensic penalty"),
            ],
        },
        {
            "name": "Cap-tier composite",
            "summary": "Within-tier weighted sum of validated signals (cf C13b rubric)",
            "items": [
                ("LARGE: 7 weighted signals", "consensus 1.0× / piotroski 0.1× / EY 0.5× ..."),
                ("MID: 7 weighted signals", "consensus 0.5× / piotroski 0.2× / EY 0.5× ..."),
                ("SMALL: 7 weighted signals", "EY 1.0× / piotroski 0.15× / promoter 1.0× ..."),
                ("Weight tiers", "|t|≥2.5 → 1.0× / 1.5-2.5 → 0.5× / 0.5-1.5 → 0.2× / <0.5 → 0×"),
            ],
        },
        {
            "name": "Regime overlay",
            "summary": "VIX-based + macro-sector overlays",
            "items": [
                ("scoring/regime.py", "Bullish / Neutral / Bearish from VIX + breadth"),
                ("Macro tilts", "Sector tailwind/headwind from regulatory + macro signals"),
            ],
        },
        {
            "name": "Personal factor library",
            "summary": f"{n_built - n_in_prod} factors built but not voting (yet)",
            "items": [
                ("Promotion criterion", "|t|≥1.5 in any tier (preferring v2_recompute)"),
                ("ADR 0012", "v2 archive refreshes after every signal-side fix"),
                ("Today: ROIC + FCF Yield", "Track 3 factors awaiting PIT helpers + backtest"),
            ],
        },
    ]

    arch_picks = [
        {
            "name": "Daily morning brief",
            "summary": "Top picks per cap tier with regime context, dossiers",
            "items": [
                ("/", "Cockpit Morning Brief route"),
                ("Top 5 LARGE / MID / SMALL", "Ranked by composite, gated by quality_gate"),
                ("Regime banner", "Bullish/Neutral/Bearish header"),
            ],
        },
        {
            "name": "Email digest",
            "summary": "Daily picks emailed via output/email_sender.py",
            "items": [
                ("output/email_sender.py", "Templated HTML email of top picks + commentary"),
            ],
        },
        {
            "name": "Cockpit explorer",
            "summary": "Per-stock dossiers, signals, action queue",
            "items": [
                ("/explorer", "Universe scan + per-stock detail"),
                ("/actions", "Buy / Watch / Exit candidates"),
                ("/signals", "Per-signal cross-section"),
                ("/portfolio", "Personal position tracking"),
            ],
        },
    ]

    architecture = {
        "data": arch_data_layer,
        "signals": arch_signals,
        "model": arch_model,
        "picks": arch_picks,
        "summary": {
            "tables": len(data_layer),
            "factors_total": len(factors),
            "factors_in_model": n_in_prod,
            "factors_in_library": n_in_library,
        },
    }

    return {
        "factors": factors,
        "factor_summary": {
            "built": n_built,
            "target": FACTOR_COUNT_TARGET,
            "pct": round(100 * n_built / FACTOR_COUNT_TARGET, 1),
            "in_production": n_in_prod,
            "in_library": n_in_library,
        },
        "data_layer": data_layer,
        "data_model": data_model,
        "todos": todos,
        "where_md": where_md,
        "commits": commits,
        "architecture": architecture,
    }


# ═══════════════════════════════════════════════════
# Health Center — unified one-screen pulse
#
# Surfaces ALL findings inside cockpit so the user never has to read terminal
# health_report output or email digests to know if the system is healthy:
#   1. tools.health_report.gather()  — pipeline + tables + watchdog + dossiers
#   2. tools.data_sanity.run()       — semantic invariants (CRITICAL/WARN/INFO)
#   3. pipeline_log endpoint_audit_* — per-endpoint cockpit coverage gaps
#   4. failed_streaks                — steps currently broken (not historical)
# Each issue is one row with severity / code / source / message / sample /
# drilldown URL, ready for filter+render in the template.
# ═══════════════════════════════════════════════════

def _drilldown_for_issue(issue):
    """Return ('/sql?q=...', label) for an issue, or (None, None) if no drilldown.

    Looks at the issue's source ('sanity'/'freshness'/'pipeline'/'endpoint'/'dossier')
    and table/code to pick the most useful SQL probe.
    """
    src = issue.get("source")
    table = issue.get("table")
    col = issue.get("column")
    if src == "pipeline" and issue.get("step"):
        sql = f"SELECT run_date, status, started_at, error_message FROM pipeline_log WHERE step_name='{issue['step']}' ORDER BY id DESC LIMIT 20"
        return (f"/sql?q={sql}", "Last 20 runs →")
    if src == "endpoint" and issue.get("endpoint"):
        sql = f"SELECT * FROM pipeline_log WHERE step_name='endpoint_audit_{issue['endpoint']}' ORDER BY id DESC LIMIT 10"
        return (f"/sql?q={sql}", "Endpoint audit log →")
    if src == "freshness" and table:
        sql = f"SELECT MAX(date) AS latest FROM {table}" if table else None
        return (f"/sql?table={table}", "Inspect table →") if table else (None, None)
    if src == "sanity":
        # If we have a sample sid, link to its stock detail (always useful)
        sample = issue.get("sample")
        sample = str(sample) if sample is not None else ""
        if sample and len(sample.split()) == 1 and len(sample) <= 12 and "@" not in sample:
            # Looks like a sid
            return (f"/explorer/{sample}", f"Inspect {sample} →")
        if table:
            return (f"/sql?table={table}", f"Inspect {table} →")
    return (None, None)


def _severity_rank(sev):
    return {"CRITICAL": 0, "WARN": 1, "INFO": 2}.get(sev, 3)


def get_health_overview(force=False):
    """One-stop Health Center overview.

    Returns:
        {
            "as_of":            ISO datetime,
            "verdict":          human string (e.g. "1 CRITICAL · 12 WARN"),
            "verdict_severity": "CRITICAL" | "WARN" | "INFO" | "OK",
            "counts":           {critical, warn, info, total},
            "tiles":            {data, factors, pipeline, dossiers}  each {grade, color, headline, detail, link},
            "issues":           [issue dicts] sorted CRITICAL → WARN → INFO,
            "categories":       list of category labels present (for filter dropdown),
            "sources":          list of source labels present,
        }
    """
    from tools import health_report as _hr
    try:
        from tools import data_sanity as _sanity
    except Exception:
        _sanity = None

    report = _hr.gather()
    issues = []

    # ── pipeline failures (today) + streaks (currently broken only) ──
    for f in report["pipeline"]["failed_steps_today"]:
        issues.append({
            "severity": "CRITICAL",
            "source": "pipeline",
            "category": "Pipeline",
            "code": f"PIPELINE_FAILED:{f['step']}",
            "table": None, "column": None,
            "step": f["step"],
            "message": f"Pipeline step '{f['step']}' failed today",
            "detail": (f.get("error") or "")[:240],
            "sample": None, "pct": None, "n_bad": None, "n_total": None,
        })
    for s in report["pipeline"]["failed_streaks"]:
        # Skip if it's already in today's failures (avoid duplicate)
        if any(i["code"] == f"PIPELINE_FAILED:{s['step']}" for i in issues):
            continue
        issues.append({
            "severity": "CRITICAL",
            "source": "pipeline",
            "category": "Pipeline",
            "code": f"PIPELINE_STREAK:{s['step']}",
            "table": None, "column": None,
            "step": s["step"],
            "message": f"Pipeline step '{s['step']}' has failed {s['days']} consecutive days (currently broken)",
            "detail": (s.get("sample_error") or "")[:240],
            "sample": None, "pct": None, "n_bad": s["days"], "n_total": None,
        })

    # ── freshness (stale / outdated / empty tables) ──
    for tbl, age, threshold, producer in report["tables"].get("outdated", []):
        sev = "CRITICAL" if tbl in _hr.CRITICAL_TABLE_OUTDATED else "WARN"
        issues.append({
            "severity": sev,
            "source": "freshness",
            "category": "Data freshness",
            "code": f"OUTDATED:{tbl}",
            "table": tbl, "column": "—",
            "message": f"{tbl} is OUTDATED ({age:.0f}d old, threshold {threshold:.0f}d)",
            "detail": f"producer: {producer}" if producer else "",
            "sample": None, "pct": None,
            "n_bad": round(age), "n_total": round(threshold),
        })
    for tbl, age, threshold, producer in report["tables"].get("stale", []):
        issues.append({
            "severity": "WARN",
            "source": "freshness",
            "category": "Data freshness",
            "code": f"STALE:{tbl}",
            "table": tbl, "column": "—",
            "message": f"{tbl} is STALE ({age:.0f}d / threshold {threshold:.0f}d)",
            "detail": f"producer: {producer}" if producer else "",
            "sample": None, "pct": None,
            "n_bad": round(age), "n_total": round(threshold),
        })
    for tbl in report["tables"].get("empty", []):
        issues.append({
            "severity": "CRITICAL",
            "source": "freshness",
            "category": "Data freshness",
            "code": f"EMPTY:{tbl}",
            "table": tbl, "column": "—",
            "message": f"{tbl} is EMPTY (table exists but no rows)",
            "detail": "",
            "sample": None, "pct": None, "n_bad": 0, "n_total": None,
        })

    # ── data_sanity violations ──
    if _sanity is not None:
        try:
            sanity_violations = _sanity.run()
        except Exception as e:
            sanity_violations = []
            issues.append({
                "severity": "WARN",
                "source": "sanity",
                "category": "Data sanity",
                "code": "SANITY_RUN_FAILED",
                "table": None, "column": None,
                "message": f"data_sanity.run() itself raised: {type(e).__name__}",
                "detail": str(e)[:240],
                "sample": None, "pct": None, "n_bad": None, "n_total": None,
            })
        for v in sanity_violations:
            # categorize by code prefix for filter
            code = v.get("code", "")
            if any(p in code for p in ("CONSENSUS", "ANALYST", "PT_", "FORECAST")):
                cat = "Analyst / PT"
            elif any(p in code for p in ("REGULATORY", "NEWS", "SENTIMENT")):
                cat = "News / regulatory"
            elif any(p in code for p in ("FACTOR", "PIT", "BACKTEST", "PIOTROSKI", "M_SCORE")):
                cat = "Factors / backtest"
            elif any(p in code for p in ("DAILY_PICK", "SCORE_TABLE", "UNIVERSE", "PROMOTER", "INSIDER", "BULK")):
                cat = "Signals / picks"
            elif "COVERAGE" in code:
                cat = "Coverage"
            else:
                cat = "Data sanity"
            issues.append({
                "severity": v.get("severity", "WARN"),
                "source": "sanity",
                "category": cat,
                "code": code,
                "table": v.get("table"),
                "column": v.get("column"),
                "message": v.get("message", ""),
                "detail": "",
                "sample": v.get("sample"),
                "pct": v.get("pct_violations"),
                "n_bad": v.get("n_violations"),
                "n_total": v.get("n_total"),
            })

    # ── cockpit endpoint audit (most-recent per endpoint) ──
    try:
        ep = read_sql(
            """
            WITH ranked AS (
                SELECT step_name, status, error_message, started_at,
                       ROW_NUMBER() OVER (PARTITION BY step_name ORDER BY id DESC) AS rn
                FROM pipeline_log
                WHERE step_name LIKE 'endpoint_audit_%'
            )
            SELECT step_name, status, error_message, started_at
            FROM ranked WHERE rn = 1
            """
        )
    except Exception:
        ep = pd.DataFrame()
    for _, r in ep.iterrows():
        if r["status"] in ("SUCCESS",) and not (r.get("error_message") or ""):
            continue  # endpoint is fine
        endpoint = r["step_name"].replace("endpoint_audit_", "")
        err = (r.get("error_message") or "").strip()
        # Heuristic: if status SUCCESS but error_message non-empty, audit found a gap
        sev = "CRITICAL" if r["status"] == "FAILED" else "WARN"
        issues.append({
            "severity": sev,
            "source": "endpoint",
            "category": "Cockpit endpoints",
            "code": f"ENDPOINT_AUDIT:{endpoint}",
            "table": None, "column": None,
            "endpoint": endpoint,
            "message": f"Cockpit endpoint `{endpoint}` has audit issues",
            "detail": err[:240] or f"status={r['status']}",
            "sample": None, "pct": None, "n_bad": None, "n_total": None,
        })

    # ── dossier validator failures ──
    dossiers_block = report.get("dossiers", {}) or {}
    invalid = dossiers_block.get("invalid_count", 0) or 0
    if invalid:
        issues.append({
            "severity": "WARN",
            "source": "dossier",
            "category": "Dossiers (LLM)",
            "code": "DOSSIER_VALIDATOR_FAILED",
            "table": None, "column": None,
            "message": f"{invalid} dossier(s) failed the narrative validator (raw numbers in prose, or signal mention without context)",
            "detail": ", ".join((dossiers_block.get("invalid_sample") or [])[:5]),
            "sample": None, "pct": None,
            "n_bad": invalid, "n_total": dossiers_block.get("total"),
        })

    # ── attach drilldowns ──
    for i in issues:
        url, label = _drilldown_for_issue(i)
        i["drilldown_url"] = url
        i["drilldown_label"] = label

    # ── sort: severity then code ──
    issues.sort(key=lambda i: (_severity_rank(i["severity"]), i.get("code", "")))

    # ── counts + verdict ──
    counts = {"critical": 0, "warn": 0, "info": 0, "total": len(issues)}
    for i in issues:
        if i["severity"] == "CRITICAL": counts["critical"] += 1
        elif i["severity"] == "WARN":   counts["warn"]     += 1
        elif i["severity"] == "INFO":   counts["info"]     += 1
    if counts["critical"]:
        verdict_sev = "CRITICAL"
        verdict = f"⚠ {counts['critical']} CRITICAL · {counts['warn']} warn · {counts['info']} info"
    elif counts["warn"]:
        verdict_sev = "WARN"
        verdict = f"⚠ {counts['warn']} warn · {counts['info']} info"
    elif counts["info"]:
        verdict_sev = "INFO"
        verdict = f"{counts['info']} info"
    else:
        verdict_sev = "OK"
        verdict = "✓ all healthy"

    # ── tiles: one grade per pillar ──
    def _pillar_grade(critical_n, warn_n):
        if critical_n: return ("F", "#e74c3c")
        if warn_n >= 5: return ("C", "#f1c40f")
        if warn_n: return ("B", "#4d8eff")
        return ("A", "#2ecc71")

    def _count_by(src):
        c = sum(1 for i in issues if i["source"] == src and i["severity"] == "CRITICAL")
        w = sum(1 for i in issues if i["source"] == src and i["severity"] == "WARN")
        info = sum(1 for i in issues if i["source"] == src and i["severity"] == "INFO")
        return c, w, info

    data_c, data_w, data_i = (lambda: (
        sum(1 for i in issues if i["source"] in ("freshness", "sanity") and i["severity"] == "CRITICAL"),
        sum(1 for i in issues if i["source"] in ("freshness", "sanity") and i["severity"] == "WARN"),
        sum(1 for i in issues if i["source"] in ("freshness", "sanity") and i["severity"] == "INFO"),
    ))()

    pipe_c, pipe_w, pipe_i = _count_by("pipeline")
    ep_c, ep_w, ep_i = _count_by("endpoint")
    dos_c, dos_w, dos_i = _count_by("dossier")

    # Factor tile derives from get_factor_health()
    try:
        fh = get_factor_health() or {}
        fh_summary = fh.get("summary", {}) or {}
        # Crude factor pillar grade: F if any in_model factor has data F-grade
        f_grade_dist = fh_summary.get("data_grade_dist", {}) or {}
        f_validation = fh_summary.get("validation_dist", {}) or {}
        if f_grade_dist.get("F", 0):
            f_grade, f_color = ("D", "#e67e22")
        elif f_grade_dist.get("D", 0):
            f_grade, f_color = ("C", "#f1c40f")
        elif f_grade_dist.get("C", 0):
            f_grade, f_color = ("B", "#4d8eff")
        else:
            f_grade, f_color = ("A", "#2ecc71")
        f_headline = f"{fh_summary.get('in_model', 0)} in model · {fh_summary.get('in_library', 0)} library"
        f_detail = (
            f"{f_validation.get('KEEP', 0)} KEEP · "
            f"{f_validation.get('WEAK', 0)} WEAK · "
            f"{f_validation.get('DROP', 0)} DROP · "
            f"{f_validation.get('NONE', 0)} NONE"
        )
    except Exception:
        f_grade, f_color, f_headline, f_detail = ("?", "#888", "—", "factor health unavailable")

    data_grade, data_color = _pillar_grade(data_c, data_w)
    pipe_grade, pipe_color = _pillar_grade(pipe_c, pipe_w)
    dos_grade, dos_color = _pillar_grade(dos_c, dos_w)

    tiles = {
        "data": {
            "label": "Data",
            "grade": data_grade, "color": data_color,
            "headline": f"{data_c} critical · {data_w} warn",
            "detail": f"freshness + sanity invariants across {len(report['tables'])} table-state slots",
            "link": "#data",
        },
        "factors": {
            "label": "Factors",
            "grade": f_grade, "color": f_color,
            "headline": f_headline,
            "detail": f_detail,
            "link": "#factors",
        },
        "pipeline": {
            "label": "Pipeline",
            "grade": pipe_grade, "color": pipe_color,
            "headline": f"last run: {report['pipeline'].get('last_run_status') or '—'}",
            "detail": f"{pipe_c} broken streak(s) · {len(report['pipeline'].get('failed_steps_today', []))} failure(s) today",
            "link": "#pipeline",
        },
        "dossiers": {
            "label": "Dossiers",
            "grade": dos_grade, "color": dos_color,
            "headline": f"{dossiers_block.get('total', 0)} total · {dossiers_block.get('invalid_count', 0)} invalid",
            "detail": "narrative validator (raw numbers / signal-without-context)",
            "link": "#overview",
        },
    }

    categories = sorted({i["category"] for i in issues})
    sources = sorted({i["source"] for i in issues})

    return {
        "as_of": report["as_of"],
        "verdict": verdict,
        "verdict_severity": verdict_sev,
        "counts": counts,
        "tiles": tiles,
        "issues": issues,
        "categories": categories,
        "sources": sources,
        "watchdog": report.get("watchdog", {}),
        "pipeline_summary": report.get("pipeline", {}),
    }
