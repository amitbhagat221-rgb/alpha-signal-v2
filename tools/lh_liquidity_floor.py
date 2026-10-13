"""
Does the SMALL sleeve survive the investor's ₹1 crore/day liquidity floor?  (READ-ONLY on the DB)

PRE-REGISTRATION (2026-10-13): at each monthly anchor, drop SMALL stocks whose median traded value
(close × volume) over the 20 sessions up to the anchor is below ₹1 crore, then rerun the 12-start
timing test (tools.lh_timing_luck books: slow_v2 top 20, fast_select tactical top 20, 50/50 combo).
The floor joins the paper-sleeve rules if the floored books still meet ADR 0073 grade B on the
12-start test (>= 10/12 starts beating the index; median t >= 1.5 for the combo).
Writes data/lh/v2/liquidity_floor.csv.  Usage: python -m tools.lh_liquidity_floor
"""
import os, sqlite3, sys
from pathlib import Path
import numpy as np
import pandas as pd
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
import tools.lh_book as B  # noqa: E402
from tools.lh_timing_luck import scores, tstat  # noqa: E402
LH = PROJECT_ROOT / "data" / "lh"; V2 = LH / "v2"; FLOOR = 1e7


def adtv_by_anchor(anchors):
    con = sqlite3.connect(f"file:{PROJECT_ROOT / 'data' / 'alpha_signal.db'}?mode=ro", uri=True)
    px = pd.read_sql("SELECT sid, date, close * volume AS tv FROM stock_prices WHERE close > 0 AND date >= ?",
                     con, params=[(pd.Timestamp(min(anchors)) - pd.Timedelta(days=45)).date().isoformat()])
    con.close()
    out = []
    for a in anchors:
        w = px[px["date"] <= a]
        last = sorted(w["date"].unique())[-20:]
        m = w[w["date"].isin(last)].groupby("sid")["tv"].median()
        out.append(pd.DataFrame({"sid": m.index, "snapshot_date": a, "adtv": m.values}))
    return pd.concat(out)


def main():
    sc = scores()
    sc = sc[sc["method"].isin(["slow_v2", "fast_select"]) & (sc["snapshot_date"] >= "2022-06-01")]
    liq = adtv_by_anchor(sorted(sc["snapshot_date"].unique()))
    sc = sc.merge(liq, on=["sid", "snapshot_date"], how="left")
    print("SMALL rows below the floor:", round(float((sc.loc[sc.cap_tier == "SMALL", "adtv"] < FLOOR).mean()), 3))
    rows = []
    for floored in (False, True):
        s = sc[(sc["adtv"] >= FLOOR) | (sc["cap_tier"] != "SMALL")] if floored else sc
        s = s.drop(columns=["adtv"])
        for st in sorted(s.loc[s["method"] == "fast_select", "snapshot_date"].unique())[:12]:
            d = V2 / "win_floor"; d.mkdir(parents=True, exist_ok=True)
            s[s["snapshot_date"] >= st].to_parquet(d / "oos_scores.parquet", index=False)
            if not (d / "labels.parquet").exists():
                os.symlink(LH / "labels.parquet", d / "labels.parquet")
            B.LH = d; D = B.Data(); bench = B.benchmark(D, "SMALL"); ser = {}
            for name, v in (("slow_v2", dict(method="slow_v2", reb="M", N=20, k=3, score="avg3", min_hold=12, defer=True, block="f")),
                            ("tactical", dict(method="fast_select", reb="M", N=20, k=2, score="raw", min_hold=0, defer=False, block="f"))):
                r, m = B.simulate(D, "SMALL", v, bench)
                a, b = m["atlv"].to_numpy(float), m["bench"].to_numpy(float)
                ser[name] = (a[1:] / a[:-1] - 1) - (b[1:] / b[:-1] - 1)
                rows.append(dict(floor=floored, start=st, book=name, excess=r["excess_cagr"], t=r["t_nw"]))
            x = (ser["slow_v2"] + ser["tactical"]) / 2
            rows.append(dict(floor=floored, start=st, book="combo", excess=round(float(np.prod(1 + x) ** (12 / len(x)) - 1), 4),
                             t=round(tstat(x), 3)))
    df = pd.DataFrame(rows); df.to_csv(V2 / "liquidity_floor.csv", index=False)
    print(df.groupby(["floor", "book"]).agg(median_excess=("excess", "median"), min_excess=("excess", "min"),
          starts=("excess", lambda v: f"{int((v > 0).sum())}/{len(v)}"), median_t=("t", "median")).round(3).to_string())


if __name__ == "__main__":
    main()
