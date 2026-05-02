"""
Alpha Signal Cockpit — Data Layer

All data queries live here. Called by app.py routes.
Imports db.read_sql directly — no ORM, no new abstractions.
"""

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db


# ═══════════════════════════════════════════════════
# A1-A12: NEW DATA FUNCTIONS
# ═══════════════════════════════════════════════════

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


def get_analyst_consensus(sid):
    """A2: Price target, analyst count, buy%, growth from analyst_consensus."""
    row = read_sql(
        "SELECT price_target, total_analysts, buy_pct, eps_growth_pct, "
        "revenue_growth_pct, forward_eps, fetched_at "
        "FROM analyst_consensus WHERE sid = ?",
        params=[sid],
    )
    if row.empty:
        return {}
    r = row.iloc[0].to_dict()
    # Compute upside vs current price
    price = read_sql(
        "SELECT close FROM stock_prices WHERE sid = ? ORDER BY date DESC LIMIT 1",
        params=[sid],
    )
    if not price.empty and price.iloc[0]["close"] and r.get("price_target"):
        cmp = price.iloc[0]["close"]
        if cmp > 0:
            r["pt_upside_pct"] = round((r["price_target"] / cmp - 1) * 100, 1)
            r["current_price"] = round(cmp, 2)
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
    """A7: Recent regulatory events affecting a sector."""
    if not sector:
        return []
    df = read_sql(
        "SELECT rs.direction, rs.magnitude, rs.time_horizon, rs.confidence, "
        "rs.ai_reasoning, re.title, re.published_at "
        "FROM regulatory_signals rs "
        "JOIN regulatory_events re ON rs.event_id = re.event_id "
        "WHERE rs.sector = ? AND rs.magnitude IN ('major', 'moderate') "
        "ORDER BY re.published_at DESC LIMIT 8",
        params=[sector],
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


def get_dossier(sid):
    """A9: AI investment dossier from latest JSON file."""
    dossier_dir = PROJECT_ROOT / "output"
    files = sorted(glob.glob(str(dossier_dir / "dossiers_*.json")), reverse=True)
    for f in files:
        try:
            with open(f) as fh:
                dossiers = json.load(fh)
            for d in dossiers:
                if d.get("sid") == sid and d.get("thesis"):
                    return d
        except (json.JSONDecodeError, IOError):
            continue
    return {}


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
    """Sector scores + stock counts."""
    df = read_sql("""
        SELECT dp.sector, COUNT(*) as stocks,
               ROUND(AVG(dp.final_score), 3) as avg_score,
               MIN(dp.rank) as best_rank
        FROM daily_picks dp
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
        AND dp.sector IS NOT NULL
        GROUP BY dp.sector
        ORDER BY avg_score DESC
    """)

    # Merge with macro sector signals (latest snapshot only — table keeps history)
    macro = read_sql("""
        SELECT sector, macro_score, macro_signal, macro_detail
        FROM macro_sector_signals
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM macro_sector_signals)
    """)
    if not macro.empty:
        df = df.merge(macro, on="sector", how="left")

    return df.to_dict("records")


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

    return {
        "layers": [{"name": ln, "steps": layers[ln]} for ln in LAYER_ORDER if layers[ln]],
        "step_count": sum(len(v) for v in layers.values()),
    }


def get_data_health_scores(force=False):
    """Comprehensive per-table data health from health.compute_db_health().

    Pass force=True to bypass the 5-minute TTL cache.
    """
    from health import compute_db_health
    return compute_db_health(force=force)
