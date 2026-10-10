"""Display fixes from the 2026-10 data-QA sweep of the cockpit preview: fund pages with NULL scores,
the peer table, the consensus tab, price-history gaps, tier counts and held-but-unranked names."""
import re

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import views
import webauth


@pytest.fixture
def client(monkeypatch, tmp_path):
    from cockpit.app import app
    monkeypatch.delenv("COCKPIT_PREVIEW", raising=False)
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    return TestClient(app, cookies={webauth.COOKIE: webauth.make_token()})


# ── 1. a fund with NULL scores renders ──────────────────────────────────────────

NULL_METRICS = {k: None for k in (
    "nav", "ret_1y", "ret_3y_cagr", "ret_5y_cagr", "ret_10y_cagr", "ret_since_inception_cagr", "std_1y", "std_3y",
    "sharpe_1y", "sharpe_3y", "sortino_1y", "max_drawdown", "recovery_days", "composite_score",
    "score_3y_cagr_pct", "score_sharpe_3y_pct", "score_max_dd_pct", "score_consistency_pct",
    "bench_spread_1y", "bench_spread_3y", "peer_rank_3y", "peer_count", "max_dd_start", "max_dd_end")}
NULL_METRICS.update(nav_date="2026-10-09", as_of_date="2026-10-09")


def _fund(metrics):
    info = {"scheme_code": "1", "scheme_name": "Test Fund", "amc": "X", "category_norm": "Equity / Large Cap",
            "category_raw": None, "plan_type": "DIRECT", "option_type": "GROWTH", "isin_growth": None,
            "isin_div": None, "aum_cr": None, "expense_ratio": None, "benchmark": None, "data_quality": None,
            "quality_reason": None, "inception_date": None, "has_full_history": 1, "last_seen": None,
            "is_debt": False, "has_bench": True}
    return {"info": info, "metrics": metrics, "calendar": [], "cat_rank": None}


def test_fund_with_null_scores_renders(client, monkeypatch):
    from cockpit import app as app_mod
    monkeypatch.setattr(app_mod.api, "get_mf_detail", lambda code: _fund(dict(NULL_METRICS)))
    monkeypatch.setattr(app_mod.api, "get_mf_peer_rank", lambda code: {"category": None, "peers": []})
    monkeypatch.setattr(app_mod.api, "get_mf_holdings", lambda code: {"top": [], "sectors": [], "as_of_date": None})
    r = client.get("/mutual-funds/1")
    assert r.status_code == 200 and "Score breakdown" in r.text


# ── 2. the peer table: latest snapshot, no repeats, same order as the rank ──────

def test_peer_table_matches_the_category_rank(monkeypatch):
    from cockpit import mf
    pool = pd.DataFrame({
        "scheme_code": list("ABCD"), "scheme_name": list("abcd"), "amc": "X",
        "category_norm": ["Cat", "Cat", "Cat", "Other"], "composite_score": [50.0, 80.0, 65.0, 99.0],
        "ret_3y_cagr": 10.0, "sharpe_3y": 1.0})
    pool["cat_rank"] = pool.groupby("category_norm")["composite_score"].rank(ascending=False, method="min")
    pool["cat_n"] = pool.groupby("category_norm")["composite_score"].transform("count")
    monkeypatch.setattr(mf, "_mf_universe_pool", lambda: pool)
    monkeypatch.setattr(mf.db, "scalar", lambda *a, **k: "Cat")
    peers = mf.get_mf_peer_rank("C", top_n=10)["peers"]
    codes = [p["scheme_code"] for p in peers]
    assert codes == ["B", "C", "A"] and len(set(codes)) == len(codes)      # best first, one row per scheme
    assert codes.index("C") + 1 == mf.mf_category_rank("C")[0]            # "#2 of 3" is the second row


# ── 3. consensus tab uses the median, the mean only when it is inside low-high ──

def _ac(**kw):
    base = {"price_target": None, "price_target_median": None, "price_target_low": None, "price_target_high": None,
            "current_price": 90.0, "total_analysts": None, "fetched_at": "2026-10-09 04:00:00",
            "pt_source": "yfinance", "days_since_pt_change": 2, "pt_change_pct": 0.0, "pt_upside_median_pct": 11.1}
    base.update(kw)
    return base


def _first_ranked(client):
    return re.search(r'class="st-tk" href="/stocks/([^"]+)"', client.get("/stocks").text).group(1)


def test_consensus_tab_shows_the_median_target(client, monkeypatch):
    from cockpit import app as app_mod
    sid = _first_ranked(client)
    monkeypatch.setattr(app_mod.api, "get_analyst_consensus", lambda s: _ac(price_target_median=100.0))
    page = client.get(f"/stocks/{sid}").text
    assert "No analyst price target available" not in page
    assert "? sell-side" not in page and "of ? analysts" not in page
    assert "median, vs close" in page


def test_an_impossible_mean_is_not_shown_and_no_pt_move(client, monkeypatch):
    from cockpit import app as app_mod
    sid = _first_ranked(client)
    ac = _ac(price_target=500.0, price_target_median=100.0, price_target_low=80.0, price_target_high=120.0,
             total_analysts=7, pt_change_pct=12.0, days_since_pt_change=3)
    monkeypatch.setattr(app_mod.api, "get_analyst_consensus", lambda s: ac)
    page = client.get(f"/stocks/{sid}").text
    assert "PT moved" not in page and "median of 7 analysts" in page
    monkeypatch.setattr(app_mod.api, "get_analyst_consensus", lambda s: {**ac, "price_target": 100.0})
    assert "PT moved" in client.get(f"/stocks/{sid}").text


def test_no_target_at_all_still_says_so(client, monkeypatch):
    from cockpit import app as app_mod
    sid = _first_ranked(client)
    monkeypatch.setattr(app_mod.api, "get_analyst_consensus", lambda s: _ac())
    assert "No analyst price target available" in client.get(f"/stocks/{sid}").text


# ── 5. price history with a hole shows no return over it ────────────────────────

def _series(*spans):
    dates = [d for a, b in spans for d in pd.bdate_range(a, b)]
    return pd.DataFrame({"date": [d.strftime("%Y-%m-%d") for d in dates],
                         "close": [100.0 + i * 0.1 for i in range(len(dates))]})


def test_a_price_gap_blocks_the_returns_it_spans():
    m = views._price_metrics(_series(("2023-01-02", "2023-10-20"), ("2026-04-01", "2026-10-09")))
    assert "return_1y" not in m and m["returns_incomplete"] and "return_6m" in m      # 6M sits wholly after the gap
    assert m["price_gap"]["from"] == "2023-10-20" and m["price_gap"]["to"] == "2026-04-01"
    assert m["low_52w"] > 110                                   # the 52w range is the last 365 days only


def test_a_clean_year_keeps_its_returns():
    m = views._price_metrics(_series(("2025-01-01", "2026-10-09")))
    assert {"return_1m", "return_3m", "return_6m", "return_1y"} <= set(m)
    assert "price_gap" not in m and "returns_incomplete" not in m


def test_a_short_gap_inside_a_window_blocks_only_that_window():
    m = views._price_metrics(_series(("2025-01-01", "2026-05-29"), ("2026-07-01", "2026-10-09")))
    assert m["price_gap"]["days"] > 14 and "return_6m" not in m and "return_1y" not in m
    assert "return_1m" in m


# ── 7. Explorer and Stocks count the same stocks in each tier ───────────────────

def test_explorer_and_stocks_agree_on_tier_counts():
    from cockpit import api, stocks
    heat = api.get_heatmap_data()
    u = stocks.universe()
    for tier in views.display_tiers():
        assert len(heat[tier]) == sum(r["ranked"] and r["tier"] == tier for r in u["rows"]), tier
    for tier in views.unpickable_tiers():
        assert len(heat.get(tier, [])) == sum(not r["ranked"] and r["tier"] == tier for r in u["rows"]), tier
    ranked_sids = {s["sid"] for t in views.display_tiers() for s in heat[t]}
    assert not ranked_sids & {s["sid"] for t in views.unpickable_tiers() for s in heat.get(t, [])}


# ── 8. a held name with no rank today is "Not ranked today" ─────────────────────

def test_held_but_unranked_is_not_below_the_sell_line():
    from cockpit import book
    assert book.held_status("not ranked today", False, ranked=False) == ("Not ranked today", "amber")
    assert book.held_status("left top picks 3 Oct", True, ranked=True) == ("Below sell line", "red")
    assert book.held_status(None, False, ranked=True) == ("In top picks", "green")


def test_unranked_stock_page_does_not_guess_the_reason(client, monkeypatch):
    from cockpit import app as app_mod
    sid = _first_ranked(client)
    real = app_mod.api.get_stock_detail

    def unranked(s):
        d = real(s)
        d["final_score"], d["rank"], d["pick_date"] = None, None, None
        return d
    monkeypatch.setattr(app_mod.api, "get_stock_detail", unranked)
    page = client.get(f"/stocks/{sid}").text
    assert "is not in today's ranking" in page and "failed the data gate" not in page
    monkeypatch.setattr(app_mod.api, "get_dossier", lambda s: {"thesis": "It tops the ranking.", "as_of": "2020-01-01"})
    assert "any claim about its rank or position may be out of date" in client.get(f"/stocks/{sid}").text


# ── bulk deals: the company itself is not a counterparty, and a row shows once ──

def test_bulk_deals_hide_the_company_and_repeats(monkeypatch):
    from cockpit import api
    rows = [{"client_name": "Lodha Developers Limited", "buy_sell": "BUY", "quantity": 5.0, "price": 9.0,
             "deal_date": "2026-06-25", "deal_type": "bulk"},
            {"client_name": "FIDELITY FUND", "buy_sell": "BUY", "quantity": 5.0, "price": 9.0,
             "deal_date": "2026-06-25", "deal_type": "bulk"},
            {"client_name": "Fidelity Fund", "buy_sell": "BUY", "quantity": 5.0, "price": 9.0,
             "deal_date": "2026-06-25", "deal_type": "bulk"}]
    monkeypatch.setattr(api.db, "one", lambda *a, **k: {"name": "Lodha Developers Ltd"})
    monkeypatch.setattr(api.db, "rows", lambda *a, **k: list(rows))
    out = api.get_bulk_deals("LOD")
    assert [r["client_name"] for r in out] == ["FIDELITY FUND"]


# ── 11. Library wording follows the evidence ────────────────────────────────────

def test_proposed_factor_wording_follows_its_t():
    from cockpit import model
    assert "below the 2.5 bar" in model.bench_note("PROPOSED", 0.68)
    assert "strong" not in model.bench_note("PROPOSED", 0.68)
    assert "clears" in model.bench_note("PROPOSED", 3.1)
    assert model.bench_note("PROPOSED", None).startswith("Proposed: no test")
    assert model.bench_note("PROPOSED", 4.0, "DROPPED").startswith("Blocked")
