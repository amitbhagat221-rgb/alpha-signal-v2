"""
Data model v3 — daily old-vs-new parity (ADR 0054; the reconciliation week).

For every legacy table: the row count (and, for numbers, the value checksum) in the
legacy table vs its v3 representation, as the sync maps it. One check_results row
per table per day (check 'datamodel_parity'); retired tables are listed as RETIRED
with the reason. Exit 1 if any table is FAIL, so `run.sh` surfaces it.

    python -m datamodel.reconcile            # run + record today's parity
    python -m datamodel.reconcile --show     # print the last 7 days, no write
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from datamodel.sync import (EVENT_SPECS, FEATURE_SKIP, FEATURE_TABLES, MEMBERSHIP, SEC, TIER_TO_CLS, TODAY, cat_ensure, cat_ids,  # noqa: E402
                            coltypes, cols, connect, ensure_schema, exists, q, tx)

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
RTOL = 1e-9

# legacy tables with no v3 target, and why (plan 0017 §3 / census)
RETIRED = {
    "event_calendar": "hand-loaded once 2026-07-11, no scheduled writer, no reader",
    "sector_policy_pit": "hindsight-curated list, no reader",
    "paper_positions": "only writer is _archive/paper_portfolio.py", "paper_trades": "only writer is _archive/paper_portfolio.py",
    "paper_nav_history": "only writer is _archive/paper_portfolio.py",
    "pit_ic_by_tier_v1": "same evidence is in pit_ic_by_tier_v2 source='v1_archive' → factor_tests",
    "uhs_calibration_log": "pure join of pick_outcomes × daily_picks → a view over outcomes ⋈ picks",
    "external_anchors": "copy of stock_prices; gate 7 can never fire (D4)",
    "signal_lineage": "2 of ~105 factors emit it (D3)",
    "vix_history": "copy of macro_history india_vix → series_values",
    "daily_changes": "derivable: picks of a run vs the previous run (a view)",
    "symbol_changes": "kept as-is: plan 0020 NSE symbol renames (old → new), an identifier history for entities",
    "stock_prices_unlisted": "kept as-is: plan 0020 prices of symbols with no entity (delisted / outside the universe); "
                             "joins bars_daily once entities carry them",
    "llm_usage": "kept as-is: it is already the v3 table",
    "run_events": "kept as-is: plan 0018 run log (Ops)",
    "llm_tasks": "kept as-is: plan 0016 LLM work queue (Ops, already v3-shaped)",
    "news_themes": "kept as-is: plan 0021 theme notes (D3: text moves to documents with the rest of news)",
    "news_theme_articles": "kept as-is: plan 0021 headline-to-theme links",
    "news_theme_history": "kept as-is: plan 0021 theme timeline",
    "news_today": "kept as-is: plan 0021 daily edition",
    "news_week": "kept as-is: plan 0021 weekly edition",
    "mcp_calls": "kept as-is: plan 0016 MCP audit log (Ops)",
    "sqlite_sequence": "SQLite internal",
}


def _one(c, sql):
    r = c.execute(sql).fetchone()
    return tuple(r) if r else (None,)


def _close(a, b):
    if a is None and b is None:        # a count-only check
        return True
    a, b = a or 0.0, b or 0.0          # SUM over no rows is NULL
    return abs(a - b) <= RTOL * max(1.0, abs(a), abs(b))


def checks(c):
    """Yield (legacy_table, old_count, new_count, old_sum, new_sum, note)."""
    ids = lambda k: cat_ids(c, k)
    # reference
    yield ("stocks", *_one(c, "SELECT COUNT(*) FROM stocks"),
           *_one(c, "SELECT COUNT(*) FROM entities e JOIN stocks s ON e.kind='security' AND e.market='IN' AND e.key=s.sid"), None, None,
           "entities(security)")
    mism = _one(c, f"""SELECT COUNT(*) FROM stocks s JOIN entities e ON {SEC}=s.sid
        LEFT JOIN classifications k ON k.entity_id=e.entity_id AND k.scheme='tier' AND k.valid_to IS NULL
        WHERE s.cap_tier IS NOT NULL AND k.value IS NOT s.cap_tier""")[0]
    yield ("stocks.cap_tier", *_one(c, "SELECT COUNT(*) FROM stocks WHERE cap_tier IS NOT NULL"),
           *_one(c, "SELECT COUNT(*) FROM classifications WHERE scheme='tier' AND valid_to IS NULL"), 0, mism,
           "open tier rows; checksum = stocks whose open tier differs")
    yield ("stocks.market_cap_cr+adtv_6m_cr", *_one(c, "SELECT COUNT(market_cap_cr) + COUNT(adtv_6m_cr) FROM stocks"),
           *_one(c, "SELECT COUNT(attrs ->> '$.market_cap_cr') + COUNT(attrs ->> '$.adtv_6m_cr') FROM entities WHERE kind='security'"),
           *_one(c, "SELECT COALESCE(SUM(market_cap_cr),0) + COALESCE(SUM(adtv_6m_cr),0) FROM stocks"),
           *_one(c, "SELECT COALESCE(SUM(attrs ->> '$.market_cap_cr'),0) + COALESCE(SUM(attrs ->> '$.adtv_6m_cr'),0) FROM entities WHERE kind='security'"),
           "every other stocks column rides in entities.attrs")
    yield ("scrip_master", *_one(c, "SELECT COUNT(*) FROM scrip_master"),
           *_one(c, "SELECT COUNT(*) FROM identifiers WHERE namespace='bse_scrip' AND valid_to IS NULL"), None, None,
           "row for row → identifiers(bse_scrip), attrs = the row")
    yield ("historical_universe", *_one(c, "SELECT COUNT(*) FROM historical_universe"),
           *_one(c, "SELECT COUNT(*) FROM bars_daily WHERE source='historical_universe'"),
           *_one(c, "SELECT SUM(close) FROM historical_universe"), *_one(c, "SELECT SUM(close) FROM bars_daily WHERE source='historical_universe'"),
           "row for row → bars_daily; dead names → entities 'NSE:<symbol>'")
    # bars
    yield ("stock_prices", *_one(c, f"SELECT COUNT(*) FROM stock_prices p JOIN entities e ON {SEC}=p.sid"),
           *_one(c, "SELECT COUNT(*) FROM bars_daily WHERE source NOT IN ('nse_index', 'historical_universe')"),
           *_one(c, f"SELECT SUM(close) FROM stock_prices p JOIN entities e ON {SEC}=p.sid"),
           *_one(c, "SELECT SUM(close) FROM bars_daily WHERE source NOT IN ('nse_index', 'historical_universe')"), "")
    yield ("nse_index_history", *_one(c, "SELECT COUNT(*) FROM nse_index_history"),
           *_one(c, "SELECT COUNT(*) FROM bars_daily WHERE source = 'nse_index'"),
           *_one(c, "SELECT SUM(close) FROM nse_index_history"), *_one(c, "SELECT SUM(close) FROM bars_daily WHERE source = 'nse_index'"), "")
    yield ("fno_bhav", *_one(c, """SELECT COUNT(*) FROM (SELECT 1 FROM fno_bhav GROUP BY symbol, instrument_type, expiry_date,
               COALESCE(strike, 0), COALESCE(option_type, ''), trade_date)"""),
           *_one(c, "SELECT COUNT(*) FROM derivative_bars"), None, None, "distinct grid keys (futures collapse on NULL strike/type)")
    # series / facts / estimates: latest version per key vs the legacy cells
    lv = lambda t, keys: f"""(SELECT x.* FROM {t} x JOIN (SELECT {keys}, MAX(fetched_at) mf FROM {t} GROUP BY {keys}) m
                              USING ({keys}) WHERE x.fetched_at = m.mf)"""
    s_lv = lv("series_values", "series_id, date")
    old_n = old_s = 0
    for x in ("value", "yoy_change", "mom_change"):
        n, sm = _one(c, f"SELECT COUNT({x}), SUM({x}) FROM macro_history")
        old_n += n; old_s += sm or 0
    for t, skip in (("fii_dii_cash_flow", {"flow_date", "category"}), ("fii_dii_positioning", {"trade_date", "client_type"})):
        for x, ty in coltypes(c, t).items():
            if x not in skip and ty in ("REAL", "INTEGER"):
                n, sm = _one(c, f"SELECT COUNT({x}), SUM({x}) FROM {t}")
                old_n += n; old_s += sm or 0
    yield ("macro_history+fii_dii_cash_flow+fii_dii_positioning", old_n, *_one(c, f"SELECT COUNT(value) FROM {s_lv}"), old_s,
           *_one(c, f"SELECT SUM(value) FROM {s_lv}"), "latest version per (series, date)")
    yield ("macro_indicator_meta", *_one(c, "SELECT COUNT(*) FROM macro_indicator_meta"),
           *_one(c, "SELECT COUNT(*) FROM catalog WHERE kind='series' AND json_extract(spec, '$.meta') IS NOT NULL"), None, None,
           "catalog series spec.meta")
    yield ("macro_sector_map", *_one(c, "SELECT COUNT(*) FROM macro_sector_map"),
           *_one(c, "SELECT COALESCE(SUM(json_array_length(spec, '$.sector_map')), 0) FROM catalog WHERE kind='series'"),
           *_one(c, "SELECT SUM(weight) FROM macro_sector_map"),
           *_one(c, "SELECT SUM(j.value ->> '$.weight') FROM catalog, json_each(catalog.spec, '$.sector_map') j WHERE kind='series'"),
           "catalog series spec.sector_map")
    f_lv = lv("fundamentals", "entity_id, metric_id, period_end, period_type, basis, source")
    for t, pe, skip in (("quarterly_income", "end_date", {"period"}), ("annual_balance_sheet", "end_date", {"period"}),
                        ("annual_cash_flow", "end_date", {"period"}), ("banking_metrics", "period_end", set()),
                        ("shareholding", "end_date", set())):
        on = on_s = 0
        for x, ty in coltypes(c, t).items():
            if x in skip | {"sid", pe} or ty not in ("REAL", "INTEGER"):
                continue
            n, sm = _one(c, f"SELECT COUNT(t.{x}), SUM(t.{x}) FROM {t} t JOIN entities e ON {SEC}=t.sid WHERE t.{pe} IS NOT NULL")
            on += n; on_s += sm or 0
        yield (t, on, *_one(c, f"SELECT COUNT(value) FROM {f_lv} WHERE source='{t}'"), on_s,
               *_one(c, f"SELECT SUM(value) FROM {f_lv} WHERE source='{t}'"), "non-null cells vs latest versions")
    yield ("fundamentals_screener", *_one(c, f"SELECT COUNT(value) FROM fundamentals_screener t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, f"SELECT COUNT(value) FROM {f_lv} WHERE source='fundamentals_screener'"),
           *_one(c, f"SELECT SUM(value) FROM fundamentals_screener t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, f"SELECT SUM(value) FROM {f_lv} WHERE source='fundamentals_screener'"), "")
    e_lv = lv("estimates", "entity_id, metric_id, target_period, source")
    ac = {x: ty for x, ty in coltypes(c, "analyst_consensus").items() if x not in ("sid", "fetched_at")}
    yield ("analyst_consensus", sum(_one(c, f"SELECT COUNT({x}) FROM analyst_consensus t JOIN entities e ON {SEC}=t.sid")[0] for x in ac),
           *_one(c, f"SELECT COUNT(*) FROM {e_lv} WHERE source='analyst_consensus'"),
           sum(_one(c, f"SELECT COALESCE(SUM({x}),0) FROM analyst_consensus t JOIN entities e ON {SEC}=t.sid")[0]
               for x, ty in ac.items() if ty in ("REAL", "INTEGER")),
           *_one(c, f"SELECT SUM(value) FROM {e_lv} WHERE source='analyst_consensus'"), "non-null cells vs latest versions")
    yield ("forecast_history", *_one(c, f"SELECT COUNT(*) + COUNT(change) FROM forecast_history t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, f"SELECT COUNT(*) FROM {e_lv} WHERE source='forecast_history'"),
           *_one(c, f"SELECT COALESCE(SUM(value),0) + COALESCE(SUM(change),0) FROM forecast_history t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, f"SELECT SUM(value) FROM {e_lv} WHERE source='forecast_history'"), "value + change as two metrics")
    acs = [x for x in cols(c, "analyst_consensus_snapshots") if x not in ("sid", "snapshot_date", "source", "fetched_at")]
    yield ("analyst_consensus_snapshots",
           sum(_one(c, f"SELECT COUNT({x}) FROM analyst_consensus_snapshots t JOIN entities e ON {SEC}=t.sid")[0] for x in acs),
           *_one(c, "SELECT COUNT(*) FROM estimates WHERE source LIKE 'acs:%'"), None, None, "every snapshot kept (as_of)")
    yield ("analyst_estimates", *_one(c, f"SELECT COUNT(*) FROM analyst_estimates t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, "SELECT COUNT(*) FROM estimates WHERE source LIKE 'ae:%'"),
           *_one(c, f"SELECT SUM(value) FROM analyst_estimates t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, "SELECT SUM(value) FROM estimates WHERE source LIKE 'ae:%'"), "")
    # events
    et = ids("event_type")
    for t, spec in EVENT_SPECS.items():
        if exists(c, t):
            yield (t, *_one(c, f"SELECT COUNT(*) FROM {t}"), *_one(c, f"SELECT COUNT(*) FROM events WHERE source='{t}' AND type_id={et[spec[0]]}"),
                   None, None, "")
    yield ("market_events", *_one(c, "SELECT COUNT(*) FROM market_events"),
           *_one(c, "SELECT COUNT(*) FROM events WHERE source IN (SELECT DISTINCT source FROM market_events) "
                    "AND type_id IN (SELECT catalog_id FROM catalog WHERE kind='event_type' AND name IN (SELECT DISTINCT type FROM market_events))"),
           None, None, "")
    yield ("corporate_adjustments", *_one(c, f"SELECT COUNT(*) FROM corporate_adjustments t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, f"SELECT COUNT(*) FROM events WHERE type_id={et['price_adjustment']}"),
           *_one(c, f"SELECT SUM(factor) FROM corporate_adjustments t JOIN entities e ON {SEC}=t.sid"),
           *_one(c, f"SELECT SUM(payload ->> '$.factor') FROM events WHERE type_id={et['price_adjustment']}"), "derived, replaced daily")
    yield ("news_article_stocks", *_one(c, f"""SELECT COUNT(*) FROM news_article_stocks n JOIN entities e ON {SEC}=n.sid
               WHERE n.article_id IN (SELECT article_id FROM news_articles)"""),
           *_one(c, "SELECT COUNT(*) FROM event_links"), None, None, "")
    # documents: distinct keys vs latest valid/invalid versions
    dt = ids("doc_type")
    for t, dtype, keys, extra in (("transcripts", "transcript", "source_url", ""), ("news_enriched", "news_classification", "article_id", ""),
                                  ("regulatory_signals", "regulatory_classification", "event_id || '|' || sector", ""),
                                  ("regulatory_events", "regulatory_text", "event_id", "WHERE full_text IS NOT NULL AND full_text <> ''"),
                                  ("news_briefs", "news_brief", "brief_date", ""),
                                  ("sector_dossiers", "sector_dossier", "sector || '|' || snapshot_date", ""),
                                  ("sector_metadata", "sector_metadata", "sector || '|' || source", "")):
        if exists(c, t) and dtype in dt:
            yield (t, *_one(c, f"SELECT COUNT(DISTINCT {keys}) FROM {t} {extra}"),
                   *_one(c, f"SELECT COUNT(DISTINCT source_key) FROM documents WHERE type_id={dt[dtype]} AND status <> 'superseded'"),
                   None, None, "")
    # features: raw non-null cells vs feature rows (a key collapse fails); free text vs its documents; panel membership
    fs = {}
    for fid, spec in c.execute("SELECT catalog_id, json_extract(spec, '$.origin_table') FROM catalog WHERE kind='feature'"):
        if spec:
            fs.setdefault(spec, []).append(fid)
    dts = cat_ids(c, "doc_type")
    for t, (ecol, ekind, dcol, split, mode) in FEATURE_TABLES.items():
        if not exists(c, t):
            continue
        ct = coltypes(c, t)
        key = {x for x in (ecol or "").split("|") if x} | {dcol} | ({split} if split else set())
        text_docs = {k.split(".", 1)[1] for k in dts if k.startswith(t + ".")}
        vals = [x for x in ct if x not in key and x not in FEATURE_SKIP and (t, x) not in TIER_TO_CLS and x not in text_docs
                and x not in ("sid", "symbol")]
        ej = ("JOIN entities e ON " + (f"{SEC}=t.sid" if ekind == "security" else
              "e.market='IN' AND ((t.sid IS NOT NULL AND e.kind='security' AND e.key=t.sid) OR (t.sid IS NULL AND e.kind='index' AND e.key='FNO:' || t.symbol))"
              if ekind == "security|index" else f"e.kind='sector' AND e.market='IN' AND e.key=t.{ecol}" if ekind == "sector"
              else "e.kind='market' AND e.key='IN'"))
        old = _one(c, f"SELECT {' + '.join(f'COUNT(t.{q(x)})' for x in vals) or '0'} FROM {t} t {ej} WHERE t.{dcol} IS NOT NULL")[0]
        if t in MEMBERSHIP:
            old += _one(c, f"SELECT COUNT(*) FROM {t} t {ej} WHERE t.{dcol} IS NOT NULL")[0]
        new_ids = ",".join(map(str, fs.get(t, [-1])))
        num_sum = " + ".join(f"COALESCE(SUM(t.{q(x)}),0)" for x in vals if ct[x] in ("REAL", "INTEGER")) or "0"
        yield (t, old, *_one(c, f"SELECT COUNT(*) FROM feature_values WHERE feature_id IN ({new_ids})"), None, None,
               f"{len(vals)} value cols{' + membership' if t in MEMBERSHIP else ''}; raw non-null cells")
        if text_docs:
            yield (f"{t}.text", _one(c, f"SELECT {' + '.join(f'COUNT(t.{q(x)})' for x in sorted(text_docs))} FROM {t} t {ej} WHERE t.{dcol} IS NOT NULL")[0],
                   _one(c, f"SELECT COUNT(*) FROM documents WHERE type_id IN ({','.join(str(dts[t + '.' + x]) for x in text_docs)}) AND status <> 'superseded'")[0],
                   None, None, f"free text → documents: {sorted(text_docs)}")
    # decisions
    yield ("daily_picks", *_one(c, f"SELECT COUNT(*) FROM daily_picks d JOIN entities e ON {SEC}=d.sid"),
           *_one(c, "SELECT COUNT(*) FROM picks p JOIN runs r USING (run_id) WHERE r.kind='morning'"),
           *_one(c, f"SELECT SUM(final_score) FROM daily_picks d JOIN entities e ON {SEC}=d.sid"),
           *_one(c, "SELECT SUM(score) FROM picks p JOIN runs r USING (run_id) WHERE r.kind='morning'"), "")
    yield ("portfolio_weights", *_one(c, "SELECT COUNT(*) FROM portfolio_weights"), *_one(c, "SELECT COUNT(*) FROM book_weights"),
           *_one(c, "SELECT SUM(weight) FROM portfolio_weights"), *_one(c, "SELECT SUM(weight) FROM book_weights"), "")
    yield ("pick_outcomes+portfolio_outcomes",
           _one(c, f"SELECT COUNT(*) FROM pick_outcomes d JOIN entities e ON {SEC}=d.sid")[0] + _one(c, "SELECT COUNT(*) FROM portfolio_outcomes")[0],
           *_one(c, "SELECT COUNT(*) FROM outcomes"),
           (_one(c, f"SELECT COALESCE(SUM(fwd_return_pct),0) FROM pick_outcomes d JOIN entities e ON {SEC}=d.sid")[0]
            + _one(c, "SELECT COALESCE(SUM(hrp_return_pct),0) FROM portfolio_outcomes")[0]),
           *_one(c, "SELECT SUM(ret) FROM outcomes"), "")
    worst = _one(c, """SELECT MAX(ABS(s - (p.attrs ->> '$.base_score'))) FROM
        (SELECT run_id, entity_id, SUM(contribution) s FROM pick_contributions GROUP BY run_id, entity_id) x
        JOIN picks p USING (run_id, entity_id) WHERE p.attrs ->> '$.base_score' IS NOT NULL""")[0]
    n_runs = _one(c, "SELECT COUNT(DISTINCT run_id) FROM pick_contributions")[0]
    yield ("pit_replay_snapshots", *_one(c, f"SELECT COUNT(*) FROM pit_replay_snapshots p JOIN entities e ON {SEC}=p.sid"),
           *_one(c, f"SELECT COUNT(*) FROM documents WHERE type_id={dts.get('pit_replay', -1)} AND status <> 'superseded'"), None, None,
           "row for row → documents(pit_replay): exact frozen inputs + outputs")
    yield ("pit_replay_snapshots.contributions", *_one(c, "SELECT COUNT(DISTINCT snapshot_date) FROM pit_replay_snapshots"),
           *_one(c, "SELECT COUNT(*) FROM runs WHERE kind='morning' AND json_extract(attrs, '$.contrib_match') IS NOT NULL"), 0.0,
           worst if worst is not None else 0.0,
           f"days replayed; {n_runs} days kept (weights = today's); checksum = max |Σcontribution − base_score|")
    # research
    yield ("pit_ic_by_tier_v2+factor_horizon_gate",
           _one(c, "SELECT COUNT(*) FROM pit_ic_by_tier_v2")[0] + _one(c, "SELECT COUNT(*) FROM factor_horizon_gate")[0],
           *_one(c, "SELECT COUNT(*) FROM factor_tests"), None, None, "")
    # ops
    # Only the rows the sync has seen: its own SUCCESS row (and every cron job after it) is
    # logged after the sync read the table, so an unbounded count is always one ahead and this
    # parity could never pass (off by exactly 1 on 2026-10-02 and -03). The same bound applies
    # to the "has a terminal twin" test: the sync saw its own RUNNING row as an orphan.
    seen = _one(c, """SELECT COALESCE(MAX(CAST(json_extract(attrs, '$.log_id') AS INTEGER)), 0) FROM step_runs
                      WHERE json_extract(attrs, '$.from')='pipeline_log'""")[0]
    yield ("pipeline_log", *_one(c, f"""SELECT COUNT(*) FROM pipeline_log p WHERE p.id <= {seen} AND (status <> 'RUNNING' OR NOT EXISTS
               (SELECT 1 FROM pipeline_log t WHERE t.id <= {seen} AND t.step_name=p.step_name AND t.started_at IS p.started_at
                  AND t.status <> 'RUNNING'))"""),
           *_one(c, "SELECT COUNT(*) FROM step_runs WHERE json_extract(attrs, '$.from')='pipeline_log'"), None, None, "terminal rows + orphans")
    yield ("pit_reconstruction_log", *_one(c, "SELECT COUNT(*) FROM pit_reconstruction_log"),
           *_one(c, "SELECT COUNT(*) FROM step_runs WHERE json_extract(attrs, '$.from')='pit_reconstruction_log'"), None, None, "")
    yield ("sector_narrative_runs+regulatory_batches",
           _one(c, "SELECT COUNT(*) FROM sector_narrative_runs")[0] + _one(c, "SELECT COUNT(*) FROM regulatory_batches")[0],
           *_one(c, "SELECT COUNT(*) FROM step_runs WHERE json_extract(attrs, '$.from') IN ('sector_narrative_runs', 'regulatory_batches')"),
           None, None, "")
    ck = ids("check")
    yield ("health_score", *_one(c, "SELECT COUNT(*) FROM health_score"),
           *_one(c, f"SELECT COUNT(*) FROM check_results WHERE check_id={ck.get('uhs', -1)}"), None, None, "")
    yield ("trust_verdicts", *_one(c, "SELECT COUNT(*) FROM trust_verdicts"),
           _one(c, f"SELECT COUNT(*) FROM check_results WHERE check_id={ck.get('trust_gate', -1)}")[0]
           + _one(c, "SELECT COUNT(*) FROM row_issues WHERE rule LIKE 'trust:%'")[0], None, None, "TRUSTED rows → check_results, others → row_issues")
    yield ("feed_checks", *_one(c, "SELECT COUNT(*) FROM (SELECT 1 FROM feed_checks GROUP BY check_kind, feed, COALESCE(route,''), run_date)"),
           *_one(c, "SELECT COUNT(*) FROM check_results WHERE check_id IN (SELECT catalog_id FROM catalog WHERE kind='check' AND name LIKE 'feed\\_%' ESCAPE '\\')"),
           None, None, "distinct (kind, feed, route, day)")
    mirrors = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%\\_quarantine' ESCAPE '\\'")]
    yield ("quarantine_mirrors(11)+screener_pull_errors",
           sum(_one(c, f"SELECT COUNT(*) FROM {m}")[0] for m in mirrors) + _one(c, "SELECT COUNT(*) FROM screener_pull_errors")[0],
           _one(c, "SELECT COUNT(*) FROM row_issues WHERE rule NOT LIKE 'trust:%'")[0] + _one(c, "SELECT COUNT(*) FROM mf.row_issues")[0],
           None, None, "")
    # mutual funds (mf.db)
    yield ("mf_scheme_master+mf_schemes", *_one(c, """SELECT COUNT(*) FROM (SELECT scheme_code FROM mf_scheme_master UNION SELECT scheme_code FROM mf_schemes
               UNION SELECT scheme_code FROM mf_nav_history UNION SELECT scheme_code FROM mf_holdings UNION SELECT scheme_code FROM mf_sector_allocation
               UNION SELECT scheme_code FROM mf_metrics UNION SELECT scheme_code FROM mf_rolling_returns UNION SELECT scheme_code FROM mf_calendar_returns)"""),
           *_one(c, "SELECT COUNT(*) FROM mf.funds"), None, None, "")
    yield ("mf_nav_history", *_one(c, "SELECT COUNT(*) FROM mf_nav_history"), *_one(c, "SELECT COUNT(*) FROM mf.fund_nav"),
           *_one(c, "SELECT SUM(nav) FROM mf_nav_history"), *_one(c, "SELECT SUM(nav) FROM mf.fund_nav"), "")
    yield ("mf_holdings+mf_sector_allocation",
           _one(c, "SELECT COUNT(*) FROM mf_holdings")[0] + _one(c, "SELECT COUNT(*) FROM mf_sector_allocation")[0],
           *_one(c, "SELECT COUNT(*) FROM mf.fund_holdings"), None, None, "")
    old = 0
    for t, skip in (("mf_metrics", {"scheme_code", "as_of_date"}), ("mf_rolling_returns", {"scheme_code", "anchor_date"}),
                    ("mf_category_stats", {"category_norm", "as_of_date"})):
        old += sum(_one(c, f"SELECT COUNT({x}) FROM {t}")[0] for x in coltypes(c, t) if x not in skip)
    old += _one(c, "SELECT COUNT(ret_pct) + COUNT(bench_ret_pct) FROM mf_calendar_returns")[0]
    yield ("mf_metrics+mf_rolling_returns+mf_calendar_returns+mf_category_stats", old, *_one(c, "SELECT COUNT(*) FROM mf.fund_metrics"), None, None, "")


def covered(names):
    """Every legacy table name mentioned by a check (for the 'unmapped' guard)."""
    return {part.split(".")[0].strip() for n in names for part in n.split("+")}


def run(write=True):
    c = connect()
    ensure_schema(c)
    rows = []
    for t, on, nn, os_, ns, note in checks(c):
        ok = on == nn and _close(os_, ns)
        rows.append((t, "PASS" if ok else "FAIL", on, nn, os_, ns, note))
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    cov = covered([r[0] for r in rows]) | set(RETIRED) | {m for m in names if m.endswith("_quarantine")}
    v3_tables = {"catalog", "entities", "classifications", "identifiers", "bars_daily", "derivative_bars", "series_values", "events",
                 "event_links", "documents", "fundamentals", "estimates", "feature_values", "runs", "picks", "pick_contributions",
                 "book_weights", "outcomes", "factor_tests", "step_runs", "check_results", "row_issues"}
    for t in sorted(names - cov - v3_tables):
        rows.append((t, "FAIL", None, None, None, None, "legacy table with no parity check and not retired"))
    for t, why in RETIRED.items():
        if t in names:
            rows.append((t, "RETIRED", None, None, None, None, why))
    if write:
        with tx(c):
            cat_ensure(c, "check", ["datamodel_parity"])
            cid = cat_ids(c, "check")["datamodel_parity"]
            for t, st, on, nn, os_, ns, note in rows:
                c.execute("""INSERT INTO check_results(check_id, subject, entity_id, date, status, score, detail, checked_at)
                    VALUES (?, ?, 0, ?, ?, ?, ?, ?)
                    ON CONFLICT(check_id, subject, entity_id, date) DO UPDATE SET status=excluded.status, score=excluded.score,
                       detail=excluded.detail, checked_at=excluded.checked_at""",
                          (cid, t, TODAY, st, (nn / on) if on else None,
                           json.dumps({"old": on, "new": nn, "old_sum": os_, "new_sum": ns, "note": note}), NOW))
    return rows


def show(c, days=7):
    cid = cat_ids(c, "check").get("datamodel_parity")
    if cid is None:
        print("no parity results yet")
        return
    df = __import__("pandas").read_sql(f"""SELECT date, subject, status FROM check_results WHERE check_id={cid}
        AND date >= date('{TODAY}', '-{days} day') ORDER BY subject, date""", c)
    print(df.pivot(index="subject", columns="date", values="status").fillna("").to_string())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args(argv)
    if a.show:
        c = connect()
        ensure_schema(c)
        show(c)
        return 0
    rows = run()
    w = max(len(r[0]) for r in rows)
    for t, st, on, nn, os_, ns, note in sorted(rows, key=lambda r: ({"FAIL": 0, "PASS": 1, "RETIRED": 2}[r[1]], r[0])):
        cs = "" if os_ is None and ns is None else f"  Σ {os_:.6g} → {ns:.6g}" if (os_ is not None and ns is not None) else f"  Σ {os_} → {ns}"
        print(f"{st:7} {t:<{w}}  {'' if on is None else f'{on:>12,} → {nn:<12,}'}{cs}  {note}")
    fails = sum(r[1] == "FAIL" for r in rows)
    print(f"\n{sum(r[1] == 'PASS' for r in rows)} PASS · {fails} FAIL · {sum(r[1] == 'RETIRED' for r in rows)} RETIRED")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
