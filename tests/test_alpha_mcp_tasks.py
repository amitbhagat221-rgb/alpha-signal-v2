"""
The llm_tasks queue (plan 0016 phase 2) on a fresh schema-built DB: enqueue is
idempotent, claim leases atomically, submit validates server-side and ingests
through the producers' own save paths, duplicates copy the verdict, invalid
results stay claimable up to 3 attempts, expired or foreign leases write nothing,
rollback restores the prior state, and news ingest leaves image_url alone.
"""
import datetime as dt
import json

import pytest

import db


@pytest.fixture
def qdb(tmp_path, monkeypatch):
    path = tmp_path / "q.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    today = dt.date.today().isoformat()
    with db.get_db() as c:
        c.executemany(
            "INSERT INTO regulatory_events (event_id, title, summary, source, published_at, classifier_status) "
            "VALUES (?, ?, ?, 'test', ?, ?)",
            [("e1", "RBI hikes repo rate by 25 bps to curb inflation", "MPC decision", today, "pending"),
             ("e2", "RBI hikes repo rate by 25 bps to curb inflation", "syndicated copy", today, "pending"),
             ("e3", "Sensex closes higher on IT buying today", "market wrap", today, "haiku_passed_sonnet_failed"),
             ("e4", "Old already classified item about SEBI", "x", today, "classified")])
        c.executemany(
            "INSERT INTO news_articles (article_id, title, summary, source, published_at) VALUES (?, ?, ?, 'test', ?)",
            [("a1", "Infosys Q2 profit rises 12% to Rs 6,500 crore", "Revenue grew on deal wins.", today)])
        c.execute("INSERT INTO news_enriched (article_id, classifier_status, image_url) "
                  "VALUES ('a1', 'failed', 'img.jpg')")
    from alpha_mcp import tasks
    return tasks


REG_YES = {"is_regulatory": True, "stage": "implementation", "ministry": "RBI",
           "sectors_affected": [{"sector": "Financials", "direction": 1, "magnitude": "moderate",
                                 "time_horizon": "immediate", "confidence": "high",
                                 "reasoning": "higher rates widen bank margins"}]}
NEWS_OK = {"topics": ["earnings"], "one_liner": "Infosys profit rises", "why_it_matters": "IT demand holding up",
           "key_numbers": [{"label": "Profit", "value": "Rs 6,500 crore"}, {"label": "Invented", "value": "999"}],
           "what_to_watch": "Guidance", "confidence": "high", "sentiment": "bullish",
           "keywords": ["Infosys", "Q2 Results"]}


def test_enqueue_dedups_headlines_and_is_idempotent(qdb):
    first = qdb.enqueue("regulatory")
    assert first == {"kind": "regulatory", "exported": 2, "queued": 2}      # e1+e2 share a headline; e4 not claimable
    assert qdb.enqueue("regulatory")["queued"] == 0
    payload = json.loads(db.one("SELECT payload_json FROM llm_tasks WHERE item_key = 'e1'")["payload_json"])
    assert payload["_dups"] == ["e2"] and payload["title"] == {"untrusted_text": payload["title"]["untrusted_text"]}


def test_claim_submit_ingests_and_copies_to_duplicates(qdb):
    qdb.enqueue("regulatory")
    items = qdb.claim("regulatory", 10, worker="w1")
    assert len(items) == 2 and all("_dups" not in i["payload"] for i in items)
    assert qdb.claim("regulatory", 10, worker="w2") == []                   # leased
    by_key = {i["payload"]["event_id"]: i["task_id"] for i in items}
    out = qdb.submit([{"task_id": by_key["e1"], "result": REG_YES},
                      {"task_id": by_key["e3"], "result": {"is_regulatory": False}}], worker="w1")
    assert out["counts"] == {"done": 2}
    st = {r["event_id"]: r["classifier_status"] for r in db.rows("SELECT * FROM regulatory_events")}
    assert st == {"e1": "classified", "e2": "classified", "e3": "haiku_rejected", "e4": "classified"}
    assert db.scalar("SELECT COUNT(*) FROM regulatory_signals WHERE sector = 'Financials'") == 2
    assert qdb.submit([{"task_id": by_key["e1"], "result": REG_YES}], worker="w1")["counts"] == {"noop": 1}
    usage = db.rows("SELECT step, mode, n_calls FROM llm_usage")
    assert usage == [{"step": "classify_regulatory_deep", "mode": "local", "n_calls": 2}]


def test_invalid_result_stays_claimable_then_fails_after_three(qdb):
    qdb.enqueue("regulatory")
    bad = {"is_regulatory": True, "sectors_affected": [{"sector": "Banking", "direction": 1, "magnitude": "minor",
                                                        "time_horizon": "3mo", "confidence": "low"}]}
    for attempt in (1, 2, 3):
        items = qdb.claim("regulatory", 1, worker="w")
        assert items and items[0]["attempt"] == attempt
        out = qdb.submit([{"task_id": items[0]["task_id"], "result": bad}], worker="w")
        assert out["results"][0]["status"] == ("failed" if attempt == 3 else "invalid")
        assert "bad sector" in out["results"][0]["reasons"][0]
    assert db.scalar("SELECT status FROM llm_tasks WHERE task_id = ?", [items[0]["task_id"]]) == "failed"
    assert db.scalar("SELECT classifier_status FROM regulatory_events WHERE event_id = 'e1'") == "pending"


def test_foreign_or_expired_lease_writes_nothing(qdb):
    qdb.enqueue("regulatory")
    item = qdb.claim("regulatory", 1, worker="w1")[0]
    assert qdb.submit([{"task_id": item["task_id"], "result": REG_YES}], worker="w2")["counts"] == {"rejected": 1}
    with db.get_db() as c:
        c.execute("UPDATE llm_tasks SET lease_until = '2000-01-01T00:00:00' WHERE task_id = ?", (item["task_id"],))
    assert qdb.submit([{"task_id": item["task_id"], "result": REG_YES}], worker="w1")["counts"] == {"rejected": 1}
    assert db.scalar("SELECT COUNT(*) FROM regulatory_signals") == 0
    again = qdb.claim("regulatory", 5, worker="w3")                          # expired lease is reclaimed
    assert item["task_id"] in {i["task_id"] for i in again}


def test_rollback_restores_prior_state(qdb):
    qdb.enqueue("regulatory")
    for i in qdb.claim("regulatory", 10, worker="w"):
        qdb.submit([{"task_id": i["task_id"], "result": REG_YES}], worker="w")
    assert qdb.rollback("regulatory", "2000-01-01")["rolled_back"] == 2
    st = {r["event_id"]: r["classifier_status"] for r in db.rows("SELECT * FROM regulatory_events")}
    assert st == {"e1": "pending", "e2": "pending", "e3": "haiku_passed_sonnet_failed", "e4": "classified"}
    assert db.scalar("SELECT COUNT(*) FROM regulatory_signals") == 0
    assert qdb.retry("regulatory")["requeued"] == 2


def test_news_enrich_filters_invented_numbers_and_keeps_image_url(qdb):
    assert qdb.enqueue("news_enrich")["queued"] == 1
    item = qdb.claim("news_enrich", 5, worker="w")[0]
    assert item["payload"]["title"]["untrusted_text"].startswith("Infosys")
    out = qdb.submit([{"task_id": item["task_id"], "result": NEWS_OK}], worker="w")
    assert out["counts"] == {"done": 1}
    row = db.one("SELECT * FROM news_enriched WHERE article_id = 'a1'")
    assert row["classifier_status"] == "done" and row["image_url"] == "img.jpg"
    assert [k["value"] for k in json.loads(row["key_numbers"])] == ["Rs 6,500 crore"]   # 999 is not in the source
    assert qdb.rollback("news_enrich", "2000-01-01")["rolled_back"] == 1
    row = db.one("SELECT * FROM news_enriched WHERE article_id = 'a1'")
    assert row["classifier_status"] == "failed" and row["image_url"] == "img.jpg"


def test_news_validator_rejects_empty_fields(qdb):
    qdb.enqueue("news_enrich")
    item = qdb.claim("news_enrich", 1, worker="w")[0]
    out = qdb.submit([{"task_id": item["task_id"], "result": {**NEWS_OK, "one_liner": ""}}], worker="w")
    assert out["results"][0]["status"] == "invalid"


def test_queue_status_and_kinds_spec(qdb):
    qdb.enqueue("regulatory")
    qs = qdb.queue_status()["kinds"]
    assert qs["regulatory"]["counts"] == {"queued": 2}
    spec = qdb.kinds_spec()
    assert spec["drain_order"][-2:] == ["news_enrich", "regulatory"]
    assert spec["kinds"]["regulatory"]["claimable"] == 2 and "Financials" in spec["kinds"]["regulatory"]["instructions"]


def test_expired_lease_counts_as_claimable(qdb):
    qdb.enqueue("regulatory")
    for i in qdb.claim("regulatory", 10, worker="w"):
        with db.get_db() as c:
            c.execute("UPDATE llm_tasks SET lease_until = '2000-01-01T00:00:00' WHERE task_id = ?", (i["task_id"],))
    assert qdb.queue_status()["kinds"]["regulatory"]["expired_leases"] == 2
    assert qdb.kinds_spec()["kinds"]["regulatory"]["claimable"] == 2


# ── phase-3 prompt-backed kinds: validate → ingest → undo through the producers' own code ──

def test_dossier_kind_rejects_numbers_and_writes_the_days_file(qdb, tmp_path, monkeypatch):
    from output import dossier as od
    monkeypatch.setattr(od, "OUTPUT_DIR", tmp_path)
    with db.get_db() as c:
        c.execute("INSERT INTO stocks (sid, ticker, name, cap_tier, sector) VALUES ('RELI','RELIANCE','Reliance','LARGE','Energy')")
    k = qdb.TASK_KINDS["dossier"]
    payload = {"sid": "RELI", "ticker": "RELIANCE", "_day": "2026-10-01"}
    good = {"thesis": "Integrated energy major with a steady retail and digital engine.",
            "bull_case": ["Retail scale keeps widening", "Digital monetisation improving"],
            "bear_case": ["Refining margins are cyclical", "Capex intensity stays heavy"],
            "catalysts": ["New energy commissioning", "Tariff action in telecom"],
            "risks": ["Execution on new energy", "Commodity swings"], "conviction": "MEDIUM", "action": "WATCH"}
    with pytest.raises(ValueError, match="validator rejected"):
        k["validate"]({**good, "thesis": "Shares could rise 16.5% from here."}, payload)
    clean = k["validate"](good, payload)
    undo = k["ingest"](clean, payload)
    saved = json.loads((tmp_path / "dossiers_2026-10-01.json").read_text())
    assert saved[0]["sid"] == "RELI" and saved[0]["validation"]["ok"] and od.is_publishable(saved[0])
    k["undo"](undo)
    assert json.loads((tmp_path / "dossiers_2026-10-01.json").read_text()) == []


def test_sector_dossier_kind_persists_and_undoes(qdb):
    from output import sector_dossier as sd
    sd._ensure_schema()
    k = qdb.TASK_KINDS["sector_dossier"]
    payload = {"sector": "Energy", "snapshot_date": "2026-10-01"}
    good = {"thesis": "Policy-led capex keeps the sector constructive.", "bull_case": ["Grid build-out"],
            "bear_case": ["Crude volatility"], "tech_innovation_drivers": ["Green hydrogen"],
            "what_to_watch": [{"horizon": "S", "item": "Monsoon demand"}], "conviction": "MEDIUM"}
    with pytest.raises(ValueError, match="what_to_watch"):
        k["validate"]({**good, "what_to_watch": ["no horizon"]}, payload)
    with pytest.raises(ValueError, match="validator rejected"):
        k["validate"]({**good, "thesis": "Margins expand 12.5x."}, payload)
    undo = k["ingest"](k["validate"](good, payload), payload)
    row = db.one("SELECT * FROM sector_dossiers WHERE sector = 'Energy'")
    assert row["valid"] == 1 and row["model"] == qdb.SESSION_MODEL
    k["undo"](undo)
    assert not db.one("SELECT * FROM sector_dossiers WHERE sector = 'Energy'")


def test_news_brief_kind_persists_and_undoes(qdb):
    k = qdb.TASK_KINDS["news_brief"]
    payload = {"brief_date": "2026-10-01", "n_articles": 25}
    good = {"big_one": "RBI holds rates.", "five_fast": ["One", "Two"], "one_to_watch": "Monsoon.",
            "zoom_out": "Liquidity cycle."}
    with pytest.raises(ValueError):
        k["validate"]({**good, "five_fast": []}, payload)
    undo = k["ingest"](k["validate"](good, payload), payload)
    row = db.one("SELECT * FROM news_briefs WHERE brief_date = '2026-10-01'")
    assert row["big_one"] == "RBI holds rates." and json.loads(row["five_fast"]) == ["One", "Two"]
    k["undo"](undo)
    assert not db.one("SELECT * FROM news_briefs WHERE brief_date = '2026-10-01'")


def test_drain_order_puts_dossiers_first(qdb):
    assert qdb.DRAIN_ORDER == ["dossier", "news_brief", "sector_dossier", "news_enrich", "regulatory"]


def test_news_rollback_when_there_was_no_prior_row(qdb):
    with db.get_db() as c:
        c.execute("DELETE FROM news_enriched")
    qdb.enqueue("news_enrich")
    item = qdb.claim("news_enrich", 1, worker="w")[0]
    assert qdb.submit([{"task_id": item["task_id"], "result": NEWS_OK}], worker="w")["counts"] == {"done": 1}
    assert qdb.rollback("news_enrich", "2000-01-01")["rolled_back"] == 1
    assert not db.one("SELECT * FROM news_enriched WHERE article_id = 'a1'")
