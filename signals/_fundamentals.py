"""Shared input hygiene for statement-based factors (plan 0015 Phase 3, ADR 0052).

Applied INSIDE each factor's _compute_scores, so the live signal step and the PIT
reconstruction (pit.py) — which call the same function with
as-of-sliced frames — see identically cleaned inputs. Before this, the filters
lived only in each module's live `_load_data`, and the backtest measured a
slightly different factor (piotroski: 819 of 2,220 overlapping rows differed).
"""
import math

import pandas as pd

from config import SCREEN

FINANCIAL_SECTORS = set(SCREEN["financial_sectors"])


def prefer_consolidated(qi):
    """Consolidated rows where a sid has any, standalone otherwise. Idempotent."""
    if qi is None or qi.empty or "reporting" not in qi.columns:
        return qi
    has_consol = set(qi.loc[qi["reporting"] == "consolidated", "sid"])
    keep = (qi["sid"].isin(has_consol) & (qi["reporting"] == "consolidated")) | ~qi["sid"].isin(has_consol)
    return qi[keep]


def quarters(qi_g, skip=0, n=4):
    """The `n` quarterly rows ending `skip` rows before the latest (by end_date):
    skip=0 is the trailing year, skip=4 the year before. None when there are fewer
    than n + skip rows. Rows with a missing value still count as quarters."""
    if qi_g is None or len(qi_g) < n + skip:
        return None
    g = qi_g.sort_values("end_date")
    return g.iloc[len(g) - n - skip:len(g) - skip]


def ttm(qi_g, column, skip=0):
    """Trailing-twelve-month sum of `column` (see quarters); a missing quarter adds 0,
    as every factor has always summed it. None when there are too few quarters."""
    q = quarters(qi_g, skip)
    return None if q is None else float(q[column].sum())


def annual_items(fund, items):
    """{sid: frame indexed by period_end, one column per item} from annual Screener
    rows [sid, period_end, line_item, value] (as-of filtered by the caller), oldest →
    newest, keeping only the periods where EVERY item is present (the half-year rows
    carry balance-sheet items only). Empty dict when `fund` is None / empty."""
    if fund is None or fund.empty:
        return {}
    wide = (fund[fund["line_item"].isin(items)]
            .pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first")
            .reindex(columns=list(items)).dropna().sort_index())
    return {sid: g.droplevel("sid") for sid, g in wide.groupby(level="sid")}


SHARE_ITEMS = ("Equity Share Capital", "Reserves", "Face value", "No. of Equity Shares")
RUPEES_PER_CRORE = 1e7
SHARE_JUMP = 5.0          # a share count moving more than this in a year with no split / bonus is a bad row
SHARE_AGREE = 1.5         # two readings further apart than this do not agree
RESTATE_LAG_DAYS = 45     # the vendor restates its share count at the next monthly refetch after a split


def _factor(events, lo, hi):
    """Product of the split / bonus factors with lo < ex_date ≤ hi (1.0 when none)."""
    if events is None or lo >= hi:
        return 1.0
    return float(events.loc[(events["ex_date"] > lo) & (events["ex_date"] <= hi), "factor"].prod())


def market_caps(bs, fund, adjustments, close, as_of):
    """[sid, mcap_cr] as of `as_of`: the close × the share count on that close's basis
    (shares_and_book). THE market cap — live tiers, backtest tiers, the MICRO carve-out,
    fcf_yield and stocks.market_cap_cr (₹ crore) all read this. `close` = [sid, close_price]."""
    mc = shares_and_book(bs, fund, adjustments, as_of).merge(close, on="sid")
    mc["mcap_cr"] = mc["shares"] * mc["close_price"] / RUPEES_PER_CRORE
    return mc.loc[mc["mcap_cr"] > 0, ["sid", "mcap_cr"]].reset_index(drop=True)


def shares_and_book(bs, fund, adjustments, as_of):
    """[sid, shares, book_equity_cr] as of `as_of` for every sid with a balance sheet:
    a share count on the SAME basis as that day's close, and owners' equity.
    `bs` = Tickertape annual balance sheets, `fund` = annual Screener rows for
    SHARE_ITEMS (both as-of filtered by the caller), `adjustments` = corporate_adjustments
    [sid, ex_date, factor, inds] (unfiltered: a later split is a unit, not information).

    shares — the vendor restates shares_outstanding to the basis of its last fetch, so
      T = shares_outstanding × the split / bonus factors still to come after `as_of`
    is the count on the as_of basis (dividing the restated count by an unadjusted old
    close understated book-to-price by the split factor on 5.6% of panel rows).
    T is checked against the Screener statement, which is NOT restated:
      S = 'No. of Equity Shares' (else Equity Share Capital / Face value)
          ÷ the split / bonus factors between the statement date and as_of
    and S replaces T when they disagree by more than SHARE_AGREE× and either a split /
    bonus went ex within RESTATE_LAG_DAYS before as_of (the vendor has not restated
    yet: TAA read 5× too cheap) or T jumped more than SHARE_JUMP× on the year with no
    corporate action (a bad row: KDDL 1.25 Cr → 1,744 Cr shares). Otherwise T stands —
    it also reflects actions our event table missed.

    book_equity_cr — Screener Equity Share Capital + Reserves when its latest statement
    is the balance sheet's period (owners' equity: Tickertape's total_equity includes
    minority interest, 23% of LARGE off by more than 5%), else total_equity."""
    cols = ["sid", "shares", "book_equity_cr"]
    if bs is None or bs.empty:
        return pd.DataFrame(columns=cols)
    as_of = str(as_of)
    recent = (pd.Timestamp(as_of) - pd.Timedelta(days=RESTATE_LAG_DAYS)).date().isoformat()
    events = {}
    if adjustments is not None and not adjustments.empty:
        ev = adjustments[adjustments["inds"].str.contains("SPLIT|BONUS", na=False)]
        events = {sid: g for sid, g in ev.groupby("sid")}
    stmt = {}
    if fund is not None and not fund.empty:
        wide = (fund[fund["line_item"].isin(SHARE_ITEMS)]
                .pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first")
                .reindex(columns=list(SHARE_ITEMS)).dropna(subset=["Equity Share Capital", "Reserves"]).reset_index()
                .sort_values(["sid", "period_end"]).groupby("sid").tail(1))
        stmt = wide.set_index("sid").to_dict("index")

    rows = []
    for sid, g in bs.sort_values(["sid", "end_date"]).groupby("sid"):
        y0, ev, st = g.iloc[-1], events.get(sid), stmt.get(sid)
        t_raw = y0["shares_outstanding"] * RUPEES_PER_CRORE
        shares = t_raw * _factor(ev, as_of, "9999") if t_raw > 0 else float("nan")
        equity = y0["total_equity"]
        if st is not None:
            prev = g.iloc[-2]["shares_outstanding"] * RUPEES_PER_CRORE if len(g) > 1 else float("nan")
            s_raw = st["No. of Equity Shares"]
            by_face = st["Equity Share Capital"] * RUPEES_PER_CRORE / st["Face value"] if st["Face value"] > 0 else float("nan")
            # the statement's two counts disagree (a stale face value, a bad row): the one nearer last year's
            if by_face > 0 and (not s_raw > 0 or (prev > 0 and abs(math.log(by_face / prev)) < abs(math.log(s_raw / prev)))):
                s_raw = by_face
            s = s_raw / _factor(ev, st["period_end"], as_of) if s_raw > 0 else float("nan")
            if s > 0 and not (shares > 0 and 1 / SHARE_AGREE <= shares / s <= SHARE_AGREE):
                jumped = prev > 0 and not (1 / SHARE_JUMP <= t_raw / prev <= SHARE_JUMP)
                if not shares > 0 or jumped or _factor(ev, recent, as_of) != 1.0:
                    shares = s
            if st["period_end"] == y0["end_date"]:
                equity = st["Equity Share Capital"] + st["Reserves"]
        rows.append((sid, shares, equity))
    return pd.DataFrame(rows, columns=cols)


def without_financials(stocks):
    """Drop Financials (structurally N/A for bank balance sheets; ADR 0048)."""
    if "sector" not in stocks.columns:
        return stocks
    return stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)]
