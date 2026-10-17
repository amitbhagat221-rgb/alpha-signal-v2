"""Extra computations for mockup v5: long histories, episodes, event studies, playbooks (read-only DB)."""
import json, math, sqlite3
from pathlib import Path
import numpy as np, pandas as pd

R = "file:/home/ubuntu/alpha-signal-v2/data/alpha_signal.db?mode=ro"
con = sqlite3.connect(R, uri=True)
mh = pd.read_sql("select indicator_id, date, value from macro_history", con, parse_dates=["date"])
S = {k: g.set_index("date")["value"].sort_index().dropna() for k, g in mh.groupby("indicator_id")}
S = {k: v[~v.index.duplicated(keep="last")] for k, v in S.items()}
out = {}

def weekly(k, start="2015-07-01"):
    s = S[k][S[k].index >= start].resample("W-FRI").last().dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in s.items()]

for k in ["nifty50", "brent_crude", "usdinr", "us_10y", "india_vix", "gold", "copper", "nifty_metal", "nifty_it", "bank_nifty"]:
    out[f"w_{k}"] = weekly(k)

# copper / gold weekly
cg = (S["copper"] / S["gold"]).dropna()
cg = cg[cg.index >= "2015-07-01"].resample("W-FRI").last().dropna()
out["w_cg"] = [[d.strftime("%Y-%m-%d"), round(float(v) * 1000, 4)] for d, v in cg.items()]

# gold in rupees, indexed, vs nifty indexed (weekly)
gi = (S["gold"] * S["usdinr"]).dropna(); gi = gi[gi.index >= "2015-07-01"].resample("W-FRI").last().dropna()
ni = S["nifty50"][S["nifty50"].index >= "2015-07-01"].resample("W-FRI").last().dropna()
j = pd.concat([gi / gi.iloc[0] * 100, ni / ni.iloc[0] * 100], axis=1, keys=["gold_inr", "nifty"]).dropna()
out["w_gold_vs_nifty"] = [[d.strftime("%Y-%m-%d"), round(float(r.gold_inr), 1), round(float(r.nifty), 1)] for d, r in j.iterrows()]

# nifty drawdown (weekly)
dd = (ni / ni.cummax() - 1) * 100
out["w_drawdown"] = [[d.strftime("%Y-%m-%d"), round(float(v), 2)] for d, v in dd.items()]

# monthly macro since 2022
def mser(k):
    s = S[k].resample("MS").last().dropna()
    return [[d.strftime("%Y-%m"), round(float(v), 3)] for d, v in s.items()]
for k in ["india_money_rate", "iip_general", "iip_capital_goods", "iip_consumer_durables", "iip_manufacturing", "cpi_general", "india_cpi_index", "cpi_food_beverages", "india_exports", "india_imports"]:
    out[f"m_{k}"] = mser(k)
def yoy(k):
    s = S[k].resample("MS").last().dropna(); y = (s / s.shift(12) - 1) * 100
    return {d.strftime("%Y-%m"): round(float(v), 2) for d, v in y.dropna().items()}
out["yoy"] = {k: yoy(k) for k in ["iip_general", "iip_capital_goods", "iip_consumer_durables", "iip_manufacturing", "cpi_general", "india_cpi_index", "cpi_food_beverages", "india_exports", "india_imports"]}

# ── episodes (windows) with computed stats ──
EPIS = [
    ("2015-16", "China's yuan devaluation and the commodity rout", "2015-08-01", "2016-02-29"),
    ("2016", "Demonetisation", "2016-11-01", "2016-12-31"),
    ("2018", "Oil, a falling rupee and IL&FS", "2018-01-01", "2018-10-31"),
    ("2020", "Covid crash", "2020-01-15", "2020-04-30"),
    ("2022", "Ukraine war, oil and the Fed", "2022-01-01", "2022-06-30"),
    ("2024", "Election result and the yen carry unwind", "2024-05-25", "2024-08-31"),
    ("2026", "The Iran war and the oil shock", "2026-02-27", "2026-10-16"),
]
def win_stats(a, b):
    def rng(k):
        s = S[k][(S[k].index >= a) & (S[k].index <= b)]
        return s
    n = rng("nifty50"); mdd = float(((n / n.cummax()) - 1).min() * 100) if len(n) else None
    def chg(k, bps=False):
        s = rng(k)
        if len(s) < 2: return None
        return round(float((s.iloc[-1] - s.iloc[0]) * 100), 0) if bps else round(float(s.iloc[-1] / s.iloc[0] - 1) * 100, 1)
    vix = rng("india_vix")
    return {"nifty_mdd": round(mdd, 1) if mdd is not None else None, "nifty_chg": chg("nifty50"), "brent_chg": chg("brent_crude"),
            "usdinr_chg": chg("usdinr"), "us10y_bps": chg("us_10y", bps=True), "vix_peak": round(float(vix.max()), 1) if len(vix) else None}
out["episodes"] = [{"label": l, "name": nm, "start": a, "end": b, **win_stats(a, b)} for l, nm, a, b in EPIS]

# ── event study: nifty indexed to 100 on the day before the event, -5 .. +30 trading days ──
EVENTS = [
    ("geo", "Surgical strikes", "2016-09-29"), ("geo", "Pulwama attack", "2019-02-14"), ("geo", "Balakot strike", "2019-02-26"),
    ("geo", "Galwan clash", "2020-06-15"), ("geo", "Pahalgam attack", "2025-04-22"), ("geo", "Operation Sindoor", "2025-05-07"),
    ("glob", "Yuan devaluation", "2015-08-11"), ("glob", "Brexit vote", "2016-06-24"), ("glob", "Abqaiq attack", "2019-09-16"),
    ("glob", "Russia invades Ukraine", "2022-02-24"), ("glob", "Hamas attack on Israel", "2023-10-09"), ("glob", "Yen carry unwind", "2024-08-05"),
    ("dom", "Demonetisation", "2016-11-09"), ("dom", "IL&FS default", "2018-09-21"), ("dom", "Covid lockdown", "2020-03-24"), ("dom", "Election result", "2024-06-04"),
]
nifty = S["nifty50"]; vix = S["india_vix"]; brent = S["brent_crude"]
ev_out = []
for kind, name, d in EVENTS:
    d = pd.Timestamp(d)
    idx = nifty.index
    pos = idx.searchsorted(d)
    if pos <= 5 or pos + 30 >= len(idx): continue
    base = nifty.iloc[pos - 1]
    path = [round(float(nifty.iloc[pos + k] / base * 100), 2) for k in range(-5, 31)]
    vpos = vix.index.searchsorted(d)
    bpos = brent.index.searchsorted(d)
    ev_out.append({"kind": kind, "name": name, "date": idx[pos].strftime("%Y-%m-%d"), "path": path,
                   "day0": round(path[5] - 100, 2), "min10": round(min(path[5:16]) - 100, 2), "d30": round(path[-1] - 100, 2),
                   "vix_chg": round(float(vix.iloc[vpos] / vix.iloc[vpos - 1] - 1) * 100, 1) if 0 < vpos < len(vix) else None,
                   "brent_5d": round(float(brent.iloc[min(bpos + 5, len(brent) - 1)] / brent.iloc[bpos - 1] - 1) * 100, 1) if 0 < bpos < len(brent) else None})
out["events"] = ev_out

# ── oil-shock playbook: months where Brent rose > 25% over 3 months; sector relative returns over that window ──
mm = pd.DataFrame({k: S[k].resample("ME").last() for k in ["brent_crude", "nifty50", "bank_nifty", "nifty_auto", "nifty_energy", "nifty_fmcg",
                   "nifty_infra", "nifty_it", "nifty_media", "nifty_metal", "nifty_pharma", "nifty_psubank", "nifty_realty", "gold", "usdinr"]}).dropna()
r3 = mm / mm.shift(3) - 1
shock = r3["brent_crude"] > 0.25
rows = {}
for k in mm.columns:
    if k in ("brent_crude", "nifty50"): continue
    rel = (r3[k] - r3["nifty50"])[shock].dropna() * 100
    rest = (r3[k] - r3["nifty50"])[~shock].dropna() * 100
    rows[k] = {"rel": round(float(rel.mean()), 2), "n": int(len(rel)), "rest": round(float(rest.mean()), 2),
               "t": round(float(rel.mean() / (rel.std() / math.sqrt(len(rel)))), 2) if len(rel) > 2 else None}
out["oil_playbook"] = {"months": [d.strftime("%Y-%m") for d in shock[shock].index], "rows": rows,
                       "nifty_rel_window": round(float(r3["nifty50"][shock].mean() * 100), 2)}

# ── US 10y shock playbook: 3-month rise > 75 bps ──
u = S["us_10y"].resample("ME").last()
mm2 = mm.join(u.rename("us10y"), how="inner")
du = (mm2["us10y"] - mm2["us10y"].shift(3)) * 100
ushock = du > 75
rows2 = {}
for k in ["bank_nifty", "nifty_it", "nifty_fmcg", "nifty_metal", "nifty_pharma", "nifty_realty", "nifty_energy", "gold"]:
    rel = ((mm2[k] / mm2[k].shift(3) - 1) - (mm2["nifty50"] / mm2["nifty50"].shift(3) - 1))[ushock].dropna() * 100
    rows2[k] = {"rel": round(float(rel.mean()), 2), "n": int(len(rel)), "t": round(float(rel.mean() / (rel.std() / math.sqrt(len(rel)))), 2) if len(rel) > 2 else None}
nifty3 = (mm2["nifty50"] / mm2["nifty50"].shift(3) - 1)[ushock].dropna() * 100
usd3 = (mm2["usdinr"] / mm2["usdinr"].shift(3) - 1)[ushock].dropna() * 100
out["us_playbook"] = {"months": [d.strftime("%Y-%m") for d in ushock[ushock].index], "rows": rows2,
                      "nifty_abs": round(float(nifty3.mean()), 2), "usdinr": round(float(usd3.mean()), 2)}

# ── FII positioning: forward 20-session Nifty return by long-share bucket ──
pos = pd.read_sql("select trade_date, future_index_long l, future_index_short s from fii_dii_positioning where client_type='FII'",
                  con, parse_dates=["trade_date"]).set_index("trade_date").sort_index()
ls = (pos.l / (pos.l + pos.s) * 100)
ndaily = S["nifty50"]
fwd = (ndaily.shift(-20) / ndaily - 1) * 100
jj = pd.concat([ls.rename("ls"), fwd.rename("fwd")], axis=1).dropna()
q15 = jj.ls.quantile(0.15); q85 = jj.ls.quantile(0.85)
def bucket(mask):
    x = jj.fwd[mask]
    return {"n": int(len(x)), "mean": round(float(x.mean()), 2), "hit": round(float((x > 0).mean() * 100), 0)}
out["pos_buckets"] = {"q15": round(float(q15), 1), "q85": round(float(q85), 1), "low": bucket(jj.ls <= q15), "mid": bucket((jj.ls > q15) & (jj.ls < q85)), "high": bucket(jj.ls >= q85)}
lw = ls.resample("W-FRI").last().dropna()
out["w_fii_long"] = [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in lw.items()]
nw = ndaily[ndaily.index >= lw.index[0]].resample("W-FRI").last().dropna()
out["w_nifty_pos"] = [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in nw.items()]

# ── records and levels ──
def rec(k):
    s = S[k]; return {"max": round(float(s.max()), 2), "max_date": s.idxmax().strftime("%Y-%m-%d"), "min": round(float(s.min()), 2), "min_date": s.idxmin().strftime("%Y-%m-%d"), "last": round(float(s.iloc[-1]), 2)}
out["records"] = {k: rec(k) for k in ["brent_crude", "usdinr", "us_10y", "india_vix", "nifty50", "gold"]}
out["usdinr_2015"] = round(float(S["usdinr"][S["usdinr"].index >= "2015-07-01"].iloc[0]), 2)

Path(__file__).with_name("data2.json").write_text(json.dumps(out, default=str))
print("episodes:"); [print(" ", e) for e in out["episodes"]]
print("events:"); [print(" ", e["kind"], e["name"], e["date"], "d0", e["day0"], "min10", e["min10"], "d30", e["d30"], "vix", e["vix_chg"], "brent5", e["brent_5d"]) for e in ev_out]
print("oil playbook months", out["oil_playbook"]["months"]); print({k: (v["rel"], v["t"], v["n"]) for k, v in rows.items()})
print("us playbook months", out["us_playbook"]["months"], out["us_playbook"]["nifty_abs"], out["us_playbook"]["usdinr"]); print({k: (v["rel"], v["t"]) for k, v in rows2.items()})
print("pos buckets", out["pos_buckets"])
print("records", out["records"], "usdinr 2015", out["usdinr_2015"])
