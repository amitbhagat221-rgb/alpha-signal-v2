"""Compute the real numbers for the macro mockup (read-only DB)."""
import json, sqlite3, math
from collections import defaultdict
import pandas as pd, numpy as np

R = "file:/home/ubuntu/alpha-signal-v2/data/alpha_signal.db?mode=ro"
con = sqlite3.connect(R, uri=True)
mh = pd.read_sql("select indicator_id, date, value from macro_history", con, parse_dates=["date"])
S = {k: g.set_index("date")["value"].sort_index() for k, g in mh.groupby("indicator_id")}
out = {}

def yoy_monthly(s):
    s = s.resample("MS").last().dropna()
    return (s / s.shift(12) - 1) * 100

# ── India quadrant: growth = IIP YoY (3m avg) trend, inflation = CPI YoY trend ──
iip = yoy_monthly(S["iip_general"]).rolling(3).mean().dropna()
cpi_new = yoy_monthly(S["cpi_general"]).dropna()
cpi_old = yoy_monthly(S["india_cpi_index"]).dropna()
cpi = pd.concat([cpi_old, cpi_new]).sort_index()
cpi = cpi[~cpi.index.duplicated(keep="last")]
out["iip_yoy3"] = {d.strftime("%Y-%m"): round(v, 2) for d, v in iip.items()}
out["cpi_yoy"] = {d.strftime("%Y-%m"): round(v, 2) for d, v in cpi.items()}
# direction = change over 3 months
def trail(series, months=9):
    s = series.dropna()
    return s
out["iip_last"] = (iip.index[-1].strftime("%Y-%m"), round(iip.iloc[-1], 2), round(iip.iloc[-1] - iip.iloc[-4], 2))
out["cpi_last"] = (cpi.index[-1].strftime("%Y-%m"), round(cpi.iloc[-1], 2), round(cpi.iloc[-1] - cpi.iloc[-4], 2) if len(cpi) > 4 else None)

# ── money rate, usdinr, us10y, brent, vix: level + 1m/3m change ──
def lvl(k, days=(1, 21, 63)):
    s = S[k].dropna()
    r = {"date": s.index[-1].strftime("%Y-%m-%d"), "value": round(float(s.iloc[-1]), 4)}
    for d in days:
        if len(s) > d:
            r[f"chg_{d}"] = round(float(s.iloc[-1] / s.iloc[-1 - d] - 1) * 100, 2)
    return r
for k in ["usdinr", "us_10y", "brent_crude", "gold", "copper", "india_vix", "nifty50", "india_money_rate", "silver", "aluminium"]:
    out[f"lvl_{k}"] = lvl(k)
out["money_rate_hist"] = {d.strftime("%Y-%m"): v for d, v in S["india_money_rate"].items()}
vix = S["india_vix"].dropna()
out["vix_pctile_3y"] = round(float((vix[-750:] < vix.iloc[-1]).mean() * 100), 1)

# ── pulse: daily movers, z = today's change / std of daily changes over 1y ──
daily = ["brent_crude", "usdinr", "us_10y", "gold", "silver", "copper", "aluminium", "india_vix", "nifty50", "bank_nifty",
         "nifty_auto", "nifty_energy", "nifty_fmcg", "nifty_infra", "nifty_it", "nifty_media", "nifty_metal", "nifty_pharma",
         "nifty_psubank", "nifty_realty"]
mv = []
for k in daily:
    s = S[k].dropna()
    s = s[s.index <= "2026-10-16"]
    ch = s.pct_change() * 100 if k != "us_10y" else s.diff() * 100   # us_10y in bps
    z = ch.iloc[-1] / ch.iloc[-260:-1].std()
    mv.append({"id": k, "date": s.index[-1].strftime("%Y-%m-%d"), "value": round(float(s.iloc[-1]), 2),
               "chg": round(float(ch.iloc[-1]), 2), "z": round(float(z), 2), "unit": "bps" if k == "us_10y" else "%"})
mv.sort(key=lambda r: -abs(r["z"]))
out["movers"] = mv

# monthly latest prints
mp = []
for k in ["iip_general", "iip_manufacturing", "iip_capital_goods", "iip_consumer_durables", "core_combined", "cpi_general",
          "cpi_food_beverages", "cpi_housing_fuel", "india_exports", "india_imports"]:
    y = yoy_monthly(S[k]).dropna()
    if len(y) >= 2:
        mp.append({"id": k, "month": y.index[-1].strftime("%Y-%m"), "yoy": round(float(y.iloc[-1]), 2), "prev": round(float(y.iloc[-2]), 2)})
out["monthly_prints"] = mp

# ── flows ──
f = pd.read_sql("select flow_date, category, net_value_cr from fii_dii_cash_flow", con, parse_dates=["flow_date"])
fp = f.pivot_table(index="flow_date", columns="category", values="net_value_cr").sort_index()
fp.columns = ["DII", "FII"] if list(fp.columns) == ["DII", "FII/FPI"] else fp.columns
out["flows_last"] = {"date": fp.index[-1].strftime("%Y-%m-%d"), **{c: round(float(fp[c].iloc[-1]), 0) for c in fp.columns}}
out["flows_20d"] = {c: round(float(fp[c].iloc[-20:].sum()), 0) for c in fp.columns}
out["flows_series"] = [{"d": d.strftime("%Y-%m-%d"), **{c: round(float(fp.loc[d, c]), 0) for c in fp.columns}} for d in fp.index[-60:]]

# ── FII index-futures positioning ──
pos = pd.read_sql("select trade_date, future_index_long l, future_index_short s from fii_dii_positioning where client_type='FII'",
                  con, parse_dates=["trade_date"]).set_index("trade_date").sort_index()
pos["long_pct"] = pos.l / (pos.l + pos.s) * 100
lp = pos["long_pct"]
out["fii_long_pct"] = {"date": lp.index[-1].strftime("%Y-%m-%d"), "value": round(float(lp.iloc[-1]), 1),
                       "pctile": round(float((lp < lp.iloc[-1]).mean() * 100), 1),
                       "min": round(float(lp.min()), 1), "max": round(float(lp.max()), 1), "median": round(float(lp.median()), 1),
                       "ago_20": round(float(lp.iloc[-21]), 1)}
out["fii_long_series"] = [{"d": d.strftime("%Y-%m-%d"), "v": round(float(v), 1)} for d, v in lp.iloc[-250:].items()]

# ── market-implied regime 2016→ : growth = copper/gold 6m change, inflation = brent YoY change vs 6m ago ──
m = pd.DataFrame({k: S[k].resample("ME").last() for k in ["copper", "gold", "brent_crude", "nifty50", "bank_nifty", "nifty_auto",
                  "nifty_energy", "nifty_fmcg", "nifty_infra", "nifty_it", "nifty_media", "nifty_metal", "nifty_pharma",
                  "nifty_psubank", "nifty_realty", "gold"]}).dropna()
m = m.loc[:, ~m.columns.duplicated()]
cg = (m.copper / m.gold)
growth_up = cg / cg.shift(6) - 1 > 0
brent_yoy = m.brent_crude / m.brent_crude.shift(12) - 1
infl_up = brent_yoy - brent_yoy.shift(3) > 0
reg = pd.Series(np.where(growth_up & ~infl_up, "Goldilocks", np.where(growth_up & infl_up, "Reflation",
                np.where(~growth_up & infl_up, "Stagflation", "Deflation"))), index=m.index)
reg = reg[brent_yoy.shift(3).notna() & cg.shift(6).notna()]
fwd = m.pct_change().shift(-1) * 100        # next-month return
sectors = ["bank_nifty", "nifty_auto", "nifty_energy", "nifty_fmcg", "nifty_infra", "nifty_it", "nifty_media", "nifty_metal",
           "nifty_pharma", "nifty_psubank", "nifty_realty", "gold"]
tbl = {}
for q in ["Goldilocks", "Reflation", "Stagflation", "Deflation"]:
    idx = reg[reg == q].index
    idx = [i for i in idx if i in fwd.index and not fwd.loc[i].isna().any()]
    row = {"n": len(idx), "nifty": round(float(fwd.loc[idx, "nifty50"].mean()), 2)}
    for s in sectors:
        rel = fwd.loc[idx, s] - fwd.loc[idx, "nifty50"]
        t = rel.mean() / (rel.std() / math.sqrt(len(rel))) if len(rel) > 2 else float("nan")
        row[s] = {"rel": round(float(rel.mean()), 2), "hit": round(float((rel > 0).mean() * 100), 0), "t": round(float(t), 2)}
    tbl[q] = row
out["regime_table"] = tbl
out["regime_now"] = {"date": reg.index[-1].strftime("%Y-%m"), "regime": reg.iloc[-1],
                     "trail": [(d.strftime("%Y-%m"), r) for d, r in reg.iloc[-12:].items()],
                     "cg_6m": round(float((cg / cg.shift(6) - 1).iloc[-1] * 100), 2),
                     "brent_yoy": round(float(brent_yoy.iloc[-1] * 100), 2), "brent_yoy_3m_ago": round(float(brent_yoy.iloc[-4] * 100), 2)}
out["regime_months_total"] = int(len(reg))

# ── reverse dial index from the 38 explainers ──
rows = con.execute("select sector, payload from sector_metadata where source='auto' and json_extract(payload,'$.explainer') is not null").fetchall()
rev = defaultdict(list); unmapped = defaultdict(list)
for ind, p in rows:
    for d in json.loads(p)["explainer"]["dials"]:
        rec = {"industry": ind, "direction": d["direction"], "weight": d["weight"], "name": d["name"], "rise_does": d["rise_does"]}
        (rev[d["indicator_id"]] if d.get("indicator_id") else unmapped[d["name"]]).append(rec)
out["reverse"] = {k: sorted(v, key=lambda r: -r["weight"]) for k, v in rev.items()}
out["unmapped_top"] = sorted(((k, len(v)) for k, v in unmapped.items()), key=lambda x: -x[1])[:25]

# ── news themes ──
th = pd.read_sql("select theme_id, title, updated_at, stands_now, what_changed, why_it_matters, gains, loses, what_to_watch from news_themes where status='active'", con)
out["themes"] = th.to_dict("records")

json.dump(out, open(__import__("pathlib").Path(__file__).parent / "data.json", "w"), default=str, indent=1)
print("iip_last", out["iip_last"], "cpi_last", out["cpi_last"])
print("money", out["lvl_india_money_rate"], "vix pct", out["vix_pctile_3y"])
print("flows", out["flows_last"], out["flows_20d"])
print("fii long", out["fii_long_pct"])
print("regime now", out["regime_now"]["regime"], out["regime_now"]["cg_6m"], out["regime_now"]["brent_yoy"], "n", out["regime_months_total"])
for q, r in tbl.items(): print(q, r["n"], r["nifty"], {s: (r[s]["rel"], r[s]["t"]) for s in ["bank_nifty", "nifty_it", "nifty_metal", "nifty_fmcg", "gold"]})
print("movers", [(m_["id"], m_["chg"], m_["z"]) for m_ in mv[:8]])
print("monthly", mp)
print("reverse ids", {k: len(v) for k, v in sorted(rev.items(), key=lambda x: -len(x[1]))})
print("unmapped", out["unmapped_top"][:12])
print("themes", [(t["theme_id"], t["updated_at"]) for t in out["themes"]])
for k in ["usdinr", "us_10y", "brent_crude", "gold", "copper"]: print(k, out[f"lvl_{k}"])
