"""
Alpha Signal v2 — Segment node: assign LARGE / MID / SMALL by market cap (plan 0015 D3).

Until this node, nothing wrote LARGE/MID/SMALL: stocks.cap_tier was loaded once from
v1's universe.csv (April 2026) and only SMALL<->MICRO was ever toggled. This node ranks
the universe by a FRESH market cap and applies config.TIERS' `rank_max` rules
(SEBI/AMFI: top 100 = LARGE, 101-250 = MID, the rest = SMALL). The MICRO carve-out
stays with tools/classify_micro_tier.py, which must run AFTER this node.

Market cap (Rs crore) and the MICRO carve-out inputs come from pit.tier_inputs — the
function the backtest's point-in-time tiers (pit.tiers_at) use — so a stock is tiered
live exactly as the evidence assumed. stocks.market_cap_cr is written from it, in crore,
by the daily MICRO step (tools/classify_micro_tier.py).

Hysteresis (config.TIER_HYSTERESIS = h): an incumbent keeps its tier while its rank stays
inside the tier's band widened by h x boundary on each side (LARGE <= 110, MID 91-275,
SMALL > 225 at h = 0.10); an entrant must clear the boundary by the same margin. Tier
sizes float a little around 100 / 150 instead of names flipping across the line every
month (churn measured with measure(); see plan 0015 Phase 6 notes).

A MICRO stock is treated as a SMALL incumbent: it keeps MICRO unless its rank lifts it
into MID/LARGE (classify_micro_tier only looks at SMALL/MICRO, so it then stays there).
A stock with no market cap (no recent close or share count) keeps its tier; a stock with
no tier yet (None) gets the strict rank tier.

Usage:
    python -m scoring.segment --dry-run          # transition matrix, no write
    python -m scoring.segment                    # apply to stocks.cap_tier
    python -m scoring.segment --measure          # monthly churn study (read-only)
"""

import argparse
import math
from datetime import date, timedelta

import pandas as pd

import config
from db import get_db, read_sql

# MICRO carve-out (ADR 0026): illiquid AND (small OR too little history to trust)
MICRO_ADTV_CR = 1.0         # 90-day average traded value below this (₹ crore / day)
MICRO_MCAP_CR = 500.0       # market cap below this (₹ crore)
MICRO_MIN_QUARTERS = 4      # fewer knowable quarterly statements than this


def _rank_tiers(tiers=None):
    """[(tier, lower_rank, upper_rank)] for the rank-assigned tiers, in order."""
    tiers = tiers or config.TIERS
    out, lower = [], 0
    for name, spec in tiers.items():
        if "rank_max" not in spec:
            continue
        upper = math.inf if spec["rank_max"] is None else spec["rank_max"]
        out.append((name, lower, upper))
        lower = upper
    return out


def inputs(t=None):
    """pit.tier_inputs as of t (default today) from the DB: [sid, mcap_cr, adtv_cr, quarters].
    Market cap = signals._fundamentals.market_caps (KDDL: both vendors carried 1,744 Cr
    shares for FY26, 1,400x the real count; the old two-source check passed it as
    "corroborated" and ranked a ₹5,000 Cr company in LARGE)."""
    import pit
    t = pd.Timestamp(t or date.today()).date()
    raw = pit.load_raw(set(pit.TIER_INPUTS) | {"adjustments"})
    px = read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 AND date <= ? AND date >= ?",
                  params=[t.isoformat(), (t - timedelta(days=100)).isoformat()])
    px = pit.apply_pit_adjustments(px.sort_values(["sid", "date"]), raw["adjustments"], t)
    return pit.tier_inputs(t, raw, px)


def market_caps(t=None):
    """DataFrame[sid, mcap_cr] as of t (see inputs)."""
    return inputs(t)[["sid", "mcap_cr"]]


def carve(tiers, ti):
    """Tiers with the MICRO carve-out applied: a stock of the carve-from tier (SMALL)
    whose 90-day traded value is under MICRO_ADTV_CR and whose market cap is under
    MICRO_MCAP_CR or whose knowable quarters are under MICRO_MIN_QUARTERS becomes MICRO.
    `tiers` = Series {sid: tier}; `ti` = tier inputs [sid, mcap_cr, adtv_cr, quarters]."""
    micro, carve_from = next((t, spec["carve_from"]) for t, spec in config.TIERS.items() if spec.get("carve_from"))
    x = ti.set_index("sid").reindex(tiers.index)
    thin = (x["adtv_cr"].fillna(0) < MICRO_ADTV_CR) & (
        (x["mcap_cr"] < MICRO_MCAP_CR) | (x["quarters"].fillna(0) < MICRO_MIN_QUARTERS))
    out = tiers.copy()
    out[(tiers == carve_from) & thin] = micro
    return out


def assign(caps, current, h=None, tiers=None):
    """New tier per sid (Series). `caps` = DataFrame[sid, mcap_cr]; `current` =
    {sid: tier} (the universe; None = no tier yet). Pure — no DB."""
    h = config.TIER_HYSTERESIS if h is None else h
    tiers = tiers or config.TIERS
    bands = _rank_tiers(tiers)
    carve = {name: spec["carve_from"] for name, spec in tiers.items() if spec.get("carve_from")}
    caps = caps.set_index("sid")
    rank = caps["mcap_cr"].rank(ascending=False, method="first")

    out = {}
    for sid, cur in current.items():
        r = rank.get(sid)
        if r is None or pd.isna(r):
            out[sid] = cur                  # no market cap: keep
            continue
        base = carve.get(cur, cur)                          # MICRO behaves as SMALL
        band = next(((lo, hi) for name, lo, hi in bands if name == base), None)
        if band and band[0] * (1 - h) < r <= band[1] * (1 + h):
            out[sid] = cur                                  # inside the widened band
        else:
            out[sid] = next(name for name, lo, hi in bands if r <= hi)
    return pd.Series(out, name="cap_tier", dtype=object)


def transitions(current, new):
    """{(from, to): n} for the sids whose tier changes."""
    moves = {}
    for sid, cur in current.items():
        nxt = new.get(sid, cur)
        if nxt != cur:
            moves[(cur, nxt)] = moves.get((cur, nxt), 0) + 1
    return moves


def compute(dry_run=False, as_of=None):
    """Assign rank tiers; write stocks.cap_tier for the sids that change. Returns the
    number of stocks ranked (raises when too few could be — never a silent no-op)."""
    stocks = read_sql("SELECT sid, cap_tier FROM stocks")
    caps = market_caps(as_of)
    if len(caps) < 0.5 * len(stocks):
        raise RuntimeError(f"segment: market cap for only {len(caps)} of {len(stocks)} stocks — "
                           "stale prices or missing share counts; refusing to re-tier")
    current = dict(zip(stocks["sid"], stocks["cap_tier"]))
    new = assign(caps, current)
    moves = transitions(current, new)
    sizes = new.value_counts().to_dict()
    print(f"Segment (h={config.TIER_HYSTERESIS}): {len(caps)} of {len(stocks)} ranked (with a market cap); "
          f"tier sizes {dict(sorted(sizes.items()))}")
    for (a, b), n in sorted(moves.items(), key=lambda kv: -kv[1]):
        print(f"  {a} -> {b}: {n}")
    if dry_run:
        print("Dry run — stocks.cap_tier not written.")
        return len(caps)
    changed = [(new[sid], sid) for sid in new.index if new[sid] != current.get(sid)]
    if changed:
        with get_db() as conn:
            conn.executemany("UPDATE stocks SET cap_tier = ? WHERE sid = ?", changed)
    print(f"Re-tiered {len(changed)} stocks")
    return len(caps)


def measure(start="2024-10-01", months=24, hs=(0.0, 0.05, 0.10, 0.20)):
    """Churn study: strict tiers at the first month start, then re-tier monthly; count
    rank-tier changes per month for each hysteresis h. Read-only."""
    dates = pd.date_range(start, periods=months, freq="MS")
    caps = {d: market_caps(d) for d in dates}
    rows = []
    for h in hs:
        cur = assign(caps[dates[0]], {s: None for s in caps[dates[0]]["sid"]}, h=0.0).to_dict()
        for d in dates[1:]:
            new = assign(caps[d], {**{s: None for s in caps[d]["sid"]}, **cur}, h=h)
            moved = sum(1 for s, c in cur.items() if c is not None and new.get(s, c) != c)
            sizes = new.value_counts()
            rows.append({"h": h, "date": d.date().isoformat(), "moves": moved,
                         **{t: int(sizes.get(t, 0)) for t, *_ in _rank_tiers()}})
            cur = new.to_dict()
    return pd.DataFrame(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--measure", action="store_true", help="monthly churn study (read-only)")
    args = parser.parse_args()
    if args.measure:
        m = measure()
        print(m.groupby("h")[["moves", "LARGE", "MID"]].agg(["mean", "min", "max"]).round(1))
    else:
        compute(dry_run=args.dry_run)
