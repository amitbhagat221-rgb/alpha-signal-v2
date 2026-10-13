"""
Plan 0024 H1 — which factors are slow?  (READ-ONLY on the DB.)

For every numeric factor column of daily_snapshots_pit × tier (LARGE / MID / SMALL):
monthly rank IC (Spearman within tier, per monthly anchor) against the forward returns
in data/lh/labels.parquet (tools.lh_labels: pit.forward_returns at 21 / 63 / 126 / 252
sessions), aggregated with the Newey-West standard error of tools.backtest_pit at a lag
equal to the horizon in months (1 / 3 / 6 / 12), for the whole sample and by anchor
period (2019-12…2022-12, 2023-01…2024-12, 2025-01…2026-10).

Classification (plan 0024, fixed before any result):
  slow  = n(126) ≥ 12 anchors, |t126| ≥ 2.5, |IC126| ≥ |IC21|, IC21 and IC126 the same sign
  fast  = |t21| ≥ 2.5 and |IC21| is the largest |IC| of the horizons measured (n ≥ 12 at 21, 63
          and 126 at least): peaks at 21 and decays
  robust (slow) = IC126 has the full-sample sign in each of the three periods
Multiple testing: every full-sample (factor, tier, horizon) test with n ≥ 12 anchors is one
hypothesis; two-sided p from |t| with df = n − 1 (as tools.multiple_testing); Bonferroni and
Benjamini-Yekutieli (tools.multiple_testing._bh_adjusted) at 5%.

Writes data/lh/horizon.json and data/lh/horizon_tests.csv.

Usage:  python -m tools.lh_horizon            # compute ICs + classify
        python -m tools.lh_horizon --reuse    # classify from data/lh/horizon_raw.csv
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import factors  # noqa: E402
from tools.backtest_pit import IC_MIN_PERIODS, _aggregate, _compute_ic  # noqa: E402
from tools.multiple_testing import _bh_adjusted  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
HORIZONS = (21, 63, 126, 252)
NW_LAG = {21: 1, 63: 3, 126: 6, 252: 12}       # lag = horizon in months
TIERS = ("LARGE", "MID", "SMALL")
PERIODS = {"2020-22": ("0000", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "9999")}
NON_FACTOR = {"sid", "snapshot_date", "cap_tier", "close_price", "reconstructed_at",
              "fwd_return_20d", "industry_id"}
SLOW_T, ALPHA = 2.5, 0.05


def factor_columns(conn):
    info = pd.read_sql("PRAGMA table_info(daily_snapshots_pit)", conn)
    return [r.name for r in info.itertuples() if r.type in ("REAL", "INTEGER") and r.name not in NON_FACTOR]


def registry():
    """pit column → {factor id, bench/status, live weight per tier} (display only)."""
    out = {}
    for fid, spec in factors.FACTORS.items():
        col = spec.get("pit_column_v2") or spec.get("pit_column_v1")
        if not col or col in out:
            continue
        wk = spec.get("weight_key", fid)
        w = {t: factors.SIGNAL_WEIGHTS.get(t, {}).get(wk) for t in TIERS}
        out[col] = {"factor": fid, "bench": spec.get("bench"), "status": spec.get("status"),
                    "live_weight": {t: v for t, v in w.items() if v}}
    return out


def load(conn, cols):
    lab = pd.read_parquet(LH / "labels.parquet",
                          columns=["sid", "snapshot_date", "cap_tier"] + [f"fwd_{h}" for h in HORIZONS])
    lab = lab[lab["cap_tier"].isin(TIERS)]
    anchors = sorted(lab["snapshot_date"].unique())
    ph = ",".join("?" * len(anchors))
    sel = ", ".join(["sid", "snapshot_date"] + cols)
    panel = pd.read_sql(f"SELECT {sel} FROM daily_snapshots_pit WHERE snapshot_date IN ({ph}) "
                        f"AND cap_tier IN ('LARGE','MID','SMALL')", conn, params=anchors)
    return lab.merge(panel, on=["sid", "snapshot_date"], how="inner")


def _agg(rows, col, tier, h):
    r = _aggregate(rows, col, tier, "lh", cadence="monthly", nw_lag=NW_LAG[h]) if rows else None
    if not r:
        return {"n": 0, "ic": None, "t": None}
    return {"n": r["n_periods"], "ic": r["mean_ic"], "t": r["t_stat"],
            "t_ci": [r["t_stat_ci_lo"], r["t_stat_ci_hi"]], "n_stocks": r["n_stocks_avg"]}


def compute_tests(cols):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    df = load(conn, cols)
    conn.close()
    print(f"{len(cols)} factor columns · {len(df):,} (sid, anchor) rows in LARGE/MID/SMALL · "
          f"{df['snapshot_date'].nunique()} anchors", flush=True)

    tests = []
    for i, col in enumerate(cols):
        for tier in TIERS:
            tdf = df[df["cap_tier"] == tier][["snapshot_date", col] + [f"fwd_{h}" for h in HORIZONS]]
            if tdf[col].notna().sum() == 0:
                continue
            for h in HORIZONS:
                rows = _compute_ic(tdf, col, f"fwd_{h}")
                rec = {"factor": col, "tier": tier, "h": h, **_agg(rows, col, tier, h)}
                for p, (lo, hi) in PERIODS.items():
                    sub = [r for r in rows if lo <= r[0] <= hi]
                    a = _agg(sub, col, tier, h)
                    rec[f"ic_{p}"], rec[f"t_{p}"], rec[f"n_{p}"] = a["ic"], a["t"], a["n"]
                tests.append(rec)
        print(f"  [{i + 1}/{len(cols)}] {col}", flush=True)
    return pd.DataFrame(tests)


def run(reuse=False):
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    cols = factor_columns(conn)
    conn.close()
    raw = LH / "horizon_raw.csv"
    if reuse and raw.exists():
        t = pd.read_csv(raw)
    else:
        t = compute_tests(cols)
        t.to_csv(raw, index=False)

    # ── multiple testing over every full-sample (factor, tier, horizon) test with n ≥ 12 ──
    mt = t[(t["n"] >= IC_MIN_PERIODS) & t["t"].notna()].copy()
    m = len(mt)
    mt["p"] = 2.0 * stats.t.sf(mt["t"].abs(), mt["n"] - 1)
    c_m = float(np.sum(1.0 / np.arange(1, m + 1)))
    mt["p_bonf"] = np.clip(mt["p"] * m, 0, 1)
    mt["p_by"] = _bh_adjusted(mt["p"].values, c=c_m)
    t = t.merge(mt[["factor", "tier", "h", "p", "p_bonf", "p_by"]], on=["factor", "tier", "h"], how="left")
    t.to_csv(LH / "horizon_tests.csv", index=False)
    t = t.astype(object).where(t.notna(), None)          # NaN → None for the classifier

    # ── classification per (factor, tier) ──
    reg = registry()
    summ = []
    for (col, tier), g in t.groupby(["factor", "tier"], sort=False):
        by = {int(r.h): r for r in g.itertuples()}
        if 21 not in by or 126 not in by:
            continue
        r21, r126 = by[21], by[126]
        ics = {h: by[h].ic for h in HORIZONS if h in by and by[h].ic is not None and by[h].n >= IC_MIN_PERIODS}
        ok126 = r126.n >= IC_MIN_PERIODS and r126.t is not None and r21.ic is not None
        same = ok126 and np.sign(r126.ic) == np.sign(r21.ic) and r126.ic != 0
        slow = bool(ok126 and abs(r126.t) >= SLOW_T and abs(r126.ic) >= abs(r21.ic) and same)
        sign126 = np.sign(r126.ic) if r126.ic else 0
        per_signs = {p: g.loc[g["h"] == 126, f"ic_{p}"].iloc[0] for p in PERIODS}
        robust = bool(slow and all(v is not None and not pd.isna(v) and np.sign(v) == sign126
                                   for v in per_signs.values()))
        fast = bool(r21.t is not None and r21.n >= IC_MIN_PERIODS and abs(r21.t) >= SLOW_T
                    and all(h in ics for h in (21, 63, 126))      # decay needs the longer horizons measured
                    and abs(r21.ic) >= max(abs(v) for v in ics.values()))
        flip = bool(ok126 and abs(r126.t) >= SLOW_T and not same)
        summ.append({
            "factor": col, "tier": tier,
            **{("factor_id" if k == "factor" else k): v for k, v in reg.get(col, {}).items()},
            "periods_missing_126": [p for p, v in per_signs.items() if v is None or pd.isna(v)],
            "periods_flipped_126": [p for p, v in per_signs.items()
                                    if v is not None and not pd.isna(v) and np.sign(v) != sign126],
            "ic": {h: (by[h].ic if h in by else None) for h in HORIZONS},
            "t": {h: (by[h].t if h in by else None) for h in HORIZONS},
            "n": {h: (int(by[h].n) if h in by else 0) for h in HORIZONS},
            "p_by": {h: (None if h not in by or pd.isna(by[h].p_by) else float(by[h].p_by)) for h in HORIZONS},
            "p_bonf": {h: (None if h not in by or pd.isna(by[h].p_bonf) else float(by[h].p_bonf)) for h in HORIZONS},
            "ic126_by_period": {p: (None if pd.isna(v) else float(v)) for p, v in per_signs.items()},
            "t126_by_period": {p: (None if pd.isna(x) else float(x)) for p, x in
                               ((p, g.loc[g["h"] == 126, f"t_{p}"].iloc[0]) for p in PERIODS)},
            "ic21_by_period": {p: (None if pd.isna(x) else float(x)) for p, x in
                               ((p, g.loc[g["h"] == 21, f"ic_{p}"].iloc[0]) for p in PERIODS)},
            "slow": slow, "slow_robust": robust,
            "slow_by": bool(slow and by[126].p_by is not None and by[126].p_by <= ALPHA),
            "slow_bonf": bool(slow and by[126].p_bonf is not None and by[126].p_bonf <= ALPHA),
            "fast": fast, "sign_flip_21_126": flip,
            "sign": int(sign126),
        })

    s = pd.DataFrame(summ)
    verdict = {}
    for tier in TIERS:
        st = s[s["tier"] == tier]
        strict = st[st["slow"] & st["slow_robust"] & st["slow_by"]]
        verdict[tier] = {"slow": int(st["slow"].sum()), "slow_robust": int((st["slow"] & st["slow_robust"]).sum()),
                         "slow_by": int(st["slow_by"].sum()), "slow_bonf": int(st["slow_bonf"].sum()),
                         "slow_robust_by": int(len(strict)), "fast": int(st["fast"].sum()),
                         "H1_pass": bool(len(strict) > 0)}
    mtsum = {"M": m, "c_m": round(c_m, 3),
             "survive_by": int((mt["p_by"] <= ALPHA).sum()), "survive_bonf": int((mt["p_bonf"] <= ALPHA).sum()),
             "naive_abs_t_ge_2_5": int((mt["t"].abs() >= 2.5).sum()),
             "by_h": {int(h): {"tests": int((mt["h"] == h).sum()),
                               "by": int(((mt["h"] == h) & (mt["p_by"] <= ALPHA)).sum()),
                               "bonf": int(((mt["h"] == h) & (mt["p_bonf"] <= ALPHA)).sum())} for h in HORIZONS},
             "bonf_t_bar_at_median_df": round(float(stats.t.ppf(1 - ALPHA / m / 2, int(mt["n"].median()) - 1)), 2)}
    out = {"plan": "0024 H1", "horizons": HORIZONS, "nw_lag": NW_LAG, "periods": PERIODS,
           "n_factor_columns": len(cols), "verdict": verdict, "multiple_testing": mtsum,
           "factors": summ}
    (LH / "horizon.json").write_text(json.dumps(out, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(json.dumps({"verdict": verdict, "multiple_testing": mtsum}, indent=1))
    for tier in TIERS:
        st = s[(s["tier"] == tier) & s["slow"]].copy()
        st["t126"] = st["t"].map(lambda d: d[126])
        print(f"\n{tier} slow:")
        for r in st.sort_values("t126", key=abs, ascending=False).itertuples():
            print(f"  {r.factor:28} sign {r.sign:+d} IC21 {r.ic[21]:+.4f} IC126 {r.ic[126]:+.4f} t126 {r.t[126]:+.2f} "
                  f"robust={r.slow_robust} BY={r.slow_by} bonf={r.slow_bonf}")
    return out


if __name__ == "__main__":
    run(reuse="--reuse" in sys.argv)
