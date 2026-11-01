"""
Paper Books — six strategies, ₹10 lakh each, started June 2026 and marked to the latest close.
(READ-ONLY on the DB; writes output/paper_books/latest.{json,md}. Paper only: no orders anywhere.)

Amit 2026-11-01: "we have 5 strategies and we want to create a paper book on it 10 lakhs each … assuming the
10 lakhs in each gets invested in June 2026 … returns till date, how many times we rotated, STT, STCG tax,
an appropriate benchmark, best weights with 3-4 custom options."

Books (config BOOKS):
  mid_slow / small_slow   the long-hold rule the paper sleeve runs (ADR 0073): buy the top N by the average of
                          the last three monthly scores; sell only when the rank falls below 3N AND the name has
                          been held 12 months. N = 20.
  mid_fast / small_fast   the tactical rule: buy the top N by this month's score; sell when the rank falls below
                          2N; no minimum hold. N = 20.
  multibagger             the desk's ranking as it stood each month: the old multibagger score (June–Sep 2026)
                          and the thesis rank from 2026-10-15; buy the top 10, sell below rank 30.
  published               the sixth book, added as the honest live record: the picks the cockpit actually
                          published on the anchor day (daily_picks, no hindsight): Mid top 10 + Small top 10,
                          ₹5 L each half; sell when a name falls below rank 20 in its tier.
Weight options (OPTIONS, one score source each; the default is the best-tested pre-registered rule (slow: slow_select by
Amit's call; fast: fast_select), never the one that happens to lead this window; each option's `why` quotes its 2022–26 book evidence):
  slow   slow_select (default, Amit 2026-11-01: the best-tested slow score) · slow_v2 (the sleeve's rule) · slow_icw · blend
  fast   fast_select (default) · fast_v1 (the frozen live weights on the panel) · published (daily_picks top N)
  multibagger / published   the basket size (10 / 20 / 30 and 10+10 / 5+5 / 20+20).

Mechanics (the paper sleeve's): monthly anchors = the score panel's snapshot dates (first trading day of the
month); fills at the anchor close; equal amounts per new buy (book value / N, capped by cash); total-return
adjusted closes (signals._prices.apply_adjustments: splits, bonuses, dividends); the ₹1 crore 20-session
median traded-value floor for a new buy; trusts never bought.
Costs: every trade pays tools.lh_costs.cost_breakdown at the stock's own ADTV — statutory charges (STT 0.1 %
each side, stamp, exchange, SEBI, DP) + half the spread + square-root impact. STT is reported on its own.
Tax: every holding is under 12 months, so realised gains are short-term: 20 % + 4 % cess on the net realised
gain per book (loss → no tax, carried); "tax if sold today" adds the unrealised gain at the same rate.
Benchmark: the tier's price index (NIFTY MIDCAP 150 / NIFTY SMALLCAP 250; published = half each), bought at
the first anchor. A price index carries no dividends, so the books' excess is flattered by ~1 %/yr.

Usage:
  python -m tools.paper_books            # full run, writes output/paper_books/latest.{json,md}
  python -m tools.paper_books --smoke    # one option per book, no write
"""

from __future__ import annotations

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
from tools import lh_costs  # noqa: E402

DB = Path(os.environ.get("ALPHA_DB", PROJECT_ROOT / "data" / "alpha_signal.db"))
LH = Path(os.environ.get("ALPHA_LH", DB.parent / "lh"))
OUT = PROJECT_ROOT / "output" / "paper_books"

START = "2026-06-01"             # the first anchor (Amit: "invested in June 2026")
CAPITAL = 1_000_000.0
FLOOR_INR = 1e7                  # ₹1 crore 20-session median traded value for a new buy
STCG = 0.20 * 1.04               # 20 % + 4 % cess on short-term gains (in force since 23 July 2024)
STT = lh_costs.ZERODHA["stt"]
MB_SWITCH = "2026-10-15"         # first multibagger_scores snapshot with a thesis_rank
TIER_BENCH = {"MID": "NIFTY MIDCAP 150", "SMALL": "NIFTY SMALLCAP 250"}

BOOKS = {
    "mid_slow":   dict(label="Mid cap · Slow", tier="MID", kind="slow", bench={"NIFTY MIDCAP 150": 1.0}, N=20, min_hold_m=12,
                       rule="Top 20 Mid caps by the average of the last three monthly slow scores. A name is sold only "
                            "when its rank falls below 60 and it has been held 12 months, so the book barely turns over."),
    "mid_fast":   dict(label="Mid cap · Fast", tier="MID", kind="fast", bench={"NIFTY MIDCAP 150": 1.0}, N=20,
                       rule="Top 20 Mid caps by this month's fast score. A name is sold the month its rank falls "
                            "below 40; the cash buys the best names not yet held."),
    "small_slow": dict(label="Small cap · Slow", tier="SMALL", kind="slow", bench={"NIFTY SMALLCAP 250": 1.0}, N=20, min_hold_m=12,
                       rule="Top 20 Small caps by the average of the last three monthly slow scores. Sold only below "
                            "rank 60 after 12 months held. New buys need ₹1 crore a day of trading."),
    "small_fast": dict(label="Small cap · Fast", tier="SMALL", kind="fast", bench={"NIFTY SMALLCAP 250": 1.0}, N=20,
                       rule="Top 20 Small caps by this month's fast score, sold below rank 40. New buys need ₹1 crore "
                            "a day of trading."),
    "multibagger": dict(label="Multibagger · Best 10", tier=None, kind="mb", bench={"NIFTY SMALLCAP 250": 1.0}, N=10,
                        rule="The desk's 10 best names each month: the multibagger score as published until September, "
                             "the five-part thesis rank from 15 October. Sold when the rank falls below 30."),
    "published":  dict(label="Published picks · Mid 10 + Small 10", tier=None, kind="published",
                       bench={"NIFTY MIDCAP 150": 0.5, "NIFTY SMALLCAP 250": 0.5}, N=10,
                       rule="The picks the cockpit actually showed on the anchor morning (daily_picks): the top 10 Mid "
                            "and top 10 Small, ₹5 lakh each half, no hindsight. Sold when a name falls below rank 20 "
                            "in its tier."),
}

# One score source per option. file/method = the research panels under data/lh; `published` = daily_picks.
OPTIONS = {
    "slow": [
        dict(key="slow_select", label="Slow select (default)", file="oos_scores.parquet", method="slow_select", avg3=True,
             why="Walk-forward: each month the 8 factors with the strongest 126-day evidence so far, equal weight. The best "
                 "slow score in the 2022–26 book test: SMALL +19.7 %/yr over the index (t 2.08), MID +5.5 %/yr (t 1.53)."),
        dict(key="slow_v2", label="Slow v2 (sleeve rule)", file="v2/scores_all.parquet", method="slow_v2", avg3=True,
             why="The pre-registered sleeve rule (plan 0025): equal weights on 6-month momentum, ROCE × book-to-price "
                 "and Piotroski-lite, nothing fitted. Its own 2022–26 book: SMALL +7.9 %/yr over the index, t 1.19, up from "
                 "12 of 12 start months. Kept for simplicity, not because it tested best."),
        dict(key="slow_icw", label="Slow IC-weighted", file="oos_scores.parquet", method="slow_icw", avg3=True,
             why="Walk-forward: ~30 factors, each weighted by its past 126-day information coefficient. Best rank IC "
                 "across the whole tier (0.115) but a weak book at the top: SMALL +3.6 %/yr, t 0.73, worst year −25 %."),
        dict(key="blend", label="Blend slow + fast", file="oos_scores.parquet", method="blend", avg3=True,
             why="The mean of the walk-forward slow-select and fast-select scores."),
    ],
    "fast": [
        dict(key="fast_select", label="Fast select (default)", file="oos_scores.parquet", method="fast_select",
             why="Walk-forward: each month the 6 factors with the strongest 20-day evidence so far. Out of sample by "
                 "construction; the paper sleeve's tactical book runs on it."),
        dict(key="fast_v1", label="Fast v1 (frozen live weights)", file="v2/scores_all.parquet", method="fast_v1",
             why="The production weights frozen in October 2026, applied to the panel. In-sample for these months."),
        dict(key="published", label="As published (daily_picks)", source="published",
             why="The ranks the cockpit showed on the anchor morning, whatever the weights were that day."),
    ],
    "mb": [dict(key="top10", label="Best 10 (default)", N=10, sell=30), dict(key="top20", label="Best 20", N=20, sell=50),
           dict(key="top30", label="Best 30", N=30, sell=70)],
    "published": [dict(key="10+10", label="Mid 10 + Small 10 (default)", N=10, sell=20),
                  dict(key="5+5", label="Mid 5 + Small 5", N=5, sell=10),
                  dict(key="20+20", label="Mid 20 + Small 20", N=20, sell=40)],
}

# What the backtests promised, in plain words, so the page can say whether the window is in line.
EVIDENCE = {
    "mid_slow": "Plan 0024: Mid slow +5.2 %/yr over Midcap 150 after costs and tax (t 1.44) — weak. Apr–Oct 2026 "
                "backtest book +3.7 % vs the index +9.6 %.",
    "mid_fast": "Mid fast_select Apr–Oct 2026 backtest +15.1 % vs the index +9.6 %. Live top-10 picks Apr–Jul: −0.5 % vs "
                "the tier at 63 days, hit rate 44 %.",
    "small_slow": "Plan 0024: Small slow +18.3 %/yr over Smallcap 250 after costs and tax (t 1.81, fragile). Apr–Oct 2026 "
                  "backtest book +23.9 % vs the index +18.7 %.",
    "small_fast": "Plan 0025: the fast Small tactical book was the closest to passing (+12.2 %/yr, t 1.64). Apr–Oct 2026 "
                  "backtest +31.8 % vs the index +18.7 %. Live top-10 picks Apr–Jul: +4.8 % over the tier, hit 58 %.",
    "multibagger": "Research 0008: top 30 vs the equal-weight pond +8.7 %/yr (t 2.25) on survivors; honest DSR fails. "
                   "The forward books (pond / top 30 / price-only 30) started 2026-10-16 and are judged at 24 months.",
    "published": "The Track record page's own numbers: published top-10 picks since April 2026, Small +4.8 % over the "
                 "tier at 63 days, Mid −0.5 %. This book is those picks held as money.",
}


# ── reading ────────────────────────────────────────────────────────────────────────────────────

def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def anchors():
    sc = pd.read_parquet(LH / "oos_scores.parquet", columns=["snapshot_date"])
    return sorted(d for d in sc["snapshot_date"].unique() if d >= START)


def panel_ranks(opt, tier, anchor):
    """{sid: rank} for one score option at one anchor (avg3 = mean of the last three panel anchors' scores,
    over the names in the tier at this anchor)."""
    sc = _panel(opt["file"])
    sc = sc[(sc["method"] == opt["method"]) & (sc["cap_tier"] == tier)]
    if opt.get("avg3"):
        panel_anchors = sorted(sc["snapshot_date"].unique())
        i = panel_anchors.index(anchor)
        use = panel_anchors[max(0, i - 2): i + 1]
        now = sc[sc["snapshot_date"] == anchor]["sid"].unique()
        cur = sc[sc["snapshot_date"].isin(use)].groupby("sid")["score"].mean().reindex(now)
    else:
        cur = sc[sc["snapshot_date"] == anchor].set_index("sid")["score"]
    cur = cur.dropna()
    return cur.rank(ascending=False, method="first").astype(int).to_dict()


_PANELS = {}


def _panel(file):
    if file not in _PANELS:
        sc = pd.read_parquet(LH / file, columns=["sid", "snapshot_date", "cap_tier", "method", "score"])
        _PANELS[file] = sc[sc["snapshot_date"] >= "2026-03-01"]
    return _PANELS[file]


def published_ranks(con, tier, anchor):
    """The cockpit's ranks on the latest pick day on or before the anchor (integrity FAIL excluded)."""
    d = con.execute("SELECT MAX(pick_date) FROM daily_picks WHERE pick_date <= ? AND cap_tier = ?", (anchor, tier)).fetchone()[0]
    rows = con.execute("SELECT sid, rank FROM daily_picks WHERE pick_date = ? AND cap_tier = ? AND "
                       "COALESCE(integrity_status, '') != 'FAIL' ORDER BY rank", (d, tier)).fetchall()
    return d, {sid: i + 1 for i, (sid, _) in enumerate(rows)}


def mb_ranks(con, anchor):
    """The multibagger desk's ranking on the latest snapshot on or before the anchor."""
    d = con.execute("SELECT MAX(snapshot_date) FROM multibagger_scores WHERE snapshot_date <= ?", (anchor,)).fetchone()[0]
    if d is None:
        d = con.execute("SELECT MIN(snapshot_date) FROM multibagger_scores").fetchone()[0]
    if d >= MB_SWITCH:
        rows = con.execute("SELECT sid FROM multibagger_scores WHERE snapshot_date = ? AND thesis_pond = 1 AND thesis_rank "
                           "IS NOT NULL ORDER BY thesis_rank", (d,)).fetchall()
    else:
        rows = con.execute("SELECT sid FROM multibagger_scores WHERE snapshot_date = ? AND passed_gates = 1 AND "
                           "multibagger_score IS NOT NULL ORDER BY multibagger_score DESC", (d,)).fetchall()
    return d, {sid: i + 1 for i, (sid,) in enumerate(rows)}


def load_prices(con, asof):
    """Adjusted closes for every stock from 2026-04-01 to `asof` (one pull), the 20-session ADTV at each date,
    and the index levels."""
    px = pd.read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date >= '2026-04-01' "
                     "AND date <= ?", con, params=[asof])
    adj = pd.read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments", con)
    px = apply_adjustments(px[["sid", "date", "close"]], adj, date.fromisoformat(asof)).merge(
        px[["sid", "date", "volume"]], on=["sid", "date"])
    px["tv"] = px["close"] * px["volume"]
    px = px.sort_values(["sid", "date"])
    px["adtv"] = px.groupby("sid")["tv"].transform(lambda s: s.rolling(20, min_periods=5).median())
    sessions = sorted(px["date"].unique())
    bench = pd.read_sql("SELECT index_symbol, trade_date AS date, close FROM nse_index_history WHERE trade_date >= '2026-04-01' "
                        "AND trade_date <= ? AND close > 0", con, params=[asof])
    return px.set_index(["sid", "date"]), sessions, bench.set_index(["index_symbol", "date"])["close"]


def stock_meta(con):
    from config import SCREEN
    st = pd.read_sql("SELECT sid, ticker, name, cap_tier FROM stocks", con)
    pats = SCREEN.get("trust_exclusion_patterns", [])
    trusts = set(st.loc[st["name"].str.contains("|".join(pats), case=False, regex=True, na=False), "sid"]) if pats else set()
    return st.set_index("sid"), trusts


# ── the simulation ─────────────────────────────────────────────────────────────────────────────

class Prices:
    """Adjusted closes per stock; a stock whose last close is more than 10 sessions old has no price (suspended)."""

    def __init__(self, px, sessions):
        self.by_sid = {sid: g.droplevel(0) for sid, g in px.groupby(level=0)}
        self.pos = {d: i for i, d in enumerate(sessions)}
        self.sessions = sessions

    def at(self, sid, d):
        """(adj_close, close, adtv) at the latest session on or before d, else None."""
        r = self.by_sid.get(sid)
        if r is None:
            return None
        r = r[r.index <= d]
        if r.empty:
            return None
        last = r.index[-1]
        d_pos = self.pos.get(d, max((i for s, i in self.pos.items() if s <= d), default=0))
        if d_pos - self.pos[last] > 10:
            return None
        row = r.iloc[-1]
        return float(row["adj_close"]), float(row["close"]), (float(row["adtv"]) if pd.notna(row["adtv"]) else None)


def trade_cost(value, adtv, price, tier, side):
    tier = tier if tier in ("LARGE", "MID", "SMALL") else "SMALL"
    c = lh_costs.cost_breakdown(adtv, price, value, tier, side=side, year=2026)
    return dict(total=value * c["total"] / 1e4, stt=value * STT, fees_other=value * c["fees"] / 1e4 - value * STT,
                spread_impact=value * (c["half_spread"] + c["impact"]) / 1e4)


def simulate(book_key, opt, ranks_by_anchor, prices, meta, trusts, bench_levels, all_anchors, asof, capital=CAPITAL):
    """One book under one option. ranks_by_anchor: {anchor: [(sleeve, {sid: rank}, N, sell_rank)]} — a book is one
    or two sleeves (published = Mid + Small halves)."""
    sleeves = {s for a in ranks_by_anchor.values() for s, _, _, _ in a}
    cash = {s: capital / len(sleeves) for s in sleeves}
    pos = {}                      # sid -> dict(sleeve, units, cost_basis, bought, rank_at_buy, entry_close)
    trades, history = [], []
    costs = dict(total=0.0, stt=0.0, fees_other=0.0, spread_impact=0.0)
    realised = 0.0
    rotations = 0

    def nav_at(d):
        v = sum(cash.values())
        for sid, p in pos.items():
            q = prices.at(sid, d)
            v += p["units"] * (q[0] if q else p["last_adj"])
        return v

    def bench_at(d):
        lvl = 0.0
        for sym, w in BOOKS[book_key]["bench"].items():
            s = bench_levels.loc[sym]
            s = s[s.index <= d]
            lvl += w * float(s.iloc[-1]) / float(bench_levels.loc[sym][bench_levels.loc[sym].index <= all_anchors[0]].iloc[-1])
        return lvl

    for anchor in all_anchors:
        acted = False
        for sid, p in pos.items():                     # mark to market first
            q = prices.at(sid, anchor)
            if q:
                p["last_adj"] = q[0]
        for sleeve, rk, N, sell_rank in ranks_by_anchor[anchor]:
            # sells
            for sid in [s for s, p in pos.items() if p["sleeve"] == sleeve]:
                p = pos[sid]
                r = rk.get(sid)
                held_m = months_between(p["bought"], anchor)
                min_hold = BOOKS[book_key].get("min_hold_m", 0)
                if (r is None or r > sell_rank) and held_m >= min_hold:
                    q = prices.at(sid, anchor)
                    if q is None:
                        continue                                       # no price: hold and mark at the last close
                    value = p["units"] * q[0]
                    c = trade_cost(value, q[2], q[1], meta.loc[sid, "cap_tier"] if sid in meta.index else "SMALL", "sell")
                    for k in costs:
                        costs[k] += c[k]
                    proceeds = value - c["total"]
                    gain = proceeds - p["cost_basis"]
                    realised += gain
                    cash[sleeve] += proceeds
                    trades.append(dict(date=anchor, sleeve=sleeve, sid=sid, side="SELL", value=round(proceeds), gain=round(gain),
                                       rank=r, held_months=held_m, ret=round(proceeds / p["cost_basis"] - 1, 4)))
                    del pos[sid]
                    acted = True
            # buys
            held_here = [s for s, p in pos.items() if p["sleeve"] == sleeve]
            book_value = cash[sleeve] + sum(pos[s]["units"] * pos[s]["last_adj"] for s in held_here)
            target = book_value / N
            for sid, r in sorted(rk.items(), key=lambda kv: kv[1]):
                if len([s for s, p in pos.items() if p["sleeve"] == sleeve]) >= N or cash[sleeve] < target * 0.5:
                    break
                if sid in pos or sid in trusts:
                    continue
                q = prices.at(sid, anchor)
                if q is None or q[2] is None or q[2] < FLOOR_INR:
                    continue
                amt = min(target, cash[sleeve])
                c = trade_cost(amt, q[2], q[1], meta.loc[sid, "cap_tier"] if sid in meta.index else "SMALL", "buy")
                for k in costs:
                    costs[k] += c[k]
                cash[sleeve] -= amt
                units = (amt - c["total"]) / q[0]
                pos[sid] = dict(sleeve=sleeve, units=units, cost_basis=amt, bought=anchor, rank_at_buy=r, entry_close=q[1],
                                last_adj=q[0])
                trades.append(dict(date=anchor, sleeve=sleeve, sid=sid, side="BUY", value=round(amt), rank=r))
                acted = True
        if acted and anchor != all_anchors[0]:
            rotations += 1
        history.append(dict(date=anchor, nav=round(nav_at(anchor)), bench=round(bench_at(anchor), 5)))

    # mark to the latest close
    final_nav = nav_at(asof)
    history.append(dict(date=asof, nav=round(final_nav), bench=round(bench_at(asof), 5)))
    unreal = 0.0
    holdings = []
    for sid, p in sorted(pos.items(), key=lambda kv: (kv[1]["sleeve"], kv[1]["rank_at_buy"])):
        q = prices.at(sid, asof)
        value = p["units"] * (q[0] if q else p["last_adj"])
        unreal += value - p["cost_basis"]
        holdings.append(dict(sid=sid, ticker=meta.loc[sid, "ticker"] if sid in meta.index else sid, sleeve=p["sleeve"],
                             bought=p["bought"], rank_at_buy=p["rank_at_buy"], value=round(value),
                             ret=round(value / p["cost_basis"] - 1, 4), priced=q is not None))
    tax_realised = max(realised, 0.0) * STCG
    tax_if_sold = max(realised + unreal, 0.0) * STCG
    sells = [t for t in trades if t["side"] == "SELL"]
    buys = [t for t in trades if t["side"] == "BUY"]
    bench_ret = history[-1]["bench"] - 1
    closed_wins = sum(t["gain"] > 0 for t in sells)
    open_wins = sum(h["ret"] > 0 for h in holdings)
    return dict(
        nav=round(final_nav), ret=round(final_nav / capital - 1, 4), bench_ret=round(bench_ret, 4),
        excess=round(final_nav / capital - 1 - bench_ret, 4),
        costs={k: round(v) for k, v in costs.items()}, realised_gain=round(realised), unrealised_gain=round(unreal),
        tax_realised=round(tax_realised), tax_if_sold=round(tax_if_sold),
        ret_after_tax=round((final_nav - tax_realised) / capital - 1, 4),
        ret_if_sold_after_tax=round((final_nav - tax_if_sold) / capital - 1, 4),
        rotations=rotations, buys=len(buys), sells=len(sells),
        turnover=round(sum(t["value"] for t in sells) / capital, 4),
        hit_rate=round((closed_wins + open_wins) / max(len(sells) + len(holdings), 1), 4),
        n=len(holdings), cash=round(sum(cash.values())), history=history, holdings=holdings, trades=trades)


def months_between(d0, d1):
    a, b = pd.Timestamp(d0), pd.Timestamp(d1)
    return (b.year - a.year) * 12 + (b.month - a.month) - (b.day < a.day)


def ranks_for(book_key, opt, con, all_anchors):
    """{anchor: [(sleeve, ranks, N, sell_rank)]} for one book under one option; also the score dates used."""
    b = BOOKS[book_key]
    out, dates = {}, {}
    for a in all_anchors:
        if b["kind"] in ("slow", "fast"):
            N = b["N"]
            sell = 3 * N if b["kind"] == "slow" else 2 * N
            if opt.get("source") == "published":
                d, rk = published_ranks(con, b["tier"], a)
            else:
                d, rk = a, panel_ranks(opt, b["tier"], a)
            out[a] = [(b["tier"], rk, N, sell)]
        elif b["kind"] == "mb":
            d, rk = mb_ranks(con, a)
            out[a] = [("MB", rk, opt["N"], opt["sell"])]
        else:
            parts, ds = [], []
            for t in ("MID", "SMALL"):
                d, rk = published_ranks(con, t, a)
                parts.append((t, rk, opt["N"], opt["sell"]))
                ds.append(d)
            d = ds[-1]
            out[a] = parts
        dates[a] = d
    return out, dates


def run(smoke=False):
    con = ro()
    asof = con.execute("SELECT MAX(date) FROM stock_prices").fetchone()[0]
    all_anchors = anchors()
    px, sessions, bench_levels = load_prices(con, asof)
    meta, trusts = stock_meta(con)
    prices = Prices(px, sessions)
    books = {}
    for key, b in BOOKS.items():
        opts = OPTIONS[b["kind"]][:1] if smoke else OPTIONS[b["kind"]]
        variants = {}
        for opt in opts:
            rk, dates = ranks_for(key, opt, con, all_anchors)
            res = simulate(key, opt, rk, prices, meta, trusts, bench_levels, all_anchors, asof)
            res.update(key=opt["key"], label=opt["label"], why=opt.get("why", ""), score_dates=dates)
            variants[opt["key"]] = res
            print(f"{key:12s} {opt['key']:12s} nav {res['nav']:>10,.0f}  ret {res['ret']:+.1%}  bench {res['bench_ret']:+.1%}  "
                  f"rot {res['rotations']}  stt ₹{res['costs']['stt']:,.0f}  tax(if sold) ₹{res['tax_if_sold']:,.0f}")
        default = opts[0]["key"]
        best = max(variants, key=lambda k: variants[k]["ret"])
        books[key] = dict(label=b["label"], tier=b["tier"], kind=b["kind"], rule=b["rule"], bench=b["bench"],
                          bench_label=" / ".join(f"{int(w * 100)} % {s}" for s, w in b["bench"].items()) if len(b["bench"]) > 1
                          else next(iter(b["bench"])), N=b["N"], default=default, best_in_window=best,
                          evidence=EVIDENCE[key], option_order=[o["key"] for o in opts], variants=variants)
    con.close()
    out = dict(asof=asof, start=all_anchors[0], anchors=all_anchors, capital=CAPITAL, stcg=STCG, stt=STT,
               floor_inr=FLOOR_INR, computed=date.today().isoformat(), books=books,
               notes=["Fills at the anchor close; no slippage beyond the modelled half-spread and impact.",
                      "Benchmarks are price indices (no dividends); the books' closes include dividends.",
                      "The slow and fast research panels were built in October 2026; fast_select / slow_select / slow_icw "
                      "/ blend are walk-forward (out of sample), slow_v2 and fast_v1 are fixed weights chosen in October "
                      "(in-sample for these months), and 'As published' is the cockpit's own record."])
    if not smoke:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "latest.json").write_text(json.dumps(out, indent=1, default=str))
        (OUT / "latest.md").write_text(markdown(out))
        print(f"wrote {OUT / 'latest.json'}")
    return out


def markdown(out):
    lines = [f"# Paper books — ₹{out['capital'] / 1e5:.0f} L each from {out['start']}, marked {out['asof']}", ""]
    lines.append("| Book | Option | Return | Benchmark | Excess | Rotations | STT | Tax if sold | After tax |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for k, b in out["books"].items():
        for vk, v in b["variants"].items():
            star = " *" if vk == b["default"] else ""
            lines.append(f"| {b['label']} | {v['label']}{star} | {v['ret']:+.1%} | {v['bench_ret']:+.1%} | {v['excess']:+.1%} | "
                         f"{v['rotations']} | ₹{v['costs']['stt']:,.0f} | ₹{v['tax_if_sold']:,.0f} | {v['ret_if_sold_after_tax']:+.1%} |")
    lines += ["", "\\* the default option (the pre-registered rule)."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    run(smoke=a.smoke)


if __name__ == "__main__":
    main()
