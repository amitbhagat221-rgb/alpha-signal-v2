"""The pick gate around a results season (regression 2026-10-14..20).

The five big private banks dropped out of the LARGE daily_picks: each one's July print aged
past announcement_car's 90-day staleness before its October print's [-1,+1] window closed, so
the factor (35 % of LARGE weight) had no value. Two gate rules then failed together:
  * eligible_coverage 0.5625 < 0.60 — the eligibility rule (any print in 95 days) was wider than
    what the factor can measure, so the gap counted as "eligible but missing";
  * weight_coverage 0.45 < 0.50 — the backstop divided by the tier total, including
    asset_growth_yoy (0.20), which never exists for a bank (a LARGE Financial's ceiling was 0.8).
"""
import sqlite3
from datetime import date, timedelta

import numpy as np
import pandas as pd

import factors
from scoring import screener


# ── announcement_car eligibility = exactly the prints the factor can measure ──

def _announcement_db(today, prints):
    """In-memory DB with a daily price row per sid up to YESTERDAY (a morning run) and the given
    Result prints {sid: [days_ago, …]} in bse_announcements."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE bse_announcements (news_id TEXT, sid TEXT, dt_tm TEXT, category TEXT, subcategory TEXT,
                                        headline TEXT, news_sub TEXT, attachment TEXT);
        CREATE TABLE nse_announcements (seq_id TEXT, sid TEXT, an_dt TEXT, desc_category TEXT, subject TEXT,
                                        attachment_url TEXT);
        CREATE TABLE stock_prices (sid TEXT, date TEXT, close REAL, PRIMARY KEY (sid, date));
    """)
    days = [(today - timedelta(days=k)).isoformat() for k in range(200, 0, -1)]   # ends yesterday
    for sid in prints:
        conn.executemany("INSERT INTO stock_prices VALUES (?, ?, ?)",
                         [(sid, d, 100.0 + i * (0.3 if sid < "C" else -0.2)) for i, d in enumerate(days)])
        for k in prints[sid]:
            conn.execute("INSERT INTO bse_announcements VALUES (?, ?, ?, 'Result', 'Financial Results', "
                         "'Financial Results', '', '')",
                         (f"{sid}{k}", sid, (today - timedelta(days=k)).isoformat() + "T12:00:00"))
    nifty = pd.DataFrame({"date": days, "value": [20000.0 + i for i in range(len(days))]})
    return conn, nifty


def test_announcement_car_eligibility_matches_what_the_factor_can_measure():
    from signals.announcement_car import STALE_DAYS, compute_announcement_car
    probe = sqlite3.connect(":memory:")
    today = date.fromisoformat(probe.execute("SELECT date('now')").fetchone()[0])   # the SQL's 'now'
    prints = {
        "A": [30],          # fresh print, window closed                 → value, eligible
        "B": [92],          # only print just past STALE_DAYS            → no value, NOT eligible (was, at 95d)
        "C": [92, 1],       # HDFC Bank on 2026-10-20: new print yesterday, window still open,
                            # prior one stale                              → no value, NOT eligible
        "D": [92, 4],       # the new print's window has closed          → value, eligible
    }
    conn, nifty = _announcement_db(today, prints)
    sql = factors.SIGNAL_ELIGIBILITY["announcement_car"]["eligible_sql"]
    eligible = {r[0] for r in conn.execute(sql)}

    prices = pd.read_sql_query("SELECT sid, date, close FROM stock_prices", conn)
    anns = pd.read_sql_query("SELECT sid, dt_tm FROM bse_announcements", conn)
    car = compute_announcement_car(prices=prices, nifty=nifty, announcements=anns,
                                   as_of_date=today.isoformat())
    measured = set(car.loc[car["announcement_car"].notna(), "sid"])

    assert measured == {"A", "D"}
    assert eligible == measured                                # was {A, B, C, D}: B and C gated out
    assert f"-{STALE_DAYS} day" in sql                         # one staleness rule, factor and eligibility


# ── the weight_coverage backstop ignores factors structurally N/A for the sector ──

def _large_frame():
    """Two LARGE stocks scored like 2026-10-20: a bank between prints (no announcement_car, no
    asset growth by construction) and a non-financial missing the same two factors."""
    w = factors.SIGNAL_WEIGHTS["LARGE"]
    assert {"announcement_car", "asset_growth_yoy"} <= set(w)
    cols = {c for k in w for c in [factors.SCREENER_TIER_COLS.get((k, "LARGE")) or factors.SCREENER_COLS[k]]}
    df = pd.DataFrame({"sid": ["BANK", "INDU", "P1", "P2"], "cap_tier": "LARGE",
                       "sector": ["Financials", "Industrials", "Industrials", "Industrials"],
                       "penalty": 0.0, "price_rows": 500, "fundamental_coverage": 1.0})
    for c in cols:
        df[c] = [0.5, 0.5, 0.2, 0.8]
    car = factors.SCREENER_COLS["announcement_car"]
    ag = factors.SCREENER_COLS["asset_growth_yoy"]
    df.loc[df.sid.isin(["BANK", "INDU"]), car] = np.nan
    df.loc[df.sid.isin(["BANK", "INDU"]), ag] = np.nan
    return df


def test_bank_between_results_prints_stays_in_the_ranking(monkeypatch):
    df = _large_frame()
    # eligibility snapshot: no announcement_car reading is possible for either (between prints);
    # asset growth is N/A for the bank only
    elig = pd.DataFrame({"announcement_car": [0, 0, 1, 1], "asset_growth_yoy": [0, 1, 1, 1]},
                        index=pd.Index(df["sid"], name="sid"))
    monkeypatch.setattr(screener, "_load_eligibility_wide", lambda as_of=None: elig)
    s = screener.score_universe(df).set_index("sid")
    ok = screener._pick_eligible(s.reset_index()).set_axis(s.index)

    w = factors.SIGNAL_WEIGHTS["LARGE"]
    covered = 1.0 - abs(w["announcement_car"]) - abs(w["asset_growth_yoy"])
    applicable = 1.0 - abs(w["asset_growth_yoy"])
    assert s.loc["BANK", "weight_coverage"] == np.float64(covered / applicable)    # 0.5625, was 0.45
    assert s.loc["BANK", "eligible_coverage"] == 1.0
    assert ok["BANK"]
    # a non-financial missing the same factors is NOT helped: its asset growth applies and is missing
    assert s.loc["INDU", "weight_coverage"] == np.float64(covered)
    assert not ok["INDU"]
    assert s.loc["P1", "weight_coverage"] == 1.0 and ok["P1"]


def test_not_for_sectors_mirrors_the_eligibility_sql():
    """A factor whose eligible_sql drops Financials declares it in `not_for_sectors` (and only then),
    so the backstop and the eligibility snapshot agree on what is structurally N/A."""
    for key, e in factors.SIGNAL_ELIGIBILITY.items():
        drops_fin = "sector = 'Financials'" in e["eligible_sql"]
        assert drops_fin == ("Financials" in factors.SIGNAL_NOT_FOR_SECTORS.get(key, ())), key
