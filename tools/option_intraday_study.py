"""
Alpha Signal v2 — intraday study of stops, wings and sizing for the option paper book.

Pre-registered 2026-10-21 (docs/studies/option-stops-wings-preregistration-2026-10.md, committed
before any result). READ-ONLY: reads fno_bhav (sqlite mode=ro) and the 1-minute archive
(sources.hf_options_1m, data/intraday/options_1m); writes nothing but an optional CSV/markdown you name.

Fixed by the pre-registration, not tunable here:
  entry     the paper book's strikes (0.05 delta from that day's fno_bhav chain, option_book picker),
            at the AVERAGE of the 1-minute closes stamped 15:20-15:29 on the entry day (2 sessions before expiry)
  variants  baseline | premium stop k=2,3 per leg | index stop 0.5 % | wings 2/3/4 % | wings 3 % + premium stop 3x
  costs     option_book.leg_cost (1 % slippage per leg per side, brokerage, exchange, STT, stamp); a stop pays
            the exit; long wings that finish in the money pay STT on exercise (as tools/option_premium_backtest)
  settle    option_book: intrinsic on the expiry-day underlying_price in fno_bhav
  margin    naked: 12 % of the forward; hedged: (wing width - net credit) + exposure margin 2 % of notional on
            each short leg (--elm-legs 1 charges it once)
  sizing    A: floor(capital / margin per lot); B: floor(10 % of capital / worst-case loss per lot)

Interpretations where the pre-registration is silent (also written in the study doc):
  * a stop is monitored from the first session AFTER the entry day (entry is at 15:20-15:29);
  * bars exist only for minutes that traded: "session opens above the stop" = the leg's first print of the
    session has open >= stop (gap-through, fill at that open);
  * index-stop exit prices: the leg's last print at or before the trigger minute (its first print of the day
    when none yet / on a gap), never below intrinsic at the trigger index level;
  * sizing B for the unhedged variants uses the BASELINE's worst observed loss per unit (points), converted
    with each trade's own lot, so every unhedged variant risks the same budget and the stop's effect is visible.

Usage:
  python -m tools.option_intraday_study --underlying NIFTY --variant baseline
  python -m tools.option_intraday_study --underlying both --variant all --report
  python -m tools.option_intraday_study --smoke        # three trades, with the fills printed
"""

from __future__ import annotations

import argparse
import math
import sqlite3
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

import option_book as ob
from config import DB_PATH
from option_book import MARGIN_STRANGLE_PCT, SLIP, STT_EXERCISE, leg_cost, nearest, slice_deltas
from sources import hf_options_1m as hf

# ── pre-registered constants ──
DELTA = 0.05
WIN0, WIN1 = 15 * 60 + 20, 15 * 60 + 29        # entry window, minute of day (bars stamped 15:20 … 15:29)
OPEN0 = 9 * 60 + 15
STOP_KS = (2, 3)
INDEX_BAND = 0.005
WING_PCTS = (0.02, 0.03, 0.04)
ELM_PCT = 0.02                                  # exposure margin, of notional, per short leg
ELM_LEGS = 2                                    # legs it is charged on (--elm-legs)
CAPITAL = 3_500_000.0                           # ₹35 L
WORST_CASE_SHARE = 0.10                         # sizing B: 10 % of capital
VARIANTS = ("baseline_vwap", "baseline", "pstop2", "pstop3", "istop", "wing2", "wing3", "wing4", "wing3_pstop3")
NAKED = ("baseline_vwap", "baseline", "pstop2", "pstop3", "istop")
SPLITS = (("2021-23", "2021-01-01", "2024-01-01"), ("2024-26", "2024-01-01", "2027-01-01"))


# ───────────────────────────── minute-frame helpers (pure; tested) ─────────────────────────────

def minute_of_day(ts):
    return ts.dt.hour * 60 + ts.dt.minute


def window_price(bars, day):
    """(price, how): average of the 1-minute closes stamped 15:20-15:29 on `day`.
    When the leg did not print in the window: its last close before 15:20 that day ('last_before'), else None."""
    d = bars[bars["trading_day"] == day]
    if d.empty:
        return None, "none"
    m = minute_of_day(d["ts"])
    w = d[(m >= WIN0) & (m <= WIN1)]
    if len(w):
        return float(w["close"].mean()), "window"
    p = d[m < WIN0]
    if len(p):
        return float(p["close"].iloc[-1]), "last_before"
    return None, "none"


def premium_stop(bars, entry_day, entry_px, k, until="9999"):
    """First stop on a short leg: the first 1-minute close >= k x entry price on a session after the entry day;
    if a session's first print already opens at or above the stop, exit at that open (gap-through).
    Returns {'ts', 'day', 'px', 'gap'} or None."""
    b = bars[(bars["trading_day"] > entry_day) & (bars["trading_day"] <= until)]
    if b.empty:
        return None
    stop = k * entry_px
    first = (b["trading_day"] != b["trading_day"].shift()).to_numpy()
    gap = first & (b["open"].to_numpy() >= stop)
    hit = gap | (b["close"].to_numpy() >= stop)
    if not hit.any():
        return None
    i = int(hit.argmax())
    row = b.iloc[i]
    return {"ts": row["ts"], "day": row["trading_day"], "px": float(row["open"] if gap[i] else row["close"]),
            "gap": bool(gap[i])}


def index_stop(idx, entry_day, k_call, k_put, band=INDEX_BAND, until="9999"):
    """First 1-minute index close within `band` of either short strike (>= Kc(1-band) or <= Kp(1+band)) on a
    session after the entry day; a session whose first bar already opens inside the zone exits at that open.
    Returns {'ts', 'day', 'level', 'gap'} or None."""
    b = idx[(idx["trading_day"] > entry_day) & (idx["trading_day"] <= until) & (minute_of_day(idx["ts"]) >= OPEN0)]
    if b.empty:
        return None
    hi, lo = k_call * (1 - band), k_put * (1 + band)
    first = (b["trading_day"] != b["trading_day"].shift()).to_numpy()
    gap = first & ((b["open"].to_numpy() >= hi) | (b["open"].to_numpy() <= lo))
    hit = gap | (b["close"].to_numpy() >= hi) | (b["close"].to_numpy() <= lo)
    if not hit.any():
        return None
    i = int(hit.argmax())
    row = b.iloc[i]
    return {"ts": row["ts"], "day": row["trading_day"], "level": float(row["open"] if gap[i] else row["close"]),
            "gap": bool(gap[i])}


def price_at(bars, ts, gap, floor=0.0):
    """A leg's price at the trigger minute: its last close at or before `ts` that session (first print of the
    session when it has not traded yet, or on a gap); never below `floor` (intrinsic at the trigger level)."""
    day = ts.date().isoformat()
    d = bars[bars["trading_day"] == day]
    px = None
    if gap and len(d):
        px = float(d["open"].iloc[0])
    else:
        p = bars[bars["ts"] <= ts]
        if len(p) and p["trading_day"].iloc[-1] == day:
            px = float(p["close"].iloc[-1])
        elif len(d):
            px = float(d["open"].iloc[0])
        elif len(p):
            px = float(p["close"].iloc[-1])
    return None if px is None else max(px, floor)


def pick_wing(listed, target, side):
    """Nearest listed strike at or beyond `target`: call side the lowest K >= target, put side the highest K <= target.
    `listed` {strike: priced?} (only priced strikes are usable)."""
    ks = sorted(k for k, ok in listed.items() if ok)
    if side == "C":
        c = [k for k in ks if k >= target]
        return c[0] if c else None
    c = [k for k in ks if k <= target]
    return c[-1] if c else None


def intrinsic(cp, K, S):
    return ob.intrinsic(cp, K, S)


# ───────────────────────────── trade assembly (pure; tested) ─────────────────────────────

@dataclass
class Ctx:
    """Everything one trade needs, loaded once and shared by all variants."""
    underlying: str
    expiry: str
    entry: str
    lot: int
    F: float
    S: float
    kc: float
    kp: float
    ec: float                 # entry price, call: 15:20-15:29 average
    ep: float
    vwap_c: float             # entry price, call: fno_bhav settle (the exchange's 15:00-15:30 VWAP close)
    vwap_p: float
    bars_c: pd.DataFrame
    bars_p: pd.DataFrame
    idx: pd.DataFrame | None
    listed_c: dict           # {strike: window price or None} on the entry day, calls
    listed_p: dict
    bars_by_leg: dict         # {(cp, K): frame} for wing strikes
    how: str = "window"


def settle_value(c, cp, K):
    return intrinsic(cp, K, c.S)


def _result(c, name, parts, **kw):
    """Net points per unit and the bookkeeping from `parts`: list of dicts {cp, K, qty, entry, exit, exit_day,
    exercise} with qty -1 short / +1 long; exit None = held to expiry (cash-settled)."""
    gross = cost = 0.0
    for p in parts:
        side = "sell" if p["qty"] < 0 else "buy"
        cost += leg_cost(p["entry"], side, c.lot, SLIP, c.entry)
        if p["exit"] is None:
            val = intrinsic(p["cp"], p["K"], c.S)
            if p["qty"] > 0:
                cost += STT_EXERCISE * val
        else:
            val = p["exit"]
            cost += leg_cost(val, "buy" if p["qty"] < 0 else "sell", c.lot, SLIP, p["exit_day"])
        gross += p["qty"] * (val - p["entry"])
    out = {"variant": name, "underlying": c.underlying, "expiry": c.expiry, "entry": c.entry, "lot": c.lot,
           "F": c.F, "kc": c.kc, "kp": c.kp, "ec": c.ec, "ep": c.ep, "S": c.S, "gross_pts": gross,
           "cost_pts": cost, "net_pts": gross - cost}
    out.update(kw)
    return out


def _naked_margin(c):
    return MARGIN_STRANGLE_PCT * c.F


def _shorts(c, entry_c, entry_p, exits=None):
    exits = exits or {}
    parts = []
    for cp, K, e in (("C", c.kc, entry_c), ("P", c.kp, entry_p)):
        x = exits.get(cp)
        parts.append({"cp": cp, "K": K, "qty": -1, "entry": e,
                      "exit": None if x is None else x["px"], "exit_day": None if x is None else x["day"].isoformat()
                      if hasattr(x["day"], "isoformat") else x["day"]})
    return parts


def v_baseline_vwap(c):
    """Naked strangle held to expiry, entered at the exchange's VWAP close (the paper book's own price)."""
    r = _result(c, "baseline_vwap", _shorts(c, c.vwap_c, c.vwap_p), margin_pts=_naked_margin(c), bound_pts=np.nan,
                triggered=0, whipsaw=0, hold_net_pts=np.nan)
    r["credit_pts"] = c.vwap_c + c.vwap_p
    return r


def v_baseline(c):
    """Naked strangle at the 15:20-15:29 average, held to expiry."""
    r = _result(c, "baseline", _shorts(c, c.ec, c.ep), margin_pts=_naked_margin(c), bound_pts=np.nan,
                triggered=0, whipsaw=0, hold_net_pts=np.nan)
    r["credit_pts"] = c.ec + c.ep
    return r


def v_pstop(c, k):
    """Premium stop: each short leg exits at its first 1-minute close >= k x entry price (gap-through at the open)."""
    exits = {}
    for cp, bars, e in (("C", c.bars_c, c.ec), ("P", c.bars_p, c.ep)):
        s = premium_stop(bars, c.entry, e, k, until=c.expiry)
        if s is not None:
            exits[cp] = s
    base = v_baseline(c)
    r = _result(c, f"pstop{k}", _shorts(c, c.ec, c.ep, exits), margin_pts=_naked_margin(c), bound_pts=np.nan,
                triggered=len(exits), gap_fills=sum(x["gap"] for x in exits.values()),
                hold_net_pts=base["net_pts"], credit_pts=c.ec + c.ep)
    # whipsaw: a stopped leg that would have expired worthless
    r["whipsaw"] = sum(1 for cp in exits if intrinsic(cp, c.kc if cp == "C" else c.kp, c.S) == 0)
    return r


def v_istop(c):
    """Index stop: both legs exit when a 1-minute index close comes within 0.5 % of either short strike."""
    base = v_baseline(c)
    if c.idx is None:
        return None
    s = index_stop(c.idx, c.entry, c.kc, c.kp, until=c.expiry)
    exits = {}
    if s is not None:
        for cp, bars, K in (("C", c.bars_c, c.kc), ("P", c.bars_p, c.kp)):
            px = price_at(bars, s["ts"], s["gap"], floor=intrinsic(cp, K, s["level"]))
            if px is not None:
                exits[cp] = {"px": px, "day": s["day"]}
    r = _result(c, "istop", _shorts(c, c.ec, c.ep, exits), margin_pts=_naked_margin(c), bound_pts=np.nan,
                triggered=int(bool(exits)), gap_fills=int(bool(s and s["gap"])), hold_net_pts=base["net_pts"],
                credit_pts=c.ec + c.ep)
    r["whipsaw"] = int(bool(exits) and all(intrinsic(cp, c.kc if cp == "C" else c.kp, c.S) == 0 for cp in exits))
    return r


def _wings(c, w):
    """{cp: (K, entry price)} for the long wings w x F beyond each short strike, or None when a side has no priced strike."""
    out = {}
    for cp, listed, short, sign in (("C", c.listed_c, c.kc, +1), ("P", c.listed_p, c.kp, -1)):
        target = short + sign * w * c.F
        K = pick_wing({k: v is not None for k, v in listed.items()}, target, cp)
        if K is None:
            return None
        out[cp] = (K, listed[K])
    return out


def v_wings(c, w, k=None):
    """Wings w x F beyond each short strike bought at entry and held to expiry; optional premium stop k on the shorts."""
    wings = _wings(c, w)
    if wings is None:
        return None
    exits = {}
    if k is not None:
        for cp, bars, e in (("C", c.bars_c, c.ec), ("P", c.bars_p, c.ep)):
            s = premium_stop(bars, c.entry, e, k, until=c.expiry)
            if s is not None:
                exits[cp] = s
    parts = _shorts(c, c.ec, c.ep, exits)
    for cp, (K, px) in wings.items():
        parts.append({"cp": cp, "K": K, "qty": +1, "entry": px, "exit": None, "exit_day": None})
    wc, wp = wings["C"][1], wings["P"][1]
    width_c, width_p = wings["C"][0] - c.kc, c.kp - wings["P"][0]
    name = f"wing{round(w * 100)}" + (f"_pstop{k}" if k else "")
    net_credit = c.ec + c.ep - wc - wp
    margin = max(width_c, width_p) - net_credit            # worst loss before costs, per unit
    legs = ELM_LEGS
    margin_pts = margin + ELM_PCT * c.F * legs
    # worst case: one side runs through its wing (loses the width), the other side's premium is kept
    # (no stop) or lost at the stop multiple (stop)
    wsum = wc + wp
    ek = (k - 1) if k else None
    bound = max(width_c - c.ec + wsum + (ek * c.ep if k else -c.ep),
                width_p - c.ep + wsum + (ek * c.ec if k else -c.ec))
    r = _result(c, name, parts, margin_pts=margin_pts, bound_pts=bound, credit_pts=c.ec + c.ep,
                triggered=0, wing_itm=int(intrinsic("C", wings["C"][0], c.S) > 0 or intrinsic("P", wings["P"][0], c.S) > 0),
                wing_cost_pts=wsum, wing_c=wings["C"][0], wing_p=wings["P"][0], gap_fills=0,
                hold_net_pts=np.nan)
    r["bound_pts"] += r["cost_pts"]
    r["triggered"] = int(r["wing_itm"] or bool(exits))
    if k:
        r["stops"] = len(exits)
        r["whipsaw"] = sum(1 for cp in exits if intrinsic(cp, c.kc if cp == "C" else c.kp, c.S) == 0)
    else:
        r["whipsaw"] = 0
    return r


def variants_for(c, which):
    """Every requested variant for one trade → list of result dicts (None results dropped)."""
    fns = {"baseline_vwap": lambda: v_baseline_vwap(c), "baseline": lambda: v_baseline(c),
           "pstop2": lambda: v_pstop(c, 2), "pstop3": lambda: v_pstop(c, 3), "istop": lambda: v_istop(c),
           "wing2": lambda: v_wings(c, 0.02), "wing3": lambda: v_wings(c, 0.03), "wing4": lambda: v_wings(c, 0.04),
           "wing3_pstop3": lambda: v_wings(c, 0.03, 3)}
    out = [fns[v]() for v in which]
    return [r for r in out if r is not None]


# ───────────────────────────── sizing + statistics (pure; tested) ─────────────────────────────

def lots_A(capital, margin_pts, lot):
    return int(math.floor(capital / (margin_pts * lot)))


def lots_B(capital, worst_pts, lot, share=WORST_CASE_SHARE):
    return int(math.floor(capital * share / (worst_pts * lot)))


def size_trades(df, sizing, capital, naked_worst_pts):
    """Add lots and pnl_rs. df: one variant's trades. naked_worst_pts: baseline's worst loss per unit (points, > 0)."""
    d = df.copy()
    if sizing == "A":
        d["lots"] = [lots_A(capital, m, l) for m, l in zip(d.margin_pts, d.lot)]
    else:
        worst = d.bound_pts if d.bound_pts.notna().all() else pd.Series(naked_worst_pts, index=d.index)
        d["lots"] = [lots_B(capital, w, l) for w, l in zip(worst, d.lot)]
    d["pnl_rs"] = d.lots * d.lot * d.net_pts
    d["margin_rs"] = d.lots * d.lot * d.margin_pts
    d["ret_on_margin"] = d.net_pts / d.margin_pts
    return d


def stats(d, capital):
    """Pre-registered metrics for one sized trade list (columns: expiry, entry, pnl_rs, ret_on_margin, ...)."""
    if d.empty:
        return {}
    d = d.sort_values("expiry")
    pnl = d.pnl_rs.to_numpy()
    span = (date.fromisoformat(d.expiry.max()) - date.fromisoformat(d.entry.min())).days / 365.0
    wk = pd.to_datetime(d.entry).dt.to_period("W")
    weekly = d.groupby(wk).pnl_rs.sum()
    weekly = weekly.reindex(pd.period_range(weekly.index.min(), weekly.index.max(), freq="W"), fill_value=0.0)
    sharpe = float(weekly.mean() / weekly.std(ddof=1) * math.sqrt(52)) if weekly.std(ddof=1) > 0 else float("nan")
    cum = np.cumsum(pnl)
    dd = float((cum - np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:]).min())
    yearly = d.groupby(d.expiry.str[:4]).pnl_rs.sum()
    out = {"n": len(d), "win%": 100 * float((pnl > 0).mean()), "mean_rs": float(pnl.mean()),
           "mean_pct_margin": 100 * float(d.ret_on_margin.mean()), "annual_rs": float(pnl.sum() / span),
           "annual_pct": 100 * float(pnl.sum() / span) / capital, "sharpe": sharpe,
           "worst_rs": float(pnl.min()), "worst_pct_cap": 100 * float(pnl.min()) / capital,
           "maxdd_rs": dd, "maxdd_pct_cap": 100 * dd / capital, "losing_years": int((yearly < 0).sum()),
           "years": int(len(yearly))}
    for name, lo, hi in SPLITS:
        s = d[(d.expiry >= lo) & (d.expiry < hi)]
        out[f"mean_rs_{name}"] = float(s.pnl_rs.mean()) if len(s) else float("nan")
        out[f"n_{name}"] = len(s)
    for col in ("triggered", "whipsaw"):
        if col in d:
            out[col] = int(d[col].sum()) if col == "whipsaw" else int((d[col] > 0).sum())
    return out


# ───────────────────────────── loading ─────────────────────────────

def _ro():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def sessions():
    """NIFTY F&O sessions (fno_bhav): the calendar both exchanges share."""
    with _ro() as c:
        return sorted(r[0] for r in c.execute(
            "SELECT DISTINCT trade_date FROM fno_bhav WHERE symbol='NIFTY' AND instrument_type='IDO'"))


def manifest_status():
    """{(symbol, expiry): status} from the intraday_files manifest (ok | unvalidated | suspect | stub)."""
    with _ro() as c:
        rows = c.execute("SELECT key, note FROM intraday_files WHERE dataset='options_1m' AND kind='expiry'").fetchall()
    return {tuple(k.split("/")): hf.parse_note(n).get("status") for k, n in rows}


def candidate_expiries(u, days):
    """[(expiry, entry_day)] for every expiry whose front-weekly entry day (2 sessions before) is in fno_bhav."""
    with _ro() as c:
        exps = [r[0] for r in c.execute("SELECT DISTINCT expiry_date FROM fno_bhav WHERE symbol=? AND instrument_type='IDO'", (u,))]
        first = c.execute("SELECT MIN(trade_date) FROM fno_bhav WHERE symbol=? AND instrument_type='IDO'", (u,)).fetchone()[0]
    pos = {d: i for i, d in enumerate(days)}
    out = []
    for e in sorted(exps):
        if e not in pos or pos[e] < 2:
            continue
        t = days[pos[e] - ob.RULE["sessions_before_expiry"]]
        if t < first:
            continue
        out.append((e, t))
    return out


def load_ctx(u, e, t, idx, conn):
    """Build the Ctx for one trade, or (None, reason)."""
    ch = pd.read_sql_query("SELECT option_type, strike, settle, volume, underlying_price FROM fno_bhav "
                           "WHERE symbol=? AND instrument_type='IDO' AND trade_date=? AND expiry_date=?", conn,
                           params=(u, t, e))
    if ch.empty:
        return None, "no_chain"
    front = conn.execute("SELECT MIN(expiry_date) FROM fno_bhav WHERE symbol=? AND instrument_type='IDO' "
                         "AND trade_date=? AND expiry_date>?", (u, t, t)).fetchone()[0]
    if front != e:
        return None, "not_front_weekly"
    ch["strike"] = ch["strike"].astype(float)
    d = slice_deltas(ch, t, e)
    if d is None:
        return None, "no_delta_chain"
    F, deltas = d
    k = nearest(deltas, DELTA)
    px = {(("C" if o == "CE" else "P"), s): v for o, s, v in zip(ch.option_type, ch.strike, ch.settle)}
    S = conn.execute("SELECT MAX(underlying_price) FROM fno_bhav WHERE symbol=? AND instrument_type='IDO' "
                     "AND trade_date=? AND expiry_date=?", (u, e, e)).fetchone()[0]
    if not S:
        return None, "no_settlement"
    opt = hf.load(u, e)
    opt["trading_day"] = opt["trading_day"].map(lambda x: x if isinstance(x, str) else x.isoformat())
    g = {key: grp.reset_index(drop=True) for key, grp in opt.groupby(["option_type", "strike"], sort=False)}

    def leg(cp, K):
        return g.get(("CE" if cp == "C" else "PE", int(round(K))))

    bc, bp = leg("C", k["C"]), leg("P", k["P"])
    if bc is None or bp is None:
        return None, "short_leg_not_in_file"
    ec, how_c = window_price(bc, t)
    ep, how_p = window_price(bp, t)
    if ec is None or ep is None:
        return None, "short_leg_no_print_on_entry_day"
    listed = {"C": {}, "P": {}}
    for (ot, K), grp in g.items():
        cp = "C" if ot == "CE" else "P"
        if (cp == "C" and K > k["C"]) or (cp == "P" and K < k["P"]):
            on = grp[grp["trading_day"] == t]
            if len(on):
                listed[cp][float(K)] = window_price(grp, t)[0]
    c = Ctx(underlying=u, expiry=e, entry=t, lot=ob.lot_size(u, t, e), F=F, S=float(S), kc=k["C"], kp=k["P"],
            ec=ec, ep=ep, vwap_c=px[("C", k["C"])], vwap_p=px[("P", k["P"])], bars_c=bc, bars_p=bp, idx=idx,
            listed_c=listed["C"], listed_p=listed["P"], bars_by_leg={},
            how="window" if how_c == how_p == "window" else "fallback")
    return c, "ok"


def load_index(u):
    ix = hf.load(u)
    ix["trading_day"] = ix["trading_day"].map(lambda x: x if isinstance(x, str) else x.isoformat())
    return ix


def build_trades(u, which=VARIANTS, limit=None, verbose=False):
    """(trades DataFrame for `which` variants, coverage dict) for one underlying."""
    days = sessions()
    status = manifest_status()
    idx = load_index(u)
    idx_last = idx["trading_day"].max()
    cov = {"candidates": 0, "no_file": 0, "stub": 0, "unvalidated": 0, "suspect": 0, "used": 0, "no_index_for_istop": 0}
    skipped = {}
    rows = []
    with _ro() as conn:
        for e, t in candidate_expiries(u, days):
            if e < hf_span(u)[0] or e > hf_span(u)[1]:
                continue
            cov["candidates"] += 1
            st = status.get((u, e))
            if st is None:
                cov["no_file"] += 1
                continue
            if st == "stub":
                cov["stub"] += 1
                continue
            if st == "suspect":
                cov["suspect"] += 1
                continue
            if st == "unvalidated":
                cov["unvalidated"] += 1          # kept, counted: the VWAP cross-check could not run on it
            if limit and cov["used"] >= limit:
                break
            c, why = load_ctx(u, e, t, idx if e <= idx_last else None, conn)
            if c is None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            if e > idx_last:
                cov["no_index_for_istop"] += 1
            cov["used"] += 1
            res = variants_for(c, which)
            for r in res:
                r["entry_how"] = c.how
            rows += res
            if verbose:
                print(u, e, t, f"lot={c.lot} F={c.F:.0f} Kc={c.kc:.0f} Kp={c.kp:.0f} ec={c.ec:.2f} ep={c.ep:.2f} "
                      f"vwap=({c.vwap_c:.2f},{c.vwap_p:.2f}) S={c.S:.0f}",
                      {r["variant"]: round(r["net_pts"], 2) for r in res})
    cov["skipped"] = skipped
    return pd.DataFrame(rows), cov


def hf_span(u):
    """(first, last) expiry the archive covers for `u` (manifest)."""
    ex = sorted(e for (s, e) in manifest_status() if s == u)
    return ex[0], ex[-1]


# ───────────────────────────── report ─────────────────────────────

def _fmt(x, f="{:,.0f}"):
    return "-" if x is None or (isinstance(x, float) and np.isnan(x)) else f.format(x)


def table(rows, cols):
    head = "| " + " | ".join(h for h, _, _ in cols) + " |\n|" + "|".join("---" for _ in cols) + "|\n"
    return head + "\n".join("| " + " | ".join(_fmt(r.get(k), f) for _, k, f in cols) + " |" for r in rows)


STAT_COLS = [("Variant", "variant", "{}"), ("Trades", "n", "{:,.0f}"), ("Win %", "win%", "{:.1f}"),
             ("Mean/trade ₹", "mean_rs", "{:,.0f}"), ("Mean % margin", "mean_pct_margin", "{:.2f}"),
             ("Annual ₹", "annual_rs", "{:,.0f}"), ("Annual % cap", "annual_pct", "{:.1f}"),
             ("Sharpe", "sharpe", "{:.2f}"), ("Worst ₹", "worst_rs", "{:,.0f}"),
             ("Worst % cap", "worst_pct_cap", "{:.1f}"), ("Max DD ₹", "maxdd_rs", "{:,.0f}"),
             ("Losing yrs", "losing_years", "{:.0f}"), ("Triggered", "triggered", "{:.0f}"),
             ("Whipsaw", "whipsaw", "{:.0f}")]


def evaluate(trades, which=VARIANTS, capital=CAPITAL):
    """{(book, sizing, variant): stats} for books NIFTY, SENSEX and COMBINED (half capital each)."""
    out, sized = {}, {}
    for book, cap_share in (("NIFTY", 1.0), ("SENSEX", 1.0), ("COMBINED", 0.5)):
        for sizing in ("A", "B"):
            for v in which:
                parts, bparts = [], []
                for u in ("NIFTY", "SENSEX") if book == "COMBINED" else (book,):
                    t = trades[(trades.underlying == u) & (trades.variant == v)]
                    if t.empty:
                        continue
                    base = trades[(trades.underlying == u) & (trades.variant == "baseline")]
                    worst = float(-base.net_pts.min()) if len(base) else float("nan")
                    parts.append(size_trades(t, sizing, capital * cap_share, worst))
                    same = base[base.expiry.isin(t.expiry)]          # baseline on exactly this variant's trades
                    bparts.append(size_trades(same, sizing, capital * cap_share, worst))
                if not parts:
                    continue
                d = pd.concat(parts)
                s = stats(d, capital)
                s["variant"] = v
                out[(book, sizing, v)] = s
                out[(book, sizing, v + "@base")] = stats(pd.concat(bparts), capital)
                sized[(book, sizing, v)] = d
    return out, sized


def decision(res, which=VARIANTS):
    """The pre-registered rule, per book, against baseline (same trades, sizing B)."""
    verdict = {}
    for book in ("NIFTY", "SENSEX", "COMBINED"):
        for v in which:
            if v in ("baseline", "baseline_vwap") or (book, "B", v) not in res:
                continue
            s = res[(book, "B", v)]
            b = res[(book, "B", v + "@base")]
            c1 = s["worst_rs"] >= 0.5 * b["worst_rs"]          # losses are negative: worst >= half of baseline's worst
            c2 = s["annual_rs"] >= 0.7 * b["annual_rs"]
            c3 = all((s.get(f"mean_rs_{n}", float("nan")) > 0) for n, _, _ in SPLITS if s.get(f"n_{n}", 0) > 0)
            verdict[(book, v)] = {"c1_worst": c1, "c2_pnl": c2, "c3_regimes": c3, "pass": c1 and c2 and c3,
                                  "worst_ratio": s["worst_rs"] / b["worst_rs"], "pnl_ratio": s["annual_rs"] / b["annual_rs"]}
    return verdict


def report(trades, cov, which=VARIANTS):
    res, _ = evaluate(trades, which)
    for book in ("NIFTY", "SENSEX", "COMBINED"):
        for sizing in ("A", "B"):
            rows = [res[(book, sizing, v)] for v in which if (book, sizing, v) in res]
            if rows:
                print(f"\n### {book}, sizing {sizing}\n")
                print(table(rows, STAT_COLS))
    print("\n### Decision rule (sizing B vs baseline)\n")
    for (book, v), d in decision(res, which).items():
        print(f"{book:9s} {v:14s} worst_ratio={d['worst_ratio']:.2f} (need<=0.5) {d['c1_worst']} | "
              f"pnl_ratio={d['pnl_ratio']:.2f} (need>=0.7) {d['c2_pnl']} | regimes {d['c3_regimes']} | PASS={d['pass']}")
    print("\ncoverage", cov)


def extras(trades, which=VARIANTS):
    """Supporting tables for the study doc: coverage, entry-price effect, whipsaw, gap fills, worst trades,
    yearly P&L, and one labelled non-pre-registered wing-price sensitivity."""
    res, sized = evaluate(trades, which)
    print("\n### Coverage: trades per variant (a wing needs a priced strike at or beyond its target)\n")
    cov = trades.groupby(["variant", "underlying"]).size().unstack(fill_value=0)
    print(cov.reindex([v for v in which if v in cov.index]).to_string())
    print("\nentry-price source: ", trades[trades.variant == "baseline"].entry_how.value_counts().to_dict())

    print("\n### Entry-price effect (baseline at the exchange VWAP close vs 15:20-15:29 average, same trades)\n")
    for u in ("NIFTY", "SENSEX"):
        a = trades[(trades.underlying == u) & (trades.variant == "baseline_vwap")].set_index("expiry")
        b = trades[(trades.underlying == u) & (trades.variant == "baseline")].set_index("expiry")
        if a.empty:
            continue
        j = a.join(b, lsuffix="_v", rsuffix="_m", how="inner")
        print(f"{u}: n={len(j)}  mean credit VWAP {j.credit_pts_v.mean():.2f} vs window {j.credit_pts_m.mean():.2f} pts "
              f"({100 * (j.credit_pts_m.mean() / j.credit_pts_v.mean() - 1):+.1f}%)  "
              f"mean net/trade VWAP {j.net_pts_v.mean():.2f} vs window {j.net_pts_m.mean():.2f} pts")
    rows = []
    for book in ("NIFTY", "SENSEX", "COMBINED"):
        for sizing in ("A", "B"):
            for v in ("baseline_vwap", "baseline"):
                if (book, sizing, v) in res:
                    r = dict(res[(book, sizing, v)])
                    r["variant"] = f"{book} {sizing} {v}"
                    rows.append(r)
    print()
    print(table(rows, STAT_COLS[:12]))

    print("\n### Stops: legs fired, gap fills, whipsaw (stopped leg would have expired worthless), cost vs holding\n")
    srows = []
    for v in ("pstop2", "pstop3", "istop", "wing3_pstop3"):
        for book in ("NIFTY", "SENSEX", "COMBINED"):
            d = sized.get((book, "B", v))
            if d is None:
                continue
            ws = d[d.whipsaw > 0]
            hold = d.hold_net_pts if d.hold_net_pts.notna().all() else None
            cost = float(((d.hold_net_pts - d.net_pts) * d.lots * d.lot)[d.whipsaw > 0].sum()) if hold is not None else float("nan")
            fired = d[d.triggered > 0]
            srows.append({"variant": f"{v} {book}", "trades": len(d), "fired": len(fired),
                          "fired%": 100 * len(fired) / len(d), "gap": int(d.gap_fills.sum()), "whip_trades": len(ws),
                          "whip%": 100 * len(ws) / len(d), "whip_cost": cost,
                          "stopped_won_anyway": int(((d.triggered > 0) & (d.hold_net_pts > 0)).sum()) if hold is not None else None})
    print(table(srows, [("Variant", "variant", "{}"), ("Trades", "trades", "{:.0f}"), ("Stop fired", "fired", "{:.0f}"),
                        ("Fired %", "fired%", "{:.1f}"), ("Gap fills", "gap", "{:.0f}"), ("Whipsaw trades", "whip_trades", "{:.0f}"),
                        ("Whipsaw %", "whip%", "{:.1f}"), ("Whipsaw cost vs holding ₹ (B)", "whip_cost", "{:,.0f}"),
                        ("Fired but hold won", "stopped_won_anyway", "{:.0f}")]))

    print("\n### Wings: finished in the money, and the premium paid\n")
    wrows = []
    for v in ("wing2", "wing3", "wing4"):
        for u in ("NIFTY", "SENSEX"):
            t = trades[(trades.underlying == u) & (trades.variant == v)]
            if t.empty:
                continue
            wrows.append({"variant": f"{v} {u}", "n": len(t), "itm": int(t.wing_itm.sum()), "wing_px": t.wing_cost_pts.mean(),
                          "credit": t.credit_pts.mean(), "bound": t.bound_pts.mean(), "margin": t.margin_pts.mean()})
    print(table(wrows, [("Variant", "variant", "{}"), ("Trades", "n", "{:.0f}"), ("Wing ITM", "itm", "{:.0f}"),
                        ("Wings premium (pts)", "wing_px", "{:.2f}"), ("Short credit (pts)", "credit", "{:.2f}"),
                        ("Worst-case bound (pts)", "bound", "{:.0f}"), ("Hedged margin (pts)", "margin", "{:.0f}")]))

    print("\n### Worst baseline trades (NIFTY and SENSEX)\n")
    b = trades[trades.variant == "baseline"].sort_values("net_pts").groupby("underlying").head(4)
    b = b.assign(move_pct=100 * (b.S / b.F - 1), loss_inr_1lot=b.net_pts * b.lot)
    print(table(b.to_dict("records"), [("Underlying", "underlying", "{}"), ("Entry", "entry", "{}"), ("Expiry", "expiry", "{}"),
                                       ("Index move to settle %", "move_pct", "{:.2f}"), ("Net pts", "net_pts", "{:.1f}"),
                                       ("1 lot ₹", "loss_inr_1lot", "{:,.0f}")]))

    print("\n### P&L by year, combined, sizing B (₹)\n")
    ys = {}
    for v in ("baseline", "pstop2", "pstop3", "istop", "wing2", "wing3", "wing4", "wing3_pstop3"):
        d = sized.get(("COMBINED", "B", v))
        if d is not None:
            ys[v] = d.groupby(d.expiry.str[:4]).pnl_rs.sum().round(0)
    print(pd.DataFrame(ys).fillna(0).astype(int).to_string())

    print("\n### Sensitivity (NOT pre-registered): wings cost twice the printed premium, combined, sizing B\n")
    t2 = trades.copy()
    m = t2.variant.str.startswith("wing")
    t2.loc[m, "net_pts"] = t2.loc[m, "net_pts"] - t2.loc[m, "wing_cost_pts"]
    t2.loc[m, "bound_pts"] = t2.loc[m, "bound_pts"] + t2.loc[m, "wing_cost_pts"]
    r2, _ = evaluate(t2, which)
    print(table([r2[("COMBINED", "B", v)] for v in ("baseline", "wing2", "wing3", "wing4") if ("COMBINED", "B", v) in r2],
                STAT_COLS[:11]))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--underlying", choices=("NIFTY", "SENSEX", "both"), default="both")
    ap.add_argument("--variant", default="all", help="one of " + ", ".join(VARIANTS) + " or all")
    ap.add_argument("--report", action="store_true", help="print the full pre-registered tables")
    ap.add_argument("--smoke", action="store_true", help="3 trades per underlying, fills printed")
    ap.add_argument("--elm-legs", type=int, choices=(1, 2), default=2, help="exposure margin on 1 or 2 short legs")
    ap.add_argument("--trades", help="write the per-trade table to this CSV")
    ap.add_argument("--from-csv", help="skip the build: report from a saved per-trade CSV")
    ap.add_argument("--extras", action="store_true", help="also print the supporting tables")
    a = ap.parse_args()
    global ELM_LEGS
    ELM_LEGS = a.elm_legs
    which = VARIANTS if a.variant == "all" else (a.variant, "baseline") if a.variant != "baseline" else ("baseline",)
    us = ("NIFTY", "SENSEX") if a.underlying == "both" else (a.underlying,)
    if a.from_csv:
        trades = pd.read_csv(a.from_csv)
        report(trades, {}, which)
        if a.extras:
            extras(trades, which)
        return
    frames, covs = [], {}
    for u in us:
        t, cov = build_trades(u, which, limit=3 if a.smoke else None, verbose=a.smoke)
        frames.append(t)
        covs[u] = cov
    trades = pd.concat(frames, ignore_index=True)
    if a.trades:
        trades.to_csv(a.trades, index=False)
    if a.smoke:
        print(trades[["underlying", "expiry", "variant", "lot", "net_pts", "cost_pts", "triggered"]].to_string())
        return
    report(trades, covs, which)
    if a.extras:
        extras(trades, which)


if __name__ == "__main__":
    main()
