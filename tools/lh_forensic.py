"""
Plan 0025 tasks 2.3 / 2.4 — do the forensic penalties and the accruals weight earn their place?
(READ-ONLY on the DB; writes data/lh/v2/forensic_*.csv)

PRE-REGISTRATION (2026-10-13, before any result):

Rebuild from annual Screener statements (fundamentals_screener, knowable at period end + 150
days), non-Financials only, at every monthly anchor of data/lh/labels.parquet:
  Beneish M, the live 6-factor form and coefficients of signals/forensic.py (DSRI, AQI, SGI, DEPI,
  TATA, LVGI; same clips; >= 5 of 6 components) on annual figures:
    revenue = Sales, NI = Net profit, receivables = Trade receivables (else Receivables),
    TA = Total, CA ~ Other Assets, PPE = Net Block, dep = Depreciation, OCF = Cash from Operating
    Activity, CL ~ Other Liabilities, LTD = Long term Borrowings (else Borrowings).
  Altman Z'' (EM), coefficients of signals/forensic.py: X1 = (Other Assets − Other Liabilities)/TA,
    X2 = Reserves/TA, X3 = (PBT + Interest)/TA, X4 = (Equity Share Capital + Reserves)/(TA − equity);
    same clips.
  Flags as live: M > −1.28 LIKELY (−0.20), M > −1.72 POSSIBLE (−0.10); Z < 1.10 DISTRESS (−0.20),
    Z < 2.60 GREY (−0.10).
  Approximation: live M uses TTM quarterly revenue/NI and Tickertape current assets/liabilities; the
  annual form is a proxy. Its flag rate is compared with the live flags on the anchors both cover.
2.3 test, per tier and flag: per-anchor mean and median excess vs the tier median at 63 / 126 / 252
  sessions, beat-median rate, top-5 % and bottom-5 % rates; the flagged-minus-clean mean excess
  with a non-overlap t; share of the top revenue-growth quintile flagged.
  Decision rule: a −0.20 penalty is justified only if flagged stocks underperform clean ones at
  126 with non-overlap t <= −2.0 in that tier; otherwise recommend a review flag (no score cut).
2.4 accruals: cf_accruals_long = (Net profit − Cash from Operating Activity) / Total, rank IC at
  63 / 126 / 252 within tier, Newey-West and non-overlap t, by period. The live MID weight (−0.10)
  is supported only if the MID IC at 126 is negative with non-overlap t <= −2.0.

Usage: python -m tools.lh_forensic
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import SCREEN  # noqa: E402
from signals.forensic import ALTMAN_COEFFICIENTS as AC, BENEISH_COEFFICIENTS as BC  # noqa: E402
from tools.backtest_pit import _aggregate, _compute_ic  # noqa: E402
from tools.lh_growth import asof  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
V2 = LH / "v2"
LAG = 150
HORIZONS = (63, 126, 252)
NW_LAG = {63: 3, 126: 6, 252: 12}
TIERS = ("LARGE", "MID", "SMALL")
PERIODS = {"2020-22": ("0000", "2022-12-31"), "2023-24": ("2023-01-01", "2024-12-31"),
           "2025-26": ("2025-01-01", "9999")}
ITEMS = {"Sales": "rev", "Net profit": "ni", "Trade receivables": "rec_t", "Receivables": "rec",
         "Total": "ta", "Other Assets": "ca", "Net Block": "ppe", "Depreciation": "dep",
         "Cash from Operating Activity": "ocf", "Other Liabilities": "cl", "Long term Borrowings": "ltd",
         "Borrowings": "borrow", "Reserves": "res", "Equity Share Capital": "eqc",
         "Profit before tax": "pbt", "Interest": "interest"}
CLIP = {"DSRI": (0, 5), "AQI": (-2, 5), "SGI": (0, 5), "DEPI": (0, 5), "TATA": (-1, 1), "LVGI": (0, 5)}


def statements(conn):
    raw = pd.read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener "
                      "WHERE period_type='annual' AND line_item IN (%s)" % ",".join("?" * len(ITEMS)),
                      conn, params=list(ITEMS))
    w = raw.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="last")
    w = w.rename(columns=ITEMS).reset_index().sort_values(["sid", "period_end"])
    for c in ITEMS.values():
        if c not in w:
            w[c] = np.nan
    w["rec"] = w["rec_t"].fillna(w["rec"])
    w["ltd"] = w["ltd"].fillna(w["borrow"])
    g = w.groupby("sid")
    p = lambda c: g[c].shift(1)  # noqa: E731
    consec = (pd.to_datetime(w["period_end"]) - pd.to_datetime(g["period_end"].shift(1))).dt.days.between(330, 400)

    def r(a, b):
        return np.where((b != 0) & np.isfinite(a) & np.isfinite(b), a / np.where(b != 0, b, 1), np.nan)

    comp = pd.DataFrame(index=w.index)
    comp["DSRI"] = r(r(w["rec"], w["rev"]), r(p("rec"), p("rev")))
    comp["AQI"] = r(1 - r(w["ca"] + w["ppe"], w["ta"]), 1 - r(p("ca") + p("ppe"), p("ta")))
    comp["SGI"] = r(w["rev"], p("rev"))
    comp["DEPI"] = r(r(p("dep"), p("dep") + p("ppe")), r(w["dep"], w["dep"] + w["ppe"]))
    comp["TATA"] = r(w["ni"] - w["ocf"], w["ta"])
    comp["LVGI"] = r(r(w["cl"] + w["ltd"], w["ta"]), r(p("cl") + p("ltd"), p("ta")))
    for k, (lo, hi) in CLIP.items():
        comp[k] = comp[k].clip(lo, hi)
    comp.loc[~consec.values, ["DSRI", "AQI", "SGI", "DEPI", "LVGI"]] = np.nan
    ok = comp.notna().sum(axis=1) >= 5
    m = BC["intercept"] + sum(BC[k] * comp[k].fillna(1.0) for k in CLIP)
    w["m_score"] = np.where(ok, m, np.nan)
    eq = w["eqc"].fillna(0) + w["res"]
    x1 = r(w["ca"] - w["cl"], w["ta"]).clip(-1, 1)
    x2 = r(w["res"], w["ta"]).clip(-2, 2)
    x3 = r(w["pbt"] + w["interest"].fillna(0), w["ta"]).clip(-1, 1)
    x4 = r(eq, w["ta"] - eq).clip(-5, 20)
    w["z_score"] = (AC["intercept"] + AC["X1_WC_TA"] * x1 + AC["X2_RE_TA"] * x2
                    + AC["X3_EBIT_TA"] * x3 + AC["X4_EQ_TL"] * x4)
    w["cf_accruals_long"] = r(w["ni"] - w["ocf"], w["ta"])
    w["sales_g1"] = np.where(consec, r(w["rev"], p("rev")) - 1, np.nan)
    return w


def nonoverlap_t(series_by_anchor, h):
    s_all = series_by_anchor.dropna().sort_index()
    step = h // 21
    ts = [s.mean() / (s.std() / np.sqrt(len(s))) for s in (s_all.iloc[o::step] for o in range(step))
          if len(s) >= 3 and s.std() > 0]
    return float(np.mean(ts)) if ts else None


def run():
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lab = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier"]
                          + [f"fwd_{h}" for h in HORIZONS])
    lab = lab[lab["cap_tier"].isin(TIERS)]
    anchors = sorted(lab["snapshot_date"].unique())
    st = statements(conn)
    sec = pd.read_sql("SELECT sid, sector FROM stocks", conn)
    ph = ",".join("?" * len(anchors))
    live = pd.read_sql(f"SELECT sid, snapshot_date, m_score AS m_live, z_score AS z_live FROM daily_snapshots_pit "
                       f"WHERE snapshot_date IN ({ph})", conn, params=anchors)
    conn.close()
    feat = asof(st, "period_end", LAG, anchors, ["m_score", "z_score", "cf_accruals_long", "sales_g1"])
    df = lab.merge(feat, on=["sid", "snapshot_date"], how="left").merge(sec, on="sid", how="left") \
            .merge(live, on=["sid", "snapshot_date"], how="left")
    df = df[~df["sector"].isin(SCREEN["financial_sectors"])].copy()
    df["m_flag"] = np.select([df["m_score"] > -1.28, df["m_score"] > -1.72, df["m_score"].notna()],
                             ["LIKELY", "POSSIBLE", "CLEAN"], default="NA")
    df["z_flag"] = np.select([df["z_score"] < 1.10, df["z_score"] < 2.60, df["z_score"].notna()],
                             ["DISTRESS", "GREY", "SAFE"], default="NA")
    g = df.groupby(["snapshot_date", "cap_tier"])
    for h in HORIZONS:
        df[f"ex_{h}"] = df[f"fwd_{h}"] - g[f"fwd_{h}"].transform("median")
        df[f"rp_{h}"] = g[f"fwd_{h}"].rank(pct=True)

    # calibration vs live flags where both exist
    both = df[df["m_live"].notna() & df["m_score"].notna()]
    calib = dict(rows=len(both), m_corr=round(float(both["m_score"].corr(both["m_live"], method="spearman")), 3),
                 likely_rate_annual=round(float((both["m_score"] > -1.28).mean()), 3),
                 likely_rate_live=round(float((both["m_live"] > -1.28).mean()), 3),
                 z_corr=round(float(both["z_score"].corr(both["z_live"], method="spearman")), 3))
    print("calibration vs live (2024-07+ anchors):", calib)
    print("anchors with annual M:", df.loc[df["m_score"].notna(), "snapshot_date"].nunique(),
          "first", df.loc[df["m_score"].notna(), "snapshot_date"].min())

    recs = []
    for flagcol, clean in (("m_flag", "CLEAN"), ("z_flag", "SAFE")):
        for tier in TIERS:
            t = df[df["cap_tier"] == tier]
            for flag in sorted(set(t[flagcol]) - {"NA"}):
                for h in HORIZONS:
                    x = t[(t[flagcol] == flag) & t[f"ex_{h}"].notna()]
                    c = t[(t[flagcol] == clean) & t[f"ex_{h}"].notna()]
                    if x.empty:
                        continue
                    per_f = x.groupby("snapshot_date")[f"ex_{h}"].mean()
                    per_c = c.groupby("snapshot_date")[f"ex_{h}"].mean()
                    diff = (per_f - per_c).dropna()
                    recs.append(dict(
                        score=flagcol, tier=tier, flag=flag, h=h, anchors=x["snapshot_date"].nunique(),
                        n_per_anchor=round(len(x) / max(x["snapshot_date"].nunique(), 1), 1),
                        mean_ex=round(float(per_f.mean()), 4), median_ex=round(float(x[f"ex_{h}"].median()), 4),
                        beat_median=round(float((x[f"ex_{h}"] > 0).mean()), 3),
                        top5=round(float((x[f"rp_{h}"] >= .95).mean()), 3),
                        bottom5=round(float((x[f"rp_{h}"] <= .05).mean()), 3),
                        minus_clean=round(float(diff.mean()), 4) if flag != clean else None,
                        t_nonoverlap=(nonoverlap_t(diff, h) if flag != clean and len(diff) > 6 else None)))
    res = pd.DataFrame(recs)
    res.to_csv(V2 / "forensic_flags.csv", index=False)

    q = df[df["sales_g1"].notna() & df["m_score"].notna()].copy()
    q["gq"] = q.groupby(["snapshot_date", "cap_tier"])["sales_g1"].rank(pct=True)
    growth_flag = q.groupby(pd.cut(q["gq"], [0, .2, .4, .6, .8, 1]), observed=True)["m_flag"] \
                   .apply(lambda s: round(float((s == "LIKELY").mean()), 3))

    acc = []
    for tier in TIERS:
        t = df[df["cap_tier"] == tier]
        for h in HORIZONS:
            rows = _compute_ic(t, "cf_accruals_long", f"fwd_{h}")
            r_ = _aggregate(rows, "acc", tier, "lh", cadence="monthly", nw_lag=NW_LAG[h]) if rows else None
            if not r_:
                continue
            s = pd.Series([x[1] for x in rows], index=[x[0] for x in rows])
            rec = dict(tier=tier, h=h, n=r_["n_periods"], ic=round(r_["mean_ic"], 4), t_nw=round(r_["t_stat"], 2),
                       t_nonoverlap=round(nonoverlap_t(s, h), 2))
            for p, (lo, hi) in PERIODS.items():
                sub = s[(s.index >= lo) & (s.index <= hi)]
                rec[f"ic_{p}"] = round(float(sub.mean()), 4) if len(sub) >= 3 else None
            acc.append(rec)
    acc = pd.DataFrame(acc)
    acc.to_csv(V2 / "forensic_accruals.csv", index=False)

    pd.set_option("display.width", 220)
    print("\n== flags (excess vs tier median; minus_clean = flagged − clean, per-anchor means)")
    print(res[res["h"] == 126].to_string(index=False))
    print("\n== 252 sessions"); print(res[(res["h"] == 252)].to_string(index=False))
    print("\n== share flagged LIKELY by sales-growth quintile:"); print(growth_flag.to_string())
    print("\n== accruals (cf_accruals_long; negative IC = high accruals underperform)")
    print(acc.to_string(index=False))
    return res, acc, calib


if __name__ == "__main__":
    run()
