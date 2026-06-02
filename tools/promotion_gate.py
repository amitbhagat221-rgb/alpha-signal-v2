"""
Alpha Signal v2 — Horizon-resolved, net-of-cost factor promotion gate.

ADR 0036 follow-up. The legacy promotion decision reads a SINGLE-horizon (20d)
t-stat and a human eyeballs it. ADR 0036's IC-decay diagnostic showed factors
have heterogeneous natural horizons — a slow value factor looks dead at 20d even
when it's real, a fast microstructure factor looks great at 20d but the edge is
eaten by turnover cost. This codifies the proposed replacement:

  Judge every factor at ITS OWN horizon, NET OF the turnover cost that horizon
  implies, and emit a PROMOTE / LIBRARY / REJECT verdict per (signal, cap_tier).

WHY NET-OF-COST IR DRIVES *BOTH* THE HORIZON AND THE VERDICT
ADR 0036 warns: do NOT classify off raw peak |IC| — raw IC mechanically grows
with horizon (longer returns accumulate more signal) and the long end is
survivorship-biased and thin. So we do not pick the horizon by raw |IC|. Instead
the natural horizon is the one that maximises the factor's *net-of-cost annualised
information ratio*. That single objective bakes turnover cost into the horizon
choice: a fast factor's high gross IC gets eaten by cost and the optimiser pushes
its horizon out only if a slower hold actually nets more. Survivorship inflation
at 252d is countered two ways — the √(252/h) annualisation penalises very long
holds, and we require sign-stability up to the chosen horizon + adequate
non-overlapping periods (a thin 252d artifact can't win).

COST MODEL (transparent, one assumption)
Grinold–Kahn: per-period gross active return ≈ IC_h · σ(fwd_h), where σ(fwd_h) is
the cross-sectional dispersion of h-day forward returns (grows ~√h). Per-rebalance
cost ≈ T · c_side(tier), where c_side = config.TRANSACTION_COSTS_BPS/1e4 (per side)
and T is one-way turnover per rebalance at the natural horizon (default 0.3 — a
z-scored factor reconstitutes ~25-35% of the book each rebalance; full
reconstitution T=1.0 implies absurd annualised turnover and rejects everything).
Expressed in IC units the cost is `T·c_side / σ(fwd_h)`, which
SHRINKS as the horizon grows (σ grows ~√h while c_side is fixed) — i.e. the model
charges fast factors more, exactly the turnover-awareness ADR 0036 asked for.

  net_ic_h   = max(0, |IC_h| − T·c_side(tier)/σ_fwd_h)   · sign(IC_h)
  net_icir_h = net_ic_h / std_ic_h
  net_t_h    = net_icir_h · √(n_periods_h)         (matches backtest_pit's t)
  net_IR_yr  = net_icir_h · √(252 / h)             (annualised, breadth = 252/h)

VERDICT (at the cost-resolved natural horizon h*)
  PROMOTE  net_t ≥ 2.0  AND sign-stable AND n_periods ≥ min AND not a 252d-thin artifact
  LIBRARY  1.5 ≤ net_t < 2.0  (validated, on the bench — FACTOR_LIBRARY tier)
  REJECT   net_t < 1.5  OR cost eats the whole edge (net_ic ≤ 0)

This writes the evidence table `factor_horizon_gate` and prints a roster. It does
NOT touch config.SIGNAL_WEIGHTS — promotion stays a human decision (CLAUDE.md:
"never mechanically"); this is the evidence surface that decision now reads.

Reuses ic_decay / backtest_pit IC machinery in a single pass (so σ_fwd_h is
computed alongside IC, no double recompute).

Usage:
    python -m tools.promotion_gate                 # all signals × tiers
    python -m tools.promotion_gate --signal roic
    python -m tools.promotion_gate --turnover 0.5  # softer cost assumption
    python -m tools.promotion_gate --reeval-live   # only re-score production-wired factors
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, upsert_df, get_db, get_backtest_cadence
from config import TRANSACTION_COSTS_BPS
from tools.backtest_pit import SIGNAL_COLUMN_MAP, _compute_ic, _aggregate
from tools.ic_decay import HORIZONS, _price_series, _fwd_panel, _horizon_lag

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS factor_horizon_gate (
    signal TEXT NOT NULL, cap_tier TEXT NOT NULL, source TEXT, cadence TEXT,
    natural_horizon INTEGER, gross_ic REAL, gross_t REAL, sigma_fwd REAL,
    cost_ic REAL, net_ic REAL, net_t REAL, net_ir_annual REAL, n_periods INTEGER,
    sign_stable INTEGER, turnover_assumed REAL, is_live INTEGER, verdict TEXT,
    ir_curve_json TEXT, computed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (signal, cap_tier)
);
"""


def _ensure_table():
    with get_db() as conn:
        conn.execute(_CREATE_SQL)

PROMOTE_T = 2.0
LIBRARY_T = 1.5
# One-way turnover per rebalance AT THE NATURAL HORIZON. A persistent quantile-
# ranked factor, rebalanced when its signal has meaningfully changed (~every h
# days), reconstitutes only a fraction of the book each time — empirically ~25-35%
# for a z-scored factor. (T=1.0 = full reconstitution every rebalance implies
# absurd annualised turnover, e.g. 1260% at h=20d, and rejects everything.) The
# relative verdicts are robust to T within [0.2, 0.5]; --turnover overrides.
DEFAULT_TURNOVER = 0.3
MIN_PERIODS = 5            # non-overlapping periods for a horizon to be eligible
THIN_252_PERIODS = 8       # below this at 252d → treat as survivorship-thin, can't be h*


def _winsor_std(x, p=0.01):
    """Cross-sectionally robust dispersion of forward returns."""
    x = pd.Series(x).dropna()
    if len(x) < 20:
        return np.nan
    lo, hi = x.quantile(p), x.quantile(1 - p)
    return float(x.clip(lo, hi).std())


def _sigma_fwd(tier_df, h):
    """σ(fwd_h) for a tier — pooled winsorised std of h-day forward returns."""
    col = f"fwd_{h}"
    if col not in tier_df.columns:
        return np.nan
    return _winsor_std(tier_df[col].to_numpy())


def _resolve_and_score(by_h, tier, c_side, turnover):
    """Given the per-horizon IC dicts (with sigma_fwd attached), pick the
    cost-resolved natural horizon and return its net metrics + the full curve."""
    cand = {}
    for h, r in by_h.items():
        if not r or r.get("mean_ic") is None or r.get("std_ic") in (None, 0):
            continue
        if r["n_periods"] < MIN_PERIODS:
            continue
        sig = r.get("sigma_fwd")
        if sig is None or not np.isfinite(sig) or sig <= 0:
            continue
        cost_ic = turnover * c_side / sig
        net_ic = max(0.0, abs(r["mean_ic"]) - cost_ic) * np.sign(r["mean_ic"])
        net_icir = net_ic / r["std_ic"] if r["std_ic"] else 0.0
        net_t = net_icir * np.sqrt(r["n_periods"])
        net_ir_yr = net_icir * np.sqrt(252.0 / h)
        # survivorship guard: a thin 252d horizon cannot be the natural horizon
        eligible_h = not (h >= 252 and r["n_periods"] < THIN_252_PERIODS)
        cand[h] = {
            "horizon": h, "gross_ic": r["mean_ic"], "std_ic": r["std_ic"],
            "n_periods": r["n_periods"], "sigma_fwd": sig, "cost_ic": cost_ic,
            "net_ic": net_ic, "net_icir": net_icir, "net_t": net_t,
            "net_ir_yr": net_ir_yr, "gross_t": r.get("t_stat"),
            "eligible_h": eligible_h,
        }
    if not cand:
        return None, cand
    # sign stability across the (eligible, sampled) horizons
    signs = {np.sign(c["gross_ic"]) for c in cand.values() if c["gross_ic"]}
    sign_stable = len(signs) <= 1
    # natural horizon = argmax net annualised IR among horizon-eligible candidates
    pool = {h: c for h, c in cand.items() if c["eligible_h"]} or cand
    h_star = max(pool, key=lambda h: pool[h]["net_ir_yr"])
    best = dict(cand[h_star])
    best["sign_stable"] = sign_stable
    return best, cand


def _verdict(best):
    if best is None:
        return "INSUFFICIENT"
    if best["net_ic"] <= 0:
        return "REJECT"          # cost eats the whole edge
    t = abs(best["net_t"])
    if t >= PROMOTE_T and best["sign_stable"]:
        return "PROMOTE"
    if t >= LIBRARY_T:
        return "LIBRARY"
    return "REJECT"


def run(only_signal=None, turnover=DEFAULT_TURNOVER, reeval_live=False):
    print("Loading PIT panels + price history…")
    v1_df = read_sql("SELECT * FROM daily_snapshots_pit_v1")
    v2_df = read_sql("SELECT * FROM daily_snapshots_pit")
    price_series = _price_series()
    print(f"  v1 {len(v1_df):,} / v2 {len(v2_df):,} rows · {len(price_series):,} sids")

    # attach multi-horizon forward returns once
    for name in ("v1", "v2"):
        df = v1_df if name == "v1" else v2_df
        if df.empty:
            continue
        fwd = _fwd_panel(df, price_series)
        df.drop(columns=[c for c in df.columns if c.startswith("fwd_") and c != "fwd_return_20d"],
                errors="ignore", inplace=True)
        merged = df.merge(fwd, on=["snapshot_date", "sid"], how="left")
        if name == "v1":
            v1_df = merged
        else:
            v2_df = merged

    v2_dates_all = pd.to_datetime(v2_df["snapshot_date"]).dt.date.unique() if not v2_df.empty else []
    weekly_dates = {d.isoformat() for d in v2_dates_all if pd.Timestamp(d).weekday() == 4}

    live = _live_keys()
    targets = [(s, c) for s, c in SIGNAL_COLUMN_MAP.items() if s != "_response"]
    if only_signal:
        targets = [(s, c) for s, c in targets if s == only_signal]
    if reeval_live:
        targets = [(s, c) for s, c in targets if s in live]

    rows = []
    for signal, (v1_col, v2_col) in targets:
        cadence = get_backtest_cadence(signal)
        sources = [("v2_recompute", v2_df, v2_col)]
        if cadence == "monthly":
            sources.insert(0, ("v1_archive", v1_df, v1_col))

        scored_any = False
        for src_name, src_df, signal_col in sources:
            if signal_col is None or signal_col not in src_df.columns:
                continue
            if src_df[signal_col].notna().sum() == 0:
                continue
            if cadence == "weekly" and src_name == "v2_recompute":
                df_use = src_df[src_df["snapshot_date"].isin(weekly_dates)]
            elif cadence == "monthly" and src_name == "v2_recompute" and weekly_dates:
                df_use = src_df[~src_df["snapshot_date"].isin(weekly_dates)]
            else:
                df_use = src_df
            if df_use.empty:
                continue

            for tier in ["LARGE", "MID", "SMALL"]:
                tier_df = df_use[df_use["cap_tier"] == tier]
                if tier_df.empty:
                    continue
                c_side = TRANSACTION_COSTS_BPS.get(tier, 50) / 1e4
                by_h = {}
                for h in HORIZONS:
                    fwd_col = f"fwd_{h}"
                    if fwd_col not in tier_df.columns or tier_df[fwd_col].notna().sum() == 0:
                        by_h[h] = None
                        continue
                    ic_rows = _compute_ic(tier_df, signal_col, fwd_col)
                    res = _aggregate(ic_rows, signal, tier, src_name,
                                     cadence=cadence, nw_lag=_horizon_lag(signal, cadence, h))
                    if res:
                        res["sigma_fwd"] = _sigma_fwd(tier_df, h)
                    by_h[h] = res
                best, curve = _resolve_and_score(by_h, tier, c_side, turnover)
                if best is None and not any(by_h.values()):
                    continue
                verdict = _verdict(best)
                rows.append({
                    "signal": signal, "cap_tier": tier, "source": src_name,
                    "cadence": cadence,
                    "natural_horizon": int(best["horizon"]) if best else None,
                    "gross_ic": round(best["gross_ic"], 4) if best else None,
                    "gross_t": round(best["gross_t"], 2) if best and best["gross_t"] is not None else None,
                    "sigma_fwd": round(best["sigma_fwd"], 4) if best else None,
                    "cost_ic": round(best["cost_ic"], 4) if best else None,
                    "net_ic": round(best["net_ic"], 4) if best else None,
                    "net_t": round(best["net_t"], 2) if best else None,
                    "net_ir_annual": round(best["net_ir_yr"], 3) if best else None,
                    "n_periods": int(best["n_periods"]) if best else None,
                    "sign_stable": int(best["sign_stable"]) if best else None,
                    "turnover_assumed": turnover,
                    "is_live": int(signal in live),
                    "verdict": verdict,
                    "ir_curve_json": json.dumps(
                        {h: round(c["net_ir_yr"], 3) for h, c in curve.items()}) if curve else "{}",
                })
                scored_any = True
            if scored_any:
                break   # one source per signal is enough

    return rows, live


def _live_keys():
    try:
        import config
        keys = set()
        w = getattr(config, "SIGNAL_WEIGHTS", {})
        for tier_w in w.values():
            if isinstance(tier_w, dict):
                keys.update(tier_w.keys())
        return keys
    except Exception:
        return set()


# screener-name → backtest signal-id (the production weights use short names;
# the gate keys on registry ids). Mirrors the alias map in health_score.py.
_LIVE_ALIAS = {
    "consensus": "consensus_signal_combined", "accruals": "cf_accruals_ratio",
    "piotroski": "piotroski_f_score", "momentum": "mom_12m_adj",
    "promoter": "promoter_qoq", "smart_money": "avg_delivery_pct_30d",
}


def _fmt(rows, live):
    order = {"PROMOTE": 0, "LIBRARY": 1, "REJECT": 2, "INSUFFICIENT": 3}
    rows = sorted(rows, key=lambda r: (order.get(r["verdict"], 9), -(r["net_t"] or -99)))
    out = ["", "HORIZON-RESOLVED, NET-OF-COST PROMOTION GATE",
           "net_t at the cost-resolved natural horizon h*.  ★ = production-wired.",
           f"{'signal':28} {'tier':5} {'h*':>5} {'grossIC':>8} {'grossT':>7} "
           f"{'costIC':>7} {'netIC':>7} {'netT':>6} {'IRyr':>6} {'n':>3}  verdict"]
    for r in rows:
        star = "★" if r["is_live"] else " "
        out.append(
            f"{star}{r['signal'][:27]:27} {r['cap_tier']:5} "
            f"{(str(r['natural_horizon'])+'d') if r['natural_horizon'] else '—':>5} "
            f"{_n(r['gross_ic']):>8} {_n(r['gross_t']):>7} {_n(r['cost_ic']):>7} "
            f"{_n(r['net_ic']):>7} {_n(r['net_t']):>6} {_n(r['net_ir_annual']):>6} "
            f"{r['n_periods'] or 0:>3}  {r['verdict']}")
    return "\n".join(out)


def _n(v):
    return "—" if v is None else f"{v:+.3f}" if abs(v) < 100 else f"{v:.1f}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--signal", help="single signal (default: all)")
    ap.add_argument("--turnover", type=float, default=DEFAULT_TURNOVER,
                    help="one-way turnover per rebalance (default 1.0 = full book; lower = softer cost)")
    ap.add_argument("--reeval-live", action="store_true",
                    help="only re-score the production-wired factors (the ADR 're-evaluate weights' step)")
    ap.add_argument("--dry-run", action="store_true", help="don't write the table")
    args = ap.parse_args()

    rows, live = run(only_signal=args.signal, turnover=args.turnover, reeval_live=args.reeval_live)
    if not rows:
        print("No factors scored.")
        return

    print(_fmt(rows, live))

    n_prom = sum(1 for r in rows if r["verdict"] == "PROMOTE")
    n_lib = sum(1 for r in rows if r["verdict"] == "LIBRARY")
    n_rej = sum(1 for r in rows if r["verdict"] == "REJECT")
    print(f"\n{len(rows)} (signal,tier) scored · PROMOTE {n_prom} · LIBRARY {n_lib} · REJECT {n_rej} "
          f"· turnover={args.turnover}")

    # Re-evaluation of live factors at their natural horizon (the ADR ask)
    live_rows = [r for r in rows if r["is_live"]]
    if live_rows:
        survive = [r for r in live_rows if r["verdict"] == "PROMOTE"]
        fail = [r for r in live_rows if r["verdict"] != "PROMOTE"]
        print(f"\nLIVE re-eval: {len(survive)}/{len(live_rows)} production (signal,tier) clear "
              f"the net-of-cost bar at their natural horizon.")
        for r in fail:
            print(f"  ⚠ {r['signal']}/{r['cap_tier']} → {r['verdict']} "
                  f"(net_t={_n(r['net_t'])} @ {r['natural_horizon']}d)")

    if not args.dry_run:
        _ensure_table()
        from datetime import datetime, timezone
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in rows:
            r["computed_at"] = stamp
        upsert_df(pd.DataFrame(rows), "factor_horizon_gate")
        out_txt = PROJECT_ROOT / "output" / "promotion_gate.txt"
        out_txt.parent.mkdir(parents=True, exist_ok=True)
        out_txt.write_text(_fmt(rows, live) + "\n")
        print(f"\n→ wrote factor_horizon_gate ({len(rows)} rows) + {out_txt.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
