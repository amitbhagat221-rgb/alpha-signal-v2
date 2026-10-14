"""Cockpit scaling guard: a page's cost must depend on what it SHOWS (N rows, a date window, one
stock), not on how much history or how many stocks the DB holds.

On 2026-10-14 `stock_prices` reached 5.0M rows and the Markets sector view read every close to use
the last 127 per stock: 20 s (47 s first visit). This test renders EVERY route of both cockpits
(main :3000 and ops :3001), every lazy partial / JSON API the pages call, and every function in both
apps' `prewarm` lists against the LIVE database, with a cold cache and every SQL statement captured.
It FAILS when a captured statement

  1. full-scans a table flagged `big: True` in `tables.TABLES` (plan line `SCAN <table>`, with or
     without a covering index: both read every row), or
  2. reads more than MAX_ROWS rows out of a big table into Python (an index seek on a date range
     that still returns the whole history is the same problem in a different plan).

Genuine exceptions go in ALLOW below, each with the page it serves and why it is bounded in
practice. Adding to ALLOW is a decision: write the reason, and prefer fixing the query.

The test opens the DB read-only (`mode=ro`), so it can never write, and skips when ALPHA_DB is not
set to an existing file (CI, fresh checkouts). Latency per unit is PRINTED (pytest -s), never
asserted: it varies with machine load and the Kite backfill writing beside it.

`capture_all()` is also the audit tool: it returns every statement with its plan, rows and ms.
"""
import json
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest

import tables

MAX_ROWS = 100_000          # rows one statement may pull out of a big table into the page
SCAN_STEPS = 1_000_000      # a plan SCAN counts once it ran this many VM instructions (~100k rows):
                            # a LIMIT-terminated walk of an index (newest 2 dates) is a SCAN in the plan but cheap
HEAVY_STEPS = 15_000_000    # ...and any statement on a big table that ran this many, whatever its plan says
                            # (a MIN() over an unindexed column prints as SEARCH but walks the table)
COLD_BUDGET_S = 15.0        # printed, not asserted

# (table or "*", substring of the statement, why it is acceptable). Whitespace-insensitive. An entry excuses
# BOTH kinds of failure for that statement. Each one is a decision: say what bounds it and what would end it.
ALLOW = [
    # ── main cockpit: all-history reads that are the page's content ──
    ("daily_snapshots_pit", "fwd_return_20d, [announcement_car]",
     "Model > Evidence, FACTOR_DECAY (tools/factor_decay.analyze): the mean IC of every wired factor over EVERY PIT "
     "anchor, so the whole 500k-row panel is the input. One read per hour (persisted cache, prewarmed); grows by one "
     "anchor a month. Ends with a per-anchor IC table updated incrementally."),
    ("daily_snapshots_pit", "AVG(CASE WHEN mom_6m > 0",
     "Playbooks > Market cycle: breadth at every snapshot since 2019, to say where today ranks against history. "
     "Counted inside SQLite (205 rows come back); one read per hour. Same fix as above."),
    ("pick_outcomes", "FROM pick_outcomes",
     "Book > Track record: averages, medians and hit rates over EVERY realised pick (270k rows, +2.4k a day). Cached "
     "5 min (persisted, prewarmed). A SQL rewrite was measured slower than this code (2.8 s against 1.8 s), so the "
     "real fix is a (pick_date, window, tier) rollup table: Amit's decision when the table passes ~2M rows."),
    ("fundamentals_screener", "line_item IN",
     "Playbooks > Compounders / Categories: Sales and Net profit for every stock's annual statements (about 11 years "
     "each, so the rows grow with the universe, not with time). One read per hour."),
    # ── ops cockpit: monitoring that inspects whole tables by design (all cached stale-while-revalidate, re-warmed ≤ every 10 min) ──
    ("*", "SUM(CASE WHEN [",
     "checks.range_counts: a RANGE check validates every row of a column (one scan per table). Whole-column "
     "validation is the check's job; it would become incremental with an ingest watermark per table."),
    ("trust_verdicts", "gate_1_identity IS NOT NULL",
     "TRUST_GATE_DORMANT heartbeat (checks/system.gate_facts): one pass over 310k verdict rows to ask each write-time "
     "gate when it last wrote. Cached with the health state; the gates are mostly retired (ADR 0061), so it ends "
     "with the check."),
    ("shareholding_holders", "SELECT DISTINCT [end_date]",
     "db._table_date_range slow path: 28 stray rows dated 1982 to 2001 make MIN/MAX fail its sanity check, so every "
     "census reads each distinct date. Goes away when those rows are deleted (data fix, not code)."),
    ("mf_nav_history", "[fetched_at]",
     "Freshness date range: tables.TABLES date_col is fetched_at, which has no index (0.8 s a pass at 8.9M rows). "
     "mf_nav_history(fetched_at) is proposed in schema.sql, not built on the live DB."),
]

_REAL_CONNECT = sqlite3.connect
_DB = os.environ.get("ALPHA_DB", "")


def big_tables():
    """Tables flagged `big: True` in tables.TABLES (the registry owns the list)."""
    return {t for t, m in tables.TABLES.items() if m.get("big")}


# ───────────────────────────── SQL capture ─────────────────────────────

LOG = []            # one dict per executed statement
_CUR = {"unit": ""}


class _Cursor(sqlite3.Cursor):
    def execute(self, sql, params=()):
        conn = self.connection
        rec = {"unit": _CUR["unit"], "sql": sql, "params": params, "t0": time.perf_counter(),
               "ms": None, "rows": None, "steps": 0, "_s0": getattr(conn, "steps", 0), "_conn": conn}
        LOG.append(rec)
        self._rec = rec
        try:
            return super().execute(sql, params)
        finally:
            rec["ms"] = (time.perf_counter() - rec["t0"]) * 1000
            rec["steps"] = getattr(conn, "steps", 0) - rec["_s0"]

    def _done(self, n):
        rec = getattr(self, "_rec", None)
        if rec is not None:
            rec["ms"] = (time.perf_counter() - rec["t0"]) * 1000
            rec["steps"] = getattr(rec["_conn"], "steps", 0) - rec["_s0"]
            rec["rows"] = (rec["rows"] or 0) + n

    def fetchall(self):
        out = super().fetchall()
        self._done(len(out))
        return out

    def fetchone(self):
        out = super().fetchone()
        self._done(0 if out is None else 1)
        return out

    def fetchmany(self, size=None):
        out = super().fetchmany(*(() if size is None else (size,)))
        self._done(len(out))
        return out

    def __next__(self):
        try:
            out = super().__next__()
        except StopIteration:
            self._done(0)
            raise
        self._done(1)
        return out


class _Conn(sqlite3.Connection):
    def cursor(self, factory=_Cursor):
        return super().cursor(factory)

    def execute(self, sql, params=()):          # sqlite3's own Connection.execute bypasses cursor()
        return self.cursor().execute(sql, params)


def _is_main_db(database):
    s = str(database)
    if s.startswith("file:"):
        s = s[5:].split("?")[0]
    try:
        return bool(_DB) and Path(s).resolve() == Path(_DB).resolve()
    except OSError:
        return False


def _connect(database, *a, **kw):
    """sqlite3.connect for the live DB: read-only, with the capturing cursor. Others pass through."""
    if not _is_main_db(database):
        return _REAL_CONNECT(database, *a, **kw)
    kw = {k: v for k, v in kw.items() if k not in ("uri", "factory")}
    conn = _REAL_CONNECT(f"file:{Path(_DB).resolve()}?mode=ro", *a, uri=True, factory=_Conn, **kw)
    conn.steps = 0

    def _tick():                                  # one tick = 1,000 VM instructions: work done, machine-independent
        conn.steps += 1000
        return 0
    conn.set_progress_handler(_tick, 1000)
    return conn


_ALIAS = re.compile(r"\b(?:from|join)\s+[\[\"`]?(\w+)[\]\"`]?(?:\s+(?:as\s+)?(?!on\b|where\b|join\b|left\b|inner\b|cross\b|group\b|order\b|limit\b|using\b|union\b|natural\b|window\b)(\w+))?",
                    re.I)


def plan_of(conn, sql, params):
    """[(verb, table, detail)] from EXPLAIN QUERY PLAN, aliases resolved to real table names."""
    aliases = {}
    for tbl, al in _ALIAS.findall(sql):
        aliases[tbl.lower()] = tbl
        if al:
            aliases[al.lower()] = tbl
    out = []
    try:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    except sqlite3.Error as e:
        return [("ERROR", "", str(e))]
    for _, _, _, detail in rows:
        m = re.match(r"(SCAN|SEARCH)\s+(\S+)(.*)", detail)
        if m:
            out.append((m.group(1), aliases.get(m.group(2).lower(), m.group(2)), detail))
    return out


def analyse(log, big):
    """Attach plan + offence list to every distinct statement. Returns (stmts, offences)."""
    conn = _REAL_CONNECT(f"file:{Path(_DB).resolve()}?mode=ro", uri=True)
    cache, stmts, offences = {}, [], []
    try:
        for rec in log:
            s = rec["sql"].strip()
            if s.upper().startswith(("PRAGMA", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")):
                continue
            key = (s, repr(rec["params"]))
            if key not in cache:
                cache[key] = plan_of(conn, s, rec["params"])
            plan = cache[key]
            touched = {t for _, t, _ in plan}
            scans = sorted({t for v, t, _ in plan if v == "SCAN" and t in big})
            heavy = sorted(touched & big) if (rec["rows"] or 0) > MAX_ROWS else []
            busy = sorted(touched & big) if rec["steps"] >= HEAVY_STEPS else []
            rec2 = {k: v for k, v in rec.items() if not k.startswith("_")}
            rec2.update(plan=plan, scans=scans, heavy=heavy, busy=busy)
            if rec["steps"] < SCAN_STEPS:
                scans = []
            stmts.append(rec2)
            for t in scans:
                offences.append((rec["unit"], t, f"full scan ({rec['steps']:,} VM steps)", s))
            for t in busy:
                if t not in scans:
                    offences.append((rec["unit"], t, f"heavy read ({rec['steps']:,} VM steps)", s))
            for t in heavy:
                offences.append((rec["unit"], t, f"{rec['rows']:,} rows read", s))
    finally:
        conn.close()
    flat = lambda x: " ".join(x.split())
    allowed = [o for o in offences
               if any(t in ("*", o[1]) and flat(frag) in flat(o[3]) for t, frag, _ in ALLOW)]
    return stmts, [o for o in offences if o not in allowed]


# ───────────────────────────── the units ─────────────────────────────

def _fixtures():
    """Sample ids chosen from the live DB (own connection, not captured)."""
    c = _REAL_CONNECT(f"file:{Path(_DB).resolve()}?mode=ro", uri=True)
    q = lambda sql, p=(): [r[0] for r in c.execute(sql, p).fetchall()]
    try:
        pick_date = q("SELECT MAX(pick_date) FROM daily_picks")[0]
        fx = {"sid": {}}
        for tier in ("LARGE", "MID", "SMALL"):
            r = q("SELECT sid FROM daily_picks WHERE pick_date = ? AND cap_tier = ? ORDER BY rank LIMIT 1",
                  (pick_date, tier))
            if r:
                fx["sid"][tier] = r[0]
        r = q("SELECT sid FROM stocks WHERE cap_tier = 'MICRO' ORDER BY sid LIMIT 1")
        if r:
            fx["sid"]["MICRO"] = r[0]
        r = q("SELECT sid FROM stocks WHERE cap_tier = 'SMALL' AND sid NOT IN "
              "(SELECT sid FROM daily_picks WHERE pick_date = ?) ORDER BY sid LIMIT 1", (pick_date,))
        if r:
            fx["sid"]["UNRANKED"] = r[0]
        fx["schemes"] = q("SELECT scheme_code FROM mf_metrics WHERE as_of_date = (SELECT MAX(as_of_date) FROM mf_metrics) "
                          "ORDER BY composite_score DESC LIMIT 3")
        fx["memos"] = q("SELECT doc_id FROM documents WHERE source = 'org' AND status = 'valid' "
                        "ORDER BY doc_id DESC LIMIT 2")
        fx["themes"] = q("SELECT theme_id FROM news_themes LIMIT 2")
        return fx
    finally:
        c.close()


def _reset_caches(mods):
    """Cold cache: wipe the on-disk cache dir and every in-process memo."""
    from cockpit import _shared
    d = Path(_shared._PERSISTED_CACHE_DIR)
    if d.exists():
        for f in d.glob("*.pkl"):
            f.unlink(missing_ok=True)
    for m in mods:
        for v in list(vars(m).values()):
            fn = getattr(v, "cache_clear", None)
            if callable(fn):
                try:
                    fn()
                except Exception:       # noqa: BLE001
                    pass


def build_units(main_mod, ops_mod, cm, co, fx):
    """[(name, callable)] — every route/partial/API of both apps plus every prewarm function.
    Prewarm lists are collected from the apps' own startup hooks, so they cannot drift."""
    import org
    import feeds
    from cockpit import pages
    units = []
    sid = fx["sid"]
    get = lambda client, path: (lambda: client.get(path))

    # prewarm functions, collected from the startup hooks
    for label, mod in (("main", main_mod), ("ops", ops_mod)):
        got = []
        orig = mod.prewarm
        mod.prewarm = lambda warmers, label="x", **kw: got.extend(warmers)
        try:
            mod._prewarm_cache()
        finally:
            mod.prewarm = orig
        for w in got:
            units.append((f"{label} prewarm:{w[0]}", w[1]))

    # main cockpit
    for p in ("/", "/stocks", "/markets", "/explorer", "/sectors", "/playbooks", "/book", "/model",
              "/mutual-funds", "/actions", "/news", "/ideas", "/portfolio", "/model/outcomes", "/multibagger"):
        units.append((f"main GET {p}", get(cm, p)))
    for q in ("tier=LARGE", "tier=SMALL&sort=score", "q=tata", "page=2"):
        units.append((f"main GET /stocks?{q}", get(cm, f"/stocks?{q}")))
    for tab, _ in pages.PLAYBOOK_TABS:
        units.append((f"main GET /partial/playbooks/{tab}", get(cm, f"/partial/playbooks/{tab}")))
    units.append(("main GET /partial/news-search", get(cm, "/partial/news-search?q=bank&hours=168")))
    for t in fx["themes"]:
        units.append((f"main GET /markets/theme/{t}", get(cm, f"/markets/theme/{t}")))
    for kind, sidv in sid.items():
        units.append((f"main GET /stocks/{kind}", get(cm, f"/stocks/{sidv}")))
    s0 = next(iter(sid.values()))
    for days in (31, 92, 130, 183, 366, 1096, 3650):
        units.append((f"main GET /api/prices-extended?days={days}", get(cm, f"/api/prices-extended/{s0}?days={days}")))
    for kind, sidv in sid.items():
        for api in ("quarterly", "shareholding", "forecasts", "insider-timeline", "lineage"):
            units.append((f"main GET /api/{api} [{kind}]", get(cm, f"/api/{api}/{sidv}")))
    units.append(("main GET /api/search", get(cm, "/api/search?q=tata")))
    units.append(("main GET /api/model/outcomes", get(cm, "/api/model/outcomes?n=10")))
    # sector / industry cards: the first industry and sector the model knows
    units.append(("main GET /sectors?industry", lambda: cm.get(
        "/sectors?industry=" + __import__("urllib.parse", fromlist=["quote"]).quote(
            next(iter(main_mod.api.get_group_list("industry")), "")))))
    units.append(("main GET /sectors?sector", lambda: cm.get(
        "/sectors?sector=" + __import__("urllib.parse", fromlist=["quote"]).quote(
            next(iter(main_mod.api.get_group_list("sector")), "")))))
    units.append(("main GET /partial/industry-card", lambda: cm.get(
        "/partial/industry-card/" + __import__("urllib.parse", fromlist=["quote"]).quote(
            next(iter(main_mod.api.get_group_list("industry")), "")) + f"?sid={s0}")))
    units.append(("main GET /partial/sector-card", lambda: cm.get(
        "/partial/sector-card/" + __import__("urllib.parse", fromlist=["quote"]).quote(
            next(iter(main_mod.api.get_group_list("sector")), "")) + f"?sid={s0}")))
    # funds
    for q in ("category=" + "Equity%20%2F%20Large%20Cap", "q=hdfc", "sort=ret_3y", "show_all=1", "page=2"):
        units.append((f"main GET /mutual-funds?{q}", get(cm, f"/mutual-funds?{q}")))
    units.append(("main GET /api/mf-search", get(cm, "/api/mf-search?q=hdfc")))
    if fx["schemes"]:
        units.append(("main GET /mutual-funds/compare", get(cm, "/mutual-funds/compare?codes=" + ",".join(fx["schemes"]))))
    for code in fx["schemes"][:2]:
        units.append(("main GET /mutual-funds/{code}", get(cm, f"/mutual-funds/{code}")))
        units.append(("main GET /api/mf-nav-series (all)", get(cm, f"/api/mf-nav-series/{code}")))
        for d in (365, 1095, 1825):
            units.append((f"main GET /api/mf-nav-series?days={d}", get(cm, f"/api/mf-nav-series/{code}?days={d}")))
        units.append(("main GET /api/mf-rolling", get(cm, f"/api/mf-rolling/{code}")))

    # ops cockpit
    for p in ("/", "/system", "/feeds", "/flow", "/options", "/org", "/sql", "/command", "/api/options",
              "/api/feeds", "/api/org", "/api/health", "/api/health/overview", "/api/pipeline",
              "/api/runs", "/api/run-events", "/api/org/running", "/api/org/chats", "/api/org/conversations",
              "/api/org/house-style", "/feeds/tab/data", "/flow/tab/log", "/api/search?q=tata"):
        units.append((f"ops GET {p}", get(co, p)))
    for t in ops_mod.SYSTEM_TABS:
        units.append((f"ops GET /system/tab/{t}", get(co, f"/system/tab/{t}")))
    for q in ("mfrom=2000-01-01", "mpage=2&mfrom=2000-01-01", "mrole=cio&mfrom=2000-01-01"):
        units.append((f"ops GET /org?{q}", get(co, f"/org?{q}")))
    for d in fx["memos"]:
        units.append(("ops GET /org/memo/{id}", get(co, f"/org/memo/{d}")))
    for role in org.ROLES:
        units.append((f"ops GET /api/org/chat/{role}", get(co, f"/api/org/chat/{role}")))
    units.append(("ops GET /api/org/seat/{role}", get(co, f"/api/org/seat/{next(iter(org.ROLES))}")))
    for f in feeds.FEEDS:
        units.append((f"ops GET /api/feeds/{f}/incident", get(co, f"/api/feeds/{f}/incident")))
    for f in list(feeds.FEEDS)[:3]:
        units.append(("ops GET /api/runs?feed", get(co, f"/api/runs?feed={f}&limit=200")))
        units.append(("ops GET /api/run-events?feed", get(co, f"/api/run-events?feed={f}&limit=500&since=7d")))
    # the per-table diagnostic of every table in the Feeds > Data grid (cached scores, one fetch each)
    units.append(("ops GET /feeds/data/{table}", lambda: [
        co.get(f"/feeds/data/{t}") for t in ("stock_prices", "fno_bhav", "mf_nav_history", "daily_picks")]))
    return units


# The Data tab's health scores (compute_db_health) score every column of every table: ~4.5 minutes on 5M-row
# tables, by design, cached and re-warmed every 6 h (see cockpit/_shared.prewarm). Off unless SCALE_FULL=1.
FULL = os.environ.get("SCALE_FULL") == "1"
SLOW_UNITS = ("prewarm:data_health_scores", "/feeds/data/")


def capture_all(reset=True, only=None, progress=None, skip=()):
    """Run every unit against the live DB, read-only, from a cold cache. `reset` also empties the caches between
    units (the audit: each page pays its own cost; the test: False, the way production runs, one cold start).
    Returns (stmts, offences, report): every statement with plan / rows / ms / steps, the failures after ALLOW,
    and [{name, wall_ms, status, error}] per unit."""
    import sys
    import tempfile
    import types
    import db
    import runlog
    import webauth
    from cockpit import _shared
    from fastapi.testclient import TestClient

    big = big_tables()
    LOG.clear()
    saved = dict(connect=sqlite3.connect, db_path=db.DB_PATH, runlog_path=runlog.DB_PATH, auth=webauth.AUTH_FILE,
                 scan_file=db._slow_scan_file, cache_dir=_shared._PERSISTED_CACHE_DIR,
                 preview=os.environ.pop("COCKPIT_PREVIEW", None))
    slow_warms = []
    try:
        with tempfile.TemporaryDirectory() as tmp:
            sqlite3.connect = _connect
            db.DB_PATH = runlog.DB_PATH = Path(_DB)
            _shared._PERSISTED_CACHE_DIR = Path(tmp) / "cache"          # a cold cache that never touches production's
            webauth.AUTH_FILE = Path(tmp) / "auth.json"
            webauth.set_password("correct horse battery")
            # The census (db.data_health) remembers big tables' counts for 6 h beside the DB; production has that
            # memo, so seed it: the test measures the steady state, and never writes beside the live DB.
            db._slow_scan_file = lambda: Path(tmp) / "slow_scans.json"
            db._slow_scan_file().write_text(json.dumps({t: [time.time(), 1, 1] for t in big}))
            db._slow_scans.clear()
            from cockpit import app as main_mod
            from cockpit_ops import app as ops_mod
            from cockpit_ops import api as oapi
            cookies = {webauth.COOKIE: webauth.make_token()}
            # Feeds > Data starts the 4.5-minute whole-database health scan in a background thread when its cache
            # is cold; its statements would land in whatever unit runs next. It is censused on purpose (SCALE_FULL=1).
            if not FULL:
                for slow in (oapi._data_health_scores, oapi.get_db_summary):
                    slow_warms.append((slow, slow.warm))
                    slow.warm = lambda *a, **k: None
            cm = TestClient(main_mod.app, cookies=cookies)
            co = TestClient(ops_mod.app, cookies=cookies)
            fx = _fixtures()
            units = build_units(main_mod, ops_mod, cm, co, fx)
            cache_mods = [m for m in list(sys.modules.values())
                          if isinstance(m, types.ModuleType)
                          and getattr(m, "__name__", "").startswith(("cockpit", "views", "signals", "pit", "org", "option_book"))]
            _reset_caches(cache_mods)
            report = []
            for name, fn in units:
                if (only and not any(o in name for o in only)) or any(k in name for k in skip) \
                        or (not FULL and any(k in name for k in SLOW_UNITS)):
                    continue
                if reset:
                    _reset_caches(cache_mods)
                _CUR["unit"] = name
                t0 = time.perf_counter()
                status, err = "ok", ""
                try:
                    r = fn()
                    for x in (r if isinstance(r, list) else [r]):
                        if hasattr(x, "status_code") and x.status_code >= 500:
                            status, err = f"HTTP {x.status_code}", x.text[:200]
                except Exception as e:          # noqa: BLE001 - a broken page is reported, not fatal here
                    status, err = "EXC", f"{type(e).__name__}: {e}"[:200]
                report.append({"name": name, "wall_ms": (time.perf_counter() - t0) * 1000, "status": status, "error": err})
                if progress:
                    progress(report[-1])
    finally:
        for slow, warm in slow_warms:
            slow.warm = warm
        sqlite3.connect = saved["connect"]
        db.DB_PATH, runlog.DB_PATH, webauth.AUTH_FILE = saved["db_path"], saved["runlog_path"], saved["auth"]
        db._slow_scan_file, _shared._PERSISTED_CACHE_DIR = saved["scan_file"], saved["cache_dir"]
        if saved["preview"] is not None:
            os.environ["COCKPIT_PREVIEW"] = saved["preview"]
    stmts, offences = analyse(list(LOG), big)
    return stmts, offences, report


# ───────────────────────────── the tests ─────────────────────────────

needs_db = pytest.mark.skipif(not (_DB and Path(_DB).is_file()), reason="ALPHA_DB is not set to a database file")


def test_big_flag_matches_row_counts():
    """The registry flag is the guard's list: a table that has grown past 200k rows without
    `big: True` (or a flagged name that does not exist) fails here."""
    if not (_DB and Path(_DB).is_file()):
        pytest.skip("ALPHA_DB is not set to a database file")
    c = _REAL_CONNECT(f"file:{Path(_DB).resolve()}?mode=ro", uri=True)
    try:
        existing = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in big_tables() if t not in existing]
        assert not missing, f"tables.TABLES flags big tables the DB does not have: {missing}"
        grown = []
        for t in sorted(existing - big_tables()):
            if t.endswith("_quarantine") or t.startswith("sqlite_"):
                continue
            if c.execute(f"SELECT 1 FROM [{t}] LIMIT 1 OFFSET 200000").fetchone():
                grown.append(t)
        assert not grown, f"{grown} hold over 200k rows: add `big: True` to their tables.TABLES entry"
    finally:
        c.close()


@needs_db
def test_no_cockpit_statement_scans_a_big_table(capsys):
    """Every route, partial, API and prewarm function of both cockpits, cold cache, live DB."""
    stmts, offences, report = capture_all(reset=False)
    with capsys.disabled():
        print("\n  cockpit scaling: unit latency (cold, printed only; budget %.0f s)" % COLD_BUDGET_S)
        for r in sorted(report, key=lambda r: -r["wall_ms"])[:15]:
            flag = "  OVER BUDGET" if r["wall_ms"] > COLD_BUDGET_S * 1000 else ""
            print(f"    {r['wall_ms']:9.0f} ms  {r['name']}{flag}")
    broken = [r for r in report if r["status"] != "ok" and not r["status"].startswith("HTTP 4")]
    assert not broken, "units failed to render: " + json.dumps(broken, indent=1)
    assert not offences, "a page query reads a big table in proportion to its history:\n" + "\n".join(
        f"  [{u}] {kind} of {t}: {' '.join(s.split())[:240]}" for u, t, kind, s in offences)


def test_guard_catches_the_pre_fd81010_sector_query(monkeypatch):
    """The query that made Markets take 20 s: every close of every stock, to use the last 127.
    Run through the same capture and analysis as the pages; it must be reported, and the seek that
    replaced it (signals/sector_tilt._per_sector_view) must not be."""
    if not (_DB and Path(_DB).is_file()):
        pytest.skip("ALPHA_DB is not set to a database file")
    import pandas as pd
    monkeypatch.setattr(sqlite3, "connect", _connect)
    LOG.clear()
    _CUR["unit"] = "pre-fd81010 sector view"
    old = "SELECT sid, date, close FROM stock_prices WHERE close > 0 ORDER BY sid, date"
    with sqlite3.connect(_DB) as con:
        cur = con.execute(old)
        cur.fetchmany(150_000)          # streams in key order: 150k rows are enough to cross both bars, in seconds
        new = ("SELECT sid, date, close FROM stock_prices WHERE sid = ? AND close > 0 "
               "ORDER BY date DESC LIMIT 128")
        for (sid,) in con.execute("SELECT sid FROM stocks LIMIT 300").fetchall():
            con.execute(new, [sid]).fetchall()
    stmts, offences = analyse(list(LOG), big_tables())
    LOG.clear()
    assert [o for o in offences if " ".join(o[3].split()) == old], "the pre-fd81010 query was not caught"
    assert not [o for o in offences if "LIMIT 128" in o[3]], "the per-stock seek must pass"
    kinds = {o[2].split(" (")[0] for o in offences if " ".join(o[3].split()) == old}
    assert "full scan" in kinds


def test_decimate_keeps_the_last_year_the_first_row_and_every_extreme():
    from cockpit._shared import CHART_MAX_POINTS, decimate
    import random
    rnd = random.Random(7)
    rows = [{"i": i, "v": rnd.random() * 10 + i * 0.005} for i in range(3300)]
    out = decimate(rows, lambda r: r["v"])
    assert len(out) <= CHART_MAX_POINTS
    assert out[0] is rows[0] and out[-250:] == rows[-250:]
    older = rows[:-250]
    assert max(older, key=lambda r: r["v"]) in out and min(older, key=lambda r: r["v"]) in out
    assert [r["i"] for r in out] == sorted(r["i"] for r in out)
    short = rows[:CHART_MAX_POINTS]
    assert decimate(short, lambda r: r["v"]) is short          # under the limit: untouched
