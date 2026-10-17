"""v5.1 extras: AI build-out vs IT services baskets, event lines for DeepSeek and the Iran war phases, Brent 2026 (read-only)."""
import json, sqlite3
from pathlib import Path
import pandas as pd

con = sqlite3.connect("file:/home/ubuntu/alpha-signal-v2/data/alpha_signal.db?mode=ro", uri=True)
def px(tickers, start):
    q = ",".join("?" * len(tickers))
    df = pd.read_sql(f"select s.ticker, p.date, p.close from stock_prices p join stocks s on s.sid = p.sid where s.ticker in ({q}) and p.date >= ?",
                     con, params=tickers + [start], parse_dates=["date"])
    return df.pivot_table(index="date", columns="ticker", values="close").sort_index().ffill()
START = "2023-08-01"
BUILD = ["NETWEB", "CGPOWER", "DIXON", "KAYNES", "ABB", "POWERGRID"]   # Siemens dropped: 2025 demerger break in raw prices
ITS = ["TCS", "INFY", "HCLTECH", "WIPRO"]
b = px(BUILD, START); i = px(ITS, START)
mh = pd.read_sql("select indicator_id, date, value from macro_history where indicator_id in ('nifty50','nifty_it','brent_crude','india_vix')", con, parse_dates=["date"])
S = {k: g.set_index("date")["value"].sort_index() for k, g in mh.groupby("indicator_id")}
def ew(df):
    df = df.dropna(how="all"); r = df.pct_change()
    r = r.mask(r < -0.25, 0.0)   # bonus issues and splits in unadjusted prices (Power Grid 2023, Wipro 2024)
    r = r.mean(axis=1).fillna(0); return (1 + r).cumprod() * 100
bw = ew(b).resample("W-FRI").last(); iw = ew(i).resample("W-FRI").last()
n = S["nifty50"][S["nifty50"].index >= START]; nw = (n / n.iloc[0] * 100).resample("W-FRI").last()
out = {"basket_build": [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in bw.dropna().items()],
       "basket_it": [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in iw.dropna().items()],
       "basket_nifty": [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in nw.dropna().items()],
       "build_members": BUILD, "it_members": ITS, "basket_start": START}
out["basket_last"] = {"build": out["basket_build"][-1][1], "it": out["basket_it"][-1][1], "nifty": out["basket_nifty"][-1][1]}

def path(series, d, pre=5, post=30):
    idx = series.index; pos = idx.searchsorted(pd.Timestamp(d)); base = series.iloc[pos - 1]
    return idx[pos].strftime("%Y-%m-%d"), [round(float(series.iloc[pos + k] / base * 100), 2) for k in range(-pre, post + 1)]
evs = []
for name, d, ser in [("DeepSeek shock (Nifty IT)", "2025-01-27", "nifty_it"), ("Iran war begins", "2026-03-02", "nifty50"),
                     ("US campaign to reopen Hormuz", "2026-03-19", "nifty50"), ("Ceasefire announced", "2026-04-08", "nifty50"),
                     ("US–Iran MoU signed", "2026-06-17", "nifty50"), ("Truce collapses", "2026-07-07", "nifty50")]:
    dt, p = path(S[ser], d, post=min(30, len(S[ser][S[ser].index >= d]) - 1))
    p = p + [p[-1]] * (36 - len(p))
    evs.append({"name": name, "date": dt, "path": p, "day0": round(p[5] - 100, 2), "min10": round(min(p[5:16]) - 100, 2), "d30": round(p[-1] - 100, 2)})
out["events3"] = evs
br = S["brent_crude"][S["brent_crude"].index >= "2025-12-01"].resample("W-FRI").last().dropna()
out["brent_2026"] = [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in br.items()]
nf = S["nifty50"][S["nifty50"].index >= "2025-12-01"].resample("W-FRI").last().dropna()
out["nifty_2026"] = [[d.strftime("%Y-%m-%d"), round(float(v), 1)] for d, v in nf.items()]
Path(__file__).with_name("data3.json").write_text(json.dumps(out))
print("basket last", out["basket_last"], "members", {t: (b[t].first_valid_index().date() if t in b else None) for t in BUILD})
for e in evs: print(e["name"], e["date"], e["day0"], e["min10"], e["d30"])
