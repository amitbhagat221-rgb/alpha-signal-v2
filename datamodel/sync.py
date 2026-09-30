"""
Data model v3 shadow sync (ADR 0054, plan 0017).

Derives every v3 table from the legacy tables, applying each concept's write rule:
reference upsert + SCD2 (classifications, identifiers), bars/events/documents
append-if-new, series/fundamentals/estimates versioned (fetched_at + last_seen_at),
features slice-replace per (feature, date), decisions per run. Producers are not
touched; the old tables stay the source of truth until the reconciliation week ends
(datamodel/reconcile.py). Idempotent: re-running a day changes nothing.

    python -m datamodel.sync               # incremental (end of `run.sh morning`)
    python -m datamodel.sync --full        # rebuild every slice from all history
    python -m datamodel.sync --only features,events

Writes go to config.DB_PATH (and data/mf.db); run it from a worktree whose data/ is a
snapshot to test.
"""
import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import time
import zlib
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

DB_PATH = config.DB_PATH
MF_DB = DB_PATH.parent / "mf.db"
ROOT = Path(__file__).resolve().parents[1]
V3_MARK = "-- Data model v3"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
TODAY = datetime.now(timezone.utc).date().isoformat()
WINDOW_DAYS = 15          # incremental re-sync window for dated slices
ENUM_MAX = 64             # a TEXT column with ≤ this many distinct values is an enum


def log(msg):
    print(f"[datamodel {datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


# ─────────────────────────── connection / schema ───────────────────────────

def connect():
    c = sqlite3.connect(str(DB_PATH), isolation_level=None, timeout=60)
    c.execute("PRAGMA busy_timeout=60000")
    c.execute("PRAGMA foreign_keys=OFF")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA cache_size=-500000")
    return c


@contextmanager
def tx(c):
    c.execute("BEGIN IMMEDIATE")
    try:
        yield
        c.execute("COMMIT")
    except BaseException:
        c.execute("ROLLBACK")
        raise


def ensure_schema(c):
    text = (ROOT / "schema.sql").read_text()
    i = text.index(V3_MARK)
    c.executescript(text[text.rfind("\n", 0, i) + 1:])
    m = sqlite3.connect(str(MF_DB))
    m.executescript((ROOT / "datamodel" / "mf_schema.sql").read_text())
    m.close()
    c.execute(f"ATTACH DATABASE '{MF_DB}' AS mf")


def cols(c, table, schema="main"):
    return [r[1] for r in c.execute(f"PRAGMA {schema}.table_info('{table}')")]


def coltypes(c, table):
    return {r[1]: (r[2] or "").upper() for r in c.execute(f"PRAGMA table_info('{table}')")}


def exists(c, table):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def q(name):
    return '"' + name.replace('"', '""') + '"'


def jobj(prefix, columns):
    """json_object('c1', p.c1, ...) — SQLite caps json_object at ~50 pairs per call, so chunk + json_patch."""
    parts = [", ".join(f"'{x}', {prefix}{q(x)}" for x in columns[i:i + 40]) for i in range(0, len(columns), 40)]
    if not parts:
        return "'{}'"
    expr = f"json_object({parts[0]})"
    for p in parts[1:]:
        expr = f"json_patch({expr}, json_object({p}))"
    return expr


# ─────────────────────────── catalog ───────────────────────────

def cat_ensure(c, kind, names, spec=None, **fields):
    """Register names (append-only ids). `spec`: dict name → JSON-able spec (only set on insert)."""
    rows = []
    for n in names:
        s = spec.get(n) if isinstance(spec, dict) else None
        rows.append((kind, n, NOW[:10], json.dumps(s, default=str) if s is not None else None,
                     fields.get("unit"), fields.get("cadence"), fields.get("lag_days")))
    c.executemany("INSERT OR IGNORE INTO catalog(kind, name, first_seen, spec, unit, cadence, lag_days) "
                  "VALUES (?,?,?,?,?,?,?)", rows)


def cat_ids(c, kind):
    return {n: i for i, n in c.execute("SELECT catalog_id, name FROM catalog WHERE kind=?", (kind,))}


def cat_spec(c, kind, name):
    r = c.execute("SELECT spec FROM catalog WHERE kind=? AND name=?", (kind, name)).fetchone()
    return json.loads(r[0]) if r and r[0] else {}


def cat_set_spec(c, kind, name, spec):
    c.execute("UPDATE catalog SET spec=? WHERE kind=? AND name=?", (json.dumps(spec, default=str), kind, name))


def _jsonable(v):
    if callable(v):
        return getattr(v, "__name__", str(v))
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in v]
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    return str(v)


def sync_catalog(c):
    import factors
    import tables
    with tx(c):
        cat_ensure(c, "feature", list(factors.FACTORS),
                   spec={k: {"registry": "factors.FACTORS", **_jsonable(v)} for k, v in factors.FACTORS.items()})
        cat_ensure(c, "dataset", list(tables.TABLES),
                   spec={k: {"registry": "tables.TABLES", **_jsonable(v)} for k, v in tables.TABLES.items()})
        cat_ensure(c, "check", ["datamodel_parity", "uhs", "trust_gate"])
    log(f"catalog: {c.execute('SELECT COUNT(*) FROM catalog').fetchone()[0]} names")


# ─────────────────────────── runs ───────────────────────────

def git_sha():
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True).stdout.strip() != ""
        return sha or None, int(dirty)
    except Exception:
        return None, None


def start_sync_run(c):
    sha, dirty = git_sha()
    with tx(c):
        cur = c.execute("INSERT INTO runs(kind, as_of_date, started_at, status, git_sha, dirty) "
                        "VALUES ('datamodel_sync', ?, ?, 'running', ?, ?)", (TODAY, NOW, sha, dirty))
    return cur.lastrowid


def last_sync(c):
    r = c.execute("SELECT MAX(started_at) FROM runs WHERE kind='datamodel_sync' AND status='ok'").fetchone()
    return r[0]


def ensure_runs(c, kind, date_sql, official=1):
    """One mirror run per (kind, as_of_date) for the legacy dates in `date_sql` (a SELECT of one column)."""
    c.execute(f"""INSERT INTO runs(kind, as_of_date, started_at, status, official, attrs)
        WITH x(d) AS ({date_sql})
        SELECT DISTINCT '{kind}', d, d || 'T00:00:00', 'ok', {official}, '{{"legacy_mirror": true}}' FROM x
        WHERE d IS NOT NULL AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.kind='{kind}' AND r.as_of_date=x.d)""")


# ─────────────────────────── entities ───────────────────────────

SEC = "e.kind='security' AND e.market='IN' AND e.key"


def sync_entities(c):
    # every stocks column not modelled elsewhere (tier/sector/industry/nifty500 → classifications) rides in attrs
    st_attrs = [x for x in cols(c, "stocks") if x not in ("sid", "name", "sector", "industry", "cap_tier", "in_nifty500")]
    with tx(c):
        c.execute(f"""INSERT INTO entities(kind, key, name, attrs, created_at, updated_at)
            SELECT 'security', sid, name, {jobj("", st_attrs)}, '{NOW}', '{NOW}'
            FROM stocks WHERE true
            ON CONFLICT(kind, market, key) DO UPDATE SET name=excluded.name, attrs=excluded.attrs, updated_at=excluded.updated_at
            WHERE entities.name IS NOT excluded.name OR entities.attrs IS NOT excluded.attrs""")
        # every sid any legacy table references (orphans get an entity, flagged)
        for t in ("stock_prices", "daily_picks", "daily_snapshots_pit", "daily_snapshots_pit_v1", "bse_announcements",
                  "market_events", "insider_trades", "fno_bhav", "mf_holdings", "pick_outcomes", "analyst_estimates", "historical_universe",
                  "scrip_master"):
            if exists(c, t) and "sid" in cols(c, t):
                c.execute(f"""INSERT OR IGNORE INTO entities(kind, key, attrs, created_at, updated_at)
                    SELECT DISTINCT 'security', sid, '{{"orphan_from": "{t}"}}', '{NOW}', '{NOW}' FROM {t} WHERE sid IS NOT NULL""")
        # dead names: listed in historical bhavcopy but never mapped to a Tickertape sid
        if exists(c, "historical_universe"):
            c.execute(f"""INSERT INTO entities(kind, key, listed_on, delisted_on, attrs, created_at, updated_at)
                SELECT 'security', 'NSE:' || symbol, MIN(snapshot_date), MAX(snapshot_date),
                       json_object('series', MAX(series), 'from', 'historical_universe'), '{NOW}', '{NOW}'
                FROM historical_universe WHERE sid IS NULL GROUP BY symbol
                ON CONFLICT(kind, market, key) DO UPDATE SET listed_on=excluded.listed_on, delisted_on=excluded.delisted_on""")
        sectors = set()
        for t, col in (("stocks", "sector"), ("macro_sector_signals", "sector"), ("macro_sector_signals_pit", "sector"),
                       ("sector_briefs", "sector"), ("sector_force_breakdown", "sector"), ("sector_dossiers", "sector"),
                       ("sector_metadata", "sector"), ("policy_events", "sector"), ("regulatory_signals", "sector"),
                       ("sector_analyst_breadth_pit", "sector"), ("sector_sentiment_breadth_pit", "sector"),
                       ("macro_sector_map", "sector")):
            if exists(c, t):
                sectors |= {r[0] for r in c.execute(f"SELECT DISTINCT {col} FROM {t} WHERE {col} IS NOT NULL")}
        c.executemany(f"INSERT OR IGNORE INTO entities(kind, key, name, created_at, updated_at) VALUES ('sector', ?, ?, '{NOW}', '{NOW}')",
                      [(s, s) for s in sectors])
        c.execute(f"""INSERT OR IGNORE INTO entities(kind, key, name, created_at, updated_at)
            SELECT DISTINCT 'industry', industry, industry, '{NOW}', '{NOW}' FROM stocks WHERE industry IS NOT NULL""")
        c.execute(f"""INSERT OR IGNORE INTO entities(kind, key, name, created_at, updated_at)
            SELECT DISTINCT 'index', index_symbol, index_symbol, '{NOW}', '{NOW}' FROM nse_index_history""")
        for t in ("fno_iv_history", "fno_pcr_history", "fno_bhav"):
            c.execute(f"""INSERT OR IGNORE INTO entities(kind, key, name, created_at, updated_at)
                SELECT DISTINCT 'index', 'FNO:' || symbol, symbol, '{NOW}', '{NOW}' FROM {t} WHERE sid IS NULL AND symbol IS NOT NULL""")
        c.execute(f"INSERT OR IGNORE INTO entities(kind, key, name, created_at, updated_at) VALUES ('market', 'IN', 'India', '{NOW}', '{NOW}')")
        c.execute(f"INSERT OR IGNORE INTO entities(kind, key, name, created_at, updated_at) VALUES ('portfolio', 'book', 'HRP book', '{NOW}', '{NOW}')")
    log("entities: " + ", ".join(f"{k}={n}" for k, n in c.execute("SELECT kind, COUNT(*) FROM entities GROUP BY kind")))


# ─────────────────────────── SCD2 (classifications, identifiers) ───────────────────────────

def scd2(c, target, kcol, incoming_sql, source, run_id):
    """incoming_sql yields (entity_id, k, value). Close changed/vanished open rows at TODAY, open new ones."""
    c.execute("DROP TABLE IF EXISTS temp._inc")
    c.execute(f"CREATE TEMP TABLE _inc AS {incoming_sql}")
    c.execute("CREATE INDEX temp._inc_ix ON _inc(entity_id, k)")
    extra_cols, extra_vals = ("source, run_id", f"'{source}', {run_id}") if target == "classifications" else ("attrs", f"json_object('source', '{source}')")
    # same-day change of a row opened today: update in place (PK includes valid_from)
    c.execute(f"""UPDATE {target} SET value = (SELECT i.value FROM _inc i WHERE i.entity_id={target}.entity_id AND i.k={target}.{kcol})
        WHERE valid_to IS NULL AND valid_from = '{TODAY}' AND {kcol} IN (SELECT DISTINCT k FROM _inc)
          AND EXISTS (SELECT 1 FROM _inc i WHERE i.entity_id={target}.entity_id AND i.k={target}.{kcol} AND i.value <> {target}.value)""")
    changed = c.execute(f"""SELECT COUNT(*) FROM {target} t JOIN _inc i ON i.entity_id=t.entity_id AND i.k=t.{kcol}
        WHERE t.valid_to IS NULL AND t.value <> i.value""").fetchone()[0]
    # close rows whose value changed, or that vanished from the incoming set (for the kinds incoming covers)
    c.execute(f"""UPDATE {target} SET valid_to = '{TODAY}'
        WHERE valid_to IS NULL AND {kcol} IN (SELECT DISTINCT k FROM _inc) AND (
          NOT EXISTS (SELECT 1 FROM _inc i WHERE i.entity_id={target}.entity_id AND i.k={target}.{kcol})
          OR EXISTS (SELECT 1 FROM _inc i WHERE i.entity_id={target}.entity_id AND i.k={target}.{kcol} AND i.value <> {target}.value))""")
    # open rows for new / changed values
    cur = c.execute(f"""INSERT OR IGNORE INTO {target}(entity_id, {kcol}, value, valid_from, valid_to, {extra_cols})
        SELECT i.entity_id, i.k, i.value, '{TODAY}', NULL, {extra_vals} FROM _inc i
        WHERE NOT EXISTS (SELECT 1 FROM {target} t WHERE t.entity_id=i.entity_id AND t.{kcol}=i.k AND t.valid_to IS NULL)""")
    return changed, cur.rowcount


def sync_classifications(c, run_id):
    with tx(c):
        if c.execute("SELECT COUNT(*) FROM classifications").fetchone()[0] == 0:
            # history the legacy tables kept: tier + sector of every ranked stock per pick_date
            for scheme, col in (("tier", "cap_tier"), ("sector", "sector")):
                c.execute(f"""INSERT INTO classifications(entity_id, scheme, value, valid_from, valid_to, source, run_id)
                    WITH x AS (SELECT e.entity_id, d.pick_date AS d, d.{col} AS v,
                                      LAG(d.{col}) OVER (PARTITION BY d.sid ORDER BY d.pick_date) AS pv
                               FROM daily_picks d JOIN entities e ON {SEC}=d.sid WHERE d.{col} IS NOT NULL),
                         s AS (SELECT entity_id, d, v FROM x WHERE pv IS NULL OR pv <> v)
                    SELECT entity_id, '{scheme}', v, d, LEAD(d) OVER (PARTITION BY entity_id ORDER BY d), 'daily_picks', {run_id} FROM s""")
            log(f"classifications: seeded {c.execute('SELECT COUNT(*) FROM classifications').fetchone()[0]} history rows from daily_picks")
        inc = " UNION ALL ".join(
            f"SELECT e.entity_id, '{scheme}' AS k, CAST({col} AS TEXT) AS value FROM stocks s JOIN entities e ON {SEC}=s.sid WHERE {col} IS NOT NULL"
            for scheme, col in (("tier", "cap_tier"), ("sector", "sector"), ("industry", "industry"), ("nifty500", "in_nifty500")))
        changed, opened = scd2(c, "classifications", "scheme", inc, "stocks", run_id)
    log(f"classifications: {changed} changed, {opened} opened today; open rows by scheme: " +
        ", ".join(f"{k}={n}" for k, n in c.execute("SELECT scheme, COUNT(*) FROM classifications WHERE valid_to IS NULL GROUP BY scheme")))


def sync_identifiers(c):
    parts = [f"SELECT e.entity_id, '{ns}' AS k, CAST({col} AS TEXT) AS value FROM stocks s JOIN entities e ON {SEC}=s.sid WHERE {col} IS NOT NULL AND {col} <> ''"
             for ns, col in (("nse_symbol", "ticker"), ("tickertape_slug", "slug"), ("mc_slug", "mc_slug"))]
    with tx(c):
        changed, opened = scd2(c, "identifiers", "namespace", " UNION ALL ".join(parts), "stocks", None)
        n_bse = 0
        if exists(c, "scrip_master"):
            # the BSE instrument master, row for row: keyed by scrip code (one sid can own several codes)
            sm = cols(c, "scrip_master")
            c.execute(f"""INSERT OR IGNORE INTO entities(kind, key, name, attrs, created_at, updated_at)
                SELECT 'instrument', 'BSE:' || scrip_cd, name, json_object('from', 'scrip_master'), '{NOW}', '{NOW}'
                FROM scrip_master WHERE sid IS NULL""")
            c.execute("DROP TABLE IF EXISTS temp._sm")
            c.execute(f"""CREATE TEMP TABLE _sm AS SELECT CAST(m.scrip_cd AS TEXT) AS v, COALESCE(e.entity_id, i.entity_id) AS entity_id,
                    {jobj("m.", sm)} AS attrs
                FROM scrip_master m LEFT JOIN entities e ON {SEC}=m.sid
                LEFT JOIN entities i ON i.kind='instrument' AND i.market='IN' AND i.key='BSE:' || m.scrip_cd""")
            c.execute(f"""UPDATE identifiers SET valid_to='{TODAY}' WHERE namespace='bse_scrip' AND valid_to IS NULL AND valid_from < '{TODAY}'
                AND NOT EXISTS (SELECT 1 FROM _sm WHERE _sm.v=identifiers.value AND _sm.entity_id=identifiers.entity_id)""")
            c.execute("""UPDATE identifiers SET attrs = (SELECT attrs FROM _sm WHERE _sm.v=identifiers.value)
                WHERE namespace='bse_scrip' AND valid_to IS NULL AND attrs IS NOT (SELECT attrs FROM _sm WHERE _sm.v=identifiers.value)""")
            n_bse = c.execute(f"""INSERT OR IGNORE INTO identifiers(entity_id, namespace, value, valid_from, valid_to, attrs)
                SELECT entity_id, 'bse_scrip', v, '{TODAY}', NULL, attrs FROM _sm
                WHERE NOT EXISTS (SELECT 1 FROM identifiers i WHERE i.namespace='bse_scrip' AND i.value=_sm.v AND i.valid_to IS NULL)""").rowcount
    log(f"identifiers: {changed} changed, {opened} opened; bse_scrip +{n_bse}")


# ─────────────────────────── bars ───────────────────────────

def sync_bars(c, full):
    w = "" if full else f"AND p.date >= date('{TODAY}', '-{WINDOW_DAYS} day')"
    wi = "" if full else f"AND p.trade_date >= date('{TODAY}', '-{WINDOW_DAYS} day')"
    upd = "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, prev_close=excluded.prev_close, " \
          "volume=excluded.volume, delivery_qty=excluded.delivery_qty, delivery_pct=excluded.delivery_pct, " \
          "trades=excluded.trades, turnover=excluded.turnover"
    with tx(c):
        n1 = c.execute(f"""INSERT INTO bars_daily(entity_id, date, source, open, high, low, close, prev_close, volume,
                delivery_qty, delivery_pct, trades, turnover, fetched_at)
            SELECT e.entity_id, p.date, COALESCE(p.source, 'unknown'), p.open, p.high, p.low, p.close, p.prev_close, p.volume,
                   p.delivered_qty, p.delivery_pct, p.num_trades, p.traded_value, '{NOW}'
            FROM stock_prices p JOIN entities e ON {SEC}=p.sid WHERE true {w}
            ON CONFLICT(entity_id, date, source) DO UPDATE SET {upd}""").rowcount
        n2 = c.execute(f"""INSERT INTO bars_daily(entity_id, date, source, open, high, low, close, volume, turnover, fetched_at)
            SELECT e.entity_id, p.trade_date, 'nse_index', p.open, p.high, p.low, p.close, p.volume, p.traded_value, COALESCE(p.fetched_at, '{NOW}')
            FROM nse_index_history p JOIN entities e ON e.kind='index' AND e.market='IN' AND e.key=p.index_symbol WHERE true {wi}
            ON CONFLICT(entity_id, date, source) DO UPDATE SET open=excluded.open, high=excluded.high, low=excluded.low,
               close=excluded.close, volume=excluded.volume, turnover=excluded.turnover""").rowcount
        n3 = c.execute(f"""INSERT INTO derivative_bars(underlying_id, symbol, instrument, expiry, strike, option_type, date,
                close, settle, underlying_price, oi, oi_change, volume, trades, fetched_at)
            SELECT e.entity_id, p.symbol, p.instrument_type, p.expiry_date, COALESCE(p.strike, 0), COALESCE(p.option_type, ''),
                   p.trade_date, p.close, p.settle, p.underlying_price, p.oi, p.chg_oi, p.volume, p.num_trades, COALESCE(p.fetched_at, '{NOW}')
            FROM fno_bhav p LEFT JOIN entities e ON {SEC}=p.sid WHERE true {wi}
            ON CONFLICT(symbol, instrument, expiry, strike, option_type, date) DO UPDATE SET close=excluded.close,
               settle=excluded.settle, underlying_price=excluded.underlying_price, oi=excluded.oi, oi_change=excluded.oi_change,
               volume=excluded.volume, trades=excluded.trades""").rowcount
        n4 = c.execute(f"""INSERT INTO bars_daily(entity_id, date, source, close, delivery_pct, attrs, fetched_at)
            SELECT COALESCE(e.entity_id, d.entity_id), h.snapshot_date, 'historical_universe', h.close, h.delivery_pct,
                   json_object('symbol', h.symbol, 'series', h.series, 'requested_date', h.requested_date), '{NOW}'
            FROM historical_universe h LEFT JOIN entities e ON {SEC}=h.sid
            LEFT JOIN entities d ON d.kind='security' AND d.market='IN' AND d.key='NSE:' || h.symbol
            WHERE COALESCE(e.entity_id, d.entity_id) IS NOT NULL
            ON CONFLICT(entity_id, date, source) DO UPDATE SET close=excluded.close, delivery_pct=excluded.delivery_pct,
               attrs=excluded.attrs""").rowcount if exists(c, "historical_universe") else 0
    log(f"bars: stock {n1}, index {n2}, derivative {n3}, historical-universe {n4} rows upserted")


# ─────────────────────────── versioned writes (series, fundamentals, estimates) ───────────────────────────

def versioned(c, target, keys, inc="_vinc"):
    """_vinc(keys..., value, [label,] available_at, fetched_at [, as_of]) → new version when value differs from the
    key's latest version, else bump last_seen_at. Returns (new_versions, confirmed)."""
    k = ", ".join(keys)
    on = " AND ".join(f"l.{x} IS i.{x}" for x in keys)
    has_label = "label" in cols(c, inc, "temp")
    has_asof = "as_of" in cols(c, inc, "temp")
    same = "l.value IS i.value" + (" AND l.label IS i.label" if has_label else "")
    c.execute("DROP TABLE IF EXISTS temp._vlatest")
    c.execute(f"""CREATE TEMP TABLE _vlatest AS SELECT t.* FROM {target} t
        JOIN (SELECT {k}, MAX(fetched_at) AS mf FROM {target} GROUP BY {k}) m USING ({k}) WHERE t.fetched_at = m.mf""")
    c.execute(f"CREATE INDEX temp._vl_ix ON _vlatest({k})")
    extra = (", label" if has_label else "") + (", as_of" if has_asof else "")
    new = c.execute(f"""INSERT OR IGNORE INTO {target}({k}, value{extra}, available_at, fetched_at, last_seen_at)
        SELECT {", ".join("i." + x for x in keys)}, i.value{", i.label" if has_label else ""}{", i.as_of" if has_asof else ""},
               i.available_at,
               CASE WHEN l.fetched_at IS NULL OR i.fetched_at > l.fetched_at THEN i.fetched_at ELSE '{NOW}' END,
               COALESCE(i.fetched_at, '{NOW}')
        FROM {inc} i LEFT JOIN _vlatest l ON {on}
        WHERE l.fetched_at IS NULL OR NOT ({same})""").rowcount
    conf = c.execute(f"""UPDATE {target} AS t SET last_seen_at = x.seen
        FROM (SELECT {", ".join("l." + x for x in keys)}, l.fetched_at AS vf, i.fetched_at AS seen
              FROM {inc} i JOIN _vlatest l ON {on} WHERE ({same}) AND i.fetched_at > l.last_seen_at) AS x
        WHERE {" AND ".join(f"t.{x} IS x.{x}" for x in keys)} AND t.fetched_at = x.vf""").rowcount
    return new, conf


def sync_series(c):
    with tx(c):
        mh = [x for x in ("value", "yoy_change", "mom_change") if x in cols(c, "macro_history")]
        names = []
        for x in mh:
            suf = "" if x == "value" else "." + x.split("_")[0]
            names += [f"macro.{r[0]}{suf}" for r in c.execute("SELECT DISTINCT indicator_id FROM macro_history")]
        num = lambda t, skip: [x for x, ty in coltypes(c, t).items() if x not in skip and ty in ("REAL", "INTEGER")]
        cash_cols = num("fii_dii_cash_flow", {"flow_date", "category"})
        pos_cols = num("fii_dii_positioning", {"trade_date", "client_type"})
        names += [f"fii_dii_cash.{r[0]}.{x}" for r in c.execute("SELECT DISTINCT category FROM fii_dii_cash_flow") for x in cash_cols]
        names += [f"fii_dii_pos.{r[0]}.{x}" for r in c.execute("SELECT DISTINCT client_type FROM fii_dii_positioning") for x in pos_cols]
        names += [f"macro.{r[0]}" for r in c.execute("SELECT indicator_id FROM macro_indicator_meta UNION SELECT indicator_id FROM macro_sector_map")]
        cat_ensure(c, "series", names)
        # series metadata and indicator→sector weights are attributes of the series (catalog spec), not tables
        c.execute("""UPDATE catalog SET unit = m.unit, cadence = m.frequency,
                spec = json_set(COALESCE(catalog.spec, '{}'), '$.meta', json_object('name', m.name, 'source', m.source,
                       'source_ref', m.source_ref, 'category', m.category, 'frequency', m.frequency, 'unit', m.unit, 'description', m.description))
            FROM macro_indicator_meta m WHERE catalog.kind='series' AND catalog.name = 'macro.' || m.indicator_id""")
        c.execute("""UPDATE catalog SET spec = json_set(COALESCE(catalog.spec, '{}'), '$.origin', json(x.j))
            FROM (SELECT indicator_id, json_object('source', json_group_array(DISTINCT source), 'category', json_group_array(DISTINCT category),
                         'unit', json_group_array(DISTINCT unit)) AS j FROM macro_history GROUP BY indicator_id) x
            WHERE catalog.kind='series' AND catalog.name = 'macro.' || x.indicator_id""")
        c.execute("""UPDATE catalog SET spec = json_set(COALESCE(catalog.spec, '{}'), '$.sector_map', json(x.j))
            FROM (SELECT indicator_id, json_group_array(json_object('sector', sector, 'direction', direction, 'weight', weight,
                         'rationale', rationale)) AS j FROM macro_sector_map GROUP BY indicator_id) x
            WHERE catalog.kind='series' AND catalog.name = 'macro.' || x.indicator_id""")
        c.execute("DROP TABLE IF EXISTS temp._vinc")
        sel = []
        for x in mh:
            suf = "" if x == "value" else "." + x.split("_")[0]
            sel.append(f"""SELECT k.catalog_id AS series_id, m.date, m.{x} AS value, m.date AS available_at,
                COALESCE(m.fetched_at, '{NOW}') AS fetched_at FROM macro_history m
                JOIN catalog k ON k.kind='series' AND k.name = 'macro.' || m.indicator_id || '{suf}'""")
        for x in cash_cols:
            sel.append(f"""SELECT k.catalog_id, m.flow_date, m.{x}, m.flow_date, COALESCE(m.fetched_at, '{NOW}') FROM fii_dii_cash_flow m
                JOIN catalog k ON k.kind='series' AND k.name = 'fii_dii_cash.' || m.category || '.{x}'""")
        for x in pos_cols:
            sel.append(f"""SELECT k.catalog_id, m.trade_date, m.{x}, m.trade_date, COALESCE(m.fetched_at, '{NOW}') FROM fii_dii_positioning m
                JOIN catalog k ON k.kind='series' AND k.name = 'fii_dii_pos.' || m.client_type || '.{x}'""")
        c.execute("CREATE TEMP TABLE _vinc AS " + " UNION ALL ".join(sel))
        new, conf = versioned(c, "series_values", ["series_id", "date"])
    log(f"series: {new} new versions, {conf} confirmed")


FACT_LAG = {"Q": 60, "A": 75, "H": 60, "TTM": 60}


def sync_fundamentals(c):
    numeric = lambda t, skip: [x for x, ty in coltypes(c, t).items() if x not in skip and ty in ("REAL", "INTEGER")]
    specs = [  # table, prefix, period_end, period_type SQL, basis SQL, lag SQL, skip cols
        ("quarterly_income", "qi", "end_date", "'Q'", "COALESCE(t.reporting, 'consolidated')", "60", {"period"}),
        ("annual_balance_sheet", "bs", "end_date", "'A'", "'default'", "75", {"period"}),
        ("annual_cash_flow", "cf", "end_date", "'A'", "'default'", "75", {"period"}),
        ("banking_metrics", "bank", "period_end", "t.period_type", "COALESCE(t.source, 'default')", "CASE WHEN t.period_type='A' THEN 75 ELSE 60 END", set()),
        ("shareholding", "sh", "end_date", "'Q'", "'default'", "21", set()),
    ]
    with tx(c):
        sel = []
        for t, pre, pe, pt, basis, lag, skip in specs:
            nc = numeric(t, skip | {"sid", pe})
            cat_ensure(c, "metric", [f"{pre}.{x}" for x in nc])
            for x in nc:
                sel.append(f"""SELECT e.entity_id, k.catalog_id AS metric_id, t.{pe} AS period_end, {pt} AS period_type,
                    {basis} AS basis, '{t}' AS source, t.{x} AS value, date(t.{pe}, '+' || ({lag}) || ' day') AS available_at,
                    COALESCE(t.fetched_at, '{NOW}') AS fetched_at
                    FROM {t} t JOIN entities e ON {SEC}=t.sid JOIN catalog k ON k.kind='metric' AND k.name='{pre}.{x}'
                    WHERE t.{pe} IS NOT NULL""")
        cat_ensure(c, "metric", [f"screener.{r[0]}" for r in c.execute("SELECT DISTINCT line_item FROM fundamentals_screener")])
        sel.append(f"""SELECT e.entity_id, k.catalog_id, t.period_end, t.period_type, 'default', 'fundamentals_screener', t.value,
                COALESCE(t.filing_date, date(t.period_end, '+' || (CASE WHEN t.period_type IN ('annual','A') THEN 75 ELSE 60 END) || ' day')),
                COALESCE(t.fetched_at, '{NOW}')
            FROM fundamentals_screener t JOIN entities e ON {SEC}=t.sid
            JOIN catalog k ON k.kind='metric' AND k.name = 'screener.' || t.line_item""")
        c.execute("DROP TABLE IF EXISTS temp._vinc")
        c.execute("CREATE TEMP TABLE _vinc AS " + " UNION ALL ".join(sel))
        new, conf = versioned(c, "fundamentals", ["entity_id", "metric_id", "period_end", "period_type", "basis", "source"])
    log(f"fundamentals: {new} new versions, {conf} confirmed")


def sync_estimates(c):
    ac = coltypes(c, "analyst_consensus")
    ac_num = [x for x, ty in ac.items() if x not in ("sid", "fetched_at") and ty in ("REAL", "INTEGER")]
    ac_txt = [x for x, ty in ac.items() if x not in ("sid", "fetched_at") and ty not in ("REAL", "INTEGER")]
    acs = coltypes(c, "analyst_consensus_snapshots")
    acs_num = [x for x, ty in acs.items() if x not in ("sid", "snapshot_date", "source", "fetched_at") and ty in ("REAL", "INTEGER")]
    acs_txt = [x for x, ty in acs.items() if x not in ("sid", "snapshot_date", "source", "fetched_at") and ty not in ("REAL", "INTEGER")]
    with tx(c):
        cat_ensure(c, "metric", [f"ac.{x}" for x in ac_num + ac_txt] + [f"acs.{x}" for x in acs_num + acs_txt]
                   + [f"fh.{r[0]}" for r in c.execute("SELECT DISTINCT metric FROM forecast_history")]
                   + [f"fh.{r[0]}.change" for r in c.execute("SELECT DISTINCT metric FROM forecast_history")]
                   + [f"ae.{r[0]}" for r in c.execute("SELECT DISTINCT metric FROM analyst_estimates")])
        # versioned: the current-consensus row (overwritten daily) and Tickertape forecasts (overwritten monthly)
        sel = [f"""SELECT e.entity_id, k.catalog_id AS metric_id, '12M' AS target_period, 'analyst_consensus' AS source,
                    {("t." + x) if x in ac_num else "NULL"} AS value, {("CAST(t." + x + " AS TEXT)") if x in ac_txt else "NULL"} AS label,
                    COALESCE(t.fetched_at, '{NOW}') AS available_at, COALESCE(t.fetched_at, '{NOW}') AS fetched_at
                   FROM analyst_consensus t JOIN entities e ON {SEC}=t.sid JOIN catalog k ON k.kind='metric' AND k.name='ac.{x}'
                   WHERE t.{x} IS NOT NULL""" for x in ac_num + ac_txt]
        sel.append(f"""SELECT e.entity_id, k.catalog_id, t.date, 'forecast_history', t.value, NULL, COALESCE(t.fetched_at, '{NOW}'),
                    COALESCE(t.fetched_at, '{NOW}')
                   FROM forecast_history t JOIN entities e ON {SEC}=t.sid JOIN catalog k ON k.kind='metric' AND k.name='fh.' || t.metric""")
        sel.append(f"""SELECT e.entity_id, k.catalog_id, t.date, 'forecast_history', t.change, NULL, COALESCE(t.fetched_at, '{NOW}'),
                    COALESCE(t.fetched_at, '{NOW}')
                   FROM forecast_history t JOIN entities e ON {SEC}=t.sid JOIN catalog k ON k.kind='metric' AND k.name='fh.' || t.metric || '.change'
                   WHERE t.change IS NOT NULL""")
        c.execute("DROP TABLE IF EXISTS temp._vinc")
        c.execute("CREATE TEMP TABLE _vinc AS " + " UNION ALL ".join(sel))
        new, conf = versioned(c, "estimates", ["entity_id", "metric_id", "target_period", "source"])
        # monthly snapshots are observations: every snapshot row is kept (as_of = the snapshot date)
        n_acs = 0
        for x in acs_num + acs_txt:
            n_acs += c.execute(f"""INSERT OR IGNORE INTO estimates(entity_id, metric_id, target_period, source, value, label, as_of,
                    available_at, fetched_at, last_seen_at)
                SELECT e.entity_id, k.catalog_id, '12M', 'acs:' || t.source, {("t." + x) if x in acs_num else "NULL"},
                       {("CAST(t." + x + " AS TEXT)") if x in acs_txt else "NULL"}, t.snapshot_date,
                       COALESCE(t.fetched_at, t.snapshot_date), COALESCE(t.fetched_at, t.snapshot_date), COALESCE(t.fetched_at, t.snapshot_date)
                FROM analyst_consensus_snapshots t JOIN entities e ON {SEC}=t.sid JOIN catalog k ON k.kind='metric' AND k.name='acs.{x}'
                WHERE t.{x} IS NOT NULL""").rowcount
        # Yahoo estimates are already versioned upstream (plan 0018): copy
        n_ae = c.execute(f"""INSERT OR IGNORE INTO estimates(entity_id, metric_id, target_period, source, value, label,
                available_at, fetched_at, last_seen_at)
            SELECT e.entity_id, k.catalog_id, t.target_period, 'ae:' || t.source, t.value, t.label, t.available_at, t.fetched_at, t.last_seen_at
            FROM analyst_estimates t JOIN entities e ON {SEC}=t.sid JOIN catalog k ON k.kind='metric' AND k.name='ae.' || t.metric""").rowcount
        c.execute(f"""UPDATE estimates AS t SET last_seen_at = a.last_seen_at FROM analyst_estimates a
            JOIN entities e ON {SEC}=a.sid JOIN catalog k ON k.kind='metric' AND k.name='ae.' || a.metric
            WHERE t.entity_id=e.entity_id AND t.metric_id=k.catalog_id AND t.target_period=a.target_period
              AND t.source='ae:' || a.source AND t.fetched_at=a.fetched_at AND t.last_seen_at < a.last_seen_at""")
    log(f"estimates: {new} new versions, {conf} confirmed; snapshots +{n_acs}; yahoo +{n_ae}")


# ─────────────────────────── events ───────────────────────────

# table: (event type, source_key SQL, entity SQL (t.<col>) or None, event_time SQL, available_at SQL, subtype SQL, cols kept out of payload)
EVENT_SPECS = {
    "bse_announcements": ("bse_announcement", "t.news_id", "t.sid", "t.dt_tm", "COALESCE(t.dissem_dt, t.dt_tm)",
                          "COALESCE(t.category, '') || '|' || COALESCE(t.subcategory, '')", {"news_id", "sid", "dt_tm", "category", "subcategory", "fetched_at"}),
    "corporate_actions": ("corporate_action", "t.id", "t.sid", "COALESCE(t.ex_date, substr(t.fetched_at, 1, 10))", "COALESCE(t.ex_date, substr(t.fetched_at, 1, 10))",
                          "t.ind", {"id", "sid", "fetched_at"}),
    "insider_trades": ("insider_trade", "t.id", "t.sid", "t.trade_date", "t.trade_date", "t.transaction_type", {"id", "sid", "fetched_at"}),
    "bulk_deals": ("bulk_deal", "t.id", "t.sid", "t.deal_date", "t.deal_date", "t.buy_sell", {"id", "sid", "fetched_at"}),
    "short_selling_data": ("short_sale", "t.id", "t.sid", "t.short_date", "t.short_date", "NULL", {"id", "sid", "fetched_at"}),
    "surveillance_flags": ("surveillance_flag", "t.sid || '|' || t.flag_type || '|' || t.flag_date", "t.sid", "t.flag_date", "t.flag_date",
                           "t.flag_type", {"sid", "fetched_at"}),
    "earnings_calendar": ("earnings_date", "t.id", "t.sid", "t.date", "COALESCE(t.added_date, t.date)", "t.purpose", {"id", "sid"}),
    "regulatory_events": ("regulatory_event", "t.event_id", None, "COALESCE(t.published_at, substr(t.fetched_at, 1, 10))",
                          "COALESCE(t.published_at, substr(t.fetched_at, 1, 10))", "t.ministry", {"event_id", "fetched_at", "full_text"}),
    "policy_events": ("policy_event", "t.event_date || '|' || t.sector || '|' || t.title", "SECTOR:t.sector", "t.event_date", "t.event_date",
                      "t.event_type", set()),
    "news_articles": ("news_article", "t.article_id", None, "COALESCE(t.published_at, t.fetched_at)", "COALESCE(t.published_at, t.fetched_at)",
                      "t.source", {"article_id", "fetched_at"}),
    "broker_recommendations": ("broker_reco", "t.sid || '|' || t.broker || '|' || t.reco_date || '|' || COALESCE(t.target_price, '')", "t.sid",
                               "t.reco_date", "COALESCE(t.fetched_at, t.reco_date)", "t.reco_type", {"sid", "fetched_at"}),
}


def _entity_join(ent):
    if ent is None:
        return "", "NULL"
    if ent.startswith("SECTOR:"):
        return (f"LEFT JOIN entities e ON e.kind='sector' AND e.market='IN' AND e.key={ent[7:]}", "e.entity_id")
    return f"LEFT JOIN entities e ON {SEC}={ent}", "e.entity_id"


def sync_events(c, full, since):
    wm = None if full or not since else since[:10]
    tot = {}
    with tx(c):
        cat_ensure(c, "event_type", [s[0] for s in EVENT_SPECS.values()] + ["price_adjustment"]
                   + [r[0] for r in c.execute("SELECT DISTINCT type FROM market_events")])
        types = cat_ids(c, "event_type")
        for t, (etype, key, ent, et, av, sub, skip) in EVENT_SPECS.items():
            if not exists(c, t):
                continue
            pc = [x for x in cols(c, t) if x not in skip]
            ej, eid = _entity_join(ent)
            where = f"WHERE substr(COALESCE(t.fetched_at, ''), 1, 10) >= '{wm}'" if (wm and "fetched_at" in cols(c, t)) else ""
            tot[t] = c.execute(f"""INSERT OR IGNORE INTO events(type_id, subtype, entity_id, event_time, available_at, source, source_key, payload, fetched_at)
                SELECT {types[etype]}, {sub}, {eid}, {et}, {av}, '{t}', CAST({key} AS TEXT), {jobj("t.", pc)},
                       {"COALESCE(t.fetched_at, '" + NOW + "')" if "fetched_at" in cols(c, t) else "'" + NOW + "'"}
                FROM {t} t {ej} {where}""").rowcount
        # market_events is already event-shaped (plan 0018)
        tot["market_events"] = c.execute(f"""INSERT OR IGNORE INTO events(type_id, subtype, entity_id, event_time, available_at, source, source_key, payload, fetched_at)
            SELECT k.catalog_id, t.subtype, e.entity_id, t.event_time, t.available_at, t.source, t.source_key, t.payload, t.fetched_at
            FROM market_events t JOIN catalog k ON k.kind='event_type' AND k.name=t.type LEFT JOIN entities e ON {SEC}=t.sid""").rowcount
        # derived events are replaced whole by their producer (corporate_adjustments is rebuilt atomically daily)
        c.execute(f"DELETE FROM events WHERE type_id={types['price_adjustment']} AND source='corporate_adjustments'")
        tot["corporate_adjustments"] = c.execute(f"""INSERT INTO events(type_id, subtype, entity_id, event_time, available_at, source, source_key, payload, fetched_at)
            SELECT {types['price_adjustment']}, NULL, e.entity_id, t.ex_date, t.ex_date, 'corporate_adjustments', t.sid || '|' || t.ex_date,
                   json_object('factor', t.factor, 'n_events', t.n_events, 'inds', t.inds, 'subjects', t.subjects), COALESCE(t.fetched_at, '{NOW}')
            FROM corporate_adjustments t JOIN entities e ON {SEC}=t.sid""").rowcount
        # news → stocks links
        tot["news_article_stocks"] = c.execute(f"""INSERT OR IGNORE INTO event_links(event_id, entity_id, role)
            SELECT v.event_id, e.entity_id, COALESCE(n.match_location, 'mention')
            FROM news_article_stocks n JOIN events v ON v.type_id={types['news_article']} AND v.source='news_articles' AND v.source_key=n.article_id
            JOIN entities e ON {SEC}=n.sid""").rowcount
    log("events: " + ", ".join(f"{k}+{v}" for k, v in tot.items()))


# ─────────────────────────── documents ───────────────────────────

def _hash(*parts):
    h = hashlib.sha1()
    for p in parts:
        h.update(b"\x00" + (p if isinstance(p, bytes) else str(p).encode()))
    return h.hexdigest()


def _insert_docs(c, type_id, rows):
    """rows: dicts with entity_id, event_id, doc_date, available_at, source, source_key, title, fields(dict), body(str|None), model."""
    out = []
    for r in rows:
        body = r.get("body")
        fields = json.dumps(r.get("fields") or {}, default=str, sort_keys=True)
        out.append((type_id, r.get("entity_id"), r.get("event_id"), r["doc_date"], r["available_at"], r["source"], str(r["source_key"]),
                    r.get("model"), r.get("title"), fields, zlib.compress(body.encode()) if body else None,
                    _hash(fields, body or ""), r.get("status", "valid"), NOW))
    n = 0
    for i in range(0, len(out), 5000):
        n += c.executemany("""INSERT OR IGNORE INTO documents(type_id, entity_id, event_id, doc_date, available_at, source, source_key,
            model, title, fields, body, content_hash, status, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", out[i:i + 5000]).rowcount
    return n


def _supersede(c, type_id):
    c.execute(f"""UPDATE documents SET status='superseded' WHERE type_id={type_id} AND status='valid' AND doc_id < (
        SELECT MAX(d.doc_id) FROM documents d WHERE d.type_id=documents.type_id AND d.source=documents.source AND d.source_key=documents.source_key)""")


def _df(c, sql):
    return pd.read_sql(sql, c)


def _ent_map(c, kind):
    return {k: i for i, k in c.execute("SELECT entity_id, key FROM entities WHERE kind=? AND market='IN'", (kind,))}


def _clean(v):
    if v is None or (isinstance(v, float) and v != v):
        return None
    return v


def sync_documents(c, full, since):
    wm = None if full or not since else since[:10]
    sec, sct = _ent_map(c, "security"), _ent_map(c, "sector")
    specs = [  # table, doc type, key cols, entity (col, map), date col, available SQL-free fn, title col, body col, time col for incremental
        ("transcripts", "transcript", ["source_url"], ("sid", sec), "doc_date",
         lambda r: r.get("bse_filing_date") or r.get("announce_date") or r.get("doc_date"), "period_label", "raw_text", "fetched_at"),
        ("news_enriched", "news_classification", ["article_id"], None, "classified_at", lambda r: r.get("classified_at"), "one_liner", None, "classified_at"),
        ("regulatory_signals", "regulatory_classification", ["event_id", "sector"], ("sector", sct), "classified_at",
         lambda r: r.get("classified_at"), None, None, "classified_at"),
        ("regulatory_events", "regulatory_text", ["event_id"], None, "published_at", lambda r: r.get("published_at") or r.get("fetched_at"),
         "title", "full_text", "fetched_at"),
        ("news_briefs", "news_brief", ["brief_date"], None, "brief_date", lambda r: r.get("generated_at") or r.get("brief_date"), None, None, "generated_at"),
        ("sector_dossiers", "sector_dossier", ["sector", "snapshot_date"], ("sector", sct), "snapshot_date",
         lambda r: r.get("generated_at") or r.get("snapshot_date"), None, None, "generated_at"),
        ("sector_metadata", "sector_metadata", ["sector", "source"], ("sector", sct), "generated_at",
         lambda r: r.get("generated_at"), "industry", "payload", "generated_at"),
    ]
    tot = {}
    ev = {}
    with tx(c):
        cat_ensure(c, "doc_type", [s[1] for s in specs])
        dtypes = cat_ids(c, "doc_type")
        etypes = cat_ids(c, "event_type")
        for key_src, et in (("news_articles", "news_article"), ("regulatory_events", "regulatory_event")):
            ev[key_src] = {k: i for i, k in c.execute("SELECT event_id, source_key FROM events WHERE type_id=? AND source=?", (etypes.get(et), key_src))}
        for t, dtype, keys, ent, dcol, avail, tcol, bcol, tcol_inc in specs:
            if not exists(c, t):
                continue
            where = f"WHERE substr(COALESCE({tcol_inc}, ''), 1, 10) >= '{wm}'" if wm and tcol_inc in cols(c, t) else ""
            if t == "regulatory_events":
                where = (where + " AND " if where else "WHERE ") + "full_text IS NOT NULL AND full_text <> ''"
            df = _df(c, f"SELECT * FROM {t} {where}")
            rows = []
            for r in df.to_dict("records"):
                r = {k: _clean(v) for k, v in r.items()}
                d = str(r.get(dcol) or r.get("fetched_at") or NOW)[:10]
                fields = {k: v for k, v in r.items() if k not in keys and k not in (bcol, tcol)}
                eid = None
                if t in ("news_enriched",):
                    eid = ev["news_articles"].get(r["article_id"])
                elif t in ("regulatory_signals", "regulatory_events"):
                    eid = ev["regulatory_events"].get(r["event_id"])
                rows.append({"entity_id": ent[1].get(r.get(ent[0])) if ent else None, "event_id": eid, "doc_date": d,
                             "available_at": str(avail(r) or d), "source": t, "source_key": "|".join(str(r[k]) for k in keys),
                             "title": r.get(tcol) if tcol else None, "fields": fields, "body": r.get(bcol) if bcol else None,
                             "model": r.get("model"),
                             "status": "invalid" if t == "sector_dossiers" and r.get("valid") == 0 else "valid"})
            tot[t] = _insert_docs(c, dtypes[dtype], rows)
            _supersede(c, dtypes[dtype])
    log("documents: " + ", ".join(f"{k}+{v}" for k, v in tot.items()))


# ─────────────────────────── features ───────────────────────────

# table: (entity col, entity kind, date col, split col (its value goes into the feature name) or None, name mode)
#   name mode: "bare" = the column name is the feature (the PIT panel's canonical factor columns),
#              "prefix" = "<table>.<col>" (unambiguous, stable across renames of other tables)
FEATURE_TABLES = {
    **{t: ("sid", "security", "snapshot_date", None, "prefix") for t in (
        "accruals_scores", "asset_tangibility_scores", "capex_to_dep_scores", "cash_conversion_cycle_scores", "consensus_signals",
        "debt_structure_scores", "dio_change_yoy_scores", "dso_change_yoy_scores", "fcf_margin_scores", "fcf_yield_scores",
        "financial_signal_scores", "forensic_scores", "goodwill_to_assets_scores", "gross_profitability_scores",
        "interest_coverage_scores", "inventory_turnover_scores", "management_scores", "managerial_ability_scores", "multibagger_scores",
        "nwc_to_revenue_scores", "operating_margin_trend_scores", "piotroski_scores", "promoter_signals", "revenue_cv_scores",
        "roic_scores", "roiic_scores", "sales_growth_relative_scores", "sentiment_scores", "sga_to_revenue_change_scores",
        "share_momentum_scores", "sloan_accruals_full_scores", "smart_money_scores", "working_capital_intensity_scores",
        "daily_snapshots")},
    "nlp_scores": ("sid", "security", "doc_date", "doc_type", "prefix"),      # available_date is a value (date kind)
    "insider_signals": ("sid", "security", "snapshot_date", "signal_type", "prefix"),
    "fno_iv_history": ("sid|symbol", "security|index", "trade_date", None, "prefix"),
    "fno_pcr_history": ("sid|symbol", "security|index", "trade_date", None, "prefix"),
    "universe_eligibility": ("sid", "security", "snapshot_date", "signal", "prefix"),
    "macro_indicators": (None, "market", "snapshot_date", "indicator", "prefix"),
    "regime_state": (None, "market", "updated_at", None, "prefix"),
    "macro_sector_signals": ("sector", "sector", "snapshot_date", None, "prefix"),
    "macro_sector_signals_pit": ("sector", "sector", "snapshot_date", None, "prefix"),
    "sector_force_breakdown": ("sector", "sector", "snapshot_date", "force", "prefix"),
    "sector_analyst_breadth_pit": ("sector", "sector", "snapshot_date", None, "prefix"),
    "sector_sentiment_breadth_pit": ("sector", "sector", "snapshot_date", None, "prefix"),
    "sector_briefs": ("sector", "sector", "snapshot_date", None, "prefix"),
    "daily_snapshots_pit": ("sid", "security", "snapshot_date", None, "bare"),
    "daily_snapshots_pit_v1": ("sid", "security", "snapshot_date", None, "v1"),
}
# columns that are write-time metadata or live elsewhere (tier/sector history → classifications)
FEATURE_SKIP = {"computed_at", "reconstructed_at", "imported_at", "refreshed_at", "id", "created_at"}
TIER_TO_CLS = {("daily_snapshots_pit", "cap_tier"): "tier@pit", ("daily_snapshots_pit_v1", "cap_tier"): "tier@v1",
               ("daily_snapshots_pit_v1", "sector"): "sector@v1", ("daily_snapshots_pit_v1", "ticker"): "ticker@v1"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
PLAIN_DATE_COLS = {"snapshot_date", "trade_date", "doc_date"}   # stored as YYYY-MM-DD (checked by reconcile parity)
# a row's existence is itself a fact where every value can be NULL (the PIT panel: "in the universe that day")
MEMBERSHIP = {"daily_snapshots_pit": "in_universe", "daily_snapshots_pit_v1": "v1.in_universe"}


def _fname(t, mode, col, split=None):
    base = col if mode == "bare" else (f"v1.{col}" if mode == "v1" else f"{t}.{col}")
    if split is not None:
        base = f"{t}.{split}.{col}" if mode == "prefix" else f"{base}.{split}"
    return base


def _classify_text(c, t, col):
    """date | enum | text — decided once, remembered in the catalog (kind 'dataset_column')."""
    name = f"{t}.{col}"
    spec = cat_spec(c, "dataset_column", name)
    if spec.get("text_kind"):
        return spec
    sample = [r[0] for r in c.execute(f"SELECT DISTINCT {q(col)} FROM {t} WHERE {q(col)} IS NOT NULL LIMIT {ENUM_MAX + 1}")]
    if sample and all(isinstance(v, str) and DATE_RE.match(v) for v in sample) and len(sample) > 3:
        spec = {"text_kind": "date"}
    elif len(sample) <= ENUM_MAX:
        spec = {"text_kind": "enum", "codes": {}}
    else:
        spec = {"text_kind": "text"}
    cat_ensure(c, "dataset_column", [name])
    cat_set_spec(c, "dataset_column", name, spec)
    return spec


def _enum_codes(c, t, col, spec, where):
    codes = spec.setdefault("codes", {})
    for (v,) in c.execute(f"SELECT DISTINCT CAST({q(col)} AS TEXT) FROM {t} t {where} {'AND' if where else 'WHERE'} {q(col)} IS NOT NULL ORDER BY 1"):
        if v not in codes:
            codes[v] = len(codes) + 1
    cat_set_spec(c, "dataset_column", f"{t}.{col}", spec)
    return codes


def sync_features(c, run_id, full, since):
    stats = {}
    for t, (ecol, ekind, dcol, split, mode) in FEATURE_TABLES.items():
        if not exists(c, t):
            continue
        t0 = time.time()
        ct = coltypes(c, t)
        key_cols = {x for x in (ecol or "").split("|") if x} | {dcol} | ({split} if split else set())
        value_cols = [x for x in ct if x not in key_cols and x not in FEATURE_SKIP and (t, x) not in TIER_TO_CLS]
        dexpr = f"substr(t.{dcol}, 1, 10)"
        # entity expression
        if ekind == "security":
            ej, eid = f"JOIN entities e ON {SEC}=t.{ecol}", "e.entity_id"
        elif ekind == "security|index":
            ej = (f"JOIN entities e ON e.market='IN' AND ((t.sid IS NOT NULL AND e.kind='security' AND e.key=t.sid) "
                  f"OR (t.sid IS NULL AND e.kind='index' AND e.key='FNO:' || t.symbol))")
            eid = "e.entity_id"
            value_cols = [x for x in value_cols if x not in ("sid", "symbol")]
        elif ekind == "sector":
            ej, eid = f"JOIN entities e ON e.kind='sector' AND e.market='IN' AND e.key=t.{ecol}", "e.entity_id"
        else:
            ej, eid = "JOIN entities e ON e.kind='market' AND e.key='IN'", "e.entity_id"
        with tx(c):
            # which dates to (re)write: all on --full, else the last window + dates not yet mirrored + rewritten ones
            c.execute("DROP TABLE IF EXISTS temp._dates")
            if full:
                c.execute(f"CREATE TEMP TABLE _dates AS SELECT DISTINCT {dexpr} AS d FROM {t} t WHERE t.{dcol} IS NOT NULL")
            else:
                wcol = next((x for x in ("computed_at", "reconstructed_at", "refreshed_at") if x in ct), None)
                rew = f"UNION SELECT DISTINCT {dexpr} FROM {t} t WHERE substr(t.{wcol},1,19) >= '{since[:19]}'" if (wcol and since) else ""
                c.execute(f"""CREATE TEMP TABLE _dates AS SELECT d FROM (
                    SELECT DISTINCT {dexpr} AS d FROM {t} t WHERE t.{dcol} >= date('{TODAY}', '-{WINDOW_DAYS} day') {rew})""")
                # plus dates the mirror has never seen (first run of a table, or a backfill upstream)
                seen_fid = c.execute("SELECT catalog_id FROM catalog WHERE kind='feature' AND json_extract(spec, '$.origin_table')=? LIMIT 1", (t,)).fetchone()
                if seen_fid is None:
                    c.execute(f"INSERT INTO _dates SELECT DISTINCT {dexpr} FROM {t} t WHERE t.{dcol} IS NOT NULL")
            c.execute("DELETE FROM _dates WHERE d IS NULL")
            c.execute("CREATE INDEX temp._dates_ix ON _dates(d)")
            n_dates = c.execute("SELECT COUNT(*) FROM _dates").fetchone()[0]
            if n_dates == 0:
                continue
            # plain date columns filter on the raw column (index-friendly); timestamp columns need the substr
            dw = (f"WHERE t.{dcol} IN (SELECT d FROM _dates)" if dcol in PLAIN_DATE_COLS else f"WHERE {dexpr} IN (SELECT d FROM _dates)")
            splits = [None] if not split else [r[0] for r in c.execute(f"SELECT DISTINCT {split} FROM {t} WHERE {split} IS NOT NULL")]
            n_rows = n_docs = 0
            text_cols = []
            for col in value_cols:
                ty = ct[col]
                if ty in ("REAL", "INTEGER", "NUMERIC", "INT"):
                    kind, vexpr = "num", f"t.{q(col)}"
                else:
                    spec = _classify_text(c, t, col)
                    kind = spec["text_kind"]
                    if kind == "date":
                        vexpr = f"COALESCE(julianday(t.{q(col)}), julianday(substr(t.{q(col)}, 1, 10)))"   # keeps the time part
                    elif kind == "enum":
                        codes = _enum_codes(c, t, col, spec, dw)
                        vexpr = "CASE CAST(t." + q(col) + " AS TEXT) " + " ".join(
                            f"WHEN '{k.replace(chr(39), chr(39) * 2)}' THEN {v}" for k, v in codes.items()) + " END" if codes else "NULL"
                    else:
                        text_cols.append(col)
                        continue
                for sv in splits:
                    fname = _fname(t, mode, col, sv)
                    fspec = {"origin_table": t, "origin_column": col, "value_kind": kind}
                    if sv is not None:
                        fspec["split"] = {split: sv}
                    if kind == "enum":
                        fspec["codes_ref"] = f"dataset_column:{t}.{col}"
                    cat_ensure(c, "feature", [fname], spec={fname: fspec})
                    fid = c.execute("SELECT catalog_id FROM catalog WHERE kind='feature' AND name=?", (fname,)).fetchone()[0]
                    if not c.execute("SELECT json_extract(spec,'$.origin_table') FROM catalog WHERE catalog_id=?", (fid,)).fetchone()[0]:
                        cat_set_spec(c, "feature", fname, {**cat_spec(c, "feature", fname), **fspec})
                    c.execute(f"DELETE FROM feature_values WHERE feature_id={fid} AND date IN (SELECT d FROM _dates)")
                    sw = "" if sv is None else f"AND t.{split} = '{str(sv).replace(chr(39), chr(39) * 2)}'"
                    n_rows += c.execute(f"""INSERT INTO feature_values(feature_id, date, entity_id, value, run_id)
                        SELECT {fid}, {dexpr}, {eid}, {vexpr}, {run_id} FROM {t} t {ej} {dw} {sw} AND t.{q(col)} IS NOT NULL
                        ORDER BY 2, 3
                        ON CONFLICT(feature_id, date, entity_id) DO UPDATE SET value=excluded.value, run_id=excluded.run_id""").rowcount
            if t in MEMBERSHIP:
                fname = MEMBERSHIP[t]
                cat_ensure(c, "feature", [fname], spec={fname: {"origin_table": t, "value_kind": "membership"}})
                fid = c.execute("SELECT catalog_id FROM catalog WHERE kind='feature' AND name=?", (fname,)).fetchone()[0]
                c.execute(f"DELETE FROM feature_values WHERE feature_id={fid} AND date IN (SELECT d FROM _dates)")
                n_rows += c.execute(f"""INSERT INTO feature_values(feature_id, date, entity_id, value, run_id)
                    SELECT {fid}, {dexpr}, {eid}, 1, {run_id} FROM {t} t {ej} {dw} AND true
                    ON CONFLICT(feature_id, date, entity_id) DO UPDATE SET value=excluded.value, run_id=excluded.run_id""").rowcount
            # PIT panel tiers / v1 labels → classifications history under their own schemes
            for (tt, col), scheme in TIER_TO_CLS.items():
                if tt != t:
                    continue
                c.execute(f"DELETE FROM classifications WHERE scheme='{scheme}'")
                c.execute(f"""INSERT INTO classifications(entity_id, scheme, value, valid_from, valid_to, source, run_id)
                    WITH x AS (SELECT {eid} AS entity_id, {dexpr} AS d, t.{col} AS v,
                                      LAG(t.{col}) OVER (PARTITION BY t.{ecol} ORDER BY t.{dcol}) AS pv
                               FROM {t} t {ej} WHERE t.{col} IS NOT NULL),
                         s AS (SELECT entity_id, d, v FROM x WHERE pv IS NULL OR pv <> v)
                    SELECT entity_id, '{scheme}', v, d, LEAD(d) OVER (PARTITION BY entity_id ORDER BY d), '{t}', {run_id} FROM s""")
            # free text → documents (one per entity/date/column)
            if text_cols:
                cat_ensure(c, "doc_type", [f"{t}.{x}" for x in text_cols])
                dtypes = cat_ids(c, "doc_type")
                sel = ", ".join(q(x) for x in text_cols)
                keysel = ", ".join(q(x) for x in sorted(key_cols))
                df = _df(c, f"SELECT {keysel}, {sel}, {eid} AS _eid FROM {t} t {ej} {dw}")
                for col in text_cols:
                    rows = []
                    for r in df[df[col].notna()].to_dict("records"):
                        d = str(r[dcol])[:10]
                        rows.append({"entity_id": r["_eid"], "doc_date": d, "available_at": d, "source": t,
                                     "source_key": "|".join(str(r[k]) for k in sorted(key_cols)) + f"|{col}",
                                     "fields": {"value": r[col]}})
                    n_docs += _insert_docs(c, dtypes[f"{t}.{col}"], rows)
                    _supersede(c, dtypes[f"{t}.{col}"])
        stats[t] = (n_dates, n_rows, n_docs, round(time.time() - t0, 1))
        log(f"  feature table {t}: {n_dates} dates, {n_rows} values, {n_docs} docs in {stats[t][3]}s")
    log("features: " + ", ".join(f"{t}[{d}d {r}v {dd}doc {s}s]" for t, (d, r, dd, s) in stats.items()))


# ─────────────────────────── decisions ───────────────────────────

def sync_decisions(c, full, sync_run):
    import factors  # noqa: F401
    tiers = config.TIERS
    sel_case = "CASE " + " ".join(f"WHEN d.cap_tier='{t}' THEN (d.rank <= {int(s.get('picks') or 0)})" for t, s in tiers.items()) + " ELSE 0 END"
    dp = cols(c, "daily_picks")
    attrs = [x for x in dp if x not in ("sid", "pick_date", "cap_tier", "rank", "final_score", "integrity_status", "uhs_score")]
    win = "" if full else f"WHERE pick_date >= date('{TODAY}', '-{WINDOW_DAYS} day') OR pick_date NOT IN (SELECT as_of_date FROM runs WHERE kind='morning' AND EXISTS (SELECT 1 FROM picks p WHERE p.run_id=runs.run_id))"
    with tx(c):
        for src, dcol in (("daily_picks", "pick_date"), ("portfolio_weights", "asof_date"), ("pick_outcomes", "pick_date"),
                          ("portfolio_outcomes", "asof_date"), ("pit_replay_snapshots", "snapshot_date")):
            ensure_runs(c, "morning", f"SELECT DISTINCT {dcol} FROM {src}")
        runs = "JOIN runs r ON r.kind='morning' AND r.as_of_date = d.pick_date"
        c.execute("DROP TABLE IF EXISTS temp._pd")
        c.execute(f"CREATE TEMP TABLE _pd AS SELECT DISTINCT pick_date AS d FROM daily_picks {win}")
        c.execute("DELETE FROM picks WHERE run_id IN (SELECT r.run_id FROM runs r JOIN _pd ON r.kind='morning' AND r.as_of_date=_pd.d)")
        n_p = c.execute(f"""INSERT INTO picks(run_id, entity_id, tier, rank, score, selected, gate, uhs, attrs)
            SELECT r.run_id, e.entity_id, COALESCE(d.cap_tier, '?'), d.rank, d.final_score, {sel_case}, d.integrity_status, d.uhs_score,
                   {jobj("d.", attrs)}
            FROM daily_picks d {runs} JOIN entities e ON {SEC}=d.sid WHERE d.pick_date IN (SELECT d FROM _pd)""").rowcount
        pw = [x for x in cols(c, "portfolio_weights") if x not in ("asof_date", "sid", "weight")]
        c.execute("""DELETE FROM book_weights WHERE run_id IN (SELECT r.run_id FROM runs r WHERE r.kind='morning' AND r.as_of_date IN
            (SELECT DISTINCT asof_date FROM portfolio_weights))""")
        n_b = c.execute(f"""INSERT INTO book_weights(run_id, entity_id, weight, attrs)
            SELECT r.run_id, e.entity_id, d.weight, {jobj("d.", pw)} FROM portfolio_weights d
            JOIN runs r ON r.kind='morning' AND r.as_of_date=d.asof_date JOIN entities e ON {SEC}=d.sid""").rowcount
        po = [x for x in cols(c, "pick_outcomes") if x not in ("sid", "pick_date", "window_days", "exit_date", "fwd_return_pct",
                                                                 "bench_return_pct", "excess_return_pct", "computed_at")]
        n_o = c.execute(f"""INSERT INTO outcomes(run_id, entity_id, horizon_days, start_date, end_date, ret, bench_ret, excess, attrs, computed_at)
            SELECT r.run_id, e.entity_id, d.window_days, d.pick_date, d.exit_date, d.fwd_return_pct, d.bench_return_pct, d.excess_return_pct,
                   {jobj("d.", po)}, COALESCE(d.computed_at, '{NOW}')
            FROM pick_outcomes d JOIN runs r ON r.kind='morning' AND r.as_of_date=d.pick_date JOIN entities e ON {SEC}=d.sid WHERE true
            ON CONFLICT(run_id, entity_id, horizon_days) DO UPDATE SET end_date=excluded.end_date, ret=excluded.ret,
               bench_ret=excluded.bench_ret, excess=excluded.excess, attrs=excluded.attrs, computed_at=excluded.computed_at""").rowcount
        pco = [x for x in cols(c, "portfolio_outcomes") if x not in ("asof_date", "window_days", "hrp_return_pct", "bench_return_pct",
                                                                       "hrp_excess_pct", "computed_at")]
        n_po = c.execute(f"""INSERT INTO outcomes(run_id, entity_id, horizon_days, start_date, ret, bench_ret, excess, attrs, computed_at)
            SELECT r.run_id, (SELECT entity_id FROM entities WHERE kind='portfolio' AND key='book'), d.window_days, d.asof_date,
                   d.hrp_return_pct, d.bench_return_pct, d.hrp_excess_pct, {jobj("d.", pco)}, COALESCE(d.computed_at, '{NOW}')
            FROM portfolio_outcomes d JOIN runs r ON r.kind='morning' AND r.as_of_date=d.asof_date WHERE true
            ON CONFLICT(run_id, entity_id, horizon_days) DO UPDATE SET ret=excluded.ret, bench_ret=excluded.bench_ret,
               excess=excluded.excess, attrs=excluded.attrs, computed_at=excluded.computed_at""").rowcount
        # today's official run carries the code version and the regime it ran under
        sha, dirty = git_sha()
        regime = c.execute("SELECT json_object('regime', regime, 'vix_latest', vix_latest, 'vix_20d_avg', vix_20d_avg, 'alloc_large', alloc_large, "
                           "'alloc_mid', alloc_mid, 'alloc_small', alloc_small, 'updated_at', updated_at) FROM regime_state LIMIT 1").fetchone()
        c.execute("UPDATE runs SET git_sha=COALESCE(git_sha, ?), dirty=COALESCE(dirty, ?), attrs=json_set(COALESCE(attrs,'{}'), '$.regime', json(?)) "
                  "WHERE kind='morning' AND as_of_date=?", (sha, dirty, regime[0] if regime else "null", TODAY))
    n_r = sync_replay_docs(c, full)
    n_c = sync_contributions(c, full)
    log(f"decisions: picks {n_p}, book {n_b}, outcomes {n_o}+{n_po}, replay docs {n_r}, contributions {n_c}")


def sync_replay_docs(c, full):
    """pit_replay_snapshots, row for row: the exact screener inputs/outputs frozen per stock per day."""
    with tx(c):
        cat_ensure(c, "doc_type", ["pit_replay"])
        dt = cat_ids(c, "doc_type")["pit_replay"]
        w = "" if full else f"WHERE p.snapshot_date >= date('{TODAY}', '-{WINDOW_DAYS} day') OR p.snapshot_date NOT IN " \
                            f"(SELECT doc_date FROM documents WHERE type_id={dt})"
        n = c.execute(f"""INSERT OR IGNORE INTO documents(type_id, entity_id, doc_date, available_at, source, source_key, run_id, fields,
                content_hash, status, created_at)
            SELECT {dt}, e.entity_id, p.snapshot_date, COALESCE(p.frozen_at, p.snapshot_date), 'pit_replay_snapshots',
                   p.snapshot_date || '|' || p.sid, r.run_id,
                   json_object('rank', p.rank, 'final_score', p.final_score, 'cap_tier', p.cap_tier, 'frozen_by_commit', p.frozen_by_commit,
                               'frozen_at', p.frozen_at, 'inputs', json(p.inputs_json), 'output', json(p.output_json)),
                   COALESCE(p.frozen_by_commit, '') || ':' || length(p.inputs_json) || ':' || length(p.output_json) || ':' || COALESCE(p.frozen_at, ''),
                   'valid', '{NOW}'
            FROM pit_replay_snapshots p JOIN entities e ON {SEC}=p.sid
            LEFT JOIN runs r ON r.kind='morning' AND r.as_of_date=p.snapshot_date {w}""").rowcount
        _supersede(c, dt)
    return n


def sync_contributions(c, full):
    """Replay each frozen day through score_universe and keep its per-factor terms only when the rebuilt base score
    matches daily_picks (weights of that day == today's weights). Σ contribution = base score, by construction."""
    import numpy as np
    import factors
    from scoring import screener
    from tools.pit_replay import _META_COLS
    have = {r[0] for r in c.execute("SELECT DISTINCT r.as_of_date FROM pick_contributions p JOIN runs r USING (run_id)")}
    dates = [r[0] for r in c.execute("SELECT DISTINCT snapshot_date FROM pit_replay_snapshots ORDER BY 1")]
    recent = (date.fromisoformat(TODAY).fromordinal(date.fromisoformat(TODAY).toordinal() - WINDOW_DAYS)).isoformat()
    todo = dates if full else [d for d in dates if d not in have or d >= recent]
    cat_ensure(c, "feature", list(factors.SIGNAL_WEIGHTS.get("LARGE", {})) + [k for t in factors.SIGNAL_WEIGHTS.values() for k in t])
    fids = cat_ids(c, "feature")
    kept = skipped = 0
    ent = _ent_map(c, "security")
    for d in todo:
        rows = pd.read_sql("SELECT sid, inputs_json FROM pit_replay_snapshots WHERE snapshot_date=?", c, params=[d])
        dfi = pd.DataFrame([json.loads(s) for s in rows["inputs_json"]])
        if dfi.empty or "cap_tier" not in dfi:
            continue
        if "sid" not in dfi:
            dfi["sid"] = rows["sid"].values
        for col in dfi.columns:
            if col not in _META_COLS:
                dfi[col] = pd.to_numeric(dfi[col], errors="coerce")
        scored = screener.score_universe(dfi.copy(), as_of=date.fromisoformat(d))
        stored = pd.read_sql("SELECT sid, base_score FROM daily_picks WHERE pick_date=?", c, params=[d])
        m = scored[["sid", "base_score"]].merge(stored, on="sid", suffixes=("", "_stored"))
        both = m.dropna(subset=["base_score", "base_score_stored"])
        match = float(np.isclose(both["base_score"], both["base_score_stored"], rtol=0, atol=1e-9).mean()) if len(both) else 0.0
        rid = c.execute("SELECT run_id FROM runs WHERE kind='morning' AND as_of_date=?", (d,)).fetchone()
        if rid is None:
            continue
        with tx(c):
            c.execute("UPDATE runs SET attrs=json_set(COALESCE(attrs,'{}'), '$.contrib_match', ?) WHERE run_id=?", (round(match, 6), rid[0]))
            c.execute("DELETE FROM pick_contributions WHERE run_id=?", (rid[0],))
            if match < 0.999:
                skipped += 1
                continue
            out = []
            for tier, tw in factors.SIGNAL_WEIGHTS.items():
                sub = scored[scored["cap_tier"] == tier]
                if sub.empty:
                    continue
                wsum = pd.Series(0.0, index=sub.index)
                terms = {}
                for sk, w in tw.items():
                    pc = f"{sk}_pctile"
                    if pc not in sub:
                        continue
                    p = sub[pc]
                    term = (abs(w) * (1.0 - p)) if w < 0 else (w * p)
                    terms[sk] = (p, term, w)
                    wsum = wsum + p.notna() * abs(w)
                for sk, (p, term, w) in terms.items():
                    col = factors.SCREENER_TIER_COLS.get((sk, tier), factors.SCREENER_COLS.get(sk))
                    raw = sub[col] if col in sub else pd.Series(np.nan, index=sub.index)
                    for i in sub.index[p.notna() & (wsum > 0)]:
                        e = ent.get(sub.at[i, "sid"])
                        if e is None:
                            continue
                        out.append((rid[0], e, fids[sk], _clean(float(raw[i])) if pd.notna(raw[i]) else None, float(p[i]), float(w),
                                    float(term[i] / wsum[i])))
            c.executemany("""INSERT INTO pick_contributions VALUES (?,?,?,?,?,?,?) ON CONFLICT(run_id, entity_id, feature_id)
                DO UPDATE SET raw=excluded.raw, pctile=excluded.pctile, weight=excluded.weight, contribution=excluded.contribution""", out)
            kept += 1
    log(f"contributions: {kept} dates kept, {skipped} skipped (weights differed from today's), {len(dates) - len(todo)} unchanged")
    return kept


# ─────────────────────────── research ───────────────────────────

def sync_research(c):
    with tx(c):
        names = [r[0] for r in c.execute("SELECT DISTINCT signal FROM pit_ic_by_tier_v2 UNION SELECT DISTINCT signal FROM factor_horizon_gate")]
        cat_ensure(c, "feature", names)
        a = c.execute(f"""INSERT INTO factor_tests(feature_id, tier, horizon_days, method, source, n, ic, t_stat, icir, verdict, computed_at, attrs)
            SELECT k.catalog_id, t.cap_tier, 0, 'ic_by_tier', COALESCE(t.source, ''), t.n_periods, t.mean_ic, t.t_stat, t.icir, t.verdict,
                   COALESCE(t.computed_at, '{NOW}'),
                   json_object('std_ic', t.std_ic, 'n_stocks_avg', t.n_stocks_avg, 't_stat_ci_lo', t.t_stat_ci_lo, 't_stat_ci_hi', t.t_stat_ci_hi)
            FROM pit_ic_by_tier_v2 t JOIN catalog k ON k.kind='feature' AND k.name=t.signal WHERE true
            ON CONFLICT(feature_id, tier, horizon_days, method, source) DO UPDATE SET n=excluded.n, ic=excluded.ic, t_stat=excluded.t_stat,
               icir=excluded.icir, verdict=excluded.verdict, computed_at=excluded.computed_at, attrs=excluded.attrs""").rowcount
        hg = [x for x in cols(c, "factor_horizon_gate") if x not in ("signal", "cap_tier", "source", "natural_horizon", "gross_ic",
                                                                       "gross_t", "net_ir_annual", "n_periods", "verdict", "computed_at")]
        b = c.execute(f"""INSERT INTO factor_tests(feature_id, tier, horizon_days, method, source, n, ic, t_stat, icir, verdict, computed_at, attrs)
            SELECT k.catalog_id, t.cap_tier, COALESCE(t.natural_horizon, 0), 'horizon_gate', COALESCE(t.source, ''), t.n_periods, t.gross_ic,
                   t.gross_t, t.net_ir_annual, t.verdict, COALESCE(t.computed_at, '{NOW}'), {jobj("t.", hg)}
            FROM factor_horizon_gate t JOIN catalog k ON k.kind='feature' AND k.name=t.signal WHERE true
            ON CONFLICT(feature_id, tier, horizon_days, method, source) DO UPDATE SET n=excluded.n, ic=excluded.ic, t_stat=excluded.t_stat,
               icir=excluded.icir, verdict=excluded.verdict, computed_at=excluded.computed_at, attrs=excluded.attrs""").rowcount
    log(f"research: ic_by_tier {a}, horizon_gate {b}")


# ─────────────────────────── ops ───────────────────────────

def _run_kind(step):
    for p, k in (("watchdog_", "watchdog"), ("endpoint_audit_", "endpoint_audit")):
        if step.startswith(p):
            return k
    return "morning"


def sync_ops(c, full):
    with tx(c):
        # pipeline_log → runs + step_runs (terminal rows; a RUNNING row with no terminal twin is an orphan)
        last = c.execute("SELECT COALESCE(MAX(CAST(json_extract(attrs, '$.log_id') AS INTEGER)), 0) FROM step_runs "
                         "WHERE json_extract(attrs, '$.from')='pipeline_log'").fetchone()[0]
        pl = pd.read_sql(f"SELECT * FROM pipeline_log WHERE id > {0 if full else last} ORDER BY id", c)
        n_sr = 0
        if not pl.empty:
            term = pl[pl["status"] != "RUNNING"]
            key = set(zip(term["step_name"], term["started_at"]))
            orphan = pl[(pl["status"] == "RUNNING") & [(s, t) not in key for s, t in zip(pl["step_name"], pl["started_at"])]]
            rows = pd.concat([term, orphan]).sort_values("id")
            for kind, cond in (("watchdog", "step_name LIKE 'watchdog\\_%' ESCAPE '\\'"),
                               ("endpoint_audit", "step_name LIKE 'endpoint\\_audit\\_%' ESCAPE '\\'"),
                               ("morning", "step_name NOT LIKE 'watchdog\\_%' ESCAPE '\\' AND step_name NOT LIKE 'endpoint\\_audit\\_%' ESCAPE '\\'")):
                ensure_runs(c, kind, f"SELECT DISTINCT run_date FROM pipeline_log WHERE {cond}", official=1 if kind == "morning" else 0)
            rid = {(k, d): i for i, k, d in c.execute("SELECT run_id, kind, as_of_date FROM runs")}
            att = {}
            for r in c.execute("SELECT run_id, step, MAX(attempt) FROM step_runs GROUP BY run_id, step"):
                att[(r[0], r[1])] = r[2]
            out = []
            for r in rows.to_dict("records"):
                run = rid.get((_run_kind(r["step_name"]), r["run_date"]))
                if run is None:
                    continue
                a = att.get((run, r["step_name"]), 0) + 1
                att[(run, r["step_name"])] = a
                out.append((run, r["step_name"], a, r["status"] if r["status"] != "RUNNING" else "RUNNING(orphan)",
                            r["started_at"] or r["finished_at"] or NOW, r["finished_at"], _clean(r["rows_affected"]), r["error_message"],
                            json.dumps({"from": "pipeline_log", "log_id": int(r["id"]), "duration_sec": _clean(r["duration_sec"])})))
            n_sr = c.executemany("INSERT OR IGNORE INTO step_runs VALUES (?,?,?,?,?,?,?,?,?)", out).rowcount
        # PIT reconstructions and LLM batch logs → their own runs
        ensure_runs(c, "reconstruct", "SELECT DISTINCT substr(started_at, 1, 10) FROM pit_reconstruction_log", official=0)
        n_rc = c.execute(f"""INSERT OR IGNORE INTO step_runs(run_id, step, attempt, status, started_at, finished_at, rows, error, attrs)
            SELECT r.run_id, 'reconstruct:' || p.eval_date, 1 + p.id, COALESCE(p.status, '?'), COALESCE(p.started_at, '{NOW}'), p.finished_at,
                   p.rows_written, p.error_message,
                   json_object('from', 'pit_reconstruction_log', 'log_id', p.id, 'signals_run', p.signals_run, 'rows_attempted', p.rows_attempted,
                               'validation_summary', p.validation_summary, 'duration_sec', p.duration_sec)
            FROM pit_reconstruction_log p JOIN runs r ON r.kind='reconstruct' AND r.as_of_date=substr(p.started_at, 1, 10)""").rowcount
        ensure_runs(c, "llm", "SELECT DISTINCT substr(started_at, 1, 10) FROM sector_narrative_runs UNION SELECT DISTINCT substr(submitted_at, 1, 10) FROM regulatory_batches", official=0)
        n_llm = c.execute(f"""INSERT OR IGNORE INTO step_runs(run_id, step, attempt, status, started_at, finished_at, rows, error, attrs)
            SELECT r.run_id, 'sector_narrative', p.id, COALESCE(p.status, '?'), p.started_at, p.finished_at, p.sectors_done, NULL,
                   json_object('from', 'sector_narrative_runs', 'sectors_failed', p.sectors_failed, 'api_cost_usd', p.api_cost_usd, 'detail', p.detail)
            FROM sector_narrative_runs p JOIN runs r ON r.kind='llm' AND r.as_of_date=substr(p.started_at, 1, 10)""").rowcount
        n_llm += c.execute(f"""INSERT INTO step_runs(run_id, step, attempt, status, started_at, finished_at, rows, error, attrs)
            SELECT r.run_id, 'regulatory_batch:' || p.batch_id, 1, COALESCE(p.status, '?'), COALESCE(p.submitted_at, '{NOW}'), p.ingested_at,
                   p.n_items, NULL, json_object('from', 'regulatory_batches', 'stage', p.stage)
            FROM regulatory_batches p JOIN runs r ON r.kind='llm' AND r.as_of_date=substr(COALESCE(p.submitted_at, '{NOW}'), 1, 10) WHERE true
            ON CONFLICT(run_id, step, attempt) DO UPDATE SET status=excluded.status, finished_at=excluded.finished_at, rows=excluded.rows,
               attrs=excluded.attrs""").rowcount
        # checks: UHS, trust-gate pass counts, feed checks
        cat_ensure(c, "check", ["uhs", "trust_gate"] + [f"feed_{r[0]}" for r in c.execute("SELECT DISTINCT check_kind FROM feed_checks")])
        ck = cat_ids(c, "check")
        n_ck = c.execute(f"""INSERT INTO check_results(check_id, subject, entity_id, date, status, score, detail, checked_at)
            SELECT {ck['uhs']}, h.entity_kind || ':' || h.entity_id, 0, h.snapshot_date, COALESCE(h.label, '?'), h.score_pct,
                   json_object('dim_provenance', h.dim_provenance, 'dim_freshness', h.dim_freshness, 'dim_plausibility', h.dim_plausibility,
                               'dim_consistency', h.dim_consistency, 'dim_coverage', h.dim_coverage, 'score_total', h.score_total,
                               'score_max', h.score_max, 'reasons', json(COALESCE(h.reasons_json, 'null'))),
                   COALESCE(h.computed_at, '{NOW}')
            FROM health_score h WHERE {"true" if full else f"h.snapshot_date >= date('{TODAY}', '-{WINDOW_DAYS} day')"}
            ON CONFLICT(check_id, subject, entity_id, date) DO UPDATE SET status=excluded.status, score=excluded.score, detail=excluded.detail,
               checked_at=excluded.checked_at""").rowcount
        tvc = [x for x in cols(c, "trust_verdicts") if x not in ("sid", "source_table", "source_key", "datum_class", "snapshot_date",
                                                                  "verdict_overall", "computed_at")]
        n_ck += c.execute(f"""INSERT INTO check_results(check_id, subject, entity_id, date, status, score, detail, checked_at)
            SELECT {ck['trust_gate']}, t.source_table || '|' || t.source_key || '|' || t.datum_class, COALESCE(e.entity_id, 0),
                   t.snapshot_date, t.verdict_overall, NULL, {jobj("t.", tvc)}, COALESCE(t.computed_at, '{NOW}')
            FROM trust_verdicts t LEFT JOIN entities e ON {SEC}=t.sid WHERE t.verdict_overall = 'TRUSTED'
            ON CONFLICT(check_id, subject, entity_id, date) DO UPDATE SET status=excluded.status, detail=excluded.detail,
               checked_at=excluded.checked_at""").rowcount
        fc = [x for x in cols(c, "feed_checks") if x not in ("id", "run_date", "feed", "check_kind", "route", "status", "n_rows", "checked_at")]
        n_ck += c.execute(f"""INSERT INTO check_results(check_id, subject, entity_id, date, status, score, detail, checked_at)
            SELECT k.catalog_id, f.feed || '/' || COALESCE(f.route, ''), 0, f.run_date, f.status, f.n_rows, {jobj("f.", fc)},
                   COALESCE(f.checked_at, '{NOW}')
            FROM feed_checks f JOIN catalog k ON k.kind='check' AND k.name='feed_' || f.check_kind WHERE true
            ON CONFLICT(check_id, subject, entity_id, date) DO UPDATE SET status=excluded.status, score=excluded.score,
               detail=excluded.detail, checked_at=excluded.checked_at""").rowcount
        # row issues: failing trust verdicts, quarantine mirrors, Screener pull errors
        tv = cols(c, "trust_verdicts")
        n_ri = c.execute(f"""INSERT OR IGNORE INTO row_issues(dataset, row_key, rule, severity, payload, detected_at)
            SELECT source_table, json_array(sid, source_key, datum_class, snapshot_date), 'trust:' || verdict_overall,
                   CASE verdict_overall WHEN 'QUARANTINED' THEN 'quarantine' ELSE 'review' END, {jobj("", tv)},
                   COALESCE(computed_at, snapshot_date)
            FROM trust_verdicts WHERE verdict_overall <> 'TRUSTED'""").rowcount
        for mirror in [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%\\_quarantine' ESCAPE '\\'")]:
            src = mirror[:-len("_quarantine")]
            mc = cols(c, mirror)
            pk = [r[1] for r in sorted(c.execute(f"PRAGMA table_info('{src}')"), key=lambda r: r[5]) if r[5] > 0] or [x for x in mc if not x.startswith("_q_")][:3]
            target = "mf.row_issues" if src.startswith("mf_") else "row_issues"
            n_ri += c.execute(f"""INSERT OR IGNORE INTO {target}(dataset, row_key, rule, severity, payload, detected_at)
                SELECT '{src}', json_array({", ".join("t." + q(x) for x in pk)}), COALESCE(t._q_failed_gate, 'quarantine'), 'quarantine',
                       json_set({jobj("t.", [x for x in mc if not x.startswith("_q_")])}, '$._q_reason', t._q_reason),
                       COALESCE(t._q_quarantined_at, '{NOW}')
                FROM {mirror} t""").rowcount
        n_ri += c.execute(f"""INSERT OR IGNORE INTO row_issues(dataset, row_key, rule, severity, payload, detected_at)
            SELECT 'fundamentals_screener', json_array(sid, id), COALESCE(error_type, 'error'), 'error',
                   json_object('ticker', ticker, 'error_message', error_message, 'http_status', http_status), COALESCE(attempted_at, '{NOW}')
            FROM screener_pull_errors""").rowcount
    log(f"ops: step_runs +{n_sr} (+{n_rc} reconstruct, +{n_llm} llm), check_results {n_ck}, row_issues +{n_ri}")


# ─────────────────────────── mf.db ───────────────────────────

def sync_mf(c, full):
    with tx(c):
        sm = [x for x in cols(c, "mf_scheme_master") if x not in ("scheme_code", "scheme_name", "amc", "category_norm", "plan_type", "option_type", "isin_growth")]
        c.execute(f"""INSERT INTO mf.funds(scheme_code, name, amc, category, plan_type, option_type, isin, attrs, updated_at)
            SELECT scheme_code, scheme_name, amc, category_norm, plan_type, option_type, isin_growth, {jobj("", sm)}, '{NOW}'
            FROM mf_scheme_master WHERE true
            ON CONFLICT(scheme_code) DO UPDATE SET name=excluded.name, amc=excluded.amc, category=excluded.category, plan_type=excluded.plan_type,
               option_type=excluded.option_type, isin=excluded.isin, attrs=excluded.attrs, updated_at=excluded.updated_at
            WHERE funds.attrs IS NOT excluded.attrs OR funds.name IS NOT excluded.name""")
        ms = [x for x in cols(c, "mf_schemes") if x != "scheme_code"]
        c.execute(f"""INSERT OR IGNORE INTO mf.funds(scheme_code, name, amc, category, attrs, updated_at)
            SELECT scheme_code, scheme_name, fund_house, category_norm, json_object('from', 'mf_schemes'), '{NOW}' FROM mf_schemes""")
        c.execute(f"""UPDATE mf.funds SET attrs = json_set(COALESCE(attrs, '{{}}'), '$.mf_schemes', json(s.j))
            FROM (SELECT scheme_code, {jobj("", ms)} AS j FROM mf_schemes) s WHERE funds.scheme_code = s.scheme_code""")
        # scheme codes that appear in MF data but in neither scheme master still get a fund (flagged), so no row is dropped
        for t in ("mf_nav_history", "mf_holdings", "mf_sector_allocation", "mf_metrics", "mf_rolling_returns", "mf_calendar_returns"):
            c.execute(f"""INSERT OR IGNORE INTO mf.funds(scheme_code, attrs, updated_at)
                SELECT DISTINCT scheme_code, json_object('orphan_from', '{t}'), '{NOW}' FROM {t} WHERE scheme_code IS NOT NULL""")
        w = "" if full else f"AND n.nav_date >= date('{TODAY}', '-{WINDOW_DAYS} day') OR n.fetched_at >= date('{TODAY}', '-2 day')"
        n_nav = c.execute(f"""INSERT INTO mf.fund_nav(fund_id, date, nav, fetched_at)
            SELECT f.fund_id, n.nav_date, n.nav, n.fetched_at FROM mf_nav_history n JOIN mf.funds f ON f.scheme_code=n.scheme_code WHERE true {w}
            ON CONFLICT(fund_id, date) DO UPDATE SET nav=excluded.nav, fetched_at=excluded.fetched_at""").rowcount
        c.execute("DELETE FROM mf.fund_holdings")   # holdings are small; rebuilt whole so a re-scrape replaces cleanly
        n_h = c.execute("""INSERT INTO mf.fund_holdings(fund_id, as_of, available_at, holding_type, holding_key, sid, isin, name, sector,
                instrument, weight, value)
            SELECT f.fund_id, h.as_of_date, h.as_of_date, 'security', CAST(h.holding_rank AS TEXT), h.sid, h.isin, h.instrument_name, h.sector,
                   h.instrument_type, h.pct_of_aum, h.market_value_cr
            FROM mf_holdings h JOIN mf.funds f ON f.scheme_code=h.scheme_code""").rowcount
        n_h += c.execute("""INSERT INTO mf.fund_holdings(fund_id, as_of, available_at, holding_type, holding_key, sector, weight)
            SELECT f.fund_id, h.as_of_date, h.as_of_date, 'sector', h.sector, h.sector, h.pct_of_aum
            FROM mf_sector_allocation h JOIN mf.funds f ON f.scheme_code=h.scheme_code""").rowcount
        n_m = 0
        for t, subj_kind, subj, asof, skip in (
                ("mf_metrics", "fund", "scheme_code", "as_of_date", {"scheme_code", "as_of_date"}),
                ("mf_rolling_returns", "fund", "scheme_code", "anchor_date", {"scheme_code", "anchor_date"}),
                ("mf_category_stats", "category", "category_norm", "as_of_date", {"category_norm", "as_of_date"})):
            for x, ty in coltypes(c, t).items():
                if x in skip:
                    continue
                num = ty in ("REAL", "INTEGER")
                n_m += c.execute(f"""INSERT INTO mf.fund_metrics(subject_kind, subject, metric, win, as_of, value, text_value)
                    SELECT '{subj_kind}', {subj}, '{t}.{x}', '', {asof}, {x if num else 'NULL'}, {'NULL' if num else x}
                    FROM {t} WHERE {x} IS NOT NULL
                    ON CONFLICT(subject_kind, subject, metric, win, as_of) DO UPDATE SET value=excluded.value, text_value=excluded.text_value""").rowcount
        for x in ("ret_pct", "bench_ret_pct"):
            n_m += c.execute(f"""INSERT INTO mf.fund_metrics(subject_kind, subject, metric, win, as_of, value)
                SELECT 'fund', scheme_code, 'mf_calendar_returns.{x}', CAST(year AS TEXT), year || '-12-31', {x}
                FROM mf_calendar_returns WHERE {x} IS NOT NULL
                ON CONFLICT(subject_kind, subject, metric, win, as_of) DO UPDATE SET value=excluded.value""").rowcount
    log(f"mf.db: nav {n_nav}, holdings {n_h}, metrics {n_m}")


# ─────────────────────────── driver ───────────────────────────

STEPS = ["catalog", "entities", "classifications", "identifiers", "bars", "series", "fundamentals", "estimates", "events",
         "documents", "features", "decisions", "research", "ops", "mf"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--full", action="store_true", help="rebuild every slice from all history")
    ap.add_argument("--only", default="", help="comma-separated subset of: " + ",".join(STEPS))
    a = ap.parse_args(argv)
    only = [s for s in a.only.split(",") if s] or STEPS
    bad = set(only) - set(STEPS)
    if bad:
        sys.exit(f"unknown step(s): {bad}")
    c = connect()
    ensure_schema(c)
    since = last_sync(c)
    full = a.full or since is None
    run_id = start_sync_run(c)
    log(f"run {run_id} · {'FULL' if full else 'incremental since ' + since} · db={DB_PATH}")
    t0 = time.time()
    status, err = "ok", None
    try:
        for s in only:
            t1 = time.time()
            if s == "catalog":
                sync_catalog(c)
            elif s == "entities":
                sync_entities(c)
            elif s == "classifications":
                sync_classifications(c, run_id)
            elif s == "identifiers":
                sync_identifiers(c)
            elif s == "bars":
                sync_bars(c, full)
            elif s == "series":
                sync_series(c)
            elif s == "fundamentals":
                sync_fundamentals(c)
            elif s == "estimates":
                sync_estimates(c)
            elif s == "events":
                sync_events(c, full, since)
            elif s == "documents":
                sync_documents(c, full, since)
            elif s == "features":
                sync_features(c, run_id, full, since)
            elif s == "decisions":
                sync_decisions(c, full, run_id)
            elif s == "research":
                sync_research(c)
            elif s == "ops":
                sync_ops(c, full)
            elif s == "mf":
                sync_mf(c, full)
            log(f"  {s} done in {time.time() - t1:.1f}s")
    except Exception as e:  # noqa: BLE001 — recorded on the run row, then re-raised
        status, err = "failed", f"{type(e).__name__}: {e}"
        raise
    finally:
        c.execute("UPDATE runs SET status=?, finished_at=?, attrs=json_object('steps', ?, 'error', ?, 'full', ?) WHERE run_id=?",
                  (status, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"), ",".join(only), err, int(full), run_id))
        log(f"run {run_id} {status} in {time.time() - t0:.0f}s")
        try:   # big backfills grow the WAL; hand the space back (a busy reader just makes this a no-op)
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
