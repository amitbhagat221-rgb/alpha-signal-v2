"""
Plan 0026 phase 1d.8 — the multibagger desk's three forward paper books and their kill rules.
(READ-ONLY on the DB; state in data/paper/mb_books.json, report in output/mb_paper/latest.{json,md}.)

Why (research 0008 section 6): the desk's score and its human stage cannot be backtested honestly, so they are
graded forward, from day one, against two mechanical baselines:

  pond    equal weight every `thesis_pond` stock of the latest multibagger_scores run (gates only, no score)
  top30   equal weight the 30 best thesis_rank of that run
  amit10  equal weight the names with status 'held' in multibagger_book (cash while there are none)

Each book starts with `config.MB_THESIS["book_inr"]` (Rs 30 lakh). pond and top30 are rebuilt from the latest
run on the yearly anniversary of the start (checked at the monthly mark, so within a month of it); amit10
follows the book on every run: a name that became held is bought, one that left is sold, at that day's close,
and the book is re-equalised whenever its set changes. Prices are closes from stock_prices carried through
splits and bonuses (corporate_adjustments SPLIT/BONUS factors after the last mark, the same basis as the
cockpit's Held tab). Every trade pays tools.lh_costs.one_way_cost_bps at the amount traded, with the stock's
own 20-session ADTV. The benchmark is NIFTY SMALLCAP 250 (price index, nse_index_history).

Kill rules (research 0008 section 6), computed on every mark with value, threshold and state
(ok / warn / kill, or early before they can be judged); thresholds are config.MB_THESIS["kill"]:
  score     after 24 months top30 trails pond by more than 5 points cumulative
  human     after 24 months amit10 trails top30 by more than 10 points, or fewer of its names are up 50 %+
  risk      any rolling 12-month top30 return minus the benchmark's below -35 %: halt new buying, unless the
            pond itself rose more than 50 % in that window (momentum-crash exemption, research 0008 round 2)
  capacity  any amit10 / top30 position above 10 % of its 20-day ADTV: stop adding
A kill never sells anything; risk and capacity kills stop BUYING in the paper books (the other kills are advice).
The name-level process kills (auditor resignation, pledge, GSM...) stay with the Watch tab.

Paper only: no orders are placed anywhere.

Usage:
  run.sh mb_paper start          # first time: start all three books today (refuses if state exists)
  run.sh mb_paper mark           # monthly: mark to market, follow the book, rebalance if due
  run.sh mb_paper status         # rewrite latest.json from the saved state, no trading
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import MB_THESIS  # noqa: E402
from output import mb_capacity  # noqa: E402

DB = Path(os.environ.get("ALPHA_DB", PROJECT_ROOT / "data" / "alpha_signal.db"))
STATE = DB.parent / "paper" / "mb_books.json"
OUT = DB.parent.parent / "output" / "mb_paper"
BENCH = "NIFTY SMALLCAP 250"
PRICE_LOOKBACK_DAYS = 10     # a stock whose last close is older than this has no price today (suspended)
BOOKS = {
    "pond": dict(label="Pond", rule="Every name that passed the safety gates, equal weight. No score."),
    "top30": dict(label="Top 30", rule="The 30 best thesis ranks, equal weight."),
    "amit10": dict(label="Amit 10", rule="The names you hold, equal weight; cash while there are none."),
}
YEARLY = ("pond", "top30")


# ── reading the DB ──────────────────────────────────────────────────────────────────────────────

def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def read(sql, params=None):
    """list[dict] on a read-only connection (the reader output.mb_capacity takes)."""
    con = ro()
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, params or [])]
    finally:
        con.close()


def _in(n):
    return ",".join("?" * n)


def _chunks(xs, n=500):
    xs = list(xs)
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def latest_scores():
    """(snapshot_date, pond sids, top sids): the newest multibagger_scores run that has a thesis, the pond
    (thesis_pond = 1) and the `paper_top_n` best thesis_rank of it. Raises on an empty run."""
    snap = read("SELECT MAX(snapshot_date) AS d FROM multibagger_scores WHERE thesis_score IS NOT NULL")[0]["d"]
    if not snap:
        raise SystemExit("mb_paper: no thesis run in multibagger_scores yet")
    pond = read("SELECT sid, thesis_rank FROM multibagger_scores WHERE snapshot_date = ? AND thesis_pond = 1 "
                "AND thesis_score IS NOT NULL ORDER BY thesis_rank, sid", [snap])
    if not pond:
        raise SystemExit(f"mb_paper: the {snap} run has an empty pond")
    sids = [r["sid"] for r in pond]
    return snap, sids, sids[:MB_THESIS["paper_top_n"]]


def held_sids():
    try:
        return [r["sid"] for r in read("SELECT sid FROM multibagger_book WHERE status = 'held' ORDER BY sid")]
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            return []
        raise


def closes(sids, asof):
    """{sid: (date, close)}: the last close on or before asof, no older than PRICE_LOOKBACK_DAYS."""
    lo = (date.fromisoformat(asof) - timedelta(days=PRICE_LOOKBACK_DAYS)).isoformat()
    out = {}
    for ch in _chunks(sids):
        for r in read(f"SELECT sid, date, close FROM stock_prices WHERE close > 0 AND date <= ? AND date >= ? "
                      f"AND sid IN ({_in(len(ch))}) ORDER BY date", [asof, lo, *ch]):
            out[r["sid"]] = (r["date"], r["close"])
    return out


def split_factor(sids, after, upto):
    """{sid: product of SPLIT / BONUS factors with after < ex_date <= upto} (corporate_adjustments: factor < 1
    multiplies pre-ex prices). Only sids with an event appear."""
    out = {}
    for ch in _chunks(sids):
        for r in read(f"SELECT sid, factor FROM corporate_adjustments WHERE ex_date > ? AND ex_date <= ? "
                      f"AND (inds LIKE '%SPLIT%' OR inds LIKE '%BONUS%') AND sid IN ({_in(len(ch))})",
                      [after, upto, *ch]):
            out[r["sid"]] = out.get(r["sid"], 1.0) * r["factor"]
    return out


def bench_level(asof):
    r = read("SELECT trade_date, close FROM nse_index_history WHERE index_symbol = ? AND close > 0 AND trade_date <= ? "
             "ORDER BY trade_date DESC LIMIT 1", [BENCH, asof])
    if not r:
        raise SystemExit(f"mb_paper: no {BENCH} level on or before {asof}")
    return float(r[0]["close"]), r[0]["trade_date"]


def tiers(sids):
    out = {}
    for ch in _chunks(sids):
        out.update({r["sid"]: r["cap_tier"] for r in read(f"SELECT sid, cap_tier FROM stocks WHERE sid IN ({_in(len(ch))})", ch)})
    return out


def names(sids):
    out = {}
    for ch in _chunks(sids):
        out.update({r["sid"]: r["ticker"] for r in read(f"SELECT sid, ticker FROM stocks WHERE sid IN ({_in(len(ch))})", ch)})
    return out


def cost_bps(adv, price, trade_inr, tier):
    """One-way cost of a trade of `trade_inr` (tools.lh_costs, calibrated on the real account)."""
    from tools.lh_costs import one_way_cost_bps
    return one_way_cost_bps(adv, price, trade_inr, tier if tier in ("LARGE", "MID", "SMALL", "MICRO") else "SMALL")


# ── dates ───────────────────────────────────────────────────────────────────────────────────────

def months_between(d0, d1):
    from tools.paper_sleeve import months_between as mb
    return mb(d0, d1)


# ── the books ───────────────────────────────────────────────────────────────────────────────────

def nav_of(book):
    return book["cash"] + sum(p["value"] for p in book["positions"].values())


def _ret(p):
    return (p["value"] + p["proceeds"]) / p["invested"] - 1 if p["invested"] > 0 else 0.0


def revalue(st, asof):
    """Carry every position to its latest close, through splits / bonuses since the last mark. A position
    whose stock has no recent close keeps its value (suspended)."""
    sids = sorted({s for b in st["books"].values() for s in b["positions"]})
    px = closes(sids, asof)
    for b in st["books"].values():
        by_date = {}
        for sid, p in b["positions"].items():
            if sid in px and px[sid][0] > p["last_date"]:
                by_date.setdefault(p["last_date"], []).append(sid)
        for last_date, group in by_date.items():
            f = split_factor(group, last_date, asof)
            for sid in group:
                p = b["positions"][sid]
                p["value"] *= px[sid][1] / (p["last_close"] * f.get(sid, 1.0))
                p["last_close"], p["last_date"] = px[sid][1], px[sid][0]
    return px


def _sell(st, k, sid, amount, ctx, asof, why):
    """Sell `amount` ₹ of value (all of it when >= the position). Returns the cash received."""
    b = st["books"][k]
    p = b["positions"][sid]
    amount = min(amount, p["value"])
    if amount <= 0:
        return 0.0
    bps = cost_bps(ctx["adv"].get(sid), p["last_close"], amount, ctx["tier"].get(sid))
    got = amount * (1 - bps / 1e4)
    p["value"] -= amount
    p["proceeds"] += got
    b["cash"] += got
    st["trades"].append(dict(date=asof, book=k, sid=sid, side="SELL", value=round(amount, 2), cost_bps=round(bps, 1), why=why))
    if p["value"] <= 1e-6:
        b["closed"].append(dict(sid=sid, entry_date=p["entry_date"], exit_date=asof, ret=round(_ret(p), 4)))
        del b["positions"][sid]
    return got


def _buy(st, k, sid, amount, ctx, asof, why):
    b = st["books"][k]
    amount = min(amount, b["cash"])
    if amount <= 0:
        return 0.0
    d, close = ctx["px"][sid]
    bps = cost_bps(ctx["adv"].get(sid), close, amount, ctx["tier"].get(sid))
    p = b["positions"].setdefault(sid, dict(entry_date=asof, entry_close=close, invested=0.0, proceeds=0.0, value=0.0,
                                            last_date=d, last_close=close))
    p["value"] += amount * (1 - bps / 1e4)
    p["invested"] += amount
    b["cash"] -= amount
    st["trades"].append(dict(date=asof, book=k, sid=sid, side="BUY", value=round(amount, 2), cost_bps=round(bps, 1), why=why))
    return amount


def rebalance_to(st, k, targets, ctx, asof, why, halt_buys=False):
    """Equal weight `targets` (sids) in book k: sell what left the list, trim what is over, then buy what is
    under with the cash. A target with no close today is skipped (listed in the returned `skipped`).
    halt_buys (risk / capacity kill) sells but buys nothing. Returns the skipped sids."""
    b = st["books"][k]
    have_px = [s for s in targets if s in ctx["px"]]
    skipped = [s for s in targets if s not in ctx["px"]]
    for sid in [s for s in b["positions"] if s not in targets]:
        if sid in ctx["px"]:
            _sell(st, k, sid, b["positions"][sid]["value"], ctx, asof, why)
    if not have_px:
        return skipped
    each = nav_of(b) / len(have_px)
    for sid in have_px:
        over = b["positions"].get(sid, {}).get("value", 0.0) - each
        if over > 0.01 * each:
            _sell(st, k, sid, over, ctx, asof, why)
    if halt_buys:
        return skipped
    for sid in have_px:
        under = each - b["positions"].get(sid, {}).get("value", 0.0)
        if under > 0.01 * each:
            _buy(st, k, sid, under, ctx, asof, why)
    return skipped


def _context(st, extra, asof):
    sids = sorted({s for b in st["books"].values() for s in b["positions"]} | set(extra))
    return dict(px=closes(sids, asof), adv=mb_capacity.adv_inr(read, sids, asof), tier=tiers(sids))


# ── kill rules ──────────────────────────────────────────────────────────────────────────────────

def _cum(hist, k):
    return hist[-1]["nav"][k] / hist[0]["nav"][k] - 1


def _hit_rate(book):
    rets = [_ret(p) for p in book["positions"].values()] + [c["ret"] for c in book["closed"]]
    return None if not rets else sum(r >= MB_THESIS["kill"]["hit_up"] for r in rets) / len(rets)


def _state(value, threshold, warn_at):
    return "kill" if value < threshold else "warn" if value < warn_at else "ok"


def evaluate(st, hist, adv):
    """The four kill rules on the history `hist` (the last row is now) and the books in `st`. Returns a list of
    dicts {key, label, value, threshold, state, state_text, detail}."""
    kc, months = MB_THESIS["kill"], months_between(st["start"], hist[-1]["date"])
    wf = kc["warn_fraction"]
    kills = []

    def add(key, label, value, threshold, state, text, detail):
        kills.append(dict(key=key, label=label, value=value, threshold=threshold, state=state, state_text=text, detail=detail))

    early = months < kc["months_to_judge"]
    et = f"too early ({months} months)"
    # score kill
    if early:
        add("score", "Score", None, kc["score_pts"], "early", et,
            f"The score kill fires if, after {kc['months_to_judge']} months, the top 30 trail the pond by more than "
            f"{abs(kc['score_pts']):g} points cumulative. Judged from month {kc['months_to_judge']}; now {months}.")
    else:
        v = round((_cum(hist, "top30") - _cum(hist, "pond")) * 100, 1)
        s = _state(v, kc["score_pts"], kc["score_pts"] * wf)
        add("score", "Score", v, kc["score_pts"], s, {"ok": "ok", "warn": "watch", "kill": "KILL"}[s],
            f"Top 30 minus pond, cumulative since start: {v:+.1f} points; kill below {kc['score_pts']:g}. "
            "A kill means the score adds nothing: hold the pond basket or an index instead.")
    # human kill
    a, t = st["books"]["amit10"], st["books"]["top30"]
    never = not a["positions"] and not a["closed"]
    hit_a, hit_t = _hit_rate(a), _hit_rate(t)
    if early or never:
        add("human", "Human", None, kc["human_pts"], "early", "no names held yet" if never and not early else et,
            f"The human kill fires if, after {kc['months_to_judge']} months, the names you hold trail the top 30 by more than "
            f"{abs(kc['human_pts']):g} points, or fewer of them are up {kc['hit_up'] * 100:.0f} %. "
            + ("You hold no names yet." if never else f"Now {months} months."))
    else:
        v = round((_cum(hist, "amit10") - _cum(hist, "top30")) * 100, 1)
        worse_hits = hit_a is not None and hit_t is not None and hit_a < hit_t
        s = "kill" if v < kc["human_pts"] or worse_hits else _state(v, kc["human_pts"], kc["human_pts"] * wf)
        add("human", "Human", v, kc["human_pts"], s, {"ok": "ok", "warn": "watch", "kill": "KILL"}[s],
            f"Amit 10 minus top 30, cumulative: {v:+.1f} points (kill below {kc['human_pts']:g}). Share of names up "
            f"{kc['hit_up'] * 100:.0f} %+: yours {hit_a * 100:.0f} % against {hit_t * 100:.0f} % for the top 30"
            + (" (below it is a kill)." if worse_hits else "."))
    # risk kill: worst rolling 12-month excess of top30 over the benchmark. Momentum-crash exemption (research 0008
    # round 2: the backtest's worst window, Apr 2020 → Apr 2021, was a junk rally in which the pond rose +146 % and
    # the lowest-momentum names led): a window in which the pond itself rose more than `risk_crash_pond_up` does not halt.
    worst, worst_all, crash = None, None, None
    for i in range(len(hist)):
        js = [j for j in range(i) if months_between(hist[j]["date"], hist[i]["date"]) >= 12]
        if js:
            j = js[-1]
            ex = (hist[i]["nav"]["top30"] / hist[j]["nav"]["top30"]) - (hist[i]["bench"] / hist[j]["bench"])
            pond_up = hist[i]["nav"]["pond"] / hist[j]["nav"]["pond"] - 1
            worst_all = ex if worst_all is None else min(worst_all, ex)
            if pond_up > kc["risk_crash_pond_up"]:
                if ex < kc["risk_excess"] and (crash is None or ex < crash[0]):
                    crash = (ex, pond_up, hist[i]["date"])
                continue
            worst = ex if worst is None else min(worst, ex)
    if worst_all is None:
        add("risk", "Risk", None, kc["risk_excess"], "ok", "ok",
            f"Worst rolling 12-month return of the top 30 minus {BENCH}; halts new buying below "
            f"{kc['risk_excess'] * 100:.0f} %. Needs 12 months of history; now {months}.")
    else:
        w = worst if worst is not None else 0.0
        v = round(w * 100, 1)
        s = _state(w, kc["risk_excess"], kc["risk_excess"] * wf)
        note = ("" if crash is None else
                f" Exempt: the window to {crash[2]} reached {crash[0] * 100:+.1f} points while the pond itself rose "
                f"{crash[1] * 100:+.0f} % — a momentum crash (junk rally), not a halt.")
        add("risk", "Risk", v, kc["risk_excess"] * 100, s, {"ok": "ok", "warn": "watch", "kill": "KILL"}[s],
            f"Worst rolling 12-month top 30 minus {BENCH}: {v:+.1f} points; halts new buying below "
            f"{kc['risk_excess'] * 100:.0f}% unless the pond rose more than {kc['risk_crash_pond_up'] * 100:.0f} % in "
            f"the same window. A redesign review, never a forced sale into a lower circuit.{note}")
    # capacity kill: the biggest position as a share of its 20-day ADTV
    worst_share, worst_sid, unknown = None, None, 0
    for k in ("top30", "amit10"):
        for sid, p in st["books"][k]["positions"].items():
            if not adv.get(sid):
                unknown += 1
                continue
            sh = p["value"] / adv[sid]
            if worst_share is None or sh > worst_share:
                worst_share, worst_sid = sh, sid
    if worst_share is None:
        add("capacity", "Capacity", None, kc["capacity_share"] * 100, "warn" if unknown else "ok", "watch" if unknown else "ok",
            f"Stops adding if any top 30 or held name is above {kc['capacity_share'] * 100:.0f} % of its 20-day traded value."
            + (f" {unknown} positions have no traded value." if unknown else ""))
    else:
        s = "kill" if worst_share > kc["capacity_share"] else "warn" if worst_share > MB_THESIS["max_adv_share"] else "ok"
        add("capacity", "Capacity", round(worst_share * 100, 1), kc["capacity_share"] * 100, s,
            {"ok": "ok", "warn": "watch", "kill": "KILL"}[s],
            f"Biggest position is {worst_share * 100:.1f} % of its 20-day median traded value ({worst_sid}); "
            f"stop adding above {kc['capacity_share'] * 100:.0f} %, watch above {MB_THESIS['max_adv_share'] * 100:.0f} %."
            + (f" {unknown} positions have no traded value." if unknown else ""))
    return kills


def halted(kills):
    return any(k["state"] == "kill" and k["key"] in ("risk", "capacity") for k in kills)


# ── commands ────────────────────────────────────────────────────────────────────────────────────

def load_state():
    if not STATE.exists():
        raise SystemExit("mb_paper: paper books not started — run `run.sh mb_paper start`")
    return json.loads(STATE.read_text())


def save_state(st):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=1))


def _row(st, asof, px_date, bench):
    return dict(date=asof, price_date=px_date, bench_date=bench[1], bench=bench[0],
                nav={k: round(nav_of(b), 2) for k, b in st["books"].items()},
                n={k: len(b["positions"]) for k, b in st["books"].items()})


def _with_row(hist, row):
    """A copy of the history with `row` as its last entry (it replaces a row of the same date)."""
    return (hist[:-1] if hist and hist[-1]["date"] == row["date"] else list(hist)) + [row]


def _record(st, row):
    st["history"] = _with_row(st["history"], row)


def start(asof):
    if STATE.exists():
        raise SystemExit(f"mb_paper: {STATE} exists — the books are already started")
    snap, pond, top = latest_scores()
    held = held_sids()
    bench = bench_level(asof)
    st = dict(created=date.today().isoformat(), start=asof, score_date=snap, book_inr=MB_THESIS["book_inr"],
              bench_start=bench[0], bench_start_date=bench[1], last_rebalance={k: asof for k in YEARLY},
              books={k: dict(cash=float(MB_THESIS["book_inr"]), positions={}, closed=[]) for k in BOOKS},
              history=[], trades=[], skipped={})
    ctx = _context(st, set(pond) | set(held), asof)
    for k, targets in (("pond", pond), ("top30", top), ("amit10", held)):
        st["skipped"][k] = rebalance_to(st, k, targets, ctx, asof, "start")
    for k in ("pond", "top30"):
        if not st["books"][k]["positions"]:
            raise SystemExit(f"mb_paper: {k} bought nothing (no closes on or before {asof}) — refusing to start")
    px_date = max(d for d, _ in ctx["px"].values())
    _record(st, _row(st, asof, px_date, bench))
    save_state(st)
    return report(st, asof)


def mark(asof):
    st = load_state()
    snap, pond, top = latest_scores()
    held = held_sids()
    bench = bench_level(asof)
    revalue(st, asof)
    ctx = _context(st, set(pond) | set(held), asof)
    px_date = max((d for d, _ in ctx["px"].values()), default=asof)
    pre = _with_row(st["history"], _row(st, asof, px_date, bench))
    stop = halted(evaluate(st, pre, ctx["adv"]))
    why = "yearly rebuild"
    for k, targets in (("pond", pond), ("top30", top)):
        if months_between(st["last_rebalance"][k], asof) >= 12:
            st["skipped"][k] = rebalance_to(st, k, targets, ctx, asof, why, halt_buys=stop)
            st["last_rebalance"][k] = asof
    if set(held) != set(st["books"]["amit10"]["positions"]):
        st["skipped"]["amit10"] = rebalance_to(st, "amit10", held, ctx, asof, "book changed", halt_buys=stop)
    st["score_date"] = snap
    _record(st, _row(st, asof, px_date, bench))
    save_state(st)
    return report(st, asof, halt=stop)


def status(asof):
    st = load_state()
    return report(st, st["history"][-1]["date"] if asof is None else asof)


def _pct(x):
    return round(x * 100, 1)


def build_report(st, asof, adv, halt=None):
    """The cockpit's file (config.FILE_OUTPUTS `_file_mb_paper`): books, kill rules, bench, halted flag."""
    hist = st["history"]
    h0, h1 = hist[0], hist[-1]
    kills = evaluate(st, hist, adv)
    bench_ret = h1["bench"] / st["bench_start"] - 1
    tick = names(sorted({s for b in st["books"].values() for s in b["positions"]}))
    books = []
    for k, meta in BOOKS.items():
        b = st["books"][k]
        nav = h1["nav"][k]
        ret = nav / st["book_inr"] - 1
        pos = [dict(sid=s, ticker=tick.get(s, s), entry_date=p["entry_date"], value=round(p["value"], 2), ret=_pct(_ret(p)))
               for s, p in sorted(b["positions"].items(), key=lambda kv: -kv[1]["value"])]
        note = None
        if k == "amit10" and not b["positions"]:
            note = "in cash, no held names"
        elif st["skipped"].get(k):
            note = f"{len(st['skipped'][k])} skipped, no close"
        books.append(dict(key=k, label=meta["label"], rule=meta["rule"], nav=round(nav, 2), nav_text=mb_capacity.inr_short(nav),
                          cash=round(b["cash"], 2), ret_pct=_pct(ret), vs_bench_pts=_pct(ret - bench_ret),
                          n=len(pos), note=note, positions=pos))
    return dict(asof=asof, start=st["start"], months=months_between(st["start"], h1["date"]), price_date=h1["price_date"],
                score_date=st["score_date"], book_inr=st["book_inr"], book_text=mb_capacity.inr_short(st["book_inr"]),
                bench=BENCH, bench_ret_pct=_pct(bench_ret), books=books, kills=kills,
                halted=halted(kills) if halt is None else halt,
                history=[dict(date=h["date"], nav=h["nav"], bench=round(h["bench"] / st["bench_start"], 6)) for h in hist])


def report(st, asof, halt=None):
    sids = sorted({s for k in ("top30", "amit10") for s in st["books"][k]["positions"]})
    rep = build_report(st, asof, mb_capacity.adv_inr(read, sids, asof), halt)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(rep, indent=1))
    md = [f"# Multibagger paper books — {rep['asof']} (prices {rep['price_date']}, scores {rep['score_date']})", "",
          f"Started {rep['start']} · {rep['months']} months · each book {rep['book_text']} · "
          f"{BENCH} {rep['bench_ret_pct']:+.1f} %" + (" · **NEW BUYING HALTED**" if rep["halted"] else ""), ""]
    for b in rep["books"]:
        md.append(f"- **{b['label']}** {b['ret_pct']:+.1f} % ({b['vs_bench_pts']:+.1f} pts vs index) · NAV {b['nav_text']} · "
                  f"{b['n']} names" + (f" · {b['note']}" if b["note"] else ""))
    md += ["", "## Kill rules", ""]
    for k in rep["kills"]:
        md.append(f"- **{k['label']}: {k['state_text']}** — {k['detail']}")
    (OUT / "latest.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["start", "mark", "status"])
    ap.add_argument("--asof", default=None, help="YYYY-MM-DD (default today; status: the last mark)")
    a = ap.parse_args()
    today = a.asof or date.today().isoformat()
    if a.cmd == "start":
        start(today)
    elif a.cmd == "mark":
        mark(today)
    else:
        status(a.asof)


if __name__ == "__main__":
    main()
