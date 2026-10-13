"""
Plan 0024 H2 — does a slow composite work on months it has not seen?  (READ-ONLY on the DB.)

Modelled on tools/walk_forward.py, but the factors are chosen and weighted on the
126-session label (data/lh/labels.parquet, pit.forward_returns) instead of 20 sessions.

  for each monthly anchor k (tools.backtest_pit._is_month_start_anchor):
    train  = the monthly anchors j whose 126-session label had fully matured by anchor k:
             exit close (entry_j + 126 sessions) on or before anchor k's close, i.e.
             sessions(entry_j -> entry_k) >= 127, and k - j >= 6 anchors. Expanding window.
             The session count comes from h_next_anchor in labels.parquet (same calendar
             and same function as the label).
    start  = the first anchor with >= 24 matured training anchors. Every method is
             scored on the same OOS anchors.
    choose = from the training window only, per tier:
      slow_select  factors with >= 12 training anchors and |NW t (lag 6) of training IC126|
                   >= 2.5, the 8 strongest, equal weight, training sign
      slow_icw     every factor with >= 24 training anchors, weight = training mean IC126
      blend        mean of the slow_select and fast_select composites (each its own
                   0-1 score); if one set is empty that month, the other alone
      fast_select  tools.walk_forward's `select` (20-session panel label fwd_return_20d,
                   embargo 1 anchor, >= 12 anchors, |t| >= 2.5, 6 strongest)
      live         today's factors.SIGNAL_WEIGHTS, fixed. NOT out of sample: chosen on
                   this same history. A control only.
    score  = tools.walk_forward.composite: within-tier percentile over every tier member
             at the anchor, negative weight inverts, missing factor = 0.5
             (config.MISSING_FACTOR_SCORE)
    record = rank IC vs fwd_21/63/126/252; top decile and top 15 (picked by score over
             all tier members, averaged over those with a label) minus the tier average
             at 63/126/252; the share of the top 20 still in the top 60 a month later.

Candidate factors = tools.walk_forward._columns() (every IC-rankable registry factor) that
the panel carries, plus the live columns.

Writes (never the DB):
  data/lh/oos_scores.parquet      sid, snapshot_date, cap_tier, method, score, pct_rank, oos
  data/lh/slow_model_records.csv  one row per (tier, method, anchor)
  data/lh/slow_model_choices.csv  the factor set + weights each method chose per (tier, anchor)
  data/lh/slow_model.json         summary tables + verdict

Usage:  python -m tools.lh_slow_model           # walk forward + summary (~10 min)
        python -m tools.lh_slow_model --reuse   # re-summarise the saved records
"""

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import factors  # noqa: E402
from tools.backtest_pit import IC_MIN_PERIODS, _compute_ic, _newey_west_se  # noqa: E402
from tools.walk_forward import _choose, _columns, _ranked_col, composite  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
TIERS = ("LARGE", "MID", "SMALL")
HORIZONS = (21, 63, 126, 252)
NW_LAG = {21: 1, 63: 3, 126: 6, 252: 12}
TRAIN_H = 126
LABEL_SESSIONS = 126
EMBARGO_MIN = 6           # anchors
MIN_TRAIN = 24            # matured training anchors before the first OOS month
SLOW_T, SLOW_MAX, SLOW_MIN_N = 2.5, 8, IC_MIN_PERIODS
ICW_MIN_N = 24
FAST = "fwd_return_20d"
METHODS = ("slow_select", "slow_icw", "blend", "fast_select", "live")
TOP_N, STAB_TOP, STAB_WIDE = 15, 20, 60
MIN_STOCKS = 20
PERIODS = {"2022": ("0000", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "9999")}


def log(*a):
    print(*a, flush=True)


def load():
    col_of = _columns()
    live_w = {t: {_ranked_col(k, t): w for k, w in ws.items()} for t, ws in factors.SIGNAL_WEIGHTS.items()}
    want = sorted(set(col_of) | {c for ws in live_w.values() for c in ws})
    lab = pd.read_parquet(LH / "labels.parquet",
                          columns=["sid", "snapshot_date", "cap_tier", "h_next_anchor"]
                          + [f"fwd_{h}" for h in HORIZONS])
    anchors = sorted(lab["snapshot_date"].unique())
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    have = {r[1] for r in conn.execute("PRAGMA table_info(daily_snapshots_pit)")}
    cols = [c for c in want if c in have]
    ph = ",".join("?" * len(anchors))
    sel = ", ".join(f'"{c}"' for c in ["sid", "snapshot_date", "cap_tier", FAST, *cols])
    panel = pd.read_sql(f"SELECT {sel} FROM daily_snapshots_pit WHERE snapshot_date IN ({ph}) "
                        f"AND cap_tier IN ('LARGE','MID','SMALL')", conn, params=anchors)
    conn.close()
    for c in cols + [FAST]:
        panel[c] = pd.to_numeric(panel[c], errors="coerce").astype("float32")
    df = panel.merge(lab.drop(columns=["cap_tier", "h_next_anchor"]), on=["sid", "snapshot_date"], how="left")
    # session index of each anchor's entry (first session after the anchor)
    h = lab.drop_duplicates("snapshot_date").set_index("snapshot_date")["h_next_anchor"].reindex(anchors)
    entry = np.concatenate([[0], np.cumsum(h.to_numpy()[:-1])])
    log(f"panel {len(df):,} rows · {len(anchors)} anchors {anchors[0]} → {anchors[-1]} · "
        f"{len(cols)} candidate columns ({len(set(want) - set(cols))} not in the panel: "
        f"{sorted(set(want) - set(cols))})")
    return df, cols, anchors, entry.astype(int), live_w


def ic_table(tdf, cols, resp):
    out = {}
    for c in cols:
        rows = _compute_ic(tdf, c, resp)
        if rows:
            out[c] = pd.Series({d: ic for d, ic, _ in rows}).sort_index()
    return out


def nw_t(x, lag):
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < 3:
        return np.nan
    se = _newey_west_se(x, lag)
    return float(x.mean() / se) if se and se > 0 else np.nan


def choose_slow(ic126, train):
    stats = {}
    for c, s in ic126.items():
        x = s[s.index.isin(train)].to_numpy()
        if len(x) >= SLOW_MIN_N and x.std(ddof=1) > 0:
            stats[c] = (float(x.mean()), nw_t(x, NW_LAG[TRAIN_H]), len(x))
    strong = sorted((c for c, (_, t, _) in stats.items() if abs(t) >= SLOW_T),
                    key=lambda c: -abs(stats[c][1]))[:SLOW_MAX]
    select = {c: float(np.sign(stats[c][0])) for c in strong}
    icw = {c: m for c, (m, _, n) in stats.items() if n >= ICW_MIN_N and m != 0}
    return select, icw, {c: stats[c] for c in strong}


def scores_at(g, weights):
    return composite(g, weights) if weights else None


def evaluate(g, s):
    """IC + top-group excess for one (tier, anchor, method) score Series aligned with g."""
    rec = {}
    order = s.sort_values(ascending=False, kind="mergesort").index
    top15 = order[:TOP_N]
    top10 = s.index[s >= s.quantile(0.9)]
    for h in HORIZONS:
        r = g[f"fwd_{h}"]
        sub = pd.DataFrame({"s": s, "r": r}).dropna()
        if len(sub) >= MIN_STOCKS and sub["s"].nunique() > 1:
            rec[f"ic{h}"] = float(sub["s"].rank().corr(sub["r"].rank()))
            tier_avg = sub["r"].mean()
            if h in (63, 126, 252):
                rec[f"top10_{h}"] = float(r.loc[top10].mean() - tier_avg)
                rec[f"top15_{h}"] = float(r.loc[top15].mean() - tier_avg)
                rec[f"cov15_{h}"] = float(r.loc[top15].notna().mean())
    return rec


def run():
    df, cols, anchors, entry, live_w = load()
    pos = {a: i for i, a in enumerate(anchors)}
    recs, choices, score_frames = [], [], []
    for tier in TIERS:
        tdf = df[df["cap_tier"] == tier]
        log(f"[{tier}] IC tables on {len(cols)} columns …")
        ic126 = ic_table(tdf[["snapshot_date", *cols, "fwd_126"]], cols, "fwd_126")
        ic20 = ic_table(tdf[["snapshot_date", *cols, FAST]], cols, FAST)
        by_date = dict(tuple(tdf.groupby("snapshot_date")))
        prev = {}
        for k, a in enumerate(anchors):
            if a not in by_date:
                continue
            train = [anchors[j] for j in range(k) if k - j >= EMBARGO_MIN and entry[k] - entry[j] >= LABEL_SESSIONS + 1]
            if len(train) < MIN_TRAIN:
                continue
            g = by_date[a].set_index("sid")
            sel, icw, sel_stats = choose_slow(ic126, set(train))
            fast_methods, _ = _choose(ic20, set(anchors[:k - 1]))
            fast = fast_methods["select"]
            live = {c: w for c, w in live_w.get(tier, {}).items() if c in g.columns}
            sc = {"slow_select": scores_at(g, sel), "slow_icw": scores_at(g, icw),
                  "fast_select": scores_at(g, fast), "live": scores_at(g, live)}
            parts = [x for x in (sc["slow_select"], sc["fast_select"]) if x is not None]
            sc["blend"] = sum(parts) / len(parts) if parts else None
            sets = {"slow_select": sel, "slow_icw": icw, "fast_select": fast, "live": live,
                    "blend": {**{f"S:{c}": w for c, w in sel.items()}, **{f"F:{c}": w for c, w in fast.items()}}}
            for m in METHODS:
                s = sc[m]
                w = sets[m]
                key = frozenset((c, np.sign(v)) for c, v in w.items())
                choices.append({"tier": tier, "anchor": a, "method": m, "n_train": len(train),
                                "last_train": train[-1], "n_factors": len(w),
                                "weights": json.dumps({c: round(float(v), 4) for c, v in
                                                       sorted(w.items(), key=lambda kv: -abs(kv[1]))}),
                                "slow_t": json.dumps({c: round(st[1], 2) for c, st in sel_stats.items()})
                                if m == "slow_select" else ""})
                if s is None:
                    continue
                r = {"tier": tier, "anchor": a, "method": m, "n_factors": len(w), **evaluate(g, s)}
                if m in prev:
                    pk, ps = prev[m]
                    r["set_changed"] = float(key != pk)
                    union = len(key | pk)
                    r["set_jaccard"] = len(key & pk) / union if union else 1.0
                    top_prev = ps.sort_values(ascending=False, kind="mergesort").index[:STAB_TOP]
                    wide = set(s.sort_values(ascending=False, kind="mergesort").index[:STAB_WIDE])
                    still = [x for x in top_prev if x in s.index]
                    r["top20_left_tier"] = 1 - len(still) / len(top_prev)
                    r["top20_in_top60"] = (sum(x in wide for x in still) / len(still)) if still else np.nan
                prev[m] = (key, s)
                recs.append(r)
                score_frames.append(pd.DataFrame({
                    "sid": s.index, "snapshot_date": a, "cap_tier": tier, "method": m,
                    "score": s.to_numpy(dtype=float), "pct_rank": s.rank(pct=True).to_numpy(dtype=float),
                    "oos": m != "live"}))
            if k % 6 == 0:
                log(f"  {tier} {a}: train {len(train)} ({train[0]}…{train[-1]}) slow_select {list(sel)} "
                    f"| fast {list(fast)}")
        log(f"[{tier}] done")
    rec = pd.DataFrame(recs)
    cho = pd.DataFrame(choices)
    sco = pd.concat(score_frames, ignore_index=True)
    return rec, cho, sco


def nonoverlap_t(g, col, months):
    """Plain t on every `months`-th anchor (labels that do not overlap), one per starting offset.
    Returns (median t over offsets, min t, median n). A check on the NW t, which is generous
    when the lag is long relative to the number of months."""
    x = g.sort_values("anchor")[col].to_numpy(dtype=float)
    ts, ns = [], []
    for off in range(months):
        y = x[off::months]
        y = y[~np.isnan(y)]
        if len(y) >= 3 and y.std(ddof=1) > 0:
            ts.append(y.mean() / (y.std(ddof=1) / np.sqrt(len(y))))
            ns.append(len(y))
    if not ts:
        return np.nan, np.nan, 0
    return round(float(np.median(ts)), 2), round(float(np.min(ts)), 2), int(np.median(ns))


def summarise(rec):
    rows = []
    for (tier, m), g in rec.groupby(["tier", "method"], sort=False):
        g = g.sort_values("anchor")
        row = {"tier": tier, "method": m, "oos_from": g["anchor"].min(), "oos_to": g["anchor"].max(),
               "months": len(g), "avg_factors": round(g["n_factors"].mean(), 1)}
        for h in HORIZONS:
            x = g[f"ic{h}"].dropna() if f"ic{h}" in g else pd.Series(dtype=float)
            row[f"n{h}"] = len(x)
            row[f"ic{h}"] = round(float(x.mean()), 4) if len(x) else np.nan
            row[f"t{h}"] = round(nw_t(x, NW_LAG[h]), 2) if len(x) > 2 else np.nan
            if h in (126, 252) and f"ic{h}" in g:
                med, mn, nn = nonoverlap_t(g, f"ic{h}", NW_LAG[h])
                row[f"t{h}_nonoverlap_median"], row[f"t{h}_nonoverlap_min"], row[f"n{h}_nonoverlap"] = med, mn, nn
        for h in (63, 126, 252):
            for q in ("top10", "top15"):
                x = g[f"{q}_{h}"].dropna() if f"{q}_{h}" in g else pd.Series(dtype=float)
                row[f"{q}_{h}_pct"] = round(float(x.mean()) * 100, 2) if len(x) else np.nan
                row[f"{q}_{h}_t"] = round(nw_t(x, NW_LAG[h]), 2) if len(x) > 2 else np.nan
        row["set_change_rate"] = round(float(g["set_changed"].mean()), 3) if "set_changed" in g else np.nan
        row["set_jaccard"] = round(float(g["set_jaccard"].mean()), 3) if "set_jaccard" in g else np.nan
        row["top20_in_top60"] = round(float(g["top20_in_top60"].mean()), 3) if "top20_in_top60" in g else np.nan
        row["top20_left_tier"] = round(float(g["top20_left_tier"].mean()), 3) if "top20_left_tier" in g else np.nan
        for p, (lo, hi) in PERIODS.items():
            x = g[(g["anchor"] >= lo) & (g["anchor"] <= hi)]["ic126"].dropna()
            row[f"ic126_{p}"] = round(float(x.mean()), 4) if len(x) else np.nan
            row[f"t126_{p}"] = round(nw_t(x, NW_LAG[126]), 2) if len(x) > 2 else np.nan
            row[f"n126_{p}"] = len(x)
        rows.append(row)
    return pd.DataFrame(rows)


def chosen_frequency(cho):
    out = {}
    for (tier, m), g in cho[cho["method"].isin(["slow_select", "fast_select"])].groupby(["tier", "method"]):
        cnt = {}
        for w in g["weights"]:
            for c, v in json.loads(w).items():
                cnt[(c, int(np.sign(v)))] = cnt.get((c, int(np.sign(v))), 0) + 1
        n = len(g)
        out[f"{tier}|{m}"] = {"months": n, "share_chosen": {f"{c} ({'+' if s > 0 else '-'})": round(v / n, 3)
                                                             for (c, s), v in sorted(cnt.items(), key=lambda kv: -kv[1])},
                              "latest": json.loads(g.sort_values("anchor")["weights"].iloc[-1])}
    return out


def verdict(summ):
    out = {}
    for tier in TIERS:
        s = summ[summ["tier"] == tier].set_index("method")
        t = {m: (None if m not in s.index or pd.isna(s.loc[m, "t126"]) else float(s.loc[m, "t126"])) for m in METHODS}
        slow_pass = [m for m in ("slow_select", "slow_icw") if t[m] is not None and t[m] >= 2.0]
        out[tier] = {"t126": t, "slow_methods_passing": slow_pass,
                     "H2_pass_either": bool(slow_pass), "H2_pass_both": len(slow_pass) == 2}
    return out


def main():
    if "--reuse" in sys.argv:          # re-summarise the saved records, no recompute
        rec = pd.read_csv(LH / "slow_model_records.csv")
        cho = pd.read_csv(LH / "slow_model_choices.csv")
        sco = pd.read_parquet(LH / "oos_scores.parquet", columns=["method"])
    else:
        rec, cho, sco = run()
        LH.mkdir(parents=True, exist_ok=True)
        rec.to_csv(LH / "slow_model_records.csv", index=False)
        cho.to_csv(LH / "slow_model_choices.csv", index=False)
        sco.to_parquet(LH / "oos_scores.parquet", index=False)
    summ = summarise(rec)
    summ.to_csv(LH / "slow_model_summary.csv", index=False)
    v = verdict(summ)
    out = {"plan": "0024 H2", "label_train": f"fwd_{TRAIN_H}", "embargo_min_anchors": EMBARGO_MIN,
           "label_sessions_matured": LABEL_SESSIONS + 1, "min_train_anchors": MIN_TRAIN,
           "slow_select": {"t": SLOW_T, "max": SLOW_MAX, "min_n": SLOW_MIN_N, "nw_lag": NW_LAG[TRAIN_H]},
           "slow_icw_min_n": ICW_MIN_N, "verdict": v,
           "summary": json.loads(summ.to_json(orient="records")),
           "chosen": chosen_frequency(cho),
           "oos_scores_rows": int(len(sco))}
    (LH / "slow_model.json").write_text(json.dumps(out, indent=1))
    pd.set_option("display.width", 250)
    log(summ[["tier", "method", "months", "avg_factors", "ic63", "t63", "ic126", "t126", "n126", "ic252", "t252",
              "top10_126_pct", "top15_126_pct", "top15_252_pct", "set_change_rate", "top20_in_top60"]].to_string(index=False))
    log(json.dumps(v, indent=1))
    log(f"wrote oos_scores.parquet ({len(sco):,} rows)")


if __name__ == "__main__":
    main()
