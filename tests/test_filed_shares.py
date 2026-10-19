"""The one share count (plan 0027; Amit 2026-10-19): the vendor count, cross-checked against
the latest BSE shareholding filing (signals._fundamentals.filed_shares), adjusted for splits
and bonuses after the filing, point in time. Live tiers, the MICRO carve-out,
stocks.market_cap_cr, fcf_yield, book_to_price and the multibagger thesis all read it."""
import sqlite3
from datetime import date

import pandas as pd
import pytest

import config
import db
from signals._fundamentals import FILED_SHARES_TOL, filed_shares, market_caps, shares_and_book

AS_OF = "2026-10-16"
NO_FUND = pd.DataFrame(columns=["sid", "period_end", "line_item", "value"])
NO_ADJ = pd.DataFrame(columns=["sid", "ex_date", "factor", "inds"])


def _bs(**shares_cr):
    return pd.DataFrame({"sid": list(shares_cr), "end_date": "2026-03-31",
                         "shares_outstanding": list(shares_cr.values()), "total_equity": 100.0})


def _filing(sid, total, end="2026-06-30", filed="2026-07-18T10:00:00"):
    return {"sid": sid, "end_date": end, "filed_at": filed, "total_shares": total}


def test_a_split_after_the_filing_adjusts_the_filed_count():
    """A 1:2 split after the June quarter: the filing's pre-split count, on the as-of basis, is twice it —
    so it agrees with a vendor that restated, and the vendor count stands."""
    adj = pd.DataFrame({"sid": ["SPL"], "ex_date": ["2026-08-01"], "factor": [0.5], "inds": ["SPLIT"]})
    filings = pd.DataFrame([_filing("SPL", 1e7)])
    assert filed_shares(filings, adj, AS_OF)["SPL"] == pytest.approx(2e7)
    assert filed_shares(filings, adj, "2026-07-25")["SPL"] == pytest.approx(1e7)     # before the split goes ex
    sb = shares_and_book(_bs(SPL=2.0), NO_FUND, adj, AS_OF, filings).set_index("sid")
    assert sb.loc["SPL", "shares"] == pytest.approx(2e7) and sb.loc["SPL", "shares_source"] == "vendor"
    demerger = pd.DataFrame({"sid": ["SPL"], "ex_date": ["2026-08-01"], "factor": [0.37], "inds": ["DEMERGER"]})
    assert filed_shares(filings, demerger, AS_OF)["SPL"] == pytest.approx(1e7)     # a demerger is not a unit change


def test_the_filing_wins_when_the_vendor_disagrees_either_way():
    """IIAB: the vendor kept 0.99 Cr shares after an allotment that made it 23 Cr (22x). VEDL: the vendor divided
    the count by the demerger's price factor (2.7x too many). Inside the tolerance the vendor count stands."""
    filings = pd.DataFrame([_filing("IIAB", 2.33e8), _filing("VEDL", 3.91e9), _filing("NEAR", 1.2e7)])
    sb = shares_and_book(_bs(IIAB=0.99, VEDL=1044.8, NEAR=1.0), NO_FUND, NO_ADJ, AS_OF, filings).set_index("sid")
    assert sb.loc["IIAB", "shares"] == pytest.approx(2.33e8) and sb.loc["IIAB", "shares_source"] == "filing"
    assert sb.loc["VEDL", "shares"] == pytest.approx(3.91e9) and sb.loc["VEDL", "shares_source"] == "filing"
    assert 1.2 < FILED_SHARES_TOL and sb.loc["NEAR", "shares"] == pytest.approx(1e7)  # 1.2x apart: an allotment's noise
    assert sb.loc["NEAR", "shares_source"] == "vendor"
    mc = market_caps(_bs(IIAB=0.99), NO_FUND, NO_ADJ, pd.DataFrame({"sid": ["IIAB"], "close_price": [30.0]}),
                     AS_OF, filings)
    assert mc.loc[0, "mcap_cr"] == pytest.approx(2.33e8 * 30 / 1e7) and mc.loc[0, "shares_source"] == "filing"
    without = shares_and_book(_bs(IIAB=0.99), NO_FUND, NO_ADJ, AS_OF).set_index("sid")         # no filings: as before
    assert without.loc["IIAB", "shares"] == pytest.approx(0.99e7) and without.loc["IIAB", "shares_source"] == "vendor"


def test_a_filing_counts_from_its_broadcast_and_only_while_recent():
    filings = pd.DataFrame([_filing("A", 5e6, end="2026-03-31", filed="2026-04-20T09:00:00"),
                            _filing("A", 9e6, end="2026-06-30", filed="2026-07-18T09:00:00"),
                            _filing("A", 9.5e6, end="2026-06-30", filed="2026-08-30T09:00:00"),    # a revision
                            _filing("B", 4e6, end="2025-09-30", filed="2025-10-20T09:00:00")])     # too old
    assert filed_shares(filings, NO_ADJ, "2026-07-10")["A"] == 5e6         # June filing not yet broadcast
    assert filed_shares(filings, NO_ADJ, "2026-08-01")["A"] == 9e6
    assert filed_shares(filings, NO_ADJ, AS_OF)["A"] == 9.5e6              # the revision, from its own broadcast
    assert "B" not in filed_shares(filings, NO_ADJ, AS_OF)
    assert "B" in filed_shares(filings, NO_ADJ, "2026-01-15")


def _make_db(path):
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE stocks (sid TEXT PRIMARY KEY, ticker TEXT NOT NULL, name TEXT NOT NULL, sector TEXT, "
              "industry TEXT, cap_tier TEXT, market_cap_cr REAL)")
    c.executescript((config.PROJECT_ROOT / "schema.sql").read_text())
    for sid in ("IIAB", "SPL"):
        c.execute("INSERT INTO stocks (sid, ticker, name, sector, cap_tier) VALUES (?, ?, ?, 'Industrials', 'SMALL')",
                  (sid, sid, sid))
        c.execute("INSERT INTO annual_balance_sheet (sid, period, end_date, total_equity, shares_outstanding, fetched_at) "
                  "VALUES (?, '2026-03', '2026-03-31', 100.0, ?, '2026-06-15')", (sid, 0.99 if sid == "IIAB" else 2.0))
        for q in ("2025-09-30", "2025-12-31", "2026-03-31", "2026-06-30"):
            c.execute("INSERT INTO quarterly_income (sid, period, end_date, reporting, revenue, eps, fetched_at) "
                      "VALUES (?, ?, ?, 'standalone', 10.0, 1.0, '2026-08-01')", (sid, q[:7], q))
        for d in pd.bdate_range("2026-06-01", AS_OF):
            c.execute("INSERT INTO stock_prices (sid, date, close, volume) VALUES (?, ?, 30.0, 100000)",
                      (sid, d.date().isoformat()))
    c.execute("INSERT INTO fundamentals_screener (sid, period_end, period_type, line_item, value) "
              "VALUES ('SPL', '2026-03-31', 'annual', 'Sales', 40.0)")
    c.execute("INSERT INTO corporate_adjustments (sid, ex_date, factor, n_events, inds) "
              "VALUES ('SPL', '2026-08-01', 0.5, 1, 'SPLIT')")
    for sid, total in (("IIAB", 2.33e8), ("SPL", 1e7)):
        c.execute("INSERT INTO shareholding_categories (sid, scrip_cd, end_date, filed_at, total_shares, fetched_at) "
                  "VALUES (?, 1, '2026-06-30', '2026-07-18T10:00:00', ?, '2026-07-18')", (sid, total))
    c.commit()
    c.close()


def test_live_tier_inputs_read_the_filed_count(tmp_path, monkeypatch):
    """scoring.segment.inputs — live tiers, the MICRO carve-out and stocks.market_cap_cr — on a temp DB: IIAB's
    market cap comes from its filing; SPL's split after the filing leaves the restated vendor count standing.
    Before the June filing was broadcast the backtest (same function) sees the vendor count."""
    path = tmp_path / "shares.db"
    _make_db(path)
    monkeypatch.setattr(db, "DB_PATH", path)
    from scoring import segment
    ti = segment.inputs(AS_OF).set_index("sid")
    assert ti.loc["IIAB", "mcap_cr"] == pytest.approx(2.33e8 * 30 / 1e7) and ti.loc["IIAB", "shares_source"] == "filing"
    assert ti.loc["SPL", "mcap_cr"] == pytest.approx(2e7 * 30 / 1e7) and ti.loc["SPL", "shares_source"] == "vendor"
    import pit
    raw = pit.load_raw(set(pit.TIER_INPUTS) | {"adjustments"})
    px = db.read_sql("SELECT sid, date, close, volume FROM stock_prices")
    then = date(2026, 7, 10)
    early = pit.tier_inputs(then, raw, pit.apply_pit_adjustments(px[px["date"] <= then.isoformat()], raw["adjustments"], then))
    assert early.set_index("sid").loc["IIAB", "shares_source"] == "vendor"
