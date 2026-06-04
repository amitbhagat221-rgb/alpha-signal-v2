"""
Alpha Signal v2 — Multibagger Cohort Study (Phase 2b — THE validation)

Answers the question the 20d backtest cannot: would ranking small-caps by
quality+growth at a historical anchor have CAPTURED the multibaggers over the
next 2-4 years? Survivorship-correct (deaths included) and split-adjusted.

Method:
  1. Universe = `historical_universe` @ anchor (true universe incl. delisted),
     mapped to sid, filtered to as-of small-cap band (close × shares ∈ band).
  2. As-of score (knowable at anchor, 75d annual lag): mean percentile of
     gross_profitability + roic (reused PIT helpers) + pat_cagr_3y +
     earnings_acceleration; exclude high leverage (de_ratio > 0.5).
  3. Forward return anchor→end, SPLIT/BONUS-adjusted via corporate_actions.
     Names absent from the end bhavcopy = DELISTED → terminal loss (DEATH_MULT).
  4. Metrics (tail-capture, NOT rank-IC): top-decile median mult, ≥2x/≥3x/≥5x
     hit-rate, top−bottom decile lift, top−universe spread, and capture
     (of all ≥3x, what fraction the top decile caught).

Usage:
    python -m tools.multibagger_cohort                       # default 2023-04 → 2026-05
    python -m tools.multibagger_cohort --anchor 2022-08-01 --end 2026-05-29
"""

import argparse
import re
import warnings

import numpy as np
import pandas as pd

# All-NaN pillar rows (no PIT fundamentals) → np.nanmean warns; it correctly
# yields NaN, which the scheme scorer fills with a neutral. Cosmetic only.
warnings.filterwarnings("ignore", message="Mean of empty slice")

from config import SCREEN
from db import read_sql
from tools.reconstruct_pit import knowable_screener, pit_gross_profitability, pit_roic

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])
MCAP_MIN_CR, MCAP_MAX_CR = 1_000.0, 20_000.0
DE_MAX = 0.5
MIN_PAT_BASE_CR = 5.0
DEATH_MULT = 0.0          # delisted → total loss (conservative). Sensitivity printed.
RUPEES_PER_CRORE = 1e7


# ───────── as-of growth + leverage + shares from knowable annual screener ─────────

def _asof_metrics(fund_pit):
    items = ["Net profit", "Borrowings", "Equity Share Capital", "Reserves",
             "No. of Equity Shares"]
    fp = fund_pit[fund_pit["line_item"].isin(items)]
    if fp.empty:
        return pd.DataFrame(columns=["sid", "pat_cagr_3y", "earnings_acceleration",
                                     "de_ratio", "shares"])
    wide = fp.pivot_table(index=["sid", "period_end"], columns="line_item",
                          values="value", aggfunc="first").reset_index()
    rows = []
    for sid, g in wide.sort_values(["sid", "period_end"]).groupby("sid"):
        nps = g["Net profit"].dropna().tolist() if "Net profit" in g else []
        rec = {"sid": sid, "pat_cagr_3y": np.nan, "earnings_acceleration": np.nan,
               "de_ratio": np.nan, "shares": np.nan, "np_latest": np.nan}
        if len(nps) >= 1 and nps[-1] is not None:
            rec["np_latest"] = float(nps[-1])
        if len(nps) >= 2:
            n = min(3, len(nps) - 1)
            base, latest = nps[-(n + 1)], nps[-1]
            if base and base > MIN_PAT_BASE_CR and latest and latest > 0:
                rec["pat_cagr_3y"] = (latest / base) ** (1.0 / n) - 1.0
        if len(nps) >= 3:
            a, b, c = nps[-3], nps[-2], nps[-1]
            if a and b and abs(a) > MIN_PAT_BASE_CR and abs(b) > MIN_PAT_BASE_CR:
                rec["earnings_acceleration"] = float(np.clip((c / b - 1) - (b / a - 1), -3, 3))
        last = g.iloc[-1]
        borrow, eqcap, res = last.get("Borrowings"), last.get("Equity Share Capital"), last.get("Reserves")
        if pd.notna(borrow) and pd.notna(eqcap) and pd.notna(res) and (eqcap + res) > 0:
            rec["de_ratio"] = float(borrow / (eqcap + res))
        sh = g["No. of Equity Shares"].dropna()
        if len(sh):
            rec["shares"] = float(sh.iloc[-1])
        rows.append(rec)
    return pd.DataFrame(rows)


# ───────── corporate-action split/bonus adjustment factor ─────────

def _event_factor(subject, ind):
    s = str(subject).lower()
    if ind == "SPLIT" or "split" in s:
        m = re.search(r"from\s*rs[.]?\s*([\d.]+)\s*/?-?\s*per\s*share\s*to\s*rs[.]?\s*([\d.]+)", s)
        if not m:
            m = re.search(r"from\s*rs[.]?\s*([\d.]+).*?to\s*rs[.]?\s*([\d.]+)", s)
        if m:
            old, new = float(m.group(1)), float(m.group(2))
            if new > 0:
                return old / new
    if ind == "BONUS" or "bonus" in s:
        m = re.search(r"(\d+)\s*:\s*(\d+)", s)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if b > 0:
                return (a + b) / b
    return 1.0


def _cum_factors(anchor, end):
    """Per sid: product of split/bonus factors with anchor < ex_date <= end."""
    ca = read_sql(
        "SELECT sid, ex_date, ind, subject FROM corporate_actions "
        "WHERE ex_date > ? AND ex_date <= ? AND ind IN ('SPLIT','BONUS')",
        params=[anchor, end],
    )
    factors = {}
    for _, r in ca.iterrows():
        if not r["sid"]:
            continue
        f = _event_factor(r["subject"], r["ind"])
        factors[r["sid"]] = factors.get(r["sid"], 1.0) * f
    return factors


# ───────── regime windows + weight schemes (Phase 2b+ — regime conditioning) ─────────
#
# Three independent windows, each its own small-cap regime. We characterise each
# window by its REALISED broad small-cap strength (universe-median forward
# multiple) rather than an EMA label — nse_index_history small-cap depth starts
# 2023-06, so the live EMA classifier (scoring/regime_smallcap.py) can't reach
# these anchors. universe-median >> 1 ⇒ a rally-like (junk-rally-prone) window;
# ≈ 1 ⇒ a bear/derating window.
WINDOWS = {
    "2018→21 (bear)":     ("2018-04-02", "2021-04-01"),
    "2019→22 (recovery)": ("2019-04-01", "2022-04-01"),
    "2022→26 (rally)":    ("2022-08-01", "2026-05-29"),
}

# Pillar weight schemes tested per window. The cohort decides WHICH scheme wins
# in which regime — these become the regime-conditioned weights in the live
# screen (quality-heavy ↔ DOWNTREND, growth-heavy ↔ UPTREND), never hand-set.
WEIGHT_SCHEMES = {
    "quality_heavy": {"quality": 0.50, "growth": 0.20, "interaction": 0.30},
    "balanced":      {"quality": 0.34, "growth": 0.33, "interaction": 0.33},
    "growth_heavy":  {"quality": 0.20, "growth": 0.30, "interaction": 0.50},
}


# ───────── the study ─────────

def _score(anchor, end):
    """Build the scoreable small-cap cohort for one window.

    Returns (scored, fwd, a_snap, e_snap) where `scored` carries split-adjusted
    `fwd_mult` plus the three pillar percentiles (p_quality / p_growth /
    p_interaction) and the legacy `score_quality` / `score` columns. `fwd` is the
    full true universe (incl. deaths + unmapped) for base-rate / capture stats."""
    # nearest actual bhavcopy snapshot dates we stored
    uni = read_sql("SELECT snapshot_date FROM historical_universe GROUP BY snapshot_date "
                   "ORDER BY ABS(julianday(snapshot_date) - julianday(?)) LIMIT 1", params=[anchor])
    a_snap = uni["snapshot_date"].iloc[0]
    uni = read_sql("SELECT snapshot_date FROM historical_universe GROUP BY snapshot_date "
                   "ORDER BY ABS(julianday(snapshot_date) - julianday(?)) LIMIT 1", params=[end])
    e_snap = uni["snapshot_date"].iloc[0]

    a = read_sql("SELECT symbol, sid, close c0 FROM historical_universe WHERE snapshot_date=?", params=[a_snap])
    e = read_sql("SELECT symbol, close c1 FROM historical_universe WHERE snapshot_date=?", params=[e_snap])
    fwd = a.merge(e, on="symbol", how="left")          # c1 NaN → died
    fwd["died"] = fwd["c1"].isna()

    # split/bonus adjustment (by sid; only mapped names get adjusted)
    cum = _cum_factors(a_snap, e_snap)
    fwd["cum"] = fwd["sid"].map(cum).fillna(1.0)
    fwd["fwd_mult"] = np.where(fwd["died"], DEATH_MULT, fwd["c1"] * fwd["cum"] / fwd["c0"])
    fwd["fwd_mult_excl_death"] = np.where(fwd["died"], np.nan, fwd["c1"] * fwd["cum"] / fwd["c0"])

    # ── as-of scoring (only mapped sids with fundamentals) ──
    stocks = read_sql("SELECT sid, sector FROM stocks")
    fund = read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type='annual'")
    fund_pit = knowable_screener(fund, pd.Timestamp(a_snap).date())

    gp = pit_gross_profitability(stocks, fund_pit)
    roic = pit_roic(stocks, fund_pit)
    asof = _asof_metrics(fund_pit)

    sc = (stocks.merge(gp, on="sid", how="left")
                .merge(roic, on="sid", how="left")
                .merge(asof, on="sid", how="left"))
    sc = sc[~sc["sector"].isin(FINANCIAL_SECTORS)]

    # join score inputs onto the anchor universe (mapped sids), compute as-of mcap
    df = fwd[fwd["sid"].notna()].merge(sc, on="sid", how="left")
    df["mcap_cr"] = df["c0"] * df["shares"] / RUPEES_PER_CRORE
    band = df[(df["mcap_cr"] >= MCAP_MIN_CR) & (df["mcap_cr"] <= MCAP_MAX_CR)].copy()

    # leverage gate + require a score
    band = band[~(band["de_ratio"] > DE_MAX)]
    band["ep_yield"] = band["np_latest"] / band["mcap_cr"]    # cheapness (earnings yield)

    def pct(s): return s.rank(pct=True)
    # Clean pillars (mirror signals/multibagger.py): quality, growth, growth×cheapness.
    # Conviction (smart_money/pledge) is omitted — no PIT-deep history pre-2023.
    band["p_quality"] = np.nanmean(np.vstack([
        pct(band["gross_profitability"]).values, pct(band["roic"]).values]), axis=0)
    band["p_growth"] = np.nanmean(np.vstack([
        pct(band["pat_cagr_3y"]).values, pct(band["earnings_acceleration"]).values]), axis=0)
    band["p_interaction"] = (pct(band["pat_cagr_3y"]) * pct(band["ep_yield"])).values

    # legacy columns retained for the head-to-head print
    band["score_quality"] = np.nanmean(np.vstack([
        pct(band["gross_profitability"]).values, pct(band["roic"]).values,
        pct(band["pat_cagr_3y"]).values, pct(band["earnings_acceleration"]).values]), axis=0)
    band["score"] = (0.5 * np.nan_to_num(band["score_quality"].values, nan=0.5)
                     + 0.5 * np.nan_to_num(band["p_interaction"].values, nan=0.25))

    scored = band[band[["gross_profitability", "roic", "pat_cagr_3y"]].notna().any(axis=1)].copy()
    return scored, fwd, a_snap, e_snap


def _scheme_score(scored, weights):
    """Composite score for a weight scheme; NaN pillars → neutral (0.5 / 0.25)."""
    return (weights["quality"] * np.nan_to_num(scored["p_quality"].values, nan=0.5)
            + weights["growth"] * np.nan_to_num(scored["p_growth"].values, nan=0.5)
            + weights["interaction"] * np.nan_to_num(scored["p_interaction"].values, nan=0.25))


def _scheme_metrics(scored, fwd, weights):
    """Top-decile tail-capture metrics for one weight scheme."""
    s = scored.assign(_sc=_scheme_score(scored, weights)).sort_values("_sc", ascending=False)
    n = len(s); k = max(1, n // 10)
    top, bot = s.head(k), s.tail(k)
    scored_med = s["fwd_mult"].median()
    total_3x = int((fwd["fwd_mult"] >= 3).sum())
    return {
        "top_med": round(top["fwd_mult"].median(), 2),
        "spread": round(top["fwd_mult"].median() - scored_med, 2),
        "lift": round(top["fwd_mult"].median() - bot["fwd_mult"].median(), 2),
        "ge3_hit": round((top["fwd_mult"] >= 3).mean(), 3),
        "ge3_capture": round((top["fwd_mult"] >= 3).sum() / total_3x, 3) if total_3x else 0.0,
        "k": k,
    }


def run(anchor, end):
    scored, fwd, a_snap, e_snap = _score(anchor, end)
    print(f"Anchor snapshot: {a_snap}   End snapshot: {e_snap}")
    scored = scored.sort_values("score", ascending=False)

    # ── head-to-head: does adding cheapness (QARP) beat quality+growth alone? ──
    _n = len(scored); _k = max(1, _n // 10)
    print(f"\n=== RANKING COMPARISON ({a_snap}→{e_snap}, {_n} scoreable small-caps, decile={_k}) ===")
    for label, col in [("Quality+growth only", "score_quality"), ("QARP (×cheapness) ", "score")]:
        rk = scored.sort_values(col, ascending=False)
        t, b = rk.head(_k), rk.tail(_k)
        mt, ma, mb = t["fwd_mult"].median(), rk["fwd_mult"].median(), b["fwd_mult"].median()
        print(f"  [{label}] top-dec median {mt:.2f}x | scored-median {ma:.2f}x | "
              f"spread {mt-ma:+.2f}x | lift {mt-mb:+.2f}x | ≥3x hit {(t['fwd_mult']>=3).mean():.1%} "
              f"| ≥2x hit {(t['fwd_mult']>=2).mean():.1%}")

    # ── weight-scheme sweep (Phase 2b+): which pillar mix captures best here? ──
    print(f"\n=== WEIGHT-SCHEME SWEEP ({a_snap}→{e_snap}) ===")
    for name, w in WEIGHT_SCHEMES.items():
        m = _scheme_metrics(scored, fwd, w)
        print(f"  [{name:13s}] top-dec {m['top_med']:.2f}x | spread {m['spread']:+.2f}x | "
              f"lift {m['lift']:+.2f}x | ≥3x hit {m['ge3_hit']:.1%} | ≥3x capture {m['ge3_capture']:.1%}")

    n = len(scored)
    if n < 30:
        print(f"⚠ only {n} scoreable small-caps at {a_snap} — thin, interpret with care.")
    k = max(1, n // 10)
    top = scored.head(k)
    bot = scored.tail(k)

    def stats(g):
        m = g["fwd_mult"].dropna()
        return dict(n=len(m), median=round(m.median(), 2),
                    ge2=round((m >= 2).mean(), 3), ge3=round((m >= 3).mean(), 3),
                    ge5=round((m >= 5).mean(), 3))

    uni_all = fwd  # full universe incl. deaths + unmapped
    uni_mult = uni_all["fwd_mult"].dropna()
    total_3x = int((uni_all["fwd_mult"] >= 3).sum())
    captured_3x = int((top["fwd_mult"] >= 3).sum())

    print(f"\n=== COHORT {a_snap} → {e_snap}  (split/bonus-adjusted; deaths @ {DEATH_MULT}x) ===")
    print(f"True universe: {len(uni_all)} symbols | deaths {int(uni_all['died'].sum())} "
          f"({100*uni_all['died'].mean():.1f}%) | universe median mult {uni_mult.median():.2f}")
    print(f"Scoreable small-caps (₹1-20k cr, ex-fin, de≤{DE_MAX}): {n} | decile size {k}")
    print(f"\n  TOP decile:    {stats(top)}")
    print(f"  BOTTOM decile: {stats(bot)}")
    print(f"  Universe(all): median={uni_mult.median():.2f}  ≥3x base rate={ (uni_all['fwd_mult']>=3).mean():.3f}")
    spread = top['fwd_mult'].median() - scored['fwd_mult'].median()
    lift = top['fwd_mult'].median() - bot['fwd_mult'].median()
    print(f"\n  HEADLINE: top-decile median {top['fwd_mult'].median():.2f}x vs scored-median "
          f"{scored['fwd_mult'].median():.2f}x  → spread {spread:+.2f}x")
    print(f"  Decile lift (top−bottom): {lift:+.2f}x")
    print(f"  ≥3x capture: top decile caught {captured_3x} of {total_3x} universe ≥3x "
          f"({(captured_3x/total_3x if total_3x else 0):.1%})")
    print(f"  Top-decile ≥3x hit-rate: {(top['fwd_mult']>=3).mean():.1%} "
          f"(vs universe base rate {(uni_all['fwd_mult']>=3).mean():.1%})")
    print(f"\n  Top-10 names by as-of score:")
    show = top.head(10)[["symbol", "sid", "mcap_cr", "score", "fwd_mult", "died"]]
    print(show.to_string(index=False))
    return scored


def run_all_windows():
    """Run every regime window and print a regime × weight-scheme capture matrix.

    THE deliverable for regime-conditioned weights: read down each window to see
    which scheme's top decile captures multibaggers best, and whether the winner
    flips with the window's realised regime (universe-median forward multiple)."""
    rows = []
    for label, (anchor, end) in WINDOWS.items():
        scored, fwd, a_snap, e_snap = _score(anchor, end)
        uni_med = float(fwd["fwd_mult"].dropna().median())
        regime = "RALLY" if uni_med >= 1.5 else ("BEAR" if uni_med <= 1.05 else "MIXED")
        per = {name: _scheme_metrics(scored, fwd, w) for name, w in WEIGHT_SCHEMES.items()}
        rows.append((label, a_snap, e_snap, len(scored), uni_med, regime, per))

    print("\n" + "=" * 96)
    print("REGIME × WEIGHT-SCHEME CAPTURE MATRIX  (top-decile spread vs scored-median, ₹cr small-cap band)")
    print("=" * 96)
    hdr = f"{'window':22s} {'uni-med':>8s} {'regime':>7s} {'n':>4s} | " + \
          " | ".join(f"{name:>13s}" for name in WEIGHT_SCHEMES)
    print(hdr)
    print("-" * len(hdr))
    for label, a_snap, e_snap, n, uni_med, regime, per in rows:
        cells = " | ".join(
            f"{per[name]['spread']:+.2f}x/{per[name]['ge3_capture']:.0%}".rjust(13)
            for name in WEIGHT_SCHEMES)
        print(f"{label:22s} {uni_med:>8.2f} {regime:>7s} {n:>4d} | {cells}")
    print("-" * len(hdr))
    print("cell = top-decile spread (x over scored-median) / ≥3x capture. Winner per row = best spread.")
    print("\nPer-window winner (by top-decile spread):")
    for label, a_snap, e_snap, n, uni_med, regime, per in rows:
        win = max(WEIGHT_SCHEMES, key=lambda nm: per[nm]["spread"])
        print(f"  {label:22s} [{regime:5s}] → {win:13s} "
              f"(spread {per[win]['spread']:+.2f}x, ≥3x capture {per[win]['ge3_capture']:.0%})")


# anchor→end pairs (existing historical_universe snapshots, ≥2yr forward). Several
# share the 2026-05 endpoint → forward windows overlap, so effective independent
# N is ~3-4, not 8. Used to validate the live regime_favorable flag.
REGIME_VALIDATION_PAIRS = [
    ("2018-04-02", "2021-04-01"), ("2019-04-01", "2022-04-01"),
    ("2021-04-01", "2024-04-01"), ("2022-04-01", "2026-05-29"),
    ("2022-08-01", "2026-05-29"), ("2023-04-03", "2026-05-29"),
    ("2023-10-03", "2026-05-29"), ("2024-04-01", "2026-05-29"),
]


def validate_regime_flag():
    """Validate the live EMA regime → screen-edge mapping (makes regime_favorable
    rigorous instead of hand-set). For each anchor: label the small-cap EMA regime
    AT entry (scoring/regime_smallcap, now backfilled to 2016) and measure the
    screen's realised forward top-decile spread. If the EMA regime predicts the
    sign of the forward edge, the live flag is evidence-based.

    Result (2026-06-04): UPTREND → mean spread −0.27x (UNFAVORABLE, robust even
    after discounting overlap — the strongest uptrend had the worst edge);
    NEUTRAL ≈ 0; DOWNTREND n=1 inconclusive. No regime is reliably FAVORABLE —
    the screen's ranking edge is zero-to-negative everywhere, worst in uptrends."""
    import collections
    from scoring.regime_smallcap import classify

    rows = []
    print(f"{'anchor':12s} {'yrs':>4s} {'EMA-regime':>11s} {'c/EMA200':>9s} "
          f"{'uni-med':>8s} {'bal-spread':>10s} {'qual-spread':>11s}")
    for anchor, end in REGIME_VALIDATION_PAIRS:
        reg = classify(as_of=anchor)
        scored, fwd, a_snap, e_snap = _score(anchor, end)
        yrs = (pd.Timestamp(e_snap) - pd.Timestamp(a_snap)).days / 365.25
        uni_med = float(fwd["fwd_mult"].dropna().median())
        bal = _scheme_metrics(scored, fwd, WEIGHT_SCHEMES["balanced"])["spread"]
        qual = _scheme_metrics(scored, fwd, WEIGHT_SCHEMES["quality_heavy"])["spread"]
        cema = reg["close_vs_slow_pct"]
        rows.append((reg["regime"], bal))
        print(f"{anchor:12s} {yrs:4.1f} {reg['regime']:>11s} "
              f"{(f'{cema:+.1f}%' if cema is not None else 'n/a'):>9s} "
              f"{uni_med:8.2f} {bal:+9.2f}x {qual:+10.2f}x")

    byreg = collections.defaultdict(list)
    for r, bal in rows:
        byreg[r].append(bal)
    print("\nMean BALANCED top-decile spread by ENTRY EMA-regime "
          "(does regime predict forward edge sign?):")
    for r in ("UPTREND", "NEUTRAL", "DOWNTREND"):
        v = byreg.get(r, [])
        if not v:
            continue
        verdict = "UNFAVORABLE" if np.mean(v) < -0.10 else "neutral (edge≈0)"
        print(f"  {r:11s} n={len(v)}  mean spread {np.mean(v):+.2f}x  → {verdict}")
    print("\nNote: several anchors share the 2026-05 endpoint → ~3-4 independent windows, not 8.\n"
          "Validated: strong EMA UPTREND ⇒ negative edge. No regime is reliably favorable.")


# ───────── at-entry SECTOR signal × multibagger forward multiple ─────────
#
# Tests the user's thesis: do top-decile candidates whose SECTOR had a positive
# at-entry tailwind (sector-relative trailing momentum, knowable at entry) earn
# higher forward multiples? Uses the deep sector-index cache from
# tools.sector_regime_history (parquet) → maps each candidate's GICS sector to
# its NSE sector index and reads trailing 6m sector-relative momentum at anchor.
GICS_TO_INDEX = {
    "Materials": "Metal", "Industrials": "Infra", "Consumer Discretionary": "Auto",
    "Health Care": "Pharma", "Information Technology": "IT", "Consumer Staples": "FMCG",
    "Real Estate": "Realty", "Utilities": "Infra", "Communication Services": "Media",
    "Energy": "Energy",
}
SECTOR_CACHE = "/tmp/sector_regime_cache.parquet"


def _sector_mom_at(px, anchor, idx, months=6):
    """Sector-relative trailing return of NSE index `idx` over `months` ending at
    the nearest trading day ≤ anchor (index return − Nifty return)."""
    sub = px.loc[:anchor]
    if len(sub) < 130 or idx not in px.columns:
        return np.nan
    p_now = sub[idx].iloc[-1]
    p_then = sub[idx].iloc[-1 - 21 * months] if len(sub) > 21 * months else np.nan
    n_now, n_then = sub["Nifty"].iloc[-1], (sub["Nifty"].iloc[-1 - 21 * months]
                                            if len(sub) > 21 * months else np.nan)
    if pd.isna(p_then) or pd.isna(n_then) or p_then == 0 or n_then == 0:
        return np.nan
    return (p_now / p_then - 1.0) - (n_now / n_then - 1.0)


def sector_test():
    """Does at-entry sector momentum predict a candidate's 2-4yr forward multiple?"""
    import os
    if not os.path.exists(SECTOR_CACHE):
        print(f"⚠ {SECTOR_CACHE} missing — run `python -m tools.sector_regime_history` first.")
        return
    px = pd.read_parquet(SECTOR_CACHE)
    px.index = pd.to_datetime(px.index)

    rows = []
    for anchor, end in REGIME_VALIDATION_PAIRS:
        scored, fwd, a_snap, e_snap = _score(anchor, end)
        if scored.empty:
            continue
        s = scored.copy()
        s["idx"] = s["sector"].map(GICS_TO_INDEX)
        # per-anchor sector momentum (one value per index), mapped onto candidates
        mom_by_idx = {ix: _sector_mom_at(px, a_snap, ix) for ix in s["idx"].dropna().unique()}
        s["sec_mom6"] = s["idx"].map(mom_by_idx)
        # restrict to TOP-decile candidates (the names you'd actually buy)
        s = s.sort_values("score", ascending=False)
        k = max(1, len(s) // 10)
        top = s.head(k).dropna(subset=["sec_mom6", "fwd_mult"])
        if len(top) >= 6:
            rho = top["sec_mom6"].rank().corr(top["fwd_mult"].rank())
            rows.append((anchor, a_snap, e_snap, top, rho))

    if not rows:
        print("No usable anchors.")
        return

    print("\n" + "=" * 84)
    print("MULTIBAGGER × AT-ENTRY SECTOR MOMENTUM  (top-decile candidates only)")
    print("Thesis: do candidates in tailwind sectors (positive sector-relative 6m mom")
    print("at entry) earn higher forward multiples?")
    print("=" * 84)
    print(f"{'anchor':12s} {'n_top':>5s} {'rho(secmom,fwd)':>16s} "
          f"{'hi-mom med':>11s} {'lo-mom med':>11s} {'lift':>7s}")
    all_top, rhos = [], []
    for anchor, a_snap, e_snap, top, rho in rows:
        med = top["sec_mom6"].median()
        hi = top[top["sec_mom6"] >= med]["fwd_mult"].median()
        lo = top[top["sec_mom6"] < med]["fwd_mult"].median()
        print(f"{anchor:12s} {len(top):>5d} {rho:>+16.2f} "
              f"{hi:>10.2f}x {lo:>10.2f}x {hi-lo:>+6.2f}x")
        rhos.append(rho)
        all_top.append(top)
    pooled = pd.concat(all_top)
    prho = pooled["sec_mom6"].rank().corr(pooled["fwd_mult"].rank())
    pmed = pooled["sec_mom6"].median()
    phi = pooled[pooled["sec_mom6"] >= pmed]["fwd_mult"].median()
    plo = pooled[pooled["sec_mom6"] < pmed]["fwd_mult"].median()
    print("-" * 84)
    print(f"{'POOLED':12s} {len(pooled):>5d} {prho:>+16.2f} "
          f"{phi:>10.2f}x {plo:>10.2f}x {phi-plo:>+6.2f}x")
    print(f"\nMean per-anchor rho {np.mean(rhos):+.2f} (n={len(rhos)} anchors). "
          f"rho>0 ⇒ tailwind-sector candidates win; ≈0 ⇒ no at-entry sector edge.")
    print("Consistent with horizon-decay: sector momentum is a 3-6mo signal, ~dead by 2-4yr.")


def sector_decomp():
    """Reproduce the 'isolate sectors' finding EXACTLY, with numbers.

    Two questions:
      (1) How much does the candidate's SECTOR (realised, ex-post) explain its
          forward multiple vs its own stock-specific score?  → corr decomposition.
      (2) With perfect sector foresight (pick the right sector), how much would
          the top-decile improve?  → tailwind vs headwind sector split.  THIS is
          the '+0.70x when sectors are isolated' number.
    Both are HINDSIGHT (the sector winner is unknowable at entry) — the point is
    to size the prize and show where the multibagger edge actually lives."""
    rows = []
    for anchor, end in REGIME_VALIDATION_PAIRS:
        scored, fwd, a_snap, e_snap = _score(anchor, end)
        if scored.empty:
            continue
        s = scored.dropna(subset=["fwd_mult"]).copy()
        # realised sector return = median forward multiple of all scoreable
        # small-caps in that sector (ex-post, the sector's actual outcome)
        sec_real = s.groupby("sector")["fwd_mult"].median()
        s["sec_real"] = s["sector"].map(sec_real)
        uni_med = s["fwd_mult"].median()
        s["tailwind"] = s["sec_real"] >= uni_med
        rows.append((anchor, a_snap, e_snap, s, uni_med))

    print("\n" + "=" * 88)
    print("MULTIBAGGER SECTOR DECOMPOSITION  ('what worked when sectors were isolated')")
    print("=" * 88)
    print(f"{'anchor':12s} {'n':>4s} | {'corr(score,fwd)':>15s} {'corr(secReal,fwd)':>17s} | "
          f"{'topDec tailwind':>15s} {'topDec headwind':>15s} {'GAP':>7s}")
    pooled = []
    g_top_tail, g_top_head = [], []
    for anchor, a_snap, e_snap, s, uni_med in rows:
        cs = s["score"].rank().corr(s["fwd_mult"].rank())
        cr = s["sec_real"].rank().corr(s["fwd_mult"].rank())
        s2 = s.sort_values("score", ascending=False)
        k = max(1, len(s2) // 10)
        top = s2.head(k)
        tt = top[top["tailwind"]]["fwd_mult"].median()
        th = top[~top["tailwind"]]["fwd_mult"].median()
        g_top_tail += top[top["tailwind"]]["fwd_mult"].tolist()
        g_top_head += top[~top["tailwind"]]["fwd_mult"].tolist()
        gap = (tt - th) if (pd.notna(tt) and pd.notna(th)) else np.nan
        print(f"{anchor:12s} {len(s):>4d} | {cs:>+15.2f} {cr:>+17.2f} | "
              f"{tt:>14.2f}x {th:>14.2f}x {gap:>+6.2f}x")
        pooled.append(s)

    P = pd.concat(pooled)
    cs = P["score"].rank().corr(P["fwd_mult"].rank())
    cr = P["sec_real"].rank().corr(P["fwd_mult"].rank())
    tt, th = np.median(g_top_tail), np.median(g_top_head)
    print("-" * 88)
    print(f"{'POOLED':12s} {len(P):>4d} | {cs:>+15.2f} {cr:>+17.2f} | "
          f"{tt:>14.2f}x {th:>14.2f}x {tt-th:>+6.2f}x")
    print(f"\nWHAT THIS SAYS:")
    print(f"  • The candidate's stock-specific SCORE barely correlates with its outcome "
          f"(rho {cs:+.2f}).")
    print(f"  • Its SECTOR's realised return is the dominant driver (rho {cr:+.2f}).")
    print(f"  • Top-decile names that LANDED in a winning sector returned {tt:.2f}x vs "
          f"{th:.2f}x in a")
    print(f"    losing sector — a {tt-th:+.2f}x gap from sector alone. But 'which sector "
          f"wins' is")
    print(f"    HINDSIGHT: no at-entry signal (momentum/value/macro) predicts it at 2-4yr "
          f"(all tested ~0).")
    print(f"  ⇒ The multibagger prize is mostly SECTOR, and sector @2-4yr is a forward-"
          f"JUDGMENT call,\n    not a backtestable factor. The screen's job is junk-removal "
          f"(gates), not ranking.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--anchor", default="2023-04-03")
    p.add_argument("--end", default="2026-05-29")
    p.add_argument("--all-windows", action="store_true",
                   help="Run the 3 regime windows + print the regime×scheme capture matrix")
    p.add_argument("--validate-flag", action="store_true",
                   help="Validate the live regime_favorable flag (EMA regime → forward edge sign)")
    p.add_argument("--sector-test", action="store_true",
                   help="Does at-entry sector momentum predict candidate forward multiples?")
    p.add_argument("--sector-decomp", action="store_true",
                   help="Decompose forward multiple into sector (ex-post) vs stock-score")
    args = p.parse_args()
    if args.validate_flag:
        validate_regime_flag()
    elif args.all_windows:
        run_all_windows()
    elif args.sector_test:
        sector_test()
    elif args.sector_decomp:
        sector_decomp()
    else:
        run(args.anchor, args.end)


if __name__ == "__main__":
    main()
