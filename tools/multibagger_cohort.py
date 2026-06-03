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

import numpy as np
import pandas as pd

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


# ───────── the study ─────────

def run(anchor, end):
    # nearest actual bhavcopy snapshot dates we stored
    uni = read_sql("SELECT snapshot_date FROM historical_universe GROUP BY snapshot_date "
                   "ORDER BY ABS(julianday(snapshot_date) - julianday(?)) LIMIT 1", params=[anchor])
    a_snap = uni["snapshot_date"].iloc[0]
    uni = read_sql("SELECT snapshot_date FROM historical_universe GROUP BY snapshot_date "
                   "ORDER BY ABS(julianday(snapshot_date) - julianday(?)) LIMIT 1", params=[end])
    e_snap = uni["snapshot_date"].iloc[0]
    print(f"Anchor snapshot: {a_snap}   End snapshot: {e_snap}")

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
    q = np.nanmean(np.vstack([
        pct(band["gross_profitability"]).values,
        pct(band["roic"]).values,
        pct(band["pat_cagr_3y"]).values,
        pct(band["earnings_acceleration"]).values,
    ]), axis=0)
    interaction = (pct(band["pat_cagr_3y"]) * pct(band["ep_yield"])).values   # growth × cheapness
    band["score_quality"] = q                                  # quality+growth only (run 1)
    band["score"] = 0.5 * np.nan_to_num(q, nan=0.5) + 0.5 * np.nan_to_num(interaction, nan=0.25)  # QARP
    scored = band[band[["gross_profitability", "roic", "pat_cagr_3y"]].notna().any(axis=1)].copy()
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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--anchor", default="2023-04-03")
    p.add_argument("--end", default="2026-05-29")
    args = p.parse_args()
    run(args.anchor, args.end)


if __name__ == "__main__":
    main()
