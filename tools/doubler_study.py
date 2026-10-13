"""
Why did the doublers double, why did we miss them, was missing them prudent, and is there an
asymmetric-return model worth building?  (READ-ONLY on the DB; writes data/lh/v2/doubler_*)

Amit 2026-10-13: "analyse these and figure out why our model did not catch it (it might be prudent also
to not catch it) … what other asymmetric return model could have caught it … sentiment, Adani political
connections, regulatory lobbying …"

Panel: every (stock, monthly anchor) 2019-12 → 2025-10 in LARGE / MID / SMALL (data/lh/labels.parquet,
fwd_252 = next-12-month adjusted return). Today's universe only (survivorship: doublers that later
delisted are missing, so the "prudence" numbers are if anything flattering).
Outcomes: DOUBLE fwd_252 >= +100 % · HALVE fwd_252 <= −50 %.

Part A — profiles (descriptive): P(double), P(halve), mean / median fwd_252 by feature quintile (within
anchor × tier) and by category: tier, year, sector, industry, PSU (a government holder in BSE shareholding
filings), business group (name match: Adani, Tata, …; a crude stand-in for "connections"), loss-making,
penny (< ₹50), 3-year drawdown, sector policy score (sector_policy_pit), forensic flag.
Part B — prudence: for each stock's first doubling run, the return over the 12 months after the run
ended (fwd_252 at anchor + 12 months) and the share that gave back half.
Part C — an asymmetric model, PRE-REGISTERED here (2026-10-13) before Part A was read:
  target  DOUBLE.  features  the Part-A numeric features as within-anchor-tier percentiles + the PSU,
  group, loss-making and penny flags + tier dummies.
  fit     logistic regression (L2, C = 0.1, class_weight balanced) on anchors 2019-12 … 2022-12 only.
  test    anchors 2023-01 … 2025-10, never seen. For the model's top 20 per tier per anchor (SMALL and MID):
          P(double), P(halve), mean and median fwd_252, mean excess vs the tier median; against the base
          rates and against the live model's top 20 (`fast_v1`).
  bar     "worth building" if, in SMALL test anchors, top-20 P(double) >= 2× the base rate AND the top-20
          mean excess > 0 AND median excess >= 0 (i.e. not only a lottery ticket), with the sign held in
          both test years 2023-24 and 2025.

Usage: python -m tools.doubler_study
"""

import re
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from signals._prices import apply_adjustments  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
NUM = ["mom_6m", "mom_12m", "position_52w", "low_vol_252d", "max_lottery_21d", "revenue_growth_yoy",
       "eps_growth_yoy", "roe", "debt_to_equity", "book_to_price", "earnings_yield", "promoter_trend_4q",
       "sector_momentum", "delivery_anomaly_z", "avg_delivery_pct_30d", "relative_turnover", "announcement_car",
       "z_score", "dd_3y", "policy_score", "close_price"]
GROUPS = {"Adani": r"\badani\b", "Tata": r"\btata\b", "Reliance": r"\breliance\b", "Birla/Aditya": r"\bbirla\b|\baditya\b",
          "Bajaj": r"\bbajaj\b", "Mahindra": r"\bmahindra\b", "JSW/Jindal": r"\bjsw\b|\bjindal\b", "Vedanta": r"\bvedanta\b|\bhindustan zinc\b",
          "Godrej": r"\bgodrej\b", "Murugappa": r"\bcholamandalam\b|\bcoromandel\b|\bcarborundum\b|\btube investments\b",
          "Hinduja": r"\bhinduja\b|\bashok leyland\b|\bindusind\b", "RPG": r"\bceat\b|\bzensar\b|\bkec\b|\brpg\b",
          "Essel/Zee": r"\bzee\b|\bessel\b", "Wadia": r"\bbritannia\b|\bbombay dyeing\b|\bbombay burmah\b"}


def build():
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_252"])
    lab = lab[lab["cap_tier"].isin(["LARGE", "MID", "SMALL"]) & lab["fwd_252"].notna()]
    anchors = sorted(lab["snapshot_date"].unique())
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ph = ",".join("?" * len(anchors))
    cols = [c for c in NUM if c not in ("dd_3y", "policy_score")] + ["profit_margin", "forensic_penalty"]
    pan = pd.read_sql(f"SELECT sid, snapshot_date, {', '.join(cols)} FROM daily_snapshots_pit WHERE snapshot_date IN ({ph})",
                      con, params=anchors)
    st = pd.read_sql("SELECT sid, ticker, name, sector, industry FROM stocks", con)
    psu = set(pd.read_sql("SELECT DISTINCT sid FROM shareholding_holders WHERE holder_name LIKE '%President of India%' "
                          "OR holder_name LIKE '%Governor%' OR upper(holder_name) LIKE '%GOVERNMENT OF%'", con)["sid"])
    pol = pd.read_sql("SELECT sector, snapshot_date, policy_score FROM sector_policy_pit", con)
    px = pd.read_sql("SELECT sid, date, close FROM stock_prices WHERE close > 0 AND date >= '2016-06-01'", con)
    adj = pd.read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments", con)
    con.close()
    px = apply_adjustments(px, adj, date.max)
    P = px.pivot_table(index="date", columns="sid", values="adj_close").sort_index()
    rows = []
    for a in anchors:
        w = P[P.index <= a].tail(756)
        rows.append(pd.DataFrame({"sid": w.columns, "snapshot_date": a, "dd_3y": (w.iloc[-1] / w.max()).values}))
    dd = pd.concat(rows)
    d = lab.merge(pan, on=["sid", "snapshot_date"], how="left").merge(dd, on=["sid", "snapshot_date"], how="left") \
           .merge(st, on="sid", how="left")
    pol["pol_t"] = pd.to_datetime(pol["snapshot_date"])
    pol = pol.drop(columns=["snapshot_date"]).sort_values("pol_t")
    d["_t"] = pd.to_datetime(d["snapshot_date"])
    d = d.sort_values("_t")
    d = pd.merge_asof(d, pol, left_on="_t", right_on="pol_t", by="sector", direction="backward").drop(columns=["pol_t", "_t"])
    d["psu"] = d["sid"].isin(psu)
    d["group"] = "none"
    for g, pat in GROUPS.items():
        d.loc[d["name"].str.lower().str.contains(pat, regex=True, na=False), "group"] = g
    d["loss_making"] = (d["profit_margin"] < 0) | (d["earnings_yield"] < 0)
    d["penny"] = d["close_price"] < 50
    d["flagged"] = d["forensic_penalty"].fillna(0) < 0
    d["double"] = d["fwd_252"] >= 1.0
    d["halve"] = d["fwd_252"] <= -0.5
    d["ex"] = d["fwd_252"] - d.groupby(["snapshot_date", "cap_tier"])["fwd_252"].transform("median")
    return d


def profile(d):
    base = dict(p_double=d["double"].mean(), p_halve=d["halve"].mean())
    out = []

    def add(kind, key, g):
        out.append(dict(kind=kind, key=str(key), n=len(g), p_double=g["double"].mean(), p_halve=g["halve"].mean(),
                        mean_fwd=g["fwd_252"].mean(), median_fwd=g["fwd_252"].median(), median_ex=g["ex"].median()))
    for c in NUM:
        q = d.groupby(["snapshot_date", "cap_tier"])[c].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False)
                                                                   if s.notna().sum() >= 25 else np.nan)
        for k, g in d.groupby(q):
            add(c, f"Q{int(k) + 1}", g)
    for c in ("cap_tier", "psu", "group", "loss_making", "penny", "flagged", "sector"):
        for k, g in d.groupby(c):
            add(c, k, g)
    d["year"] = d["snapshot_date"].str[:4]
    for k, g in d.groupby("year"):
        add("year", k, g)
    ind = d.groupby("industry").filter(lambda g: len(g) >= 300)
    for k, g in ind.groupby("industry"):
        add("industry", k, g)
    t = pd.DataFrame(out)
    t["lift_double"] = t["p_double"] / base["p_double"]
    t["lift_halve"] = t["p_halve"] / base["p_halve"]
    return t, base


def prudence(d):
    runs = d[d["double"]].sort_values(["sid", "snapshot_date"]).groupby("sid").head(1)
    nxt = d[["sid", "snapshot_date", "fwd_252"]].copy()
    nxt["snapshot_date"] = (pd.to_datetime(nxt["snapshot_date"]) - pd.DateOffset(months=12)).dt.strftime("%Y-%m")
    runs = runs.assign(ym=runs["snapshot_date"].str[:7]).merge(
        nxt.rename(columns={"snapshot_date": "ym", "fwd_252": "next_12m"}).drop_duplicates(["sid", "ym"]),
        on=["sid", "ym"], how="left")
    r = runs.dropna(subset=["next_12m"])
    return dict(runs=len(runs), with_next_year=len(r), next12_median=float(r["next_12m"].median()),
                next12_mean=float(r["next_12m"].mean()), gave_back_half=float((r["next_12m"] <= -0.5).mean()),
                kept_rising=float((r["next_12m"] > 0).mean()),
                by_kind={k: dict(n=int(len(g)), median_next12=round(float(g["next_12m"].median()), 3),
                                 gave_back_half=round(float((g["next_12m"] <= -0.5).mean()), 3))
                         for k, g in [("psu", r[r["psu"]]), ("group", r[r["group"] != "none"]),
                                      ("loss_making", r[r["loss_making"]]), ("penny", r[r["penny"]]),
                                      ("flagged", r[r["flagged"]]), ("all", r)]})


def model(d):
    from sklearn.linear_model import LogisticRegression
    X = pd.DataFrame(index=d.index)
    for c in NUM:
        X[c] = d.groupby(["snapshot_date", "cap_tier"])[c].rank(pct=True).fillna(0.5)
    for c in ("psu", "loss_making", "penny"):
        X[c] = d[c].astype(float)
    X["group"] = (d["group"] != "none").astype(float)
    for t in ("MID", "SMALL"):
        X[f"tier_{t}"] = (d["cap_tier"] == t).astype(float)
    train = d["snapshot_date"] <= "2022-12-31"
    test = d["snapshot_date"] >= "2023-01-01"
    m = LogisticRegression(C=0.1, class_weight="balanced", max_iter=2000).fit(X[train], d.loc[train, "double"])
    d = d.copy()
    d["p_hat"] = m.predict_proba(X)[:, 1]
    coef = pd.Series(m.coef_[0], index=X.columns).sort_values()
    fv = pd.read_parquet(V2 / "scores_all.parquet")
    fv = fv[fv["method"] == "fast_v1"][["sid", "snapshot_date", "score"]].rename(columns={"score": "live"})
    d = d.merge(fv, on=["sid", "snapshot_date"], how="left")
    res = []
    for tier in ("SMALL", "MID"):
        tt = d[test & (d["cap_tier"] == tier)] if False else d[(d["snapshot_date"] >= "2023-01-01") & (d["cap_tier"] == tier)]
        for name, col in (("asym_model", "p_hat"), ("live_model", "live")):
            top = tt.sort_values(col, ascending=False).groupby("snapshot_date").head(20)
            for per, g in (("2023-24", top[top["snapshot_date"] < "2025-01-01"]), ("2025", top[top["snapshot_date"] >= "2025-01-01"]),
                           ("all test", top)):
                base = tt[(tt["snapshot_date"].isin(g["snapshot_date"].unique()))]
                res.append(dict(tier=tier, model=name, period=per, n=len(g), p_double=g["double"].mean(),
                                base_p_double=base["double"].mean(), p_halve=g["halve"].mean(),
                                base_p_halve=base["halve"].mean(), mean_ex=g["ex"].mean(), median_ex=g["ex"].median()))
    r = pd.DataFrame(res)
    s = r[(r["tier"] == "SMALL") & (r["model"] == "asym_model")].set_index("period")
    verdict = bool(s.loc["all test", "p_double"] >= 2 * s.loc["all test", "base_p_double"] and s.loc["all test", "mean_ex"] > 0
                   and s.loc["all test", "median_ex"] >= 0 and (s.loc[["2023-24", "2025"], "mean_ex"] > 0).all())
    return r, coef, verdict


def main():
    d = build()
    d.to_parquet(V2 / "doubler_panel.parquet", index=False)
    t, base = profile(d)
    t.to_csv(V2 / "doubler_profiles.csv", index=False)
    pr = prudence(d)
    r, coef, verdict = model(d)
    r.to_csv(V2 / "doubler_model.csv", index=False)
    pd.set_option("display.width", 220)
    print("BASE:", {k: round(v, 4) for k, v in base.items()}, "rows", len(d))
    show = t[(t["n"] >= 200)].copy()
    print("\nTOP lift_double (n >= 200):")
    print(show.sort_values("lift_double", ascending=False).head(35).round(3).to_string(index=False))
    print("\nPRUDENCE:", pr)
    print("\nASYM MODEL (test 2023-01 → 2025-10):\n", r.round(4).to_string(index=False))
    print("\ncoefficients:\n", coef.round(3).to_string())
    print("\nVERDICT worth building:", verdict)


if __name__ == "__main__":
    main()
