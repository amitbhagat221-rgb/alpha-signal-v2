"""
Alpha Signal Cockpit — Data Layer

All data queries live here. Called by app.py routes.
Imports db.read_sql directly — no ORM, no new abstractions.
"""

import functools
import glob
import json
import re
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


# Persistent TTL cache — same as _ttl_cache but also pickles to disk so a
# systemd restart doesn't reset the cache. First call after restart loads
# from disk (~ms) instead of recomputing (~5-17s). Background refresh kicks
# off the next time TTL expires. Use for the heaviest cockpit endpoints.
# 2026-05-25: added after /system cold-restart was 28-39s.
_PERSISTED_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / ".cockpit_cache"


def _persisted_cache(ttl_seconds, name=None):
    """Disk-backed sibling of _ttl_cache. Keyed by (args, kwargs) — each unique
    arg combo gets its own pickle file. Use sparingly for heavy functions where
    the arg space is small (e.g. news pool keyed by hours ∈ {24,72,168,720})."""
    import pickle as _pickle

    def _key_to_slot(slot_base, args, kwargs):
        if not args and not kwargs:
            return slot_base
        parts = [slot_base]
        if args:
            parts.append("_".join(str(a) for a in args))
        if kwargs:
            parts.append("_".join(f"{k}={v}" for k, v in sorted(kwargs.items())))
        return "__".join(parts)

    def decorator(fn):
        slot_base = name or f"{fn.__module__}.{fn.__name__}"
        memo: dict = {}  # key -> (value, mtime)

        def _path_for(slot):
            return _PERSISTED_CACHE_DIR / f"{slot}.pkl"

        def _load(slot):
            p = _path_for(slot)
            if not p.exists():
                return None, 0
            try:
                with p.open("rb") as f:
                    payload, mtime = _pickle.load(f)
                return payload, mtime
            except Exception:
                return None, 0

        def _save(slot, payload, mtime):
            try:
                _PERSISTED_CACHE_DIR.mkdir(parents=True, exist_ok=True)
                with _path_for(slot).open("wb") as f:
                    _pickle.dump((payload, mtime), f)
            except Exception:
                pass

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            force = kwargs.pop("_force", False)
            now = _time.time()
            slot = _key_to_slot(slot_base, args, kwargs)
            entry = memo.get(slot)
            if entry is None and not force:
                payload, mtime = _load(slot)
                if payload is not None:
                    entry = (payload, mtime)
                    memo[slot] = entry
            if not force and entry is not None and (now - entry[1]) < ttl_seconds:
                return entry[0]
            value = fn(*args, **kwargs)
            memo[slot] = (value, now)
            _save(slot, value, now)
            return value

        wrapper.cache_clear = lambda: memo.clear()
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
    df = df.astype(object).where(df.notna(), None)
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
        # Plan 0005 Phase F: Barra-style risk decomp
        "risk_decomp": get_risk_decomposition([s["sid"] for s in all_stocks]),
    }


def get_risk_decomposition(sids):
    """Barra-style portfolio risk decomposition for a given pick set.

    Plan 0005 Phase F (93 → 95). Surfaces three views:
      1. Style tilts — portfolio's average factor z-score vs universe mean.
         A +1.4σ Value tilt means the portfolio is, on average, 1.4 standard
         deviations above the universe on Earnings Yield + Book-to-Price.
         Catches "your model is just a value bet" without you noticing.
      2. Sector concentration — Herfindahl-Hirschman Index (HHI) of sector
         weights. HHI > 1500 = concentrated; > 2500 = highly concentrated.
      3. Cap-tier mix — % of picks in LARGE/MID/SMALL.

    Returns: {"tilts": [{group, z, label}], "sector_hhi": int, "sector_top3_pct": float,
              "cap_mix": {LARGE, MID, SMALL}, "n_picks": int} or {} if no picks.
    """
    if not sids:
        return {}

    # Latest daily_snapshots for portfolio + universe
    snap = read_sql(
        "SELECT sid, cap_tier, piotroski_f, cf_accruals, bs_accruals, "
        "       earnings_yield, book_to_price, consensus_signal, "
        "       promoter_qoq, mom_6m, mom_12m, smart_money "
        "FROM daily_snapshots "
        "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)"
    )
    if snap.empty:
        return {}

    # Style groups — Barra-style. Each group aggregates 1-N signals.
    STYLE_GROUPS = [
        ("Value",     ["earnings_yield", "book_to_price"]),
        ("Quality",   ["piotroski_f"]),
        ("Growth",    ["consensus_signal"]),
        ("Momentum",  ["mom_6m", "mom_12m"]),
        ("Accruals",  ["cf_accruals", "bs_accruals"]),   # sign-flipped (lower = better)
        ("Ownership", ["promoter_qoq"]),
        ("Flow",      ["smart_money"]),
    ]

    portfolio = snap[snap["sid"].isin(sids)]
    if portfolio.empty:
        return {}

    tilts = []
    for label, cols in STYLE_GROUPS:
        # Combine the constituent signals: z-score each, average. Universe z=0 by definition.
        zs_port = []
        for c in cols:
            if c not in snap.columns:
                continue
            mu = float(snap[c].mean(skipna=True))
            sd = float(snap[c].std(skipna=True, ddof=1))
            if sd <= 0 or pd.isna(sd):
                continue
            port_mean = float(portfolio[c].mean(skipna=True))
            if pd.isna(port_mean):
                continue
            # Accruals: invert sign so lower-is-better gives a POSITIVE quality-tilt z
            sign = -1 if c in ("cf_accruals", "bs_accruals") else 1
            zs_port.append(sign * (port_mean - mu) / sd)
        if zs_port:
            z = round(sum(zs_port) / len(zs_port), 2)
            tilts.append({
                "group": label,
                "z": z,
                # Direction label — what "+z" means for this style
                "direction": "tilted toward" if z >= 0 else "tilted away from",
                "magnitude": (
                    "strong" if abs(z) >= 0.5 else
                    "moderate" if abs(z) >= 0.25 else
                    "neutral"
                ),
            })

    # Sector concentration — HHI on the pick set
    sectors_q = read_sql(
        f"SELECT sector FROM stocks WHERE sid IN ({','.join('?'*len(sids))})",
        params=list(sids),
    )
    sector_counts = sectors_q["sector"].value_counts(normalize=True)  # weight by equal-weight
    hhi = int((sector_counts ** 2).sum() * 10000) if not sector_counts.empty else 0
    top3_pct = float(sector_counts.head(3).sum() * 100) if not sector_counts.empty else 0
    top_sector = sector_counts.idxmax() if not sector_counts.empty else None
    top_sector_pct = float(sector_counts.max() * 100) if not sector_counts.empty else 0

    # Cap-tier mix
    cap_counts = portfolio["cap_tier"].value_counts().to_dict()
    cap_mix = {t: int(cap_counts.get(t, 0)) for t in ("LARGE", "MID", "SMALL")}

    return {
        "n_picks": len(portfolio),
        "tilts": tilts,
        "sector_hhi": hhi,
        "sector_hhi_label": (
            "concentrated" if hhi > 2500 else
            "moderate" if hhi > 1500 else
            "diversified"
        ),
        "sector_top3_pct": round(top3_pct, 1),
        "top_sector": top_sector,
        "top_sector_pct": round(top_sector_pct, 1),
        "cap_mix": cap_mix,
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
    """Top picks by tier with stock metadata.

    integrity FAIL SIDs (plan 0005 Phase B) are excluded — a stock whose
    structured fields contradict each other shouldn't appear in morning_brief
    or action_queue. The picks still exist in daily_picks for review in cockpit,
    just not as a recommendation.
    """
    where = f"AND dp.cap_tier = '{tier}'" if tier else ""
    df = read_sql(f"""
        SELECT dp.sid, dp.final_score, dp.rank, dp.cap_tier, dp.sector,
               dp.base_score, dp.forensic_adj,
               s.ticker, s.name, s.market_cap_cr, s.pe_ratio, s.roe
        FROM daily_picks dp
        JOIN stocks s ON dp.sid = s.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
          AND (dp.integrity_status IS NULL OR dp.integrity_status != 'FAIL')
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
    """All stocks grouped by tier with scores for heat map.
    MICRO tier is included via a separate path: they're excluded from daily_picks
    by design (config.EXCLUDED_FROM_PICKS) but signal data IS still computed for
    them. Render at score=0 placeholder so the heatmap shows the universe."""
    df = read_sql("""
        SELECT dp.sid, s.ticker, s.name, dp.final_score as score, dp.cap_tier
        FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid
        WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
          AND s.cap_tier != 'MICRO'
        ORDER BY dp.cap_tier, dp.final_score DESC
    """)
    micro_df = read_sql("""
        SELECT sid, ticker, name, 0.0 AS score, cap_tier
        FROM stocks WHERE cap_tier = 'MICRO'
        ORDER BY ticker
    """)
    result = {}
    for tier in ["LARGE", "MID", "SMALL"]:
        tier_df = df[df["cap_tier"] == tier]
        result[tier] = tier_df[["sid", "ticker", "name", "score"]].to_dict("records")
    if not micro_df.empty:
        result["MICRO"] = micro_df[["sid", "ticker", "name", "score"]].to_dict("records")
    return result


def get_explorer_table():
    """Ranked table view for explorer with enriched data.
    Includes MICRO tier (no rank/score since they're excluded from daily_picks)
    via a UNION — explorer tab needs to render the MICRO grid even though MICRO
    stocks aren't scored. Signal data IS computed for them; we just don't pick."""
    df = read_sql("""
        SELECT * FROM (
          SELECT dp.sid, s.ticker, s.name, dp.sector, dp.cap_tier,
                 dp.rank AS rank, dp.final_score AS score,
                 ds.consensus_signal, ds.piotroski_f, ds.earnings_yield
          FROM daily_picks dp
          JOIN stocks s ON dp.sid = s.sid
          LEFT JOIN daily_snapshots ds ON dp.sid = ds.sid
              AND ds.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
          WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)
            AND s.cap_tier != 'MICRO'
          UNION ALL
          SELECT s.sid, s.ticker, s.name, s.sector, s.cap_tier,
                 NULL AS rank, NULL AS score,
                 ds.consensus_signal, ds.piotroski_f, ds.earnings_yield
          FROM stocks s
          LEFT JOIN daily_snapshots ds ON s.sid = ds.sid
              AND ds.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
          WHERE s.cap_tier = 'MICRO'
        )
        ORDER BY cap_tier, rank
    """)
    if df.empty:
        return []
    df = df.astype(object).where(df.notna(), None)
    return df.to_dict("records")


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

    # Latest pick. Skip cap_tier from daily_picks — `stocks.cap_tier` is the
    # source of truth (MICRO reclassification, etc); merging a stale pick row
    # would resurrect yesterday's tier assignment.
    pick = read_sql(
        "SELECT final_score, rank FROM daily_picks "
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


def get_stock_lineage(sid):
    """Per-stock data lineage — which source rows fed each factor.

    Returns dict keyed by factor name, each value a list of source records
    with {table, key, cols, column_sources, contribution}.

    Pairs with the static `lineage.FACTOR_LINEAGE` registry: the cockpit
    panel shows both layers — declarative reads from the registry, plus
    actual emitted rows from `signal_lineage` for this sid (top-300 only).

    See plan 0005 Phase F + ADR 0027.
    """
    import json as _json
    from lineage import FACTOR_LINEAGE, TABLE_COLUMN_SOURCES

    df = read_sql(
        "SELECT factor, source_table, source_key, source_cols, column_sources, contribution, "
        "       snapshot_date "
        "FROM signal_lineage WHERE sid = ? "
        "ORDER BY factor, source_table, contribution, source_key",
        params=[sid],
    )

    grouped = {}
    if not df.empty:
        for _, row in df.iterrows():
            f = row["factor"]
            try:
                src_key = _json.loads(row["source_key"]) if row["source_key"] else {}
            except Exception:
                src_key = row["source_key"]
            try:
                src_cols = _json.loads(row["source_cols"]) if row["source_cols"] else None
            except Exception:
                src_cols = row["source_cols"]
            try:
                col_src = _json.loads(row["column_sources"]) if row["column_sources"] else None
            except Exception:
                col_src = None
            grouped.setdefault(f, []).append({
                "table":          row["source_table"],
                "key":            src_key,
                "cols":           src_cols,
                "column_sources": col_src,
                "contribution":   row["contribution"] or None,
                "snapshot_date":  row["snapshot_date"],
            })

    # Also surface the static registry entries so factors WITHOUT dynamic
    # emission still show their declared reads (model_active subset for now).
    static = {}
    for factor, entry in FACTOR_LINEAGE.items():
        if "inherits_from" in entry:
            entry = FACTOR_LINEAGE.get(entry["inherits_from"], {})
        reads = entry.get("reads") or []
        if not reads and "composite_of" in entry:
            static[factor] = {
                "status":       entry.get("status"),
                "composite_of": entry.get("composite_of"),
            }
            continue
        static[factor] = {
            "status": entry.get("status"),
            "module": entry.get("module"),
            "reads":  reads,
            "sector_exclusions": entry.get("sector_exclusions", []),
        }

    return {
        "sid":              sid,
        "dynamic_lineage":  grouped,
        "static_registry":  static,
        "mixed_source_tables": list(TABLE_COLUMN_SOURCES.keys()),
        "in_active_universe": bool(grouped),   # top-300 SIDs have dynamic rows
    }


def get_price_series(sid, days=365):
    """Price time series for charts."""
    df = read_sql(
        "SELECT date, close, volume FROM stock_prices "
        "WHERE sid = ? ORDER BY date DESC LIMIT ?",
        params=[sid, days],
    )
    if df.empty:
        return []
    df = df.sort_values("date").astype(object).where(df.notna(), None)
    return df.to_dict("records")


def get_price_series_extended(sid, days=365):
    """Extended price series with OHLCV + delivery % for technicals tab.
    NaN → None so FastAPI's JSON encoder doesn't 500 on sparse delivery_pct rows."""
    df = read_sql(
        "SELECT date, open, high, low, close, volume, delivery_pct "
        "FROM stock_prices WHERE sid = ? AND close > 0 "
        "ORDER BY date DESC LIMIT ?",
        params=[sid, days],
    )
    if df.empty:
        return []
    df = df.sort_values("date").astype(object).where(df.notna(), None)
    return df.to_dict("records")


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

    # YoY growth: compare each quarter to the same quarter 4 quarters ago.
    # replace([inf,-inf,nan], None) so divide-by-zero margins (revenue=0) don't 500 the API.
    df_records = (df.sort_values("end_date")
                    .replace([np.inf, -np.inf], np.nan)
                    .astype(object).where(lambda x: x.notna(), None))
    quarters = df_records.to_dict("records")
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


@_persisted_cache(60, name="get_action_candidates")
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


@_persisted_cache(60, name="get_portfolio_bundle")
def get_portfolio_bundle():
    """Single cacheable bundle for /portfolio render — picks + per-stock enrichment
    + analytics in one disk slot, so first-click after restart is fast even though
    we'd otherwise loop ~30 stocks × 2 API calls. 2026-05-25 perf pass."""
    regime = get_regime()
    portfolio_data = get_model_portfolio()
    for key in ["large", "mid", "small"]:
        for s in portfolio_data.get(key, []):
            ac = get_analyst_consensus(s["sid"])
            pm = get_stock_price_metrics(s["sid"])
            s["pt_upside"] = ac.get("pt_upside_pct")
            s["price"] = pm.get("close_price")
            s["return_1m"] = pm.get("return_1m")
            s["price_target"] = ac.get("price_target")
    analytics = get_portfolio_analytics(portfolio_data, regime)
    return {"regime": regime, "portfolio": portfolio_data, "analytics": analytics}


@_persisted_cache(60, name="get_model_portfolio")
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


# ── Factor-model variants (production / max-return / max-sharpe) ──
# Runs scoring.screener three ways and returns picks side-by-side. Production
# is the same data already in daily_picks; variants are computed live.
# Cached 30 min — once per ~half-hour the screener runs end-to-end (~5-8s).

@_persisted_cache(1800, name="model_variants")
def get_model_variants(top_per_tier: int = 10) -> dict:
    """Run all 3 weight schemes and return their top picks for comparison.

    Returns a dict with structure:
        {
          'variants': {
            'production': {
              'label': 'Production', 'description': '...',
              'weights': {LARGE: {...}, MID: {...}, SMALL: {...}},
              'picks':   {LARGE: [...], MID: [...], SMALL: [...]},
              'gate_excluded': int,
            },
            'return':  {...},
            'sharpe':  {...},
          },
          'as_of': '2026-05-28',
        }
    Pick records carry: rank, sid, ticker, name, sector, final_score,
    base_score, eligible_coverage.
    """
    from datetime import date
    from config import SIGNAL_WEIGHTS, SIGNAL_WEIGHTS_RETURN, SIGNAL_WEIGHTS_SHARPE
    from scoring.screener import _load_signals, score_universe, select_picks

    variant_specs = [
        ("production", SIGNAL_WEIGHTS,        None, "Production",
         "Hand-tuned weights from the C13b validation. Currently writes to daily_picks."),
        ("return",     SIGNAL_WEIGHTS_RETURN, 0.40, "Max Return",
         "Weights ∝ |t-stat| from PIT IC backtest. Concentrates on factors with biggest absolute IC."),
        ("sharpe",     SIGNAL_WEIGHTS_SHARPE, 0.40, "Max Sharpe",
         "Weights ∝ ICIR (IC info-ratio). Favors consistency over magnitude — lower variance per trade."),
    ]

    df = _load_signals()

    out = {}
    for key, weights, gate, label, descr in variant_specs:
        scored = score_universe(df.copy(), weights=weights)
        # Note: select_picks already prints to stdout; ok in this cached path.
        picks_df = select_picks(scored,
                                 {"LARGE": top_per_tier, "MID": top_per_tier, "SMALL": top_per_tier},
                                 min_eligible=gate)
        picks_by_tier = {}
        for tier in ["LARGE", "MID", "SMALL"]:
            tier_df = picks_df[picks_df["cap_tier"] == tier]
            picks_by_tier[tier] = [
                {
                    "rank":              int(r["rank"]) if pd.notna(r["rank"]) else None,
                    "sid":               r["sid"],
                    "ticker":            r["ticker"],
                    "name":              r["name"],
                    "sector":            r["sector"],
                    "final_score":       round(float(r["final_score"]), 4) if pd.notna(r["final_score"]) else None,
                    "base_score":        round(float(r["base_score"]), 4) if pd.notna(r["base_score"]) else None,
                    "eligible_coverage": round(float(r.get("eligible_coverage", 0)), 3) if pd.notna(r.get("eligible_coverage", 0)) else None,
                }
                for _, r in tier_df.iterrows()
            ]
        out[key] = {
            "label":       label,
            "description": descr,
            "weights":     weights,
            "picks":       picks_by_tier,
        }

    return {
        "variants": out,
        "as_of":    date.today().isoformat(),
    }


# ── Mutual Fund research section (plan prfect-lets-add-a-zazzy-eich) ──
# Standalone research section. See cockpit/templates/mutual_funds.html (universe
# browser) and mf_detail.html (per-scheme deep-dive). Data layer:
#   - mf_scheme_master   AMFI universe (~14k schemes, refreshed weekly)
#   - mf_nav_history     daily NAV per scheme (AMFI daily + mfapi.in backfill)
#   - mf_metrics         per-scheme returns/risk/composite_score (monthly recompute)
#   - mf_rolling_returns 3Y/5Y rolling CAGR sampled monthly per scheme
#   - mf_calendar_returns per-year returns table
#   - mf_category_stats  category medians/deciles


@_persisted_cache(600, name="mf_universe_overview")
def get_mf_universe_overview(category: str = None, amc: str = None,
                              plan: str = None, option: str = None,
                              q: str = None, sort: str = "score",
                              page: int = 1, page_size: int = 50,
                              include_non_investable: bool = False) -> dict:
    """Filterable + paginated universe browser. Returns dict with rows + facets + counts.

    Filters:
      category   one of mf_scheme_master.category_norm (or family prefix like 'Equity')
      amc        substring match on AMC name
      plan       'DIRECT' / 'REGULAR'
      option     'GROWTH' / 'IDCW'
      q          free-text on scheme_name
      include_non_investable  if True, include schemes that are NOT realistically
                       investable: data_quality != 'TRUSTED' (wound-up, segregated,
                       interval, bonus, anomalous NAV) OR latest NAV is stale
                       (>30 days old — matured FMPs, delisted plans). Default False.
    Sort: 'score' (default) / 'ret_1y' / 'ret_3y' / 'sharpe_1y' / 'name'.
    """
    where = ["sm.active = 1"]
    if not include_non_investable:
        where.append("(sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')")
        where.append(
            "EXISTS (SELECT 1 FROM mf_nav_history n "
            "WHERE n.scheme_code = sm.scheme_code "
            "AND n.nav_date >= date('now','-30 days'))"
        )
    params: list = []
    if category:
        if "/" in category:
            where.append("sm.category_norm = ?")
            params.append(category)
        else:
            where.append("sm.category_norm LIKE ?")
            params.append(f"{category}%")
    if amc:
        where.append("sm.amc LIKE ?")
        params.append(f"%{amc}%")
    if plan:
        where.append("sm.plan_type = ?")
        params.append(plan.upper())
    if option:
        where.append("sm.option_type = ?")
        params.append(option.upper())
    if q:
        where.append("sm.scheme_name LIKE ?")
        params.append(f"%{q}%")

    where_sql = " AND ".join(where)
    sort_map = {
        "score":     "m.composite_score DESC NULLS LAST",
        "ret_1y":    "m.ret_1y DESC NULLS LAST",
        "ret_3y":    "m.ret_3y_cagr DESC NULLS LAST",
        "ret_5y":    "m.ret_5y_cagr DESC NULLS LAST",
        "sharpe_1y": "m.sharpe_1y DESC NULLS LAST",
        "max_dd":    "m.max_drawdown DESC NULLS LAST",
        "name":      "sm.scheme_name ASC",
    }
    order_by = sort_map.get(sort, sort_map["score"])

    # Join to LATEST mf_metrics row per scheme (defensive — table should be clean
    # after the monthly compute, but stale rows from earlier runs can stick around).
    metrics_join = """LEFT JOIN mf_metrics m
        ON sm.scheme_code = m.scheme_code
       AND m.as_of_date = (SELECT MAX(as_of_date) FROM mf_metrics)"""

    # Count for pagination
    total = read_sql(
        f"""SELECT COUNT(*) AS n FROM mf_scheme_master sm
            {metrics_join}
            WHERE {where_sql}""",
        params=params,
    ).iloc[0]["n"]

    # Page rows
    offset = max(0, (page - 1) * page_size)
    rows = read_sql(
        f"""SELECT sm.scheme_code, sm.scheme_name, sm.amc, sm.category_norm,
                   sm.plan_type, sm.option_type,
                   m.nav, m.nav_date,
                   m.ret_1y, m.ret_3y_cagr, m.ret_5y_cagr,
                   m.sharpe_1y, m.max_drawdown,
                   m.composite_score, m.score_percentile, m.peer_rank_3y
            FROM mf_scheme_master sm
            {metrics_join}
            WHERE {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?""",
        params=params + [page_size, offset],
    )

    return {
        "rows":      rows.replace({float("nan"): None}).to_dict("records"),
        "total":     int(total),
        "page":      page,
        "page_size": page_size,
        "n_pages":   (int(total) + page_size - 1) // page_size,
        "sort":      sort,
        "filters":   {"category": category, "amc": amc, "plan": plan, "option": option, "q": q},
    }


@_persisted_cache(3600, name="mf_category_heatmap")
def get_mf_category_heatmap(include_non_investable: bool = False) -> list[dict]:
    """Category-level medians for the heatmap on /mutual-funds.

    One row per category_norm with median 3Y CAGR, scheme count.
    Used to render colored squares at the top of the page (click to filter).

    When include_non_investable=False (default), categories with zero investable
    schemes (e.g. Debt / Income legacy FMPs, ETFs that aren't real funds) are
    hidden, and scheme_count reflects the investable-only count to match the
    table below.
    """
    df = read_sql("""
        SELECT cs.category_norm,
               cs.scheme_count,
               ROUND(cs.median_ret_1y, 2)  AS median_ret_1y,
               ROUND(cs.median_ret_3y, 2)  AS median_ret_3y,
               ROUND(cs.median_ret_5y, 2)  AS median_ret_5y,
               ROUND(cs.median_sharpe_1y, 2) AS median_sharpe_1y,
               ROUND(cs.median_std_1y, 2)    AS median_std_1y,
               ROUND(cs.top_decile_ret_1y, 2) AS top_decile_ret_1y
        FROM mf_category_stats cs
        WHERE cs.as_of_date = (SELECT MAX(as_of_date) FROM mf_category_stats)
        ORDER BY cs.scheme_count DESC
    """)
    if include_non_investable:
        return df.replace({float("nan"): None}).to_dict("records")

    inv = read_sql("""
        SELECT sm.category_norm, COUNT(*) AS investable_count
        FROM mf_scheme_master sm
        WHERE sm.active = 1
          AND (sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')
          AND EXISTS (SELECT 1 FROM mf_nav_history n
                      WHERE n.scheme_code = sm.scheme_code
                        AND n.nav_date >= date('now','-30 days'))
        GROUP BY sm.category_norm
    """)
    inv_map = dict(zip(inv["category_norm"], inv["investable_count"]))
    df["scheme_count"] = df["category_norm"].map(inv_map).fillna(0).astype(int)
    df = df[df["scheme_count"] > 0].sort_values("scheme_count", ascending=False).copy()
    return df.replace({float("nan"): None}).to_dict("records")


def get_mf_detail(scheme_code: str) -> dict | None:
    """Per-scheme deep-dive payload — identity, snapshot, returns, risk, scorer breakdown."""
    info = read_sql(
        """SELECT sm.scheme_code, sm.scheme_name, sm.amc, sm.category_norm, sm.category_raw,
                  sm.plan_type, sm.option_type, sm.isin_growth, sm.isin_div,
                  sm.aum_cr, sm.expense_ratio, sm.benchmark,
                  sm.data_quality, sm.quality_reason,
                  ms.inception_date, ms.has_full_history, sm.last_seen
           FROM mf_scheme_master sm
           LEFT JOIN mf_schemes ms ON sm.scheme_code = ms.scheme_code
           WHERE sm.scheme_code = ?""",
        params=[scheme_code],
    )
    if info.empty:
        return None
    info_dict = info.iloc[0].replace({float("nan"): None}).to_dict()

    metrics = read_sql(
        "SELECT * FROM mf_metrics WHERE scheme_code = ? ORDER BY as_of_date DESC LIMIT 1",
        params=[scheme_code],
    )
    metrics_dict = metrics.iloc[0].replace({float("nan"): None}).to_dict() if not metrics.empty else {}

    calendar = read_sql(
        "SELECT year, ret_pct, bench_ret_pct FROM mf_calendar_returns "
        "WHERE scheme_code = ? ORDER BY year DESC",
        params=[scheme_code],
    )
    calendar_list = calendar.replace({float("nan"): None}).to_dict("records")

    return {
        "info":     info_dict,
        "metrics":  metrics_dict,
        "calendar": calendar_list,
    }


def get_mf_nav_series(scheme_code: str, days: int = None) -> list[dict]:
    """NAV time series for the chart. `days` filters to last N days; None = full history."""
    if days:
        df = read_sql(
            "SELECT nav_date AS date, nav FROM mf_nav_history "
            "WHERE scheme_code = ? AND nav_date >= date('now', ?) "
            "ORDER BY nav_date",
            params=[scheme_code, f"-{int(days)} day"],
        )
    else:
        df = read_sql(
            "SELECT nav_date AS date, nav FROM mf_nav_history "
            "WHERE scheme_code = ? ORDER BY nav_date",
            params=[scheme_code],
        )
    return df.to_dict("records")


def get_mf_rolling_returns(scheme_code: str) -> list[dict]:
    """Rolling 3Y / 5Y CAGR series (monthly anchors)."""
    df = read_sql(
        """SELECT anchor_date,
                  rolling_3y_cagr, rolling_5y_cagr,
                  rolling_3y_beats_category, rolling_5y_beats_category
           FROM mf_rolling_returns
           WHERE scheme_code = ? ORDER BY anchor_date""",
        params=[scheme_code],
    )
    return df.replace({float("nan"): None}).to_dict("records")


def get_mf_peer_rank(scheme_code: str, top_n: int = 10) -> dict:
    """Peer comparison — top N schemes in same category_norm by composite_score."""
    cat = read_sql(
        "SELECT category_norm FROM mf_scheme_master WHERE scheme_code = ?",
        params=[scheme_code],
    )
    if cat.empty or not cat.iloc[0]["category_norm"]:
        return {"category": None, "peers": []}
    category = cat.iloc[0]["category_norm"]

    peers = read_sql(
        """SELECT sm.scheme_code, sm.scheme_name, sm.amc,
                  m.composite_score, m.ret_3y_cagr, m.sharpe_3y
           FROM mf_metrics m
           JOIN mf_scheme_master sm ON sm.scheme_code = m.scheme_code
           WHERE sm.category_norm = ? AND m.composite_score IS NOT NULL
           ORDER BY m.composite_score DESC LIMIT ?""",
        params=[category, top_n],
    )
    return {
        "category": category,
        "peers":    peers.replace({float("nan"): None}).to_dict("records"),
    }


def get_mf_holdings(scheme_code: str) -> dict:
    """Top holdings + sector allocation for a scheme (mf_holdings + mf_sector_allocation).

    Returns dict with `top` (list of holding dicts), `sectors` (list of sector dicts),
    and `as_of_date`. Empty if no holdings data has been ingested for this scheme.
    """
    top = read_sql(
        """SELECT holding_rank, instrument_name, sid, isin, sector, pct_of_aum,
                  market_value_cr, instrument_type
           FROM mf_holdings
           WHERE scheme_code = ?
             AND as_of_date = (SELECT MAX(as_of_date) FROM mf_holdings WHERE scheme_code = ?)
           ORDER BY holding_rank ASC""",
        params=[scheme_code, scheme_code],
    )
    sectors = read_sql(
        """SELECT sector, pct_of_aum FROM mf_sector_allocation
           WHERE scheme_code = ?
             AND as_of_date = (SELECT MAX(as_of_date) FROM mf_sector_allocation WHERE scheme_code = ?)
           ORDER BY pct_of_aum DESC""",
        params=[scheme_code, scheme_code],
    )
    as_of = top["holding_rank"].iloc[0] if False else None
    if not top.empty:
        as_of_row = read_sql(
            "SELECT MAX(as_of_date) AS d FROM mf_holdings WHERE scheme_code = ?",
            params=[scheme_code],
        )
        as_of = as_of_row.iloc[0]["d"] if not as_of_row.empty else None
    return {
        "top":         top.replace({float("nan"): None}).to_dict("records"),
        "sectors":     sectors.replace({float("nan"): None}).to_dict("records"),
        "as_of_date":  as_of,
    }


def get_mf_compare(scheme_codes: list[str]) -> dict:
    """Side-by-side comparison for 2-5 schemes — same metrics shape as detail page.

    Returns dict with `schemes` (one entry per code) + `categories_seen` (so the
    UI can warn when comparing across categories).
    """
    if not scheme_codes:
        return {"schemes": [], "categories_seen": []}
    scheme_codes = scheme_codes[:5]
    ph = ",".join("?" * len(scheme_codes))

    info = read_sql(
        f"""SELECT sm.scheme_code, sm.scheme_name, sm.amc, sm.category_norm,
                   sm.plan_type, sm.option_type,
                   ms.inception_date, ms.has_full_history
            FROM mf_scheme_master sm
            LEFT JOIN mf_schemes ms ON sm.scheme_code = ms.scheme_code
            WHERE sm.scheme_code IN ({ph})""",
        params=scheme_codes,
    )
    metrics = read_sql(
        f"""SELECT * FROM mf_metrics WHERE scheme_code IN ({ph})
            AND as_of_date = (SELECT MAX(as_of_date) FROM mf_metrics)""",
        params=scheme_codes,
    )

    info_by_code = {r["scheme_code"]: r for _, r in info.iterrows()}
    metrics_by_code = {r["scheme_code"]: r for _, r in metrics.iterrows()}

    schemes = []
    for code in scheme_codes:
        if code not in info_by_code:
            continue
        i = info_by_code[code].replace({float("nan"): None}).to_dict()
        m = metrics_by_code.get(code)
        m = m.replace({float("nan"): None}).to_dict() if m is not None else {}
        schemes.append({"info": i, "metrics": m})

    cats = sorted({s["info"].get("category_norm") for s in schemes if s["info"].get("category_norm")})
    return {"schemes": schemes, "categories_seen": cats}


def get_mf_search(q: str, limit: int = 10) -> list[dict]:
    """Typeahead suggestions for scheme search."""
    if not q or len(q) < 2:
        return []
    df = read_sql(
        """SELECT scheme_code, scheme_name, amc, category_norm
           FROM mf_scheme_master
           WHERE active = 1 AND scheme_name LIKE ?
           ORDER BY LENGTH(scheme_name) ASC LIMIT ?""",
        params=[f"%{q}%", limit],
    )
    return df.to_dict("records")


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


# Source tier map — per news_app_build_spec.md.
# Tier 1 = highest trust, Tier 4 = lowest. Score is the source_trust component.
# Moved back here from cockpit_ops/api.py during a hotfix on 2026-05-26: the
# Stage 2 Ops extraction had grabbed it along with `get_health_overview` (it
# lived adjacent in the original file), but `_news_tier()` is the only
# consumer and lives here.
_NEWS_SOURCE_TIERS = {
    "livemint_markets":     ("Mint Markets",        1, 1.0),
    "livemint_companies":   ("Mint Companies",      1, 1.0),
    "et_markets":           ("Economic Times Markets",   2, 0.75),
    "et_companies":         ("Economic Times Companies", 2, 0.75),
    "et_economy":           ("Economic Times Economy",   2, 0.75),
    "moneycontrol_latest":  ("Moneycontrol",        3, 0.55),
    "moneycontrol_business":("Moneycontrol Business",3, 0.55),
    "moneycontrol_markets": ("Moneycontrol Markets",3, 0.55),
}


def _news_tier(source):
    return _NEWS_SOURCE_TIERS.get(source, (source, 4, 0.30))


def _humanize_age(published_at):
    """Return '3h ago' / '2d ago' / '5m ago' style relative time."""
    if not published_at:
        return ""
    try:
        ts = pd.to_datetime(published_at, errors="coerce", utc=True)
        if pd.isna(ts):
            return ""
        delta = (pd.Timestamp.now(tz="UTC") - ts).total_seconds()
    except Exception:
        return ""
    if delta < 60:    return "just now"
    if delta < 3600:  return f"{int(delta/60)}m ago"
    if delta < 86400: return f"{int(delta/3600)}h ago"
    if delta < 604800:return f"{int(delta/86400)}d ago"
    return ts.strftime("%d %b")


@_ttl_cache(300)
def get_news_brief(target_date=None):
    """Latest daily brief (THE BIG ONE / FIVE FAST / ONE TO WATCH / ZOOM OUT).

    Returns {} if no brief generated yet. Otherwise the parsed structure for
    display at the top of /news. Synthesized by sources/news_brief.py via
    Claude Sonnet.
    """
    if target_date:
        df = read_sql(
            "SELECT * FROM news_briefs WHERE brief_date = ? LIMIT 1",
            params=[target_date],
        )
    else:
        df = read_sql("SELECT * FROM news_briefs ORDER BY brief_date DESC LIMIT 1")
    if df.empty:
        return {}
    r = df.iloc[0].to_dict()
    import json as _json
    try:
        r["five_fast"] = _json.loads(r.get("five_fast") or "[]")
    except Exception:
        r["five_fast"] = []
    return r


# Topic taxonomy — kept in sync with sources/news_classifier.py TOPIC_TAXONOMY.
# Cockpit reads its own copy so it can render without importing the classifier
# module (avoids pulling in anthropic SDK dependency on every page load).
_NEWS_TOPICS = [
    ("macro",          "Macro",                "#9b59b6"),
    ("global_economy", "Global Economy",       "#5dade2"),
    ("india_markets",  "India Markets",        "#2ecc71"),
    ("finance",        "Finance & Banking",    "#f1c40f"),
    ("earnings",       "Earnings & Companies", "#e67e22"),
    ("deals",          "Deals, IPOs & M&A",    "#e91e63"),
    ("ai_tech",        "AI & Tech",            "#3498db"),
    ("politics",       "Politics & Policy",    "#c0392b"),
    ("energy",         "Energy & Commodities", "#ff8c00"),
    ("consumer",       "Consumer & Retail",    "#16a085"),
    ("industrial",     "Industrial & Infra",   "#7f8c8d"),
    ("pharma_health",  "Pharma & Health",      "#1abc9c"),
    ("other",          "Other",                "#95a5a6"),
]
_NEWS_TOPIC_MAP = {tid: (label, color) for tid, label, color in _NEWS_TOPICS}


@_persisted_cache(300, name="_get_news_pool")
def _get_news_pool(hours=720):
    """Cached pool: full ranked+deduped feed for the requested window.

    All in-memory filtering/sort/paginate happens in get_news_feed() against
    this pool — one cache slot serves every filter combo, so flipping
    chips/search doesn't re-run the 800-row DB pass + scoring.
    """
    df = read_sql(
        """
        SELECT na.article_id AS id, na.title AS headline, na.summary,
               na.url AS source_url, na.source, na.published_at,
               ne.primary_topic, ne.topics, ne.one_liner, ne.why_it_matters,
               ne.key_numbers, ne.what_to_watch, ne.confidence, ne.sentiment,
               ne.classifier_status, ne.image_url
        FROM news_articles na
        LEFT JOIN news_enriched ne ON ne.article_id = na.article_id
        WHERE na.published_at >= datetime('now', ? )
        ORDER BY na.published_at DESC
        LIMIT 2000
        """,
        params=[f"-{int(hours)} hours"],
    )
    if df.empty:
        return []

    now = pd.Timestamp.now(tz="UTC")
    cards = []
    for _, r in df.iterrows():
        label, tier_num, tier_score = _news_tier(r["source"])
        try:
            ts = pd.to_datetime(r["published_at"], errors="coerce", utc=True)
            hours_old = (now - ts).total_seconds() / 3600 if not pd.isna(ts) else 999
        except Exception:
            hours_old = 999
        recency = 0.5 ** (hours_old / 12.0)
        score = tier_score * recency

        summary = (r["summary"] or "").strip()
        words = summary.split()
        if len(words) > 80:
            summary = " ".join(words[:80]) + "…"

        import json as _json
        key_numbers = []
        if r.get("key_numbers") and pd.notna(r.get("key_numbers")):
            try:
                key_numbers = _json.loads(r["key_numbers"]) or []
            except Exception:
                key_numbers = []

        primary_topic = r.get("primary_topic") if pd.notna(r.get("primary_topic")) else None
        topic_label, topic_color = _NEWS_TOPIC_MAP.get(primary_topic or "", (None, None))

        cards.append({
            "id": r["id"],
            "headline": (r["headline"] or "").strip(),
            "summary": summary,
            "source": r["source"],
            "source_label": label,
            "source_tier": tier_num,
            "source_tier_score": tier_score,
            "source_url": r["source_url"],
            "published_at": r["published_at"],
            "age_label": _humanize_age(r["published_at"]),
            "hours_old": round(hours_old, 1),
            "score": round(score, 4),
            "enriched": pd.notna(r.get("classifier_status")) and r.get("classifier_status") == "done",
            "primary_topic": primary_topic,
            "topic_label": topic_label,
            "topic_color": topic_color,
            "one_liner": r.get("one_liner") if pd.notna(r.get("one_liner")) else None,
            "why_it_matters": r.get("why_it_matters") if pd.notna(r.get("why_it_matters")) else None,
            "key_numbers": key_numbers,
            "n_key_numbers": len(key_numbers),
            "what_to_watch": r.get("what_to_watch") if pd.notna(r.get("what_to_watch")) else None,
            "confidence": r.get("confidence") if pd.notna(r.get("confidence")) else None,
            "sentiment": r.get("sentiment") if pd.notna(r.get("sentiment")) else None,
            "image_url": r.get("image_url") if "image_url" in r and pd.notna(r.get("image_url")) else None,
        })

    cards.sort(key=lambda c: c["score"], reverse=True)

    # Dedupe: first-7-word fingerprint overlap >80% (catches "same story, 12 outlets").
    def _fingerprint(text):
        toks = [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 3]
        return set(toks[:7])

    kept, seen_prints = [], []
    for c in cards:
        fp = _fingerprint(c["headline"])
        if not fp:
            continue
        dup = any(
            len(fp & sp) >= 5 and len(fp & sp) / max(1, min(len(fp), len(sp))) > 0.8
            for sp in seen_prints
        )
        if dup:
            continue
        kept.append(c)
        seen_prints.append(fp)
    return kept


_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, None: 0}


def get_news_feed(
    topic=None, tier=None, limit=80,
    q=None, sentiment=None, confidence=None,
    hours=168, sort="smart", page=1, page_size=24,
):
    """Filter + sort + paginate over the cached news pool.

    All inputs are user-facing query params from /news. The heavy work
    (DB + scoring + dedupe) is cached upstream in _get_news_pool — this
    function is pure in-memory transformation.
    """
    pool_hours = max(int(hours), 720)  # always cache 30d; filter window in-memory
    pool = _get_news_pool(hours=pool_hours)

    # Window filter
    pool_in_window = [c for c in pool if c["hours_old"] <= int(hours)]

    # Topic counts for tabs — computed over window, BEFORE other filters,
    # so chip badges show "what's available if I switched to this topic".
    topic_counts = {tid: 0 for tid, _, _ in _NEWS_TOPICS}
    for c in pool_in_window:
        topic_counts[c.get("primary_topic") or "other"] = (
            topic_counts.get(c.get("primary_topic") or "other", 0) + 1
        )

    filtered = pool_in_window

    if topic:
        def _topic_match(c):
            if c.get("primary_topic"):
                return c["primary_topic"] == topic
            t_lower = (c["headline"] or "").lower() + " " + (c["summary"] or "").lower()
            return topic.lower().replace("_", " ") in t_lower
        filtered = [c for c in filtered if _topic_match(c)]

    if tier:
        tier_int = int(tier)
        filtered = [c for c in filtered if c["source_tier"] == tier_int]

    if sentiment and sentiment != "all":
        filtered = [c for c in filtered if c.get("sentiment") == sentiment]

    if confidence and confidence != "all":
        min_rank = _CONFIDENCE_RANK.get(confidence, 0)
        filtered = [c for c in filtered if _CONFIDENCE_RANK.get(c.get("confidence")) >= min_rank]

    if q:
        q_lower = q.strip().lower()
        if q_lower:
            def _hit(c):
                blob = " ".join([
                    c.get("headline") or "", c.get("summary") or "",
                    c.get("one_liner") or "", c.get("why_it_matters") or "",
                ]).lower()
                return q_lower in blob
            filtered = [c for c in filtered if _hit(c)]

    # Sort
    if sort == "recent":
        filtered.sort(key=lambda c: c["hours_old"])
    elif sort == "trust":
        filtered.sort(key=lambda c: (-c["source_tier_score"], c["hours_old"]))
    elif sort == "numbers":
        filtered.sort(key=lambda c: (-c["n_key_numbers"], -c["score"]))
    else:  # "smart" (default) — already sorted by score in pool
        filtered.sort(key=lambda c: -c["score"])

    total_filtered = len(filtered)
    page = max(1, int(page))
    page_size = max(1, int(page_size))
    total_pages = max(1, (total_filtered + page_size - 1) // page_size)
    if page > total_pages:
        page = total_pages
    start = (page - 1) * page_size
    page_cards = filtered[start:start + page_size]

    return {
        "cards": page_cards,
        "total": total_filtered,
        "total_filtered": total_filtered,
        "total_pool": len(pool_in_window),
        "page": page,
        "total_pages": total_pages,
        "page_size": page_size,
        "tier_counts": {
            1: sum(1 for c in pool_in_window if c["source_tier"] == 1),
            2: sum(1 for c in pool_in_window if c["source_tier"] == 2),
            3: sum(1 for c in pool_in_window if c["source_tier"] == 3),
        },
        "sentiment_counts": {
            "bullish": sum(1 for c in pool_in_window if c.get("sentiment") == "bullish"),
            "bearish": sum(1 for c in pool_in_window if c.get("sentiment") == "bearish"),
            "neutral": sum(1 for c in pool_in_window if c.get("sentiment") == "neutral"),
        },
        "topic_counts": topic_counts,
        "topics": _NEWS_TOPICS,
        "n_enriched": sum(1 for c in pool_in_window if c["enriched"]),
        "n_with_image": sum(1 for c in pool_in_window if c.get("image_url")),
    }


# ── Pick outcomes (live equity curve) ──
# Built 2026-05-29. The factor model is hypothesis; pick_outcomes is the
# realization. ADR 0028 ships SIGNAL_WEIGHTS_RETURN/SHARPE on backtest t-stats;
# this surface shows what live picks actually did, per tier × window.

@_persisted_cache(300, name="get_pick_outcomes_summary")
def get_pick_outcomes_summary(top_n=10):
    """Returns aggregate stats per (tier, window) for all picks AND for the top-N
    portfolio (the actual tradable subset).

    Shape:
    {
      "as_of": "2026-05-29T...",
      "bench_max_date": "2026-04-30",
      "bench_staleness_days": 29,
      "by_window_tier": [
        {"window_days": 20, "cap_tier": "LARGE", "scope": "all",      "n": ..., "avg_fwd": ..., "avg_excess": ..., "hit_rate": ...},
        {"window_days": 20, "cap_tier": "LARGE", "scope": "top_10",   ...},
        ...
      ],
      "rank_deciles": [
        {"cap_tier": "LARGE", "window_days": 20, "decile": 1, "n": ..., "avg_fwd": ..., "avg_excess": ...},
        ...
      ],
      "time_series": [
        {"pick_date": "2026-05-01", "cap_tier": "LARGE", "window_days": 20, "avg_fwd_top_n": ..., "avg_excess_top_n": ...},
        ...
      ]
    }
    """
    base = read_sql(
        "SELECT sid, pick_date, window_days, cap_tier, rank_at_pick, "
        "       fwd_return_pct, bench_return_pct, excess_return_pct, bench_index "
        "FROM pick_outcomes"
    )
    bench_max = read_sql(
        "SELECT MAX(trade_date) AS d FROM nse_index_history WHERE index_symbol='NIFTY 50'"
    ).iloc[0]["d"]

    from datetime import datetime as _dt
    bench_staleness = None
    if bench_max:
        try:
            bench_staleness = (_dt.now().date() - _dt.fromisoformat(bench_max).date()).days
        except Exception:
            pass

    by_window_tier = []
    if not base.empty:
        # all-picks aggregate
        for (w, t), g in base.groupby(["window_days", "cap_tier"]):
            by_window_tier.append({
                "window_days": int(w),
                "cap_tier": t,
                "scope": "all",
                "n": int(len(g)),
                "n_dates": int(g["pick_date"].nunique()),
                "avg_fwd": round(float(g["fwd_return_pct"].mean()), 3),
                "median_fwd": round(float(g["fwd_return_pct"].median()), 3),
                "avg_excess": (round(float(g["excess_return_pct"].mean()), 3)
                               if g["excess_return_pct"].notna().any() else None),
                "hit_rate": round(100.0 * (g["fwd_return_pct"] > 0).mean(), 1),
                "n_excess_obs": int(g["excess_return_pct"].notna().sum()),
            })

        # top-N portfolio aggregate (the actually-tradable basket)
        top = base[base["rank_at_pick"] <= top_n]
        for (w, t), g in top.groupby(["window_days", "cap_tier"]):
            by_window_tier.append({
                "window_days": int(w),
                "cap_tier": t,
                "scope": f"top_{top_n}",
                "n": int(len(g)),
                "n_dates": int(g["pick_date"].nunique()),
                "avg_fwd": round(float(g["fwd_return_pct"].mean()), 3),
                "median_fwd": round(float(g["fwd_return_pct"].median()), 3),
                "avg_excess": (round(float(g["excess_return_pct"].mean()), 3)
                               if g["excess_return_pct"].notna().any() else None),
                "hit_rate": round(100.0 * (g["fwd_return_pct"] > 0).mean(), 1),
                "n_excess_obs": int(g["excess_return_pct"].notna().sum()),
            })

    # Rank-decile analysis (20d only — the canonical window)
    rank_deciles = []
    deciles_df = read_sql(
        """
        WITH ranked AS (
            SELECT cap_tier, fwd_return_pct, excess_return_pct,
                   NTILE(10) OVER (PARTITION BY pick_date, cap_tier ORDER BY rank_at_pick) AS d
            FROM pick_outcomes WHERE window_days = 20
        )
        SELECT cap_tier, d AS decile, COUNT(*) n,
               AVG(fwd_return_pct) avg_fwd,
               AVG(excess_return_pct) avg_excess
        FROM ranked GROUP BY cap_tier, d ORDER BY cap_tier, d
        """
    )
    for _, row in deciles_df.iterrows():
        rank_deciles.append({
            "cap_tier": row["cap_tier"],
            "window_days": 20,
            "decile": int(row["decile"]),
            "n": int(row["n"]),
            "avg_fwd": round(float(row["avg_fwd"]), 3) if pd.notna(row["avg_fwd"]) else None,
            "avg_excess": round(float(row["avg_excess"]), 3) if pd.notna(row["avg_excess"]) else None,
        })

    # Time series of avg top-N fwd return per pick_date (20d window)
    time_series = []
    ts_df = read_sql(
        """
        SELECT pick_date, cap_tier,
               AVG(fwd_return_pct) avg_fwd,
               AVG(excess_return_pct) avg_excess,
               COUNT(*) n
        FROM pick_outcomes
        WHERE window_days = 20 AND rank_at_pick <= ?
        GROUP BY pick_date, cap_tier
        ORDER BY pick_date, cap_tier
        """,
        params=[top_n],
    )
    for _, row in ts_df.iterrows():
        time_series.append({
            "pick_date": row["pick_date"],
            "cap_tier": row["cap_tier"],
            "window_days": 20,
            "avg_fwd_top_n": round(float(row["avg_fwd"]), 3) if pd.notna(row["avg_fwd"]) else None,
            "avg_excess_top_n": (round(float(row["avg_excess"]), 3)
                                  if pd.notna(row["avg_excess"]) else None),
            "n": int(row["n"]),
        })

    return {
        "as_of": pd.Timestamp.now().isoformat(timespec="seconds"),
        "bench_max_date": bench_max,
        "bench_staleness_days": bench_staleness,
        "top_n": top_n,
        "by_window_tier": by_window_tier,
        "rank_deciles": rank_deciles,
        "time_series": time_series,
    }


# ── Re-exports from cockpit_ops ──
# Stage 2 split (2026-05-26) moved Ops functions to cockpit_ops/api.py, but the
# main cockpit's /model page (and a few other surfaces) still calls them through
# `api.get_model_overview()`. Re-export at the very end of this module — after
# every cockpit.api function is fully defined — so the back-import from
# cockpit_ops (which `from cockpit.api import _ttl_cache, _persisted_cache`) sees
# a fully-populated module. Anything imported here also stays available as
# `cockpit.api.<name>` for callers that haven't been migrated.
from cockpit_ops.api import (  # noqa: E402
    get_model_overview,
    get_backtest_roster,
)

