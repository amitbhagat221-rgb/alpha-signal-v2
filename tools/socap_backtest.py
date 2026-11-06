"""
Alpha Signal v2 — SOCAP's expiry-day option strategy, rebuilt and backtested on our 1-minute data.

Pre-registered 2026-11-07 (docs/studies/socap-option-strategy-preregistration.md, commit 75f352d, before any
result). READ-ONLY: fno_bhav and the intraday_files manifest through sqlite mode=ro, the 1-minute Parquet
archives (Hugging Face `options_1m`, Kite capture `options_1m_kite`); writes nothing but a report you name.

The primary rule P (the only one that decides the verdict):
  expiry day, 09:30 IST: sell 1 call + 1 put at |delta| nearest 0.40 (Black-76 on each strike's own
  09:25-09:30 last close, forward from put-call parity at the strike nearest the index); every 15 min
  from 09:45 to 15:15 hedge h = 0.5 of the options' delta with a synthetic future (ATM call/put pair),
  sticky-strike IVs; everything settles at intrinsic on fno_bhav's expiry-day underlying_price.
  Costs: option_book.charges_pts + slippage max(0.05, 0.25 % of price) per leg per side; STT on exercise
  of long legs that finish in the money. Margin 14 % of F x lot.

Interpretations where the pre-registration is silent (also in the study doc):
  * book size: costs are per unit of a 10-lot book (brokerage = 2 orders per entry or rebalance, spread over
    10 lots), and hedge trades are rounded to whole lots of that book (a change under 0.1 per unit is not
    traded). Our live rule is charged the same 10-lot brokerage on the same expiries ("ours_10lot"); the
    pre-registered as-is replay ("ours") is reported beside it;
  * a strike "printed at 09:30" = a 1-minute close stamped 09:25-09:30; later times use the same 5-minute
    look-back;
  * lean: +0.2 x sign(S 10:00 close - S 09:15 open) added to the hedge target from the 10:00 rebalance.

Usage:
  python -m tools.socap_backtest --smoke                  # three expiry days, fills printed
  python -m tools.socap_backtest --report out.md          # everything in the pre-registration
"""

from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import brentq


def _ncdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


class norm:                                   # scalar normal CDF without scipy's per-call overhead
    cdf = staticmethod(_ncdf)

import option_book as ob
from config import DB_PATH, INTRADAY_DIR
from tools import option_intraday_study as ois

HF = INTRADAY_DIR / "options_1m"
KITE = INTRADAY_DIR / "options_1m_kite"
YEAR_MIN = 375 * 252
END = 15 * 60 + 30
BOOK_LOTS = 10
MARGIN_PCT = 0.14
MIN_HEDGE_STEP = 1.0 / BOOK_LOTS

PRIMARY = dict(delta=0.40, h=0.5, every=15, slip=0.0025, tranches=False, tail=False, lean=False)
GRID_DELTA = (0.15, 0.25, 0.40)
GRID_H = (0.0, 0.3, 0.5, 1.0)
GRID_N = (5, 15, 30)
VARIANTS = {
    "P": {},
    "tranches": dict(tranches=True),
    "tail": dict(tail=True),
    "lean": dict(lean=True),
    "slip 0.1 %": dict(slip=0.001),
    "slip 1 %": dict(slip=0.01),
}
STRESS = [("NIFTY", "2026-01-20"), ("NIFTY", "2026-02-03"), ("SENSEX", "2026-11-05")]
SOCAP_HIT_2026 = {"NIFTY": 84.0, "SENSEX": 76.0}


# ── Black-76, r = 0 (hours to expiry) ──

def b76(F, K, T, s, cp):
    if T <= 0 or s <= 0:
        return max(F - K, 0.0) if cp == "C" else max(K - F, 0.0)
    v = s * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    d2 = d1 - v
    return F * norm.cdf(d1) - K * norm.cdf(d2) if cp == "C" else K * norm.cdf(-d2) - F * norm.cdf(-d1)


def iv(px, F, K, T, cp):
    intr = max(F - K, 0.0) if cp == "C" else max(K - F, 0.0)
    if px is None or not np.isfinite(px) or px <= intr + 1e-9 or T <= 0:
        return np.nan
    try:
        return brentq(lambda s: b76(F, K, T, s, cp) - px, 1e-4, 8.0, maxiter=200)
    except ValueError:
        return np.nan


def delta(F, K, T, s, cp):
    if T <= 0 or s <= 0 or not np.isfinite(s):
        return (1.0 if F > K else 0.0) if cp == "C" else (-1.0 if F < K else 0.0)
    v = s * math.sqrt(T)
    d1 = (math.log(F / K) + 0.5 * v * v) / v
    return norm.cdf(d1) if cp == "C" else norm.cdf(d1) - 1.0


def mins(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def T_at(m):
    return max(END - m, 0) / YEAR_MIN


# ── costs (per unit of a BOOK_LOTS book) ──

def leg_var(price, side, d, slip):
    """Variable cost of one unit traded once: exchange + GST, STT on a sell, stamp on a buy, slippage."""
    c = price * ob.EXCHANGE * (1 + ob.GST) + price * (ob.stt_sell(d) if side == "sell" else ob.STAMP_BUY)
    return c + max(ob.TICK, slip * price)


def brokerage(orders, lot):
    return orders * ob.BROKERAGE_RS * (1 + ob.GST) / (BOOK_LOTS * lot)


# ── data ──

@dataclass
class Day:
    u: str
    e: str
    src: str
    lot: int
    S_settle: float
    idx: pd.Series                       # minute (int) -> index close
    idx_open915: float
    px: dict = field(default_factory=dict)   # (cp, K) -> Series minute -> close (ffill <= 5)
    picks: dict = field(default_factory=dict)  # (minute, F) -> [(cp, K, px, iv, |delta|)] cache


def _ro():
    return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)


def settle(conn, u, e):
    r = conn.execute("SELECT MAX(underlying_price) FROM fno_bhav WHERE symbol=? AND instrument_type='IDO' "
                     "AND trade_date=?", (u, e)).fetchone()[0]
    return float(r) if r else None


def _minute_frame(df):
    m = df["ts"].dt.hour * 60 + df["ts"].dt.minute
    return df.assign(m=m.values)


_INDEX = {}


def index_minutes(src, u):
    if (src, u) not in _INDEX:
        ix = pd.read_parquet((HF if src == "hf" else KITE) / "index" / f"{u}.parquet")
        ix["trading_day"] = ix["trading_day"].map(lambda x: x if isinstance(x, str) else x.isoformat())
        _INDEX[(src, u)] = _minute_frame(ix)
    return _INDEX[(src, u)]


def expiry_days(conn):
    """[(u, e, src)] every expiry day the minute files can cover; Kite wins only where HF has no file."""
    st = ois.manifest_status()
    out = []
    for (u, e), s in sorted(st.items()):
        if s in ("stub", "suspect"):
            continue
        out.append((u, e, "hf"))
    have = {(u, e) for u, e, _ in out}
    for u in ("NIFTY", "SENSEX"):
        for f in sorted((KITE / u).glob("*.parquet")):
            e = f.stem
            if (u, e) not in have:
                out.append((u, e, "kite"))
    return out


def load_day(conn, u, e, src):
    S = settle(conn, u, e)
    if S is None:
        return None, "no_settlement"
    ix = index_minutes(src, u)
    ix = ix[ix["trading_day"] == e]
    if ix.empty:
        return None, "no_index_day"
    idx = ix.groupby("m")["close"].last().reindex(range(9 * 60 + 15, END)).ffill(limit=5)
    if idx.loc[9 * 60 + 30:END - 1].isna().any():
        return None, "index_gap"
    o915 = ix[ix["m"] == 9 * 60 + 15]["open"]
    opt = pd.read_parquet((HF if src == "hf" else KITE) / u / f"{e}.parquet",
                          columns=["ts", "trading_day", "strike", "option_type", "close"])
    opt["trading_day"] = opt["trading_day"].map(lambda x: x if isinstance(x, str) else x.isoformat())
    opt = opt[opt["trading_day"] == e]
    if opt.empty:
        return None, "no_options_on_expiry_day"
    opt = _minute_frame(opt)
    d = Day(u=u, e=e, src=src, lot=ob.lot_size(u, e, e), S_settle=S, idx=idx,
            idx_open915=float(o915.iloc[0]) if len(o915) else float(idx.iloc[0]))
    grid = range(9 * 60 + 15, END + 1)
    for (ot, K), g in opt.groupby(["option_type", "strike"], sort=False):
        s = g.groupby("m")["close"].last().reindex(grid).ffill(limit=5)
        d.px[("C" if ot == "CE" else "P", float(K))] = s
    return d, "ok"


def price(d, cp, K, m):
    s = d.px.get((cp, K))
    if s is None:
        return np.nan
    v = s.get(m, np.nan)
    return float(v) if np.isfinite(v) and v > 0 else np.nan


def forward_at(d, m):
    """(F, K_atm, C, P) from put-call parity at the strike nearest the index with both prints, or None."""
    S = float(d.idx[m])
    strikes = sorted({K for (cp, K) in d.px}, key=lambda K: abs(K - S))
    for K in strikes[:4]:
        c, p = price(d, "C", K, m), price(d, "P", K, m)
        if np.isfinite(c) and np.isfinite(p):
            return K + c - p, K, c, p
    return None


def pick(d, m, F, target):
    """{'C': (K, px, iv), 'P': ...}: OTM strike whose |delta| is nearest target at minute m, or None."""
    T = T_at(m)
    key = (m, round(F, 4))
    if key not in d.picks:
        cand = []
        for (cp, K) in d.px:
            if (cp == "C" and K <= F) or (cp == "P" and K >= F) or abs(K - F) > 0.08 * F:
                continue
            px = price(d, cp, K, m)
            s = iv(px, F, K, T, cp)
            if np.isfinite(s):
                cand.append((cp, K, px, s, abs(delta(F, K, T, s, cp))))
        d.picks[key] = cand
    out = {}
    for cp in ("C", "P"):
        side = [c for c in d.picks[key] if c[0] == cp]
        if not side:
            return None
        best = min(side, key=lambda c: abs(c[4] - target))
        out[cp] = best[1:4]
    return out


# ── one day under one rule ──

def run_day(d, f0, cfg):
    """Net points per unit and the parts, under rule cfg; None when the day can't be traded."""
    m0 = 9 * 60 + 30
    base = f0[0] - float(d.idx[m0])
    slip = cfg["slip"]
    legs = []                                     # [cp, K, units (neg = short), iv]
    cost = credit = 0.0
    entries = [m0 + 60 * i for i in range(6)] if cfg["tranches"] else [m0]
    for me in entries:
        fw = f0 if me == m0 else forward_at(d, me)
        if fw is None:
            if me == m0:
                return None
            continue
        pk = pick(d, me, fw[0], cfg["delta"])
        if pk is None:
            if me == m0:
                return None
            continue
        u = 1.0 / len(entries)
        for cp, (K, px, s) in pk.items():
            legs.append([cp, K, -u, s])
            credit += u * px
            cost += u * leg_var(px, "sell", d.e, slip)
        cost += brokerage(2, d.lot)
    if cfg["tail"]:
        tk = pick(d, m0, f0[0], 0.01)
        if tk is not None:
            spend = 0.10 * credit
            pc, pp = tk["C"][1], tk["P"][1]
            n = spend / (pc + pp)
            for cp, (K, px, s) in tk.items():
                legs.append([cp, K, n, s])
                credit -= n * px
                cost += n * leg_var(px, "buy", d.e, slip)
            cost += brokerage(2, d.lot)
    atm_iv = iv(f0[2] + f0[3], f0[0], f0[1], T_at(m0), "S") if False else _straddle_iv(f0, T_at(m0))
    lean = 0.0
    if cfg["lean"]:
        lean = 0.2 * float(np.sign(float(d.idx[10 * 60]) - d.idx_open915))
    H, hedge_pnl, last_F = 0.0, 0.0, None
    active = lambda m: [L for L, me in zip(_leg_times(legs, entries, cfg), _leg_times(legs, entries, cfg)) if True]  # noqa: E731
    leg_start = _leg_starts(legs, entries, cfg)
    t = m0 + cfg["every"]
    while t <= 15 * 60 + 15:
        F = float(d.idx[t]) + base * (END - t) / (END - m0)
        if last_F is not None:
            hedge_pnl += H * (F - last_F)
        D = sum(L[2] * delta(F, L[1], T_at(t), L[3], L[0]) for L, ms in zip(legs, leg_start) if ms <= t)
        target = -cfg["h"] * D + (lean if t >= 10 * 60 else 0.0)
        step = target - H
        step = round(step * BOOK_LOTS) / BOOK_LOTS
        if abs(step) >= MIN_HEDGE_STEP - 1e-12:
            atm = b76(F, F, T_at(t), atm_iv, "C")
            cost += abs(step) * (leg_var(atm, "buy", d.e, slip) + leg_var(atm, "sell", d.e, slip))
            cost += brokerage(2, d.lot)
            H += step
        last_F = F
        t += cfg["every"]
    S = d.S_settle
    if last_F is not None:
        hedge_pnl += H * (S - last_F)
        cost += abs(H) * abs(S - last_F) * ob.STT_EXERCISE      # the long hedge leg's exercise, approx.
    payout = 0.0
    for cp, K, u, s in legs:
        intr = ob.intrinsic(cp, K, S)
        payout += u * intr                                        # short: negative u -> pays intrinsic
        if u > 0 and intr > 0:
            cost += u * intr * ob.STT_EXERCISE
    gross = credit + payout + hedge_pnl
    return {"credit": credit, "payout": payout, "hedge": hedge_pnl, "cost": cost, "net": gross - cost,
            "kc": [L[1] for L in legs if L[0] == "C" and L[2] < 0][0],
            "kp": [L[1] for L in legs if L[0] == "P" and L[2] < 0][0]}


def _leg_times(legs, entries, cfg):
    return [0] * len(legs)


def _leg_starts(legs, entries, cfg):
    """Minute each leg is on the book (tranche legs come 2 per entry; tail legs at 09:30)."""
    starts, i = [], 0
    for L in legs:
        starts.append(None)
    # shorts were appended entry by entry, 2 legs each; the tail legs (u > 0) last, at 09:30
    shorts = [k for k, L in enumerate(legs) if L[2] < 0]
    for n, k in enumerate(shorts):
        starts[k] = entries[min(n // 2, len(entries) - 1)] if cfg["tranches"] else entries[0]
    for k, L in enumerate(legs):
        if starts[k] is None:
            starts[k] = 9 * 60 + 30
    return starts


def _straddle_iv(f0, T):
    F, K, c, p = f0
    target = c + p
    try:
        return brentq(lambda s: b76(F, K, T, s, "C") + b76(F, K, T, s, "P") - target, 1e-4, 8.0)
    except ValueError:
        return np.nan


def realised_vol(d, m0=9 * 60 + 30):
    s = d.idx.loc[m0:END - 1].astype(float)
    r = np.diff(np.log(np.r_[s.values, d.S_settle]))
    return math.sqrt(float(np.sum(r * r)) * YEAR_MIN / (END - m0))


# ── the sample ──

def build(limit=None, verbose=False):
    cfgs = {"P": dict(PRIMARY)}
    for name, over in VARIANTS.items():
        cfgs[name] = {**PRIMARY, **over}
    for dl in GRID_DELTA:
        for h in GRID_H:
            for n in GRID_N:
                cfgs[f"g d{dl} h{h} n{n}"] = {**PRIMARY, "delta": dl, "h": h, "every": n}
    rows, vol, skipped = [], [], {}
    with _ro() as conn:
        days = expiry_days(conn)
        for u, e, src in days:
            if limit and len({r["e"] for r in rows}) >= limit:
                break
            d, why = load_day(conn, u, e, src)
            if d is None:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            f0 = forward_at(d, 9 * 60 + 30)
            if f0 is None:
                skipped["no_parity_at_0930"] = skipped.get("no_parity_at_0930", 0) + 1
                continue
            siv = _straddle_iv(f0, T_at(9 * 60 + 30))
            vol.append({"u": u, "e": e, "implied": siv, "realised": realised_vol(d)})
            ok = True
            day_rows = []
            for name, cfg in cfgs.items():
                r = run_day(d, f0, cfg)
                if r is None:
                    if name == "P":
                        ok = False
                        break
                    continue
                day_rows.append({"u": u, "e": e, "src": src, "rule": name, "lot": d.lot, "F": f0[0],
                                 "S": d.S_settle, **r})
            if not ok:
                skipped["no_strike_at_0930"] = skipped.get("no_strike_at_0930", 0) + 1
                continue
            rows += day_rows
            done = len({(r['u'], r['e']) for r in rows if r['rule'] == 'P'})
            if done % 25 == 0:
                print(f"progress {done} days ({u} {e})", file=sys.stderr, flush=True)
            if verbose:
                p = [r for r in day_rows if r["rule"] == "P"][0]
                print(f"{u} {e} {src} lot={d.lot} F={f0[0]:.1f} Katm={f0[1]:.0f} Kc={p['kc']:.0f} Kp={p['kp']:.0f} "
                      f"credit={p['credit']:.2f} payout={p['payout']:.2f} hedge={p['hedge']:.2f} cost={p['cost']:.2f} "
                      f"net={p['net']:.2f} S={d.S_settle:.1f} iv={siv:.3f} rv={vol[-1]['realised']:.3f}")
    df = pd.DataFrame(rows)
    df["rs_lot"] = df["net"] * df["lot"]
    df["pct_margin"] = df["rs_lot"] / (MARGIN_PCT * df["F"] * df["lot"]) * 100
    return df, pd.DataFrame(vol), skipped


def ours(expiry_set):
    """Our live rule (0.05 delta, T-2 settle, held) on the same expiries, ₹ per lot: as-is and at 10-lot brokerage."""
    from tools import option_t1_exit_study as t1
    out = []
    for u in ("NIFTY", "SENSEX"):
        tr = t1.trades(u)
        tr = tr[tr["expiry"].isin({e for uu, e in expiry_set if uu == u})]
        for r in tr.itertuples():
            pts = t1.pnl(r, "hold")[0]
            adj = 2 * ob.BROKERAGE_RS * (1 + ob.GST) / r.lot * (1 - 1 / BOOK_LOTS)
            out.append({"u": u, "e": r.expiry, "ours": pts * r.lot, "ours_10lot": (pts + adj) * r.lot,
                        "ours_pct": pts * r.lot / (0.12 * r.F * r.lot) * 100})
    return pd.DataFrame(out)


# ── statistics ──

def nw_t(x, lags=4):
    x = np.asarray(x, float)
    n = len(x)
    if n < 3:
        return np.nan
    e = x - x.mean()
    s = np.sum(e * e) / n
    for L in range(1, lags + 1):
        s += 2 * (1 - L / (lags + 1)) * np.sum(e[L:] * e[:-L]) / n
    return x.mean() / math.sqrt(s / n) if s > 0 else np.nan


def summarise(x):
    x = pd.Series(x, dtype=float).dropna()
    if x.empty:
        return {}
    m = x.mean()
    return {"n": len(x), "win %": (x > 0).mean() * 100, "mean": m, "median": x.median(),
            "sharpe": m / x.std() * math.sqrt(50) if x.std() > 0 else np.nan, "nw t": nw_t(x.values),
            "worst": x.min(), "worst/mean": (-x.min() / m) if m > 0 else np.nan, "p5": x.quantile(0.05), "total": x.sum()}


def table(rows, cols, fmt=None):
    fmt = fmt or {}
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        cells = []
        for c in cols:
            v = r.get(c, "")
            if isinstance(v, float):
                v = "–" if not np.isfinite(v) else fmt.get(c, "{:,.0f}").format(v)
            cells.append(str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


F2 = {"win %": "{:.0f}", "sharpe": "{:.2f}", "nw t": "{:.2f}", "worst/mean": "{:.1f}", "mean %": "{:.2f}"}


def report(df, vol, skipped):
    L = []
    P = df[df.rule == "P"].copy()
    L.append(f"Sample: {len(P)} expiry days traded (NIFTY {sum(P.u == 'NIFTY')}, SENSEX {sum(P.u == 'SENSEX')}); "
             f"skipped {skipped}. Range NIFTY {P[P.u == 'NIFTY'].e.min()} → {P[P.u == 'NIFTY'].e.max()}, "
             f"SENSEX {P[P.u == 'SENSEX'].e.min()} → {P[P.u == 'SENSEX'].e.max()}.")
    # V1
    L.append("\n## V1 implied vs realised, 09:30 → close, expiry days\n")
    vr = []
    for u in ("NIFTY", "SENSEX"):
        for lab, g in (("all", vol[vol.u == u]), ("2026", vol[(vol.u == u) & (vol.e >= "2026")])):
            g = g.dropna()
            if g.empty:
                continue
            vr.append({"index": u, "window": lab, "days": len(g), "implied median %": g.implied.median() * 100,
                       "realised median %": g.realised.median() * 100,
                       "gap median pts": (g.implied - g.realised).median() * 100,
                       "days implied > realised %": (g.implied > g.realised).mean() * 100})
    L.append(table(vr, ["index", "window", "days", "implied median %", "realised median %", "gap median pts",
                        "days implied > realised %"], {"implied median %": "{:.1f}", "realised median %": "{:.1f}",
                                                       "gap median pts": "{:.1f}", "days implied > realised %": "{:.0f}"}))
    # P
    L.append("\n## Primary rule P, ₹ per lot per expiry day\n")
    pr = []
    for u in ("NIFTY", "SENSEX"):
        g = P[P.u == u]
        pr.append({"index": u, **summarise(g.rs_lot), "mean %": g.pct_margin.mean()})
    L.append(table(pr, ["index", "n", "win %", "mean", "median", "sharpe", "nw t", "worst", "worst/mean", "p5", "total", "mean %"], F2))
    L.append("\nBy year:\n")
    yr = []
    for (u, y), g in P.assign(y=P.e.str[:4]).groupby(["u", "y"]):
        yr.append({"index": u, "year": y, "n": len(g), "win %": (g.rs_lot > 0).mean() * 100, "mean": g.rs_lot.mean(),
                   "total": g.rs_lot.sum(), "worst": g.rs_lot.min()})
    L.append(table(yr, ["index", "year", "n", "win %", "mean", "total", "worst"], F2))
    # V2, V3
    L.append("\n## V2 hit rate 2026, V3 stress days\n")
    v2 = []
    for u in ("NIFTY", "SENSEX"):
        g = P[(P.u == u) & (P.e >= "2026")]
        hr = (g.rs_lot > 0).mean() * 100 if len(g) else np.nan
        v2.append({"index": u, "days": len(g), "P hit %": hr, "SOCAP hit %": SOCAP_HIT_2026[u],
                   "holds": "yes" if np.isfinite(hr) and abs(hr - SOCAP_HIT_2026[u]) <= 15 else "no"})
    L.append(table(v2, ["index", "days", "P hit %", "SOCAP hit %", "holds"], {"P hit %": "{:.0f}", "SOCAP hit %": "{:.0f}"}))
    v3 = []
    for u, e in STRESS:
        g = P[(P.u == u) & (P.e == e)]
        v3.append({"day": f"{u} {e}", "P ₹/lot": float(g.rs_lot.iloc[0]) if len(g) else np.nan,
                   "move F→S %": float((g.S / g.F - 1).iloc[0] * 100) if len(g) else np.nan,
                   "loses": ("yes" if len(g) and g.rs_lot.iloc[0] < 0 else ("no" if len(g) else "no data"))})
    L.append("\n" + table(v3, ["day", "P ₹/lot", "move F→S %", "loses"], {"move F→S %": "{:+.2f}"}))
    # vs ours
    L.append("\n## P against our live rule on the same expiries (₹ per lot)\n")
    o = ours({(u, e) for u, e in zip(P.u, P.e)})
    m = P.merge(o, on=["u", "e"], how="inner")
    cr = []
    for u in ("NIFTY", "SENSEX"):
        g = m[m.u == u]
        for lab, col in (("SOCAP P", "rs_lot"), ("ours (as-is)", "ours"), ("ours (10-lot brokerage)", "ours_10lot")):
            cr.append({"index": u, "book": lab, **summarise(g[col])})
        g2 = g.assign(mix=(g.rs_lot + g.ours_10lot) / 2)
        cr.append({"index": u, "book": "50/50", **summarise(g2.mix)})
        cr.append({"index": u, "book": f"correlation P vs ours = {g.rs_lot.corr(g.ours_10lot):.2f}"})
    L.append(table(cr, ["index", "book", "n", "win %", "mean", "median", "sharpe", "worst", "worst/mean", "p5", "total"], F2))
    # decision
    L.append("\n## Decision (pre-registered)\n")
    nf = P[P.u == "NIFTY"]
    years = nf.assign(y=nf.e.str[:4]).groupby("y").rs_lot.sum()
    c1 = nw_t(nf.rs_lot.values)
    sx = P[P.u == "SENSEX"]
    checks = [(f"1. NIFTY mean > 0 with NW t ≥ 2.0 (mean ₹{nf.rs_lot.mean():,.0f}, t {c1:.2f})",
               nf.rs_lot.mean() > 0 and c1 >= 2.0),
              (f"2. NIFTY positive in ≥ 4 of 6 years ({int((years > 0).sum())} of {len(years)})", (years > 0).sum() >= 4),
              (f"3. SENSEX mean > 0 (₹{sx.rs_lot.mean():,.0f})", sx.rs_lot.mean() > 0)]
    for u in ("NIFTY", "SENSEX"):
        g = m[m.u == u]
        a, b = summarise(g.rs_lot), summarise(g.ours)
        better = (a.get("sharpe", -9) > b.get("sharpe", 9)) and (
            np.isfinite(a.get("worst/mean", np.nan)) and a["worst/mean"] < b.get("worst/mean", np.inf))
        checks.append((f"4. {u}: P Sharpe {a.get('sharpe', np.nan):.2f} vs ours {b.get('sharpe', np.nan):.2f}; "
                       f"worst/mean {a.get('worst/mean', np.nan):.1f} vs {b.get('worst/mean', np.nan):.1f}", better))
    for txt, ok in checks:
        L.append(f"- {'PASS' if ok else 'FAIL'} {txt}")
    L.append(f"\n**Verdict: {'KEEP (forward paper-test candidate)' if all(ok for _, ok in checks) else 'DROP'}**")
    # variants and grid
    L.append("\n## Variants on P (reported, not deciding)\n")
    vv = []
    for name in VARIANTS:
        for u in ("NIFTY", "SENSEX"):
            g = df[(df.rule == name) & (df.u == u)]
            vv.append({"variant": name, "index": u, **summarise(g.rs_lot)})
    L.append(table(vv, ["variant", "index", "n", "win %", "mean", "sharpe", "worst", "worst/mean", "total"], F2))
    L.append("\n## Grid: Δ × hedge ratio h × rebalance minutes (reported, not deciding)\n")
    gg = []
    for dl in GRID_DELTA:
        for h in GRID_H:
            for n in GRID_N:
                row = {"Δ": float(dl), "h": float(h), "N": n}
                for u in ("NIFTY", "SENSEX"):
                    s = summarise(df[(df.rule == f"g d{dl} h{h} n{n}") & (df.u == u)].rs_lot)
                    row[f"{u} mean"], row[f"{u} sharpe"], row[f"{u} worst"] = s.get("mean"), s.get("sharpe"), s.get("worst")
                gg.append(row)
    L.append(table(gg, ["Δ", "h", "N", "NIFTY mean", "NIFTY sharpe", "NIFTY worst", "SENSEX mean", "SENSEX sharpe", "SENSEX worst"],
                   {"Δ": "{:.2f}", "h": "{:.1f}", "NIFTY sharpe": "{:.2f}", "SENSEX sharpe": "{:.2f}"}))
    # parts of P
    L.append("\n## Where P's money comes from (mean points per unit)\n")
    pp = []
    for u in ("NIFTY", "SENSEX"):
        g = P[P.u == u]
        pp.append({"index": u, "credit": g.credit.mean(), "payout": g.payout.mean(), "hedge": g.hedge.mean(),
                   "cost": g.cost.mean(), "net": g.net.mean(), "cost/credit %": g.cost.mean() / g.credit.mean() * 100})
    L.append(table(pp, ["index", "credit", "payout", "hedge", "cost", "net", "cost/credit %"],
                   {k: "{:.2f}" for k in ("credit", "payout", "hedge", "cost", "net")} | {"cost/credit %": "{:.1f}"}))
    worst = P.sort_values("rs_lot").head(8)[["u", "e", "F", "S", "kc", "kp", "credit", "hedge", "net", "rs_lot"]]
    L.append("\nWorst 8 days of P:\n")
    L.append(table(worst.assign(move=(worst.S / worst.F - 1) * 100).to_dict("records"),
                   ["u", "e", "F", "S", "move", "kc", "kp", "credit", "hedge", "net", "rs_lot"],
                   {"move": "{:+.2f}", "credit": "{:.1f}", "hedge": "{:.1f}", "net": "{:.1f}"}))
    return "\n".join(L), m


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--report")
    ap.add_argument("--csv")
    a = ap.parse_args(argv)
    if a.smoke:
        df, vol, sk = build(limit=3, verbose=True)
        print(sk)
        return 0
    df, vol, sk = build()
    text, m = report(df, vol, sk)
    print(text)
    if a.report:
        with open(a.report, "w") as f:
            f.write(text + "\n")
    if a.csv:
        df.to_csv(a.csv, index=False)
        m.to_csv(a.csv.replace(".csv", "_vs_ours.csv"), index=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
