"""Alpha Signal v2 — 3-sigma vs 2-sigma short strangle on NIFTY weeklies — read-only, reuses tools.option_premium_backtest.

Question (Amit 2026-11-02): "we did a 2 sigma study, can you do a 3 sigma study on the option strategy".
The live rule (0.05 delta, two sessions before expiry) sits at about 2 sigma of the week's ATM IV, so the
2-sigma row below reproduces it (exp2 2.0: 19.3 %/yr, worst -3.7 %, vs the delta study's 19.5 % / -5.3 %).
Run: python -m tools.option_sigma_study   (read-only, ~25 s; study docs/studies/option-sigma-strikes-2026-11.md)

Strike rule: short call at the traded strike nearest F·exp(+N·σ·√T), short put nearest F·exp(−N·σ·√T),
σ = the chain's own ATM implied vol that day (mean of call+put IV at the strike nearest F).
Everything else (entry at settle, hold to expiry, costs, 12 % margin) is the pre-registered tool's.
"""
import sys
import numpy as np
import pandas as pd
import os; sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tools.option_premium_backtest as B
import option_book as ob
from sources.fno_iv import _implied_forward, _invert_iv

SIGMAS = (1.5, 2.0, 2.5, 3.0)
_atm = {}

def atm_sigma(day, t, e):
    key = (t, e)
    if key in _atm:
        return _atm[key]
    sl = day.get(key)
    T = ob.years(t, e)
    ce = sl[sl.option_type == "CE"].set_index("strike")["settle"]
    pe = sl[sl.option_type == "PE"].set_index("strike")["settle"]
    F, _ = _implied_forward(ce[ce > 0], pe[pe > 0], T)
    out = None
    if F is not None:
        ks = sl.strike.unique()
        k = float(ks[np.abs(ks - F).argmin()])
        ivs = []
        for o, cp in (("CE", "C"), ("PE", "P")):
            r = sl[(sl.strike == k) & (sl.option_type == o) & (sl.settle > 0)]
            if not r.empty:
                iv = _invert_iv(float(r.settle.iloc[0]), F, k, T, cp)
                if np.isfinite(iv) and iv > 0:
                    ivs.append(iv)
        if ivs:
            out = (F, float(np.mean(ivs)), T)
    _atm[key] = out
    return out

def pick_sigma(day, t, expiry, n):
    a = atm_sigma(day, t, expiry)
    if a is None:
        return None
    F, iv, T = a
    s = iv * np.sqrt(T)
    sl = day.get((t, expiry))
    traded = sl[(sl.volume > 0) & (sl.settle > 0)]
    calls = traded[(traded.option_type == "CE") & (traded.strike > F)].strike.values
    puts = traded[(traded.option_type == "PE") & (traded.strike < F)].strike.values
    if len(calls) == 0 or len(puts) == 0:
        return None
    kc, kp = F * np.exp(n * s), F * np.exp(-n * s)
    best = {"C": float(calls[np.abs(calls - kc).argmin()]), "P": float(puts[np.abs(puts - kp).argmin()])}
    # record how far the chosen strike really is, in sigmas
    best["_zC"], best["_zP"] = np.log(best["C"] / F) / s, np.log(F / best["P"]) / s
    best["_iv"] = iv
    return F, best, day.prices(t, expiry)[0]

B.pick_strikes = pick_sigma           # the tool's one_trade calls pick_strikes(day, t, expiry, target)
B.DELTAS = SIGMAS                     # "delta" column now holds the sigma multiple
B.HOLDS = ("exp1", "exp2", "exp3")
B.STRUCTURES = ("strangle",)

# wrap one_trade so the realised sigma distance and the rupee credit per lot ride along
_one = B.one_trade
def one_trade(chain_by_day, days, t, t_exit, expiry, target, structure, slip, vix):
    r = _one(chain_by_day, days, t, t_exit, expiry, target, structure, slip, vix)
    if r is None:
        return None
    _, best, _ = pick_sigma(chain_by_day, t, expiry, target)
    r["zC"], r["zP"], r["atm_iv"] = best["_zC"], best["_zP"], best["_iv"]
    r["lot"] = B.lot_size(t)
    r["credit_rs_lot"] = r["credit"] * r["lot"]
    r["net_rs_lot"] = r["net"] * r["lot"]
    r["dist_c%"] = 100 * (r["short_call"] / r["F"] - 1)
    r["dist_p%"] = 100 * (1 - r["short_put"] / r["F"])
    return r
B.one_trade = one_trade

pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_rows", 300)
chain, vix = B.load_chain(), B.load_vix()
day = B.Chain(chain)
start = B.REGIME_START
res, trades = B.run(chain, day, vix, ob.STT_SELL, ob.SLIP, start)
res = res.rename(columns={"delta": "sigma"})
extra = trades.groupby(["hold", "delta"]).agg(zC=("zC", "median"), zP=("zP", "median"),
        atm_iv=("atm_iv", "median"), dist_c=("dist_c%", "median"), dist_p=("dist_p%", "median"),
        credit_rs_lot=("credit_rs_lot", "median"), worst_rs_lot=("net_rs_lot", "min"),
        mean_rs_lot=("net_rs_lot", "mean")).reset_index().rename(columns={"delta": "sigma"})
print(f"\nNIFTY short strangle by SIGMA multiple of ATM IV · entries {start} → 2026-10 · costs + 12 % margin as the tool")
print(res.round(2).to_string(index=False))
print("\nrealised strike distance (median sigmas / % from forward), credit and P&L in rupees per lot")
print(extra.round(2).to_string(index=False))

# where did the losses come from? the ten worst trades at 2 and 3 sigma, exp2
for n in (2.0, 3.0):
    t = trades[(trades.hold == "exp2") & (trades.delta == n)].sort_values("ret").head(6)
    print(f"\nexp2 {n}σ — six worst trades")
    print(t[["entry", "expiry", "F", "S_exit", "short_call", "short_put", "credit", "net", "ret", "vix"]].round(3).to_string(index=False))

# stress model 2015 → 2026 with the tool's own calibration (strike distance + credit in VIX·√T units)
cal = B.calibrate(trades)
idx = B.load_index()
print("\ncalibration (strike distance and credit in units of VIX·√T)")
print(cal.round(3).to_string())
oos = B.stress(idx, cal, idx.date.min(), start)
print(f"\nSTRESS model on NIFTY + VIX, every entry day {idx.date.min()} → {start} (out of sample; 'delta' = sigma)")
print(B.stress_summary(oos).round(2).to_string(index=False))
# by year, exp2, 2σ vs 3σ
o = oos[oos.hold == "exp2"].copy()
o["year"] = o.entry.str[:4]
yr = o.groupby(["delta", "year"])["ret"].agg(mean="mean", worst="min", n="size").reset_index()
yr["ann%"] = 100 * 50 * yr["mean"]
yr["worst%"] = 100 * yr["worst"]
print("\nexp2 by year, model (ann% = mean × 50, worst% = worst entry day)")
print(yr.pivot(index="year", columns="delta", values=["ann%", "worst%"]).round(1).to_string())
import pathlib; trades.to_csv(pathlib.Path("output") / "option_sigma_trades.csv", index=False)
