"""
Alpha Signal v2 — backtest of the investor-playbook sleeves, and their forward record.

For each sleeve in sleeves.SLEEVES: at the first stored snapshot of every month, hold
the sleeve's members at equal weight until the next month's snapshot. Returns are from
split/bonus/dividend-adjusted closes, net of the tier's trading cost on every change in
weight, and compared with the average stock of the SAME tier that month (a within-tier
benchmark, so a sleeve full of small caps is not flattered by a small-cap rally).

Also tested:
  flagged   stocks carrying a red flag — their return against their tier (a veto is
            worth having only if this is negative); no cost, it is not a portfolio
  combined  every sleeve that has enough names that month at equal sleeve weight, with
            flagged stocks removed. NOT a selection of the sleeves that did well:
            choosing winners on ~5 years of history would be fitting noise.

What this cannot show (printed with the results and on the cockpit tab):
  - survivors only: the universe is today's listed stocks, which flatters every sleeve
  - short windows: one market cycle at most, under three years for insiders / deep value
  - statements are as restated today; superinvestors and say-vs-do have no history yet

Reads: daily_snapshots_pit, stock_prices, corporate_adjustments, insider_trades,
       fundamentals_screener, bse_announcements, shareholding
Writes: output/playbook_backtest.json;  --record → playbook_members (today's members)

Usage:
    python -m tools.playbook_backtest             # run the backtest, print the table
    python -m tools.playbook_backtest --record    # store today's members (run.sh morning)
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import sleeves
from config import PICKABLE_TIERS, TIERS

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "output" / "playbook_backtest.json"
RETURN_BOUNDS = (-0.90, 2.00)     # a monthly move outside this is treated as a data error and dropped
INDEX = "NIFTY SMALLCAP 250"      # the one investable index we hold for the whole window (price only, no dividends)
COST = {t: TIERS[t]["cost_bps"] / 10_000 for t in PICKABLE_TIERS}


def month_anchors(dates):
    """The first stored snapshot of each month."""
    first = {}
    for d in dates:
        first.setdefault(d[:7], d)
    return [first[m] for m in sorted(first)]


def price_matrix(anchors):
    """Adjusted close per sid at each anchor (the last trading day on or before it, within a week)."""
    from signals._prices import load_prices
    px = load_prices()
    wide = px.pivot(index="date", columns="sid", values="adj_close").sort_index()
    idx = sorted(set(wide.index) | set(anchors))
    return wide.reindex(idx).ffill(limit=5).loc[anchors]


def _stats(rows):
    """rows = [{month, net, bench, turnover, n}] for the months the portfolio was held."""
    if not rows:
        return None
    df = pd.DataFrame(rows)
    ex = df["net"] - df["bench"]
    nav = (1 + df["net"]).cumprod()
    years = len(df) / 12
    return {
        "months": len(df), "first": df["month"].iloc[0], "last": df["month"].iloc[-1],
        "avg_names": round(float(df["n"].mean()), 1),
        "net_ann": round((float(nav.iloc[-1]) ** (1 / years) - 1) * 100, 1),
        "gross_ann": round((float((1 + df["net"] + df["cost"]).prod()) ** (1 / years) - 1) * 100, 1),
        "cost_ann": round(float(df["cost"].mean()) * 12 * 100, 1),
        "index_ann": round((float((1 + df["index"]).prod()) ** (1 / years) - 1) * 100, 1) if df["index"].notna().all() else None,
        "bench_ann": round((float((1 + df["bench"]).prod()) ** (1 / years) - 1) * 100, 1),
        "excess_ann": round(float(ex.mean()) * 12 * 100, 1),
        "t_stat": round(float(ex.mean() / (ex.std(ddof=1) / np.sqrt(len(ex)))), 2) if len(ex) > 2 and ex.std(ddof=1) > 0 else None,
        "hit_rate": round(float((ex > 0).mean()) * 100),
        "max_drawdown": round(float((nav / nav.cummax() - 1).min()) * 100, 1),
        "turnover": round(float(df["turnover"].mean()) * 100),
        "curve": [{"month": m, "nav": round(float(v), 4), "bench": round(float(b), 4)}
                  for m, v, b in zip(df["month"], nav, (1 + df["bench"]).cumprod())],
    }


def _hold(weights, prev, ret, tier, tier_mean):
    """One month of a weighted book: (gross, bench, cost, one-way turnover)."""
    w = pd.Series(weights)
    gross = float((w * ret.reindex(w.index)).sum())
    bench = float((w * tier.reindex(w.index).map(tier_mean)).sum())
    old = pd.Series(prev) if prev else pd.Series(dtype=float)
    delta = w.reindex(w.index.union(old.index), fill_value=0) - old.reindex(w.index.union(old.index), fill_value=0)
    cost = float((delta.abs() * tier.reindex(delta.index).map(COST).fillna(max(COST.values()))).sum())
    return gross, bench, cost, float(delta.abs().sum() / 2)


def run(ctx=None, verbose=True):
    ctx = ctx or sleeves.load_context()
    anchors = month_anchors(ctx["dates"])
    px = price_matrix(anchors)
    from db import read_sql
    index = read_sql("SELECT trade_date, close FROM nse_index_history WHERE index_symbol = ? AND close > 0 ORDER BY trade_date",
                     params=[INDEX]).set_index("trade_date")["close"]
    held = {k: [] for k in [*sleeves.SLEEVES, "combined"]}
    flagged_rows, prev, n_dropped = [], {}, 0
    for t0, t1 in zip(anchors[:-1], anchors[1:]):
        frame = sleeves.frame_at(ctx, t0)
        tier = frame["cap_tier"]
        ret = (px.loc[t1] / px.loc[t0] - 1).dropna()
        bad = (ret < RETURN_BOUNDS[0]) | (ret > RETURN_BOUNDS[1])
        n_dropped += int(bad.sum())
        ret = ret[~bad]
        universe = [s for s in ret.index if tier.get(s) in PICKABLE_TIERS]
        ret, tier_u = ret.loc[universe], tier.reindex(universe)
        tier_mean = ret.groupby(tier_u).mean().to_dict()
        i0, i1 = index[index.index <= t0], index[index.index <= t1]
        index_ret = float(i1.iloc[-1] / i0.iloc[-1] - 1) if len(i0) and len(i1) else float("nan")
        flags = sleeves.red_flags(ctx, t0)
        flagged = [s for s in flags if s in ret.index]
        if len(flagged) >= sleeves.MIN_NAMES:
            flagged_rows.append({"month": t0[:7], "net": float(ret.loc[flagged].mean()),
                                 "bench": float(tier_u.loc[flagged].map(tier_mean).mean()), "cost": 0.0, "index": index_ret,
                                 "turnover": 0.0, "n": len(flagged)})
        books = {}
        for key, spec in sleeves.SLEEVES.items():
            members = sorted(spec["members"](ctx, t0) & set(ret.index)) if t0 >= spec["since"] else []
            if len(members) < sleeves.MIN_NAMES:
                prev[key] = {}
                continue
            books[key] = {s: 1 / len(members) for s in members}
            gross, bench, cost, turn = _hold(books[key], prev.get(key), ret, tier_u, tier_mean)
            held[key].append({"month": t0[:7], "net": gross - cost, "cost": cost, "index": index_ret, "bench": bench, "turnover": turn, "n": len(members)})
            prev[key] = books[key]
        # combined: equal weight across the sleeves held this month, flagged names removed
        clean = {k: [s for s in b if s not in flags] for k, b in books.items()}
        clean = {k: v for k, v in clean.items() if len(v) >= sleeves.MIN_NAMES}
        if clean:
            w = {}
            for members in clean.values():
                for s in members:
                    w[s] = w.get(s, 0) + 1 / len(clean) / len(members)
            gross, bench, cost, turn = _hold(w, prev.get("combined"), ret, tier_u, tier_mean)
            held["combined"].append({"month": t0[:7], "net": gross - cost, "cost": cost, "index": index_ret, "bench": bench, "turnover": turn, "n": len(w)})
            prev["combined"] = w
        else:
            prev["combined"] = {}

    out = {"generated_at": datetime.now().isoformat(timespec="seconds"), "first_month": anchors[0][:7],
           "last_month": anchors[-1][:7], "returns_dropped": n_dropped, "min_names": sleeves.MIN_NAMES,
           "costs_bps": {t: TIERS[t]["cost_bps"] for t in PICKABLE_TIERS}, "index": INDEX, "sleeves": [], "flagged": None, "combined": None}
    for key, spec in sleeves.SLEEVES.items():
        out["sleeves"].append({"key": key, "label": spec["label"], "who": spec["who"], "rule": spec["rule"],
                               "caveat": spec["caveat"], "stats": _stats(held[key])})
    out["combined"] = {"label": "All sleeves, equal weight, red flags removed", "stats": _stats(held["combined"])}
    out["flagged"] = {"label": sleeves.VETO["label"], "rule": sleeves.VETO["rule"], "stats": _stats(flagged_rows)}
    OUTPUT_PATH.write_text(json.dumps(out, indent=1))
    if verbose:
        _print(out)
    return out


def _print(out):
    print(f"Playbook sleeves, monthly, {out['first_month']} → {out['last_month']} (net of costs; 'tier avg' = average stock "
          f"of the same tier, 'index' = {out['index']} price index; excess is against tier avg; survivors only)\n")
    head = (f"{'sleeve':42s} {'months':>6s} {'from':>8s} {'names':>6s} {'gross':>6s} {'cost':>5s} {'net %/yr':>9s} {'tier avg':>8s} "
            f"{'index':>6s} {'excess':>7s} {'t':>6s} {'hit %':>6s} {'maxDD':>7s} {'turn %':>7s}")
    print(head)
    rows = [(s["label"], s["stats"]) for s in out["sleeves"]] + [(out["combined"]["label"], out["combined"]["stats"]),
                                                                  ("Flagged stocks (want: negative excess)", out["flagged"]["stats"])]
    for label, st in rows:
        if not st:
            print(f"{label:42s} {'no month with enough names':>40s}")
            continue
        t = "–" if st["t_stat"] is None else f"{st['t_stat']:.2f}"
        ix = "–" if st["index_ann"] is None else f"{st['index_ann']:.1f}"
        print(f"{label:42s} {st['months']:6d} {st['first']:>8s} {st['avg_names']:6.1f} {st['gross_ann']:6.1f} {st['cost_ann']:5.1f} "
              f"{st['net_ann']:9.1f} {st['bench_ann']:8.1f} {ix:>6s} {st['excess_ann']:7.1f} {t:>6s} {st['hit_rate']:6d} "
              f"{st['max_drawdown']:7.1f} {st['turnover']:7d}")
    print(f"\n{out['returns_dropped']} monthly returns outside {RETURN_BOUNDS} were dropped as data errors.")


def record(today=None):
    """Store today's members of every sleeve (and the flagged set) in playbook_members —
    the forward record, free of hindsight and survivorship. Returns rows written."""
    from db import insert_df
    today = (today or date.today()).isoformat() if not isinstance(today, str) else today
    members = sleeves.members_today()
    rows = [{"sid": sid, "snapshot_date": today, "sleeve": key, "in_sleeve": 1} for key, sids in members.items() for sid in sids]
    if not rows:
        raise RuntimeError("playbook_members: every sleeve is empty today — inputs missing?")
    n = insert_df(pd.DataFrame(rows), "playbook_members")
    print(f"playbook_members {today}: " + " · ".join(f"{k} {len(v)}" for k, v in members.items()) + f" ({n} new rows)")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", action="store_true", help="store today's members instead of running the backtest")
    a = ap.parse_args()
    record() if a.record else run()
