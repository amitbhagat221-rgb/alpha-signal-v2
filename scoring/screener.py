"""
Alpha Signal v2 — Tier-Aware Scoring Engine

THE replacement for v1's 03_screener.py + 08_integrate_sentiment.py.

Reads all signal tables + inline signals (momentum, earnings yield).
Applies tier-specific weights from config.SIGNAL_WEIGHTS.
Ranks within each cap_tier. Applies forensic penalty.
Outputs scored universe to daily_picks table.

Usage:
    python -m scoring.screener            # score and save
    python -m scoring.screener --dry-run  # score but don't save
    python -m scoring.screener --top 20   # show top N per tier
"""

import argparse
from datetime import date

import numpy as np
import pandas as pd

from config import SIGNAL_WEIGHTS, PORTFOLIO, SCREEN
from db import read_sql, get_db, upsert_df


def _load_eligibility_wide():
    """Load latest universe_eligibility, pivot to wide (sid index × signal cols).
    Values are 0/1. Empty DataFrame if the table is empty (e.g. before first refresh).
    """
    try:
        long = read_sql(
            "SELECT sid, signal, eligible FROM universe_eligibility "
            "WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM universe_eligibility)"
        )
    except Exception:
        long = pd.DataFrame(columns=["sid", "signal", "eligible"])
    if long.empty:
        return pd.DataFrame(index=pd.Index([], name="sid"))
    return long.pivot(index="sid", columns="signal", values="eligible").fillna(1).astype(int)


def _load_signals():
    """Load all signal values for the latest snapshot date.
    Excludes MICRO tier (config.EXCLUDED_FROM_PICKS) — they're too illiquid + data-thin
    to recommend; see tools/classify_micro_tier.py for the spec."""
    from config import EXCLUDED_FROM_PICKS
    if EXCLUDED_FROM_PICKS:
        placeholders = ",".join("?" * len(EXCLUDED_FROM_PICKS))
        stocks = read_sql(
            f"SELECT sid, ticker, name, sector, cap_tier FROM stocks "
            f"WHERE cap_tier NOT IN ({placeholders})",
            params=list(EXCLUDED_FROM_PICKS),
        )
    else:
        stocks = read_sql("SELECT sid, ticker, name, sector, cap_tier FROM stocks")

    # Drop InvIT / REIT / business-trust instruments — different ranking
    # semantics from equities (distribution-yield vehicles, low float).
    # See SCREEN["trust_exclusion_patterns"]. 2026-05-24 audit found SHREI
    # (Shrem InvIT) with 40 of 65 trading days in last 90d ranked into SMALL.
    patterns = SCREEN.get("trust_exclusion_patterns", [])
    if patterns:
        pat_re = "|".join(patterns)
        trust_mask = stocks["name"].str.contains(pat_re, case=False, regex=True, na=False)
        dropped = trust_mask.sum()
        if dropped:
            print(f"  Excluded {dropped} InvIT/REIT/trust instruments from screener universe")
        stocks = stocks[~trust_mask].reset_index(drop=True)

    # Per-sid price-row count, used by the has-prices pick-eligibility gate.
    # A stock with zero (or near-zero) price history can't be charted, can't
    # have momentum/EY/B-P computed, and isn't really actionable even if it
    # scores well on fundamentals alone.
    price_counts = read_sql(
        "SELECT sid, COUNT(*) AS price_rows FROM stock_prices WHERE close > 0 GROUP BY sid"
    )

    # Per-sid quarterly_income row count → fundamental_coverage. INPUT-side
    # coverage (vs weight_coverage which is OUTPUT-side). 2026-05-24 audit:
    # ABSM ranked #164 SMALL with weight_coverage~0.6 because signal modules
    # emit non-NULL outputs from partial inputs (accruals_signal from BS
    # alone, consensus_signal from growth-only). Input coverage catches that.
    fundamental_counts = read_sql(
        "SELECT sid, COUNT(*) AS quarters_present FROM quarterly_income GROUP BY sid"
    )

    # Signal tables — get latest snapshot per stock
    piotroski = read_sql(
        "SELECT sid, f_score FROM piotroski_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM piotroski_scores GROUP BY sid)"
    )
    accruals = read_sql(
        "SELECT sid, accruals_signal FROM accruals_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM accruals_scores GROUP BY sid)"
    )
    # consensus_signal (composite) + pt_upside (top backtest factor t=7-9) + eps_growth (t=3-5).
    # Backtest evidence: tools/optimize_weights.py shows pt_upside and eps_growth dominate the
    # MaxReturn/MaxSharpe weight schemes (~80% of LARGE/MID weight together).
    consensus = read_sql(
        "SELECT sid, consensus_signal, pt_upside, eps_growth FROM consensus_signals "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM consensus_signals GROUP BY sid)"
    )
    # promoter_signal (composite) + pledge_quality (SMALL t=5.90, KEEP).
    # pledge_quality directly proxies promoter-pledge stress; coverage ~97% of the
    # promoter_signals universe. Non-colinear with promoter_signal per the 2026-05-29
    # factor-correlation diagnostic (different cluster).
    promoter = read_sql(
        "SELECT sid, promoter_signal, pledge_quality FROM promoter_signals "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM promoter_signals GROUP BY sid)"
    )
    forensic = read_sql(
        "SELECT sid, penalty FROM forensic_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM forensic_scores GROUP BY sid)"
    )
    smart_money = read_sql(
        "SELECT sid, smart_money_score FROM smart_money_scores "
        "WHERE (sid, snapshot_date) IN (SELECT sid, MAX(snapshot_date) FROM smart_money_scores GROUP BY sid)"
    )
    # iv_skew_25d — MID t=+3.16 KEEP over 48 weekly periods (wired 2026-05-31,
    # ADR 0035). In-house IV-surface skew; latest row per F&O stock. Orthogonal to
    # size/adtv/existing factors (|ρ|<0.15). Only F&O stocks have it → non-F&O MID
    # names get NULL and renormalise over present signals (correct: only F&O names
    # have options). Weighted in MID only (LARGE t=1.37 / SMALL t=0.17 DROP).
    iv_skew = read_sql(
        "SELECT sid, iv_skew_25d FROM fno_iv_history WHERE sid IS NOT NULL "
        "AND (sid, trade_date) IN (SELECT sid, MAX(trade_date) FROM fno_iv_history GROUP BY sid)"
    )

    # Inline signals (no DB table — compute on the fly)
    from signals.momentum import compute_momentum
    from signals.earnings_yield import compute_earnings_yield
    from signals.delivery_anomaly import compute_delivery_anomaly_z

    momentum = compute_momentum()
    earnings_yield = compute_earnings_yield()
    delivery_anomaly = compute_delivery_anomaly_z()

    # Book-to-price: total_equity / (shares_outstanding * close_price)
    book_to_price = _compute_book_to_price()

    # Merge everything onto stocks
    df = stocks.copy()
    df = df.merge(piotroski, on="sid", how="left")
    df = df.merge(accruals.rename(columns={"accruals_signal": "accruals"}), on="sid", how="left")
    df = df.merge(consensus.rename(columns={"consensus_signal": "consensus"}), on="sid", how="left")
    df = df.merge(promoter.rename(columns={"promoter_signal": "promoter"}), on="sid", how="left")
    df = df.merge(forensic, on="sid", how="left")
    df = df.merge(smart_money.rename(columns={"smart_money_score": "smart_money"}), on="sid", how="left")
    df = df.merge(momentum, on="sid", how="left")
    df = df.merge(earnings_yield, on="sid", how="left")
    df = df.merge(book_to_price, on="sid", how="left")
    df = df.merge(delivery_anomaly, on="sid", how="left")
    df = df.merge(iv_skew, on="sid", how="left")
    df = df.merge(price_counts, on="sid", how="left")
    df["price_rows"] = df["price_rows"].fillna(0).astype(int)

    df = df.merge(fundamental_counts, on="sid", how="left")
    df["quarters_present"] = df["quarters_present"].fillna(0).astype(int)
    df["fundamental_coverage"] = (df["quarters_present"] / 8.0).clip(upper=1.0)

    # Normalize smart_money from 0-100 to 0-1 for consistent percentile ranking
    df["smart_money"] = df["smart_money"] / 100.0

    # Revenue-plausibility hard exclusion (tier-agnostic) — drops stocks whose
    # reported revenue churns many times the asset base at ~zero profit, the
    # signature of fabricated revenue that Beneish/Altman structurally miss
    # (REXP, SEBI 2026-06-03). See signals/revenue_plausibility.py. Left-merge +
    # fillna(False): stocks without a full TTM/balance sheet are never flagged.
    from signals.revenue_plausibility import compute_revenue_plausibility
    implausible = compute_revenue_plausibility()
    df = df.merge(implausible, on="sid", how="left")
    df["revenue_implausible"] = df["revenue_implausible"].fillna(False).astype(bool)

    return df


def _compute_book_to_price():
    """Compute B/P = book value per share / price."""
    bs = read_sql(
        "SELECT sid, total_equity, shares_outstanding FROM annual_balance_sheet "
        "WHERE (sid, period) IN (SELECT sid, MAX(period) FROM annual_balance_sheet GROUP BY sid)"
    )
    prices = read_sql(
        "SELECT sid, close FROM stock_prices "
        "WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)"
    )

    merged = bs.merge(prices, on="sid")
    rows = []
    for _, r in merged.iterrows():
        bvps = None
        if (pd.notna(r["total_equity"]) and pd.notna(r["shares_outstanding"])
                and r["shares_outstanding"] > 0 and r["close"] > 0):
            bvps = r["total_equity"] / r["shares_outstanding"]
            bp = bvps / r["close"]
            rows.append({"sid": r["sid"], "book_to_price": bp})
        else:
            rows.append({"sid": r["sid"], "book_to_price": None})

    return pd.DataFrame(rows)


def _percentile_rank_within_tier(df, col):
    """Rank column within cap_tier as 0-1 percentile."""
    return df.groupby("cap_tier")[col].rank(pct=True)


def score_universe(df, weights: dict = None):
    """
    Apply tier-specific weights, rank within segment, apply forensic penalty.
    Returns scored DataFrame with final_score and rank columns.

    `weights` — optional override. Defaults to config.SIGNAL_WEIGHTS. Pass
    SIGNAL_WEIGHTS_RETURN or SIGNAL_WEIGHTS_SHARPE to score with an alternate
    scheme. Negative weights are honoured — inverse signals get a sign-flip
    on the percentile (1 - pctile) so the weighted sum stays directional.
    """
    if weights is None:
        weights = SIGNAL_WEIGHTS
    # Signal column mapping: config key → DataFrame column
    SIGNAL_COLS = {
        "consensus": "consensus",
        "earnings_yield": "earnings_yield",
        "accruals": "accruals",
        "piotroski": "f_score",
        "momentum": "mom_6m",        # 6M for LARGE, 12M for SMALL (handled below)
        "book_to_price": "book_to_price",
        "promoter": "promoter",
        "smart_money": "smart_money",
        # Wired 2026-05-28 — dominant in PIT IC backtest, were missing from screener:
        "pt_upside": "pt_upside",    # t=7.15 LARGE / 8.40 MID / 9.14 SMALL
        "eps_growth": "eps_growth",  # t=5.31 LARGE / 3.23 SMALL
        # Wired 2026-05-29 (Next-3 #3) — non-colinear bench factors per factor-correlation diagnostic:
        "pledge_quality":     "pledge_quality",      # t=5.90 SMALL (KEEP)
        "delivery_anomaly_z": "delivery_anomaly_z",  # t=4.76 SMALL (KEEP)
        # Wired 2026-05-31 (ADR 0035) — in-house IV skew, MID only:
        "iv_skew_25d":        "iv_skew_25d",          # t=+3.16 MID (KEEP, 48 wk periods)
    }

    # Percentile-rank all signals within tier (higher = better for all)
    for signal_key, col in SIGNAL_COLS.items():
        if col in df.columns:
            df[f"{signal_key}_pctile"] = _percentile_rank_within_tier(df, col)

    # For SMALL cap momentum, use 12M instead of 6M
    if "mom_12m" in df.columns:
        mom_12m_pctile = _percentile_rank_within_tier(df, "mom_12m")
        small_mask = df["cap_tier"] == "SMALL"
        df.loc[small_mask, "momentum_pctile"] = mom_12m_pctile[small_mask]

    # Compute weighted score per tier. We track:
    #   • scores             : weight × pctile, summed over non-NULL signals (the numerator)
    #   • weight_sums        : weights actually contributing (signal produced output)
    #   • tier_total_weight  : sum of all tier weights (raw denominator)
    #   • eligible_weight    : sum of weights where the signal was ELIGIBLE for this SID
    #                          (plan 0005 Phase A — see eligibility/registry.py)
    scores = pd.Series(0.0, index=df.index)
    weight_sums = pd.Series(0.0, index=df.index)
    tier_total_weight = pd.Series(0.0, index=df.index)
    eligible_weight = pd.Series(0.0, index=df.index)

    # Load today's eligibility snapshot, pivot to wide (sid × signal). Missing
    # (sid, signal) defaults to ELIGIBLE=1 (back-compat for signals not yet
    # in registry) — registered signals will have explicit rows.
    elig_wide = _load_eligibility_wide()

    for tier in ["LARGE", "MID", "SMALL"]:
        tier_mask = df["cap_tier"] == tier
        tier_weights = weights.get(tier, {})
        # Use abs(weight) for the denominator so negative-weight signals
        # contribute to coverage but don't shrink the sum.
        total_weight = sum(abs(w) for w in tier_weights.values())
        tier_total_weight.loc[tier_mask] = total_weight

        for signal_key, weight in tier_weights.items():
            pctile_col = f"{signal_key}_pctile"
            if pctile_col not in df.columns:
                continue
            vals = df.loc[tier_mask, pctile_col]
            valid = vals.notna()
            # Negative weight ⇒ inverse signal: invert the percentile (1 - p)
            # then multiply by |weight|. Result: high-quality stocks (e.g. low
            # accruals) get the positive contribution.
            if weight < 0:
                contribution = abs(weight) * (1.0 - vals[valid])
            else:
                contribution = weight * vals[valid]
            scores.loc[tier_mask & valid.reindex(df.index, fill_value=False)] += contribution
            weight_sums.loc[tier_mask & valid.reindex(df.index, fill_value=False)] += abs(weight)

            # Eligibility — if registry has this signal, only count toward
            # eligible_weight for SIDs marked eligible. If not registered,
            # treat all SIDs as eligible (preserves prior behaviour).
            if signal_key in elig_wide.columns:
                eligible_for_signal = elig_wide.reindex(df["sid"]).loc[
                    df.loc[tier_mask, "sid"], signal_key
                ].fillna(1).astype(int).values  # default ELIGIBLE if no row
                eligible_weight.loc[tier_mask] += abs(weight) * eligible_for_signal
            else:
                eligible_weight.loc[tier_mask] += abs(weight)

    # Normalize by actual weights used (handles NaN signals gracefully)
    df["base_score"] = np.where(weight_sums > 0, scores / weight_sums, np.nan)

    # weight_coverage = covered / TIER TOTAL (legacy semantics, unchanged).
    # A LARGE cap missing consensus drops to 0.6 regardless of why.
    df["weight_coverage"] = np.where(
        tier_total_weight > 0, weight_sums / tier_total_weight, np.nan
    )

    # eligible_coverage = covered / ELIGIBLE (new — plan 0005 Phase A).
    # Same LARGE cap missing consensus, but the SID was ineligible for
    # consensus (no analyst attribution) → eligible_coverage = 1.0 (perfect).
    # Surfaced for now; gate change is a follow-up commit once we've validated.
    df["eligible_coverage"] = np.where(
        eligible_weight > 0, weight_sums / eligible_weight, np.nan
    )

    # Apply forensic penalty
    df["penalty"] = df["penalty"].fillna(0)
    df["final_score"] = df["base_score"] + df["penalty"]
    df["final_score"] = df["final_score"].clip(lower=0)

    # Rank within tier (1 = best). Tie-break by sid for a deterministic 1..N
    # ordering — `method="min"` collapses ties to a shared rank and breaks
    # `SANITY:DAILY_PICKS_RANK_DUPLICATE` (PK (pick_date, cap_tier, rank)).
    df = df.sort_values(["cap_tier", "sid"], kind="mergesort").reset_index(drop=True)
    df["rank"] = df.groupby("cap_tier")["final_score"].rank(
        ascending=False, method="first", na_option="keep"
    ).astype("Int64")

    return df


MIN_ELIGIBLE_COVERAGE = 0.60  # ≥60% of the SID's ELIGIBLE signal weight produced output
MIN_WEIGHT_COVERAGE = 0.50    # ≥50% of TIER TOTAL weight (legacy floor — defence in depth)
MIN_PRICE_ROWS = 60           # ≈3 months of trading days
MIN_FUNDAMENTAL_COVERAGE = 0.50  # ≥4 of 8 quarterly_income rows (INPUT-side, added 2026-05-24)
# Thresholds + rationale: docs/decisions/0021-pick-eligibility-gate.md
# Plan 0005 Phase A.5 (2026-05-24): primary gate switched to eligible_coverage.
# A SMALL cap with no analyst attribution that scores well on its 6 ELIGIBLE
# signals is no longer punished for missing consensus (which was never going
# to apply). weight_coverage retained at 50% as a backstop — catches the
# pathological case where eligibility data itself is wrong.


def _pick_eligible(df, min_eligible: float = None):
    """Boolean Series: True where stock qualifies for daily_picks.

    Gate has 4 conditions, ALL must hold:
      • eligible_coverage ≥ min_eligible (default 0.60) — SID's ELIGIBLE signals produced enough output
      • weight_coverage   ≥ 0.50 — legacy backstop (in case eligibility data is wrong)
      • price_rows        ≥ 60  — ≥3 months of trading prices
      • fundamental_coverage ≥ 0.50 — ≥4 of 8 quarterly_income rows

    `min_eligible` override: variant runs ('return', 'sharpe') concentrate weight on
    analyst-dependent signals (pt_upside, eps_growth). Many SMALL caps have no
    analyst coverage so the 60% bar excludes them even though their non-analyst
    signals are sound. Variants pass 0.40 so those stocks remain rankable.
    """
    if min_eligible is None:
        min_eligible = MIN_ELIGIBLE_COVERAGE
    has_elig = df.get("eligible_coverage", df.get("weight_coverage")).fillna(0) >= min_eligible
    has_weight = df["weight_coverage"].fillna(0) >= MIN_WEIGHT_COVERAGE
    has_prices = df["price_rows"].fillna(0) >= MIN_PRICE_ROWS
    has_fundamentals = df["fundamental_coverage"].fillna(0) >= MIN_FUNDAMENTAL_COVERAGE
    # Revenue-plausibility hard exclusion — fabricated-revenue signature
    # (impossible asset turnover at ~zero margin). Tier-agnostic. See
    # signals/revenue_plausibility.py. Default False when the column is absent.
    plausible = ~df.get(
        "revenue_implausible", pd.Series(False, index=df.index)
    ).fillna(False).astype(bool)
    return has_elig & has_weight & has_prices & has_fundamentals & plausible


def select_picks(df, picks_per_tier=None, min_eligible: float = None):
    """Select top stocks per tier for daily output.

    Two-part gate:
      • `weight_coverage` ≥ 50% — at least half the tier signal weight backed
        by real data (rather than missing-signal renormalization inflating the
        score of a stock with only 1-2 signals).
      • `price_rows` ≥ 60 — at least ~3 months of price history. Without
        prices the stock has no chart, no momentum/EY/B-P, and isn't really
        actionable even if fundamentals look strong.
    """
    if picks_per_tier is None:
        picks_per_tier = PORTFOLIO["picks_per_tier"]

    eligible = _pick_eligible(df, min_eligible=min_eligible)
    elig_floor = min_eligible if min_eligible is not None else MIN_ELIGIBLE_COVERAGE
    dropped_elig = (df.get("eligible_coverage", df.get("weight_coverage")).fillna(0) < elig_floor).sum()
    dropped_coverage = ((df["weight_coverage"].fillna(0) < MIN_WEIGHT_COVERAGE)).sum()
    dropped_prices = ((df["price_rows"].fillna(0) < MIN_PRICE_ROWS)).sum()
    dropped_fundamentals = ((df["fundamental_coverage"].fillna(0) < MIN_FUNDAMENTAL_COVERAGE)).sum()
    implausible_mask = df.get(
        "revenue_implausible", pd.Series(False, index=df.index)
    ).fillna(False).astype(bool)
    print(f"  Pick gate: {(~eligible).sum()} excluded "
          f"({dropped_elig} below {elig_floor:.0%} eligible, "
          f"{dropped_coverage} below {MIN_WEIGHT_COVERAGE:.0%} weight, "
          f"{dropped_prices} below {MIN_PRICE_ROWS}d prices, "
          f"{dropped_fundamentals} below {MIN_FUNDAMENTAL_COVERAGE:.0%} fundamentals, "
          f"{implausible_mask.sum()} implausible revenue)")
    if implausible_mask.any():
        for _, r in df[implausible_mask].iterrows():
            print(f"    EXCLUDE {r['sid']} ({r['cap_tier']}): {r.get('implausible_reason')}")

    picks = []
    for tier, n in picks_per_tier.items():
        tier_df = df[(df["cap_tier"] == tier) & eligible].nsmallest(n, "rank")
        picks.append(tier_df)

    return pd.concat(picks).sort_values(["cap_tier", "rank"])


def compute(dry_run=False, top=None, variant: str = "production"):
    """Main entry point. Returns row count.

    variant:
      'production'  → use config.SIGNAL_WEIGHTS (the current live weights)
      'return'      → use config.SIGNAL_WEIGHTS_RETURN (MaxReturn, t-weighted)
      'sharpe'      → use config.SIGNAL_WEIGHTS_SHARPE (MaxSharpe, ICIR-weighted)

    Non-production variants are dry-run only — they print top picks but
    don't write to daily_picks (no schema change needed yet). Compare with
    production by running:
        python -m scoring.screener --variant production --top 10
        python -m scoring.screener --variant return --top 10
        python -m scoring.screener --variant sharpe --top 10
    """
    from config import SIGNAL_WEIGHTS, SIGNAL_WEIGHTS_RETURN, SIGNAL_WEIGHTS_SHARPE
    weights = {
        "production": SIGNAL_WEIGHTS,
        "return":     SIGNAL_WEIGHTS_RETURN,
        "sharpe":     SIGNAL_WEIGHTS_SHARPE,
    }[variant]
    print(f"Variant: {variant}")
    print("Loading signals...")
    df = _load_signals()

    print("Scoring universe...")
    df = score_universe(df, weights=weights)
    # Variants concentrate weight on pt_upside/eps_growth which have ~43%
    # coverage in SMALL — relax the eligibility floor for variants only.
    variant_gate = 0.40 if variant in ("return", "sharpe") else None

    today = date.today().isoformat()

    # Summary
    for tier in ["LARGE", "MID", "SMALL"]:
        t = df[df["cap_tier"] == tier]
        scored = t["final_score"].notna().sum()
        print(f"  {tier}: {scored} scored, mean={t['final_score'].dropna().mean():.3f}")

    # Show top picks
    show_n = top or 5
    picks = select_picks(df, {t: show_n for t in ["LARGE", "MID", "SMALL"]},
                          min_eligible=variant_gate)
    print(f"\nTop {show_n} per tier:")
    display_cols = ["rank", "cap_tier", "sid", "ticker", "sector", "final_score", "base_score", "penalty"]
    print(picks[display_cols].to_string(index=False))

    if dry_run or variant != "production":
        # Non-production variants always dry-run — daily_picks schema only
        # supports one row per (sid, pick_date), so variant runs only print.
        if variant != "production" and not dry_run:
            print(f"\nVariant '{variant}' is print-only (no daily_picks write).")
        else:
            print("\nDry run — not saving.")
        return len(df)

    # Save to daily_picks. Apply pick gate before saving — data-sparse and
    # priceless stocks stay out of daily_picks entirely so dossier/email
    # pipelines can't surface them as recommendations. Rank is re-densified
    # within the eligible set so the saved column reads as 1..N_eligible
    # without gaps.
    pick_date = today
    eligible_mask = _pick_eligible(df)
    eligible = df[eligible_mask].copy()
    gated_out = (~eligible_mask).sum()
    if gated_out:
        print(f"  Pick gate excluded {gated_out} stocks from daily_picks")

    eligible["rank"] = eligible.groupby("cap_tier")["final_score"].rank(
        ascending=False, method="first", na_option="keep"
    ).astype("Int64")

    out = eligible[["sid", "final_score", "rank", "base_score", "cap_tier", "sector",
                    "consensus", "accruals", "promoter",
                    "weight_coverage", "price_rows", "fundamental_coverage",
                    "eligible_coverage"]].copy()
    out["pick_date"] = pick_date
    out["sentiment_adj"] = 0  # placeholder
    out["insider_adj"] = 0
    out["forensic_adj"] = eligible["penalty"]
    out["macro_adj"] = 0
    out["piotroski_adj"] = 0
    out["accruals_adj"] = 0
    out["consensus_adj"] = 0
    out["promoter_adj"] = 0
    out["smart_money_adj"] = 0

    # Per-stock integrity validation (plan 0005 Phase B) — runs on the gated
    # eligible set so a FAIL bumps the SID out of action_queue / morning_brief
    # downstream. Status + reasons stored alongside other adjustments.
    from validators.per_stock_integrity import validate_picks
    integrity = validate_picks(eligible)
    out = out.merge(integrity, on="sid", how="left")
    out["integrity_status"] = out["integrity_status"].fillna("PASS")
    out["integrity_reasons"] = out["integrity_reasons"].fillna("")
    fail_n = (out["integrity_status"] == "FAIL").sum()
    warn_n = (out["integrity_status"] == "WARN").sum()
    if fail_n or warn_n:
        print(f"  Integrity validator: {fail_n} FAIL, {warn_n} WARN")

    # Match daily_picks schema
    picks_out = out[["sid", "pick_date", "final_score", "rank", "base_score",
                     "sentiment_adj", "insider_adj", "forensic_adj", "macro_adj",
                     "piotroski_adj", "accruals_adj", "consensus_adj", "promoter_adj",
                     "smart_money_adj", "cap_tier", "sector",
                     "weight_coverage", "price_rows", "fundamental_coverage",
                     "eligible_coverage", "integrity_status", "integrity_reasons"]]

    # Delete today's prior rows before insert. Upsert is REPLACE on (sid, pick_date)
    # which leaves rows untouched if today's run drops a sid (gated out by
    # coverage). Without this, rank gaps + duplicate rank values from prior
    # runs accumulate in the table.
    from db import get_db
    with get_db() as conn:
        conn.execute("DELETE FROM daily_picks WHERE pick_date = ?", (pick_date,))

    rows = upsert_df(picks_out, "daily_picks")
    print(f"\nSaved {rows} rows to daily_picks (date={pick_date})")

    # Plan 0007 Phase 5 — write per-pick UHS (uhs_score / uhs_label /
    # uhs_breakdown_json / uhs_worst_dim) for every row just landed.
    # Reads health_score for input factors + signal_lineage for Gate 6
    # coverage. Non-critical: a UHS write failure must NOT block the
    # primary pick write that just succeeded.
    try:
        from scoring.confidence import batch_write_pick_uhs
        batch_write_pick_uhs(pick_date)
    except Exception as e:
        import sys
        print(f"  ⚠ pick UHS write failed (non-critical): {e}", file=sys.stderr)

    return rows


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=5, help="Show top N per tier")
    parser.add_argument("--variant", choices=["production", "return", "sharpe"],
                        default="production",
                        help="Weight scheme to use (default: production). "
                             "Non-production is dry-run only.")
    args = parser.parse_args()
    compute(dry_run=args.dry_run, top=args.top, variant=args.variant)
