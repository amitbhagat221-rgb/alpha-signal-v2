"""
Alpha Signal Cockpit — page data for the trading cockpit (:3000).

Shared concepts (picks and the pick gate, a stock, prices/returns, regime,
changes, dossiers) are named read-models in views.py; this module adds the
per-page shaping, caching and the page-specific one-off queries.
"""

import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import db
import views
from db import read_sql


# Cache decorators + JSON coercion live in cockpit/_shared.py so cockpit_ops
# can import them without pulling in this 3,000-LOC module.
from cockpit._shared import _ttl_cache, _persisted_cache, safe_json_records


# ═══════════════════════════════════════════════════
# A1-A12: NEW DATA FUNCTIONS
# ═══════════════════════════════════════════════════

# Batch reads keyed by a list of sids (views.latest_rows / views.native_rows): `/`
# and `/actions` answer each question for every sid in one `WHERE sid IN (...)`
# query; the per-sid functions delegate to them.

@_ttl_cache(60)
def get_stock_price_metrics_batch(sids):
    """A1 for many sids at once → {sid: metrics} ({} when <5 prices)."""
    return views.price_metrics(sids)


@_ttl_cache(60)
def get_stock_price_metrics(sid):
    """A1: Returns, RSI-14, 52W high/low from stock_prices."""
    return get_stock_price_metrics_batch([sid]).get(sid, {})


_CONSENSUS_COLS = (
    "price_target, price_target_median, price_target_high, price_target_low, "
    "total_analysts, buy_pct, eps_growth_pct, revenue_growth_pct, forward_eps, "
    "recommendation_key, recommendation_mean, "
    "n_strong_buy, n_buy, n_hold, n_sell, n_strong_sell, "
    "pt_source, next_earnings_date, rating_mix_history, "
    "price_target_prev, price_target_changed_at, fetched_at"
)


@_ttl_cache(60)
def get_analyst_consensus_batch(sids):
    """A2 for many sids at once → {sid: consensus dict} ({} when uncovered)."""
    sids, ph = views.sid_params(sids)
    out = {sid: {} for sid in sids}
    if not sids:
        return out
    cmp_by_sid = {sid: close for sid, (close, _) in views.latest_close(sids).items()}
    for r in views.native_rows(f"SELECT sid, {_CONSENSUS_COLS} FROM analyst_consensus WHERE sid IN ({ph})",
                               sids):
        sid = r.pop("sid")
        out[sid] = _enrich_consensus(r, cmp_by_sid.get(sid))
    return out


@_ttl_cache(60)
def get_analyst_consensus(sid):
    """A2: Price target, analyst count, buy%, growth from analyst_consensus.

    Includes Tier-1 extended yfinance fields (added 2026-05-23): median PT,
    high/low range, rating mix counts, qualitative recommendation key.
    """
    return get_analyst_consensus_batch([sid]).get(sid, {})


def _enrich_consensus(r, cmp):
    """Derived A2 fields on one analyst_consensus row; `cmp` = latest close."""
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
    if cmp:
        if cmp > 0:
            r["current_price"] = round(cmp, 2)
            # Display guard: never surface an implausible PT (>3x / <0.33x the
            # price = Yahoo garbage for thin-coverage small-caps). Mirrors the
            # source guard in sources/yfinance_analyst.py so a leaked row can't
            # reach the user as a confident "+3474%" target.
            _pt = r.get("price_target")
            if _pt and (_pt > 3 * cmp or _pt < 0.33 * cmp):
                for _k in ("price_target", "price_target_median",
                           "price_target_high", "price_target_low"):
                    r[_k] = None
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
    quarters = db.rows(
        "SELECT end_date, promoter_pct, fii_pct, mf_pct, dii_pct, "
        "public_pct, pledge_pct, insurance_pct, retail_hni_pct "
        "FROM shareholding WHERE sid = ? AND end_date > '1900-01-01' "
        "ORDER BY end_date DESC LIMIT 6",
        [sid],
    )
    # Compute QoQ changes (older quarter is in the next row since we're DESC)
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
    return {
        "trades": db.rows(
            "SELECT person_category, transaction_type, shares, value_lakhs, trade_date "
            "FROM insider_trades WHERE sid = ? AND trade_date >= date('now', '-180 days') "
            "ORDER BY trade_date DESC LIMIT 10",
            [sid],
        ),
        "signal": get_insider_signal_batch([sid]).get(sid, {}),
    }


@_ttl_cache(60)
def get_insider_signal_batch(sids):
    """Latest insider_signals row per sid → {sid: {signal_type, strength,
    score_impact, description}} ({} when the sid has none)."""
    out = {sid: {} for sid in views.sid_params(sids)[0]}
    for r in views.latest_rows("insider_signals",
                               "signal_type, strength, score_impact, description", sids):
        out[r.pop("sid")] = r
    return out


def get_stock_news(sid):
    """A5: Latest 5 news articles for a stock."""
    return db.rows(
        "SELECT na.title, na.source, na.published_at, na.url "
        "FROM news_articles na "
        "JOIN news_article_stocks nas ON na.article_id = nas.article_id "
        "WHERE nas.sid = ? ORDER BY na.published_at DESC LIMIT 5",
        [sid],
    )


def get_bulk_deals(sid):
    """A6: Recent bulk/block deals for a stock."""
    return db.rows(
        "SELECT client_name, buy_sell, quantity, price, deal_date, deal_type "
        "FROM bulk_deals WHERE sid = ? ORDER BY deal_date DESC LIMIT 10",
        [sid],
    )


# regulatory_signals names two sectors differently from `stocks` — map both ways so
# a query never silently misses ~1.6k rows (Gillette dossier bug, 2026-05-23).
_REGULATORY_SECTOR_ALIASES = {
    "Financials": ["Financials", "Financial Services"],
    "Information Technology": ["Information Technology", "IT"],
}


def get_sector_regulatory(sector, n=10, material=False):
    """Regulatory events touching `sector` in the last 90 days, newest first.

    material=True keeps only major/moderate-magnitude, high/medium-confidence
    signals (the stock page's A7 block); otherwise every signal with a direction
    (the sector pages). `published_at` is RFC 2822 text, so order by julianday()
    — a lexicographic sort put 2023 "Wed" articles above 2025 "Sat" ones."""
    if not sector:
        return []
    aliases = _REGULATORY_SECTOR_ALIASES.get(sector, [sector])
    rule = ("rs.magnitude IN ('major', 'moderate') AND rs.confidence IN ('high', 'medium')"
            if material else "rs.direction IS NOT NULL")
    return db.rows(
        f"SELECT re.event_id, re.published_at, re.title, rs.direction, rs.magnitude, "
        f"rs.time_horizon, rs.confidence, rs.ai_reasoning "
        f"FROM regulatory_events re "
        f"JOIN regulatory_signals rs ON rs.event_id = re.event_id "
        f"WHERE rs.sector IN ({','.join('?' * len(aliases))}) AND {rule} "
        f"  AND julianday('now') - julianday(re.published_at) <= 90 "
        f"ORDER BY julianday(re.published_at) DESC LIMIT ?",
        list(aliases) + [n],
    )


def get_earnings_upcoming(sid=None):
    """A8: Upcoming earnings events."""
    if sid:
        return db.rows(
            "SELECT date, purpose, bm_desc FROM earnings_calendar "
            "WHERE sid = ? AND date >= date('now') ORDER BY date LIMIT 3",
            [sid],
        )
    return db.rows(
        "SELECT ec.date, ec.symbol, s.name, ec.purpose, ec.sid "
        "FROM earnings_calendar ec JOIN stocks s ON ec.sid = s.sid "
        "WHERE ec.date >= date('now') AND ec.date <= date('now', '+14 days') "
        "ORDER BY ec.date LIMIT 10",
    )


@_ttl_cache(60)
def _dossier_index():
    """views.dossier_index(), parsed once a minute rather than per get_dossier() call."""
    return views.dossier_index()


@_ttl_cache(60)
def get_dossier(sid):
    """A9: the newest published AI dossier for `sid` (≤ views.DOSSIER_MAX_AGE_DAYS
    old; {} when missing or it failed the narrative validator)."""
    return views.published_dossier(_dossier_index().get(sid))


@_ttl_cache(60)
def get_sector_averages():
    """A10: Per-sector average metrics for comparison."""
    recs = db.rows("""
        SELECT dp.sector,
               COUNT(*) as stock_count,
               ROUND(AVG(ds.earnings_yield), 4) as avg_ey,
               ROUND(AVG(ds.piotroski_f), 1) as avg_piotroski,
               ROUND(AVG(dp.final_score), 3) as avg_score,
               ROUND(AVG(ds.consensus_signal), 3) as avg_consensus
        FROM daily_picks dp
        JOIN daily_snapshots ds ON dp.sid = ds.sid
        WHERE dp.pick_date = ?
        AND ds.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots)
        AND dp.sector IS NOT NULL
        GROUP BY dp.sector
    """, [latest_pick_date()])
    return {r["sector"]: r for r in recs}


def get_management_score(sid):
    """Management Quality Scorecard for one stock (signals/management_quality.py).

    Returns None if unscored — financials are excluded (covered by the financial
    sub-model), as are names missing the capital-allocation anchor.
    """
    r = db.one(
        "SELECT * FROM management_scores WHERE sid = ? ORDER BY snapshot_date DESC LIMIT 1",
        [sid])
    if not r:
        return None

    def num(v):
        return v if (v is not None and pd.notna(v)) else None

    def pct(v):
        v = num(v)
        return f"{v*100:.1f}%" if v is not None else "—"

    trend_lbl = {1: "Accumulating", 0: "Stable", -1: "Reducing"}.get(num(r.get("promoter_trend")), "—")
    fscore = num(r.get("f_score"))
    accr = num(r.get("accruals_quality"))
    score = num(r.get("mgmt_quality_score"))
    r["top_pct"] = round(100 - score) if score is not None else None
    r["pillars"] = [
        {"label": "Capital Allocation", "weight": 45, "z": num(r.get("capital_allocation_z")),
         "blurb": "Do they compound capital?",
         "components": [("ROIC", pct(r.get("roic"))), ("ROIIC", pct(r.get("roiic"))),
                        ("FCF margin", pct(r.get("fcf_margin")))]},
        {"label": "Alignment", "weight": 30, "z": num(r.get("alignment_z")),
         "blurb": "Skin in the game?",
         "components": [("Promoter trend", trend_lbl),
                        ("Pledge quality", pct(r.get("pledge_quality"))),
                        ("Promoter signal", f"{num(r.get('promoter_signal')):.2f}" if num(r.get('promoter_signal')) is not None else "—")]},
        {"label": "Credibility", "weight": 25, "z": num(r.get("credibility_z")),
         "blurb": "Are the earnings real?",
         "components": [("Piotroski F", f"{int(fscore)}/9" if fscore is not None else "—"),
                        ("Accruals quality", "✓ clean" if accr == 1 else ("✗ weak" if accr == 0 else "—")),
                        ("Forensic penalty", f"{num(r.get('forensic_penalty')):.2f}" if num(r.get('forensic_penalty')) is not None else "—")]},
    ]
    return r


def get_managerial_ability(sid):
    """Demerjian-Lev-McVay Managerial Ability for one stock (signals/managerial_ability.py).

    A second, ORTHOGONAL management lens beside the scorecard: a DEA operating-
    efficiency frontier within sector, residualised for size/FCF via Tobit — the
    manager-attributable slice of efficiency. Diagnostic only (not a model weight).
    None if unscored (financials, InvITs/REITs/trusts, revenue-implausible names,
    or missing inputs).
    """
    r = db.one(
        "SELECT * FROM managerial_ability_scores WHERE sid = ? ORDER BY snapshot_date DESC LIMIT 1",
        [sid])
    if not r:
        return None

    def num(v):
        return v if (v is not None and pd.notna(v)) else None

    score = num(r.get("ma_score"))
    r["top_pct"] = round(100 - score) if score is not None else None
    eff = num(r.get("dea_efficiency"))
    r["dea_pct"] = round(eff * 100) if eff is not None else None
    r["on_frontier"] = (eff is not None and eff >= 0.999)
    r["gcolor"] = ("score-green" if r.get("grade") in ("A+", "A")
                   else ("score-red" if r.get("grade") in ("C", "D") else ""))
    return r


def get_financial_management(sid):
    """Management lens for FINANCIALS (banks/NBFCs).

    Financials are excluded from the equity scorecard + DLM Managerial Ability
    (ROIC / COGS / DEA-efficiency are meaningless for a lender — they "produce"
    net interest income from deposits, not goods from inputs), so this gives the
    Management tab a lender-appropriate view by re-presenting the financial
    sub-model's already-validated pillar z-scores (financial_signal_scores):
    prudent underwriting, profitability, funding, capitalisation. Diagnostic
    only — the model ranks financials via the sub-model, not this card.
    Returns None for non-financials / unscored names.
    """
    r = db.one(
        "SELECT * FROM financial_signal_scores WHERE sid = ? ORDER BY snapshot_date DESC LIMIT 1",
        [sid])
    if not r:
        return None

    def num(v):
        return v if (v is not None and pd.notna(v)) else None

    def pctv(v):
        v = num(v)
        return f"{v:.2f}%" if v is not None else "—"

    tier = r.get("cap_tier")
    sig = num(r.get("financial_signal"))
    # within-cap_tier percentile of the composite financial signal (higher=better)
    score = None
    if sig is not None and tier:
        peers = read_sql(
            "SELECT financial_signal FROM financial_signal_scores "
            "WHERE cap_tier = ? AND financial_signal IS NOT NULL "
            "AND snapshot_date = (SELECT MAX(snapshot_date) FROM financial_signal_scores)",
            params=[tier])
        if not peers.empty:
            score = round((peers["financial_signal"] <= sig).mean() * 100, 1)
    r["fm_score"] = score
    r["top_pct"] = round(100 - score) if score is not None else None
    grade = None
    if score is not None:
        grade = ("A+" if score >= 90 else "A" if score >= 75 else
                 "B" if score >= 50 else "C" if score >= 25 else "D")
    r["grade"] = grade
    r["gcolor"] = ("score-green" if grade in ("A+", "A")
                   else ("score-red" if grade in ("C", "D") else ""))

    pillars = [
        {"label": "Asset Quality", "blurb": "Do they lend prudently?",
         "z": num(r.get("asset_quality_z")),
         "components": [("Gross NPA", pctv(r.get("gross_npa_pct"))),
                        ("Net NPA", pctv(r.get("net_npa_pct")))]},
        {"label": "Profitability", "blurb": "Earn well on assets?",
         "z": num(r.get("profitability_z")),
         "components": [("Net margin", pctv(r.get("np_margin_pct"))),
                        ("NII margin", pctv(r.get("nii_margin_pct")))]},
        {"label": "Funding", "blurb": "Funded cheaply & stably?",
         "z": num(r.get("funding_z")),
         "components": [("Cost of funds", pctv(r.get("cost_of_funds_pct")))]},
        {"label": "Capital", "blurb": "Well-capitalised?",
         "z": num(r.get("capital_z")), "components": []},
    ]
    r["pillars"] = [p for p in pillars if p["z"] is not None]
    r["n_pillars"] = num(r.get("components_present"))
    return r


def get_portfolio_analytics(portfolio_data, regime):
    """A11: Portfolio-level analytics."""
    all_stocks = [s for stocks in portfolio_data.values() for s in stocks]

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
    ac_by_sid = get_analyst_consensus_batch([s["sid"] for s in all_stocks])
    for s in all_stocks:
        ac = ac_by_sid.get(s["sid"], {})
        if ac.get("pt_upside_pct") is not None:
            upsides.append(ac["pt_upside_pct"])

    avg_upside = round(sum(upsides) / len(upsides), 1) if upsides else None
    avg_score = round(sum(s.get("final_score", 0) for s in all_stocks) / len(all_stocks) * 100, 0) if all_stocks else 0

    # Universe average score
    univ = db.scalar("SELECT AVG(final_score) FROM daily_picks WHERE pick_date = ?", [latest_pick_date()])
    univ_avg = round(univ * 100, 0) if univ else 0

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
      3. Cap-tier mix — picks per pickable tier.

    Returns: {"tilts": [{group, z, label}], "sector_hhi": int, "sector_top3_pct": float,
              "cap_mix": {tier: n}, "n_picks": int} or {} if no picks.
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
    cap_mix = {t: int(cap_counts.get(t, 0)) for t in views.pickable_tiers()}

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


@_ttl_cache(60)
def get_changes(days=1):
    """Recent change events from the diff engine (computed live if the table is empty)."""
    changes = views.changes(days)
    if not changes:
        try:
            from output.diff_engine import compute_changes
            return compute_changes()
        except Exception:
            return []
    return changes


@_ttl_cache(60)
def get_regime():
    """Current VIX regime + allocation weights + display colour."""
    return views.regime() or {"regime": "UNKNOWN", "vix_latest": 0, "vix_20d_avg": 0,
                              "alloc_large": 0.4, "alloc_mid": 0.3, "alloc_small": 0.3}


def get_top_picks(tier=None, top=5):
    """The published picks (views.picks — one gate: integrity != FAIL)
    with stock metadata: `top` of one tier, or {tier: top N} for every pickable tier."""
    df = views.picks(latest_pick_date(), tier=tier)
    if tier:
        return safe_json_records(df.head(top))
    return {t: safe_json_records(df[df["cap_tier"] == t].head(top)) for t in views.pickable_tiers()}


@_ttl_cache(60)
def latest_pick_date():
    """MAX(pick_date) in daily_picks (None when empty) — the date every "today's
    picks" query in this module pins to."""
    return views.latest_pick_date()


_DOMINANT_SIGNAL_SOURCES = [
    ("consensus_signals", "consensus_signal", "Consensus"),
    ("promoter_signals", "promoter_signal", "Promoter"),
    ("piotroski_scores", "f_score", "Piotroski"),
    ("accruals_scores", "accruals_signal", "Accruals"),
    ("insider_signals", "score_impact", "Insider"),
]


@_ttl_cache(60)
def get_dominant_signal_batch(sids):
    """Strongest two signals per sid (display string under the ticker) →
    {sid: "Consensus: 0.82 | Piotroski: 8/9"}; "" when the sid has none."""
    values = {sid: {} for sid in views.sid_params(sids)[0]}
    for table, col, label in _DOMINANT_SIGNAL_SOURCES:
        try:
            recs = views.latest_rows(table, f"[{col}]", sids)
        except Exception:
            continue
        for r in recs:
            try:
                if r[col] is not None:
                    values[r["sid"]][label] = float(r[col])
            except (TypeError, ValueError):
                pass

    out = {}
    for sid, signals in values.items():
        # Top 2 signals by |value|
        sorted_sigs = sorted(signals.items(), key=lambda x: abs(x[1]), reverse=True)
        parts = []
        for name, val in sorted_sigs[:2]:
            if name == "Piotroski":
                parts.append(f"{name}: {int(val)}/9")
            else:
                parts.append(f"{name}: {val:.2f}")
        out[sid] = " | ".join(parts)
    return out


def get_heatmap_data():
    """Every ranked stock by tier (best score first), then the non-pickable tiers
    (MICRO) from `stocks` with score None: they are classified and their signals
    computed, but never ranked into daily_picks."""
    unpickable = views.unpickable_tiers()
    ph = ",".join("?" * len(unpickable)) or "NULL"
    df = read_sql(f"""
        SELECT dp.sid, s.ticker, s.name, dp.final_score as score, dp.cap_tier
        FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid
        WHERE dp.pick_date = ?
          AND s.cap_tier NOT IN ({ph})
        ORDER BY dp.cap_tier, dp.final_score DESC
    """, params=[latest_pick_date(), *unpickable])
    result = {}
    for tier in views.pickable_tiers():
        tier_df = df[df["cap_tier"] == tier]
        result[tier] = tier_df[["sid", "ticker", "name", "score"]].to_dict("records")
    for tier in unpickable:
        rows = read_sql("SELECT sid, ticker, name, NULL AS score FROM stocks "
                        "WHERE cap_tier = ? ORDER BY ticker", params=[tier])
        if not rows.empty:
            result[tier] = rows.to_dict("records")
    return result


def search_stocks(query):
    """Search stocks by ticker or name."""
    q = f"%{query}%"
    return db.rows(
        "SELECT sid, ticker, name, sector, cap_tier FROM stocks "
        "WHERE ticker LIKE ? OR name LIKE ? LIMIT 20",
        [q, q],
    )


def get_stock_detail(sid):
    """Full stock data bundle for the detail view: views.stock(sid) (stocks row,
    newest pick, every registry signal table's newest row, latest close) with the data
    behind the pick already worded (`data`: views.pick_data, ADR 0061)."""
    detail = views.stock(sid)
    if not detail:
        return None
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


def get_price_series_extended(sid, days=365):
    """Extended price series with OHLCV + delivery % for technicals tab.
    NaN → None so FastAPI's JSON encoder doesn't 500 on sparse delivery_pct rows."""
    newest_first = db.rows(
        "SELECT date, open, high, low, close, volume, delivery_pct "
        "FROM stock_prices WHERE sid = ? AND close > 0 "
        "ORDER BY date DESC LIMIT ?",
        [sid, days],
    )
    return newest_first[::-1]  # chronological for the chart


def get_quarterly_financials(sid):
    """10 quarters of income statement + TTM aggregates + YoY growth."""
    df = read_sql(
        "SELECT period, end_date, revenue, net_income, eps, ebitda, "
        "operating_profit, pbt, operating_expenses "
        "FROM quarterly_income WHERE sid = ? AND reporting = 'consolidated' "
        "ORDER BY end_date DESC LIMIT 10",
        params=[sid],
    )
    if df.empty:
        df = read_sql(
            "SELECT period, end_date, revenue, net_income, eps, ebitda, "
            "operating_profit, pbt, operating_expenses "
            "FROM quarterly_income WHERE sid = ? AND reporting = 'standalone' "
            "ORDER BY end_date DESC LIMIT 10",
            params=[sid],
        )
    if df.empty:
        return {"quarters": [], "ttm": {}, "yoy": {}}

    # EBITDA = revenue − operating expenses (the stored column holds the same).
    df["ebitda"] = df["revenue"] - df["operating_expenses"]
    df["ebitda_margin"] = (df["ebitda"] / df["revenue"] * 100).round(1)
    df["pat_margin"] = (df["net_income"] / df["revenue"] * 100).round(1)

    # YoY growth: compare each quarter to the same quarter 4 quarters ago.
    # replace([inf,-inf,nan], None) so divide-by-zero margins (revenue=0) don't 500 the API.
    df_records = (df.sort_values("end_date")
                    .replace([np.inf, -np.inf], np.nan)
                    .astype(object).where(lambda x: x.notna(), None))
    quarters = df_records.to_dict("records")
    for i, q in enumerate(quarters):
        # None (shown "—") without a prior-year quarter: never a missing key, which a
        # template reads as a value and prints as "+0.0%"
        q["revenue_yoy"] = q["pat_yoy"] = None
        if i >= 4:
            prior = quarters[i - 4]
            if prior.get("revenue") and prior["revenue"] > 0 and q.get("revenue") is not None:
                q["revenue_yoy"] = round((q["revenue"] / prior["revenue"] - 1) * 100, 1)
            if prior.get("net_income") and prior["net_income"] != 0 and q.get("net_income") is not None:
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
        "dividends_paid, financing_cash_flow, investing_cash_flow "
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
        # metric='price' excluded: realized year-ahead close, not a PT (ADR 0045).
        "SELECT metric, date, value, change FROM forecast_history "
        "WHERE sid = ? AND metric IN ('eps', 'revenue') ORDER BY date ASC",
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
    return db.rows(
        "SELECT strftime('%Y-%m', trade_date) as month, "
        "SUM(CASE WHEN transaction_type = 'Buy' THEN value_lakhs ELSE 0 END) as buy_value, "
        "SUM(CASE WHEN transaction_type = 'Sell' THEN value_lakhs ELSE 0 END) as sell_value, "
        "COUNT(*) as trade_count "
        "FROM insider_trades "
        "WHERE sid = ? AND trade_date >= date('now', '-730 days') "
        "AND trade_date <= date('now') "
        "GROUP BY month ORDER BY month",
        [sid],
    )


def get_sector_comparison(sid, sector):
    """Sector averages (get_sector_averages) plus the sector's mean D/E."""
    if not sector:
        return {}
    base = dict(get_sector_averages().get(sector) or {
        "avg_ey": None, "avg_piotroski": None, "avg_score": None, "avg_consensus": None,
        "stock_count": 0})

    # Sector median D/E from latest balance sheet per stock in sector
    avg_de = db.scalar(
        """
        SELECT AVG(CASE WHEN abs.total_equity > 0
                        THEN abs.total_debt / abs.total_equity
                        ELSE NULL END) as avg_de
        FROM annual_balance_sheet abs
        JOIN stocks s ON abs.sid = s.sid
        WHERE s.sector = ?
        AND abs.end_date = (SELECT MAX(end_date) FROM annual_balance_sheet WHERE sid = abs.sid)
        """,
        [sector],
    )
    if avg_de is not None:
        base["avg_de"] = round(float(avg_de), 2)

    return base


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
        WHERE dp.pick_date = ?
        AND dp.rank <= 20
        AND (fs.m_score_flag = 'LIKELY_MANIPULATOR' OR fs.z_score_flag = 'DISTRESS')
        ORDER BY dp.rank LIMIT 10
    """, params=[latest_pick_date()])
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


@_persisted_cache(60, name="get_sized_book")
def get_sized_book():
    """Track 3.3c — the HRP-sized book from `portfolio_weights` (latest asof_date).

    Pure read of the persisted table (no recompute-on-read, so the page never
    drifts from the stored book). Per-name HRP weight + percent risk contribution,
    plus the concentration stats that ARE derivable from the rows. Returns None if
    no book has been built yet (table empty) — the template guards on that.

    See portfolio_construction.py + ADR 0044. ADVISORY ONLY (no capital deployed
    until the rank-skill validates)."""
    import config
    rows = read_sql(
        "SELECT pw.sid, s.ticker, pw.name, pw.cap_tier, pw.sector, pw.rank, "
        "       pw.factor_score, pw.weight, pw.marginal_risk_contrib "
        "FROM portfolio_weights pw LEFT JOIN stocks s ON pw.sid = s.sid "
        "WHERE pw.asof_date = (SELECT MAX(asof_date) FROM portfolio_weights) "
        "ORDER BY pw.weight DESC")
    if rows.empty:
        return None

    asof = db.scalar("SELECT MAX(asof_date) FROM portfolio_weights")
    w = rows["weight"].fillna(0.0)
    sector_w = rows.groupby("sector")["weight"].sum().sort_values(ascending=False)
    tier_w = rows.groupby("cap_tier")["weight"].sum()
    hrp = config.PORTFOLIO["hrp"]

    # Expected ~1Y return = book-weighted analyst-consensus PT upside, renormalised
    # over COVERED names (uncovered = no opinion, not 0% — small-caps are often
    # uncovered). Same source (get_analyst_consensus → pt_upside_pct, ADR-0037
    # cleaned) the /portfolio "Expected Return" stat uses, so the two agree; here
    # it's weight-weighted rather than the page's equal-weight. Analyst PTs are
    # ~12-month targets → a ~1-year expected PRICE return (excludes dividends).
    cov_w, cov_wu, cov_n = 0.0, 0.0, 0
    ac_by_sid = get_analyst_consensus_batch(rows["sid"].tolist())
    for r in rows.itertuples():
        ac = ac_by_sid.get(r.sid, {})
        up = ac.get("pt_upside_pct")
        if up is not None and r.weight:
            cov_w += r.weight
            cov_wu += r.weight * up
            cov_n += 1
    er_1y = round(cov_wu / cov_w, 1) if cov_w else None

    return {
        "asof_date": asof,
        "n_names": len(rows),
        "rows": safe_json_records(rows),
        "effective_n": round(float(1.0 / (w ** 2).sum()), 1) if (w ** 2).sum() else 0,
        "sum_weight_pct": round(float(w.sum()) * 100, 1),
        "max_stock_pct": round(float(w.max()) * 100, 1),
        "max_sector_pct": round(float(sector_w.max()) * 100, 1),
        "tier_weights": {t: round(v * 100, 0) for t, v in tier_w.items()},
        "top_sectors": [(s, round(v * 100, 0)) for s, v in sector_w.head(4).items()],
        "cap_stock_pct": round(hrp["max_stock_weight"] * 100, 0),
        "cap_sector_pct": round(hrp["max_sector_weight"] * 100, 0),
        "expected_return_1y": er_1y,                          # weighted PT upside, %
        "er_coverage_n": cov_n,                               # names with a target
        "er_coverage_weight_pct": round(cov_w * 100, 0),      # % of book weight covered
    }


@_persisted_cache(60, name="get_portfolio_bundle")
def get_portfolio_bundle():
    """Single cacheable bundle for /portfolio render — picks + per-stock enrichment
    + analytics in one disk slot, so first-click after restart is fast even though
    we'd otherwise loop ~30 stocks × 2 API calls. 2026-05-25 perf pass."""
    regime = get_regime()
    portfolio_data = get_model_portfolio()
    sids = [s["sid"] for stocks in portfolio_data.values() for s in stocks]
    ac_by_sid = get_analyst_consensus_batch(sids)
    pm_by_sid = get_stock_price_metrics_batch(sids)
    for stocks in portfolio_data.values():
        for s in stocks:
            ac = ac_by_sid.get(s["sid"], {})
            pm = pm_by_sid.get(s["sid"], {})
            s["pt_upside"] = ac.get("pt_upside_pct")
            s["price"] = pm.get("close_price")
            s["return_1m"] = pm.get("return_1m")
            s["price_target"] = ac.get("price_target")
    analytics = get_portfolio_analytics(portfolio_data, regime)
    return {"regime": regime, "portfolio": portfolio_data, "analytics": analytics,
            "sized_book": get_sized_book()}


@_persisted_cache(60, name="get_model_portfolio")
def get_model_portfolio():
    """Model portfolio: top 10 published picks per pickable tier, equal-weighted
    within the tier's regime allocation → {tier.lower(): [stock dicts]}."""
    regime = get_regime()
    result = {}
    for tier in views.pickable_tiers():
        key = tier.lower()
        alloc = regime.get(f"alloc_{key}", 0.33)
        stocks = get_top_picks(tier=tier, top=10)
        if stocks:
            weight_per = (alloc * 100) / len(stocks)
            for s in stocks:
                s["weight"] = round(weight_per, 1)
        result[key] = stocks
    return result


def _conviction_verdicts(surv):
    """Per-name conviction verdict for the holding monitor (reframe 2026-06).

    A multibagger you hold draws down ~40% en route (81% of eventual 3x+ winners
    do) — a stop-loss ejects you from winners. The discriminator between a
    winner-in-drawdown and a loser-grinding is DEPTH + DURATION + whether SECTOR
    momentum and RELATIVE STRENGTH are still intact. Verdicts:
       HOLD   — near highs, or sector momentum AND relative strength intact
       WATCH  — in a drawdown with mixed signals (hold, but monitor)
       REVIEW — the loser signature: deep (≤−50%) + prolonged (≥6mo underwater)
                + sector momentum rolled over + relative strength broken, AND the
                broad small-cap market is NOT itself in a bear (idiosyncratic only)
    Computed from split-adjusted month-end closes (raw bhavcopy → a bonus is a
    fake −50% drop, so we back-adjust survivors via corporate_actions).
    MARKET-REGIME GUARD (2026-06-04): a 15yr sector-index bear stress test
    (tools/multibagger_monitor.py --sector-stress) showed the un-guarded eject
    rule fired at market-wide capitulations (IT @2008 bottom, PSUBank @COVID
    bottom) that then ~doubled — so REVIEW is suppressed to WATCH when NIFTY
    SMALLCAP 250 is itself ≥20% off its trailing peak. Residual limit: an
    idiosyncratic laggard in a recovered market can still mis-flag (no regime
    guard catches that) — treat REVIEW as 'reassess', not a mechanical sell."""
    sids = surv["sid"].dropna().tolist()
    if not sids:
        return {}
    # month-end closes for ALL sids over ~13 months (one row per sid-month)
    me = read_sql(
        "WITH r AS (SELECT sid, date, close, ROW_NUMBER() OVER "
        "(PARTITION BY sid, strftime('%Y-%m', date) ORDER BY date DESC) rn "
        "FROM stock_prices WHERE date >= date('now','-400 day') AND close > 0) "
        "SELECT sid, date, close FROM r WHERE rn = 1")
    if me.empty:
        return {}
    me["ym"] = pd.to_datetime(me["date"]).dt.to_period("M")
    mat = me.pivot_table(index="ym", columns="sid", values="close", aggfunc="last").sort_index()
    if len(mat) < 7:
        return {}
    sector = read_sql("SELECT sid, sector FROM stocks").set_index("sid")["sector"]

    # split/bonus-adjust the survivor columns (medians wash out for baskets)
    ca = read_sql(
        "SELECT sid, ex_date, ind, subject FROM corporate_actions "
        "WHERE ind IN ('SPLIT','BONUS') AND ex_date >= date('now','-400 day') AND sid IS NOT NULL")
    month_ts = mat.index.to_timestamp("M")
    for _, r in ca.iterrows():
        sid = r["sid"]
        if sid not in mat.columns:
            continue
        s = str(r["subject"]).lower()
        f = 1.0
        if r["ind"] == "SPLIT" or "split" in s:
            m = re.search(r"from\s*rs[.]?\s*([\d.]+).*?to\s*rs[.]?\s*([\d.]+)", s)
            if m and float(m.group(2)) > 0:
                f = float(m.group(1)) / float(m.group(2))
        elif r["ind"] == "BONUS" or "bonus" in s:
            m = re.search(r"(\d+)\s*:\s*(\d+)", s)
            if m and int(m.group(2)) > 0:
                f = (int(m.group(1)) + int(m.group(2))) / int(m.group(2))
        if f > 1.0:
            mask = month_ts < pd.Timestamp(r["ex_date"])
            mat.loc[mask, sid] = mat.loc[mask, sid] / f

    n = len(mat)
    k = min(6, n - 1)                       # ~6-month lookback for momentum
    ret6 = mat.iloc[-1] / mat.iloc[-1 - k] - 1.0
    mkt6 = ret6.median(skipna=True)
    # sector-relative 6m momentum (median of sector's 6m returns − market)
    sec_mom = {}
    for sec, grp in sector.groupby(sector):
        cols = [c for c in mat.columns if c in grp.index]
        if len(cols) >= 4:
            sec_mom[sec] = float(ret6[cols].median(skipna=True) - mkt6)

    # market-regime guard: don't EJECT into a market-wide small-cap bear (the
    # weakness must be idiosyncratic). NIFTY SMALLCAP 250 is the broad reference
    # for these upper-small/mid names (same index as scoring/regime_smallcap).
    market_dd, market_bear = 0.0, False
    try:
        sc = read_sql(
            "SELECT trade_date, close FROM nse_index_history "
            "WHERE index_symbol='NIFTY SMALLCAP 250' AND trade_date >= date('now','-400 day') "
            "AND close > 0 ORDER BY trade_date")
        if len(sc) >= 20:
            scm = sc.assign(ym=pd.to_datetime(sc["trade_date"]).dt.to_period("M")) \
                    .groupby("ym")["close"].last()
            market_dd = float(scm.iloc[-1] / scm.cummax().iloc[-1] - 1.0)
            market_bear = market_dd <= -0.20            # textbook bear line
    except Exception:
        pass                                            # missing index → guard inactive

    out = {}
    for sid in sids:
        if sid not in mat.columns:
            continue
        p = mat[sid].dropna()
        if len(p) < 7:
            continue
        peak = p.cummax()
        dd = float(p.iloc[-1] / peak.iloc[-1] - 1.0)
        uw = int(((p / peak - 1.0) < -0.20).sum())
        rs6 = float((p.iloc[-1] / p.iloc[-1 - min(k, len(p) - 1)] - 1.0) - mkt6)
        sm = sec_mom.get(sector.get(sid), 0.0)
        review = dd <= -0.50 and uw >= 6 and sm < 0 and rs6 < 0
        if review and not market_bear:                  # eject only idiosyncratic weakness
            verdict = "REVIEW"
        elif dd > -0.25 or (sm >= 0 and rs6 >= 0):
            verdict = "HOLD"
        else:
            verdict = "WATCH"
        out[sid] = {"verdict": verdict, "drawdown": round(dd, 3),
                    "months_underwater": uw, "rel_strength": round(rs6, 3),
                    "sector_mom": round(sm, 3), "market_dd": round(market_dd, 3)}
    return out


@_ttl_cache(60)
def get_multibagger_overview(limit=60):
    """Multibagger watchlist — the SEPARATE 3-stage funnel (plan 0008), kept OUT
    of daily_picks. Returns the small-cap regime banner, the gate funnel, and the
    survivor watchlist.

    Honest framing baked into the payload: the value is the GATES (a junk-stripped
    watchlist), NOT the ranking — the ranking edge is validated zero-to-negative
    across regimes (worst in uptrends), see ADR 0039. `regime_favorable=0` flags
    the validated-unfavourable case so the page can disclose it."""
    snap = db.scalar("SELECT MAX(snapshot_date) FROM multibagger_scores")
    if snap is None:
        return {"available": False}

    rows = read_sql(
        "SELECT m.*, s.name, s.sector FROM multibagger_scores m "
        "JOIN stocks s ON m.sid = s.sid WHERE m.snapshot_date = ?",
        params=[snap],
    )
    if rows.empty:
        return {"available": False}

    n_uni = len(rows)
    n_gates = int(rows["passed_gates"].sum())
    n_surv = int(rows["survived"].sum())
    surv = (rows[rows["survived"] == 1]
            .sort_values("multibagger_score", ascending=False)
            .head(limit))

    # ── gate / hurdle fail tally (funnel detail) ──
    from collections import Counter

    def _tally(col, mask):
        c = Counter()
        for v in rows.loc[mask, col].dropna():
            for tok in str(v).split(","):
                if tok:
                    c[tok] += 1
        return [{"reason": k, "n": v} for k, v in c.most_common()]

    gate_fails = _tally("gate_fail", rows["passed_gates"] == 0)
    hurdle_fails = _tally("hurdle_fail",
                          (rows["passed_gates"] == 1) & (rows["passed_hurdles"] == 0))

    # ── regime banner: stored (scoring-time) value + live EMA context ──
    regime = rows["smallcap_regime"].iloc[0]
    favorable = int(rows["regime_favorable"].iloc[0]) if pd.notna(rows["regime_favorable"].iloc[0]) else None
    try:
        from scoring.regime_smallcap import classify
        reg_detail = classify()
    except Exception:
        reg_detail = {}

    tier_counts = (surv["cap_tier"].value_counts().to_dict() if not surv.empty else {})

    # ── per-name conviction verdict (the holding monitor — reframe 2026-06) ──
    verdicts = _conviction_verdicts(surv) if not surv.empty else {}
    surv_records = safe_json_records(surv)
    for rec in surv_records:
        v = verdicts.get(rec.get("sid"))
        rec["conviction"] = v["verdict"] if v else None
        rec["dd_pct"] = v["drawdown"] if v else None
        rec["sector_mom"] = v["sector_mom"] if v else None
        rec["rel_strength"] = v["rel_strength"] if v else None
    conv_counts = Counter(v["verdict"] for v in verdicts.values())
    market_dd = next((v.get("market_dd") for v in verdicts.values()), None)

    return {
        "available": True,
        "snapshot_date": snap,
        "market_dd": market_dd,
        "market_guard_active": (market_dd is not None and market_dd <= -0.20),
        "regime": regime,
        "regime_favorable": favorable,
        "regime_detail": reg_detail,
        "funnel": {"universe": n_uni, "passed_gates": n_gates, "survived": n_surv},
        "gate_fails": gate_fails,
        "hurdle_fails": hurdle_fails,
        "survivors": surv_records,
        "tier_counts": tier_counts,
        "conviction_counts": dict(conv_counts),
    }


# ── Mutual Fund research section — extracted to cockpit/mf.py (2026-05-30) ──
# Re-exported so existing `api.get_mf_*` call sites in cockpit/app.py keep working.
# cockpit.mf imports only db.read_sql + cockpit._shared, so no circular import.
from cockpit.mf import (
    get_mf_universe_overview, get_mf_category_heatmap, get_mf_detail,
    get_mf_nav_series, get_mf_rolling_returns, get_mf_peer_rank,
    get_mf_holdings, get_mf_compare, get_mf_search,
)


# ── Sector / industry pages ──
# One function per question, parametrised by the grouping column (`by` = "sector"
# or "industry" — both are `stocks` columns); sector_metadata is keyed by either.

_GROUPS = ("sector", "industry")


def _group_col(by):
    if by not in _GROUPS:
        raise ValueError(f"group must be one of {_GROUPS}, got {by!r}")
    return by


@_ttl_cache(60)
def get_group_overview(by):
    """Per-sector or per-industry rollup of today's ranking. avg_score is
    MARKET-CAP WEIGHTED over the stocks that have a score (a ₹10L cr leader is not
    diluted by 50 micro-caps); an industry row carries its parent sector. Adds the
    sector's macro signal, breadth (% scoring ≥ 0.55) and the top-3 tickers."""
    col = _group_col(by)
    parent = ", s.sector AS sector" if col == "industry" else ""
    df = read_sql(f"""
        SELECT s.{col} AS {col}{parent},
               COUNT(*) AS stocks,
               ROUND(
                 SUM(dp.final_score * s.market_cap_cr) /
                 NULLIF(SUM(CASE WHEN dp.final_score IS NOT NULL THEN s.market_cap_cr ELSE 0 END), 0),
                 3
               ) AS avg_score
        FROM stocks s
        LEFT JOIN daily_picks dp
          ON dp.sid = s.sid
         AND dp.pick_date = ?
        WHERE s.{col} IS NOT NULL AND s.ticker IS NOT NULL
        GROUP BY s.{col}{", s.sector" if parent else ""}
        ORDER BY avg_score DESC NULLS LAST
    """, params=[latest_pick_date()])
    if df.empty:
        return []

    # Macro signal of the (parent) sector — latest snapshot only; the table keeps history
    macro = read_sql("""
        SELECT sector, macro_score, macro_signal, macro_detail
        FROM macro_sector_signals
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM macro_sector_signals)
    """)
    if not macro.empty:
        df = df.merge(macro, on="sector", how="left")

    breadth = read_sql(f"""
        SELECT s.{col},
               ROUND(100.0 * SUM(CASE WHEN dp.final_score >= 0.55 THEN 1 ELSE 0 END) / COUNT(*), 1)
                   AS breadth_pct
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE dp.pick_date = ?
          AND s.{col} IS NOT NULL
        GROUP BY s.{col}
    """, params=[latest_pick_date()])
    if not breadth.empty:
        df = df.merge(breadth, on=col, how="left")

    top_n = read_sql(f"""
        WITH ranked AS (
            SELECT s.{col}, s.ticker, dp.final_score,
                   ROW_NUMBER() OVER (PARTITION BY s.{col} ORDER BY dp.final_score DESC) AS r
            FROM daily_picks dp
            JOIN stocks s ON s.sid = dp.sid
            WHERE dp.pick_date = ?
              AND s.{col} IS NOT NULL
        )
        SELECT {col}, ticker FROM ranked WHERE r <= 3
    """, params=[latest_pick_date()])
    top_by = {}
    for _, r in top_n.iterrows():
        top_by.setdefault(r[col], []).append(r["ticker"])
    df["top_3"] = df[col].map(lambda g: ", ".join(top_by.get(g, [])))
    return df.to_dict("records")


def get_group_list(by):
    """Sorted sectors or industries that have any listed stock."""
    col = _group_col(by)
    return read_sql(
        f"SELECT DISTINCT {col} FROM stocks "
        f"WHERE {col} IS NOT NULL AND ticker IS NOT NULL ORDER BY {col}"
    )[col].tolist()


get_group_metadata = views.sector_narrative   # sector_metadata is keyed by sector OR industry


def get_group_top_players(by, name, n=10):
    """The group's n largest LISTED stocks by market cap, with our score/rank.

    share_pct = share of the group's full listed market cap (not of the top-n
    sum, which showed a lone dominant ticker at 100%). Stocks without a market
    cap (no fundamentals) are left out. For industry share incl. private /
    unlisted players see get_industry_competitive_landscape."""
    col = _group_col(by)
    df = read_sql(
        f"""
        SELECT s.sid, s.ticker, s.name, s.market_cap_cr,
               COALESCE(dp.final_score, 0) AS final_score,
               COALESCE(dp.rank, NULL)     AS rank
        FROM stocks s
        LEFT JOIN daily_picks dp
          ON dp.sid = s.sid
         AND dp.pick_date = ?
        WHERE s.{col} = ?
          AND s.ticker IS NOT NULL
          AND s.market_cap_cr IS NOT NULL
        ORDER BY s.market_cap_cr DESC
        LIMIT ?
        """,
        params=[latest_pick_date(), name, n],
    )
    if df.empty:
        return []
    df["market_cap_cr"] = df["market_cap_cr"].round(0)
    total_listed = db.scalar(
        f"SELECT COALESCE(SUM(market_cap_cr), 0) "
        f"FROM stocks WHERE {col} = ? AND market_cap_cr IS NOT NULL",
        [name],
    )
    if total_listed and total_listed > 0:
        df["share_pct"] = (100.0 * df["market_cap_cr"] / total_listed).round(1)
    else:
        df["share_pct"] = 0.0
    return df.to_dict("records")


def get_group_picks(by, name, top_n=10, bottom_n=5):
    """Top-N (highest composite) and bottom-N (lowest) ranked stocks in the group."""
    col = _group_col(by)
    df = read_sql(
        f"""
        SELECT s.sid, s.ticker, s.name, dp.final_score, dp.cap_tier
        FROM daily_picks dp
        JOIN stocks s ON s.sid = dp.sid
        WHERE s.{col} = ?
          AND dp.pick_date = ?
        ORDER BY dp.final_score DESC
        """,
        params=[name, latest_pick_date()],
    )
    if df.empty:
        return {"top": [], "bottom": []}
    return {
        "top":    df.head(top_n).to_dict("records"),
        "bottom": df.tail(bottom_n).iloc[::-1].to_dict("records"),
    }


_PIT_NON_FACTOR_COLS = {"sid", "snapshot_date", "cap_tier", "close_price",
                        "reconstructed_at", "fwd_return_20d"}


def get_group_factor_means(by, name):
    """Mean/median of every factor column of the latest daily_snapshots_pit anchor
    across the group's stocks — a descriptive "which factors run hot here" table
    until per-group IC backtests exist. Largest |mean| first."""
    col = _group_col(by)
    df = read_sql(
        f"""
        SELECT pit.*
        FROM daily_snapshots_pit pit
        JOIN stocks s ON s.sid = pit.sid
        WHERE s.{col} = ?
          AND pit.snapshot_date = (SELECT MAX(snapshot_date) FROM daily_snapshots_pit)
        """,
        params=[name],
    )
    if df.empty:
        return []
    rows = []
    for c in df.columns:
        if c in _PIT_NON_FACTOR_COLS:
            continue
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


def get_sector_digest():
    """Front-door payload for /sectors — Plan 0006 Phase C.

    Reads sector_briefs + sector_force_breakdown for the latest snapshot.
    Returns:
      {
        "snapshot_date": "...",
        "buckets": {BOOMING: [...], LIKELY: [...], HEADWIND: [...], QUIET: [...]},
        "forces":  {macro: {positive, negative, neutral}, regulation: {...}, ...},
      }
    Each bucket entry has: sector, macro_score, macro_signal, driver_preview,
    breadth_pct, n_picks_top30, top_picks (≤5), alignment_hint, n_regulatory_30d.
    """
    briefs = read_sql("""
        SELECT sector, n_stocks, mcap_total_cr, macro_score, macro_signal,
               macro_drivers, breadth_pct, avg_score, n_picks_top30, top_picks,
               n_regulatory_30d, bucket, snapshot_date,
               horizon_short, horizon_medium, horizon_long
        FROM sector_briefs
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM sector_briefs)
    """)
    if briefs.empty:
        return {"snapshot_date": None, "buckets": {}, "forces": {}}

    snapshot_date = briefs.iloc[0]["snapshot_date"]

    # Plan 0006 Phase D — attach the LLM-narrated dossier per sector. Only
    # valid=1 rows are surfaced (mirror of get_dossier() returning {} for
    # invalid stock dossiers); a missing/invalid dossier yields {} so the
    # template degrades gracefully to the deterministic digest.
    dossier_map = {}
    try:
        ddf = read_sql(
            """
            SELECT sector, thesis, bull_case, bear_case, what_to_watch,
                   tech_innovation_drivers, conviction
            FROM sector_dossiers
            WHERE snapshot_date = ? AND valid = 1
            """,
            params=[snapshot_date],
        )
        for _, dr in ddf.iterrows():
            def _jl(v):
                try:
                    return json.loads(v) if v else []
                except (json.JSONDecodeError, TypeError):
                    return []
            dossier_map[dr["sector"]] = {
                "thesis": dr["thesis"],
                "conviction": dr["conviction"],
                "bull_case": _jl(dr["bull_case"]),
                "bear_case": _jl(dr["bear_case"]),
                "what_to_watch": _jl(dr["what_to_watch"]),
                "tech_innovation_drivers": _jl(dr["tech_innovation_drivers"]),
            }
    except Exception:
        dossier_map = {}

    def _f(v, places=None):
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return round(f, places) if places is not None else f

    def _row_to_dict(r):
        try:
            drivers = json.loads(r["macro_drivers"] or "[]")
        except (json.JSONDecodeError, TypeError):
            drivers = []
        try:
            picks = json.loads(r["top_picks"] or "[]")
        except (json.JSONDecodeError, TypeError):
            picks = []
        scored = [d for d in drivers if isinstance(d.get("value"), (int, float))][:3]
        if scored:
            driver_preview = " · ".join(
                f"{d.get('driver','')} {d.get('raw') or (str(d.get('value','')) + (d.get('unit') or ''))}"
                for d in scored
            )
        else:
            driver_preview = " · ".join(d.get("raw", "") or d.get("driver", "") for d in drivers[:3])
        hint = None
        if r["bucket"] == "HEADWIND" and (r["n_picks_top30"] or 0) > 0 and picks:
            hint = "Model still picking here — " + ", ".join(p["ticker"] for p in picks[:3])
        return {
            "sector": r["sector"],
            "macro_score": _f(r.get("macro_score"), 0),
            "macro_signal": r.get("macro_signal"),
            "driver_preview": driver_preview,
            "breadth_pct": _f(r.get("breadth_pct"), 0),
            "avg_score": _f(r.get("avg_score"), 2),
            "n_picks_top30": int(r["n_picks_top30"] or 0),
            "top_picks": picks,
            "alignment_hint": hint,
            "n_regulatory_30d": int(r["n_regulatory_30d"] or 0),
            "n_stocks": int(r["n_stocks"] or 0),
            "dossier": dossier_map.get(r["sector"], {}),
            "horizons": {
                "short": r.get("horizon_short"),
                "medium": r.get("horizon_medium"),
                "long": r.get("horizon_long"),
            },
        }

    buckets = {"BOOMING": [], "LIKELY": [], "HEADWIND": [], "QUIET": []}
    for _, r in briefs.iterrows():
        buckets[r["bucket"]].append(_row_to_dict(r))
    for b in ("BOOMING", "LIKELY"):
        buckets[b].sort(key=lambda s: (-s["n_picks_top30"], -(s["macro_score"] or 0)))
    buckets["HEADWIND"].sort(key=lambda s: (s["macro_score"] or 100))
    buckets["QUIET"].sort(key=lambda s: -(s["macro_score"] or 0))

    forces_df = read_sql(
        "SELECT sector, force, direction, magnitude, summary, detail "
        "FROM sector_force_breakdown WHERE snapshot_date = ?",
        params=[snapshot_date],
    )
    forces = {f: {"positive": [], "negative": [], "neutral": []}
              for f in ("macro", "regulation", "tech", "market")}
    if not forces_df.empty:
        # Order sectors within each direction by magnitude desc, then alpha
        mag_rank = {"strong": 3, "moderate": 2, "weak": 1, None: 0}
        for _, r in forces_df.iterrows():
            entry = {
                "sector": r["sector"],
                "magnitude": r["magnitude"],
                "summary": r["summary"] or "",
            }
            f = r["force"]
            d = r["direction"]
            if d == "+":
                forces[f]["positive"].append(entry)
            elif d == "-":
                forces[f]["negative"].append(entry)
            else:
                forces[f]["neutral"].append(entry)
        for f_key, dirs in forces.items():
            for d_key in dirs:
                dirs[d_key].sort(key=lambda e: (-mag_rank.get(e["magnitude"], 0), e["sector"]))

    return {
        "snapshot_date": snapshot_date,
        "buckets": buckets,
        "forces": forces,
    }


def get_sector_macro_contributors(sector):
    """The macro_indicator → sector_weight map for this sector, joined with
    latest macro indicator values."""
    return db.rows(
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
        [sector],
    )


def get_industry_parent_sector(industry):
    """Return the GICS sector this industry rolls up to."""
    return db.scalar(
        "SELECT DISTINCT sector FROM stocks "
        "WHERE industry = ? AND sector IS NOT NULL LIMIT 1",
        [industry],
    )


def get_industry_competitive_landscape(industry):
    """Real industry concentration including private / unlisted players.

    Sourced from the narrative payload (`competitive_landscape.players`),
    then enriched: any listed player whose ticker matches a row in `stocks`
    is given a SID + our composite score for navigation. Private players
    are marked listed=False and have no SID.

    Returns {share_basis, as_of, players: [...]} or None if no narrative
    or the narrative doesn't carry this field yet.
    """
    narr = get_group_metadata(industry)
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
         AND dp.pick_date = ?
        WHERE s.industry = ? AND s.ticker IS NOT NULL
        """,
        params=[latest_pick_date(), industry],
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
            out["market_cap_cr"] = round(mcap, 0) if mcap is not None and mcap == mcap else None
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
        r = db.one("SELECT * FROM news_briefs WHERE brief_date = ? LIMIT 1", [target_date])
    else:
        r = db.one("SELECT * FROM news_briefs ORDER BY brief_date DESC LIMIT 1")
    if not r:
        return {}
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


# Local stock-photo pool (downloaded by sources/news_images.py). Cards rotate
# through it per topic + a stable per-article hash. Empty until images are
# downloaded → cards fall back to the on-brand gradient visual.
_NEWS_IMG_DIR = Path(__file__).resolve().parent / "static" / "news_img"
_news_img_pool_cache = None


def _news_image_pool():
    """{topic_id: [/static/... urls]}. Cached for the process (cockpit restarts
    when the pool changes)."""
    global _news_img_pool_cache
    if _news_img_pool_cache is None:
        pool = {}
        if _NEWS_IMG_DIR.exists():
            for d in sorted(_NEWS_IMG_DIR.iterdir()):
                if d.is_dir():
                    imgs = sorted(f"/static/news_img/{d.name}/{f.name}" for f in d.glob("*.jpg"))
                    if imgs:
                        pool[d.name] = imgs
        _news_img_pool_cache = pool
    return _news_img_pool_cache


def _pick_news_bg(primary_topic, article_id, pool):
    """Deterministic per-article pick: same article → same photo across reloads."""
    if not pool:
        return None
    cands = pool.get(primary_topic) or pool.get("generic") or [x for v in pool.values() for x in v]
    if not cands:
        return None
    # crc32, not hash(): str hashes are salted per process (PYTHONHASHSEED), so
    # hash() re-shuffled every photo on each cockpit restart.
    import zlib
    return cands[zlib.crc32(str(article_id).encode()) % len(cands)]


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
               ne.keywords, ne.classifier_status, ne.image_url
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
    img_pool = _news_image_pool()
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

        keywords = []
        if r.get("keywords") and pd.notna(r.get("keywords")):
            try:
                keywords = [str(k) for k in (_json.loads(r["keywords"]) or [])][:5]
            except Exception:
                keywords = []

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
            "keywords": keywords,
            "bg_image": _pick_news_bg(primary_topic, r["id"], img_pool),
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
# realization: what live picks actually did, per tier × window.

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
    bench_max = db.scalar(
        "SELECT MAX(trade_date) FROM nse_index_history WHERE index_symbol='NIFTY 50'"
    )

    from datetime import datetime as _dt, timedelta as _td
    bench_staleness = None
    if bench_max:
        try:
            bench_staleness = (_dt.now().date() - _dt.fromisoformat(bench_max).date()).days
        except Exception:
            pass

    # Holding-horizon status. Windows are TRADING days (20≈1mo model-native,
    # 63≈3mo, 126≈6mo positional). The longer ones stay empty until picks
    # mature — surface that as "maturing" with an ETA rather than a blank card.
    from tools.compute_pick_outcomes import DEFAULT_WINDOWS
    earliest_pick = db.scalar("SELECT MIN(pick_date) FROM daily_picks")
    rows_by_w = base.groupby("window_days")["pick_date"].nunique().to_dict() if not base.empty else {}
    windows_status = []
    for w in sorted(DEFAULT_WINDOWS):
        n_dates = int(rows_by_w.get(w, 0))
        status = "live" if n_dates >= 2 else "maturing"
        eta = None
        if status == "maturing" and earliest_pick:
            try:  # first row appears ~w trading days (≈ w*7/5 calendar) after the earliest pick
                eta = (_dt.fromisoformat(earliest_pick) + _td(days=round(w * 7 / 5))).date().isoformat()
            except Exception:
                pass
        windows_status.append({"window_days": w, "n_dates": n_dates,
                               "status": status, "first_outcome_eta": eta,
                               "model_native": w == 20})
    # Headline = longest matured window (positional intent); fall back to 20d.
    live_ws = [w["window_days"] for w in windows_status if w["status"] == "live"]
    headline_window = max(live_ws) if live_ws else 20

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

    # Rank-decile analysis at the headline (positional) horizon.
    rank_deciles = []
    deciles_df = read_sql(
        """
        WITH ranked AS (
            SELECT cap_tier, fwd_return_pct, excess_return_pct,
                   NTILE(10) OVER (PARTITION BY pick_date, cap_tier ORDER BY rank_at_pick) AS d
            FROM pick_outcomes WHERE window_days = ?
        )
        SELECT cap_tier, d AS decile, COUNT(*) n,
               AVG(fwd_return_pct) avg_fwd,
               AVG(excess_return_pct) avg_excess
        FROM ranked GROUP BY cap_tier, d ORDER BY cap_tier, d
        """,
        params=[headline_window],
    )
    for _, row in deciles_df.iterrows():
        rank_deciles.append({
            "cap_tier": row["cap_tier"],
            "window_days": headline_window,
            "decile": int(row["decile"]),
            "n": int(row["n"]),
            "avg_fwd": round(float(row["avg_fwd"]), 3) if pd.notna(row["avg_fwd"]) else None,
            "avg_excess": round(float(row["avg_excess"]), 3) if pd.notna(row["avg_excess"]) else None,
        })

    # Time series of avg top-N fwd return per pick_date at the headline horizon
    time_series = []
    ts_df = read_sql(
        """
        SELECT pick_date, cap_tier,
               AVG(fwd_return_pct) avg_fwd,
               AVG(excess_return_pct) avg_excess,
               COUNT(*) n
        FROM pick_outcomes
        WHERE window_days = ? AND rank_at_pick <= ?
        GROUP BY pick_date, cap_tier
        ORDER BY pick_date, cap_tier
        """,
        params=[headline_window, top_n],
    )
    for _, row in ts_df.iterrows():
        time_series.append({
            "pick_date": row["pick_date"],
            "cap_tier": row["cap_tier"],
            "window_days": headline_window,
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
        "headline_window": headline_window,
        "windows_status": windows_status,
        "by_window_tier": by_window_tier,
        "rank_deciles": rank_deciles,
        "time_series": time_series,
    }



# ───────────── News editor (plan 0021 P2) ─────────────
# Read side of sources/news_editor.py: today's three items, the 7 fixed themes, the
# weekly outlook. Stocks are counted from the theme's headlines; the LLM names none.

def _articles_by_id(ids):
    ids = [str(i) for i in dict.fromkeys(ids)]
    if not ids:
        return {}
    qs = ",".join("?" * len(ids))
    return {str(r["article_id"]): r for r in db.rows(
        f"SELECT article_id, title, url, source FROM news_articles WHERE article_id IN ({qs})", ids)}


def _with_sources(items):
    """Each item's `article_ids` resolved to `sources` [{title, url, source}]."""
    lookup = _articles_by_id([a for it in items for a in it.get("article_ids", [])])
    return [{**it, "sources": [lookup[str(a)] for a in it.get("article_ids", []) if str(a) in lookup]}
            for it in items]


def _theme_stocks(theme_id, pick_sids):
    from sources import news_editor as ne
    recs = db.rows(
        f"SELECT st.sid, st.ticker, st.name, COUNT(DISTINCT ta.article_id) AS n "
        f"FROM news_theme_articles ta JOIN news_articles na ON na.article_id = ta.article_id "
        f"JOIN news_article_stocks nas ON nas.article_id = ta.article_id "
        f"JOIN stocks st ON st.sid = nas.sid WHERE ta.theme_id = ? AND {ne._ISO_DAY} AND {ne._DAY} > ? "
        f"GROUP BY st.sid ORDER BY n DESC, st.name LIMIT 5", [theme_id, ne._shift(ne._today(), -30)])
    for r in recs:
        r["is_pick"] = r["sid"] in pick_sids
    return recs


def _current_pick_sids():
    try:
        df = views.picks(latest_pick_date(), per_tier="book")
        return set(df["sid"]) if len(df) else set()
    except Exception:
        return set()


@_ttl_cache(120)
def get_news_today():
    """The newest daily edition ({day, n_headlines, items[3]}, each item with its
    source links) or {}."""
    from sources import news_editor
    t = news_editor.today()
    return {**t, "items": _with_sources(t["items"])} if t else {}


@_ttl_cache(120)
def get_news_themes():
    """The 7 themes in fixed order; each with its top 5 stocks (is_pick = in the latest picks)."""
    from sources import news_editor
    picks = _current_pick_sids()
    rows = news_editor.themes()
    for r in rows:
        r["stocks"] = _theme_stocks(r["theme_id"], picks)
    return rows


def get_news_theme(theme_id):
    """One theme (retired ones too): its note, timeline (newest first) and the newest
    30 headlines filed under it; None when the id is unknown."""
    from sources import news_editor as ne
    row = db.one("SELECT theme_id FROM news_themes WHERE theme_id = ?", [theme_id])
    if not row:
        return None
    t = next((x for x in get_news_themes() if x["theme_id"] == theme_id), None)
    if t is None:   # retired: note from the table, counts left empty
        t = db.one("SELECT * FROM news_themes WHERE theme_id = ?", [theme_id])
        for f in ("gains", "loses", "next_if"):
            try:
                t[f] = json.loads(t.get(f) or "[]")
            except ValueError:
                t[f] = []
        t.update({"n7": 0, "n_total": 0, "heat": "Quiet", "moved": False,
                  "stocks": _theme_stocks(theme_id, _current_pick_sids())})
    t = dict(t)
    t["timeline"] = db.rows("SELECT as_of, what_changed FROM news_theme_history WHERE theme_id = ? "
                            "ORDER BY as_of DESC", [theme_id])
    t["articles"] = db.rows(
        f"SELECT na.title, na.url, na.source, substr(na.published_at, 1, 10) AS day "
        f"FROM news_theme_articles ta JOIN news_articles na ON na.article_id = ta.article_id "
        f"WHERE ta.theme_id = ? ORDER BY na.published_at DESC LIMIT 30", [theme_id])
    return t


@_ttl_cache(120)
def get_news_week():
    """The newest weekly edition ({as_of, radar (with source links), favour, careful}) or {}."""
    from sources import news_editor
    w = news_editor.week()
    return {**w, "radar": _with_sources(w["radar"])} if w else {}


@_ttl_cache(120)
def get_sector_radar():
    """One row per sector, busiest against its usual first: n7 = distinct articles
    about the sector's stocks in the last 7 days, weekly_avg = the 28 days before / 4,
    flow wording from the ratio, driver = the theme with most headlines this week that
    lists the sector in gains or loses."""
    from sources import news_editor
    flow = news_editor.sector_flow()
    drivers = {}
    for t in sorted(get_news_themes(), key=lambda t: t["n7"]):   # highest n7 written last
        for side, names in (("gains", t["gains"]), ("loses", t["loses"])):
            for name in names:
                drivers[name] = {"theme_id": t["theme_id"], "title": t["title"], "side": side}
    out = []
    for sector in news_editor.sectors():
        f = flow.get(sector, {})
        n7, avg = int(f.get("this_week") or 0), float(f.get("usual_week") or 0)
        ratio = n7 / avg if avg else (float("inf") if n7 else 0.0)
        out.append({"sector": sector, "n7": n7, "weekly_avg": round(avg, 1),
                    "flow": "More than usual" if ratio >= 1.5 else ("Quieter" if ratio <= 0.5 else "Usual"),
                    "driver": drivers.get(sector), "_ratio": ratio})
    out.sort(key=lambda r: (r["_ratio"], r["n7"]), reverse=True)
    for r in out:
        r.pop("_ratio")
    return out
