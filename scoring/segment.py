"""
Alpha Signal v2 — Segment node: assign LARGE / MID / SMALL by market cap (plan 0015 D3).

Until this node, nothing wrote LARGE/MID/SMALL: stocks.cap_tier was loaded once from
v1's universe.csv (April 2026) and only SMALL<->MICRO was ever toggled. This node ranks
the universe by a FRESH market cap and applies config.TIERS' `rank_max` rules
(SEBI/AMFI: top 100 = LARGE, 101-250 = MID, the rest = SMALL). The MICRO carve-out
stays with tools/classify_micro_tier.py, which must run AFTER this node.

Market cap (Rs crore) = latest close (<= t, within PRICE_MAX_AGE_DAYS) x the latest
annual share count knowable at t (see market_caps: two sources, cross-checked; an
uncorroborated stock is not ranked and keeps its tier). stocks.market_cap_cr is NOT used:
it is a frozen April-2026 snapshot, in RUPEES despite its name, NULL for 726 stocks.

Hysteresis (config.TIER_HYSTERESIS = h): an incumbent keeps its tier while its rank stays
inside the tier's band widened by h x boundary on each side (LARGE <= 110, MID 91-275,
SMALL > 225 at h = 0.10); an entrant must clear the boundary by the same margin. Tier
sizes float a little around 100 / 150 instead of names flipping across the line every
month (churn measured with measure(); see plan 0015 Phase 6 notes).

A MICRO stock is treated as a SMALL incumbent: it keeps MICRO unless its rank lifts it
into MID/LARGE (classify_micro_tier only looks at SMALL/MICRO, so it then stays there).
A stock with no market cap (no recent close or share count), or an uncorroborated one,
keeps its tier; a stock with no tier yet (None) gets the strict rank tier.

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

PRICE_MAX_AGE_DAYS = 30     # a stock without a close in this window is not ranked
ANNUAL_LAG_DAYS = 75        # = pit.ANNUAL_LAG (annual filing lag)
CORROBORATE_X = 1.5         # the two share-count sources must agree within this factor


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


def _latest_knowable(sql, t_s):
    return read_sql(sql, params=[f"+{ANNUAL_LAG_DAYS} day", t_s]).drop_duplicates("sid")


def market_caps(t=None):
    """DataFrame[sid, mcap_cr, corroborated] as of t.

    mcap_cr = close x as-reported shares (fundamentals_screener "No. of Equity Shares",
    latest annual knowable at t) x every SPLIT/BONUS since that period end — or, for a
    stock with no screener share count, close x annual_balance_sheet.shares_outstanding
    (Tickertape, already restated to the CURRENT share basis). `corroborated` = both
    sources exist and agree within CORROBORATE_X. They disagree for ~8% of stocks
    (unit slips: KDDL 1,744 vs 1.25 cr shares; FISCHER 10x; a bonus missing from
    corporate_adjustments: LICI 2x), so an uncorroborated stock is neither ranked nor
    moved (assign keeps its tier)."""
    t = pd.Timestamp(t or date.today())
    t_s = t.date().isoformat()
    px = read_sql(
        "SELECT p.sid, p.date AS px_date, p.close FROM stock_prices p "
        "JOIN (SELECT sid, MAX(date) AS d FROM stock_prices "
        "      WHERE close > 0 AND date <= ? AND date >= ? GROUP BY sid) m "
        "  ON p.sid = m.sid AND p.date = m.d",
        params=[t_s, (t - timedelta(days=PRICE_MAX_AGE_DAYS)).date().isoformat()],
    ).drop_duplicates("sid")
    fs = _latest_knowable(
        "SELECT f.sid, f.period_end, f.value / 1e7 AS shares_fs FROM fundamentals_screener f "
        "JOIN (SELECT sid, MAX(period_end) AS e FROM fundamentals_screener "
        "      WHERE line_item = 'No. of Equity Shares' AND period_type = 'annual' AND value > 0 "
        "        AND date(period_end, ?) <= ? GROUP BY sid) m "
        "  ON f.sid = m.sid AND f.period_end = m.e "
        "WHERE f.line_item = 'No. of Equity Shares' AND f.period_type = 'annual'", t_s)
    bs = _latest_knowable(
        "SELECT b.sid, b.shares_outstanding AS shares_bs FROM annual_balance_sheet b "
        "JOIN (SELECT sid, MAX(end_date) AS e FROM annual_balance_sheet "
        "      WHERE shares_outstanding > 0 AND date(end_date, ?) <= ? GROUP BY sid) m "
        "  ON b.sid = m.sid AND b.end_date = m.e", t_s)
    ev = read_sql(
        "SELECT sid, ex_date, factor FROM corporate_adjustments "
        "WHERE (inds LIKE '%SPLIT%' OR inds LIKE '%BONUS%') AND factor > 0 AND ex_date <= ?",
        params=[t_s],
    )
    df = px.merge(fs, on="sid", how="left").merge(bs, on="sid", how="left")
    ev = ev.merge(df[["sid", "period_end", "px_date"]], on="sid")
    ev = ev[(ev["ex_date"] > ev["period_end"]) & (ev["ex_date"] <= ev["px_date"])]
    df["share_mult"] = df["sid"].map(1.0 / ev.groupby("sid")["factor"].prod()).fillna(1.0)
    mc_fs = df["close"] * df["shares_fs"] * df["share_mult"]
    mc_bs = df["close"] * df["shares_bs"]
    df["mcap_cr"] = mc_fs.fillna(mc_bs)
    ratio = mc_fs / mc_bs
    df["corroborated"] = ratio.between(1 / CORROBORATE_X, CORROBORATE_X)
    return df.loc[df["mcap_cr"] > 0, ["sid", "mcap_cr", "corroborated"]].reset_index(drop=True)


def assign(caps, current, h=None, tiers=None):
    """New tier per sid (Series). `caps` = DataFrame[sid, mcap_cr]; `current` =
    {sid: tier} (the universe; None = no tier yet). Pure — no DB."""
    h = config.TIER_HYSTERESIS if h is None else h
    tiers = tiers or config.TIERS
    bands = _rank_tiers(tiers)
    carve = {name: spec["carve_from"] for name, spec in tiers.items() if spec.get("carve_from")}
    caps = caps.set_index("sid")
    if "corroborated" in caps:          # an unconfirmed market cap neither ranks nor moves
        caps = caps[caps["corroborated"].astype(bool)]
    rank = caps["mcap_cr"].rank(ascending=False, method="first")

    out = {}
    for sid, cur in current.items():
        r = rank.get(sid)
        if r is None or pd.isna(r):
            out[sid] = cur                  # no (corroborated) market cap: keep
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
    print(f"Segment (h={config.TIER_HYSTERESIS}): {int(caps['corroborated'].sum())} of {len(stocks)} "
          f"ranked ({len(caps)} with a market cap); "
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
