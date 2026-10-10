"""
Alpha Signal v2 — plan 0023: do dynamic option setups beat the static rule?

Read-only. Builds the setup table (every entry day × legs at call/put delta 0.03/0.05/0.07,
held to expiry, after costs — the plan 0022 engine), the PIT market reading
(option_state.readings), applies the six pre-registered rules and scores each against
the static rule on TRAIN, TEST and SENSEX, with the plan's pass bar.

Everything here was fixed in docs/plans/0023-dynamic-option-setups.md before a result
was computed. Do not tune it on the output.

    python -m tools.option_dynamic_study            # the full report
    python -m tools.option_dynamic_study --table out.csv
"""

import argparse

import numpy as np
import pandas as pd

import option_book as ob
import option_state
import tools.option_premium_backtest as bt

TRAIN = ("2019-02-11", "2024-11-19")
TEST = ("2024-11-20", "9999")
SENSEX_FROM = "2024-01-05"
T_BAR = 2.4                     # one-sided 5% after Bonferroni for 6 hypotheses
SHUFFLES = 1000
DELTAS = (0.03, 0.05, 0.07)

SETUPS = {                      # (call leg, put leg, size)
    "STD": ("C05", "P05", 1.0), "SKIP": (None, None, 0.0), "HALF": ("C05", "P05", 0.5),
    "PUT_FAR": ("C07", "P03", 1.0), "CALL_FAR": ("C03", "P07", 1.0),
}


def legs(underlying, start):
    """Entry day × leg net P&L (points per unit) for every exp2 entry from `start`."""
    bt.UNDERLYING = underlying
    chain = bt.load_chain()
    _, sched = bt.schedule(chain, "exp2")
    ch = bt.Chain(chain)
    rows = []
    for t, _, e in sched:
        if t < start or ch.get((t, e)) is None or ch.get((e, e)) is None:
            continue
        d = ch.deltas(t, e)
        if d is None:
            continue
        F, deltas = d
        px, S = ch.prices(t, e)[0], ch.prices(e, e)[1]
        lot = bt.lot_size(t)
        row = {"entry": t, "expiry": e, "F": F, "margin": ob.MARGIN_STRANGLE_PCT * F}
        for cp in ("C", "P"):
            for tgt in DELTAS:
                K = min((abs(dl - tgt), k) for dl, k in deltas[cp])[1]
                p = px[(cp, K)]
                row[f"{cp}{round(tgt * 100):02d}"] = p - ob.intrinsic(cp, K, S) - ob.leg_cost(p, "sell", lot, ob.SLIP, t)
        rows.append(row)
    return pd.DataFrame(rows)


def setup_returns(tab):
    out = pd.DataFrame(index=tab.index)
    for name, (c, p, size) in SETUPS.items():
        out[name] = 0.0 if size == 0 else size * (tab[c] + tab[p]) / tab["margin"]
    return out


# ── the six pre-registered rules (plan 0023 §3): reading row → setup ──

def h1_premium(r):
    return "SKIP" if r.vrp <= 0 else "STD"


def h2_trend(r):
    return "PUT_FAR" if r.r5_pct <= 0.20 else "CALL_FAR" if r.r5_pct >= 0.80 else "STD"


def h3_skew(r):
    return "CALL_FAR" if r.skew_pct >= 0.80 else "PUT_FAR" if r.skew_pct <= 0.20 else "STD"


def h4_stress(r):
    return "SKIP" if r.term > 0 else "STD"


def h5_positioning(r):
    return "HALF" if (r.pcr_pct < 0.10 or r.pcr_pct > 0.90) else "STD"


def h6_macro(r):
    return "HALF" if (r.usd5_pct > 0.90 or r.oil5_pct > 0.90) else "STD"


RULES = {"H1 premium": h1_premium, "H2 trend": h2_trend, "H3 skew": h3_skew,
         "H4 stress": h4_stress, "H5 positioning": h5_positioning, "H6 macro": h6_macro}


def choose(rule, state):
    """Setup per row; a reading that is missing (NaN) keeps the static setup."""
    out = []
    for r in state.itertuples():
        try:
            pick = rule(r)
        except TypeError:
            pick = "STD"
        out.append(pick)
    return pd.Series(out, index=state.index)


def _maxdd(r):
    c = r.cumsum()
    return (c - c.cummax()).min()


def score(rets, picks, seed=0):
    """Policy vs STD on one window: the plan's numbers."""
    pol = pd.Series([rets.at[i, p] for i, p in picks.items()], index=picks.index)
    std = rets["STD"]
    diff = pol - std
    n = len(diff)
    t = diff.mean() / diff.std(ddof=1) * np.sqrt(n) if n > 1 and diff.std(ddof=1) > 0 else np.nan
    rng = np.random.default_rng(seed)
    obs, beat = diff.mean(), 0
    mat, col = rets.values, np.array([rets.columns.get_loc(p) for p in picks.values])
    rows = np.arange(n)
    for _ in range(SHUFFLES):             # the same choices, dealt to random weeks
        beat += (mat[rows, rng.permutation(col)] - std.values).mean() >= obs
    return {"n": n, "changed": int((picks != "STD").sum()), "diff_mean%": 100 * diff.mean(), "t": t,
            "pol_ann%": 100 * 50 * pol.mean(), "std_ann%": 100 * 50 * std.mean(),
            "pol_worst%": 100 * pol.min(), "std_worst%": 100 * std.min(),
            "pol_maxDD%": 100 * _maxdd(pol), "std_maxDD%": 100 * _maxdd(std),
            "shuffle_p": beat / SHUFFLES}


def window(df, lo, hi):
    return df[(df["entry"] >= lo) & (df["entry"] <= hi)].reset_index(drop=True)


def run(table_path=None):
    nifty = legs("NIFTY", TRAIN[0])
    sensex = legs("SENSEX", SENSEX_FROM)
    st_n = option_state.readings("NIFTY")
    st_s = option_state.readings("SENSEX")
    nifty = nifty.join(st_n, on="entry")
    sensex = sensex.join(st_s, on="entry")
    if table_path:
        nifty.to_csv(table_path, index=False)

    std_check = setup_returns(nifty)["STD"]
    print(f"setup table: NIFTY {len(nifty)} entries ({nifty.entry.min()} → {nifty.entry.max()}), "
          f"SENSEX {len(sensex)}; STD check: NIFTY ann {100 * 50 * std_check.mean():.1f}% of margin, "
          f"Sharpe {std_check.mean() / std_check.std() * np.sqrt(50):.2f}")
    cov = nifty[["vrp", "r5_pct", "skew_pct", "term", "pcr_pct", "usd5_pct", "oil5_pct"]].notna().mean()
    print("reading coverage on NIFTY entries:", {k: round(v, 2) for k, v in cov.items()})

    rows = []
    for name, rule in RULES.items():
        for label, df in (("TRAIN", window(nifty, *TRAIN)), ("TEST", window(nifty, *TEST)), ("SENSEX", sensex)):
            rets = setup_returns(df)
            picks = choose(rule, df)
            rows.append({"rule": name, "window": label, **score(rets, picks)})
    res = pd.DataFrame(rows)
    verdict = []
    for name in RULES:
        g = res[res.rule == name].set_index("window")
        te, tr, se = g.loc["TEST"], g.loc["TRAIN"], g.loc["SENSEX"]
        checks = {"TEST t≥2.4": te["t"] >= T_BAR, "TRAIN diff>0": tr["diff_mean%"] > 0,
                  "TEST worst ok": te["pol_worst%"] >= te["std_worst%"], "TEST maxDD ok": te["pol_maxDD%"] >= te["std_maxDD%"],
                  "SENSEX diff>0": se["diff_mean%"] > 0, "shuffle p<0.05": te["shuffle_p"] < 0.05}
        verdict.append({"rule": name, **{k: bool(v) for k, v in checks.items()}, "PASS": all(checks.values())})
    return nifty, sensex, res, pd.DataFrame(verdict)


def buckets(nifty):
    """STD return by quintile of each reading (descriptive, both windows)."""
    rets = setup_returns(nifty)
    out = []
    for col in ("vrp", "r5", "skew", "term", "pcr", "usd5", "oil5"):
        x = nifty[col]
        ok = x.notna()
        q = pd.qcut(x[ok], 5, labels=False, duplicates="drop")
        g = rets.loc[ok, "STD"].groupby(q)
        out.append({"reading": col, **{f"q{int(k) + 1}": round(100 * v, 2) for k, v in g.mean().items()},
                    "worst_q": int(g.min().idxmin()) + 1})
    return pd.DataFrame(out)


def main():
    ap = argparse.ArgumentParser(description="Plan 0023 — dynamic option setups vs the static rule")
    ap.add_argument("--table", help="write the NIFTY setup table + readings to this CSV")
    a = ap.parse_args()
    pd.set_option("display.width", 250, "display.max_columns", 30)
    nifty, sensex, res, verdict = run(a.table)
    print("\nper rule and window (returns % of the standard strangle's margin; diff = policy − static per trade)")
    print(res.round(3).to_string(index=False))
    print("\npass bar (plan 0023 §4)")
    print(verdict.to_string(index=False))
    print("\nstatic-rule return per trade (%) by quintile of each reading, 2019 → (descriptive)")
    print(buckets(nifty).to_string(index=False))
    by_year = []
    for name, rule in RULES.items():
        rets = setup_returns(nifty)
        picks = choose(rule, nifty)
        pol = pd.Series([rets.at[i, p] for i, p in picks.items()])
        d = (pol - rets["STD"]).groupby(nifty.entry.str[:4]).mean() * 100
        by_year.append({"rule": name, **d.round(3).to_dict()})
    print("\nmean difference per trade by year (% of margin)")
    print(pd.DataFrame(by_year).to_string(index=False))


if __name__ == "__main__":
    main()
