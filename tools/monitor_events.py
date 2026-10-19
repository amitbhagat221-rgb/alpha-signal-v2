"""
Plan 0025 task 4.1 — thesis monitors: what happens after a warning sign, seen at the next monthly
review?  (READ-ONLY on the DB; writes data/lh/v2/monitor_*.csv)

PRE-REGISTRATION (2026-10-13, before any result):
Each event is assigned to the first monthly anchor strictly after its knowable date (the review that
would see it). Outcome = the stock's forward return from that anchor (data/lh/labels.parquet,
pit.forward_returns) minus its tier's median, at 63 and 126 sessions. Also shown: the excess in the
month before that review (how much of the move had already happened).
Events (BSE announcements 2018+, shareholding 2016+, PIT panel 2019-12+):
  auditor_resign     subcategory 'Resignation of Statutory Auditors'
  cfo_resign         'Resignation of Chief Financial Officer (CFO)'
  ceo_md_resign      'Resignation of Managing Director' / '…Chief Executive Officer (CEO)' /
                     '…Chairman and Managing Director'
  director_resign    'Resignation of Director'
  rating_downgrade   Credit Rating headline with 'downgrad', or 'negative' without 'reaffirm'
  rating_upgrade     Credit Rating headline with 'upgrad' (contrast, expected positive)
  pledge_rise        shareholding pledge_pct up >= 2 points q/q (knowable end_date + 21 days)
  promoter_cut       promoter_pct down >= 2 points q/q (knowable end_date + 21 days)
  price_crash        last month's return in the bottom 5 % of the tier (at the anchor)
  results_shock      a new announcement_car <= −0.08 (value changed since the previous anchor)
  delivery_collapse  delivery_anomaly_z <= −2 at the anchor
Per event: n, mean and median excess, the false-alarm rate (share that beat the tier median), and a
non-overlap t on the per-anchor mean excess (126: every 6th anchor, averaged over offsets).
Grade (pre-registered): EXIT-grade if mean excess at 126 <= −5 % with non-overlap t <= −2.0 and
false-alarm rate <= 40 %; REVIEW-grade if mean excess at 126 < 0 with t <= −1.5; else NOISE.
Caveat fixed in advance: the label universe is today's listed names, so firms that delisted after a
bad event are missing; every negative effect here is therefore understated.

Usage: python -m tools.monitor_events
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from signals import announcements  # noqa: E402  (BSE history + NSE live, ADR 0082)

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
LH = PROJECT_ROOT / "data" / "lh"
OUT = LH / "v2"
SUBCAT = {
    "auditor_resign": ["Resignation of Statutory Auditors"],
    "cfo_resign": ["Resignation of Chief Financial Officer (CFO)"],
    "ceo_md_resign": ["Resignation of Managing Director", "Resignation of Chief Executive Officer (CEO)",
                      "Resignation of Chairman and Managing Director"],
    "director_resign": ["Resignation of Director"],
}


def nonoverlap_t(s, step):
    s = s.dropna().sort_index()
    ts = [x.mean() / (x.std() / np.sqrt(len(x))) for x in (s.iloc[o::step] for o in range(step))
          if len(x) >= 3 and x.std() > 0]
    return float(np.mean(ts)) if ts else np.nan


def run():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    lab = pd.read_parquet(LH / "labels.parquet",
                          columns=["sid", "snapshot_date", "cap_tier", "fwd_63", "fwd_126", "fwd_next_anchor"])
    lab = lab[lab["cap_tier"].isin(["LARGE", "MID", "SMALL"])].copy()
    anchors = np.array(sorted(lab["snapshot_date"].unique()))
    g = lab.groupby(["snapshot_date", "cap_tier"])
    for c in ("fwd_63", "fwd_126", "fwd_next_anchor"):
        lab[f"x_{c}"] = lab[c] - g[c].transform("median")
    # the month before each anchor = the previous anchor's next-anchor return
    lab = lab.sort_values(["sid", "snapshot_date"])
    lab["x_prior_month"] = lab.groupby("sid")["x_fwd_next_anchor"].shift(1)
    lab["prior_month_pct"] = lab.groupby("sid")["fwd_next_anchor"].shift(1)

    ev = []
    ph = ",".join("?" * sum(len(v) for v in SUBCAT.values()))
    ann = pd.read_sql(f"SELECT sid, date(dt_tm) AS d, subcategory, lower(headline) AS h FROM ({announcements.sql()}) a "
                      f"WHERE sid IS NOT NULL AND dt_tm IS NOT NULL AND (subcategory IN ({ph}) OR subcategory='Credit Rating')", con,
                      params=[x for v in SUBCAT.values() for x in v])
    for name, subs in SUBCAT.items():
        ev.append(ann[ann["subcategory"].isin(subs)].assign(event=name)[["sid", "d", "event"]])
    cr = ann[ann["subcategory"] == "Credit Rating"].assign(h=lambda x: x["h"].fillna(""))
    down = cr["h"].str.contains("downgrad") | (cr["h"].str.contains("negative") & ~cr["h"].str.contains("reaffirm"))
    ev.append(cr[down].assign(event="rating_downgrade")[["sid", "d", "event"]])
    ev.append(cr[cr["h"].str.contains("upgrad")].assign(event="rating_upgrade")[["sid", "d", "event"]])

    sh = pd.read_sql("SELECT sid, end_date, promoter_pct, pledge_pct FROM shareholding ORDER BY sid, end_date", con)
    sh["d_pledge"] = sh.groupby("sid")["pledge_pct"].diff()
    sh["d_prom"] = sh.groupby("sid")["promoter_pct"].diff()
    sh["d"] = (pd.to_datetime(sh["end_date"]) + pd.Timedelta(days=21)).dt.date.astype(str)
    ev.append(sh[sh["d_pledge"] >= 2].assign(event="pledge_rise")[["sid", "d", "event"]])
    ev.append(sh[sh["d_prom"] <= -2].assign(event="promoter_cut")[["sid", "d", "event"]])
    con2 = con
    ph = ",".join("?" * len(anchors))
    pan = pd.read_sql(f"SELECT sid, snapshot_date, announcement_car, delivery_anomaly_z FROM daily_snapshots_pit "
                      f"WHERE snapshot_date IN ({ph})", con2, params=list(anchors))
    con.close()

    events = pd.concat(ev, ignore_index=True).dropna()
    idx = np.searchsorted(anchors, events["d"].to_numpy(str), side="right")
    events = events[idx < len(anchors)].copy()
    events["snapshot_date"] = anchors[idx[idx < len(anchors)]]
    events = events.drop_duplicates(["sid", "snapshot_date", "event"])

    pan = pan.sort_values(["sid", "snapshot_date"])
    pan["car_prev"] = pan.groupby("sid")["announcement_car"].shift(1)
    shock = pan[(pan["announcement_car"] <= -0.08) & (pan["announcement_car"] != pan["car_prev"])]
    coll = pan[pan["delivery_anomaly_z"] <= -2]
    lab["crash_rank"] = lab.groupby(["snapshot_date", "cap_tier"])["prior_month_pct"].rank(pct=True)
    crash = lab[lab["crash_rank"] <= 0.05]
    events = pd.concat([events[["sid", "snapshot_date", "event"]],
                        shock[["sid", "snapshot_date"]].assign(event="results_shock"),
                        coll[["sid", "snapshot_date"]].assign(event="delivery_collapse"),
                        crash[["sid", "snapshot_date"]].assign(event="price_crash")], ignore_index=True)
    df = events.merge(lab, on=["sid", "snapshot_date"], how="inner")

    recs = []
    for (name, tier), x in list(df.groupby(["event", "cap_tier"])) + \
            [((n, "MID+SMALL"), x) for n, x in df[df["cap_tier"].isin(["MID", "SMALL"])].groupby("event")]:
        r = dict(event=name, tier=tier, n=len(x), anchors=x["snapshot_date"].nunique(),
                 prior_month_excess=round(float(x["x_prior_month"].mean()), 4))
        for h, step in ((63, 3), (126, 6)):
            y = x[x[f"x_fwd_{h}"].notna()]
            per = y.groupby("snapshot_date")[f"x_fwd_{h}"].mean()
            r.update({f"n_{h}": len(y), f"mean_{h}": round(float(y[f"x_fwd_{h}"].mean()), 4),
                      f"median_{h}": round(float(y[f"x_fwd_{h}"].median()), 4),
                      f"false_alarm_{h}": round(float((y[f"x_fwd_{h}"] > 0).mean()), 3),
                      f"t_{h}": round(nonoverlap_t(per, step), 2)})
        m, t, fa = r["mean_126"], r["t_126"], r["false_alarm_126"]
        r["grade"] = ("EXIT" if (m <= -0.05 and t <= -2.0 and fa <= 0.40)
                      else "REVIEW" if (m < 0 and t <= -1.5) else "NOISE")
        recs.append(r)
    res = pd.DataFrame(recs).sort_values(["tier", "mean_126"])
    res.to_csv(OUT / "monitor_events.csv", index=False)
    pd.set_option("display.width", 250)
    cols = ["event", "tier", "n", "prior_month_excess", "mean_63", "t_63", "n_126", "mean_126", "median_126",
            "false_alarm_126", "t_126", "grade"]
    for tier in ("MID+SMALL", "SMALL", "MID", "LARGE"):
        print(f"\n== {tier}")
        print(res[res["tier"] == tier][cols].to_string(index=False))
    return res


if __name__ == "__main__":
    run()
