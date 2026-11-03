"""
Paper Books — eight books, ₹10 lakh each, started June 2026 and marked to the latest close.
(READ-ONLY on the DB; writes output/paper_books/latest.{json,md}. Paper only: no orders anywhere.)

Amit 2026-11-01: "we have 5 strategies and we want to create a paper book on it 10 lakhs each … assuming the
10 lakhs in each gets invested in June 2026 … returns till date, how many times we rotated, STT, STCG tax,
an appropriate benchmark." Amit 2026-11-03: "have 3 models at max slow fast and blend and use a better bar, do
backtesting and select the three models" (tools/model_select.py, ADR 0095).

Books (config BOOKS):
  mid_slow / small_slow   Slow: top 20 by the average of the last three monthly scores; sold only below rank 60
                          after 12 months held (ADR 0073's slow rule).
  mid_fast / small_fast   Fast: top 20 by this month's score; sold below rank 40; no minimum hold.
  mid_blend / small_blend Blend: the mean of the Slow and Fast scores; top 20; sold below rank 50 after 6 months held.
  multibagger             the desk's ranking as it stood each month: the old multibagger score (June–Sep 2026)
                          and the thesis rank from 2026-10-15; buy the top 10, sell below rank 30.
  published               the honest live record: the picks the cockpit actually published on the anchor day
                          (daily_picks, no hindsight): Mid top 10 + Small top 10, ₹5 L each half; sold below rank 20.
The three models come from data/lh/model_select/models.parquet (tools.model_select --score). Multibagger and published
keep a basket-size choice (10 / 20 / 30 and 10+10 / 5+5 / 20+20): that is not a model.

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

Frozen record (2026-11-02): the research panels are rebuilt every month and a rebuild moves past scores (a
refresh changed 14 of the June top 20), so a replay is not a record. The first run replays June → the latest
anchor and writes every month's trades to data/paper/paper_books.json; later runs load that state, trade only
the anchors after the last frozen one, and mark the frozen positions to market. `replay_until` on the page says
which months were replayed. --rebuild throws the record away (never on cron).

Usage:
  python -m tools.paper_books            # mark + trade any new anchor, writes output/paper_books/latest.{json,md}
  python -m tools.paper_books --smoke    # one option per book, no write, no state
  python -m tools.paper_books --rebuild  # replay everything again from June (discards the frozen record)
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
STATE = DB.parent / "paper" / "paper_books.json"     # the frozen record: every month's trades, written once

START = "2026-06-01"             # the first anchor (Amit: "invested in June 2026")
CAPITAL = 1_000_000.0
FLOOR_INR = 1e7                  # ₹1 crore 20-session median traded value for a new buy
STCG = 0.20 * 1.04               # 20 % + 4 % cess on short-term gains (in force since 23 July 2024)
STT = lh_costs.ZERODHA["stt"]
MB_SWITCH = "2026-10-15"         # first multibagger_scores snapshot with a thesis_rank
TIER_BENCH = {"MID": "NIFTY MIDCAP 150", "SMALL": "NIFTY SMALLCAP 250"}

MODEL_KINDS = ("slow", "fast", "blend")
MODELS_FILE = "model_select/models.parquet"       # the three models, tools.model_select --score
SELECTION = LH / "model_select" / "results.json"  # the pre-registered test that chose them

_MID, _SMALL = {"NIFTY MIDCAP 150": 1.0}, {"NIFTY SMALLCAP 250": 1.0}
_SLOW_RULE = "Top 20 {} by the average of the last three monthly Slow scores. Sold only when the rank falls below 60 and the name has been held 12 months."
_FAST_RULE = "Top 20 {} by this month's Fast score. Sold the month the rank falls below 40; the cash buys the best names not yet held."
_BLEND_RULE = "Top 20 {} by the mean of the Slow and Fast scores this month. Sold when the rank falls below 50 and the name has been held 6 months."
BOOKS = {
    "mid_slow":    dict(label="Mid cap · Slow", tier="MID", kind="slow", bench=_MID, N=20, sell=60, min_hold_m=12, rule=_SLOW_RULE.format("Mid caps")),
    "mid_fast":    dict(label="Mid cap · Fast", tier="MID", kind="fast", bench=_MID, N=20, sell=40, rule=_FAST_RULE.format("Mid caps")),
    "mid_blend":   dict(label="Mid cap · Blend", tier="MID", kind="blend", bench=_MID, N=20, sell=50, min_hold_m=6, rule=_BLEND_RULE.format("Mid caps")),
    "small_slow":  dict(label="Small cap · Slow", tier="SMALL", kind="slow", bench=_SMALL, N=20, sell=60, min_hold_m=12, rule=_SLOW_RULE.format("Small caps")),
    "small_fast":  dict(label="Small cap · Fast", tier="SMALL", kind="fast", bench=_SMALL, N=20, sell=40, rule=_FAST_RULE.format("Small caps")),
    "small_blend": dict(label="Small cap · Blend", tier="SMALL", kind="blend", bench=_SMALL, N=20, sell=50, min_hold_m=6, rule=_BLEND_RULE.format("Small caps")),
    "multibagger": dict(label="Multibagger · Best 10", tier=None, kind="mb", bench=_SMALL, N=10,
                        rule="The desk's 10 best names each month: the multibagger score as published until September, "
                             "the five-part thesis rank from 15 October. Sold when the rank falls below 30."),
    "published":   dict(label="Published picks · Mid 10 + Small 10", tier=None, kind="published",
                        bench={"NIFTY MIDCAP 150": 0.5, "NIFTY SMALLCAP 250": 0.5}, N=10,
                        rule="The picks the cockpit actually showed on the anchor morning (daily_picks): the top 10 Mid "
                             "and top 10 Small, ₹5 lakh each half, no hindsight. Sold when a name falls below rank 20 "
                             "in its tier."),
}

OPTIONS = {
    "slow": [dict(key="slow", label="Slow", file=MODELS_FILE, method="slow", avg3=True,
                  why="Each month, from past data only: the factors that predicted 6-month returns with |t| ≥ 2.5 over at least "
                      "24 months AND whose best-ranked fifth of stocks really beat the tier (the long-side test). At most 8, equal weight.")],
    "fast": [dict(key="fast", label="Fast", file=MODELS_FILE, method="fast",
                  why="Each month, from past data only: the factors that predicted next month's return and survive a multiple-testing "
                      "correction across every factor tried (Benjamini-Yekutieli, 5 %). At most 6, equal weight.")],
    "blend": [dict(key="blend", label="Blend", file=MODELS_FILE, method="blend",
                   why="The mean of the Slow and Fast scores. Nothing is fitted: its holding rule is the midpoint of the other two.")],
    "mb": [dict(key="top10", label="Best 10 (default)", N=10, sell=30), dict(key="top20", label="Best 20", N=20, sell=50),
           dict(key="top30", label="Best 30", N=30, sell=70)],
    "published": [dict(key="10+10", label="Mid 10 + Small 10 (default)", N=10, sell=20),
                  dict(key="5+5", label="Mid 5 + Small 5", N=5, sell=10),
                  dict(key="20+20", label="Mid 20 + Small 20", N=20, sell=40)],
}

# What the record says for the books that are not one of the three models.
EVIDENCE = {
    "multibagger": "Research 0008: top 30 vs the equal-weight pond +8.7 %/yr (t 2.25) on survivors; honest DSR fails. "
                   "The forward books (pond / top 30 / price-only 30) started 2026-10-16 and are judged at 24 months.",
    "published": "The Track record page's own numbers: published top-10 picks since April 2026, Small +4.8 % over the "
                 "tier at 63 days, Mid −0.5 %. This book is those picks held as money.",
}
# Facts the test's numbers alone do not show.
MODEL_NOTES = {
    "mid_fast": "No factor cleared the bar before May 2026, so this book's test is mostly cash. Since then it runs on one factor, "
                "the consensus beat rate, whose estimates are not yet verified point-in-time, and more than a dozen names tie at "
                "the top, so the choice among them is arbitrary.",
    "mid_blend": "Before May 2026 the Fast half had no factors, so the test is mostly the Slow score on Blend's holding rule.",
}
BAR_LABELS = {"old": "Today's bar (|t| ≥ 2.5)", "fdr": "Multiple-testing bar", "long": "Long-side bar", "full": "All tests together"}
CONTROL_LABELS = {"ctl_slow_v2": "Slow v2, fixed recipe", "ctl_slow_icw": "Slow IC-weighted, no bar",
                  "ctl_blend": "The old blend", "ctl_fast_v1": "Fast v1, today's live weights"}


def load_selection():
    """The pre-registered test's result, for the page: one row per model and tier, and every bar side by side. Raises if
    the test or the scores are missing: a page of models without their evidence is the failure this page exists to stop."""
    r = json.loads(SELECTION.read_text())
    latest = pd.read_csv(LH / "model_select" / "model_factors.csv")
    latest = latest[latest["anchor"] == latest["anchor"].max()]
    rows = {}
    for tier in ("MID", "SMALL"):
        for model, method in r["chosen"].items():
            bk, g = r["books"][tier][method], r["grades"][tier][method]
            names = []
            f = latest[(latest["tier"] == tier) & (latest["method"] == model)]
            if len(f):
                names = [("−" if w < 0 else "") + c for c, w in json.loads(f["factors"].iloc[0]).items()]
            if model == "blend":
                names = ["the mean of Slow and Fast"]
            rows[f"{tier.lower()}_{model}"] = dict(
                tier=tier, model=model, excess=bk["excess_cagr"], t=bk["t"], worst=bk["worst_12m"], turnover=bk["turnover"], cost_bps=bk["costs_bps"],
                months_no_score=bk["months_no_score"], grade=g["grade"], dsr=g["dsr"], pbo=g["pbo"], beat_years=g["beat_years"], n_years=g["n_years"],
                beat_starts=g["beat_starts"], n_starts=g["n_starts"], holdout=r["holdout"].get(tier, {}).get(method, {}).get("excess"), factors=names)
    bars = []
    for model, chosen in (("slow", r["slow_bar"]), ("fast", r["fast_bar"])):
        for bar in ("old", "fdr", "long", "full"):
            m = f"{model}_{bar}"
            bars.append(dict(model=model.capitalize(), label=BAR_LABELS[bar], chosen=bar == chosen, control=False,
                             mid_x=r["books"]["MID"][m]["excess_cagr"], mid_t=r["books"]["MID"][m]["t"],
                             small_x=r["books"]["SMALL"][m]["excess_cagr"], small_t=r["books"]["SMALL"][m]["t"]))
    for m, label in CONTROL_LABELS.items():
        bars.append(dict(model="Control", label=label, chosen=False, control=True,
                         mid_x=r["books"]["MID"][m]["excess_cagr"], mid_t=r["books"]["MID"][m]["t"],
                         small_x=r["books"]["SMALL"][m]["excess_cagr"], small_t=r["books"]["SMALL"][m]["t"]))
    return dict(window=r["window"], computed=r["computed"], rows=rows, bars=bars)


def model_evidence(key, sel):
    """The card's 'what the test said' line for one of the three models, from the test's own numbers."""
    x = sel["rows"][key]
    held = "" if x["holdout"] is None else f" Held out from the decision, June to October 2026: {x['holdout'] * 100:+.1f} % over the index."
    note = f" {MODEL_NOTES[key]}" if key in MODEL_NOTES else ""
    return (f"Walk-forward test, June 2022 to June 2026, after costs and tax: {x['excess'] * 100:+.1f} %/yr over the index (t {x['t']:.2f}); "
            f"ahead in {x['beat_years']} of {x['n_years']} calendar years and from {x['beat_starts']} of {x['n_starts']} start months; "
            f"worst 12 months {x['worst'] * 100:+.1f} %. Grade {x['grade']}.{held}{note}")


# ── reading ────────────────────────────────────────────────────────────────────────────────────

def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def anchors():
    sc = pd.read_parquet(LH / MODELS_FILE, columns=["snapshot_date"])
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


def simulate(book_key, opt, ranks_by_anchor, prices, meta, trusts, bench_levels, all_anchors, asof, capital=CAPITAL,
             state=None):
    """One book under one option. ranks_by_anchor: {anchor: [(sleeve, {sid: rank}, N, sell_rank)]} — a book is one
    or two sleeves (published = Mid + Small halves). `state` = the frozen record of earlier anchors (positions,
    cash, trades, history, costs, realised, rotations): those months are not re-traded, only the anchors after
    state['last_anchor'] are. Returns the result and the new frozen state."""
    sleeves = {s for a in ranks_by_anchor.values() for s, _, _, _ in a}
    if state:
        cash, pos, trades, history = state["cash"], state["pos"], list(state["trades"]), list(state["history"])
        costs, realised, rotations = dict(state["costs"]), state["realised"], state["rotations"]
        todo = [a for a in all_anchors if a > state["last_anchor"]]
    else:
        cash = {s: capital / len(sleeves) for s in sleeves}
        pos = {}                      # sid -> dict(sleeve, units, cost_basis, bought, rank_at_buy, entry_close)
        trades, history = [], []
        costs = dict(total=0.0, stt=0.0, fees_other=0.0, spread_impact=0.0)
        realised = 0.0
        rotations = 0
        todo = list(all_anchors)

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

    for anchor in todo:
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

    frozen = dict(cash=cash, pos=pos, trades=trades, history=history, costs=costs, realised=realised, rotations=rotations,
                  last_anchor=max(all_anchors))
    # mark to the latest close
    final_nav = nav_at(asof)
    if history[-1]["date"] != asof:             # on an anchor day the anchor's own row is the mark
        history = history + [dict(date=asof, nav=round(final_nav), bench=round(bench_at(asof), 5))]
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
        n=len(holdings), cash=round(sum(cash.values())), history=history, holdings=holdings, trades=trades), frozen


# ── evidence: judge the score on the whole tier every month, not on one 20-name basket ──────────

NW_LAG = 3
LUCK_DRAWS = 5000


def load_labels():
    """Monthly anchor → next-anchor forward return per stock (data/lh/labels.parquet, pit.forward_returns)."""
    lb = pd.read_parquet(LH / "labels.parquet", columns=["sid", "snapshot_date", "cap_tier", "fwd_next_anchor"])
    return lb.dropna(subset=["fwd_next_anchor"])


_FULL = {}


def _panel_all(file):
    if file not in _FULL:
        _FULL[file] = pd.read_parquet(LH / file, columns=["sid", "snapshot_date", "cap_tier", "method", "score"])
    return _FULL[file]


def score_series(book_key, opt, con, label_anchors):
    """[(anchor, tier, Series score by sid)] for every anchor the option can score: the research panel for
    slow / fast options (avg3 = mean of the last three anchors), daily_picks for 'published', the desk's
    ranking for the multibagger book (score = -rank)."""
    b = BOOKS[book_key]
    out = []
    if b["kind"] in MODEL_KINDS:
        sc = _panel_all(opt["file"])
        sc = sc[(sc["method"] == opt["method"]) & (sc["cap_tier"] == b["tier"])]
        wide = sc.pivot_table(index="sid", columns="snapshot_date", values="score")
        if opt.get("avg3"):
            wide = wide.T.rolling(3, min_periods=1).mean().T.where(wide.notna())
        for a in wide.columns:
            if a in label_anchors:
                out.append((a, b["tier"], wide[a].dropna()))
    else:
        tiers = ("MID", "SMALL") if b["kind"] == "published" else ["MB"]
        for a in label_anchors:
            if b["kind"] == "mb":
                d, rk = mb_ranks(con, a)
                if d is None or d > a:
                    continue
                out.append((a, "MB", pd.Series({sid: -r for sid, r in rk.items()})))
            else:
                if a < "2026-04-09":
                    continue
                for t in tiers:
                    d, rk = published_ranks(con, t, a)
                    if d is None or (pd.Timestamp(a) - pd.Timestamp(d)).days > 7:
                        continue
                    out.append((a, t, pd.Series({sid: -r for sid, r in rk.items()})))
    return out


def evidence(book_key, opt, con, labels, N, asof):
    """Per month: rank IC of the score against next month's return over the whole tier, and the top-N
    basket's return minus the tier's (percentage points). Summary over the backtest months and the live
    months (anchors from START), Newey-West t on the IC."""
    label_anchors = sorted(labels["snapshot_date"].unique())
    rows = []
    for a, tier, sc in score_series(book_key, opt, con, label_anchors):
        lb = labels[labels["snapshot_date"] == a]
        if tier != "MB":
            lb = lb[lb["cap_tier"] == tier]
        m = lb.set_index("sid")["fwd_next_anchor"].to_frame("fwd").join(sc.rename("score"), how="inner")
        if len(m) < 30:
            continue
        ic = float(m["score"].rank().corr(m["fwd"].rank()))
        top = m.sort_values("score", ascending=False).head(N)["fwd"].mean()
        rows.append(dict(anchor=a, tier=tier, n=len(m), ic=round(ic, 4), spread=round(float(top - m["fwd"].mean()) * 100, 2)))
    if not rows:
        return None
    df = pd.DataFrame(rows).groupby("anchor").agg(ic=("ic", "mean"), spread=("spread", "mean"), n=("n", "sum")).reset_index()
    # the replay's live months start at the June anchor; 'as published' and the desk's own ranking have no
    # backtest at all (nothing was recomputed), so every month of theirs is live
    no_backtest = BOOKS[book_key]["kind"] in ("mb", "published")
    df["live"] = True if no_backtest else (df["anchor"] >= START)
    from tools.backtest_pit import _newey_west_se

    def summ(x):
        if x.empty:
            return dict(months=0)
        se = _newey_west_se(x["ic"].to_numpy(), NW_LAG) if len(x) > 2 else None
        return dict(months=int(len(x)), ic=round(float(x["ic"].mean()), 4), t=None if not se else round(float(x["ic"].mean() / se), 2),
                    hit=round(float((x["ic"] > 0).mean()), 3), spread=round(float(x["spread"].mean()), 2),
                    first=x["anchor"].iloc[0], last=x["anchor"].iloc[-1])
    return dict(all=summ(df), backtest=summ(df[~df["live"]]), live=summ(df[df["live"]]),
                months=[dict(anchor=r.anchor, ic=round(r.ic, 3), spread=round(r.spread, 2), live=bool(r.live)) for r in df.itertuples()],
                in_sample_before=None, N=N)


def luck(book_ret, N, tier_sids, prices, start, asof):
    """Where the book's return sits among LUCK_DRAWS random N-name baskets from the same tier over the same
    window: the percentile, and the 10th / 90th percentile of those baskets."""
    rets = []
    for sid in tier_sids:
        q0, q1 = prices.at(sid, start), prices.at(sid, asof)
        if q0 and q1:
            rets.append(q1[0] / q0[0] - 1)
    rets = np.asarray(rets)
    if len(rets) < N * 3:
        return None
    rng = np.random.default_rng(0)
    sims = np.array([rets[rng.choice(len(rets), N, replace=False)].mean() for _ in range(LUCK_DRAWS)])
    return dict(pct=round(float((sims < book_ret).mean()), 3), p10=round(float(np.quantile(sims, 0.1)), 4),
                p90=round(float(np.quantile(sims, 0.9)), 4), mean=round(float(sims.mean()), 4), n_tier=int(len(rets)), draws=LUCK_DRAWS)


def months_between(d0, d1):
    a, b = pd.Timestamp(d0), pd.Timestamp(d1)
    return (b.year - a.year) * 12 + (b.month - a.month) - (b.day < a.day)


def ranks_for(book_key, opt, con, all_anchors):
    """{anchor: [(sleeve, ranks, N, sell_rank)]} for one book under one option; also the score dates used."""
    b = BOOKS[book_key]
    out, dates = {}, {}
    for a in all_anchors:
        if b["kind"] in MODEL_KINDS:
            d, rk = a, panel_ranks(opt, b["tier"], a)
            out[a] = [(b["tier"], rk, b["N"], b["sell"])]
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


def load_state(rebuild=False):
    if rebuild or not STATE.exists():
        return dict(created=date.today().isoformat(), replay_until=None, books={})
    return json.loads(STATE.read_text())


def run(smoke=False, rebuild=False):
    con = ro()
    asof = con.execute("SELECT MAX(date) FROM stock_prices").fetchone()[0]
    all_anchors = anchors()
    st = load_state(rebuild) if not smoke else dict(created=date.today().isoformat(), replay_until=None, books={})
    if st["replay_until"] is None:
        st["replay_until"] = all_anchors[-1]          # the first run replays every anchor so far
    px, sessions, bench_levels = load_prices(con, asof)
    meta, trusts = stock_meta(con)
    prices = Prices(px, sessions)
    labels = load_labels()
    sel = load_selection()
    books = {}
    for key, b in BOOKS.items():
        opts = OPTIONS[b["kind"]][:1] if smoke else OPTIONS[b["kind"]]
        variants = {}
        for opt in opts:
            rk, dates = ranks_for(key, opt, con, all_anchors)
            prior = st["books"].get(key, {}).get(opt["key"])
            res, frozen = simulate(key, opt, rk, prices, meta, trusts, bench_levels, all_anchors, asof, state=prior)
            st["books"].setdefault(key, {})[opt["key"]] = frozen
            N = opt.get("N", b["N"])
            res.update(key=opt["key"], label=opt["label"], why=opt.get("why", ""), score_dates=dates,
                       evidence=evidence(key, opt, con, labels, N, asof))
            first = rk[all_anchors[0]]
            lucks = [luck(res["ret"], N, list(r.keys()), prices, all_anchors[0], asof) for _, r, _, _ in first]
            lucks = [l for l in lucks if l]
            res["luck"] = None if not lucks else dict(pct=round(float(np.mean([l["pct"] for l in lucks])), 3),
                                                      p10=round(float(np.mean([l["p10"] for l in lucks])), 4),
                                                      p90=round(float(np.mean([l["p90"] for l in lucks])), 4),
                                                      n_tier=sum(l["n_tier"] for l in lucks), draws=LUCK_DRAWS)
            variants[opt["key"]] = res
            print(f"{key:12s} {opt['key']:12s} nav {res['nav']:>10,.0f}  ret {res['ret']:+.1%}  bench {res['bench_ret']:+.1%}  "
                  f"rot {res['rotations']}  stt ₹{res['costs']['stt']:,.0f}  tax(if sold) ₹{res['tax_if_sold']:,.0f}")
        default = opts[0]["key"]
        best = max(variants, key=lambda k: variants[k]["ret"])
        books[key] = dict(label=b["label"], tier=b["tier"], kind=b["kind"], rule=b["rule"], bench=b["bench"],
                          bench_label=" / ".join(f"{int(w * 100)} % {s}" for s, w in b["bench"].items()) if len(b["bench"]) > 1
                          else next(iter(b["bench"])), N=b["N"], default=default, best_in_window=best,
                          evidence=model_evidence(key, sel) if b["kind"] in MODEL_KINDS else EVIDENCE[key],
                          grade=sel["rows"][key]["grade"] if b["kind"] in MODEL_KINDS else None, option_order=[o["key"] for o in opts], variants=variants)
    con.close()
    out = dict(asof=asof, start=all_anchors[0], anchors=all_anchors, capital=CAPITAL, stcg=STCG, stt=STT,
               floor_inr=FLOOR_INR, computed=date.today().isoformat(), replay_until=st["replay_until"],
               record_since=st["created"], books=books, book_order=list(books), selection=sel,
               notes=["Evidence per option: every month the score is judged on the WHOLE tier (rank IC against the next "
                      "month's return, and the top-N basket's return minus the tier's), from the first walk-forward month "
                      "in 2022 to the last matured month; live months are the anchors from June 2026. Luck: the book's "
                      "return against 5,000 random baskets of the same size from the same tier over the same window.",
                      "Fills at the anchor close; no slippage beyond the modelled half-spread and impact.",
                      "Benchmarks are price indices (no dividends); the books' closes include dividends.",
                      "Slow, Fast and Blend choose their factors each month from earlier data only. The bars themselves were chosen "
                      "on 2022-06 to 2026-06 (tools/model_select.py); June 2026 onward was held out of that decision."])
    if not smoke:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(st, indent=1, default=str))
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
    ap.add_argument("--rebuild", action="store_true", help="discard the frozen record and replay from June")
    a = ap.parse_args()
    run(smoke=a.smoke, rebuild=a.rebuild)


if __name__ == "__main__":
    main()
