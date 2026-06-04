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
      • ROIC ≥ 15%                       (reuse roic_scores)
      • Piotroski F ≥ 6                  (reuse piotroski_scores)
      • 3y PAT CAGR ≥ 15%                (Screener annual Net profit)
      • Promoter holding ≥ 35%           (shareholding.promoter_pct)

  Stage 3 — composite rank of survivors (percentile within cap_tier):
      • Quality     : gross_profitability (ANCHOR) + ROIC + ROIIC + margin_slope
      • Growth      : 3y PAT CAGR + earnings_acceleration (annual growth-of-growth)
      • Interaction : pctile(growth) × pctile(cheapness)  — Report B "Lollapalooza"
      • Conviction  : smart_money + pledge_quality + promoter_trend

Thresholds are research DEFAULTS — calibrate on the survivorship-corrected
cohort panel (Phase 2). Validation is the cohort hit-rate, NOT rank-IC.

Data realities (verified 2026-06-03):
  • stocks.market_cap_cr is stored in RUPEES → ÷1e7 for crores.
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

from config import SCREEN
from db import read_sql, upsert_df
from scoring.regime_smallcap import classify as classify_smallcap_regime

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
RUPEES_PER_CRORE = 1e7

# ── Thresholds (research defaults — calibrate on the cohort panel, Phase 2) ──
MCAP_MIN_CR = 1_000.0
MCAP_MAX_CR = 20_000.0
BENEISH_EXCLUDE_FLAG = "LIKELY_MANIPULATOR"
PLEDGE_MAX_PCT = 10.0
DE_MAX = 0.5
ROIC_MIN = 0.15
FSCORE_MIN = 6
PAT_CAGR_MIN = 0.15
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
    stocks = read_sql(
        f"SELECT sid, name, sector, cap_tier, market_cap_cr "
        f"FROM stocks WHERE sector NOT IN ({placeholders}) AND cap_tier != 'MICRO'",
        params=list(FINANCIAL_SECTORS),
    )
    stocks["mcap_cr"] = stocks["market_cap_cr"] / RUPEES_PER_CRORE
    return stocks


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

    if dry_run:
        print("Dry run — not saving.")
        return n_surv

    rows = upsert_df(out, "multibagger_scores")
    print(f"Saved {rows} rows to multibagger_scores")
    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(dry_run=args.dry_run)
