"""sources.mf_nav_daily.parse_nav_history — AMFI NAV-history report (gap repair)."""
from sources.mf_nav_daily import parse_nav_history

REPORT = """Scheme Code;NAV Name;Plan;Option;ISIN Div Payout/ISIN Growth;ISIN Div Reinvestment;Net Asset Value;Date

Open Ended Schemes ( Money Market )

Axis Mutual Fund

139619;Taurus Investor Education Pool - Growth;;;;;10.0000;19-Aug-2026
135762;Axis Children's Fund;Direct Plan;Growth Option;INF846K01WO1;-;29.6905;20-Aug-2026
135765;Axis Children's Fund;Direct Plan;IDCW Option;INF846K01WP8;-;N.A.;20-Aug-2026
"""


def test_columns_come_from_the_header_and_bad_navs_drop():
    assert parse_nav_history(REPORT) == [("139619", "2026-08-19", 10.0),
                                         ("135762", "2026-08-20", 29.6905)]
