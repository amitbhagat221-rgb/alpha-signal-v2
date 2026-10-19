"""One reporting basis per stock, and never a stale one (plan 0027; Amit 2026-10-19).

The vendor stopped refreshing consolidated quarters for 24 stocks (HDB, FCTL, UCBK …:
consolidated to 2025-03, standalone to 2026-06) and prefer_consolidated still fed the
factors the year-old consolidated trailing year."""
from datetime import date

import pandas as pd

import pit
from signals._fundamentals import STALE_BASIS_DAYS, prefer_consolidated

Q = ["2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31",
     "2026-03-31", "2026-06-30"]


def _qi(sid, consolidated, standalone):
    rows = [(sid, d, "consolidated", 1.0) for d in consolidated] + [(sid, d, "standalone", 2.0) for d in standalone]
    return pd.DataFrame(rows, columns=["sid", "end_date", "reporting", "eps"])


def test_stale_consolidated_falls_back_to_standalone():
    qi = _qi("HDB", Q[:4], Q)                                  # consolidated stops 2025-03, standalone 2026-06
    out = prefer_consolidated(qi)
    assert set(out["reporting"]) == {"standalone"} and len(out) == len(Q)


def test_fresh_or_one_quarter_behind_consolidated_is_kept():
    same = prefer_consolidated(_qi("A", Q, Q))
    behind = prefer_consolidated(_qi("B", Q[:-1], Q))        # consolidated print arrives after standalone
    assert set(same["reporting"]) == {"consolidated"} and set(behind["reporting"]) == {"consolidated"}
    assert set(prefer_consolidated(_qi("C", [], Q))["reporting"]) == {"standalone"}
    assert set(prefer_consolidated(_qi("D", Q, []))["reporting"]) == {"consolidated"}


def test_choice_is_per_stock_and_idempotent():
    qi = pd.concat([_qi("HDB", Q[:4], Q), _qi("A", Q, Q)])
    once = prefer_consolidated(qi)
    assert once.groupby("sid")["reporting"].unique().map(tuple).to_dict() == \
        {"HDB": ("standalone",), "A": ("consolidated",)}
    pd.testing.assert_frame_equal(prefer_consolidated(once), once)


def test_period_end_frames_use_the_same_rule():
    qi = _qi("HDB", Q[:4], Q).rename(columns={"end_date": "period_end"})
    assert set(prefer_consolidated(qi)["reporting"]) == {"standalone"}


def test_choice_is_point_in_time():
    """In 2025-06, before the standalone quarters ran ahead, consolidated was current: the
    backtest at that date uses it; today the same stock reads standalone. Both go through
    pit.knowable_quarterly → prefer_consolidated, the path live and backtest share."""
    qi = _qi("HDB", Q[:4], Q)
    then = prefer_consolidated(pit.knowable_quarterly(qi, date(2025, 6, 15)))
    now = prefer_consolidated(pit.knowable_quarterly(qi, date(2026, 10, 19)))
    assert set(then["reporting"]) == {"consolidated"} and then["end_date"].max() == "2025-03-31"
    assert set(now["reporting"]) == {"standalone"} and now["end_date"].max() == "2026-06-30"
    # ttm eps from the factor code path: standalone rows (eps 2.0 a quarter) today
    from signals.earnings_yield import earnings_yield
    ey = earnings_yield(pit.knowable_quarterly(qi, date(2026, 10, 19)),
                        pd.DataFrame({"sid": ["HDB"], "close_price": [100.0]}))
    assert abs(float(ey.set_index("sid").iloc[0, 0]) - 8.0 / 100.0) < 1e-9
    assert STALE_BASIS_DAYS < 181                              # two quarters behind is always stale


def test_screener_export_falls_back_to_a_fresher_standalone(monkeypatch):
    """The annual path: Screener's consolidated page froze at FY25 for the same names, and the
    harvester always took it. A stale consolidated export now loses to a fresher standalone one."""
    from sources import screener_pull as sp

    def export(newest):
        return pd.DataFrame({"sid": "HDB", "period_end": ["2024-03-31", newest], "period_type": "annual",
                             "line_item": "Sales", "value": 1.0})
    stale, fresh = export("2025-03-31"), export("2026-03-31")
    monkeypatch.setattr(sp, "fetch_export", lambda s, t, views=sp.VIEWS: (b"x", views[0]))
    monkeypatch.setattr(sp, "parse_export", lambda xls, sid: fresh)
    assert sp._fresher_view(None, "HDB", "HDBFS", stale) is fresh
    current = export(pd.Timestamp.today().strftime("%Y-%m-%d"))
    assert sp._fresher_view(None, "HDB", "HDBFS", current) is current        # recent: no extra fetch needed
    monkeypatch.setattr(sp, "parse_export", lambda xls, sid: export("2025-06-30"))
    assert sp._fresher_view(None, "HDB", "HDBFS", stale) is stale            # standalone not newer enough
