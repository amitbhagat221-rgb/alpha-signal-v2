"""The multibagger thesis (plan 0026, ADR 0075): one pure function for live and backtest, and the desk's lists."""
import pathlib
import sqlite3

import numpy as np
import pandas as pd
import pytest

import db
from config import MB_THESIS
from output import mb_book
from signals import multibagger as mb

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "mb_thesis_anchor.parquet"
CR = 1e7


def _pct(s):
    return s.rank(pct=True)


def _reference_arm_b(g):
    """The ORIGINAL tools/mb_thesis.score arm-B code (before plan 0026 moved it into signals.multibagger.thesis),
    kept verbatim as the oracle."""
    g = g.copy()
    pond_a = (g["adtv"] >= 0.5 * CR) & (g["adtv_rank"] > 250)
    pond_b = (pond_a & g["survivor"] & (g["mcap_cr"] <= g["mcap_max"]) & (g["sales"] > 0)
              & ~g["red_flag"].astype("boolean").fillna(False).astype(bool))
    pb = g[pond_b]
    parts = pd.DataFrame(index=pb.index)
    parts["smallness"] = _pct(-np.log(pb["mcap_cr"]))
    parts["cheapness"] = pd.concat([_pct(pb["bp"]), _pct(pb["sp"]), _pct(pb["ep"])], axis=1).mean(axis=1)
    parts["price"] = (_pct(pb["mom_6m"]) + _pct(pb["pos_52w"])) / 2
    parts["business"] = pd.concat([_pct(pb["q_ebitda_chg"]), _pct(pb["q_rev_yoy"])], axis=1).mean(axis=1)
    parts["tailwind"] = _pct(pb.groupby("industry")["mom_6m"].transform("median"))
    row_mean = parts.mean(axis=1)
    parts = parts.apply(lambda c: c.fillna(row_mean))
    return pond_b, parts, parts.mean(axis=1)


def test_golden_stored_anchor_reproduces_the_backtest_scores():
    g = pd.read_parquet(FIXTURE)
    pond, parts, score = _reference_arm_b(g)
    assert pond.sum() > 300
    t = mb.thesis(g, min_pond=100)
    assert (t["thesis_pond"] == pond).all()
    assert np.allclose(t.loc[pond, mb.PARTS].values, parts[mb.PARTS].values, rtol=0, atol=1e-12)
    assert np.allclose(t.loc[pond, "thesis_score"], score, rtol=0, atol=1e-12)
    assert t.loc[~pond, "thesis_score"].isna().all()
    # rank 1 = best, within the pond only
    assert t["thesis_rank"].min() == 1 and t["thesis_rank"].notna().sum() == pond.sum()
    # and the research tool's score() is that same function
    from tools import mb_thesis
    s = mb_thesis.score(g.assign(anchor="2025-10-01", roce=np.nan, de=np.nan, pat_cagr_3y=np.nan))
    assert np.allclose(s["score_b"].values[pond.values], score.values, rtol=0, atol=1e-12)


def _frame(n=8, **over):
    """A tidy pond: every stock passes every gate, with distinct inputs."""
    i = np.arange(1, n + 1)
    f = pd.DataFrame({"adtv": 1.0 * CR, "adtv_rank": 300.0 + i, "mcap_cr": 500.0 * i, "bp": 0.1 * i, "sp": 0.2 * i,
                      "ep": 0.01 * i, "sales": 100.0, "mom_6m": 0.05 * i, "pos_52w": 0.1 * i,
                      "q_ebitda_chg": 0.01 * i, "q_rev_yoy": 0.02 * i, "industry": list("AABBCCDD")[:n],
                      "red_flag": False, "pledge_pct": 10.0, "gsm": False}, index=[f"S{k}" for k in i])
    for k, v in over.items():
        f[k] = v
    return f


@pytest.mark.parametrize("col,bad,reason", [
    ("adtv", 0.4 * CR, "adtv"),
    ("adtv_rank", 250.0, "adtv_rank"),                  # inside the 250 most liquid
    ("mcap_cr", 5001.0, "mcap"),
    ("mcap_cr", np.nan, "mcap"),                        # no market cap = not buyable
    ("sales", 0.0, "sales"),
    ("sales", np.nan, "sales"),
    ("red_flag", True, "red_flag"),
    ("pledge_pct", 50.1, "pledge"),
    ("gsm", True, "gsm"),
])
def test_each_gate_fails_with_its_reason(col, bad, reason):
    f = _frame()
    f.loc["S3", col] = bad
    t = mb.thesis(f)
    assert not t.loc["S3", "thesis_pond"] and t.loc["S3", "thesis_gate_fail"] == reason
    assert t.loc[t.index != "S3", "thesis_pond"].all()
    assert t.loc["S3", ["thesis_score", "thesis_rank"]].isna().all()
    assert (t.loc[t.index != "S3", "thesis_gate_fail"] == "").all()


def test_boundaries_pass_and_missing_pledge_passes():
    f = _frame()
    f.loc["S1", "adtv"] = 0.5 * CR                     # exactly the floor
    f.loc["S2", "mcap_cr"] = 5000.0                    # exactly the cap
    f.loc["S3", "pledge_pct"] = 50.0
    f.loc["S4", "pledge_pct"] = np.nan                 # no shareholding row: absence is not a red flag
    assert mb.thesis(f)["thesis_pond"].all()
    assert MB_THESIS["mcap_max_cr"] == 5000 and MB_THESIS["pledge_max_pct"] == 50.0


def test_several_failures_are_all_listed():
    f = _frame()
    f.loc["S5", ["sales", "gsm"]] = [0.0, True]
    assert mb.thesis(f).loc["S5", "thesis_gate_fail"] == "sales,gsm"


def test_missing_part_is_the_mean_of_the_others():
    f = _frame()
    f.loc["S4", ["q_ebitda_chg", "q_rev_yoy"]] = np.nan          # no business part
    t = mb.thesis(f)
    others = t.loc["S4", ["smallness", "cheapness", "price", "tailwind"]].astype(float)
    assert t.loc["S4", "business"] == pytest.approx(others.mean())
    assert t.loc["S4", "thesis_score"] == pytest.approx(others.mean())     # the fill leaves the mean unchanged


def test_tailwind_is_the_percentile_of_the_industry_median_inside_the_pond():
    f = _frame()
    f.loc["S8", "gsm"] = True                                     # D has S7 (0.35) and S8 (0.4): S8 leaves the pond
    t = mb.thesis(f)
    med = f[t["thesis_pond"]].groupby("industry")["mom_6m"].median()      # A .075, B .175, C .275, D .35
    expect = f.loc[t["thesis_pond"], "industry"].map(med).rank(pct=True)        # a stock-level percentile of its industry median
    for s, ind in f["industry"].items():
        if t.loc[s, "thesis_pond"]:
            assert t.loc[s, "tailwind"] == pytest.approx(expect[s])
    assert expect["S7"] == 1.0 and expect["S1"] == expect["S2"]       # D (S7) has the highest industry median; A is shared


def test_smallness_and_cheapness_orient_correctly():
    t = mb.thesis(_frame())
    assert t["smallness"].idxmax() == "S1" and t["smallness"].idxmin() == "S8"      # smaller cap = higher
    assert t["cheapness"].idxmax() == "S8"                                           # higher book/sales/earnings to price


def test_min_pond_withholds_scores_but_keeps_the_flag():
    t = mb.thesis(_frame(), min_pond=100)
    assert t["thesis_pond"].all() and t["thesis_score"].isna().all()


def test_stage_top100_marks_only_the_best(monkeypatch):
    monkeypatch.setitem(MB_THESIS, "top_n", 3)
    f = _frame()
    monkeypatch.setattr(mb, "live_frame", lambda as_of=None: _with_attrs(f))
    tt, _ = mb.thesis_table()
    assert (tt["thesis_stage"] == "top100").sum() == 3 and (tt["thesis_stage"] == "pond").sum() == 5
    best = tt.sort_values("thesis_rank").head(3)
    assert (best["thesis_stage"] == "top100").all()
    assert set(tt.columns) >= set(mb.THESIS_COLS)


def _with_attrs(f):
    f = f.copy()
    f.attrs.update(price_date="2026-10-15", last_bse="2026-10-15")
    return f


def test_empty_pond_is_a_failure(monkeypatch):
    monkeypatch.setattr(mb, "live_frame", lambda as_of=None: _with_attrs(_frame(sales=0.0)))
    with pytest.raises(RuntimeError, match="empty pond"):
        mb.thesis_table()


# ───────────────────────── the lists ─────────────────────────

@pytest.fixture()
def book(tmp_path, monkeypatch):
    path = tmp_path / "alpha_signal.db"
    conn = sqlite3.connect(path)
    conn.executescript(db.SCHEMA_PATH.read_text())
    conn.executemany("INSERT INTO stocks (sid, ticker, name, cap_tier) VALUES (?, ?, 'n', 'SMALL')",
                     [(f"S{k:02d}", f"T{k:02d}") for k in range(40)])
    conn.execute("INSERT INTO stock_prices (sid, date, close, source) VALUES ('S00', '2026-10-14', 123.4, 'nse')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    return path


def _log(path):
    c = sqlite3.connect(path)
    rows = c.execute("SELECT sid, action, from_status, to_status, reason, actor FROM multibagger_book_log ORDER BY id").fetchall()
    c.close()
    return rows


def test_candidate_hold_drop_each_write_one_log_row(book):
    mb_book.add_candidate("S00", "a small cheap name", "top of the list", actor="amit")
    mb_book.hold("S00", "bought", actor="amit")
    mb_book.drop("S00", "thesis broke", actor="amit")
    assert _log(book) == [("S00", "add_candidate", None, "candidate", "top of the list", "amit"),
                          ("S00", "hold", "candidate", "held", "bought", "amit"),
                          ("S00", "drop", "held", "dropped", "thesis broke", "amit")]
    b = mb_book.list_book().set_index("sid")
    assert b.loc["S00", "status"] == "dropped" and b.loc["S00", "reason"] == "thesis broke"
    assert b.loc["S00", "thesis_line"] == "a small cheap name"


def test_hold_requires_a_candidate_and_records_entry(book):
    with pytest.raises(ValueError, match="only a candidate"):
        mb_book.hold("S00", "straight to held")
    assert _log(book) == [] and mb_book.list_book().empty
    mb_book.add_candidate("S00", "line", "why")
    mb_book.hold("S00", "buy")                                       # entry price defaults to the last close
    row = mb_book.list_book("held").iloc[0]
    assert row["entry_price"] == pytest.approx(123.4) and row["entry_date"]
    mb_book.drop("S00", "out")
    with pytest.raises(ValueError, match="only a candidate"):
        mb_book.hold("S00", "a dropped name cannot jump to held")
    mb_book.add_candidate("S00", "line again", "second look")        # but may be re-added
    assert mb_book.list_book().iloc[0]["status"] == "candidate"


def test_the_book_is_capped_at_30_and_held_at_10(book):
    for k in range(30):
        mb_book.add_candidate(f"S{k:02d}", "line", "why")
    with pytest.raises(ValueError, match="full"):
        mb_book.add_candidate("S30", "line", "why")
    for k in range(10):
        mb_book.hold(f"S{k:02d}", "buy", entry_price=10.0)
    with pytest.raises(ValueError, match="already held"):
        mb_book.hold("S10", "buy", entry_price=10.0)
    assert len(_log(book)) == 40                                     # the refused changes wrote nothing
    mb_book.drop("S29", "making room")
    mb_book.add_candidate("S30", "line", "room now")                 # a dropped name frees a slot
    assert len(mb_book.list_book("candidate")) == 20 and len(mb_book.list_book("held")) == 10


def test_bad_input_changes_nothing(book):
    for call in (lambda: mb_book.add_candidate("NOPE", "line", "why"),          # not a universe sid
                 lambda: mb_book.add_candidate("S00", "", "why"),
                 lambda: mb_book.add_candidate("S00", "line", "  "),
                 lambda: mb_book.drop("S00", "never added")):
        with pytest.raises(ValueError):
            call()
    mb_book.add_candidate("S00", "line", "why")
    with pytest.raises(ValueError, match="already candidate"):
        mb_book.add_candidate("S00", "line", "again")
    assert len(_log(book)) == 1 and len(mb_book.list_book()) == 1
