"""Honest expected-1Y-return decomposition for the current advisory book.

Answers "what should this book actually return over the next year?" WITHOUT the
two lies the cockpit stat embeds: (1) analyst-PT upside is not a return forecast
(sell-side PTs run +12-25% optimistic, cockpit/api.py:1525); (2) a blended number
hides that a long-only book's return is mostly the MARKET. Decomposes into:

    E[1Y] = BETA (tier-weighted market assumption)
          + ALPHA (clean OOS-shrunk factor IC x dispersion x selection intensity)
          - COSTS (measured turnover drag at config.TRANSACTION_COSTS_BPS)
          - TAX (STCG/LTCG on the gross pre-cost return, plan 0012 B1; see TAX below)

Alpha uses the Grinold fundamental-law approximation per tier:
    alpha_20d = shrink x IC_composite x sigma_cs(20d) x zbar_selected
IC_composite = sum |w_i| * |IC_i| over the wired factors (clean `v2_recompute`
rows only, post-ADR-0047 re-baseline; all wired factors are correct-sign by
ADR 0049 rule 3, so |.| is safe). NO orthogonality boost is applied
(conservative). The in-sample IC is then shrunk by the walk-forward OOS factor:
the 2026-05-29 walk-forward validated SMALL and found LARGE/MID ~zero OOS skill.

Read-only over prod tables. Writes ONLY data/expected_return_predictions.jsonl
(append log, one JSON line per run) so future realized returns can score the
prediction — run `--score` in 2027-07 against portfolio_nav.

Usage:
    python -m tools.expected_return            # predict + log
    python -m tools.expected_return --no-log   # predict only
"""

import argparse
import json
import math
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from db import read_sql                                    # noqa: E402
from config import PICKABLE_TIERS, TRANSACTION_COSTS_BPS   # noqa: E402
from factors import SIGNAL_WEIGHTS                        # noqa: E402
from tools.factor_decay import WEIGHT_KEY_TO_SIGNAL        # noqa: E402

PRED_LOG = Path(__file__).resolve().parent.parent / "data" / "expected_return_predictions.jsonl"

# ── Assumptions (every number here is a LEVER — stated, not hidden) ─────────
# Forward 1Y nominal total-return assumptions per tier segment. Base = long-run
# Indian equity: ~6-7% real + ~4.5% CPI ~= 11% (Nifty TR CAGR 2002-2025 ~12-13%
# is a bull-tilted sample; forward E/P ~4.3% argues lower). MID/SMALL carry a
# small historical premium paid for materially higher vol and drawdown.
BETA_SCENARIOS = {          # tier -> {scenario: 1Y nominal return}
    "LARGE": {"bear": -0.15, "base": 0.11, "bull": 0.28},
    "MID":   {"bear": -0.20, "base": 0.12, "bull": 0.35},
    "SMALL": {"bear": -0.25, "base": 0.125, "bull": 0.45},
}
BOOK_BETA = 1.0             # 5 names/tier, roughly equal-weighted -> E[beta]~1 vs its segment

# Walk-forward OOS shrink on in-sample IC (2026-05-29 run: SMALL validated,
# LARGE/MID ~zero OOS). Survivorship bias in the backtest panel (audit Data-F1)
# argues for shrinking even the "validated" tier.
OOS_SHRINK = {"LARGE": 0.25, "MID": 0.25, "SMALL": 0.50}

ZBAR_CAP = 2.0              # E[z | selected] cap — rank-IC tails aren't linear; don't
                            # credit the normal-order-statistic fantasy at top-0.3% of SMALL

PERIODS_PER_YEAR = 252 / 20   # 20d IC horizon -> ~12.6 non-overlapping periods

# Measured cost reality (tools/rebalance_sim.py, 61 trading days to 2026-07-05,
# production banded builder, config.TRANSACTION_COSTS_BPS per side):
#   banded: 6.2%/day one-way turnover -> 24.5%/yr cost drag (net ann +2.0% vs gross +30.3%)
#   daily:  14.6%/day                 -> 53.1%/yr
MEASURED_BANDED_TURNOVER_1W = 0.062     # one-way, per day
MEASURED_BANDED_COST_DRAG = 0.245      # per year
# Prospective: same model rebalanced at its natural 20d signal horizon —
# ~2.5 of 15 names replaced per month + drift trades ~= 20%/month one-way.
MONTHLY_CADENCE_TURNOVER_1W_PER_YEAR = 0.20 * 12

# ── Tax (plan 0012 B1, statutory, no research) ──────────────────────────────
# Indian LT/ST capital-gains tax on equity. STT is already inside
# TRANSACTION_COSTS_BPS — do NOT double count it here. Implied avg holding
# period = 1 / one-way ANNUAL turnover (turns/book/yr); < 1yr -> STCG applies,
# else LTCG. This is a simplification (real tax is levied on realized gains
# per lot, not on E[return]) — precision here is false precision; the point is
# to stop presenting an untaxed number as if it were spendable.
TAX = {"stcg": 0.20, "ltcg": 0.125}   # ignores the Rs 1.25L LTCG exemption (advisory book, assumed consumed)


def _book_tier_weights():
    df = read_sql(
        "SELECT cap_tier, SUM(weight) w, COUNT(*) n FROM portfolio_weights "
        "WHERE asof_date = (SELECT MAX(asof_date) FROM portfolio_weights) "
        "GROUP BY cap_tier")
    asof = read_sql("SELECT MAX(asof_date) d FROM portfolio_weights").iloc[0]["d"]
    return asof, {r.cap_tier: {"w": float(r.w), "n": int(r.n)} for r in df.itertuples()}


def _clean_ic(signal, tier):
    """Mean IC of the (signal, tier) evidence row (v2 panel only)."""
    from tools.backtest_pit import evidence
    df = evidence()
    df = df[(df["signal"] == signal) & (df["cap_tier"] == tier) & df["source"].str.startswith("v2_recompute")]
    if df.empty:
        return None
    return {"ic": float(df.iloc[0]["mean_ic"]), "n": int(df.iloc[0]["n_periods"]),
            "t": float(df.iloc[0]["t_stat"])}


def _composite_ic(tier):
    """sum |w|*|IC| over wired factors — conservative (no orthogonality boost)."""
    total, detail = 0.0, {}
    for key, w in SIGNAL_WEIGHTS[tier].items():
        sig = WEIGHT_KEY_TO_SIGNAL.get(key, key)
        row = _clean_ic(sig, tier)
        if row is None:                      # no clean backtest row -> credit ZERO
            detail[key] = {"ic": None, "contrib": 0.0}
            continue
        contrib = abs(w) * abs(row["ic"])
        total += contrib
        detail[key] = {"ic": row["ic"], "t": row["t"], "n": row["n"],
                       "w": w, "contrib": round(contrib, 5)}
    return total, detail


def _cs_dispersion(tier):
    """Mean cross-sectional std of fwd_return_20d, 2025+ anchors (clean panel)."""
    df = read_sql(
        "SELECT SQRT(AVG(fwd_return_20d*fwd_return_20d) - AVG(fwd_return_20d)*AVG(fwd_return_20d)) sd "
        "FROM daily_snapshots_pit WHERE snapshot_date >= '2025-01-01' "
        "AND cap_tier = ? AND fwd_return_20d IS NOT NULL GROUP BY snapshot_date",
        params=[tier])
    return float(df["sd"].mean())


def _zbar_top_k_of_n(k, n):
    """E[z | top k of n] for standard normal, capped at ZBAR_CAP."""
    frac = k / n
    # mean of upper tail beyond quantile q: phi(z_q)/frac
    from statistics import NormalDist
    z_q = NormalDist().inv_cdf(1 - frac)
    zbar = math.exp(-z_q * z_q / 2) / math.sqrt(2 * math.pi) / frac
    return min(zbar, ZBAR_CAP)


def _universe_size(tier):
    return int(read_sql("SELECT COUNT(*) n FROM stocks WHERE cap_tier = ?",
                        params=[tier]).iloc[0]["n"])


def _weighted_cost_bps(tier_w):
    return sum(tier_w[t]["w"] * TRANSACTION_COSTS_BPS[t] for t in tier_w)


def _tax_drag(one_way_annual_turnover, gross_pretax_return):
    """DECIDED (plan 0012 B1): implied_hold = 1 / one-way annual turnover;
    < 1yr -> STCG on max(gross_pretax_return, 0), else LTCG. Returns
    (tax_drag, regime, implied_hold_years)."""
    implied_hold_years = float("inf") if one_way_annual_turnover <= 0 else 1.0 / one_way_annual_turnover
    regime = "stcg" if implied_hold_years < 1.0 else "ltcg"
    drag = TAX[regime] * max(gross_pretax_return, 0.0)
    return drag, regime, implied_hold_years


def run(log=True):
    asof, tier_w = _book_tier_weights()
    tiers = [t for t in PICKABLE_TIERS if t in tier_w]

    # ── ALPHA per tier ──
    alpha_ann, alpha_detail = {}, {}
    for t in tiers:
        ic, detail = _composite_ic(t)
        sigma = _cs_dispersion(t)
        zbar = _zbar_top_k_of_n(tier_w[t]["n"], _universe_size(t))
        a20 = OOS_SHRINK[t] * ic * sigma * zbar
        alpha_ann[t] = a20 * PERIODS_PER_YEAR
        alpha_detail[t] = {"ic_composite": round(ic, 4), "sigma_cs20d": round(sigma, 4),
                           "zbar": round(zbar, 2), "oos_shrink": OOS_SHRINK[t],
                           "alpha_ann": round(alpha_ann[t], 4), "factors": detail}
    book_alpha = sum(tier_w[t]["w"] * alpha_ann[t] for t in tiers)
    book_alpha_raw = sum(tier_w[t]["w"] * alpha_ann[t] / OOS_SHRINK[t] for t in tiers)

    # ── BETA per scenario ──
    beta = {s: BOOK_BETA * sum(tier_w[t]["w"] * BETA_SCENARIOS[t][s] for t in tiers)
            for s in ("bear", "base", "bull")}

    # ── COSTS ──
    bps = _weighted_cost_bps(tier_w)
    # cost/yr = one-way turnover/yr x 2 sides x per-side bps
    monthly_drag = MONTHLY_CADENCE_TURNOVER_1W_PER_YEAR * 2 * bps / 10000.0
    costs = {"as_operated_banded": MEASURED_BANDED_COST_DRAG,
             "monthly_cadence": round(monthly_drag, 4)}

    # ── TAX (plan 0012 B1) — levied on the GROSS pre-cost, pre-tax return (same
    # base both modes; STT/brokerage already counted in COSTS above, not here).
    # Rate depends on each mode's own implied holding period.
    gross_pretax_return = beta["base"] + book_alpha
    tax_as_operated, regime_as_operated, hold_as_operated = _tax_drag(
        MEASURED_BANDED_TURNOVER_1W * 252, gross_pretax_return)
    tax_monthly, regime_monthly, hold_monthly = _tax_drag(
        MONTHLY_CADENCE_TURNOVER_1W_PER_YEAR, gross_pretax_return)
    taxes = {"as_operated_banded": round(tax_as_operated, 4),
             "monthly_cadence": round(tax_monthly, 4)}

    # ── Headline: base beta + alpha − cost − tax, both operating modes ──
    e_as_operated = beta["base"] + book_alpha - costs["as_operated_banded"] - tax_as_operated
    e_monthly = beta["base"] + book_alpha - costs["monthly_cadence"] - tax_monthly
    # CI is SCENARIO-based (beta dominates), not statistical: bear/bull beta with
    # alpha at [0.5x, 1.5x], monthly-cadence costs, monthly-cadence tax.
    ci = (beta["bear"] + 0.5 * book_alpha - costs["monthly_cadence"] - tax_monthly,
          beta["bull"] + 1.5 * book_alpha - costs["monthly_cadence"] - tax_monthly)

    print(f"\n══ HONEST EXPECTED 1Y RETURN — book asof {asof} ══\n")
    print(f"  Book: {sum(tier_w[t]['n'] for t in tiers)} names, tier mix "
          + " / ".join(f"{t} {tier_w[t]['w']:.0%}" for t in tiers))
    print(f"\n  {'component':<34}{'%/yr':>8}")
    print(f"  {'BETA (base: LARGE 11 / MID 12 / SMALL 12.5)':<34}{beta['base']:>7.1%}")
    print(f"  {'ALPHA gross (clean IC, OOS-shrunk)':<34}{book_alpha:>7.1%}"
          f"   (unshrunk in-sample: {book_alpha_raw:.1%})")
    for t in tiers:
        d = alpha_detail[t]
        print(f"    {t:<7} IC={d['ic_composite']:.3f} x sigma={d['sigma_cs20d']:.3f} "
              f"x zbar={d['zbar']:.2f} x shrink={d['oos_shrink']:.2f} x {PERIODS_PER_YEAR:.1f} "
              f"= {d['alpha_ann']:+.1%}  (book contrib {tier_w[t]['w'] * alpha_ann[t]:+.2%})")
    print(f"  {'COST as operated (banded 6.2%/day 1-way)':<34}{-costs['as_operated_banded']:>7.1%}   [measured, rebalance_sim 61d]")
    print(f"  {'COST at monthly cadence (~20%/mo 1-way)':<34}{-costs['monthly_cadence']:>7.1%}   [{bps:.0f}bps/side book-weighted]")
    print(f"  {'TAX as operated (' + regime_as_operated.upper() + ' @ ' + f'{TAX[regime_as_operated]:.1%}' + ')':<34}{-tax_as_operated:>7.1%}   [implied hold ~{hold_as_operated*365:.0f}d, on gross {gross_pretax_return:+.1%}]")
    print(f"  {'TAX at monthly cadence (' + regime_monthly.upper() + ' @ ' + f'{TAX[regime_monthly]:.1%}' + ')':<34}{-tax_monthly:>7.1%}   [implied hold ~{hold_monthly*365:.0f}d, on gross {gross_pretax_return:+.1%}]")
    if regime_as_operated == regime_monthly:
        print(f"    (NOTE: both modes classify {regime_as_operated.upper()} today — the "
              f"~{hold_monthly:.2f}yr implied hold at the current monthly-cadence turnover "
              f"assumption ({MONTHLY_CADENCE_TURNOVER_1W_PER_YEAR:.1f}x/yr one-way) is still "
              f"short of the 1yr LTCG bar; simplification per plan 0012 B1 taxes E[return], "
              f"not realized per-lot gains — precision here is false precision.)")
    print(f"\n  E[1Y] AS OPERATED  = {beta['base']:+.1%} beta {book_alpha:+.1%} alpha "
          f"{-costs['as_operated_banded']:+.1%} cost {-tax_as_operated:+.1%} tax = {e_as_operated:+.1%}")
    print(f"  E[1Y] MONTHLY MODE = {beta['base']:+.1%} beta {book_alpha:+.1%} alpha "
          f"{-costs['monthly_cadence']:+.1%} cost {-tax_monthly:+.1%} tax = {e_monthly:+.1%}")
    print(f"  Scenario CI (bear..bull beta, monthly costs+tax): [{ci[0]:+.1%}, {ci[1]:+.1%}]")
    print(f"\n  Gap to 25%: {0.25 - e_monthly:+.1%} — of which market-must-rise "
          f"{max(0.25 - (beta['bull'] + book_alpha - costs['monthly_cadence'] - tax_monthly), 0):+.1%} "
          f"remains even in the BULL beta scenario.")

    pred = {"run_date": date.today().isoformat(), "book_asof": str(asof),
            "horizon_days": 365,
            "e1y_as_operated": round(e_as_operated, 4),
            "e1y_monthly_cadence": round(e_monthly, 4),
            "ci_lo": round(ci[0], 4), "ci_hi": round(ci[1], 4),
            "beta": {k: round(v, 4) for k, v in beta.items()},
            "alpha_book_ann": round(book_alpha, 4),
            "alpha_book_ann_unshrunk": round(book_alpha_raw, 4),
            "costs": costs, "cost_bps_per_side_weighted": round(bps, 1),
            "tax_drag": taxes,
            "tax_detail": {
                "as_operated": {"regime": regime_as_operated, "rate": TAX[regime_as_operated],
                                 "implied_hold_years": round(hold_as_operated, 4)},
                "monthly_cadence": {"regime": regime_monthly, "rate": TAX[regime_monthly],
                                     "implied_hold_years": round(hold_monthly, 4)},
                "gross_pretax_return": round(gross_pretax_return, 4),
            },
            "tier_weights": {t: round(tier_w[t]["w"], 4) for t in tiers},
            "alpha_detail": alpha_detail,
            "assumptions": {"beta_scenarios": BETA_SCENARIOS, "oos_shrink": OOS_SHRINK,
                            "zbar_cap": ZBAR_CAP, "book_beta": BOOK_BETA, "tax": TAX}}
    if log:
        PRED_LOG.parent.mkdir(exist_ok=True)
        with open(PRED_LOG, "a") as f:
            f.write(json.dumps(pred) + "\n")
        print(f"\n  prediction logged -> {PRED_LOG.name} (score vs realized in 2027-07)")
    return pred


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-log", action="store_true", help="predict without appending to the log")
    args = ap.parse_args()
    run(log=not args.no_log)
