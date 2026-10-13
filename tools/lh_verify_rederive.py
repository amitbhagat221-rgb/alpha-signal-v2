"""Plan 0024 — independent re-derivation of the H1 / H2 / H3 headline numbers.

Written without reading or importing tools/lh_*.py logic (the cost model of tools/lh_costs
is used only in step 3, as the task allows). Read-only on the DB.

  python -m tools.lh_verify_rederive build    # panel + labels + entry prices -> data/lh/rederive_*.parquet
  python -m tools.lh_verify_rederive h1       # IC126 / t of the claimed strongest slow factors
  python -m tools.lh_verify_rederive h2       # own walk-forward slow_select, OOS IC126 t
  python -m tools.lh_verify_rederive h3       # own simple book simulator on the best variants
"""
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

import pit
from db import read_sql
from tools.backtest_pit import _is_month_start_anchor
from tools.walk_forward import _columns

OUT = Path("data/lh")
PANEL = OUT / "rederive_panel.parquet"
LABELS = OUT / "rederive_labels.parquet"
PRICES = OUT / "rederive_entry_prices.parquet"
ANCH = OUT / "rederive_anchors.parquet"
RES = OUT / "rederive_results.json"
HORIZONS = (21, 126)
TIERS = ("LARGE", "MID", "SMALL")


# ───────────────────────── helpers (own) ─────────────────────────

def nw_t(x, lag):
    """Mean / Newey-West (Bartlett) standard error."""
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return np.nan
    c = x - x.mean()
    v = c @ c / n
    for l in range(1, min(lag, n - 1) + 1):
        v += 2 * (1 - l / (lag + 1)) * (c[l:] @ c[:-l]) / n
    if v <= 0:
        v = c @ c / (n - 1)
    return x.mean() / np.sqrt(v / n)


def spearman(a, b):
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 20:
        return np.nan
    ra = pd.Series(a[m]).rank().to_numpy()
    rb = pd.Series(b[m]).rank().to_numpy()
    return np.corrcoef(ra, rb)[0, 1]


def save(key, obj):
    d = json.loads(RES.read_text()) if RES.exists() else {}
    d[key] = obj
    RES.write_text(json.dumps(d, indent=1, default=float))


# ───────────────────────── build ─────────────────────────

def build():
    cols = sorted(_columns())
    have = set(read_sql("SELECT * FROM daily_snapshots_pit LIMIT 1").columns)
    cols = [c for c in cols if c in have]
    dates = read_sql("SELECT DISTINCT snapshot_date FROM daily_snapshots_pit ORDER BY 1")["snapshot_date"]
    anchors = [d for d in dates if _is_month_start_anchor(date.fromisoformat(d))]
    print(f"{len(anchors)} monthly anchors {anchors[0]} .. {anchors[-1]}; {len(cols)} candidate columns", flush=True)
    sel = ", ".join(f'"{c}"' for c in ["sid", "snapshot_date", "cap_tier", "forensic_penalty", *cols])
    ph = ",".join("?" * len(anchors))
    panel = read_sql(f"SELECT {sel} FROM daily_snapshots_pit WHERE snapshot_date IN ({ph})", anchors)
    for c in cols + ["forensic_penalty"]:
        panel[c] = pd.to_numeric(panel[c], errors="coerce").astype("float32")
    panel.to_parquet(PANEL)
    print("panel", panel.shape, flush=True)

    raw = pit.load_raw({"prices", "adjustments"})
    prices, adj = raw["prices"], raw["adjustments"]
    cal = np.sort(prices["date"].unique())
    rows, arows = [], []
    for a in anchors:
        fr = pit.forward_returns(date.fromisoformat(a), prices, adj, HORIZONS)
        fr["snapshot_date"] = a
        rows.append(fr)
        m = int(np.searchsorted(cal, a, side="right"))
        arows.append({"snapshot_date": a,
                      "entry": cal[m] if m < len(cal) else None,
                      "exit126": cal[m + 126] if m + 126 < len(cal) else None})
    lab = pd.concat(rows, ignore_index=True).rename(columns={f"fwd_return_{h}d": f"fwd_{h}" for h in HORIZONS})
    lab.to_parquet(LABELS)
    an = pd.DataFrame(arows)
    an.to_parquet(ANCH)
    print("labels", lab.shape, flush=True)

    # adjusted close (total-return basis) at each anchor's entry session, carried forward ≤ 10 days
    adjpx = pit._fully_adjusted(prices, adj)[["sid", "date", "adj_close", "close", "volume"]].copy()
    adjpx["tv"] = adjpx["close"] * adjpx["volume"].astype(float)
    adjpx = adjpx.sort_values(["sid", "date"])
    adjpx["adtv20"] = adjpx.groupby("sid")["tv"].transform(lambda s: s.rolling(20, min_periods=10).median())
    adjpx["d"] = pd.to_datetime(adjpx["date"])
    out = []
    for r in an.dropna(subset=["entry"]).itertuples():
        e = pd.Timestamp(r.entry)
        g = adjpx[(adjpx["d"] <= e) & (adjpx["d"] >= e - pd.Timedelta(days=10))]
        g = g.groupby("sid").tail(1)
        # ADTV and raw close as known at the anchor (rows up to the anchor date)
        h = adjpx[(adjpx["d"] <= pd.Timestamp(r.snapshot_date)) & (adjpx["d"] >= pd.Timestamp(r.snapshot_date) - pd.Timedelta(days=10))]
        h = h.groupby("sid").tail(1)[["sid", "adtv20", "close"]].rename(columns={"close": "close_anchor"})
        g = g[["sid", "adj_close", "close", "date"]].merge(h, on="sid", how="outer")
        g["snapshot_date"] = r.snapshot_date
        out.append(g)
    ep = pd.concat(out, ignore_index=True)
    ep.to_parquet(PRICES)
    print("entry prices", ep.shape, flush=True)


def load():
    panel = pd.read_parquet(PANEL)
    lab = pd.read_parquet(LABELS)
    df = panel.merge(lab, on=["sid", "snapshot_date"], how="left")
    return df, pd.read_parquet(ANCH)


# ───────────────────────── H1 ─────────────────────────

H1_CLAIMS = {
    ("MID", "z_score"): (-0.0952, -5.75), ("MID", "interest_coverage"): (-0.0845, -5.02),
    ("MID", "roic"): (-0.0675, -4.27), ("MID", "piotroski_f"): (0.0954, 11.59),
    ("SMALL", "cons_beat_rate_4q"): (0.0802, 6.43), ("SMALL", "value_composite"): (0.0951, 5.69),
    ("SMALL", "sector_tilt"): (0.0728, 4.92), ("LARGE", "metals_beta"): (0.0988, 3.73),
    ("SMALL", "delivery_anomaly_z"): (None, 2.41),
}


def ic_series(df, tier, col, label):
    out = {}
    for d, g in df[df["cap_tier"] == tier].groupby("snapshot_date"):
        out[d] = spearman(g[col].to_numpy(float), g[label].to_numpy(float))
    return pd.Series(out).dropna()


def h1():
    df, _ = load()
    res = []
    for (tier, col), (cic, ct) in H1_CLAIMS.items():
        s126 = ic_series(df, tier, col, "fwd_126")
        s21 = ic_series(df, tier, col, "fwd_21")
        r = {"tier": tier, "factor": col, "n126": len(s126), "ic126": s126.mean(), "t126": nw_t(s126, 6),
             "ic21": s21.mean(), "t21": nw_t(s21, 1), "claim_ic126": cic, "claim_t126": ct}
        r["ic_ok"] = None if cic is None else abs(r["ic126"] - cic) <= 0.01
        r["t_ok"] = abs(r["t126"] - ct) <= 0.5
        res.append(r)
        print(f"{tier:5} {col:22} n={len(s126):3} IC126 {r['ic126']:+.4f} (claim {cic}) t {r['t126']:+.2f} (claim {ct:+.2f})"
              f"  IC21 {r['ic21']:+.4f} t21 {r['t21']:+.2f}", flush=True)
    save("h1", res)


# ───────────────────────── H2 ─────────────────────────

def ic_table(tdf, cols, label):
    """{anchor: {col: IC}} for one tier."""
    rows = {}
    for d, g in tdf.groupby("snapshot_date"):
        y = g[label].to_numpy(float)
        if np.isfinite(y).sum() < 20:
            continue
        rows[d] = {c: spearman(g[c].to_numpy(float), y) for c in cols}
    return pd.DataFrame.from_dict(rows, orient="index").sort_index()


def composite(g, weights):
    tot = sum(abs(w) for w in weights.values())
    s = np.zeros(len(g))
    for c, w in weights.items():
        p = g[c].rank(pct=True)
        p = 1 - p if w < 0 else p
        s += abs(w) * p.fillna(0.5).to_numpy()
    return s / tot


def h2(min_train=24, embargo=6, top_k=8, tbar=2.5, min_months=12, tiers=TIERS, tag=""):
    df, an = load()
    cols = [c for c in pd.read_parquet(PANEL).columns if c not in ("sid", "snapshot_date", "cap_tier", "forensic_penalty")]
    anchors = sorted(df["snapshot_date"].unique())
    exit126 = dict(zip(an["snapshot_date"], an["exit126"]))
    results, scores = {}, []
    for tier in tiers:
        tdf = df[df["cap_tier"] == tier]
        tab = ic_table(tdf, cols, "fwd_126")
        recs = []
        for k, a in enumerate(anchors):
            train = [d for i, d in enumerate(anchors[:k]) if k - i >= embargo and d in tab.index
                     and exit126.get(d) is not None and exit126[d] <= a]
            if len(train) < min_train:
                continue
            tr = tab.loc[train]
            stats = {}
            for c in cols:
                s = tr[c].dropna()
                if len(s) >= min_months:
                    t = nw_t(s, 6)
                    if np.isfinite(t) and abs(t) >= tbar:
                        stats[c] = t
            pick = sorted(stats, key=lambda c: -abs(stats[c]))[:top_k]
            w = {c: float(np.sign(stats[c])) for c in pick}
            g = tdf[tdf["snapshot_date"] == a]
            if not w or g.empty:
                continue
            sc = composite(g, w)
            scores.append(pd.DataFrame({"sid": g["sid"].to_numpy(), "snapshot_date": a, "cap_tier": tier, "score": sc}))
            y = g["fwd_126"].to_numpy(float)
            ic = spearman(sc, y) if np.isfinite(y).sum() >= 20 else np.nan
            top = np.nan
            if np.isfinite(y).sum() >= 20:
                order = np.argsort(-sc)[:15]
                yt = y[order]
                top = np.nanmean(yt) - np.nanmean(y)
            recs.append({"anchor": a, "n_train": len(train), "first_train": train[0], "last_train": train[-1],
                         "factors": ";".join(f"{'+' if w[c] > 0 else '-'}{c}" for c in pick), "ic126": ic, "top15": top})
        r = pd.DataFrame(recs)
        ics = r["ic126"].dropna()
        out = {"first_test": r["anchor"].iloc[0], "first_train": r["first_train"].iloc[0], "last_train_at_first": r["last_train"].iloc[0],
               "n_train_first": int(r["n_train"].iloc[0]), "n_test": len(r), "n_ic126": len(ics),
               "mean_ic126": ics.mean(), "t_nw6": nw_t(ics, 6),
               "top15_126": r["top15"].dropna().mean(), "top15_t": nw_t(r["top15"].dropna(), 6)}
        # non-overlapping check: every 6th month, plain t, per offset
        nono = []
        for off in range(6):
            s = ics.iloc[off::6]
            nono.append(s.mean() / (s.std(ddof=1) / np.sqrt(len(s))))
        out["nonoverlap_t_median"] = float(np.median(nono))
        out["nonoverlap_t_min"] = float(np.min(nono))
        fac = pd.Series([f for s in r["factors"] for f in s.split(";")]).value_counts() / len(r)
        out["top_factors"] = {k: round(v, 2) for k, v in fac.head(8).items()}
        results[tier] = out
        if not tag:
            r.to_csv(OUT / f"rederive_h2_{tier}.csv", index=False)
        print(tier, json.dumps(out, default=float), flush=True)
    if not tag:
        pd.concat(scores, ignore_index=True).to_parquet(OUT / "rederive_oos_scores.parquet")
    save("h2" + tag, results)


def h2_sens():
    """Robustness of the H2 pass: stricter factor history, longer embargo, fewer factors."""
    h2(min_months=24, tiers=("MID", "SMALL"), tag="_minmonths24")
    h2(embargo=12, tiers=("MID", "SMALL"), tag="_embargo12")
    h2(top_k=4, tiers=("MID", "SMALL"), tag="_top4")


# ───────────────────────── H3 ─────────────────────────

BEST = {
    "SMALL": dict(freq=1, N=10, k=3, avg3=True, hold=12),
    "MID": dict(freq=1, N=15, k=3, avg3=False, hold=6),
    "LARGE": dict(freq=3, N=20, k=4, avg3=False, hold=6),
}
DIV_CREDIT = {"LARGE": 0.00126, "MID": 0.00084, "SMALL": 0.00071}
INDEX = {"LARGE": "NIFTY 50", "MID": "NIFTY MIDCAP 150", "SMALL": "NIFTY SMALLCAP 250"}


def km_median(lives, censored):
    """Kaplan-Meier median lifetime (anchors)."""
    t = np.asarray(lives, float)
    c = np.asarray(censored, bool)
    s = 1.0
    for u in np.sort(np.unique(t[~c])):
        at_risk = (t >= u).sum()
        d = ((t == u) & ~c).sum()
        s *= 1 - d / at_risk
        if s <= 0.5:
            return float(u)
    return float("inf")


def simulate(tier, scores, rule, costs=False, defer=True, start_value=1_000_000.0):
    import tools.lh_costs as lc
    df, an = load()
    ep = pd.read_parquet(PRICES)
    entry = dict(zip(an["snapshot_date"], an["entry"]))
    anchors = sorted(scores["snapshot_date"].unique())
    P = ep.pivot_table(index="snapshot_date", columns="sid", values="adj_close", aggfunc="last").reindex(anchors)
    RAWC = ep.pivot_table(index="snapshot_date", columns="sid", values="close_anchor", aggfunc="last").reindex(anchors)
    ADTV = ep.pivot_table(index="snapshot_date", columns="sid", values="adtv20", aggfunc="last").reindex(anchors)
    pan = df[df["snapshot_date"].isin(anchors)][["sid", "snapshot_date", "cap_tier", "forensic_penalty"]]
    S = scores.pivot_table(index="snapshot_date", columns="sid", values="score", aggfunc="last").reindex(anchors)
    if rule["avg3"]:
        Sx = S.rolling(3, min_periods=1).mean().where(S.notna())
    else:
        Sx = S
    tier_of = pan.pivot_table(index="snapshot_date", columns="sid", values="cap_tier", aggfunc="last").reindex(anchors)
    flag = pan.pivot_table(index="snapshot_date", columns="sid", values="forensic_penalty", aggfunc="last").reindex(anchors)
    N, kN, hold, freq = rule["N"], rule["k"] * rule["N"], rule["hold"], rule["freq"]
    cash = start_value
    pos = {}   # sid -> dict(units, basis, i0)
    life, cens = [], []
    traded, values, cost_paid = [], [], 0.0
    n_defer, n_flag, n_stale = 0, 0, 0
    last_px = {}

    def px(i, s):
        v = P.iat[i, P.columns.get_loc(s)] if s in P.columns else np.nan
        return v

    def cost(i, s, val, side):
        if not costs:
            return 0.0
        a = ADTV.iat[i, ADTV.columns.get_loc(s)] if s in ADTV.columns else np.nan
        c = RAWC.iat[i, RAWC.columns.get_loc(s)] if s in RAWC.columns else np.nan
        if not np.isfinite(c):
            c = 100.0
        yr = int(anchors[i][:4])
        return val * lc.one_way_cost_bps(a if np.isfinite(a) else None, c, val, tier, side, yr) / 1e4

    for i, a in enumerate(anchors):
        # mark
        mv = {}
        for s, p in pos.items():
            v = px(i, s)
            if np.isfinite(v):
                last_px[s] = v
            else:
                n_stale += 1
                v = last_px[s]
            mv[s] = p["units"] * v
        V = cash + sum(mv.values())
        values.append(V)
        if i == len(anchors) - 1:
            break
        reb = (i % freq == 0)
        # ranks within tier (rank 1 best) on today's score
        tiers_now = tier_of.iloc[i]
        sx = Sx.iloc[i]
        home = sx[tiers_now.reindex(sx.index) == tier].dropna()
        n_home = len(home)
        rank_home = home.rank(ascending=False, method="first")
        sells = []
        for s, p in list(pos.items()):
            fp = flag.iat[i, flag.columns.get_loc(s)] if s in flag.columns else np.nan
            if np.isfinite(fp) and fp <= -0.20:
                sells.append(s); n_flag += 1; continue
            held = i - p["i0"]
            if held < hold:
                continue
            # out-of-band test (monthly re-test even in quarterly variants if previously deferred)
            if not (reb or p.get("deferred")):
                continue
            if s in rank_home.index:
                out = rank_home[s] > kN
            else:
                t_now = tiers_now.get(s) if s in tiers_now.index else None
                if t_now is None or pd.isna(sx.get(s, np.nan)):
                    out = True
                else:
                    other = sx[tiers_now.reindex(sx.index) == t_now].dropna()
                    out = other.rank(ascending=False, pct=True)[s] > kN / n_home
            if not out:
                p["deferred"] = False
                continue
            if defer:
                days = (pd.Timestamp(entry[a]) - pd.Timestamp(p["d0"])).days
                gain = mv[s] > p["basis"]
                if gain and days <= 365 and days + 42 > 365:
                    p["deferred"] = True; n_defer += 1
                    continue
            sells.append(s)
        for s in sells:
            p = pos.pop(s)
            val = mv[s]
            c = cost(i, s, val, "sell")
            cash += val - c
            cost_paid += c
            traded.append((i, val))
            life.append(i - p["i0"]); cens.append(False)
        # buys: on rebalance, or at once to refill a forced sale in quarterly variants
        if reb or sells:
            slots = N - len(pos)
            if slots > 0:
                cand = [s for s in rank_home.sort_values().index[:N] if s not in pos]
                ok = []
                for s in cand:
                    fp = flag.iat[i, flag.columns.get_loc(s)] if s in flag.columns else np.nan
                    if np.isfinite(fp) and fp <= -0.20:
                        continue
                    if not np.isfinite(px(i, s)):
                        continue
                    ok.append(s)
                ok = ok[:slots]
                if ok:
                    amt = min(V / N, cash / len(ok))
                    for s in ok:
                        c = cost(i, s, amt, "buy")
                        units = (amt - c) / px(i, s)
                        pos[s] = {"units": units, "basis": amt, "i0": i, "d0": entry[a]}
                        last_px[s] = px(i, s)
                        cash -= amt
                        cost_paid += c
                        traded.append((i, amt))
    for s, p in pos.items():
        life.append(len(anchors) - 1 - p["i0"]); cens.append(True)
    vals = np.array(values)
    d0, d1 = pd.Timestamp(entry[anchors[0]]), pd.Timestamp(entry[anchors[-1]])
    yrs = (d1 - d0).days / 365.25
    cagr = (vals[-1] / vals[0]) ** (1 / yrs) - 1
    # turnover: ½(buys+sells) excluding the first build, / average value / years
    tr = sum(v for i, v in traded if i > 0)
    turnover = 0.5 * tr / vals.mean() / yrs
    return {"cagr": cagr, "years": yrs, "final": vals[-1], "turnover": turnover, "values": vals.tolist(),
            "km_median_months": km_median(life, cens), "closed_median": float(np.median([l for l, c in zip(life, cens) if not c])),
            "n_positions": len(life), "deferrals": n_defer, "flag_sales": n_flag, "stale_marks": n_stale,
            "costs_paid": cost_paid, "anchors": anchors, "d0": str(d0.date()), "d1": str(d1.date())}


def benchmark(tier, anchors):
    _, an = load()
    entry = dict(zip(an["snapshot_date"], an["entry"]))
    ix = read_sql("SELECT index_symbol, trade_date, close FROM nse_index_history WHERE index_symbol IN (?,?,?)",
                  list(INDEX.values()))
    ix["d"] = pd.to_datetime(ix["trade_date"])
    lvl = []
    for a in anchors:
        e = pd.Timestamp(entry[a])
        g = ix[(ix["index_symbol"] == INDEX[tier]) & (ix["d"] <= e)]
        lvl.append(g.sort_values("d")["close"].iloc[-1] if len(g) else np.nan)
    lvl = np.array(lvl, float)
    rets = lvl[1:] / lvl[:-1] - 1 + DIV_CREDIT[tier]   # index is price-only: credit the tier's dividend yield
    if tier == "MID":
        # equal-weight tier average until the MIDCAP 150 history starts
        df, _ = load()
        ep = pd.read_parquet(PRICES)
        P = ep.pivot_table(index="snapshot_date", columns="sid", values="adj_close", aggfunc="last").reindex(anchors)
        tier_of = df.pivot_table(index="snapshot_date", columns="sid", values="cap_tier", aggfunc="last").reindex(anchors)
        for j in range(len(anchors) - 1):
            if not np.isfinite(rets[j]):
                m = (tier_of.iloc[j] == "MID")
                r = (P.iloc[j + 1] / P.iloc[j] - 1)[m[m].index.intersection(P.columns)].dropna()
                rets[j] = r.mean()
    # (the equal-weight months come from adjusted closes, which already carry dividends)
    vals = np.concatenate([[1.0], np.cumprod(1 + rets)])
    d0, d1 = pd.Timestamp(entry[anchors[0]]), pd.Timestamp(entry[anchors[-1]])
    yrs = (d1 - d0).days / 365.25
    return {"cagr": vals[-1] ** (1 / yrs) - 1, "values": vals.tolist(), "n_from_ew": int(np.isnan(lvl).sum()) if tier == "MID" else 0}


def ew_benchmark(tier, anchors):
    df, _ = load()
    ep = pd.read_parquet(PRICES)
    P = ep.pivot_table(index="snapshot_date", columns="sid", values="adj_close", aggfunc="last").reindex(anchors)
    tier_of = df.pivot_table(index="snapshot_date", columns="sid", values="cap_tier", aggfunc="last").reindex(anchors)
    rets = []
    for j in range(len(anchors) - 1):
        m = (tier_of.iloc[j] == tier)
        rets.append((P.iloc[j + 1] / P.iloc[j] - 1)[m[m].index.intersection(P.columns)].dropna().mean())
    return np.concatenate([[1.0], np.cumprod(1 + np.array(rets))])


def h3(tiers=("SMALL", "MID", "LARGE")):
    mine = pd.read_parquet(OUT / "rederive_oos_scores.parquet")
    theirs = pd.read_parquet(OUT / "oos_scores.parquet")
    theirs = theirs[theirs["method"] == "slow_select"][["sid", "snapshot_date", "cap_tier", "score"]]
    theirs["snapshot_date"] = theirs["snapshot_date"].astype(str).str[:10]
    res = {}
    for tier in tiers:
        rule = BEST[tier]
        for src, sc in (("own_scores", mine), ("their_scores", theirs)):
            sc_t = sc  # every tier: a held stock that moved tier is band-tested in its new tier
            for costs in (False, True):
                r = simulate(tier, sc_t, rule, costs=costs)
                b = benchmark(tier, r["anchors"])
                bv, vv = np.array(b["values"]), np.array(r["values"]) / r["values"][0]
                x = (vv[1:] / vv[:-1]) - (bv[1:] / bv[:-1])
                ew = ew_benchmark(tier, r["anchors"])
                ew_cagr = ew[-1] ** (1 / r["years"]) - 1
                key = f"{tier}|{src}|{'with_costs' if costs else 'pre_cost'}"
                res[key] = {"rule": rule, "book_cagr": r["cagr"], "bench_cagr": b["cagr"], "excess": r["cagr"] - b["cagr"],
                            "excess_vs_ew": r["cagr"] - ew_cagr, "ew_cagr": ew_cagr,
                            "t_nw3_monthly_diff": nw_t(x, 3), "turnover": r["turnover"],
                            "km_median_months": r["km_median_months"], "closed_median_months": r["closed_median"],
                            "positions": r["n_positions"], "deferrals": r["deferrals"], "flag_sales": r["flag_sales"],
                            "stale_marks": r["stale_marks"], "costs_paid": r["costs_paid"], "months": len(r["anchors"]) - 1,
                            "d0": r["d0"], "d1": r["d1"]}
                print(key, json.dumps({k: v for k, v in res[key].items() if k != "rule"}, default=float), flush=True)
    save("h3", res)


if __name__ == "__main__":
    {"build": build, "h1": h1, "h2": h2, "h2_sens": h2_sens, "h3": h3}[sys.argv[1]]()
