"""
Factor marginal-contribution diagnostic (Track 3.3b — orthogonalization), HORIZON-AWARE.

The model wires ~26 (factor,tier) weights, many of them correlated value/quality factors.
3.3b's gate-rule: a factor should add IC AFTER controlling for the others, else it's redundant
ballast double-counting the same bet. BUT marginal contribution is HORIZON-dependent — a slow
value factor (book_to_price, gate-natural-horizon 252d) looks redundant at 20d yet earns its
weight at 252d. So we judge each factor at a GRID of horizons, not just 20d.

Method — sequential rank-IC at each horizon (collinearity-robust):
- For each tier × monthly anchor: rank-percentile each wired factor AND the forward return
  (Spearman; missing factor → 0.5 neutral, mirroring "renormalise over present signals").
- UNIVARIATE IC = corr(rank(factor), rank(fwd_H)); order factors by |univariate FM-t|.
- INCREMENTAL IC = partial corr of the factor with fwd_H after residualising both against the
  already-included (higher-ranked) factors. Strong univariate but ~0 incremental = REDUNDANT.
- Fama-MacBeth t with a NEWEY-WEST correction (lag = round(H/21)−1) because long-horizon
  forward windows from monthly anchors overlap — without it the long-end t is inflated.

Forward returns at {20,63,126,252}d are computed from stock_prices (reuses ic_decay helpers).
Read-only — changes no weights. Feeds the deliberate weight review (signal-weights.md).
Caveat: weekly-native factors (iv_skew_25d) are sparse on monthly anchors → judge on their own
panel. Low-coverage factors (cov<50%) are 0.5-imputation-distorted → flagged ⚠, lean on backtest.

Usage:
    python -m tools.factor_marginal                 # all tiers, horizon matrix
    python -m tools.factor_marginal --tier MID
"""

import argparse

import numpy as np
import pandas as pd

from config import SIGNAL_WEIGHTS, SIGNAL_GROUPS
from db import read_sql
from tools.backtest_pit import SIGNAL_COLUMN_MAP
from tools.ic_decay import _fwd_panel, _price_series
from tools.multiple_testing import _ALIAS

HORIZONS = [20, 63, 126, 252]      # trading days ≈ 1mo / 3mo / 6mo / 1yr
ANCHOR_GAP = 21                    # monthly anchors ≈ 21 trading days apart


def _v2col(config_key: str) -> str | None:
    bid = _ALIAS.get(config_key, config_key)
    return SIGNAL_COLUMN_MAP.get(bid, (None, None))[1]


def _nw_lag(h: int) -> int:
    return max(0, round(h / ANCHOR_GAP) - 1)


def _fm_t(series: np.ndarray, nw_lag: int = 0):
    """Fama-MacBeth mean + Newey-West t over per-anchor estimates."""
    s = series[~np.isnan(series)]
    T = len(s)
    if T < 5:
        return np.nan, np.nan, T
    mean = s.mean()
    x = s - mean
    var = (x @ x) / T
    for l in range(1, min(nw_lag, T - 1) + 1):
        cov = (x[l:] @ x[:-l]) / T
        var += 2 * (1 - l / (nw_lag + 1)) * cov
    se = np.sqrt(max(var, 0) / T)
    return mean, (mean / se if se > 0 else np.nan), T


def _resid(a: np.ndarray, Z: np.ndarray) -> np.ndarray:
    M = np.column_stack([np.ones(len(a)), Z])
    beta, *_ = np.linalg.lstsq(M, a, rcond=None)
    return a - M @ beta


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.std() < 1e-12 or b.std() < 1e-12:
        return np.nan
    return float(np.corrcoef(a, b)[0, 1])


def _marginal_at_horizon(sub, factors, target, nw_lag):
    """Sequential rank-IC marginal contribution at one horizon. Returns {factor: (uni_t, incr_t, cov)}."""
    keys = list(factors)
    per_anchor, cov = [], {k: [] for k in keys}
    for d in sorted(sub["snapshot_date"].unique()):
        g = sub[sub["snapshot_date"] == d]
        y = g[target].values
        ok = ~np.isnan(y)
        if ok.sum() < 25:
            continue
        yv = pd.Series(y[ok]).rank(pct=True).values - 0.5
        Xr = {}
        for k, c in factors.items():
            v = g[c].values[ok]
            cov[k].append(float(np.mean(~np.isnan(v))))
            r = pd.Series(v).rank(pct=True).values
            r[np.isnan(r)] = 0.5
            Xr[k] = r - 0.5
        per_anchor.append((yv, Xr))
    if not per_anchor:
        return {k: (np.nan, np.nan, np.nan) for k in keys}
    uni = {k: _fm_t(np.array([_corr(a[1][k], a[0]) for a in per_anchor]), nw_lag) for k in keys}
    order = sorted(keys, key=lambda k: -(abs(uni[k][1]) if not np.isnan(uni[k][1]) else 0))
    out, included = {}, []
    for k in order:
        ics = []
        for yv, Xr in per_anchor:
            if included:
                Z = np.column_stack([Xr[j] for j in included])
                ics.append(_corr(_resid(Xr[k], Z), _resid(yv, Z)))
            else:
                ics.append(_corr(Xr[k], yv))
        _, it, _ = _fm_t(np.array(ics), nw_lag)
        out[k] = (uni[k][1], it, np.mean(cov[k]) if cov[k] else np.nan)
        included.append(k)
    return out


def _avg_within_group_corr(sub, factors):
    """Mean across anchors of the avg |pairwise rank-corr| among a group's factors.
    The raw collinearity the within-group residualisation is correcting for."""
    cols, vals = list(factors.values()), []
    if len(cols) < 2:
        return np.nan
    for d in sorted(sub["snapshot_date"].unique()):
        g = sub[sub["snapshot_date"] == d]
        R = g[cols].rank(pct=True)
        if len(R) < 25:
            continue
        C = R.corr(method="pearson").values   # pearson on ranks = Spearman
        iu = np.triu_indices_from(C, k=1)
        pair = np.abs(C[iu])
        pair = pair[~np.isnan(pair)]
        if pair.size:
            vals.append(pair.mean())
    return float(np.mean(vals)) if vals else np.nan


def within_group(panel, tier):
    """3.3b-3 — within-group orthogonalisation diagnostic. For each factor group with
    ≥2 wired factors in this tier, run the sequential rank-IC residualising ONLY against
    same-group higher-|t| factors (cross-group kept raw). A factor whose incr_t collapses
    vs its univariate is redundant WITHIN its family; one that holds is genuinely additive."""
    wired = {k: c for k in SIGNAL_WEIGHTS[tier] if (c := _v2col(k))}
    groups = {}
    for k in wired:
        groups.setdefault(SIGNAL_GROUPS.get(k, "Other"), {})[k] = wired[k]
    sub = panel[panel.cap_tier == tier]
    hdr = "  ".join(f"{h}d" for h in HORIZONS)
    print(f"{'='*82}\n{tier} — WITHIN-GROUP incremental t by horizon (residualised vs same-group only)\n{'='*82}")
    multi = {g: f for g, f in groups.items() if len(f) >= 2}
    if not multi:
        print("  (no group has ≥2 wired factors in this tier — nothing to orthogonalise)\n")
        return
    for g, gf in sorted(multi.items()):
        rho = _avg_within_group_corr(sub, gf)
        res = {h: _marginal_at_horizon(sub, gf, f"fwd_{h}", _nw_lag(h)) for h in HORIZONS}
        print(f"\n  ▸ {g}  (avg within-group |ρ| = {rho:.2f})")
        print(f"    {'factor':22} {'wt':>6} {'uni_t':>6} {'cov':>5}   {hdr}")
        for k in sorted(gf, key=lambda k: -abs(SIGNAL_WEIGHTS[tier][k])):
            row = [res[h][k] for h in HORIZONS]
            uni = next((r[0] for r in row if not np.isnan(r[0])), np.nan)
            cov = next((r[2] for r in row if not np.isnan(r[2])), np.nan)
            cells = "  ".join(f"{(r[1] if not np.isnan(r[1]) else 0):+5.1f}" for r in row)
            lc = " ⚠" if (not np.isnan(cov) and cov < 0.5) else ""
            print(f"    {k:22} {SIGNAL_WEIGHTS[tier][k]:+6.2f} {uni:>6.1f} {cov*100:4.0f}%   {cells}{lc}")
    print("\n  Reading: within a group, a factor with high uni_t but ~0 incr_t is the REDUNDANT")
    print("  member (its bet is already in a higher-|t| same-group factor). Read-only — no weights changed.\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--tier", choices=["LARGE", "MID", "SMALL"], default=None)
    ap.add_argument("--within-group", action="store_true",
                    help="3.3b-3: residualise each factor only against same-group factors")
    args = ap.parse_args()

    wired_cols = sorted({c for w in SIGNAL_WEIGHTS.values() for k in w
                         if (c := _v2col(k)) is not None})
    panel = read_sql(
        "SELECT snapshot_date, sid, cap_tier, " + ", ".join(wired_cols)
        + " FROM daily_snapshots_pit")
    # monthly anchors only (the fundamental block is NaN on weekly anchors)
    bp = panel.groupby("snapshot_date")["book_to_price"].apply(lambda s: s.notna().sum())
    monthly = set(bp[bp >= 50].index)
    panel = panel[panel["snapshot_date"].isin(monthly)].copy()

    print(f"computing forward returns at {HORIZONS}d from stock_prices …")
    fwd = _fwd_panel(panel[["snapshot_date", "sid"]], _price_series())
    fwd["snapshot_date"] = fwd["snapshot_date"].astype(str)
    panel["snapshot_date"] = panel["snapshot_date"].astype(str)
    panel = panel.merge(fwd, on=["snapshot_date", "sid"], how="left")
    print(f"monthly anchors: {len(monthly)} · incremental IC = partial rank-corr after the higher-|t| factors")
    print("incr_t Newey-West-corrected for forward-window overlap; ⚠ = coverage <50% (imputation-distorted)\n")

    for tier in ([args.tier] if args.tier else ["LARGE", "MID", "SMALL"]):
        if args.within_group:
            within_group(panel, tier)
            continue
        factors = {k: c for k in SIGNAL_WEIGHTS[tier] if (c := _v2col(k))}
        results = {h: _marginal_at_horizon(panel[panel.cap_tier == tier], factors,
                                           f"fwd_{h}", _nw_lag(h)) for h in HORIZONS}
        hdr = "  ".join(f"{h}d" for h in HORIZONS)
        print(f"{'='*78}\n{tier} — incremental t by horizon\n{'='*78}")
        print(f"{'factor':22} {'wt':>6} {'cov':>5}   {hdr}    natural")
        # order by weight
        for k in sorted(factors, key=lambda k: -abs(SIGNAL_WEIGHTS[tier][k])):
            row = [results[h][k] for h in HORIZONS]
            cov = next((r[2] for r in row if not np.isnan(r[2])), np.nan)
            cells = "  ".join(f"{(r[1] if not np.isnan(r[1]) else 0):+5.1f}" for r in row)
            # natural horizon = where |incr_t| peaks
            best = max(range(len(HORIZONS)), key=lambda i: abs(row[i][1]) if not np.isnan(row[i][1]) else 0)
            nat = f"{HORIZONS[best]}d" if any(not np.isnan(r[1]) for r in row) else "n/a"
            lc = " ⚠" if (not np.isnan(cov) and cov < 0.5) else ""
            print(f"{k:22} {SIGNAL_WEIGHTS[tier][k]:+6.2f} {cov*100:4.0f}%   {cells}   {nat:>5}{lc}")


if __name__ == "__main__":
    main()
