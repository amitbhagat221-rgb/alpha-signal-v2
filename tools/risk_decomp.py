"""
Risk decomposition — Barra-style (Track 3.3d, step 1).

The last unbuilt 3.3 piece. A cross-sectional factor risk model: explain each stock's
return by its exposure to STYLE factors (value/quality/momentum/analyst) + INDUSTRY
membership, leaving a SPECIFIC (idiosyncratic) residual. Then decompose a portfolio's
variance into style / industry / specific — so we can see whether the model's picks take
concentrated or unintended factor/industry risk (input to 3.3c portfolio construction).

Method (standard cross-sectional / "BARRA USE4"-lite):
- For each monthly anchor: STYLE exposures = the wired style factors z-scored cross-
  sectionally (missing → 0 = neutral); INDUSTRY = dummies off industry_id. Per-anchor OLS
  (NO intercept; full industry dummies absorb the market) of fwd_return_20d on
  [industry dummies | style z-scores] → that period's FACTOR RETURNS.
- Stack factor returns over anchors → FACTOR COVARIANCE Σ. Residuals → per-stock SPECIFIC
  variance.
- Portfolio risk: exposure vector b (industry weights ++ basket-avg style z) → factor var
  = bΣb', split into style / industry / cross blocks; specific var = Σ wᵢ²·σᵢ². Report the
  % split + the largest active style tilts and industry concentration.

Read-only — estimates no weights, deploys nothing. Caveats: fwd_return_20d on monthly
anchors overlaps (Σ slightly understated); no SIZE factor yet (cap_tier already segments
size); 20d horizon (a fast-risk lens). Foundation for the full 3.3d model.

Usage:
    python -m tools.risk_decomp                 # all tiers, equal-weight tier baskets
    python -m tools.risk_decomp --tier SMALL
"""

import argparse

import numpy as np
import pandas as pd

from config import PICKABLE_TIERS
from factors import SIGNAL_WEIGHTS
from db import read_sql

# Style factors for the risk model — keyed by their daily_snapshots_pit COLUMN, value =
# display name. (Direct PIT columns; high-coverage cross-sectional exposures.)
STYLE = {"book_to_price": "value_bp", "earnings_yield": "value_ey", "mom_12m": "momentum",
         "piotroski_f": "quality", "pt_upside": "analyst"}
# factors.SIGNAL_WEIGHTS key → its PIT style column (for the model-tilted basket score)
WEIGHT_TO_STYLE = {"book_to_price": "book_to_price", "earnings_yield": "earnings_yield",
                   "momentum": "mom_12m", "piotroski": "piotroski_f", "pt_upside": "pt_upside"}


def _zscore(v):
    v = pd.to_numeric(pd.Series(v), errors="coerce").astype(float).values
    if np.isnan(v).all():
        return np.zeros(len(v))
    mu, sd = np.nanmean(v), np.nanstd(v)
    z = (v - mu) / sd if sd > 1e-9 else np.zeros(len(v))
    return np.nan_to_num(z, nan=0.0)


def load_panel():
    style_cols = list(STYLE)
    panel = read_sql(
        "SELECT snapshot_date, sid, cap_tier, industry_id, fwd_return_20d, "
        + ", ".join(style_cols) + " FROM daily_snapshots_pit WHERE fwd_return_20d IS NOT NULL")
    bp = panel.groupby("snapshot_date")["book_to_price"].apply(lambda s: s.notna().sum())
    monthly = set(bp[bp >= 50].index)
    return panel[panel["snapshot_date"].isin(monthly)].copy(), style_cols


def estimate_factor_returns(panel, style_cols):
    """Per-anchor cross-sectional OLS → factor returns. Returns (factor_ret_df, resid_var, industries)."""
    industries = sorted(int(i) for i in panel["industry_id"].dropna().unique() if i and int(i) != 0)
    style_names = list(STYLE.values())
    col_for = {disp: col for col, disp in STYLE.items()}
    fac_rows, resid_sq = [], []
    for d in sorted(panel["snapshot_date"].unique()):
        g = panel[panel["snapshot_date"] == d]
        y = pd.to_numeric(g["fwd_return_20d"], errors="coerce").values
        ok = ~np.isnan(y)
        if ok.sum() < 50:
            continue
        y = y[ok]
        ind = g["industry_id"].values[ok]
        D = np.column_stack([(ind == i).astype(float) for i in industries])       # industry dummies
        S = np.column_stack([_zscore(g[col_for[n]].values[ok]) for n in style_names])  # style z
        X = np.column_stack([D, S])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        resid_sq.append(resid.var())
        fac_rows.append(dict(zip([f"ind_{i}" for i in industries] + style_names, beta)))
    fac = pd.DataFrame(fac_rows)
    return fac, float(np.mean(resid_sq)), industries, style_names


def _build_factor_cov(sids, g_anchor, fac, resid_var, industries, style_names):
    """Structured (Barra) stock covariance B Σ_f B' + D for `sids`, in 20d units.
    g_anchor is the full tier/universe cross-section at the anchor (for z-scoring + the
    exposure rows). Missing-exposure sids fall back to pure-specific (zero factor row)."""
    col_for = {disp: col for col, disp in STYLE.items()}
    gi = g_anchor.set_index("sid")
    zc = {nm: pd.Series(_zscore(gi[col_for[nm]].values), index=gi.index) for nm in style_names}
    ind_cols = [f"ind_{i}" for i in industries]
    Sigma_f = fac[ind_cols + style_names].cov().values
    sids = list(sids)
    B = np.zeros((len(sids), len(industries) + len(style_names)))
    n_fallback = 0
    for r, s in enumerate(sids):
        if s in gi.index:
            iid = gi.loc[s, "industry_id"]
            for j, i in enumerate(industries):
                if iid == i:
                    B[r, j] = 1.0
            for j, nm in enumerate(style_names):
                B[r, len(industries) + j] = float(zc[nm].get(s, 0.0))
        else:
            n_fallback += 1
    cov = B @ Sigma_f @ B.T + np.eye(len(sids)) * resid_var
    return pd.DataFrame(cov, index=sids, columns=sids), n_fallback


def factor_cov_daily(sids, asof=None):
    """Public hook for 3.3c HRP: structured DAILY covariance for `sids` from the factor
    risk model (B Σ_f B' + D, ÷20 from the 20d model → daily-variance units). A robust
    alternative to the n≈15 Ledoit-Wolf sample cov — it captures cross-stock correlation
    from SHARED factor exposures (e.g. the analyst tilt) that a short daily sample under-
    resolves. HRP weights are scale-invariant in cov, so the ÷20 only affects reported
    vol. Returns a sid-indexed DataFrame (sids not in the PIT panel → pure-specific)."""
    panel, style_cols = load_panel()
    if asof:
        panel = panel[panel["snapshot_date"] <= str(asof)]
    fac, resid_var, industries, style_names = estimate_factor_returns(panel, style_cols)
    anchor = sorted(panel["snapshot_date"].unique())[-1]
    g = panel[panel["snapshot_date"] == anchor]
    cov, _ = _build_factor_cov(sids, g, fac, resid_var, industries, style_names)
    return cov / 20.0


def attribute(panel, anchor_g, fac, resid_var, industries, style_names):
    """Decompose an equal-weight basket's variance into style / industry / cross / specific."""
    n = len(anchor_g)
    w = np.full(n, 1.0 / n)
    ind_cols = [f"ind_{i}" for i in industries]
    # basket exposures: industry = weight share in each industry; style = weighted avg z
    ind = anchor_g["industry_id"].values
    b_ind = np.array([w[(ind == i)].sum() for i in industries])
    col_for = {disp: col for col, disp in STYLE.items()}
    # basket style exposure = avg of stocks' z-scores computed vs the FULL cross-section
    b_sty = np.array([np.sum(w * anchor_g[f"_z_{nm}"].values) for nm in style_names])
    b = np.concatenate([b_ind, b_sty])
    Sigma = fac[ind_cols + style_names].cov().values
    n_ind = len(industries)
    var_factor = float(b @ Sigma @ b)
    # block split
    bi, bs = b[:n_ind], b[n_ind:]
    Sii, Sss, Sis = Sigma[:n_ind, :n_ind], Sigma[n_ind:, n_ind:], Sigma[:n_ind, n_ind:]
    v_ind, v_sty, v_cross = float(bi @ Sii @ bi), float(bs @ Sss @ bs), float(2 * bi @ Sis @ bs)
    v_spec = float(np.sum(w ** 2) * resid_var)
    v_total = var_factor + v_spec
    return dict(total=v_total, style=v_sty, industry=v_ind, cross=v_cross, specific=v_spec,
                b_sty=dict(zip(style_names, bs)), b_ind=dict(zip(industries, bi)))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--tier", choices=list(PICKABLE_TIERS), default=None)
    args = ap.parse_args()
    panel, style_cols = load_panel()
    fac, resid_var, industries, style_names = estimate_factor_returns(panel, style_cols)
    print(f"factor-return panel: {len(fac)} monthly anchors · {len(industries)} industries "
          f"+ {len(style_names)} style factors · mean specific σ = {np.sqrt(resid_var)*100:.2f}%/20d")
    print("annualised STYLE factor vol (√252/20 × σ_20d):")
    for s in style_names:
        print(f"  {s:10} {fac[s].std()*np.sqrt(252/20)*100:5.1f}%   (mean factor ret {fac[s].mean()*100:+.2f}%/20d)")

    latest = sorted(panel["snapshot_date"].unique())[-1]
    col_for = {disp: col for col, disp in STYLE.items()}
    for tier in ([args.tier] if args.tier else PICKABLE_TIERS):
        g = panel[(panel["snapshot_date"] == latest) & (panel["cap_tier"] == tier)].copy()
        if len(g) < 50:
            continue
        # z-score each style on the FULL tier cross-section (so the basket's avg-z is its tilt)
        for nm in style_names:
            g[f"_z_{nm}"] = _zscore(g[col_for[nm]].values)
        wts = SIGNAL_WEIGHTS[tier]
        score = np.zeros(len(g))
        for wk, col in WEIGHT_TO_STYLE.items():
            if wk in wts:
                score = score + abs(wts[wk]) * g[f"_z_{STYLE[col]}"].values
        g["_score"] = score
        basket = g.nlargest(30, "_score")                          # the model's top-30 (tilted)
        a = attribute(panel, basket, fac, resid_var, industries, style_names)
        t = a["total"]
        print(f"\n{'='*72}\n{tier} — MODEL top-30 basket (anchor {latest}) variance attribution\n{'='*72}")
        print(f"  total risk = {np.sqrt(t)*100:.2f}%/20d  ({np.sqrt(t*252/20)*100:.1f}% annualised)")
        for lbl in ("style", "industry", "cross", "specific"):
            print(f"    {lbl:10} {a[lbl]/t*100:+6.1f}%")
        top_sty = sorted(a["b_sty"].items(), key=lambda kv: -abs(kv[1]))[:4]
        print("  active STYLE tilts (basket-avg z vs tier): "
              + ", ".join(f"{k} {v:+.2f}" for k, v in top_sty))
        top_ind = sorted(a["b_ind"].items(), key=lambda kv: -kv[1])[:3]
        print(f"  industry concentration (top-3 of {len(industries)}): "
              + ", ".join(f"#{k} {v*100:.0f}%" for k, v in top_ind))
        # 3.3c HRP hook — structured factor cov vs a naive-independent estimate.
        fcov, nfb = _build_factor_cov(basket["sid"].tolist(), g, fac, resid_var, industries, style_names)
        wv = np.full(len(basket), 1.0 / len(basket))
        v_struct = np.sqrt(wv @ fcov.values @ wv)
        v_indep = np.sqrt((wv ** 2) @ np.diag(fcov.values))
        ann = np.sqrt(252 / 20)
        print(f"  factor-cov hook: book risk {ann*v_struct*100:.1f}% ann vs naive-independent "
              f"{ann*v_indep*100:.1f}% → shared-factor correlation inflates risk {v_struct/v_indep:.1f}× "
              f"(vs the n≈15 sample cov HRP uses today; {nfb} sids → specific)")


if __name__ == "__main__":
    main()
