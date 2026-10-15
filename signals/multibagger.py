"""
Alpha Signal v2 — Multibagger Candidate Funnel (v0)

A SEPARATE screen (NOT wired into daily_picks) that flags upper-small / mid-cap
candidates for 3x–10x over 2–4 years, via a 3-stage hurdle/filter funnel
(docs/reference/multibagger-research.md + the consolidated plan). Reuses the
existing factor tables; computes the few genuinely-new inputs inline.

  Stage 1 — hard exclusion gates (ANY fail → excluded):
      • Beneish M-Score flag      (reuse forensic_scores.m_score_flag)
      • Promoter pledge ≤ 10%     (shareholding.pledge_pct)
      • Debt/Equity ≤ 0.5         (Screener: Borrowings / (EqCap + Reserves))

  Stage 2 — fundamental hurdles (must clear ALL):
      • Market cap ∈ ₹1,000–20,000 cr   (mid-to-mega sweet spot)
      • ROIC ≥ 18%                       (reuse roic_scores; tightened from 15%)
      • Piotroski F ≥ 6                  (reuse piotroski_scores)
      • 3y PAT CAGR ≥ 20%                (Screener annual Net profit; tightened from 15%)
      • Promoter holding ≥ 35%           (shareholding.promoter_pct)

  Stage 3 — composite rank of survivors (percentile within cap_tier):
      • Quality     : gross_profitability (ANCHOR) + ROIC + ROIIC + margin_slope
      • Growth      : 3y PAT CAGR + earnings_acceleration (annual growth-of-growth)
      • Interaction : pctile(growth) × pctile(cheapness)  — Report B "Lollapalooza"
      • Conviction  : smart_money + pledge_quality + promoter_trend

Thresholds are research DEFAULTS — calibrate on the survivorship-corrected
cohort panel (Phase 2). Validation is the cohort hit-rate, NOT rank-IC.

Data realities (verified 2026-06-03):
  • market cap (₹ crore) is scoring.segment.market_caps() = signals._fundamentals.market_caps,
    the one market cap; NOT the stocks.market_cap_cr column (refreshed only by classify_micro_tier,
    so a snapshot read it on a stale basis: CEMPRO 9,265 vs 19,328 Cr).
  • stocks.debt_to_equity / pe_ratio are empty → D/E & PE from Screener.
  • quarterly_income too shallow (43 sids ≥12q) → growth from ANNUAL Net profit.

Usage:
    python -m signals.multibagger
    python -m signals.multibagger --dry-run
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import EXCLUDED_FROM_PICKS, MB_THESIS, SCREEN
from db import read_sql, upsert_df
from scoring.regime_smallcap import classify as classify_smallcap_regime
from scoring.segment import market_caps

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])

# ── Thresholds (calibrated on the live survivor distribution, 2026-06-04) ──
# Tightened ROIC 0.15→0.18 + PAT CAGR 0.15→0.20 to cut the watchlist from 35 to
# ~19 high-conviction names (quality + growth bar; the gates do the work, the
# ranking is noise — ADR 0039/0040). Both bars sit just above the survivor median
# (ROIC med 0.187, CAGR med 0.40) so they raise quality without over-thinning.
MCAP_MIN_CR = 1_000.0
MCAP_MAX_CR = 20_000.0
BENEISH_EXCLUDE_FLAG = "LIKELY_MANIPULATOR"
PLEDGE_MAX_PCT = 10.0
DE_MAX = 0.5
ROIC_MIN = 0.18
FSCORE_MIN = 6
PAT_CAGR_MIN = 0.20
PROMOTER_MIN_PCT = 35.0

# Growth-compute guards (annual Net profit, ₹ cr)
MIN_PAT_BASE_CR = 5.0          # ignore near-zero bases (growth explodes)
ACCEL_CLIP = (-3.0, 3.0)
MIN_GROWTH_YEARS = 3           # need ≥3 annual Net-profit periods for accel
CAGR_WINDOW = 3                # target 3y CAGR (uses earliest available if <4 pts)

# ── Stage-3 pillar weights — REGIME-CONDITIONED (Phase 2b+, ADR 0039) ──
# The survivorship cohort (tools/multibagger_cohort.py --all-windows) shows the
# winning pillar mix FLIPS with the small-cap regime: quality-heavy captures
# best in a BEAR (2018→21 +0.18x), growth/cheapness-heavy is least-bad in a junk
# RALLY (2022→26, where every scheme underperforms), balanced wins the MIXED
# recovery (2019→22 +0.30x). So we pick weights by the live small-cap EMA regime
# (scoring/regime_smallcap.py) instead of one static set. Conviction is held at a
# fixed modest weight — it isn't cohort-testable (no PIT smart-money depth pre-2023)
# — and the three cohort-proven pillars fill the rest (Σ=1.0).
CONVICTION_WEIGHT = 0.15
PILLAR_WEIGHTS_BY_REGIME = {
    "DOWNTREND": {"quality": 0.42, "growth": 0.17, "interaction": 0.26, "conviction": 0.15},
    "NEUTRAL":   {"quality": 0.29, "growth": 0.28, "interaction": 0.28, "conviction": 0.15},
    "UPTREND":   {"quality": 0.17, "growth": 0.26, "interaction": 0.42, "conviction": 0.15},
}
# regime_favorable — VALIDATED, not hand-set (tools/multibagger_cohort.py
# --validate-flag, 2026-06-04). We labelled the small-cap EMA regime AT entry
# across 8 historical anchors (~3-4 independent; the index is backfilled to 2016)
# and measured the screen's REALISED forward top-decile spread:
#   UPTREND   → mean −0.27x  (robust; the strongest uptrend had the worst edge −0.64x)
#   NEUTRAL   → ≈ 0
#   DOWNTREND → n=1, inconclusive (the lone sample was −0.25x)
# So the encoding is:
#   0 = VALIDATED-UNFAVOURABLE — EMA UPTREND, the screen's ranking edge is negative
#   1 = no validated penalty   — NEUTRAL / DOWNTREND, edge ≈ 0
# IMPORTANT: NO regime is reliably FAVOURABLE — the screen's ranking edge is
# zero-to-negative everywhere, worst in uptrends. "1" means "not the validated-bad
# regime", NOT "proven edge". The gates/hurdles add value (they strip junk); the
# ranking of survivors does not reliably beat a median small-cap.
REGIME_FAVORABLE = {"DOWNTREND": 1, "NEUTRAL": 1, "UPTREND": 0}


# ───────────────────────── data loading ─────────────────────────

def _latest(table, value_cols):
    """Latest snapshot per sid from a *_scores table."""
    cols = ", ".join(["t.sid"] + [f"t.[{c}]" for c in value_cols])
    df = read_sql(
        f"SELECT {cols} FROM {table} t "
        f"JOIN (SELECT sid, MAX(snapshot_date) ms FROM {table} GROUP BY sid) m "
        f"ON t.sid = m.sid AND t.snapshot_date = m.ms"
    )
    return df


def _load_universe():
    placeholders = ",".join("?" for _ in FINANCIAL_SECTORS)
    excluded = ",".join("?" for _ in EXCLUDED_FROM_PICKS)
    stocks = read_sql(
        f"SELECT sid, name, sector, cap_tier "
        f"FROM stocks WHERE sector NOT IN ({placeholders}) AND cap_tier NOT IN ({excluded})",
        params=[*FINANCIAL_SECTORS, *EXCLUDED_FROM_PICKS],
    )
    caps = market_caps()
    if len(caps) < 0.5 * len(stocks):
        raise RuntimeError(f"multibagger: market cap for only {len(caps)} of {len(stocks)} stocks "
                           "— stale prices or missing share counts")
    return stocks.merge(caps, on="sid", how="left")      # no cap -> NaN -> fails the mcap hurdle


def _load_shareholding():
    """Latest promoter_pct + pledge_pct per sid (by end_date)."""
    return read_sql(
        "SELECT s.sid, s.promoter_pct, s.pledge_pct FROM shareholding s "
        "JOIN (SELECT sid, MAX(end_date) me FROM shareholding GROUP BY sid) m "
        "ON s.sid = m.sid AND s.end_date = m.me"
    )


def _load_annual_fundamentals():
    """Annual Net profit / Borrowings / EqCap / Reserves per (sid, period_end)."""
    items = ["Net profit", "Borrowings", "Equity Share Capital", "Reserves"]
    f = read_sql(
        "SELECT sid, period_end, line_item, value FROM fundamentals_screener "
        f"WHERE period_type='annual' AND line_item IN ({','.join('?' for _ in items)})",
        params=items,
    )
    if f.empty:
        return pd.DataFrame(columns=["sid", "period_end"] + items)
    wide = f.pivot_table(index=["sid", "period_end"], columns="line_item",
                         values="value", aggfunc="first").reset_index()
    return wide


def _growth_metrics(annual):
    """Per sid: pat_cagr_3y, earnings_acceleration, np_latest (₹cr), de_ratio."""
    rows = []
    for sid, g in annual.sort_values(["sid", "period_end"]).groupby("sid"):
        np_series = g["Net profit"].dropna().tolist() if "Net profit" in g else []
        rec = {"sid": sid, "pat_cagr_3y": np.nan,
               "earnings_acceleration": np.nan, "np_latest": np.nan,
               "de_ratio": np.nan}

        if len(np_series) >= 2 and np_series[-1] is not None:
            rec["np_latest"] = float(np_series[-1])

        # 3y PAT CAGR (uses earliest point if <4 periods)
        if len(np_series) >= 2:
            n = min(CAGR_WINDOW, len(np_series) - 1)
            base, latest = np_series[-(n + 1)], np_series[-1]
            if base is not None and base > MIN_PAT_BASE_CR and latest is not None and latest > 0:
                rec["pat_cagr_3y"] = (latest / base) ** (1.0 / n) - 1.0

        # Earnings acceleration = ΔYoY-growth (annual growth-of-growth)
        if len(np_series) >= MIN_GROWTH_YEARS:
            a, b, c = np_series[-3], np_series[-2], np_series[-1]
            if (a is not None and b is not None and c is not None
                    and abs(a) > MIN_PAT_BASE_CR and abs(b) > MIN_PAT_BASE_CR):
                g_now = c / b - 1.0
                g_prev = b / a - 1.0
                rec["earnings_acceleration"] = float(
                    np.clip(g_now - g_prev, *ACCEL_CLIP))

        # Debt/Equity from latest annual (Borrowings / (EqCap + Reserves))
        last = g.iloc[-1]
        borrow = last.get("Borrowings")
        eqcap = last.get("Equity Share Capital")
        reserves = last.get("Reserves")
        if pd.notna(borrow) and pd.notna(eqcap) and pd.notna(reserves):
            equity = eqcap + reserves
            if equity > 0:
                rec["de_ratio"] = float(borrow / equity)
        rows.append(rec)
    return pd.DataFrame(rows)


# ───────────────────────── funnel logic ─────────────────────────

def _pctile(s):
    """Percentile rank in [0,1], NaN-safe (NaN → 0.5 neutral)."""
    r = s.rank(pct=True)
    return r.fillna(0.5)


def _build(stocks, scores, sh, growth, weights):
    df = stocks.merge(scores, on="sid", how="left") \
               .merge(sh, on="sid", how="left") \
               .merge(growth, on="sid", how="left")

    # cheapness = earnings yield = latest annual PAT (₹cr) / mcap (₹cr)
    df["ep_yield"] = df["np_latest"] / df["mcap_cr"]
    # PEG = PE / (PAT CAGR %); PE = mcap / PAT
    pe = df["mcap_cr"] / df["np_latest"].where(df["np_latest"] > 0)
    df["peg"] = pe / (df["pat_cagr_3y"] * 100.0).where(df["pat_cagr_3y"] > 0)

    # ── Stage 1: hard exclusion gates (null → pass; absence isn't a red flag) ──
    g_beneish = df["m_score_flag"].fillna("") != BENEISH_EXCLUDE_FLAG
    g_pledge = ~(df["pledge_pct"] > PLEDGE_MAX_PCT)          # NaN → pass
    g_debt = ~(df["de_ratio"] > DE_MAX)                      # NaN → pass
    df["passed_gates"] = (g_beneish & g_pledge & g_debt).astype(int)

    def _gate_reason(r):
        out = []
        if r["m_score_flag"] == BENEISH_EXCLUDE_FLAG:
            out.append("beneish")
        if pd.notna(r["pledge_pct"]) and r["pledge_pct"] > PLEDGE_MAX_PCT:
            out.append("pledge")
        if pd.notna(r["de_ratio"]) and r["de_ratio"] > DE_MAX:
            out.append("debt")
        return ",".join(out)
    df["gate_fail"] = df.apply(_gate_reason, axis=1)

    # ── Stage 2: fundamental hurdles (null on a required hurdle → fail) ──
    h_mcap = df["mcap_cr"].between(MCAP_MIN_CR, MCAP_MAX_CR)
    h_roic = df["roic"] >= ROIC_MIN
    h_fscore = df["f_score"] >= FSCORE_MIN
    h_growth = df["pat_cagr_3y"] >= PAT_CAGR_MIN
    h_promoter = df["promoter_pct"] >= PROMOTER_MIN_PCT
    df["passed_hurdles"] = (h_mcap & h_roic & h_fscore & h_growth & h_promoter).astype(int)

    def _hurdle_reason(r):
        out = []
        if not (MCAP_MIN_CR <= (r["mcap_cr"] or -1) <= MCAP_MAX_CR):
            out.append("mcap")
        if not (r["roic"] >= ROIC_MIN):
            out.append("roic")
        if not (r["f_score"] >= FSCORE_MIN):
            out.append("fscore")
        if not (r["pat_cagr_3y"] >= PAT_CAGR_MIN):
            out.append("growth")
        if not (r["promoter_pct"] >= PROMOTER_MIN_PCT):
            out.append("promoter")
        return ",".join(out)
    df["hurdle_fail"] = df.apply(_hurdle_reason, axis=1)

    df["survived"] = ((df["passed_gates"] == 1) & (df["passed_hurdles"] == 1)).astype(int)

    # ── Stage 3: composite rank of survivors (percentile within cap_tier) ──
    df["multibagger_score"] = np.nan
    df["p_quality"] = np.nan
    df["p_growth"] = np.nan
    df["p_conviction"] = np.nan
    df["interaction"] = np.nan
    df["rank_in_tier"] = np.nan

    surv = df[df["survived"] == 1].copy()
    if not surv.empty:
        parts = []
        for tier, grp in surv.groupby("cap_tier"):
            grp = grp.copy()
            grp["p_quality"] = np.mean([
                _pctile(grp["gross_profitability"]),
                _pctile(grp["roic"]),
                _pctile(grp["roiic"]),
                _pctile(grp["margin_slope"]),
            ], axis=0)
            grp["p_growth"] = np.mean([
                _pctile(grp["pat_cagr_3y"]),
                _pctile(grp["earnings_acceleration"]),
            ], axis=0)
            grp["interaction"] = _pctile(grp["pat_cagr_3y"]) * _pctile(grp["ep_yield"])
            grp["p_conviction"] = np.mean([
                _pctile(grp["smart_money_score"]),
                _pctile(grp["pledge_quality"]),
                _pctile(grp["promoter_trend"]),
            ], axis=0)
            grp["multibagger_score"] = (
                weights["quality"] * grp["p_quality"]
                + weights["growth"] * grp["p_growth"]
                + weights["interaction"] * grp["interaction"]
                + weights["conviction"] * grp["p_conviction"]
            )
            grp["rank_in_tier"] = grp["multibagger_score"].rank(ascending=False, method="min")
            parts.append(grp)
        ranked = pd.concat(parts)
        for col in ["p_quality", "p_growth", "p_conviction", "interaction",
                    "multibagger_score", "rank_in_tier"]:
            df.loc[ranked.index, col] = ranked[col]
    return df


# ───────────────── the thesis score (plan 0026 phase 2, ADR 0075) ─────────────────
# ONE pure function shared by the live desk (compute) and the research backtest (tools/mb_thesis.score).

PARTS = ["smallness", "cheapness", "price", "business", "tailwind"]
CR = 1e7
THESIS_COLS = ["thesis_pond", "thesis_gate_fail", "p_smallness", "p_cheapness", "p_price", "p_business",
               "p_tailwind", "thesis_score", "thesis_rank", "thesis_stage", "adtv_cr"]


def _pct(s):
    return s.rank(pct=True)


def liquidity_pond(f, adtv_min_cr=None):
    """Buyable: ADTV (rupees) at or above the floor and outside the most liquid `adtv_rank_min` names."""
    floor = MB_THESIS["adtv_min_cr"] if adtv_min_cr is None else adtv_min_cr
    return (f["adtv"] >= floor * CR) & (f["adtv_rank"] > MB_THESIS["adtv_rank_min"])


def thesis(frame, min_pond=0, adtv_min_cr=None):
    """Thesis v1 on a per-stock frame at ONE date (index = stock id).

    Required columns: adtv (rupees), adtv_rank, mcap_cr, bp, sp, ep, sales, mom_6m, pos_52w, industry.
    Optional (a gate or part is skipped when its column is absent; NaN passes a pledge/GSM gate):
      q_ebitda_chg, q_rev_yoy (business part), red_flag, pledge_pct, gsm, survivor, mcap_max (per-row cap;
      default config.MB_THESIS['mcap_max_cr']).
    Returns a frame on the same index: thesis_pond, thesis_gate_fail (comma list of failed gates, '' in
    the pond), the five within-pond percentile parts (a missing part = the mean of the stock's other
    parts), thesis_score (their mean) and thesis_rank (1 = best, within the pond).
    min_pond: fewer pond names than this -> no scores (the backtest's early thin ponds)."""
    t = MB_THESIS
    f = frame
    cap = f["mcap_max"] if "mcap_max" in f else t["mcap_max_cr"]
    gates = {"adtv": f["adtv"] >= (t["adtv_min_cr"] if adtv_min_cr is None else adtv_min_cr) * CR,
             "adtv_rank": f["adtv_rank"] > t["adtv_rank_min"],
             "mcap": f["mcap_cr"] <= cap, "sales": f["sales"] > 0}
    if "survivor" in f:
        gates["survivor"] = f["survivor"].astype("boolean").fillna(False).astype(bool)
    if "red_flag" in f:
        gates["red_flag"] = ~f["red_flag"].astype("boolean").fillna(False).astype(bool)
    if "pledge_pct" in f:
        gates["pledge"] = ~(f["pledge_pct"] > t["pledge_max_pct"])
    if "gsm" in f:
        gates["gsm"] = ~f["gsm"].astype("boolean").fillna(False).astype(bool)
    pond = pd.Series(True, index=f.index)
    fail = pd.Series("", index=f.index)
    for name, ok in gates.items():
        ok = ok.astype(bool)
        pond &= ok
        fail = fail + np.where(ok, "", name + ",")
    out = pd.DataFrame({"thesis_pond": pond, "thesis_gate_fail": fail.str.rstrip(",")}, index=f.index)
    for c in PARTS + ["thesis_score", "thesis_rank"]:
        out[c] = np.nan
    pb = f[pond]
    if len(pb) == 0 or len(pb) < min_pond:
        return out
    parts = pd.DataFrame(index=pb.index)
    parts["smallness"] = _pct(-np.log(pb["mcap_cr"]))
    parts["cheapness"] = pd.concat([_pct(pb["bp"]), _pct(pb["sp"]), _pct(pb["ep"])], axis=1).mean(axis=1)
    parts["price"] = (_pct(pb["mom_6m"]) + _pct(pb["pos_52w"])) / 2
    parts["business"] = (pd.concat([_pct(pb["q_ebitda_chg"]), _pct(pb["q_rev_yoy"])], axis=1).mean(axis=1)
                         if {"q_ebitda_chg", "q_rev_yoy"} <= set(pb) else np.nan)
    parts["tailwind"] = _pct(pb.groupby("industry")["mom_6m"].transform("median"))
    row_mean = parts.mean(axis=1)
    parts = parts.apply(lambda c: c.fillna(row_mean))
    out.loc[pb.index, PARTS] = parts[PARTS].values
    out.loc[pb.index, "thesis_score"] = parts.mean(axis=1)
    out["thesis_rank"] = out["thesis_score"].rank(ascending=False, method="min")
    return out


def _price_features(as_of):
    """[adtv, adtv_rank, mom_6m, pos_52w] per stock on split-adjusted prices (the backtest's definitions:
    ADTV = 126-session median of raw close x volume; 52 weeks = the last 253 sessions)."""
    from signals._prices import apply_adjustments
    w, h = MB_THESIS["adtv_window"], 252
    px = read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date <= ? AND date >= ?",
                  params=[as_of, (pd.Timestamp(as_of) - pd.Timedelta(days=450)).date().isoformat()])
    adj = read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments")
    px = apply_adjustments(px, adj, as_of)
    px["tv"] = px["close"] * px["volume"]
    P = px.pivot_table(index="date", columns="sid", values="adj_close", aggfunc="last").sort_index()
    TV = px.pivot_table(index="date", columns="sid", values="tv", aggfunc="last").reindex(P.index)
    P = P[P.notna().sum(axis=1) >= 0.5 * P.shape[1]]          # drop a partially loaded last day
    TV = TV.reindex(P.index)
    if len(P) < h + 1:
        raise RuntimeError(f"multibagger thesis: only {len(P)} price sessions, need {h + 1}")
    i = len(P) - 1
    win, tvw = P.iloc[i - h:i + 1], TV.iloc[i - w + 1:i + 1]
    ok = (win.notna().sum() >= 200) & P.iloc[i].notna() & (tvw.notna().mean() >= 0.5)
    ids = ok[ok].index
    f = pd.DataFrame(index=ids)
    f["adtv"] = tvw.median()[ids]
    f["adtv_rank"] = f["adtv"].rank(ascending=False)
    f["mom_6m"] = P.iloc[i][ids] / P.iloc[i - 126][ids] - 1
    f["pos_52w"] = P.iloc[i][ids] / win[ids].max()
    return f, P.index[i]


def _knowable_annuals(as_of):
    """Latest annual Equity Share Capital + Reserves, Sales, Net profit knowable at as_of (period_end + lag)."""
    items = ["Sales", "Net profit", "Equity Share Capital", "Reserves"]
    f = read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type='annual' "
                 f"AND line_item IN ({','.join('?' * len(items))})", params=items)
    w = f.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="last").reset_index()
    w["known"] = pd.to_datetime(w["period_end"]) + pd.Timedelta(days=MB_THESIS["annual_lag_days"])
    w = w[w["known"] <= pd.Timestamp(as_of)].sort_values(["sid", "period_end"])
    return w.drop_duplicates("sid", keep="last").set_index("sid")


def _red_flags(as_of):
    """(sids with an auditor resignation / CIRP filing in the last year, date of the newest BSE announcement)."""
    pats = MB_THESIS["red_flag_subcategories"]
    cond = " OR ".join("subcategory LIKE ?" for _ in pats)
    since = (pd.Timestamp(as_of) - pd.Timedelta(days=MB_THESIS["red_flag_days"])).date().isoformat()
    b = read_sql(f"SELECT DISTINCT sid FROM bse_announcements WHERE sid IS NOT NULL AND substr(dt_tm,1,10) > ? "
                 f"AND substr(dt_tm,1,10) <= ? AND ({cond})", params=[since, as_of, *pats])
    last = read_sql("SELECT MAX(substr(dt_tm,1,10)) d FROM bse_announcements")["d"].iloc[0]
    return set(b["sid"]), last


def live_frame(as_of=None):
    """The thesis input frame for today, one row per stock with a price history (live inputs, ADR 0075)."""
    from db import get_db
    from signals._quarterly import asof as q_asof, history as q_history
    as_of = as_of if isinstance(as_of, str) else (as_of or date.today()).isoformat()
    f, last_px = _price_features(as_of)
    stocks = read_sql("SELECT sid, ticker, name, industry, cap_tier FROM stocks").set_index("sid")
    f = f.join(stocks[["ticker", "name", "industry", "cap_tier"]])
    f["mcap_cr"] = market_caps().set_index("sid")["mcap_cr"].reindex(f.index)
    an = _knowable_annuals(as_of).reindex(f.index)
    eq = an["Equity Share Capital"] + an["Reserves"]
    f["bp"], f["sp"], f["ep"] = eq / f["mcap_cr"], an["Sales"] / f["mcap_cr"], an["Net profit"] / f["mcap_cr"]
    f["sales"] = an["Sales"]
    with get_db() as conn:
        q = q_asof(q_history(conn), [as_of]).set_index("sid")
    f["q_ebitda_chg"] = q["q_ebitda_chg"].reindex(f.index)
    f["q_rev_yoy"] = q["q_rev_yoy"].reindex(f.index)
    flagged, last_bse = _red_flags(as_of)
    f["red_flag"] = f.index.isin(flagged)
    f["pledge_pct"] = _load_shareholding().set_index("sid")["pledge_pct"].reindex(f.index)
    gsm = read_sql("SELECT DISTINCT sid FROM surveillance_flags WHERE flag_type='GSM' AND flag_date = "
                   "(SELECT MAX(flag_date) FROM surveillance_flags WHERE flag_type='GSM')")
    f["gsm"] = f.index.isin(set(gsm["sid"]))
    f.attrs.update(price_date=str(last_px), last_bse=last_bse)
    return f


def thesis_table(as_of=None):
    """([sid, snapshot_date, THESIS_COLS] for every stock with a price history, the input frame)."""
    f = live_frame(as_of)
    t = thesis(f)
    if not t["thesis_pond"].any():
        raise RuntimeError("multibagger thesis: empty pond — inputs are broken (prices / market caps / fundamentals)")
    out = t.rename(columns={p: f"p_{p}" for p in PARTS})
    out["adtv_cr"] = f["adtv"] / CR
    out["thesis_stage"] = np.where(out["thesis_rank"] <= MB_THESIS["top_n"], "top100",
                                   np.where(out["thesis_pond"], "pond", None))
    out["thesis_pond"] = out["thesis_pond"].astype(int)
    out.insert(0, "snapshot_date", date.today().isoformat())
    return out.reset_index(names="sid")[["sid", "snapshot_date"] + THESIS_COLS], f


OUTPUT_COLS = [
    "sid", "snapshot_date", "cap_tier", "mcap_cr",
    "survived", "passed_gates", "gate_fail", "passed_hurdles", "hurdle_fail",
    "de_ratio", "pat_cagr_3y", "earnings_acceleration", "ep_yield", "peg",
    "gross_profitability", "roic", "roiic", "margin_slope", "f_score",
    "promoter_pct", "pledge_pct", "smart_money_score", "m_score_flag",
    "p_quality", "p_growth", "p_conviction", "interaction",
    "multibagger_score", "rank_in_tier",
    "smallcap_regime", "regime_favorable",
]


def compute(dry_run=False):
    stocks = _load_universe()

    scores = _latest("roic_scores", ["roic"]) \
        .merge(_latest("roiic_scores", ["roiic"]), on="sid", how="outer") \
        .merge(_latest("gross_profitability_scores", ["gross_profitability"]), on="sid", how="outer") \
        .merge(_latest("operating_margin_trend_scores", ["margin_slope"]), on="sid", how="outer") \
        .merge(_latest("piotroski_scores", ["f_score"]), on="sid", how="outer") \
        .merge(_latest("smart_money_scores", ["smart_money_score"]), on="sid", how="outer") \
        .merge(_latest("promoter_signals", ["pledge_quality", "promoter_trend"]), on="sid", how="outer") \
        .merge(_latest("forensic_scores", ["m_score_flag"]), on="sid", how="outer")

    sh = _load_shareholding()
    growth = _growth_metrics(_load_annual_fundamentals())

    # Regime gate: pick cohort-proven pillar weights for the live small-cap regime.
    reg = classify_smallcap_regime()
    regime = reg["regime"]
    weights = PILLAR_WEIGHTS_BY_REGIME[regime]
    favorable = REGIME_FAVORABLE[regime]

    df = _build(stocks, scores, sh, growth, weights)
    df["snapshot_date"] = date.today().isoformat()
    df["smallcap_regime"] = regime
    df["regime_favorable"] = favorable
    out = df[OUTPUT_COLS].copy()

    n_uni = len(out)
    n_surv = int(out["survived"].sum())
    reg_note = "" if reg["close_vs_slow_pct"] is None else \
        f" (close vs EMA200 {reg['close_vs_slow_pct']:+.1f}%)"
    edge_txt = ("neutral — no validated ranking edge (≈0)" if favorable else
                "UNFAVOURABLE — validated: top-decile spread ~−0.27x in EMA uptrends")
    print(f"Small-cap regime: {regime}{reg_note} → weights "
          f"q{weights['quality']:.2f}/g{weights['growth']:.2f}/"
          f"i{weights['interaction']:.2f}/c{weights['conviction']:.2f} · edge {edge_txt}")
    print(f"Multibagger funnel: {n_uni} in universe (ex-fin, ex-micro) | "
          f"{int(out['passed_gates'].sum())} pass gates | "
          f"{n_surv} survive all gates+hurdles")
    if n_surv:
        top = out[out["survived"] == 1].nlargest(10, "multibagger_score")
        print("  Top candidates:", ", ".join(top["sid"].tolist()))

    # ── the thesis score (plan 0026): a second set of columns, same table, same date ──
    tt, frame = thesis_table()
    n_pond, n_top = int(tt["thesis_pond"].sum()), int((tt["thesis_stage"] == "top100").sum())
    print(f"Thesis: {len(tt)} priced stocks | {n_pond} in the pond | top {n_top} flagged "
          f"(prices {frame.attrs['price_date']}, newest BSE announcement {frame.attrs['last_bse']})")

    if dry_run:
        print("Dry run — not saving.")
        return n_surv

    rows = upsert_df(out, "multibagger_scores")
    # stocks outside the old funnel's universe (financials, MICRO) get the thesis columns too; the old
    # funnel columns say "did not pass" so the strict tab's counts stay NaN-free
    extra = tt[~tt["sid"].isin(out["sid"])][["sid", "snapshot_date"]].merge(
        frame[["cap_tier", "mcap_cr"]], left_on="sid", right_index=True, how="left")
    if len(extra):
        upsert_df(extra.assign(survived=0, passed_gates=0, passed_hurdles=0), "multibagger_scores")
    upsert_df(tt, "multibagger_scores")
    print(f"Saved {rows} rows to multibagger_scores (+ thesis columns for {len(tt)})")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
