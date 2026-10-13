"""Plan 0024, H3 — does a long-hold book earn after Zerodha costs and Indian tax?  (READ-ONLY on the DB)

Implements docs/studies/long-horizon-2026-10/03-design.md (the pre-registered rules):
  - monthly anchors; trades fill at the entry of pit.forward_returns (close of the first
    session after the anchor); position returns chain `fwd_next_anchor` (data/lh/labels.parquet)
  - scores: the H2 walk-forward out-of-sample scores only (data/lh/oos_scores.parquet)
  - equal weight at entry, no trimming; buy from the top N, sell only below rank k*N after the
    minimum hold; forensic_penalty <= -0.20 forces a sale and blocks a buy
  - tax deferral: a short-term gain that turns long-term within 42 days waits
  - every trade pays tools.lh_costs.one_way_cost_bps (side, year)
  - tax per Indian FY: STCG 20 % + 4 % cess, LTCG 12.5 % + cess above Rs 1.25 L, set-off,
    8-year carry-forward, dividends 31.2 %; reserve from each sale, bill paid at the first
    anchor after 31 March, shortfall raised by selling (losses, then LT, then ST lots)
  - benchmark: the tier index bought once, dividends credited, taxed only on the final sale
  - judged on monthly after-tax-liquidation-value (ATLV) excess, Newey-West t (lag 3),
    Bonferroni haircut over the variants tried in the tier.

Usage:
    python -m tools.lh_book              # full grid + comparisons + diagnostics (a few minutes)
    python -m tools.lh_book --smoke      # 2 variants per tier, quick
Writes data/lh/book_results.json, data/lh/book_variants.csv, data/lh/book_monthly.parquet.
Never writes the DB.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.backtest_pit import _newey_west_se  # noqa: E402
from tools import lh_costs  # noqa: E402

DB = ROOT / "data" / "alpha_signal.db"
LH = ROOT / "data" / "lh"
TIERS = ("LARGE", "MID", "SMALL")
CAPITAL = 1_000_000.0
FLAG = -0.20                 # forensic_penalty at or below this = red flag
DEFER_DAYS = 42
NW_LAG = 3
MISS_LIMIT = 3               # no price for 3 anchors running -> sell at the last mark

# Tax rules. 'today': the rates in force since 23 July 2024, applied to every year (the plan).
RULES = {
    "today": {"st": 0.20 * 1.04, "lt": 0.125 * 1.04, "div": 0.30 * 1.04, "ex": 125_000.0},
    "none": {"st": 0.0, "lt": 0.0, "div": 0.0, "ex": 0.0},
}
# 'historical' (diagnostic): FY up to 2023-24 at 15 % / 10 % / Rs 1 L; FY 2024-25 onward at
# today's rules (approximation: sales of Apr-Jul 2024 were really at the old rates).
HIST_OLD = {"st": 0.15 * 1.04, "lt": 0.10 * 1.04, "div": 0.30 * 1.04, "ex": 100_000.0}

BENCH_INDEX = {"LARGE": "NIFTY 50", "SMALL": "NIFTY SMALLCAP 250", "MID": "NIFTY MIDCAP 150"}
MID_INDEX_FROM = "2023-06-01"   # before this anchor MID's benchmark is the tier equal-weight average
BENCH_FEE = {"LARGE": 0.002, "MID": 0.003, "SMALL": 0.003}   # diagnostic only (assumption)


def ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def fy_of(d: pd.Timestamp) -> int:
    """Financial year by its starting calendar year (FY 2024-25 -> 2024)."""
    return d.year if d.month >= 4 else d.year - 1


def rules_for(name, fy):
    if name == "historical":
        return HIST_OLD if fy <= 2023 else RULES["today"]
    return RULES[name]


# ───────────────────────────── data ─────────────────────────────

class Data:
    """Everything the simulation reads, keyed by anchor index i."""

    def __init__(self):
        t0 = time.time()
        sc = pd.read_parquet(LH / "oos_scores.parquet")
        lab = pd.read_parquet(LH / "labels.parquet",
                              columns=["sid", "snapshot_date", "cap_tier", "fwd_next_anchor"])
        anchors = sorted(sc["snapshot_date"].unique())
        self.anchors = anchors
        n = len(anchors)
        lab = lab[lab["snapshot_date"].isin(anchors)]
        con = ro()
        ph = ",".join("?" * n)
        panel = pd.read_sql(f"SELECT sid, snapshot_date, cap_tier, forensic_penalty FROM daily_snapshots_pit "
                            f"WHERE snapshot_date IN ({ph})", con, params=anchors)
        px = pd.read_sql("SELECT sid, date, close, volume, traded_value FROM stock_prices "
                         "WHERE date >= ? AND close > 0", con,
                         params=[(pd.Timestamp(anchors[0]) - pd.Timedelta(days=60)).date().isoformat()])
        adj = pd.read_sql("SELECT sid, ex_date, factor, inds FROM corporate_adjustments", con)
        idx = pd.read_sql("SELECT index_symbol, trade_date, close FROM nse_index_history "
                          "WHERE index_symbol IN ('NIFTY 50','NIFTY SMALLCAP 250','NIFTY MIDCAP 150')", con)
        mc_today = pd.read_sql("SELECT sid, market_cap_cr FROM stocks WHERE market_cap_cr > 0", con)
        con.close()

        cal = np.sort(px["date"].unique())
        self.entry = []
        for a in anchors:
            k = int(np.searchsorted(cal, a, side="right"))
            self.entry.append(pd.Timestamp(cal[k]) if k < len(cal) else None)
        assert all(e is not None for e in self.entry), "an anchor has no entry session yet"

        # returns, tiers, equal-weight tier averages
        self.ret, self.tier_of, self.ew = [], [], []
        for a in anchors:
            g = lab[lab["snapshot_date"] == a]
            self.ret.append(dict(zip(g["sid"], g["fwd_next_anchor"])))
            self.tier_of.append(dict(zip(g["sid"], g["cap_tier"])))
            self.ew.append({t: float(g.loc[g["cap_tier"] == t, "fwd_next_anchor"].mean()) for t in TIERS})
        # red flags
        self.flags = []
        for a in anchors:
            g = panel[panel["snapshot_date"] == a]
            self.flags.append(set(g.loc[g["forensic_penalty"] <= FLAG + 1e-9, "sid"]))

        # liquidity at each anchor: ADTV = median traded value of the last 20 sessions <= anchor
        # volume x close, always: stock_prices.traded_value is in Rs lakh where present (2022-07 onward
        # for many rows) and NULL elsewhere, so mixing it with volume x close understates ADTV ~1e5x.
        px["tv"] = px["volume"] * px["close"]
        self.adtv, self.price = [], []
        for a in anchors:
            k = int(np.searchsorted(cal, a, side="right"))
            last20 = cal[max(0, k - lh_costs.ADTV_WINDOW):k]
            w = px[px["date"].isin(set(last20))]
            self.adtv.append(w.groupby("sid")["tv"].median().to_dict())
            self.price.append(w.sort_values("date").groupby("sid")["close"].last().to_dict())

        # dividends earned over month i: ex-date in (entry_i, entry_{i+1}]
        adj["ex_date"] = pd.to_datetime(adj["ex_date"])
        pure = adj[adj["inds"] == "DIVIDEND"]
        mixed = adj[adj["inds"].str.contains("DIVIDEND") & (adj["inds"] != "DIVIDEND")]
        self.div = []
        self.div_mixed_skipped = 0
        for i in range(n):
            if i + 1 >= n:
                self.div.append({})
                continue
            lo, hi = self.entry[i], self.entry[i + 1]
            g = pure[(pure["ex_date"] > lo) & (pure["ex_date"] <= hi)]
            d = (1 - g.groupby("sid")["factor"].prod()).clip(lower=0)
            self.div.append(d.to_dict())
            self.div_mixed_skipped += int(((mixed["ex_date"] > lo) & (mixed["ex_date"] <= hi)).sum())

        # benchmark: index level at each entry session
        idx["trade_date"] = pd.to_datetime(idx["trade_date"])
        self.idx_level = {}
        for sym, g in idx.groupby("index_symbol"):
            s = g.set_index("trade_date")["close"].sort_index()
            self.idx_level[sym] = [float(s[:e].iloc[-1]) if len(s[:e]) and (e - s[:e].index[-1]).days <= 5
                                   else np.nan for e in self.entry]

        # cap-weighted dividend yield of each tier per month (credit for the price indices).
        # Market cap at the anchor ~ today's market cap x (close_t / close_today) x the split/bonus
        # factors after t (approximation: only used to weight the dividend credit).
        last_close = px.sort_values("date").groupby("sid")["close"].last()
        sb = adj[adj["inds"].str.contains("SPLIT|BONUS", regex=True)]
        mc_today = mc_today.set_index("sid")["market_cap_cr"]
        self.tier_div_yield = []
        for i, a in enumerate(anchors):
            tiers = pd.Series(self.tier_of[i])
            p_t = pd.Series(self.price[i])
            later = sb[sb["ex_date"] > pd.Timestamp(a)].groupby("sid")["factor"].prod()
            mc = (mc_today / last_close).reindex(p_t.index) * p_t * later.reindex(p_t.index).fillna(1.0)
            d = pd.Series(self.div[i], dtype=float).reindex(p_t.index).fillna(0.0)
            out = {}
            for t in TIERS:
                m = tiers[tiers == t].index.intersection(mc.dropna().index)
                w = mc[m]
                out[t] = float((w * d[m]).sum() / w.sum()) if len(m) and w.sum() > 0 else 0.0
            self.tier_div_yield.append(out)

        # rankings: per (method, signal type) per anchor -> sid -> (tier, rank, size); and the
        # ordered candidate list per tier
        self.rank = {}
        sc = sc.sort_values(["method", "snapshot_date"])
        for m, g in sc.groupby("method"):
            piv = g.pivot_table(index="snapshot_date", columns="sid", values="score").reindex(anchors)
            tier_piv = g.pivot(index="snapshot_date", columns="sid", values="cap_tier").reindex(anchors)
            avg3 = piv.rolling(3, min_periods=1).mean().where(piv.notna())
            for kind, sig in (("raw", piv), ("avg3", avg3)):
                per = []
                for i, a in enumerate(anchors):
                    s = sig.loc[a].dropna()
                    tr = tier_piv.loc[a].reindex(s.index)
                    df = pd.DataFrame({"sig": s, "tier": tr})
                    df["rank"] = df.groupby("tier")["sig"].rank(ascending=False, method="first")
                    df["size"] = df.groupby("tier")["sig"].transform("size")
                    order = {t: list(df[df["tier"] == t].sort_values("rank").index) for t in TIERS}
                    per.append({"info": dict(zip(df.index, zip(df["tier"], df["rank"], df["size"]))),
                                "order": order,
                                "size": {t: len(order[t]) for t in TIERS}})
                self.rank[(m, kind)] = per
        print(f"data loaded in {time.time() - t0:.0f}s: {n} anchors {anchors[0]} -> {anchors[-1]}, "
              f"entries {self.entry[0].date()} -> {self.entry[-1].date()}; "
              f"mixed dividend rows skipped {self.div_mixed_skipped}", flush=True)


# ───────────────────────────── tax ─────────────────────────────

def fy_tax(st, lt, div, carry, fy, rules):
    """Tax for one FY. st / lt = net realised gains (may be negative). carry = list of
    [fy, kind, amount] losses carried in (not mutated). Returns (tax, new_carry)."""
    r = rules
    # 1. intra-year set-off: a short-term loss may absorb long-term gains; a long-term loss may not absorb short-term
    if st < 0 and lt > 0:
        use = min(-st, lt)
        st += use
        lt -= use
    st_loss, lt_loss = max(-st, 0.0), max(-lt, 0.0)
    st, lt = max(st, 0.0), max(lt, 0.0)
    # 2. carried losses, oldest first, 8-year life
    new = []
    for cfy, kind, amt in sorted(carry, key=lambda x: x[0]):
        if fy - cfy > 8 or amt <= 0:
            continue
        if kind == "ST":
            u = min(amt, st); st -= u; amt -= u
            u = min(amt, lt); lt -= u; amt -= u
        else:
            u = min(amt, lt); lt -= u; amt -= u
        if amt > 1e-9:
            new.append([cfy, kind, amt])
    if st_loss > 0:
        new.append([fy, "ST", st_loss])
    if lt_loss > 0:
        new.append([fy, "LT", lt_loss])
    lt_tax = max(lt - r["ex"], 0.0)
    tax = r["st"] * st + r["lt"] * lt_tax + r["div"] * max(div, 0.0)
    return tax, new


def is_lt(buy_date, sell_date):
    return sell_date > buy_date + pd.DateOffset(months=12)


# ───────────────────────────── one book ─────────────────────────────

def km_median(durations, events):
    """Kaplan-Meier median (months); events False = censored. None if the curve never reaches 0.5."""
    if not durations:
        return None
    d = np.asarray(durations, float)
    e = np.asarray(events, bool)
    order = np.argsort(d, kind="stable")
    d, e = d[order], e[order]
    s, n_at = 1.0, len(d)
    i = 0
    while i < len(d):
        t = d[i]
        j = i
        deaths = 0
        while j < len(d) and d[j] == t:
            deaths += int(e[j]); j += 1
        if deaths:
            s *= 1 - deaths / n_at
            if s <= 0.5:
                return float(t)
        n_at -= (j - i)
        i = j
    return None


def simulate(D: Data, tier, v, bench_tier_series):
    """One book. v = variant dict. Returns (summary dict, monthly DataFrame)."""
    method, kind = v["method"], v["score"]
    R = D.rank[(method, kind)]
    N, k, min_hold = v["N"], v["k"], v["min_hold"]
    exit_rank = k * N
    quarterly = v["reb"] == "Q"
    defer = v.get("defer", True)
    stress = v.get("stress", False)
    rules_name = v.get("tax", "today")
    cap0 = v.get("capital", CAPITAL)
    n = len(D.anchors)

    def cost_bps(sid, i, value, side):
        return lh_costs.one_way_cost_bps(D.adtv[i].get(sid), D.price[i].get(sid, 100.0), max(value, 1.0),
                                         tier, side=side, year=D.entry[i].year, stress=stress)

    pos = {}          # sid -> dict(buy_date, buy_i, basis, value, miss)
    cash, reserve = cap0, 0.0
    cur_fy = fy_of(D.entry[0])
    fy_st = fy_lt = fy_div = 0.0
    carry = []
    lives = []        # (months, event)
    stats_ = dict(trades=0, buys=0.0, sells=0.0, costs=0.0, tax_paid=0.0, forced=0, writeoffs=0,
                  deferred_events=0, deferred_names=set(), deferred_became_lt=0, tax_sales=0,
                  gain_st_pos=0.0, gain_lt_pos=0.0, div_total=0.0, no_signal_exits=0, empty_months=0)
    deferred = set()
    rows = []
    nav_hist, cash_share = [], []

    def sell(sid, i, frac=1.0, final=False, reason="band"):
        nonlocal cash, reserve, fy_st, fy_lt
        p = pos[sid]
        val = p["value"] * frac
        c = cost_bps(sid, i, val, "sell") / 1e4
        proceeds = val * (1 - c)
        basis = p["basis"] * frac
        gain = proceeds - basis
        lt = is_lt(p["buy_date"], D.entry[i])
        r = rules_for(rules_name, fy_of(D.entry[i]))
        if lt:
            fy_lt += gain
        else:
            fy_st += gain
        if gain > 0:
            reserve += gain * (r["lt"] if lt else r["st"])
            if lt:
                stats_["gain_lt_pos"] += gain
            else:
                stats_["gain_st_pos"] += gain
        cash += proceeds
        stats_["costs"] += val * c
        stats_["trades"] += 1
        if not final:
            stats_["sells"] += val
        if sid in stats_["deferred_names"] and frac >= 1.0:
            stats_["deferred_became_lt"] += int(lt)
            stats_["deferred_names"].discard(sid)
        if frac >= 1.0:
            months = (D.entry[i] - p["buy_date"]).days / 30.4375
            lives.append((months, not final))
            del pos[sid]
            deferred.discard(sid)
        else:
            p["value"] -= val
            p["basis"] -= basis

    def buy(sid, i, amount):
        nonlocal cash
        c = cost_bps(sid, i, amount, "buy") / 1e4
        pos[sid] = dict(buy_date=D.entry[i], buy_i=i, basis=amount, value=amount * (1 - c), miss=0)
        cash -= amount
        stats_["costs"] += amount * c
        stats_["trades"] += 1
        return amount

    def liquidation_value(i):
        """Cash after selling everything at entry i and paying this FY's tax (no state change)."""
        st, lt, proceeds = fy_st, fy_lt, 0.0
        for sid, p in pos.items():
            c = cost_bps(sid, i, p["value"], "sell") / 1e4
            pr = p["value"] * (1 - c)
            g = pr - p["basis"]
            if is_lt(p["buy_date"], D.entry[i]):
                lt += g
            else:
                st += g
            proceeds += pr
        tax, _ = fy_tax(st, lt, fy_div, carry, cur_fy, rules_for(rules_name, cur_fy))
        return cash + proceeds - tax

    def settle(i):
        """Pay the bill of the FY that just ended (at the first anchor after 31 March)."""
        nonlocal cash, reserve, fy_st, fy_lt, fy_div, carry, cur_fy
        tax, carry = fy_tax(fy_st, fy_lt, fy_div, carry, cur_fy, rules_for(rules_name, cur_fy))
        cur_fy = fy_of(D.entry[i])
        fy_st = fy_lt = fy_div = 0.0
        reserve = 0.0
        stats_["tax_paid"] += tax
        if cash < tax:   # shortfall: sell losses, then LT lots with the lowest gain per rupee, then ST
            need = tax - cash
            order = []
            for sid, p in pos.items():
                g = p["value"] - p["basis"]
                lt = is_lt(p["buy_date"], D.entry[i])
                grp = 0 if g < 0 else (1 if lt else 2)
                order.append((grp, g / max(p["value"], 1.0), sid))
            for _, _, sid in sorted(order):
                if need <= 0:
                    break
                p = pos[sid]
                frac = min(1.0, (need * 1.02 + 2_000.0) / max(p["value"], 1.0))   # + margin for the per-sale DP charge
                before = cash
                sell(sid, i, frac=frac, reason="tax")
                stats_["tax_sales"] += 1
                need -= cash - before
        cash -= tax

    def rank_ok(sid, i):
        """True if the stock is inside the exit band; None if it has no signal at i."""
        info = R[i]["info"].get(sid)
        if info is None:
            return None
        t_, rk, size = info
        if t_ == tier:
            return rk <= exit_rank
        home = R[i]["size"][tier] or 1
        return (rk / size) <= exit_rank / home

    bench = bench_tier_series
    for i in range(n):
        e = D.entry[i]
        # 1. mark to market (month i-1 -> i), dividends for tax
        if i > 0:
            for sid, p in pos.items():
                r = D.ret[i - 1].get(sid)
                dv = D.div[i - 1].get(sid, 0.0)
                if dv > 0:
                    fy_div += p["value"] * dv
                    stats_["div_total"] += p["value"] * dv
                if r is None or not np.isfinite(r):
                    p["miss"] += 1
                    r = 0.0
                else:
                    p["miss"] = 0
                p["value"] *= 1 + r
        # FY boundary: settle at the first anchor after 31 March
        if i > 0 and fy_of(e) != cur_fy:
            settle(i)
        mv = sum(p["value"] for p in pos.values())
        nav = mv + cash - reserve
        atlv = liquidation_value(i) if i < n - 1 else None
        if i == 0:
            atlv = cap0
        # final anchor: liquidate everything and settle
        if i == n - 1:
            for sid in list(pos):
                sell(sid, i, final=True)
            tax, carry = fy_tax(fy_st, fy_lt, fy_div, carry, cur_fy, rules_for(rules_name, cur_fy))
            stats_["tax_paid"] += tax
            cash -= tax
            atlv = cash
            rows.append(dict(i=i, date=D.anchors[i], entry=e.date().isoformat(), atlv=atlv, nav=nav,
                             n_pos=0, cash=cash))
            break
        nav_hist.append(nav)
        cash_share.append((cash - reserve) / nav if nav > 0 else 0.0)
        rows.append(dict(i=i, date=D.anchors[i], entry=e.date().isoformat(), atlv=atlv, nav=nav,
                         n_pos=len(pos), cash=cash - reserve))

        flags = D.flags[i]
        have_signal = R[i]["size"][tier] > 0
        if not have_signal:
            stats_["empty_months"] += 1
        on_cycle = (not quarterly) or (i % 3 == 0)
        freed = False
        # 2. forced exits
        for sid in list(pos):
            if sid in flags:
                sell(sid, i, reason="flag"); stats_["forced"] += 1; freed = True
            elif pos[sid]["miss"] >= MISS_LIMIT:
                sell(sid, i, reason="noprice"); stats_["writeoffs"] += 1; freed = True
        # 3-4. band exits (on cycle) and re-tests of deferred names (every anchor)
        if have_signal:
            test = list(pos) if on_cycle else [s for s in pos if s in deferred]
            for sid in test:
                p = pos[sid]
                ok = rank_ok(sid, i)
                if ok:
                    deferred.discard(sid)
                    continue
                if (i - p["buy_i"]) < min_hold:
                    continue
                if defer and not is_lt(p["buy_date"], e):
                    c = cost_bps(sid, i, p["value"], "sell") / 1e4
                    gain = p["value"] * (1 - c) - p["basis"]
                    lt_date = p["buy_date"] + pd.DateOffset(months=12) + pd.Timedelta(days=1)
                    if gain > 0 and (lt_date - e).days <= DEFER_DAYS:
                        if sid not in deferred:
                            stats_["deferred_events"] += 1
                        deferred.add(sid)
                        stats_["deferred_names"].add(sid)
                        continue
                if ok is None:
                    stats_["no_signal_exits"] += 1
                was_deferred = sid in deferred
                sell(sid, i)
                freed = freed or was_deferred
        # 5-6. buys: on cycle, or off cycle to refill a forced / deferred sale (quarterly)
        if have_signal and (on_cycle or freed) and len(pos) < N:
            top = [s for s in R[i]["order"][tier][:N]
                   if s not in pos and s not in flags and D.adtv[i].get(s, 0) > 0]
            free = N - len(pos)
            new = top[:free]
            if new:
                mv = sum(p["value"] for p in pos.values())
                nav_now = mv + cash - reserve
                avail = cash - reserve
                size = min(nav_now / N, avail / len(new))
                if size > 0:
                    for s in new:
                        amt = buy(s, i, size)
                        if i > 0:
                            stats_["buys"] += amt

    # ── summary ──
    m = pd.DataFrame(rows)
    m["bench"] = bench["atlv"].values[: len(m)]
    m["bench_ew"] = bench["atlv_ew"].values[: len(m)]
    years = (D.entry[-1] - D.entry[0]).days / 365.25
    out = summarise(m, years, v, cap0)
    avg_nav = float(np.mean(nav_hist)) if nav_hist else cap0
    durs = [d for d, _ in lives]
    evs = [ev for _, ev in lives]
    closed = [d for d, ev in lives if ev]
    out.update(
        trades=stats_["trades"],
        turnover_pa=round(0.5 * (stats_["buys"] + stats_["sells"]) / avg_nav / years, 4),
        costs_paid_inr=round(stats_["costs"], 0),
        costs_bps_pa=round(stats_["costs"] / avg_nav / years * 1e4, 1),
        tax_paid_inr=round(stats_["tax_paid"], 0),
        carry_left_inr=round(sum(c[2] for c in carry), 0),
        dividends_inr=round(stats_["div_total"], 0),
        lt_share_of_gains=(round(stats_["gain_lt_pos"] / (stats_["gain_lt_pos"] + stats_["gain_st_pos"]), 4)
                           if stats_["gain_lt_pos"] + stats_["gain_st_pos"] > 0 else None),
        median_hold_km_m=(round(km_median(durs, evs), 2) if km_median(durs, evs) is not None else None),
        # KM curve never fell to 0.5: the median is longer than the longest lifetime observed
        median_hold_km_lower_bound_m=(round(max(durs), 2) if durs and km_median(durs, evs) is None else None),
        median_hold_closed_m=round(float(np.median(closed)), 2) if closed else None,
        mean_hold_closed_m=round(float(np.mean(closed)), 2) if closed else None,
        positions=len(lives), positions_closed=len(closed),
        forced_exits=stats_["forced"], writeoffs=stats_["writeoffs"],
        deferred_events=stats_["deferred_events"], deferred_sold_lt=stats_["deferred_became_lt"],
        tax_sales=stats_["tax_sales"], no_signal_exits=stats_["no_signal_exits"],
        months_without_scores=stats_["empty_months"],
        avg_cash_share=round(float(np.mean(cash_share)), 4) if cash_share else None,
    )
    return out, m


def summarise(m, years, v, cap0):
    a = m["atlv"].values.astype(float)
    b = m["bench"].values.astype(float)
    bew = m["bench_ew"].values.astype(float)
    rb, rx = a[1:] / a[:-1] - 1, b[1:] / b[:-1] - 1
    x = rb - rx
    xe = rb - (bew[1:] / bew[:-1] - 1)
    n = len(x)

    def tstat(s):
        se = _newey_west_se(np.asarray(s, float), NW_LAG)
        return float(np.mean(s) / se) if se and se > 0 else None

    t = tstat(x)
    cagr = (a[-1] / cap0) ** (1 / years) - 1
    bcagr = (b[-1] / b[0]) ** (1 / years) - 1
    bewcagr = (bew[-1] / bew[0]) ** (1 / years) - 1
    w12 = [(a[j + 12] / a[j]) / (b[j + 12] / b[j]) - 1 for j in range(len(a) - 12)]
    peak = np.maximum.accumulate(a)
    return dict(
        n_months=n,
        cagr_after_tax=round(cagr, 4), bench_cagr_after_tax=round(bcagr, 4),
        excess_cagr=round(cagr - bcagr, 4),
        excess_mean_pa=round(float(np.mean(x)) * 12, 4),
        t_nw=round(t, 3) if t is not None else None,
        bench_ew_cagr_after_tax=round(bewcagr, 4), excess_cagr_vs_ew=round(cagr - bewcagr, 4),
        t_nw_vs_ew=round(tstat(xe), 3) if tstat(xe) is not None else None,
        worst_12m_excess=round(float(min(w12)), 4) if w12 else None,
        max_drawdown=round(float(np.min(a / peak - 1)), 4),
        final_atlv=round(float(a[-1]), 0), bench_final_atlv=round(float(b[-1]), 0),
        _x=list(map(float, x)),
    )


def haircut_t(t, n_obs, trials):
    if t is None:
        return None
    df = n_obs - 1
    p = 2 * stats.t.sf(abs(t), df)
    p_adj = min(1.0, p * trials)
    if p_adj >= 1.0:
        return 0.0
    return float(math.copysign(stats.t.isf(p_adj / 2, df), t))


def deflated_sharpe(x_best, sr_trials, n_trials):
    """Bailey & Lopez de Prado (2014) DSR on monthly excess returns (non-annualised Sharpe)."""
    x = np.asarray(x_best, float)
    T = len(x)
    sr = x.mean() / x.std(ddof=1)
    sk = stats.skew(x)
    ku = stats.kurtosis(x, fisher=False)
    v = np.var(sr_trials, ddof=1)
    g = 0.5772156649
    sr0 = math.sqrt(v) * ((1 - g) * stats.norm.ppf(1 - 1 / n_trials) + g * stats.norm.ppf(1 - 1 / (n_trials * math.e)))
    den = math.sqrt(max(1 - sk * sr + (ku - 1) / 4 * sr ** 2, 1e-12))
    return float(stats.norm.cdf((sr - sr0) * math.sqrt(T - 1) / den)), float(sr), float(sr0)


# ───────────────────────────── benchmark ─────────────────────────────

def benchmark(D: Data, tier, fee=0.0, rules_name="today", cap0=CAPITAL):
    """Monthly ATLV of the tier index (dividends credited, taxed only on the final sale) and of the
    tier equal-weight average (second benchmark). Values at each entry session."""
    n = len(D.anchors)
    lev = D.idx_level[BENCH_INDEX[tier]]
    rows = []
    v = vew = cap0
    src = []
    for i in range(n):
        if i > 0:
            if tier == "MID" and D.anchors[i - 1] < MID_INDEX_FROM:
                r = D.ew[i - 1][tier]; s = "EW"
            else:
                r = lev[i] / lev[i - 1] - 1 + D.tier_div_yield[i - 1][tier]; s = "index"
            src.append(s)
            v *= (1 + r) * (1 - fee / 12)
            vew *= 1 + D.ew[i - 1][tier]
        e = D.entry[i]

        def after_tax(val):
            g = val - cap0
            fy = fy_of(e)
            rr = rules_for(rules_name, fy)
            if is_lt(D.entry[0], e):
                return val - rr["lt"] * max(g - rr["ex"], 0.0)
            return val - rr["st"] * max(g, 0.0)
        rows.append(dict(i=i, pre=v, atlv=after_tax(v), pre_ew=vew, atlv_ew=after_tax(vew)))
    df = pd.DataFrame(rows)
    df.attrs["sources"] = {s: src.count(s) for s in set(src)}
    return df


# ───────────────────────────── grid ─────────────────────────────

def grid(method="slow_select"):
    out = []
    for reb in ("M", "Q"):
        for N in (10, 15, 20):
            for k in (2, 3, 4):
                for score in ("raw", "avg3"):
                    out.append(dict(method=method, reb=reb, N=N, k=k, score=score, min_hold=6, defer=True, block="core"))
    for mh in (0, 12):
        for reb in ("M", "Q"):
            for N in (10, 15, 20):
                out.append(dict(method=method, reb=reb, N=N, k=3, score="avg3", min_hold=mh, defer=True, block="minhold"))
    return out


def vname(v):
    s = f"{v['method']}|{v['reb']}|N{v['N']}|k{v['k']:g}|{v['score']}|hold{v['min_hold']}"
    if not v.get("defer", True):
        s += "|nodefer"
    for key in ("stress", "capital", "tax", "bench_fee"):
        if key in v and v[key] not in (False, None, CAPITAL, "today", 0.0):
            s += f"|{key}={v[key]}"
    return s


def passes(r):
    bars = dict(
        t=(r.get("t_haircut") is not None and r["t_haircut"] >= 2.0),
        hold=((r.get("median_hold_km_m") is not None and r["median_hold_km_m"] >= 9.0) or
              (r.get("median_hold_km_lower_bound_m") is not None and r["median_hold_km_lower_bound_m"] >= 9.0)),
        turnover=(r["turnover_pa"] <= 1.0),
        worst12=(r["worst_12m_excess"] is not None and r["worst_12m_excess"] >= -0.15),
    )
    return bars, all(bars.values())


def run(smoke=False):
    D = Data()
    results, monthly = [], []
    bench_info = {}

    def go(tier, v, kind, trials, bench_cache):
        key = (v.get("bench_fee", 0.0), v.get("tax", "today"), v.get("capital", CAPITAL))
        if key not in bench_cache:
            bench_cache[key] = benchmark(D, tier, fee=key[0], rules_name=key[1], cap0=key[2])
        b = bench_cache[key]
        r, m = simulate(D, tier, v, b)
        # pre-tax: the same rules with no tax at all (book and benchmark)
        vp = dict(v, tax="none")
        bkey = (v.get("bench_fee", 0.0), "none", v.get("capital", CAPITAL))
        if bkey not in bench_cache:
            bench_cache[bkey] = benchmark(D, tier, fee=bkey[0], rules_name="none", cap0=bkey[2])
        rp, _ = simulate(D, tier, vp, bench_cache[bkey])
        r["cagr_pre_tax"] = rp["cagr_after_tax"]
        r["bench_cagr_pre_tax"] = rp["bench_cagr_after_tax"]
        r["excess_cagr_pre_tax"] = rp["excess_cagr"]
        r["turnover_pre_tax_run"] = rp["turnover_pa"]
        r["t_haircut"] = round(haircut_t(r["t_nw"], r["n_months"], trials), 3) if r["t_nw"] is not None else None
        r["trials"] = trials
        bars, ok = passes(r)
        r["bars"] = bars
        r["pass_all"] = ok
        r.update(tier=tier, kind=kind, variant=vname(v), **{k_: v[k_] for k_ in ("method", "reb", "N", "k", "score", "min_hold")},
                 defer=v.get("defer", True), block=v.get("block", kind))
        m = m.assign(tier=tier, variant=r["variant"], kind=kind)
        monthly.append(m)
        results.append(r)
        return r

    for tier in TIERS:
        t0 = time.time()
        cache = {}
        b = benchmark(D, tier)
        cache[(0.0, "today", CAPITAL)] = b
        bench_info[tier] = dict(
            index=BENCH_INDEX[tier], months_by_source=b.attrs["sources"],
            cagr_pre_tax=round((b["pre"].iloc[-1] / CAPITAL) ** (365.25 / (D.entry[-1] - D.entry[0]).days) - 1, 4),
            cagr_after_tax=round((b["atlv"].iloc[-1] / CAPITAL) ** (365.25 / (D.entry[-1] - D.entry[0]).days) - 1, 4),
            ew_cagr_pre_tax=round((b["pre_ew"].iloc[-1] / CAPITAL) ** (365.25 / (D.entry[-1] - D.entry[0]).days) - 1, 4),
            avg_monthly_div_credit=round(float(np.mean([y[tier] for y in D.tier_div_yield[:-1]])), 5),
        )
        G = grid()
        if smoke:
            G = G[:1] + G[-1:]
        trials = len(G)
        for v in G:
            go(tier, v, "grid", trials, cache)
        grid_rows = [r for r in results if r["tier"] == tier and r["kind"] == "grid"]
        # best variant: the highest haircut t among variants that meet the three non-t bars; if none, highest t
        elig = [r for r in grid_rows if r["bars"]["hold"] and r["bars"]["turnover"] and r["bars"]["worst12"]]
        pool = elig or grid_rows
        best = max(pool, key=lambda r: (r["t_nw"] if r["t_nw"] is not None else -9))
        best["is_best"] = True
        # deflated Sharpe on the best variant
        srs = [np.mean(r["_x"]) / np.std(r["_x"], ddof=1) for r in grid_rows]
        if len(srs) > 2:
            dsr, sr, sr0 = deflated_sharpe(best["_x"], srs, trials)
            best["dsr"] = round(dsr, 4); best["sr_monthly"] = round(sr, 4); best["sr0_monthly"] = round(sr0, 4)
        bv = {k_: best[k_] for k_ in ("method", "reb", "N", "k", "score", "min_hold")}
        # comparisons: the best rule on the other score sets (not eligible to pass; haircut at trials + 4)
        for meth in ("slow_icw", "blend", "fast_select", "live"):
            go(tier, dict(bv, method=meth, defer=True, block="compare"), "compare", trials + 4, cache)
        # status quo: buy top 5, sell below rank 8, every month, no minimum hold, no deferral
        for meth in ("slow_select", "live"):
            go(tier, dict(method=meth, reb="M", N=5, k=1.6, score="raw", min_hold=0, defer=False, block="status_quo"),
               "status_quo", trials, cache)
        # diagnostics on the best variant (not eligible)
        if not smoke:
            for extra in (dict(defer=False), dict(stress=True), dict(capital=5_000_000.0),
                          dict(tax="historical"), dict(bench_fee=BENCH_FEE[tier])):
                go(tier, {**bv, "defer": True, "block": "diagnostic", **extra}, "diagnostic", trials, cache)
        print(f"{tier}: {len(results)} runs so far, {time.time() - t0:.0f}s; best {best['variant']} "
              f"t {best['t_nw']} haircut {best['t_haircut']} pass {best['pass_all']}", flush=True)

    return D, results, monthly, bench_info


def write(D, results, monthly, bench_info, smoke=False):
    suffix = "_smoke" if smoke else ""
    df = pd.DataFrame([{k: v for k, v in r.items() if k not in ("_x", "bars")} |
                       {f"bar_{b}": ok for b, ok in r["bars"].items()} for r in results])
    df.to_csv(LH / f"book_variants{suffix}.csv", index=False)
    pd.concat(monthly, ignore_index=True).to_parquet(LH / f"book_monthly{suffix}.parquet", index=False)
    per_tier = {}
    for tier in TIERS:
        g = [r for r in results if r["tier"] == tier and r["kind"] == "grid"]
        best = next(r for r in g if r.get("is_best"))
        ts = [r["t_nw"] for r in g if r["t_nw"] is not None]
        per_tier[tier] = dict(
            verdict="PASS" if any(r["pass_all"] for r in g) else "FAIL",
            variants_run=len(g), variants_passing=sum(r["pass_all"] for r in g),
            best={k: v for k, v in best.items() if k != "_x"},
            grid_median_t=round(float(np.median(ts)), 3) if ts else None,
            grid_max_t=round(float(max(ts)), 3) if ts else None,
            n_meeting_non_t_bars=sum(r["bars"]["hold"] and r["bars"]["turnover"] and r["bars"]["worst12"] for r in g),
            benchmark=bench_info[tier],
        )
    blob = dict(
        plan="0024 H3", written=pd.Timestamp.now().isoformat(timespec="seconds"),
        window=dict(first_anchor=D.anchors[0], last_anchor=D.anchors[-1],
                    first_entry=D.entry[0].date().isoformat(), last_entry=D.entry[-1].date().isoformat(),
                    anchors=len(D.anchors)),
        capital_inr=CAPITAL, nw_lag=NW_LAG, mixed_dividend_rows_skipped=D.div_mixed_skipped,
        tiers=per_tier,
        runs=[{k: v for k, v in r.items() if k != "_x"} for r in results],
    )
    (LH / f"book_results{suffix}.json").write_text(json.dumps(blob, indent=1, default=str))
    print(f"wrote data/lh/book_results{suffix}.json, book_variants{suffix}.csv, book_monthly{suffix}.parquet")
    for tier, p in per_tier.items():
        b = p["best"]
        print(f"{tier}: {p['verdict']} ({p['variants_passing']}/{p['variants_run']}); best {b['variant']} "
              f"excess {b['excess_cagr']} t {b['t_nw']} haircut {b['t_haircut']} hold {b['median_hold_km_m']} "
              f"turnover {b['turnover_pa']} worst12 {b['worst_12m_excess']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    D, results, monthly, bench_info = run(smoke=a.smoke)
    write(D, results, monthly, bench_info, smoke=a.smoke)


if __name__ == "__main__":
    main()
