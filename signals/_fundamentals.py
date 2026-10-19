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


STALE_BASIS_DAYS = 100    # consolidated whose latest quarter ends more than this before standalone's is stale


def prefer_consolidated(qi):
    """One reporting basis per sid: consolidated rows, unless the sid's latest consolidated
    quarter ends more than STALE_BASIS_DAYS before its latest standalone one — then the
    standalone rows. Without a consolidated row, standalone. A one-quarter lag (the
    consolidated print arriving after the standalone) keeps consolidated.

    Point in time by construction: the caller passes the as-of slice (pit.knowable_quarterly),
    so the choice at each date uses only the quarters knowable then — the live screener and
    the backtest call this one function. The vendor stopped refreshing consolidated for 24
    stocks (HDB, FCTL, UCBK …: consolidated to 2025-03, standalone to 2026-06) and every
    TTM factor read a year-old trailing year. Idempotent. Dates: `end_date`, else `period_end`."""
    if qi is None or qi.empty or "reporting" not in qi.columns:
        return qi
    is_c = qi["reporting"] == "consolidated"
    col = next((c for c in ("end_date", "period_end") if c in qi.columns), None)
    if col is None:
        use_c = pd.Series(True, index=pd.Index(qi.loc[is_c, "sid"].unique()))
    else:
        d = pd.to_datetime(qi[col], errors="coerce")
        c_last = d[is_c].groupby(qi.loc[is_c, "sid"]).max()
        s_last = d[~is_c].groupby(qi.loc[~is_c, "sid"]).max().reindex(c_last.index)
        use_c = ~((s_last - c_last).dt.days > STALE_BASIS_DAYS)
    return qi[qi["sid"].isin(use_c.index[use_c.astype(bool)]) == is_c]


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
FILED_SHARES_TOL = 1.3    # the filed count and ours further apart than this: the filing's count stands
FILED_MAX_AGE_DAYS = 200  # a shareholding filing for a quarter older than this is not the current count


def _factor(events, lo, hi):
    """Product of the split / bonus factors with lo < ex_date ≤ hi (1.0 when none)."""
    if events is None or lo >= hi:
        return 1.0
    return float(events.loc[(events["ex_date"] > lo) & (events["ex_date"] <= hi), "factor"].prod())


def _split_events(adjustments):
    """{sid: split / bonus rows of corporate_adjustments} (a demerger changes the price, not the count)."""
    if adjustments is None or adjustments.empty:
        return {}
    ev = adjustments[adjustments["inds"].str.contains("SPLIT|BONUS", na=False) & (adjustments["factor"] > 0)]
    return {sid: g for sid, g in ev.groupby("sid")}


def filed_shares(filings, adjustments, as_of, events=None):
    """{sid: shares} as of `as_of` from the latest BSE shareholding filing (`filings` =
    shareholding_categories [sid, end_date, filed_at, total_shares], unfiltered): the
    filing broadcast by as_of (filed_at; a revision counts from its own broadcast) for the
    newest quarter within FILED_MAX_AGE_DAYS, divided by the split / bonus factors that
    went ex after that quarter end and by as_of — the count on as_of's close basis.
    A Series; empty without filings."""
    if filings is None or filings.empty:
        return pd.Series(dtype=float)
    as_of = str(as_of)[:10]
    oldest = (pd.Timestamp(as_of) - pd.Timedelta(days=FILED_MAX_AGE_DAYS)).date().isoformat()
    f = filings[(filings["filed_at"].astype(str).str[:10] <= as_of) & (filings["end_date"] >= oldest)
                & (filings["end_date"] <= as_of) & (filings["total_shares"] > 0)]
    f = f.sort_values(["sid", "end_date", "filed_at"]).drop_duplicates("sid", keep="last")
    events = _split_events(adjustments) if events is None else events
    return pd.Series({r.sid: r.total_shares / _factor(events.get(r.sid), r.end_date, as_of)
                      for r in f.itertuples(index=False)}, dtype=float)


def market_caps(bs, fund, adjustments, close, as_of, filings=None):
    """[sid, mcap_cr, shares_source] as of `as_of`: the close × the share count on that
    close's basis (shares_and_book). THE market cap — live tiers, backtest tiers, the MICRO
    carve-out, fcf_yield, stocks.market_cap_cr (₹ crore) and the multibagger thesis all read
    this. `close` = [sid, close_price]; `filings` = shareholding_categories (filed_shares)."""
    mc = shares_and_book(bs, fund, adjustments, as_of, filings).merge(close, on="sid")
    mc["mcap_cr"] = mc["shares"] * mc["close_price"] / RUPEES_PER_CRORE
    return mc.loc[mc["mcap_cr"] > 0, ["sid", "mcap_cr", "shares_source"]].reset_index(drop=True)


def shares_and_book(bs, fund, adjustments, as_of, filings=None):
    """[sid, shares, book_equity_cr, shares_source] as of `as_of` for every sid with a
    balance sheet: a share count on the SAME basis as that day's close, and owners' equity.
    `bs` = Tickertape annual balance sheets, `fund` = annual Screener rows for
    SHARE_ITEMS (both as-of filtered by the caller), `adjustments` = corporate_adjustments
    [sid, ex_date, factor, inds] (unfiltered: a later split is a unit, not information),
    `filings` = shareholding_categories (unfiltered: filed_shares keeps what was broadcast
    by as_of).

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

    Last, the filed count F (filed_shares: the company's own quarterly filing) replaces
    the result when the two disagree by more than FILED_SHARES_TOL×, either way. The
    vendor count goes stale after allotments and mergers (IIAB 22× too few, AFI 10×) and
    divides the count by a demerger's price factor (VEDL 2.7× too many; TREI, IGLY), and
    the Screener statement is up to a year old. shares_source names the reading that
    stands: 'vendor', 'statement' or 'filing'.

    book_equity_cr — Screener Equity Share Capital + Reserves when its latest statement
    is the balance sheet's period (owners' equity: Tickertape's total_equity includes
    minority interest, 23% of LARGE off by more than 5%), else total_equity."""
    cols = ["sid", "shares", "book_equity_cr", "shares_source"]
    if bs is None or bs.empty:
        return pd.DataFrame(columns=cols)
    as_of = str(as_of)
    recent = (pd.Timestamp(as_of) - pd.Timedelta(days=RESTATE_LAG_DAYS)).date().isoformat()
    events = _split_events(adjustments)
    filed = filed_shares(filings, adjustments, as_of, events).to_dict()
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
        source = "vendor"
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
                    shares, source = s, "statement"
            if st["period_end"] == y0["end_date"]:
                equity = st["Equity Share Capital"] + st["Reserves"]
        f = filed.get(sid, float("nan"))
        if f > 0 and not (shares > 0 and 1 / FILED_SHARES_TOL <= shares / f <= FILED_SHARES_TOL):
            shares, source = f, "filing"
        rows.append((sid, shares, equity, source))
    return pd.DataFrame(rows, columns=cols)


def without_financials(stocks):
    """Drop Financials (structurally N/A for bank balance sheets; ADR 0048)."""
    if "sector" not in stocks.columns:
        return stocks
    return stocks[~stocks["sector"].isin(FINANCIAL_SECTORS)]
