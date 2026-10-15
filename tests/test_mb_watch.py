"""Plan 0026 phase 4: per-name event watch and the stage-3 evidence card (signals/mb_watch.py).

DB-dependent tests read the live DB read-only and skip when it is absent."""
import sqlite3

import pandas as pd
import pytest

import config
from signals import mb_watch

DB_OK = config.DB_PATH.exists()
needs_db = pytest.mark.skipif(not DB_OK, reason="alpha_signal.db not present")


@pytest.fixture(scope="module")
def conn():
    c = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    yield c
    c.close()


def test_category_map_values_valid():
    for sub, (cat, sev) in config.BSE_ANNOUNCEMENT_CATEGORIES.items():
        assert cat in config.WATCH_CATEGORIES, sub
        assert sev in config.WATCH_SEVERITY, sub


def test_superinvestors_copied_from_frozen_tool():
    # parse the literal: importing the tool needs data files a worktree lacks
    import ast
    from pathlib import Path
    tree = ast.parse((Path(config.PROJECT_ROOT) / "tools" / "mb_thesis_v2.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.Assign) and n.targets[0].id == "SI_NAMES")
    assert config.SUPERINVESTORS == ast.literal_eval(node.value)


@needs_db
def test_category_map_covers_every_subcategory_over_500_rows(conn):
    rows = conn.execute("SELECT subcategory, COUNT(*) FROM bse_announcements WHERE subcategory IS NOT NULL "
                        "GROUP BY 1 HAVING COUNT(*) >= 500").fetchall()
    assert len(rows) > 50
    missing = [s for s, _ in rows if s not in config.BSE_ANNOUNCEMENT_CATEGORIES]
    assert not missing, missing


@needs_db
@pytest.mark.parametrize("sid", ["KEIN", "GRSE", "TEJS"])
def test_timeline_real_names(conn, sid):
    t = mb_watch.timeline(sid, conn=conn)
    assert list(t.columns) == mb_watch.COLUMNS
    assert t["source"].nunique() >= 4
    assert t["date"].notna().all()
    assert t["date"].is_monotonic_decreasing
    assert set(t["category"]) <= set(config.WATCH_CATEGORIES)
    assert set(t["severity"]) <= set(config.WATCH_SEVERITY)
    assert all(isinstance(d, dict) for d in t["detail"])


@needs_db
def test_timeline_since_filters(conn):
    t = mb_watch.timeline("TEJS", since="2026-01-01", conn=conn)
    assert len(t) and (t["date"] >= pd.Timestamp("2026-01-01")).all()


@needs_db
def test_superinvestor_entry_detected_tejas_kedia_2020(conn):
    t = mb_watch.timeline("TEJS", since="2020-06-01", conn=conn)
    hit = t[(t["source"] == "shareholding_holders") & (t["detail"].map(lambda d: d.get("investor") == "Vijay Kedia"
                                                                      and d.get("event") == "entry"))]
    hit = hit[hit["detail"].map(lambda d: d["end_date"] == "2020-06-30")]
    assert len(hit) == 1
    row = hit.iloc[0]
    assert row["severity"] == "high" and row["detail"]["pct"] >= 1.0


@needs_db
def test_card_keys_stable(conn):
    keys = None
    for sid in ("TEJS", "GRSE", "KEIN"):
        c = mb_watch.card(sid, conn=conn)
        assert list(c) == mb_watch.CARD_KEYS
        assert set(c["events_90d"]) == set(config.WATCH_CATEGORIES)
        assert len(c["top_events_90d"]) <= 3
        keys = keys or list(c["valuation_position"])
        assert list(c["valuation_position"]) == keys
    assert c["results"]["period"]


@needs_db
def test_govt_links_grse(conn):
    g = mb_watch.govt_links("GRSE", conn=conn)
    assert any("PRESIDENT OF INDIA" in h["holder_name"].upper() for h in g["govt_holders"])
    assert g["electoral_bond_donor"] == {"flag": None, "basis": "not loaded"}


@needs_db
def test_new_since_only_medium_plus(conn):
    n = mb_watch.new_since(["TEJS", "GRSE"], "2026-08-01", conn=conn)
    assert len(n)
    assert (n["date"] > pd.Timestamp("2026-08-01")).all()
    assert n["severity"].isin(["medium", "high"]).all()
    assert list(n.columns) == ["sid"] + mb_watch.COLUMNS
