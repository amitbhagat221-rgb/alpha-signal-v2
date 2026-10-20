"""On-screen bug sweep (2026-10-20): values a page shows must never read NaN / None / #nan."""
import math

import pandas as pd

from cockpit import api
from cockpit._shared import COCKPIT_TEMPLATES, make_templates


def test_group_top_players_unranked_stock_is_none_not_nan(monkeypatch):
    df = pd.DataFrame({"sid": ["a", "b"], "ticker": ["A", "B"], "name": ["x", "y"],
                       "market_cap_cr": [900.0, 100.0], "final_score": [0.61, float("nan")],
                       "rank": [3.0, float("nan")], "cap_tier": ["LARGE", None]})
    monkeypatch.setattr(api, "read_sql", lambda *a, **k: df.copy())
    monkeypatch.setattr(api, "latest_pick_date", lambda: "2026-10-20")
    monkeypatch.setattr(api.db, "scalar", lambda *a, **k: 1000.0)
    a, b = api.get_group_top_players("sector", "Financials")
    assert a["rank"] == 3 and str(a["rank"]) == "3"           # not "3.0"
    assert b["rank"] is None and b["final_score"] is None and b["cap_tier"] is None
    assert not any(isinstance(v, float) and math.isnan(v) for r in (a, b) for v in r.values())


def test_sector_card_shows_dash_for_unranked_peer():
    t = make_templates([COCKPIT_TEMPLATES])
    html = t.env.get_template("_sector_card.html").render(
        sector="Financials", sid="b",
        top_players=[{"sid": "a", "ticker": "A", "market_cap_cr": 900, "share_pct": 90.0, "rank": 3, "cap_tier": "LARGE"},
                     {"sid": "b", "ticker": "B", "market_cap_cr": 100, "share_pct": 10.0, "rank": None, "cap_tier": None}],
        picks={"top": [], "bottom": []}, macro_contributors=[], regulatory=[])
    assert "#3" in html and "#nan" not in html.lower() and "#None" not in html


def test_sell_reason_names_the_rule_that_sold():
    from cockpit.today import sell_reason
    assert sell_reason(None, 8, 5e7, 1e7) == "rank"          # dropped out of the ranking
    assert sell_reason(12, 8, 5e7, 1e7) == "rank"            # below the hold line
    assert sell_reason(3, 8, 0.92e7, 1e7) == "liquidity"     # VISAKAIND 2026-10-20: #3 but thin
    assert sell_reason(3, 8, 5e7, 1e7) == "screen"


def test_fund_nav_card_shows_the_newest_nav_not_the_metrics_nav(monkeypatch, tmp_path):
    import webauth
    from fastapi.testclient import TestClient
    from cockpit import app as app_mod
    from tests.test_cockpit_qa_display import NULL_METRICS, _fund
    monkeypatch.delenv("COCKPIT_PREVIEW", raising=False)
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    client = TestClient(app_mod.app, cookies={webauth.COOKIE: webauth.make_token()})
    fund = _fund({**NULL_METRICS, "nav": 87.66, "nav_date": "2026-10-08"})
    fund["latest_nav"] = {"nav": 90.35, "nav_date": "2026-10-19"}
    monkeypatch.setattr(app_mod.api, "get_mf_detail", lambda code: fund)
    monkeypatch.setattr(app_mod.api, "get_mf_peer_rank", lambda code: {"category": None, "peers": []})
    monkeypatch.setattr(app_mod.api, "get_mf_holdings", lambda code: {"top": [], "sectors": [], "as_of_date": None})
    html = client.get("/mutual-funds/1").text
    assert "90.35" in html and "as of 2026-10-19" in html and "returns and score to 2026-10-08" in html
    assert "daily to 2026-10-19" in html


def test_book_states_the_real_analyst_range():
    from cockpit import book
    b = book.get_book()
    if not b:
        return
    n = [r["n_analysts"] for r in b["rows"] if r["pt_upside_pct"] is not None and r["n_analysts"]]
    assert b["analysts_range"] == ((min(n), max(n)) if n else None)
    assert "One to five analysts" not in (COCKPIT_TEMPLATES / "book.html").read_text()


def test_ownership_card_shows_mfs_and_insurers_inside_dii():
    src = (COCKPIT_TEMPLATES / "stock_detail.html").read_text()
    row = src[src.index('("Promoter", "promoter_pct"'):].split("]", 1)[0]
    assert row.index('"dii_pct"') < row.index('"mf_pct"') < row.index('"insurance_pct"') < row.index('"retail_hni_pct"')
    assert '"of which MFs"' in row and '"Mutual Funds"' not in row


def test_options_page_writes_a_loss_as_minus_rupees(monkeypatch, tmp_path):
    import option_book
    import webauth
    from fastapi.testclient import TestClient
    from cockpit_ops.app import app
    data = option_book.page_data()
    base = {"underlying": "SENSEX", "entry_date": "2026-10-19", "expiry": "2026-10-22", "short_call": 75600,
            "call_entry": 23.35, "short_put": 72200, "put_entry": 20.65, "credit_pts": 44.0, "lot": 20,
            "margin_rs": 177450, "margin_source": "kite"}
    data["trades"] = [{**base, "status": "OPEN", "mark": {"mtm_rs": -57.0, "mark_date": "2026-10-19", "index": 73853}},
                      {**base, "status": "SETTLED", "settle_index": 74315.61, "net_rs": -930.0, "ret_on_margin": -0.0056}]
    data["summary"] = {**data["summary"], "n_slip": 1, "slip_median_pct": -1.0}
    monkeypatch.setattr(option_book, "page_data", lambda: data)
    monkeypatch.delenv("COCKPIT_PREVIEW", raising=False)
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    html = TestClient(app, cookies={webauth.COOKIE: webauth.make_token()}).get("/options").text
    assert "-₹57" in html and "-₹930" in html and "₹-" not in html and "₹+" not in html
    assert "(1 trade; bar 1%)" in html
