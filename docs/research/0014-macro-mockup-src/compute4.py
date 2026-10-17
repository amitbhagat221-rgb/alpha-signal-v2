"""Dated brief snapshots for the date filter (read-only). Each snapshot uses only data dated on or before the snapshot date;
the regime uses only releases already published by then (IIP about 28 days after month-end, CPI about 12 days)."""
import json, sqlite3
from pathlib import Path
import pandas as pd

con = sqlite3.connect("file:/home/ubuntu/alpha-signal-v2/data/alpha_signal.db?mode=ro", uri=True)
mh = pd.read_sql("select indicator_id, date, value from macro_history", con, parse_dates=["date"])
S = {k: g.set_index("date")["value"].sort_index() for k, g in mh.groupby("indicator_id")}
fl = pd.read_sql("select flow_date, category, net_value_cr from fii_dii_cash_flow", con, parse_dates=["flow_date"])
fp = fl.pivot_table(index="flow_date", columns="category", values="net_value_cr").sort_index()
fp = fp.rename(columns={"FII/FPI": "FII"})
pos = pd.read_sql("select trade_date, future_index_long l, future_index_short s from fii_dii_positioning where client_type='FII'", con, parse_dates=["trade_date"]).set_index("trade_date").sort_index()
ls = pos.l / (pos.l + pos.s) * 100
th = pd.read_sql("select theme_id, as_of, stands_now, what_changed from news_theme_history", con)
titles = dict(con.execute("select theme_id, title from news_themes").fetchall())

def asof(s, d): s = s[s.index <= d]; return s
def yoy_avail(k, d, lag_days):
    s = S[k].resample("MS").last().dropna()
    y = (s / s.shift(12) - 1) * 100
    ok = [m for m in y.dropna().index if (m + pd.offsets.MonthBegin(1) + pd.Timedelta(days=lag_days)) <= d]
    return y.loc[ok]

DATES = ["2026-09-06", "2026-09-10", "2026-09-17", "2026-09-24", "2026-10-01", "2026-10-05", "2026-10-12", "2026-10-16"]
RBI = {"2026-09-06": ("amber", "On hold, draining surplus cash"), "2026-09-10": ("amber", "On hold, draining surplus cash"),
       "2026-09-17": ("amber", "On hold"), "2026-09-24": ("amber", "On hold"), "2026-10-01": ("amber", "On hold; meeting next week"),
       "2026-10-05": ("amber", "Meeting today; first hike in years expected"), "2026-10-12": ("red", "Hiked; signalled more tightening"),
       "2026-10-16": ("red", "Hiked; another rise likely")}
snaps = []
for ds in DATES:
    d = pd.Timestamp(ds)
    b = asof(S["brent_crude"], d); b3 = (b.iloc[-1] / b.iloc[-64] - 1) * 100          # 63 observations back, same window as the brief
    u = asof(S["us_10y"], d); u3 = (u.iloc[-1] - u.iloc[-64]) * 100
    r = asof(S["usdinr"], d); v = asof(S["india_vix"], d)
    f = fp[fp.index <= d].iloc[-20:]
    l = ls[ls.index <= d]; lp = float(l.iloc[-1]); pct = float((l < lp).mean() * 100)
    iip = yoy_avail("iip_general", d, 27).rolling(3).mean().dropna(); cpi_n = yoy_avail("cpi_general", d, 11)
    gx = float(iip.iloc[-1] - iip.iloc[-4]); gy = float(cpi_n.iloc[-1] - cpi_n.iloc[-4]) if len(cpi_n) >= 4 else None
    quad = None if gy is None else (("Reflation" if gy > 0 else "Goldilocks") if gx > 0 else ("Stagflation" if gy > 0 else "Deflation"))
    bl = float(b.iloc[-1])
    oil_c = "red" if (bl > 100 or b3 > 25) else "amber" if (bl > 85 or b3 > 10) else "green"   # level or speed: the level is the tax
    us_c = "red" if u.iloc[-1] > 5 else "amber" if u.iloc[-1] > 4.5 else "green"
    fii20, dii20 = float(f["FII"].sum()), float(f["DII"].sum())
    fl_c = "red" if fii20 < -50000 else "amber" if fii20 < -20000 else "green"
    note_date = max(a for a in th.as_of.unique() if a <= ds)
    notes = [{"theme": titles.get(t.theme_id, t.theme_id), "now": t.stands_now, "changed": t.what_changed} for t in th[th.as_of == note_date].itertuples()]
    snaps.append({"date": ds, "brent": round(float(b.iloc[-1]), 2), "brent_3m": round(float(b3), 1), "oil": oil_c,
                  "us10y": round(float(u.iloc[-1]), 2), "us_3m_bps": round(float(u3), 0), "us": us_c,
                  "usdinr": round(float(r.iloc[-1]), 2), "vix": round(float(v.iloc[-1]), 1),
                  "fii20": round(fii20), "dii20": round(dii20), "flows": fl_c, "fii_long": round(lp, 1), "fii_long_pct": round(pct),
                  "rbi": RBI[ds][0], "rbi_text": RBI[ds][1], "regime": quad, "regime_month": iip.index[-1].strftime("%Y-%m"),
                  "nifty": round(float(asof(S["nifty50"], d).iloc[-1]), 1), "notes": notes, "note_date": note_date})
Path(__file__).with_name("data4.json").write_text(json.dumps(snaps))
for s in snaps:
    print(s["date"], "oil", s["oil"], s["brent"], s["brent_3m"], "| us", s["us"], s["us10y"], "| flows", s["flows"], s["fii20"], s["dii20"], "| rbi", s["rbi"], "| regime", s["regime"], s["regime_month"], "| notes", len(s["notes"]))
