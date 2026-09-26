"""
Track-2 PROTOTYPE — Hierarchical Risk Parity portfolio from the top picks.

Read-only proof-of-concept (writes nothing). Answers the design questions:
  • Universe   : top-K picks PER cap tier from latest daily_picks (not the whole
                 universe; the model only ranks within tier, so we preserve that).
  • # names    : capped (~20) — a holdable retail book.
  • Optimise   : HRP (López de Prado) — risk allocation via correlation-cluster
                 hierarchy, NO expected-return inputs (dodges Markowitz's
                 error-maximiser instability), then a gentle tilt by our alpha
                 score, then position caps.
  • Results    : the book + ex-ante risk vs equal-weight / inverse-vol
                 (ex-ante risk only — a return backtest on TODAY's picks would be
                 look-ahead; the proper walk-forward is the Track-2 "done when").

HRP solved in-house (scipy.cluster only) — no Riskfolio dep, v1 venv untouched.

Usage: python -m tools.hrp_prototype
"""

import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
from scipy.spatial.distance import squareform

from db import read_sql

TIER_K = {"LARGE": 7, "MID": 7, "SMALL": 6}   # → ~20-name book
LOOKBACK = 500       # trading days for covariance
MIN_OBS = 220        # drop names with thinner history
MAX_W = 0.10         # position cap
TILT_LAMBDA = 0.6    # alpha-score tilt strength (0 = pure HRP)


# ── selection ────────────────────────────────────────────────────────────────
def _latest_date():
    return read_sql("SELECT MAX(pick_date) m FROM daily_picks").iloc[0]["m"]


def _candidates(d):
    parts = []
    for tier, k in TIER_K.items():
        parts.append(read_sql(
            "SELECT sid, rank, final_score, cap_tier, sector FROM daily_picks "
            "WHERE pick_date=? AND cap_tier=? ORDER BY rank LIMIT ?",
            params=[d, tier, k * 3]))          # over-select; survivors trimmed later
    return pd.concat(parts, ignore_index=True)


def _returns(sids, d):
    ph = ",".join("?" * len(sids))
    px = read_sql(f"SELECT date, sid, close FROM stock_prices WHERE sid IN ({ph}) AND date<=?",
                  params=[*sids, d])
    wide = px.pivot(index="date", columns="sid", values="close").sort_index().tail(LOOKBACK + 1)
    rets = np.log(wide / wide.shift(1))
    good = [s for s in rets.columns if rets[s].notna().sum() >= MIN_OBS]
    return rets[good].dropna()


# ── HRP (López de Prado 2016) ─────────────────────────────────────────────────
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


def hrp_weights(rets):
    cov, corr = rets.cov(), rets.corr()
    dist = ((1 - corr) / 2.0) ** 0.5
    link = sch.linkage(squareform(dist.values, checks=False), "single")
    order = [corr.index[i] for i in _quasi_diag(link)]
    return _rec_bipart(cov, order).reindex(corr.index), cov


# ── tilt + caps ───────────────────────────────────────────────────────────────
def _apply(w, scores):
    z = (scores - scores.mean()) / (scores.std() or 1.0)
    w = w * np.exp(TILT_LAMBDA * z.reindex(w.index).fillna(0))     # alpha tilt
    w = w / w.sum()
    for _ in range(50):                                            # iterative max-cap
        over = w > MAX_W
        if not over.any():
            break
        excess = (w[over] - MAX_W).sum()
        w[over] = MAX_W
        under = ~over
        w[under] += excess * w[under] / w[under].sum()
    return w / w.sum()


def _ann_vol(w, cov):
    w = w.reindex(cov.index).fillna(0).values
    return float(np.sqrt(w @ cov.values @ w * 252))


def _consensus_upside(sids):
    """Per-stock analyst-consensus PT upside = price_target/last_close − 1.
    Same methodology as the cockpit portfolio page (api.get_analyst_consensus →
    pt_upside_pct), reusing the ADR-0037-cleaned analyst_consensus.price_target."""
    ph = ",".join("?" * len(sids))
    pt = read_sql(f"SELECT sid, price_target FROM analyst_consensus "
                  f"WHERE sid IN ({ph}) AND price_target IS NOT NULL", params=list(sids))
    px = read_sql(f"SELECT sid, date, close FROM stock_prices WHERE sid IN ({ph})", params=list(sids))
    last = px.sort_values("date").groupby("sid")["close"].last()
    out = {}
    for _, r in pt.iterrows():
        c = last.get(r["sid"])
        if c and c > 0:
            out[r["sid"]] = r["price_target"] / c - 1.0
    return pd.Series(out)


def main():
    d = _latest_date()
    cand = _candidates(d)
    rets = _returns(cand["sid"].tolist(), d)
    cand = cand[cand["sid"].isin(rets.columns)]
    # trim to top-K per tier among survivors
    keep = pd.concat([g.nsmallest(TIER_K[t], "rank") for t, g in cand.groupby("cap_tier")])
    rets = rets[keep["sid"].tolist()]
    cov = rets.cov()
    names = read_sql("SELECT sid, name FROM stocks").set_index("sid")["name"].to_dict()

    w_hrp, cov = hrp_weights(rets)
    scores = keep.set_index("sid")["final_score"]
    w = _apply(w_hrp, scores)

    meta = keep.set_index("sid")
    upside = _consensus_upside(book_sids := w.index.tolist())
    book = pd.DataFrame({"w": w}).join(meta)
    book["upside"] = upside.reindex(book.index)
    book = book.sort_values("w", ascending=False)

    print(f"\n══ HRP PROTOTYPE BOOK  (picks {d}, {len(book)} names, {len(rets)}d covariance) ══\n")
    print(f"  {'STOCK':30s} {'TIER':5s} {'SECTOR':22s} {'SCORE':>6s} {'WEIGHT':>7s} {'PT UPSIDE':>9s}")
    for sid, r in book.iterrows():
        up = f"{r['upside']*100:+.0f}%" if pd.notna(r['upside']) else "  n/a"
        print(f"  {names.get(sid, sid)[:30]:30s} {r['cap_tier'][:5]:5s} {str(r['sector'])[:22]:22s} "
              f"{r['final_score']:6.3f} {r['w']*100:6.1f}% {up:>9s}")

    # ── expected return from analyst consensus (the portfolio-page methodology) ──
    cov_mask = book["upside"].notna()
    cov_w = book.loc[cov_mask, "w"].sum()
    er_wt = (book.loc[cov_mask, "w"] * book.loc[cov_mask, "upside"]).sum() / cov_w if cov_w else None
    er_simple = book.loc[cov_mask, "upside"].mean() if cov_mask.any() else None
    print(f"\n── expected return (analyst-consensus PT upside — same as portfolio page) ──")
    if er_wt is not None:
        print(f"   HRP-weighted     : {er_wt*100:+5.1f}%   ← weight × consensus PT upside, summed")
        print(f"   equal-weight     : {er_simple*100:+5.1f}%   (the page's simple-average method)")
        print(f"   coverage         : {int(cov_mask.sum())}/{len(book)} names have a target "
              f"= {cov_w*100:.0f}% of book weight (small-caps often uncovered)")
        print(f"   horizon          : analyst PT ≈ 12-month target → this is a ~1Y expected price return.")

    # ex-ante risk comparison
    w_eq = pd.Series(1.0 / len(rets.columns), index=rets.columns)
    w_iv = pd.Series(_ivp(cov.values), index=cov.index)
    eff_n = 1.0 / (w ** 2).sum()
    sect = book.groupby("sector")["w"].sum().sort_values(ascending=False)
    tierw = book.groupby("cap_tier")["w"].sum()

    print(f"\n── ex-ante annualised volatility (same names) ──")
    print(f"   equal-weight : {_ann_vol(w_eq, cov)*100:5.1f}%")
    print(f"   inverse-vol  : {_ann_vol(w_iv, cov)*100:5.1f}%")
    print(f"   HRP + tilt   : {_ann_vol(w, cov)*100:5.1f}%   ← robust, diversified")
    print(f"\n── concentration / exposure ──")
    print(f"   effective N      : {eff_n:.1f} of {len(book)}   (1/Σw²; higher = better spread)")
    print(f"   max position     : {w.max()*100:.1f}%  (cap {MAX_W*100:.0f}%)")
    print(f"   tier weights     : " + " · ".join(f"{t} {v*100:.0f}%" for t, v in tierw.items()))
    print(f"   top sectors      : " + " · ".join(f"{s[:14]} {v*100:.0f}%" for s, v in sect.head(3).items()))
    print(f"\n   (ex-ante RISK only — no return backtest: holding today's picks over past")
    print(f"    returns is look-ahead. Walk-forward return test = the Track-2 'done when'.)")
    print(f"   constraints in this proto: top-K/tier select · {MAX_W*100:.0f}% position cap · alpha tilt.")
    print(f"   FULL Track-2 adds: sector caps · ADTV/liquidity caps · per-tier risk budget · turnover/cost.\n")


if __name__ == "__main__":
    main()
