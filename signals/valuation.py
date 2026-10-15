"""
Alpha Signal v2 — valuation football field (plan 0026 phase 3).

For each stock, a per-share price RANGE (low / mid / high) from independent methods,
so a human sees where the price sits against several yardsticks. Structured numbers
only: `basis` names the inputs and their dates, it is never narrative. Not a factor,
not a score, not ranked, nothing here moves a pick.

  pe_band / pb_band / ev_ebitda_band  the stock's own 10th / 50th / 90th percentile multiple
                                      over its history in daily_snapshots_pit, x its current metric
  peer_pe / peer_ev_ebitda            25th / 50th / 75th percentile of the same-industry, same-tier
                                      current multiples, x its metric
  dcf                                 10-year owner-earnings DCF, bear / base / bull growth
  analyst                             low / median / high price target (analyst_consensus)
  range_52w                           low / high of the split-adjusted close over 252 sessions
  reverse_dcf                         NOT a bar: the starting growth the price implies (low/mid/high NULL);
                                      the number is `implied_growth_10y`

Method choices (see also the report that came with this file)
  EPS        TTM sum of quarterly_income.eps, the same sum earnings_yield uses, so the P/E band and
             the EPS it multiplies are on one basis (and one split basis: ratios are split-invariant).
  book/share latest book_to_price x its close, from the newest daily_snapshots_pit row: the same
             hygienic share count the factor uses (signals/_fundamentals.shares_and_book).
  EBITDA     quarterly_income.ebitda (operating_profit is empty in the table).
  EV         market cap + Borrowings - Cash & Bank, latest annual statement 150 days old at each date.
  DCF        owner earnings = CFO + min(Cash from Investing, 0), 3-year average, already after
             interest, so no net-debt bridge; falls back to net profit when that is <= 0.

Reads: stocks, stock_prices, corporate_adjustments, daily_snapshots_pit, quarterly_income,
       fundamentals_screener, analyst_consensus
Writes (write() only): valuation_ranges
"""
import argparse
import sqlite3

import numpy as np
import pandas as pd

from config import DB_PATH
from signals._fundamentals import FINANCIAL_SECTORS, prefer_consolidated

PARAMS = {
    "band_pcts": (10, 50, 90),       # own-history band
    "peer_pcts": (25, 50, 75),       # peer band
    "min_hist": 40,                  # own-history observations needed for a P/E or P/B band
    "min_quarters": 8,               # quarters of EV/EBITDA history needed
    "min_peers": 5,                  # same-tier peers needed, else the whole industry
    "max_multiple": 500.0,           # P/E above this is not a multiple, it is a rounding error in EPS
    "max_ev_multiple": 200.0,
    "max_price_mult": 20.0,          # a method whose mid is above this x price is dropped
    "quarter_lag_days": 45,          # a quarter is public this long after its end (history / as_of runs)
    "annual_lag_days": 150,
    "dcf_years": 10,
    "fade_to": 0.06,                 # growth at year 10
    "terminal_growth": 0.05,
    "coe": {"bear": 0.15, "base": 0.14, "bull": 0.13},
    "growth_clip": (-0.05, 0.35),
    "sessions_52w": 252,
}
METHODS = ("pe_band", "pb_band", "ev_ebitda_band", "peer_pe", "peer_ev_ebitda",
           "dcf", "reverse_dcf", "analyst", "range_52w")
COLUMNS = ["sid", "as_of", "method", "low", "mid", "high", "basis", "price", "implied_growth_10y"]
CRORE = 1e7


# ── pure maths (unit-tested on synthetic inputs) ─────────────────────────────

def percentiles(values, pcts, min_n=1):
    """(p_lo, p_mid, p_hi) of the finite values, or None when fewer than min_n."""
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) < max(min_n, 1):
        return None
    return tuple(float(x) for x in np.percentile(v, pcts))


def fade_path(g0, years=None, fade_to=None):
    """Growth for years 1..N: g0 in year 1, linearly to `fade_to` in year N."""
    years = years or PARAMS["dcf_years"]
    fade_to = PARAMS["fade_to"] if fade_to is None else fade_to
    return [g0 + (fade_to - g0) * t / (years - 1) for t in range(years)]


def dcf_value(oe0, shares, g0, coe):
    """Per-share value of owner earnings `oe0` (Rs; last year's), growing along fade_path(g0)
    for 10 years, then at the terminal growth, discounted at `coe`. None when oe0 or shares <= 0."""
    if not (oe0 > 0 and shares > 0) or coe <= PARAMS["terminal_growth"]:
        return None
    oe, pv = oe0, 0.0
    for t, g in enumerate(fade_path(g0), start=1):
        oe *= 1 + g
        pv += oe / (1 + coe) ** t
    tv = oe * (1 + PARAMS["terminal_growth"]) / (coe - PARAMS["terminal_growth"])
    pv += tv / (1 + coe) ** PARAMS["dcf_years"]
    return pv / shares


def implied_growth(price, oe0, shares, coe, lo=-0.30, hi=0.80):
    """Starting growth g0 at which the DCF equals `price` (bisection; the value rises with g0).
    None when the price is outside what lo..hi can reach."""
    if not (price > 0 and oe0 > 0 and shares > 0):
        return None
    f_lo, f_hi = dcf_value(oe0, shares, lo, coe), dcf_value(oe0, shares, hi, coe)
    if f_lo is None or not (f_lo <= price <= f_hi):
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        if dcf_value(oe0, shares, mid, coe) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def ev_to_price(multiple, ebitda, net_debt, shares):
    """Per-share equity value implied by an EV/EBITDA multiple (Rs; ebitda, net_debt in Rs)."""
    return (multiple * ebitda - net_debt) / shares


def cagr3(first, last):
    """3-year CAGR, None unless both ends are positive."""
    if first is None or last is None or not (first > 0 and last > 0):
        return None
    return (last / first) ** (1 / 3) - 1


def _clip_growth(g):
    lo, hi = PARAMS["growth_clip"]
    return min(max(g, lo), hi)


def _row(sid, as_of, method, lo, mid, hi, basis, price, implied=np.nan):
    """One field row. Sorts low <= mid <= high, floors low at 0, and drops the method
    (NaN range, basis 'out of range: ...') when mid <= 0 or mid > 20x price."""
    vals = [lo, mid, hi]
    if all(v is not None and np.isfinite(v) for v in vals):
        lo, mid, hi = sorted(float(v) for v in vals)
        if mid <= 0 or mid > PARAMS["max_price_mult"] * price:
            basis = f"out of range: mid {mid:.4g} vs price {price:.4g}; was {basis}"
            lo = mid = hi = np.nan
        else:
            lo = max(lo, 0.0)
    else:
        lo = mid = hi = np.nan
    return {"sid": sid, "as_of": as_of, "method": method, "low": lo, "mid": mid, "high": hi,
            "basis": basis, "price": price, "implied_growth_10y": implied}


def _na(sid, as_of, method, why, price):
    return _row(sid, as_of, method, np.nan, np.nan, np.nan, why, price)


# ── loading ──────────────────────────────────────────────────────────────────

def _read(query, params=()):
    """Read-only query: this module never writes except through write()."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return pd.read_sql_query(query, conn, params=params)
    finally:
        conn.close()


def _in(values):
    return "(" + ",".join("'" + str(v).replace("'", "''") + "'" for v in values) + ")"


ANNUAL_ITEMS = ("Sales", "Net profit", "Cash from Operating Activity", "Cash from Investing Activity",
                "Borrowings", "Cash & Bank")


def _annual(sids, as_of_str):
    """{sid: frame indexed by period_end (ISO), cols = ANNUAL_ITEMS} of annual Screener rows <= as_of."""
    f = _read("SELECT sid, period_end, line_item, value FROM fundamentals_screener "
              f"WHERE period_type='annual' AND sid IN {_in(sids)} AND period_end <= ? "
              f"AND line_item IN {_in(ANNUAL_ITEMS)}", (as_of_str,))
    if f.empty:
        return {}
    wide = (f.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first")
            .reindex(columns=list(ANNUAL_ITEMS)).sort_index())
    return {sid: g.droplevel("sid") for sid, g in wide.groupby(level="sid")}


def _quarters(sids, cutoff):
    """quarterly_income rows (consolidated preferred) with end_date <= cutoff."""
    q = _read("SELECT sid, end_date, reporting, eps, ebitda FROM quarterly_income "
              f"WHERE sid IN {_in(sids)} AND end_date <= ? ORDER BY sid, end_date", (cutoff,))
    return prefer_consolidated(q)


def _ttm(qg, col):
    """(sum of the latest 4 quarters of col, latest end_date) or (None, None)."""
    g = qg.dropna(subset=[col]).sort_values("end_date")
    if len(g) < 4:
        return None, None
    last4 = g.tail(4)
    return float(last4[col].sum()), last4["end_date"].iloc[-1]


def _net_debt_cr(ann):
    """(net debt Rs crore, period_end) from the latest annual row that has Cash & Bank, else (None, None).
    A missing Borrowings row counts as no debt."""
    if ann is None or ann.empty:
        return None, None
    a = ann.dropna(subset=["Cash & Bank"])
    if a.empty:
        return None, None
    r = a.iloc[-1]
    debt = 0.0 if pd.isna(r["Borrowings"]) else float(r["Borrowings"])
    return debt - float(r["Cash & Bank"]), a.index[-1]


def _owner_earnings_cr(ann):
    """(Rs crore, label) 3-year average of CFO + min(CFI, 0); net profit in years without CFO/CFI,
    and net profit altogether when the average is <= 0."""
    if ann is None or ann.empty:
        return None, None
    a = ann.dropna(subset=["Net profit"]).tail(3)
    if a.empty:
        return None, None
    cfo, cfi, npf = a["Cash from Operating Activity"], a["Cash from Investing Activity"], a["Net profit"]
    oe = (cfo + cfi.fillna(0).clip(upper=0)).where(cfo.notna(), npf)
    span = f"FY {a.index[0][:4]}-{a.index[-1][:4]}"
    if oe.mean() > 0:
        return float(oe.mean()), f"CFO+min(CFI,0) avg {span}"
    if npf.mean() > 0:
        return float(npf.mean()), f"net profit avg {span} (owner earnings <= 0)"
    return None, None


def _sales_cagr(ann):
    if ann is None or ann.empty:
        return None
    s = ann["Sales"].dropna()
    return cagr3(s.iloc[-4], s.iloc[-1]) if len(s) >= 4 else None


# ── per-method builders (small, take plain inputs) ───────────────────────────

def _own_band(sid, as_of, method, mult, metric_ps, price, label, metric_basis):
    band = percentiles(mult, PARAMS["band_pcts"], PARAMS["min_hist"])
    if band is None:
        return _na(sid, as_of, method, f"insufficient history (<{PARAMS['min_hist']} {label} obs)", price)
    lo, md, hi = (m * metric_ps for m in band)
    return _row(sid, as_of, method, lo, md, hi,
                f"{label} p10/50/90 {band[0]:.2f}/{band[1]:.2f}/{band[2]:.2f} over {len(mult)} snapshots x {metric_basis}", price)


def _ev_history(pit, shares, qg, ann, adj_close):
    """EV/EBITDA at each PIT date: (mcap + net debt) / TTM EBITDA with the 45- / 150-day lags.
    Returns (multiples array, n distinct TTM windows)."""
    if qg is None or ann is None or ann.empty or pit.empty:
        return np.array([]), 0
    q = qg.dropna(subset=["ebitda"]).sort_values("end_date").copy()
    q["ttm"] = q["ebitda"].rolling(4).sum()
    q = q.dropna(subset=["ttm"])
    q = q[q["ttm"] > 0]
    q["avail"] = pd.to_datetime(q["end_date"]) + pd.Timedelta(days=PARAMS["quarter_lag_days"])
    a = ann.dropna(subset=["Cash & Bank"]).copy()
    a["nd"] = a["Borrowings"].fillna(0.0) - a["Cash & Bank"]
    a["avail"] = pd.to_datetime(a.index) + pd.Timedelta(days=PARAMS["annual_lag_days"])
    if q.empty or a.empty:
        return np.array([]), 0
    p = pd.DataFrame({"date": pd.to_datetime(pit["snapshot_date"].values), "adj": adj_close}).dropna().sort_values("date")
    m = pd.merge_asof(p, q[["avail", "ttm", "end_date"]].sort_values("avail"), left_on="date", right_on="avail")
    m = pd.merge_asof(m.sort_values("date"), a[["avail", "nd"]].sort_values("avail"), left_on="date", right_on="avail",
                      suffixes=("", "_a")).dropna(subset=["ttm", "nd"])
    ev = m["adj"] * shares / CRORE + m["nd"]
    mult = (ev / m["ttm"]).to_numpy()
    ok = (mult > 0) & (mult < PARAMS["max_ev_multiple"])
    return mult[ok], int(m.loc[ok, "end_date"].nunique())


def _dcf_rows(sid, as_of, price, shares, oe_cr, oe_label, g_ind, g_own, g_top):
    """(dcf row, reverse_dcf row)."""
    gs = sorted(_clip_growth(g) for g in (g_ind, g_own, g_top))
    coe = PARAMS["coe"]
    oe = oe_cr * CRORE
    vals = [dcf_value(oe, shares, g, coe[k]) for g, k in zip(gs, ("bear", "base", "bull"))]
    basis = (f"OE {oe_cr:.0f} cr ({oe_label}); growth bear/base/bull {gs[0]:.1%}/{gs[1]:.1%}/{gs[2]:.1%} "
             f"(industry med / own / industry p75 3y sales CAGR, clipped) fading to {PARAMS['fade_to']:.0%} by yr 10; "
             f"coe {coe['bear']:.0%}/{coe['base']:.0%}/{coe['bull']:.0%}; terminal {PARAMS['terminal_growth']:.0%}; shares {shares / CRORE:.2f} cr")
    ig = implied_growth(price, oe, shares, coe["base"])
    rev = _row(sid, as_of, "reverse_dcf", np.nan, np.nan, np.nan,
               (f"growth fading to {PARAMS['fade_to']:.0%} by yr 10 that equates base DCF to price {price:.2f}; "
                f"OE {oe_cr:.0f} cr ({oe_label}); coe {coe['base']:.0%}") if ig is not None
               else f"price {price:.2f} outside the -30%..80% growth range", price, ig if ig is not None else np.nan)
    return _row(sid, as_of, "dcf", vals[0], vals[1], vals[2], basis, price), rev


# ── compute ──────────────────────────────────────────────────────────────────

def compute(sids=None, as_of=None):
    """Long frame COLUMNS: one row per (sid, method). `sids` None = every stock with a price.
    `as_of` (ISO date) None = latest data; given = only data public by then (analyst: live only)."""
    from signals._prices import apply_adjustments

    stocks = _read("SELECT sid, ticker, sector, industry, cap_tier, market_cap_cr FROM stocks")
    stocks = stocks.set_index("sid", drop=False)
    live = as_of is None
    if live:
        as_of = _read("SELECT MAX(date) d FROM stock_prices")["d"].iloc[0]
    as_of = str(as_of)
    targets = list(stocks.index) if sids is None else [s for s in sids if s in stocks.index]
    if not targets:
        raise ValueError(f"valuation: none of {sids} is in stocks")
    industries = set(stocks.loc[targets, "industry"].dropna())
    peer_sids = list(stocks.index[stocks["industry"].isin(industries)].union(pd.Index(targets)))

    qlag = 0 if live else PARAMS["quarter_lag_days"]
    q_cut = (pd.Timestamp(as_of) - pd.Timedelta(days=qlag)).date().isoformat()
    a_cut = (pd.Timestamp(as_of) - pd.Timedelta(days=0 if live else PARAMS["annual_lag_days"])).date().isoformat()
    annual = _annual(peer_sids, a_cut)
    quarters = _quarters(peer_sids, q_cut)
    qby = {s: g for s, g in quarters.groupby("sid")}

    adjustments = _read(f"SELECT sid, ex_date, factor FROM corporate_adjustments WHERE sid IN {_in(targets)}")
    start = "2019-11-01"     # the first PIT snapshot: the EV/EBITDA history prices every snapshot date
    px = _read(f"SELECT sid, date, close FROM stock_prices WHERE sid IN {_in(targets)} AND close > 0 "
               "AND date >= ? AND date <= ? ORDER BY sid, date", (start, as_of))
    px = apply_adjustments(px, adjustments, as_of)
    pit_all = _read("SELECT sid, snapshot_date, close_price, earnings_yield, book_to_price FROM daily_snapshots_pit "
                    f"WHERE sid IN {_in(peer_sids)} AND snapshot_date <= ? ORDER BY sid, snapshot_date", (as_of,))
    pit_by = {s: g for s, g in pit_all.groupby("sid")}
    last_pit = pit_all["snapshot_date"].max()
    ac = _read(f"SELECT sid, price_target, price_target_median, price_target_high, price_target_low, fetched_at "
               f"FROM analyst_consensus WHERE sid IN {_in(targets)}").set_index("sid") if live else pd.DataFrame()

    # peer universe: current P/E and EV/EBITDA per stock
    peer_rows = []
    for s in peer_sids:
        st = stocks.loc[s]
        if st["sector"] in FINANCIAL_SECTORS:
            continue
        pe = ev = np.nan
        pg = pit_by.get(s)
        if pg is not None and pg["snapshot_date"].iloc[-1] == last_pit:
            e = pg["earnings_yield"].iloc[-1]
            if e is not None and e > 0 and 1 / e < PARAMS["max_multiple"]:
                pe = 1 / e
        eb = _ttm(qby[s], "ebitda")[0] if s in qby else None
        nd = _net_debt_cr(annual.get(s))[0]
        if eb and eb > 0 and nd is not None and st["market_cap_cr"] and st["market_cap_cr"] > 0:
            m = (st["market_cap_cr"] + nd) / eb
            if 0 < m < PARAMS["max_ev_multiple"]:
                ev = m
        peer_rows.append((s, st["industry"], st["cap_tier"], pe, ev, _sales_cagr(annual.get(s))))
    peers = pd.DataFrame(peer_rows, columns=["sid", "industry", "cap_tier", "pe", "ev", "g3"])

    out = []
    pxby = {s: g for s, g in px.groupby("sid")}
    for sid in targets:
        st, g = stocks.loc[sid], pxby.get(sid)
        if g is None or g.empty:
            continue
        price = float(g["close"].iloc[-1])
        px_date = g["date"].iloc[-1]
        shares = st["market_cap_cr"] * CRORE / price if st["market_cap_cr"] and st["market_cap_cr"] > 0 else np.nan
        is_fin = st["sector"] in FINANCIAL_SECTORS
        qg = qby.get(sid)
        ann = annual.get(sid)
        pit = pit_by.get(sid, pd.DataFrame(columns=["snapshot_date", "close_price", "earnings_yield", "book_to_price"]))
        eps, eps_end = _ttm(qg, "eps") if qg is not None else (None, None)
        ebitda, eb_end = _ttm(qg, "ebitda") if qg is not None else (None, None)
        nd, nd_end = _net_debt_cr(ann)
        R = lambda *a: out.append(_row(sid, as_of, *a, price))     # noqa: E731
        N = lambda m, why: out.append(_na(sid, as_of, m, why, price))  # noqa: E731

        # pe_band
        ey = pit["earnings_yield"].dropna()
        pe_hist = (1 / ey[ey > 0]).to_numpy()
        pe_hist = pe_hist[pe_hist < PARAMS["max_multiple"]]
        if eps is None or eps <= 0:
            N("pe_band", "n/a: TTM EPS missing or <= 0")
        else:
            out.append(_own_band(sid, as_of, "pe_band", pe_hist, eps, price, "P/E",
                                 f"TTM EPS {eps:.2f} (4q to {eps_end})"))

        # pb_band
        pb = pit.dropna(subset=["book_to_price", "close_price"])
        btp = pb[pb["book_to_price"] > 0]
        if btp.empty:
            N("pb_band", "n/a: no book_to_price")
        else:
            bvps = float(btp["book_to_price"].iloc[-1] * btp["close_price"].iloc[-1])
            out.append({**_own_band(sid, as_of, "pb_band", (1 / btp["book_to_price"]).to_numpy(), bvps, price, "P/B",
                                    f"BVPS {bvps:.2f} (book_to_price x close, {btp['snapshot_date'].iloc[-1]})"), "price": price})

        # ev_ebitda_band + peer_ev_ebitda
        if is_fin:
            N("ev_ebitda_band", "n/a for financials")
            N("peer_ev_ebitda", "n/a for financials")
        else:
            if not (ebitda and ebitda > 0) or nd is None or not shares > 0:
                N("ev_ebitda_band", "n/a: TTM EBITDA <= 0 or no balance sheet")
                N("peer_ev_ebitda", "n/a: TTM EBITDA <= 0 or no balance sheet")
            else:
                adj = _adj_at(g, pit)
                mult, nq = _ev_history(pit, shares, qg, ann, adj)
                if nq < PARAMS["min_quarters"] or len(mult) < PARAMS["min_hist"]:
                    N("ev_ebitda_band", "insufficient history")
                else:
                    band = percentiles(mult, PARAMS["band_pcts"])
                    vals = [ev_to_price(m, ebitda * CRORE, nd * CRORE, shares) for m in band]
                    R("ev_ebitda_band", *vals,
                      f"EV/EBITDA p10/50/90 {band[0]:.1f}/{band[1]:.1f}/{band[2]:.1f} over {len(mult)} snapshots/{nq}q x TTM EBITDA "
                      f"{ebitda:.0f} cr (4q to {eb_end}), net debt {nd:.0f} cr (FY {nd_end})")
                pr, scope = _peer_set(peers, sid, st, "ev")
                if len(pr) < 3:
                    N("peer_ev_ebitda", f"insufficient peers ({len(pr)})")
                else:
                    band = percentiles(pr["ev"], PARAMS["peer_pcts"])
                    R("peer_ev_ebitda", *[ev_to_price(m, ebitda * CRORE, nd * CRORE, shares) for m in band],
                      f"peer EV/EBITDA p25/50/75 {band[0]:.1f}/{band[1]:.1f}/{band[2]:.1f} n={len(pr)} {scope} x TTM EBITDA {ebitda:.0f} cr, net debt {nd:.0f} cr")

        # peer_pe
        if eps is None or eps <= 0:
            N("peer_pe", "n/a: TTM EPS missing or <= 0")
        elif is_fin and st["industry"] is None:
            N("peer_pe", "n/a: no industry")
        else:
            pr, scope = _peer_set(peers, sid, st, "pe") if not is_fin else _peer_set_fin(pit_by, stocks, sid, st, last_pit)
            if len(pr) < 3:
                N("peer_pe", f"insufficient peers ({len(pr)})")
            else:
                band = percentiles(pr["pe"], PARAMS["peer_pcts"])
                R("peer_pe", *[m * eps for m in band],
                  f"peer P/E p25/50/75 {band[0]:.1f}/{band[1]:.1f}/{band[2]:.1f} n={len(pr)} {scope} x TTM EPS {eps:.2f}")

        # dcf + reverse_dcf
        oe, oe_label = _owner_earnings_cr(ann)
        g_own = _sales_cagr(ann)
        pg = peers[(peers["industry"] == st["industry"]) & peers["g3"].notna()]
        if is_fin:
            N("dcf", "n/a for financials")
            N("reverse_dcf", "n/a for financials")
        elif oe is None or g_own is None or len(pg) < 3 or not shares > 0:
            N("dcf", "n/a: no positive owner earnings, sales history or industry growth")
            N("reverse_dcf", "n/a: no positive owner earnings")
        else:
            gi = float(np.median(pg["g3"]))
            gt = float(np.percentile(pg["g3"], 75))
            d, r = _dcf_rows(sid, as_of, price, shares, oe, oe_label, gi, g_own, gt)
            d["basis"] += f"; sales CAGR own {g_own:.1%}"
            out += [d, r]

        # analyst
        a = ac.loc[sid] if (live and sid in ac.index) else None
        if a is None:
            N("analyst", "n/a: no analyst targets" if live else "n/a: live only")
        else:
            mid = a["price_target_median"] if pd.notna(a["price_target_median"]) else a["price_target"]
            if pd.isna(mid):
                N("analyst", "n/a: no analyst targets")
            else:
                lo = a["price_target_low"] if pd.notna(a["price_target_low"]) else mid
                hi = a["price_target_high"] if pd.notna(a["price_target_high"]) else mid
                R("analyst", lo, mid, hi, f"analyst price target low/median/high, fetched {str(a['fetched_at'])[:10]}")

        # 52-week range
        w = g.tail(PARAMS["sessions_52w"])
        if len(w) < 60:
            N("range_52w", "insufficient price history")
        else:
            R("range_52w", w["adj_close"].min(), float(w["adj_close"].median()), w["adj_close"].max(),
              f"split-adjusted close, {len(w)} sessions {w['date'].iloc[0]}..{px_date}; mid = median")
    if not out:
        raise RuntimeError("valuation.compute produced no rows")
    df = pd.DataFrame(out)[COLUMNS]
    df["implied_growth_10y"] = df.groupby("sid")["implied_growth_10y"].transform("max")
    return df


def _adj_at(g, pit):
    """Split-adjusted close (today's basis) at each PIT snapshot date: last session on or before it."""
    s = g.set_index(pd.to_datetime(g["date"]))["adj_close"].sort_index()
    return s.reindex(pd.to_datetime(pit["snapshot_date"].values), method="ffill").to_numpy()


def _peer_set(peers, sid, st, col):
    """(peer rows with a valid `col`, scope label): same industry + tier if >= min_peers, else industry."""
    ind = peers[(peers["industry"] == st["industry"]) & (peers["sid"] != sid) & peers[col].notna()]
    tier = ind[ind["cap_tier"] == st["cap_tier"]]
    if len(tier) >= PARAMS["min_peers"]:
        return tier, f"{st['industry']}/{st['cap_tier']}"
    return ind, f"{st['industry']} (all tiers, <{PARAMS['min_peers']} in {st['cap_tier']})"


def _peer_set_fin(pit_by, stocks, sid, st, last_pit):
    """Peer P/E for a financial: same method over the industry's financials (peers frame skips them)."""
    rows = []
    for s in stocks.index[(stocks["industry"] == st["industry"]) & (stocks.index != sid)]:
        pg = pit_by.get(s)
        if pg is None or pg["snapshot_date"].iloc[-1] != last_pit:
            continue
        e = pg["earnings_yield"].iloc[-1]
        if e is not None and e > 0 and 1 / e < PARAMS["max_multiple"]:
            rows.append((s, stocks.loc[s, "cap_tier"], 1 / e))
    d = pd.DataFrame(rows, columns=["sid", "cap_tier", "pe"])
    tier = d[d["cap_tier"] == st["cap_tier"]]
    if len(tier) >= PARAMS["min_peers"]:
        return tier, f"{st['industry']}/{st['cap_tier']}"
    return d, f"{st['industry']} (all tiers, <{PARAMS['min_peers']} in {st['cap_tier']})"


# ── CLI (print only; output/valuation.py writes, signals/ never imports db: invariant 1) ──────────────────────────────────────────────────────────────

def _format(df):
    lines = []
    for sid, g in df.groupby("sid", sort=False):
        ig = g["implied_growth_10y"].iloc[0]
        lines.append(f"\n{sid}  as_of {g['as_of'].iloc[0]}  price {g['price'].iloc[0]:.2f}  "
                     f"implied 10y growth {'n/a' if pd.isna(ig) else f'{ig:.1%}'}")
        for _, r in g.iterrows():
            rng = ("          -            -            -" if pd.isna(r["mid"])
                   else f"{r['low']:>11,.1f} {r['mid']:>12,.1f} {r['high']:>12,.1f}")
            lines.append(f"  {r['method']:<15}{rng}  {r['basis']}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Valuation football field")
    ap.add_argument("--sids", help="comma list of sids or tickers; default = every stock")
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--dry-run", action="store_true", help="kept for compatibility: this module only prints")
    args = ap.parse_args()
    sids = None
    if args.sids:
        st = _read("SELECT sid, ticker FROM stocks")
        key = {**dict(zip(st["sid"], st["sid"])), **dict(zip(st["ticker"], st["sid"]))}
        want = [x.strip() for x in args.sids.split(",") if x.strip()]
        missing = [w for w in want if w not in key]
        if missing:
            raise SystemExit(f"unknown sid/ticker: {missing}")
        sids = [key[w] for w in want]
    df = compute(sids, args.as_of)
    print(_format(df))
    if not args.dry_run:
        print("\nsignals.valuation only prints; write with `python -m output.valuation`")


if __name__ == "__main__":
    main()
