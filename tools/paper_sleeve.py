"""
ADR 0073 — the SMALL paper sleeve: a slow book and a tactical book, 20 names each, monthly.
(READ-ONLY on the DB; state in data/paper/small_sleeve.json, report in output/paper_sleeve/.)

Books (the rules the 12-start timing test graded B, docs/studies/slow-core-tactical-2026-10.md):
  slow      slow_v2 scores (data/lh/v2/scores_all.parquet): buy the top 20 by the 3-month average
            score; sell a holding only when its rank falls below 60 AND it has been held 12 months.
  tactical  fast_select scores (data/lh/oos_scores.parquet, walk-forward): buy the top 20 by score;
            sell when the rank falls below 40; no minimum hold.
Trusts: InvIT / REIT / trust instruments are never bought, by the live screener's own rule
(config.SCREEN["trust_exclusion_patterns"] on the stock name).
Liquidity floor: a new buy needs a 20-session median traded value (close × volume) of at least
₹1 crore (Amit's floor; tools/lh_liquidity_floor.py kept both books 12/12 starts with it). Sells
are never blocked.
Notional ₹5,25,000 per book (half of a 30 % sleeve of ₹35 L). Equal amounts per new buy
(book value / 20, capped by cash).
Costs: 30.5 bps per side (measured SMALL one-way cost at ₹1 L, plan 0024). Tax is not taken out of
the NAV; realised short- and long-term gains are logged so the tax can be estimated.
Valuation: total-return adjusted closes (signals._prices.apply_adjustments, dividends included).
Benchmark: NIFTY SMALLCAP 250 (price index) from nse_index_history.
Kill switch (ADR 0073): status PAUSED when the combined sleeve trails the benchmark by 15 % over the
trailing 12 months, or by 20 % from its relative high-water mark. While PAUSED there are no new buys;
holdings are kept and listed for review. Amit un-pauses by editing the state file (status ACTIVE).
Paper only: no orders are placed anywhere.

Usage:
  python -m tools.paper_sleeve rebalance [--asof YYYY-MM-DD]   # monthly, after the scores refresh
  python -m tools.paper_sleeve status
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from signals._prices import apply_adjustments  # noqa: E402

DB = Path(os.environ.get("ALPHA_DB", PROJECT_ROOT / "data" / "alpha_signal.db"))
DATA = DB.parent
LH = DATA / "lh"
STATE = DATA / "paper" / "small_sleeve.json"
OUT = DB.parent.parent / "output" / "paper_sleeve"
COST = 0.00305
FLOOR_INR = 1e7
NOTIONAL = 525_000.0
BENCH = "NIFTY SMALLCAP 250"
BOOKS = {
    "slow": dict(file="v2/scores_all.parquet", method="slow_v2", N=20, sell_rank=60, avg3=True, min_hold_m=12),
    "tactical": dict(file="oos_scores.parquet", method="fast_select", N=20, sell_rank=40, avg3=False, min_hold_m=0),
}


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def ranks(book, asof):
    b = BOOKS[book]
    sc = pd.read_parquet(LH / b["file"], columns=["sid", "snapshot_date", "cap_tier", "method", "score"])
    sc = sc[(sc["method"] == b["method"]) & (sc["snapshot_date"] <= asof)]
    anchors = sorted(sc["snapshot_date"].unique())
    if not anchors:
        raise SystemExit(f"no {b['method']} scores on or before {asof}")
    a = anchors[-1]
    cur = sc[(sc["snapshot_date"] == a) & (sc["cap_tier"] == "SMALL")].set_index("sid")
    if b["avg3"]:
        last3 = sc[sc["snapshot_date"].isin(anchors[-3:])].groupby("sid")["score"].mean()
        cur["score"] = last3.reindex(cur.index)
    cur = cur.dropna(subset=["score"])
    cur["rank"] = cur["score"].rank(ascending=False, method="first")
    return a, cur["rank"].sort_values()


def adtv(sids, asof):
    """20-session median close × volume (₹) up to `asof`."""
    con = ro()
    ph = ",".join("?" * len(sids))
    px = pd.read_sql(f"SELECT sid, date, close * volume AS tv FROM stock_prices WHERE close > 0 AND date <= ? "
                     f"AND date >= ? AND sid IN ({ph})", con,
                     params=[asof, (pd.Timestamp(asof) - pd.Timedelta(days=45)).date().isoformat(), *sids])
    con.close()
    last = sorted(px["date"].unique())[-20:]
    return px[px["date"].isin(last)].groupby("sid")["tv"].median()


def prices(sids, asof):
    con = ro()
    ph = ",".join("?" * len(sids))
    px = pd.read_sql(f"SELECT sid, date, close FROM stock_prices WHERE close > 0 AND date <= ? AND date >= ? "
                     f"AND sid IN ({ph})", con, params=[asof, "2026-01-01", *sids])
    adj = pd.read_sql(f"SELECT sid, ex_date, factor, inds FROM corporate_adjustments WHERE sid IN ({ph})", con,
                      params=list(sids))
    bench = pd.read_sql("SELECT trade_date, close FROM nse_index_history WHERE index_symbol = ? AND trade_date <= ? "
                        "ORDER BY trade_date DESC LIMIT 1", con, params=[BENCH, asof])
    con.close()
    px = apply_adjustments(px, adj, date.fromisoformat(asof))
    last = px.sort_values("date").groupby("sid").tail(1).set_index("sid")
    return last[["date", "close", "adj_close"]], float(bench["close"].iloc[0]), bench["trade_date"].iloc[0]


def months_between(d0, d1):
    a, b = pd.Timestamp(d0), pd.Timestamp(d1)
    return (b.year - a.year) * 12 + (b.month - a.month) - (b.day < a.day)


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return dict(created=date.today().isoformat(), status="ACTIVE", history=[], trades=[],
                books={k: dict(cash=NOTIONAL, positions={}) for k in BOOKS}, bench_start=None)


def rebalance(asof):
    st = load_state()
    rk = {k: ranks(k, asof) for k in BOOKS}
    held = {s for b in st["books"].values() for s in b["positions"]}
    universe = sorted(held | {s for _, r in rk.values() for s in r.index[:80]})
    px, bench_level, bench_date = prices(universe, asof)
    liquid = set(adtv(universe, asof).loc[lambda x: x >= FLOOR_INR].index)
    from config import SCREEN
    con = ro()
    nm = pd.read_sql("SELECT sid, name FROM stocks", con)
    con.close()
    pats = SCREEN.get("trust_exclusion_patterns", [])
    trusts = set(nm.loc[nm["name"].str.contains("|".join(pats), case=False, regex=True, na=False), "sid"]) if pats else set()
    liquid -= trusts
    if st["bench_start"] is None:
        st["bench_start"] = bench_level

    # 1. mark to market on adjusted closes
    for b in st["books"].values():
        for sid, p in b["positions"].items():
            if sid in px.index:
                p["value"] *= float(px.loc[sid, "adj_close"]) / p["last_adj"]
                p["last_adj"] = float(px.loc[sid, "adj_close"])
                p["last_close"] = float(px.loc[sid, "close"])

    # 2. kill switch on the combined sleeve vs the benchmark (relative NAV)
    nav = {k: b["cash"] + sum(p["value"] for p in b["positions"].values()) for k, b in st["books"].items()}
    comb = sum(nav.values()) / (2 * NOTIONAL)
    rel = comb / (bench_level / st["bench_start"])
    hist_rel = [h["relative"] for h in st["history"]] + [rel]
    hwm = max(hist_rel)
    yr_ago = [h for h in st["history"] if months_between(h["date"], asof) >= 12]
    trail12 = rel / yr_ago[-1]["relative"] - 1 if yr_ago else None
    breach = (rel / hwm - 1 <= -0.20) or (trail12 is not None and trail12 <= -0.15)
    if breach and st["status"] == "ACTIVE":
        st["status"] = "PAUSED"

    # 3. sells, then buys
    for k, b in st["books"].items():
        cfg, (anchor, r) = BOOKS[k], rk[k]
        for sid in list(b["positions"]):
            p = b["positions"][sid]
            rank = r.get(sid)
            held_m = months_between(p["bought"], asof)
            if (rank is None or rank > cfg["sell_rank"]) and held_m >= cfg["min_hold_m"]:
                proceeds = p["value"] * (1 - COST)
                gain = proceeds - p["cost_basis"]
                b["cash"] += proceeds
                st["trades"].append(dict(date=asof, book=k, sid=sid, side="SELL", value=round(proceeds, 2),
                                         rank=None if rank is None else int(rank), held_months=held_m,
                                         gain=round(gain, 2), term="LT" if held_m >= 12 else "ST"))
                del b["positions"][sid]
        if st["status"] != "ACTIVE":
            continue
        book_value = b["cash"] + sum(p["value"] for p in b["positions"].values())
        target = book_value / cfg["N"]
        for sid in r.index:
            if len(b["positions"]) >= cfg["N"] or b["cash"] < target * 0.5:
                break
            if sid in b["positions"] or sid not in px.index or sid not in liquid:
                continue
            amt = min(target, b["cash"])
            b["cash"] -= amt
            v = amt * (1 - COST)
            b["positions"][sid] = dict(bought=asof, cost_basis=amt, value=v, last_adj=float(px.loc[sid, "adj_close"]),
                                       entry_close=float(px.loc[sid, "close"]), last_close=float(px.loc[sid, "close"]),
                                       rank_at_buy=int(r[sid]))
            st["trades"].append(dict(date=asof, book=k, sid=sid, side="BUY", value=round(amt, 2), rank=int(r[sid])))

    nav = {k: b["cash"] + sum(p["value"] for p in b["positions"].values()) for k, b in st["books"].items()}
    comb = sum(nav.values()) / (2 * NOTIONAL)
    st["history"].append(dict(date=asof, price_date=str(px["date"].max()), bench_date=bench_date,
                              nav={k: round(v, 2) for k, v in nav.items()}, combined=round(comb, 6),
                              bench=round(bench_level / st["bench_start"], 6),
                              relative=round(comb / (bench_level / st["bench_start"]), 6),
                              score_anchor={k: rk[k][0] for k in BOOKS}, status=st["status"],
                              trailing12_relative=None if trail12 is None else round(trail12, 4)))
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))
    report(st)
    return st


def report(st):
    OUT.mkdir(parents=True, exist_ok=True)
    h = st["history"][-1]
    con = ro()
    names = dict(con.execute("SELECT sid, ticker FROM stocks").fetchall())
    con.close()
    lines = [f"# SMALL paper sleeve — {h['date']} (prices {h['price_date']})", "",
             f"Status: **{st['status']}** · combined {h['combined']:.4f} · Smallcap 250 {h['bench']:.4f} · "
             f"relative {h['relative']:.4f}", ""]
    for k, b in st["books"].items():
        lines.append(f"## {k} — NAV ₹{h['nav'][k]:,.0f} · cash ₹{b['cash']:,.0f} · {len(b['positions'])} names")
        for sid, p in sorted(b["positions"].items(), key=lambda kv: kv[1]["bought"]):
            lines.append(f"- {names.get(sid, sid)} ({sid}) · bought {p['bought']} at rank {p['rank_at_buy']} · "
                         f"₹{p['value']:,.0f} ({p['value'] / p['cost_basis'] - 1:+.1%})")
        lines.append("")
    (OUT / "latest.md").write_text("\n".join(lines))
    (OUT / "latest.json").write_text(json.dumps(cockpit_view(st, names), indent=1))
    print("\n".join(lines))


RULES = {"slow": "Buys the top 20 by the average of the last three monthly scores; sells only when the rank falls "
                 "below 60 and the stock has been held 12 months.",
         "tactical": "Buys the top 20; sells when the rank falls below 40. No minimum hold."}


def cockpit_view(st, names):
    """latest.json, the one file the cockpit reads (config.FILE_OUTPUTS `_file_paper_sleeve`): both books'
    holdings with today's book rank, and the whole SMALL long-hold (slow book) ranking the stock page and the
    Stocks screener show. The ranks are the ones the books act on (slow = 3-month average)."""
    h = st["history"][-1]
    rk = {k: ranks(k, h["date"]) for k in BOOKS}
    books = {}
    for k, b in st["books"].items():
        anchor, r = rk[k]
        pos = [dict(sid=sid, ticker=names.get(sid, sid), bought=p["bought"], rank_at_buy=p["rank_at_buy"],
                    rank_now=None if r.get(sid) is None else int(r[sid]), value=round(p["value"], 2),
                    ret=round(p["value"] / p["cost_basis"] - 1, 4))
               for sid, p in sorted(b["positions"].items(), key=lambda kv: (kv[1]["bought"], kv[1]["rank_at_buy"]))]
        books[k] = dict(nav=h["nav"][k], cash=round(b["cash"], 2), n=len(pos), size=len(r), score_date=anchor,
                        rule=RULES[k], positions=pos)
    d = pd.Timestamp(h["date"])
    nxt = (d + pd.offsets.MonthBegin(1)) + pd.Timedelta(days=1)          # the cron runs on the 2nd
    anchor, r = rk["slow"]
    done = [t for t in st["trades"] if t["date"] == h["date"]]
    review = dict(date=h["date"], bought=sum(t["side"] == "BUY" for t in done), sold=sum(t["side"] == "SELL" for t in done))
    return dict(status=st["status"], latest=h, next_review=nxt.date().isoformat(), notional=NOTIONAL, bench=BENCH,
                books=books, last_review=review,
                long_hold=dict(tier="SMALL", score_date=anchor, computed=h["date"], size=len(r),
                               ranks={sid: int(v) for sid, v in r.items()}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["rebalance", "status"])
    ap.add_argument("--asof", default=date.today().isoformat())
    a = ap.parse_args()
    if a.cmd == "rebalance":
        rebalance(a.asof)
    else:
        report(load_state())


if __name__ == "__main__":
    main()
