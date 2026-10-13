"""
Plan 0025 task 1.1 — is the best plan-0024 long-hold variant luck?  (READ-ONLY; no DB access)

Input: data/lh/book_monthly.parquet (tools.lh_book), the 48 'grid' variants per tier.
Per variant the monthly series is the after-tax-liquidation-value (ATLV) excess over the tier
index, exactly as tools.lh_book.summarise: x_t = atlv_t/atlv_t-1 - bench_t/bench_t-1.

Pre-registered (2026-10-13, before any result):
  1. Effective number of independent trials (Bailey & Lopez de Prado 2014, App. A.3 approx.):
       N_eff = rho_bar + (1 - rho_bar) * M, rho_bar = mean pairwise correlation of the M series.
     Cross-check: eigenvalue participation ratio (sum lambda)^2 / sum lambda^2.
  2. Deflated Sharpe ratio of the best variant (highest monthly Sharpe of x) with N_eff, and with
     N = 48 for reference (tools.lh_book.deflated_sharpe). Pass: DSR >= 0.95.
  3. Probability of backtest overfitting (Bailey, Borwein, Lopez de Prado & Zhu 2017) by CSCV:
     S = 8 contiguous blocks of the monthly series; every C(8,4) = 70 split; in-sample best by
     Sharpe; its relative rank w in the out-of-sample half; logit = ln(w / (1 - w));
     PBO = share of splits with logit <= 0. Pass (plan 0025): PBO <= 0.20.
     Also reported: how often the in-sample best loses to the index out of sample, and the
     in-sample-best's mean out-of-sample excess vs the grid median's.
Verdict per tier: luck-test PASS only if both DSR(N_eff) >= 0.95 and PBO <= 0.20.

Writes data/lh/luck.json.  Usage: python -m tools.lh_luck
"""

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.lh_book import deflated_sharpe  # noqa: E402

LH = PROJECT_ROOT / "data" / "lh"
S_BLOCKS = 8


def excess_matrix(bm, tier, kind="grid"):
    d = bm[(bm["tier"] == tier) & (bm["kind"] == kind)].sort_values(["variant", "i"])
    cols = {}
    for v, g in d.groupby("variant"):
        a, b = g["atlv"].to_numpy(float), g["bench"].to_numpy(float)
        cols[v] = (a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1)
    return pd.DataFrame(cols)


def sharpe(x):
    x = np.asarray(x, float)
    s = x.std(ddof=1)
    return x.mean() / s if s > 0 else 0.0


def n_effective(X):
    c = X.corr().to_numpy()
    m = c.shape[0]
    rho = (c.sum() - m) / (m * (m - 1))
    lam = np.clip(np.linalg.eigvalsh(c), 0, None)
    return float(rho + (1 - rho) * m), float(rho), float(lam.sum() ** 2 / (lam ** 2).sum())


def pbo(X, s=S_BLOCKS):
    T, n = X.shape
    edges = np.linspace(0, T, s + 1).round().astype(int)
    blocks = [np.arange(edges[k], edges[k + 1]) for k in range(s)]
    logits, oos_best, oos_med, best_loses = [], [], [], 0
    A = X.to_numpy()
    for ins in itertools.combinations(range(s), s // 2):
        i_idx = np.concatenate([blocks[k] for k in ins])
        o_idx = np.concatenate([blocks[k] for k in range(s) if k not in ins])
        sr_in = np.array([sharpe(A[i_idx, j]) for j in range(n)])
        sr_out = np.array([sharpe(A[o_idx, j]) for j in range(n)])
        b = int(np.argmax(sr_in))
        rank = (sr_out < sr_out[b]).sum() + 1          # 1 = worst … n = best
        w = rank / (n + 1)
        logits.append(math.log(w / (1 - w)))
        oos_best.append(A[o_idx, b].mean())
        oos_med.append(np.median(A[o_idx].mean(axis=0)))
        best_loses += A[o_idx, b].mean() < 0
    k = len(logits)
    return dict(splits=k, pbo=round(float(np.mean(np.array(logits) <= 0)), 3),
                median_logit=round(float(np.median(logits)), 3),
                is_best_loses_to_index_oos=round(best_loses / k, 3),
                is_best_oos_excess_pa=round(float(np.mean(oos_best)) * 12, 4),
                grid_median_oos_excess_pa=round(float(np.mean(oos_med)) * 12, 4))


def run():
    bm = pd.read_parquet(LH / "book_monthly.parquet")
    out = {"input": "data/lh/book_monthly.parquet (plan 0024 grid)", "blocks": S_BLOCKS, "tiers": {}}
    for tier in ("LARGE", "MID", "SMALL"):
        X = excess_matrix(bm, tier)
        srs = X.apply(sharpe)
        best = srs.idxmax()
        n_eff, rho, n_pr = n_effective(X)
        dsr_eff, sr, sr0_eff = deflated_sharpe(X[best], srs.values, max(n_eff, 2))
        dsr_48, _, sr0_48 = deflated_sharpe(X[best], srs.values, X.shape[1])
        p = pbo(X)
        out["tiers"][tier] = dict(
            variants=X.shape[1], months=X.shape[0], best=best,
            best_sr_monthly=round(sr, 4), best_sr_annual=round(sr * math.sqrt(12), 3),
            best_excess_pa=round(float(X[best].mean()) * 12, 4),
            mean_pairwise_corr=round(rho, 3), n_eff=round(n_eff, 2), n_eff_eigen=round(n_pr, 2),
            sr0_monthly_neff=round(sr0_eff, 4), dsr_neff=round(dsr_eff, 4),
            sr0_monthly_48=round(sr0_48, 4), dsr_48=round(dsr_48, 4),
            **p,
            luck_test_pass=bool(dsr_eff >= 0.95 and p["pbo"] <= 0.20))
        r = out["tiers"][tier]
        print(f"{tier}: best {best}  SR/yr {r['best_sr_annual']}  excess {r['best_excess_pa']:+.1%}/yr | "
              f"rho {rho:.2f} N_eff {n_eff:.1f} (eigen {n_pr:.1f}) | DSR(N_eff) {dsr_eff:.3f} "
              f"DSR(48) {dsr_48:.3f} | PBO {p['pbo']:.2f} (IS-best loses to index OOS "
              f"{p['is_best_loses_to_index_oos']:.0%}; OOS {p['is_best_oos_excess_pa']:+.1%} vs grid median "
              f"{p['grid_median_oos_excess_pa']:+.1%}) | PASS {r['luck_test_pass']}")
    (LH / "luck.json").write_text(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    run()
