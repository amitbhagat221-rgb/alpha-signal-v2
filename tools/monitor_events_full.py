"""
Plan 0025 task 4.1 rerun on the FULL market (delisted and non-universe NSE names included).
(READ-ONLY on the DB; needs data/lh/v2/pricehist_panel.parquet from tools.lh_price_history)

PRE-REGISTRATION (2026-10-13, before any result): the same events, grades and false-alarm
definition as tools.monitor_events, but outcomes come from the full-market price panel
(T1/T2/T3 liquidity groups, 126-session label with delisting returns kept) and events are mapped to
NSE names through stocks.sid (universe) or scrip_master.nse_symbol (everything else, "U:<symbol>").
BSE-only companies (no NSE symbol) are out of scope: an NSE investor could not hold them.
Events: auditor / CFO / CEO-MD / director resignations and rating downgrades (BSE, 2018+).
Each event is assigned to the first anchor strictly after its date.
Reported per event, pooled T2+T3 and by universe membership: n, median excess vs the group median,
false-alarm rate, non-overlap t (every 6th anchor), share that stopped trading within 126 sessions
vs all names. Grades as tools.monitor_events (EXIT / REVIEW / NOISE).

Usage: python -m tools.monitor_events_full
"""

import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from tools.monitor_events import SUBCAT, nonoverlap_t  # noqa: E402

DB = PROJECT_ROOT / "data" / "alpha_signal.db"
V2 = PROJECT_ROOT / "data" / "lh" / "v2"


def main():
    df = pd.read_parquet(V2 / "pricehist_panel.parquet")
    df["ex"] = df["fwd"] - df.groupby(["anchor", "group"])["fwd"].transform("median")
    anchors = np.array(sorted(df["anchor"].unique()))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    subs = [x for v in SUBCAT.values() for x in v]
    ann = pd.read_sql("SELECT a.sid, a.scrip_cd, date(a.dt_tm) AS d, a.subcategory, lower(coalesce(a.headline,'')) AS h, "
                      "sm.nse_symbol FROM bse_announcements a LEFT JOIN scrip_master sm ON sm.scrip_cd = a.scrip_cd "
                      "WHERE a.dt_tm IS NOT NULL AND (a.subcategory IN (%s) OR a.subcategory = 'Credit Rating')"
                      % ",".join("?" * len(subs)), con, params=subs)
    con.close()
    ann["id"] = np.where(ann["sid"].notna(), ann["sid"], "U:" + ann["nse_symbol"].fillna(""))
    ann = ann[ann["id"] != "U:"]
    ev = []
    for name, sub in SUBCAT.items():
        ev.append(ann[ann["subcategory"].isin(sub)].assign(event=name))
    cr = ann[ann["subcategory"] == "Credit Rating"]
    down = cr["h"].str.contains("downgrad") | (cr["h"].str.contains("negative") & ~cr["h"].str.contains("reaffirm"))
    ev.append(cr[down].assign(event="rating_downgrade"))
    ev = pd.concat(ev)[["id", "d", "event"]]
    idx = np.searchsorted(anchors, ev["d"].to_numpy(str), side="right")
    ev = ev[idx < len(anchors)].assign(anchor=anchors[idx[idx < len(anchors)]]).drop_duplicates(["id", "anchor", "event"])
    x = ev.merge(df, on=["id", "anchor"], how="inner")
    base_stop = df.loc[df["group"].isin(["T2", "T3"]), "stopped"].mean()
    recs = []
    for scope, sub in (("all names", x), ("universe", x[x["survivor"]]), ("delisted/outside", x[~x["survivor"]])):
        sub = sub[sub["group"].isin(["T2", "T3"])]
        for name, g in sub.groupby("event"):
            per = g.groupby("anchor")["ex"].mean()
            t = nonoverlap_t(per, 6)
            m, fa = g["ex"].mean(), (g["ex"] > 0).mean()
            recs.append(dict(scope=scope, event=name, n=len(g), median_ex=round(g["ex"].median(), 4),
                             mean_ex=round(m, 4), false_alarm=round(fa, 3), t_no=round(t, 2),
                             stopped=round(g["stopped"].mean(), 3), stopped_base=round(base_stop, 3),
                             grade=("EXIT" if (m <= -0.05 and t <= -2.0 and fa <= 0.40) else
                                    "REVIEW" if (m < 0 and t <= -1.5) else "NOISE")))
    out = pd.DataFrame(recs)
    out.to_csv(V2 / "monitor_full.csv", index=False)
    pd.set_option("display.width", 220)
    print(out.to_string(index=False))


if __name__ == "__main__":
    main()
