"""
Alpha Signal v2 — Track 3.3c — covariance-aware position sizing (HRP).

Turns the within-tier RANKED list (`daily_picks`) into a SIZED book and persists
it to `portfolio_weights`. This is the piece neither of the existing portfolio
surfaces does:
  • daily_picks        — ranked, no sizing.
  • paper_portfolio.py — equal-weight realized-return loop (ADR 0028).
  • cockpit /portfolio — DESCRIPTIVE (equal-weight view + Barra-style tilts).
  • THIS                — risk-allocated weights under real caps.

Method — Hierarchical Risk Parity (López de Prado 2016), NOT Markowitz mean-variance
(the plan-0002 §3.3c text). HRP allocates risk via a correlation-cluster hierarchy
with NO expected-return inputs, sidestepping Markowitz's error-maximiser instability
on a 15-name book estimated from 500 noisy daily returns. We then gently tilt by the
alpha score and clamp under per-stock / per-sector / liquidity caps. Rationale +
the deviation from the plan are recorded in ADR 0044.

Pipeline (mirrors hrp_prototype.py, which stays as the read-only exploration):
  1. select  — top `picks_per_tier` names per cap tier from the latest daily_picks.
  2. returns — daily log returns from stock_prices.close, winsorized (split-defense,
               raw/unadjusted closes — same rationale as signals/sector_momentum.py).
  3. cov     — Ledoit-Wolf-shrunk covariance (well-conditioned for n≈15, p≈500).
  4. liquid  — drop names below the ₹-ADTV floor (un-sizable for a retail book).
  5. hrp     — quasi-diagonalise + recursive bisection → risk-parity weights.
  6. tilt    — multiply by exp(λ·z(score)), renormalise.
  7. caps    — iterative projection onto per-stock AND per-sector ceilings.
  8. risk    — marginal (percent) risk contribution per name.
  9. store   — upsert into portfolio_weights (snapshot, PK = asof_date+sid).

ADVISORY ONLY: no capital is deployed until tools/validate_rank_skill.py clears
(<6 independent 20d windows as of 2026-06; 63d outcomes mature ~2026-07-06). This
builds the book on paper so the cockpit + validation have something to read.

HRP solved in-house (scipy.cluster only) — no Riskfolio dep, v1 venv untouched.

Usage:
  python -m portfolio_construction              # build + store the latest book
  python -m portfolio_construction --dry-run    # print, write nothing
  python -m portfolio_construction --date YYYY-MM-DD
"""

import argparse
from datetime import date as _date

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
from scipy.spatial.distance import squareform
from sklearn.covariance import LedoitWolf

import config
from db import read_sql, upsert_df

HRP = config.PORTFOLIO["hrp"]
PICKS_PER_TIER = config.PORTFOLIO["picks_per_tier"]
ADTV_WINDOW = 20  # trading days for the median traded-value liquidity screen


# ── selection ────────────────────────────────────────────────────────────────
def latest_pick_date():
    return read_sql("SELECT MAX(pick_date) m FROM daily_picks").iloc[0]["m"]


def select_candidates(asof):
    """Top picks_per_tier names per tier — over-select 3× so liquidity/history
    drops still leave a full tier (survivors trimmed in build())."""
    parts = []
    for tier, k in PICKS_PER_TIER.items():
        parts.append(read_sql(
            "SELECT sid, rank, final_score, cap_tier, sector FROM daily_picks "
            "WHERE pick_date=? AND cap_tier=? ORDER BY rank LIMIT ?",
            params=[asof, tier, k * 3]))
    return pd.concat(parts, ignore_index=True)


def daily_returns(sids, asof):
    """Winsorized daily log returns, one column per sid, last cov_lookback rows.

    stock_prices.close is raw/unadjusted, so a split shows up as a single huge
    daily return; clip to ret_clip to keep it from dominating the covariance
    (same split-defense rationale as signals/sector_momentum.py:RET_CLIP)."""
    ph = ",".join("?" * len(sids))
    px = read_sql(
        f"SELECT date, sid, close FROM stock_prices WHERE sid IN ({ph}) AND date<=?",
        params=[*sids, asof])
    wide = (px.pivot(index="date", columns="sid", values="close")
              .sort_index().tail(HRP["cov_lookback_days"] + 1))
    rets = np.log(wide / wide.shift(1))
    lo, hi = HRP["ret_clip"]
    rets = rets.clip(lower=lo, upper=hi)
    good = [s for s in rets.columns if rets[s].notna().sum() >= HRP["cov_min_obs"]]
    return rets[good].dropna()


def adtv(sids, asof):
    """Median daily turnover (₹) over the last ADTV_WINDOW sessions, per sid.

    Computed as close × volume rather than stock_prices.traded_value: the latter
    is frequently NULL and, where present, is in ₹-lakhs not ₹. close and volume
    are reliably populated, so close·volume is the robust ₹-turnover proxy."""
    ph = ",".join("?" * len(sids))
    px = read_sql(
        f"SELECT date, sid, close, volume FROM stock_prices "
        f"WHERE sid IN ({ph}) AND date<=? AND close>0 AND volume>0",
        params=[*sids, asof])
    if px.empty:
        return pd.Series(dtype=float)
    px["turnover"] = px["close"] * px["volume"]
    return (px.sort_values("date").groupby("sid")
              .tail(ADTV_WINDOW).groupby("sid")["turnover"].median())


# ── covariance ─────────────────────────────────────────────────────────────────
def shrunk_cov(rets):
    """Ledoit-Wolf-shrunk daily covariance as a sid-indexed DataFrame.

    n≈15 names from p≈500 returns is well-posed, but shrinkage still de-noises the
    off-diagonals that HRP's correlation clustering keys on. Falls back to the
    sample covariance if shrinkage is disabled or the estimator can't fit."""
    if HRP.get("ledoit_wolf", True):
        try:
            cov = LedoitWolf().fit(rets.values).covariance_
            return pd.DataFrame(cov, index=rets.columns, columns=rets.columns)
        except Exception:
            pass
    return rets.cov()


def _cov2corr(cov):
    d = np.sqrt(np.diag(cov.values))
    corr = cov.values / np.outer(d, d)
    return pd.DataFrame(np.clip(corr, -1.0, 1.0), index=cov.index, columns=cov.index)


# ── HRP (López de Prado 2016) ───────────────────────────────────────────────────
def _ivp(cov):
    iv = 1.0 / np.diag(cov)
    return iv / iv.sum()


def _cluster_var(cov, items):
    sub = cov.loc[items, items]
    w = _ivp(sub.values).reshape(-1, 1)
    return float((w.T @ sub.values @ w)[0, 0])


def _quasi_diag(link):
    link = link.astype(int)
    sort_ix = pd.Series([link[-1, 0], link[-1, 1]])
    n = link[-1, 3]
    while sort_ix.max() >= n:
        sort_ix.index = range(0, sort_ix.shape[0] * 2, 2)
        df0 = sort_ix[sort_ix >= n]
        i, j = df0.index, df0.values - n
        sort_ix[i] = link[j, 0]
        df0 = pd.Series(link[j, 1], index=i + 1)
        sort_ix = pd.concat([sort_ix, df0]).sort_index()
        sort_ix.index = range(sort_ix.shape[0])
    return sort_ix.tolist()


def _rec_bipart(cov, sort_ix):
    w = pd.Series(1.0, index=sort_ix)
    clusters = [sort_ix]
    while clusters:
        clusters = [c[j:k] for c in clusters
                    for j, k in ((0, len(c) // 2), (len(c) // 2, len(c))) if len(c) > 1]
        for i in range(0, len(clusters), 2):
            c0, c1 = clusters[i], clusters[i + 1]
            v0, v1 = _cluster_var(cov, c0), _cluster_var(cov, c1)
            alpha = 1 - v0 / (v0 + v1)
            w[c0] *= alpha
            w[c1] *= 1 - alpha
    return w


def hrp_weights(cov):
    corr = _cov2corr(cov)
    dist = ((1 - corr) / 2.0) ** 0.5
    link = sch.linkage(squareform(dist.values, checks=False), "single")
    order = [corr.index[i] for i in _quasi_diag(link)]
    return _rec_bipart(cov, order).reindex(corr.index)


# ── tilt + caps ─────────────────────────────────────────────────────────────────
def alpha_tilt(w, scores):
    """Tilt risk-parity weights toward higher alpha scores: w·exp(λ·z(score))."""
    z = (scores - scores.mean()) / (scores.std() or 1.0)
    w = w * np.exp(HRP["tilt_lambda"] * z.reindex(w.index).fillna(0))
    return w / w.sum()


def _cap_stocks(w, cap):
    """Water-fill: clamp names over `cap`, redistribute excess to the rest."""
    w = w.copy()
    for _ in range(100):
        over = w > cap + 1e-12
        if not over.any():
            break
        excess = (w[over] - cap).sum()
        w[over] = cap
        under = ~over
        if not under.any() or w[under].sum() <= 0:
            break
        w[under] += excess * w[under] / w[under].sum()
    return w / w.sum()


def apply_caps(w, sectors):
    """Project onto BOTH the per-stock and per-sector ceilings.

    Alternate the two projections (each renormalises to 1.0) until both hold or
    we hit the iteration budget — converges for feasible cap pairs; for an
    infeasible pair it lands on the closest near-feasible point and build()
    surfaces any residual breach."""
    stock_cap = HRP["max_stock_weight"]
    sector_cap = HRP["max_sector_weight"]
    sec = sectors.reindex(w.index).fillna("UNKNOWN")
    for _ in range(50):
        w = _cap_stocks(w, stock_cap)
        sw = w.groupby(sec).sum()
        over = sw[sw > sector_cap + 1e-9]
        if over.empty:
            break
        # Scale over-cap sectors down to the cap; push freed weight to under-cap
        # sectors in proportion to their current weight.
        for s in over.index:
            members = sec[sec == s].index
            w[members] *= sector_cap / sw[s]
        w = w / w.sum()
    return w


# ── risk ─────────────────────────────────────────────────────────────────────
def risk_contributions(w, cov):
    """Percent contribution to portfolio variance per name (Σ = 1.0).

    pct_i = w_i · (Σw)_i / (w' Σ w). The schema stores this as
    marginal_risk_contrib — the fraction of portfolio risk each name carries."""
    w = w.reindex(cov.index).fillna(0.0)
    sigma_w = cov.values @ w.values
    port_var = float(w.values @ sigma_w)
    if port_var <= 0:
        return pd.Series(0.0, index=w.index)
    return pd.Series(w.values * sigma_w / port_var, index=w.index)


def ann_vol(w, cov):
    w = w.reindex(cov.index).fillna(0.0).values
    return float(np.sqrt(w @ cov.values @ w * 252))


# ── build ────────────────────────────────────────────────────────────────────
def build(asof=None):
    """Construct the sized book for `asof` (default: latest daily_picks date).

    Returns (book_df, diagnostics) where book_df has the portfolio_weights
    columns and diagnostics carries ex-ante risk + concentration for the caller.
    Raises if there aren't enough investable names to form a book."""
    asof = asof or latest_pick_date()
    cand = select_candidates(asof)
    if cand.empty:
        raise RuntimeError(f"no daily_picks for {asof}")

    rets = daily_returns(cand["sid"].tolist(), asof)
    liq = adtv(cand["sid"].tolist(), asof)
    investable = {s for s in rets.columns
                  if liq.get(s, 0.0) >= HRP["min_adtv_inr"]}
    cand = cand[cand["sid"].isin(investable)]
    if cand.empty:
        raise RuntimeError(f"no investable names for {asof} "
                           f"(history + ₹{HRP['min_adtv_inr']:.0f} ADTV floor dropped all)")

    # trim to top picks_per_tier per tier among the survivors
    keep = pd.concat([g.nsmallest(PICKS_PER_TIER[t], "rank")
                      for t, g in cand.groupby("cap_tier")])
    sids = keep["sid"].tolist()
    # Recompute returns on the FINAL names only: the first pass dropna'd across all
    # over-selected candidates, so the shortest-history reject capped the common
    # window for everyone. Re-deriving on the kept names recovers the longest window.
    rets = daily_returns(sids, asof)
    keep = keep[keep["sid"].isin(rets.columns)]
    sids = keep["sid"].tolist()
    rets = rets[sids]

    cov = shrunk_cov(rets)
    w = hrp_weights(cov)
    w = alpha_tilt(w, keep.set_index("sid")["final_score"])
    w = apply_caps(w, keep.set_index("sid")["sector"])
    mrc = risk_contributions(w, cov)

    names = read_sql("SELECT sid, name FROM stocks").set_index("sid")["name"].to_dict()
    meta = keep.set_index("sid")
    book = pd.DataFrame({
        "asof_date": asof,
        "sid": w.index,
        "weight": w.values,
        "factor_score": meta["final_score"].reindex(w.index).values,
        "marginal_risk_contrib": mrc.reindex(w.index).values,
        "cap_tier": meta["cap_tier"].reindex(w.index).values,
        "sector": meta["sector"].reindex(w.index).values,
        "name": [names.get(s, s) for s in w.index],
        "rank": meta["rank"].reindex(w.index).values,
    }).sort_values("weight", ascending=False).reset_index(drop=True)

    sec_w = book.groupby("sector")["weight"].sum()
    diag = {
        "asof": asof,
        "n_names": len(book),
        "cov_obs": len(rets),
        "ann_vol_pct": ann_vol(w, cov) * 100,
        "ann_vol_eq_pct": ann_vol(pd.Series(1.0 / len(sids), index=sids), cov) * 100,
        "eff_n": float(1.0 / (w ** 2).sum()),
        "max_weight": float(w.max()),
        "max_sector_weight": float(sec_w.max()),
        "tier_weights": book.groupby("cap_tier")["weight"].sum().to_dict(),
        "top_sectors": sec_w.sort_values(ascending=False).head(3).to_dict(),
        "stock_cap_ok": bool(w.max() <= HRP["max_stock_weight"] + 1e-6),
        "sector_cap_ok": bool(sec_w.max() <= HRP["max_sector_weight"] + 1e-6),
    }
    return book, diag


def store(book):
    """Persist the book; replaces any prior rows for the same asof_date."""
    return upsert_df(book, "portfolio_weights")


def run():
    """Pipeline entrypoint — build + store the latest book, return rows written.

    Wired into PIPELINE_STEPS right after the screener (daily, NON-critical: a
    build failure on a thin day must not block dossier/email). Raises on an empty
    book rather than writing a placeholder (CLAUDE.md silent-failure rule); the
    non-critical flag means the pipeline logs FAILED and continues. ADVISORY ONLY
    — no capital deployed until the rank-skill validates."""
    book, _diag = build()
    store(book)
    return len(book)


def _print_report(book, diag):
    print(f"\n══ HRP SIZED BOOK  (picks {diag['asof']}, {diag['n_names']} names, "
          f"{diag['cov_obs']}d covariance) ══\n")
    print(f"  {'STOCK':28s} {'TIER':5s} {'SECTOR':20s} {'SCORE':>6s} "
          f"{'WEIGHT':>7s} {'%RISK':>6s}")
    for _, r in book.iterrows():
        print(f"  {str(r['name'])[:28]:28s} {str(r['cap_tier'])[:5]:5s} "
              f"{str(r['sector'])[:20]:20s} {r['factor_score']:6.3f} "
              f"{r['weight']*100:6.1f}% {r['marginal_risk_contrib']*100:5.0f}%")
    print(f"\n── ex-ante annualised vol ──")
    print(f"   HRP + tilt   : {diag['ann_vol_pct']:5.1f}%   (equal-weight {diag['ann_vol_eq_pct']:.1f}%)")
    print(f"   effective N  : {diag['eff_n']:.1f} of {diag['n_names']}   "
          f"max stock {diag['max_weight']*100:.1f}% · max sector {diag['max_sector_weight']*100:.0f}%")
    print(f"   tier weights : " + " · ".join(f"{t} {v*100:.0f}%" for t, v in diag["tier_weights"].items()))
    print(f"   top sectors  : " + " · ".join(f"{s[:14]} {v*100:.0f}%" for s, v in diag["top_sectors"].items()))
    if not diag["stock_cap_ok"] or not diag["sector_cap_ok"]:
        print(f"   ⚠ cap residual: stock_ok={diag['stock_cap_ok']} sector_ok={diag['sector_cap_ok']} "
              f"(cap pair may be infeasible for this book)")
    print(f"\n   ADVISORY ONLY — no capital deployed until validate_rank_skill clears.\n")


def main():
    ap = argparse.ArgumentParser(description="Track 3.3c — HRP position sizing")
    ap.add_argument("--date", help="pick_date to build from (default: latest)")
    ap.add_argument("--dry-run", action="store_true", help="print, write nothing")
    args = ap.parse_args()

    book, diag = build(args.date)
    _print_report(book, diag)
    if args.dry_run:
        print("   (--dry-run: portfolio_weights NOT written)\n")
    else:
        n = store(book)
        print(f"   wrote {len(book)} rows to portfolio_weights for {diag['asof']} "
              f"(upsert touched {n}).\n")


if __name__ == "__main__":
    main()
