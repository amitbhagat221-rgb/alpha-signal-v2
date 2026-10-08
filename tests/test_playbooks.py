"""Investor Playbooks (/playbooks) — the pure rules. Offline: no DB."""
import pandas as pd

from cockpit import playbooks as pb


def test_names_normalise_and_followed_patterns_need_every_word():
    assert pb._norm("  Madhusudan  Murlidhar Kela .. ") == "MADHUSUDAN MURLIDHAR KELA"
    assert pb._norm("NEMISH S SHAH (HUF)") == "NEMISH S SHAH HUF"

    def who(name):
        t = set(pb._norm(name).split())
        return [k for k, pats in pb.FOLLOWED.items() if any(set(p) <= t for p in pats)]

    assert who("Ashish Rameshchandra Kacholia") == ["Ashish Kacholia"]
    assert who("KEDIA SECURITIES PRIVATE LIMITED") == ["Vijay Kedia"]
    assert who("Ankush Kedia") == [], "a shared surname alone is not a match"
    assert who("RAMESH DAMANI") == ["Ramesh Damani"] and who("Radhakishan S Damani") == ["Radhakishan Damani"]


def test_percentile_is_share_of_history_below():
    assert pb._pctile([1, 2, 3, 4], 3) == 50
    assert pb._pctile([], 3) is None and pb._pctile([1, 2], None) is None


def test_own_history_value_is_free_of_share_counts(monkeypatch):
    """Price halves on a 1:1 bonus and profit is flat: the multiple must NOT look cheaper."""
    months = pd.date_range("2022-01-31", periods=30, freq="ME").strftime("%Y-%m-%d")
    raw = [200.0] * 15 + [100.0] * 15                       # bonus goes ex before the 16th month-end
    prices = pd.DataFrame({"sid": "S", "date": months, "close": raw})
    adj = pd.DataFrame({"sid": ["S"], "ex_date": [months[15]], "factor": [0.5]})

    def fake_sql(q, params=None):
        return prices if "FROM stock_prices" in q else adj

    monkeypatch.setattr(pb, "read_sql", fake_sql)
    monkeypatch.setattr(pb, "scalar", lambda q: "2018-03-01")
    monkeypatch.setattr(pb, "_snapshot", lambda: {"rows": pd.DataFrame({"earnings_yield": [0.05]}, index=["S"])})
    annual = {"S": pd.DataFrame({"period_end": ["2021-03-31", "2022-03-31", "2023-03-31"], "Net profit": [10.0, 10.0, 10.0]})}
    v = pb._own_history_value(["S"], annual)["S"]
    assert v["vs_median"] == 0 and v["cheaper_than"] == 0 and v["pe"] == 20.0


def test_roadmap_statuses_and_rules_are_exposed():
    assert {s for _, _, s, _ in pb.ROADMAP} <= {"live", "partial", "not built"}
    assert len(pb.CATEGORIES) == 6


# ─────────────────────────────── say vs do (output/say_do.py) ───────────────────────────────

def _result(**over):
    r = {"promises": [{"said": "Commission the new plant by the end of FY26", "outcome": "delivered", "evidence": "The plant started production in Q1"},
                      {"said": "Bring debt down", "outcome": "partly", "evidence": "Debt fell but less than planned"}],
         "verdict": "mixed", "summary": "Management delivered the plant on time. Debt reduction is behind plan."}
    r.update(over)
    return r


def test_say_do_validates_shape_verdict_and_number_rule():
    import pytest
    from output import say_do as sd
    assert sd.validate(_result())["verdict"] == "mixed"
    with pytest.raises(ValueError, match="numbers are not allowed"):
        sd.validate(_result(summary="Margins rose to 18.5% as guided."))
    with pytest.raises(ValueError, match="no_guidance"):
        sd.validate(_result(promises=[], verdict="mixed"))
    assert sd.validate(_result(promises=[], verdict="no_guidance"))["promises"] == []
    with pytest.raises(ValueError, match="keeps_word with a missed"):
        sd.validate(_result(promises=[{"said": "a", "outcome": "missed", "evidence": "dropped"},
                                      {"said": "b", "outcome": "delivered", "evidence": "done"}], verdict="keeps_word"))
    with pytest.raises(ValueError, match="outcome"):
        sd.validate(_result(promises=[{"said": "a", "outcome": "done", "evidence": "x"}]))


def test_say_do_extract_keeps_commitments_and_drops_boilerplate():
    from output import say_do as sd
    text = ("All participant lines will be in the listen-only mode and we expect questions later. "
            "We expect to commission the second plant by the end of next fiscal year and we are on track. "
            "The weather was pleasant in Mumbai during the quarter and everyone enjoyed it a great deal.")
    picked = sd._pick(text, sd._FORWARD, 5000)
    assert "second plant" in picked and "listen-only" not in picked and "weather" not in picked


# ─────────────────────────────── sleeves.py + tools/playbook_backtest.py ───────────────────────────────

def _frame(**cols):
    return pd.DataFrame(cols, index=[f"S{i}" for i in range(len(next(iter(cols.values()))))])


def test_sleeve_masks_follow_the_stated_rules():
    import sleeves
    f = _frame(announcement_car=[0.02, 0.02, -0.01, 0.02], delivery_anomaly_z=[1.5, 0.5, 2.0, 1.5],
               position_52w=[0.9, 0.9, 0.95, 0.5], mom_6m=[10, 10, 10, 10])
    assert list(sleeves.breakout_mask(f)) == [True, False, False, False]
    v = _frame(book_to_price=[1.2, 1.2, 30.0, 0.5], earnings_yield=[0.10, 0.10, 0.10, 0.10], debt_to_equity=[0.1, 0.9, 0.1, 0.1])
    assert list(sleeves.deep_value_mask(v)) == [True, False, False, False], "debt, an implausible ratio and above-book are all out"


def test_insider_rule_needs_net_buying_of_size_or_a_cluster():
    import sleeves
    t = pd.DataFrame([("A", "p1", "Buy", 150, "2026-09-01"), ("A", "p1", "Sell", 20, "2026-09-02"),      # net 1.3 cr
                      ("B", "p1", "Buy", 10, "2026-09-01"), ("B", "p2", "Buy", 10, "2026-09-03"),       # small, two buyers
                      ("C", "p1", "Buy", 50, "2026-09-01"),                                             # small, one buyer
                      ("D", "p1", "Buy", 500, "2026-09-01"), ("D", "p2", "Sell", 900, "2026-09-02")],   # net seller
                     columns=["sid", "person", "side", "value_lakhs", "trade_date"])
    got = sleeves.insider_net_buyers(t).set_index("sid")
    assert sorted(got.index) == ["A", "B"] and got.at["A", "net_cr"] == 1.3 and bool(got.at["B", "cluster"])


def test_quality_rule_uses_only_the_years_given():
    import sleeves
    good = pd.DataFrame({"period_end": [f"{y}-03-31" for y in range(2016, 2021)], "Profit before tax": [20.0] * 5, "Interest": [0.0] * 5,
                         "Equity Share Capital": [10.0] * 5, "Reserves": [90.0] * 5, "Borrowings": [0.0] * 5,
                         "Sales": [100.0, 115, 132, 152, 175], "Net profit": [15.0] * 5})
    assert sleeves.quality_stats(good, 5, 4)["hits"] == 5
    assert sleeves.quality_stats(good.iloc[:4], 5, 4) is None, "four years known is not five"
    loss = good.copy(); loss.loc[2, "Net profit"] = -1.0
    assert sleeves.quality_stats(loss, 5, 4) is None


def test_backtest_month_anchors_cost_and_stats():
    from tools import playbook_backtest as bt
    assert bt.month_anchors(["2024-01-01", "2024-01-05", "2024-02-02", "2024-02-09"]) == ["2024-01-01", "2024-02-02"]
    ret = pd.Series({"A": 0.10, "B": 0.00}); tier = pd.Series({"A": "LARGE", "B": "SMALL"})
    gross, bench, cost, turn = bt._hold({"A": 0.5, "B": 0.5}, None, ret, tier, {"LARGE": 0.02, "SMALL": 0.04})
    assert round(gross, 4) == 0.05 and round(bench, 4) == 0.03 and round(turn, 2) == 0.5
    assert round(cost, 6) == round(0.5 * bt.COST["LARGE"] + 0.5 * bt.COST["SMALL"], 6), "entering a position costs its tier's rate"
    _, _, cost2, turn2 = bt._hold({"A": 0.5, "B": 0.5}, {"A": 0.5, "B": 0.5}, ret, tier, {"LARGE": 0.02, "SMALL": 0.04})
    assert cost2 == 0 and turn2 == 0, "an unchanged book trades nothing"
    st = bt._stats([{"month": f"2024-{m:02d}", "net": 0.01, "cost": 0.001, "index": 0.0, "bench": 0.02, "turnover": 0.1, "n": 10} for m in range(1, 13)])
    assert st["months"] == 12 and st["excess_ann"] == -12.0 and st["hit_rate"] == 0 and st["index_ann"] == 0.0


def test_cloning_needs_an_earlier_filing_and_reads_only_what_was_public():
    import sleeves
    rows = [  # sid, end_date, filed_at, investor, pct
        ("A", "2026-03-31", "2026-04-20T10:00:00", None, 5.0),          # someone else was named in A's earlier filing
        ("A", "2026-06-30", "2026-07-20T10:00:00", "Inv", 1.4),         # → Inv is NEW in A
        ("B", "2026-03-31", "2026-04-20T10:00:00", "Inv", 2.0),
        ("B", "2026-06-30", "2026-07-20T10:00:00", "Inv", 2.6),         # → UP in B
        ("C", "2026-06-30", "2026-07-20T10:00:00", "Inv", 3.0),         # C has no earlier filing → unknown
        ("D", "2026-03-31", "2026-04-20T10:00:00", "Inv", 2.0),
        ("D", "2026-06-30", "2026-07-20T10:00:00", "Inv", 1.2)]         # → DOWN in D
    h = pd.DataFrame(rows, columns=["sid", "end_date", "filed_at", "investor", "pct"])
    ch = sleeves.holder_changes(h, "2026-08-01").set_index("sid")["change"].to_dict()
    assert ch == {"A": "new", "B": "up", "C": "unknown", "D": "down"}
    assert sleeves._fresh_buys(sleeves.holder_changes(h, "2026-08-01"), "2026-08-01") == {"A", "B"}
    before = sleeves.holder_changes(h, "2026-07-01").set_index("sid")["change"].to_dict()
    assert before == {"B": "unknown", "D": "unknown"}, "on 1 July only the March filings were public"
    assert sleeves._fresh_buys(sleeves.holder_changes(h, "2026-12-15"), "2026-12-15") == set(), "a July filing is stale by December"
    assert sleeves.followed_investor("ASHISH RAMESHCHANDRA KACHOLIA") == "Ashish Kacholia" and sleeves.followed_investor("Ankush Kedia") is None
