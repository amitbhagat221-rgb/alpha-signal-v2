"""
Alpha Signal v2 — named read-models (the View block, ADR 0052 / plan 0015 Phase 5).

A surface (cockpit page, ops page, email, dossier prompt, diff feed) asks for a
concept by name here instead of writing its own SQL, so every surface shows the
same thing:

  tiers         tiers() / pickable_tiers()          — from config.TIERS
  picks         picks(date, gated, tier, per_tier)  — ONE pick gate (PICK_GATE_SQL)
  stock         stock(sid), signals(sid)            — signal tables come from the factor registry
  prices        latest_close(sids), price_metrics(sids) — ONE returns definition (trading days)
  regime        regime()
  changes       changes(days), change_counts()
  sectors       sector_narrative(sector_or_industry)
  dossiers      dossier_index(max_age_days), published_dossier(hit)
  pipeline      pipeline_status(days), step_status()   — one query, stale RUNNING → ABORTED

Plain functions over SQLite (ADR 0004); no caching here — the cockpit wraps these
in its TTL caches, the pipeline calls them once. Page-specific one-off queries
stay with their page.
"""
import functools
import glob
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import config
import db
from db import get_db, read_sql

PROJECT_ROOT = Path(__file__).resolve().parent


# ═══════════════════════════ tiers ═══════════════════════════

def tiers():
    """Every cap tier, in config order (config.TIERS may be a tuple or a dict)."""
    import config
    return list(config.TIERS)


def pickable_tiers():
    """Tiers that reach picks (ADR 0052 invariant 2): a TIERS entry with
    pickable=False, or a tier in config.EXCLUDED_FROM_PICKS, never does."""
    import config
    excluded = set(config.EXCLUDED_FROM_PICKS)
    spec = config.TIERS if isinstance(config.TIERS, dict) else {}
    return [t for t in tiers()
            if t not in excluded and (spec.get(t) or {}).get("pickable", True)]


def unpickable_tiers():
    return [t for t in tiers() if t not in pickable_tiers()]


# ═══════════════════════════ batch helpers ═══════════════════════════

def sid_params(sids):
    """De-duplicated, None-free sid list + its `?,?,…` placeholder string."""
    sids = list(dict.fromkeys(s for s in sids if s))
    return sids, ",".join("?" * len(sids))


def native_rows(sql, params=()):
    """Rows as dicts with sqlite3's own per-row types. Batch reads use this, not
    pandas: in a multi-sid frame one sid's NULL turns every other sid's ints into
    floats ("12.0 analysts"), which single-sid reads never did."""
    with get_db() as conn:
        cur = conn.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def latest_rows(table, cols, sids, order_col="snapshot_date", n=1, where=None):
    """The newest `n` rows per sid (by `order_col`) for every sid in `sids`, as
    record dicts with a leading `sid` key — the batched form of
    `... WHERE sid = ? ORDER BY <order_col> DESC LIMIT n`."""
    sids, ph = sid_params(sids)
    if not sids:
        return []
    extra = f"AND ({where})" if where else ""
    return native_rows(
        f"SELECT sid, {cols} FROM ("
        f"  SELECT sid, {cols}, ROW_NUMBER() OVER ("
        f"    PARTITION BY sid ORDER BY [{order_col}] DESC) AS _rn"
        f"  FROM [{table}] WHERE sid IN ({ph}) {extra}"
        f") WHERE _rn <= {int(n)}",
        sids,
    )


def latest_per_sid(table, cols):
    """Every sid's newest row (by snapshot_date) of `table` as a DataFrame
    [sid, *cols]; `cols` may carry `AS` aliases."""
    return read_sql(
        f"SELECT sid, {', '.join(cols)} FROM [{table}] "
        f"WHERE (sid, snapshot_date) IN "
        f"(SELECT sid, MAX(snapshot_date) FROM [{table}] GROUP BY sid)"
    )


# ═══════════════════════════ picks ═══════════════════════════

# The ONE reader-side pick gate (plan 0005 Phase B): a pick that contradicts itself
# across fields (integrity FAIL) never reaches a reader. The data gate itself —
# enough factor coverage, prices and fundamentals (config.PICK_GATE) — is applied
# by the screener before a row is written. The per-pick trust score (UHS) that used
# to sit here was retired in ADR 0061; its columns stay on daily_picks as history.
PICK_GATE_SQL = "(dp.integrity_status IS NULL OR dp.integrity_status != 'FAIL')"

_PICK_COLS = """
      dp.sid, dp.final_score, dp.rank, dp.cap_tier, dp.sector,
      dp.base_score, dp.forensic_adj, dp.integrity_status,
      dp.eligible_coverage, dp.weight_coverage, dp.price_rows, dp.fundamental_coverage,
      s.ticker, s.name, s.pe_ratio, s.pb_ratio, s.roe, s.market_cap_cr"""


def pick_data(row, sid=None, pick_date=None):
    """The data behind one pick, in words (ADR 0061). The score is the share of the
    factor weight that applies to this stock which was backed by a real value —
    the quantity the pick gate uses — so it varies stock by stock and means one
    thing: {score (0-100), word, meaning, colour, factors_used, factors_applicable,
    missing: [factor keys], price_days, quarters}. With `sid` and `pick_date` the
    missing factors are named from the inputs the screener froze that day."""
    cov = row.get("eligible_coverage")
    if cov is None or pd.isna(cov):
        return None
    # a factor the registry marks ineligible for the stock can still produce a value,
    # which puts the ratio a touch over 1: it means complete, so cap it
    cov = min(float(cov), 1.0)
    complete = cov >= config.PICK_GATE["complete_from"]
    out = {"score": int(round(100 * cov)),
           "word": "Complete" if complete else "Partial",
           "meaning": ("every factor that applies to this stock had a value" if complete else
                       "ranked on the factors that had values; the rest were left out, not counted as zero"),
           "colour": "green" if complete else "amber",
           "price_days": None if row.get("price_rows") is None else int(row["price_rows"]),
           "quarters": None if row.get("fundamental_coverage") is None else int(round(8 * float(row["fundamental_coverage"]))),
           "factors_used": None, "factors_applicable": None, "missing": []}
    tier = row.get("cap_tier")
    if sid and pick_date and tier:
        import factors
        frozen = db.one("SELECT inputs_json FROM pit_replay_snapshots WHERE sid = ? AND snapshot_date = ?", [sid, pick_date])
        inputs = json.loads(frozen["inputs_json"]) if frozen.get("inputs_json") else None
        weights = factors.SIGNAL_WEIGHTS.get(tier, {})
        if inputs is not None and weights:
            cols = {k: factors.SCREENER_TIER_COLS.get((k, tier)) or factors.SCREENER_COLS[k] for k in weights}
            missing = [k for k, c in cols.items() if inputs.get(c) is None]
            out.update(factors_applicable=len(weights), factors_used=len(weights) - len(missing), missing=missing)
    return out

_SNAPSHOT_COLS = """,
      ds.close_price, ds.piotroski_f, ds.cf_accruals, ds.bs_accruals,
      ds.earnings_yield, ds.book_to_price, ds.consensus_signal, ds.promoter_qoq,
      ds.delivery_pct, ds.mom_6m, ds.mom_12m, ds.smart_money, ds.sentiment_7d"""


def latest_pick_date():
    """MAX(pick_date) in daily_picks (None when empty)."""
    return db.scalar("SELECT MAX(pick_date) FROM daily_picks")


def pick_dates(n=2):
    """The newest `n` pick dates, newest first."""
    return [r["pick_date"] for r in native_rows(
        "SELECT DISTINCT pick_date FROM daily_picks ORDER BY pick_date DESC LIMIT ?", [n])]


def pick_count(pick_date=None):
    """How many stocks were ranked on `pick_date` (default: the latest)."""
    if pick_date is None:
        return db.scalar("SELECT COUNT(*) FROM daily_picks "
                         "WHERE pick_date = (SELECT MAX(pick_date) FROM daily_picks)", default=0)
    return db.scalar("SELECT COUNT(*) FROM daily_picks WHERE pick_date = ?", [pick_date], default=0)


def picks(pick_date=None, gated=True, tier=None, per_tier=None, snapshot=False):
    """The ranked universe on `pick_date` (default: the latest), ordered by tier then rank.

    gated=True   the published set: PICK_GATE_SQL applied (email, dossier, brief,
                 actions, portfolio, diff feed). gated=False = every ranked stock
                 (explorer / heatmap / sector pages rank the whole universe).
    tier         one tier only.
    per_tier     None = all; "book" = config.PORTFOLIO["picks_per_tier"] (the 5/5/5
                 set the email shows and the dossier generator narrates); or an int.
    snapshot     also join that date's daily_snapshots signal values.
    """
    where, params = [], []
    if pick_date is None:
        where.append("dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks)")
    else:
        where.append("dp.pick_date = ?")
        params.append(pick_date)
    if gated:
        where.append(PICK_GATE_SQL)
    if tier:
        where.append("dp.cap_tier = ?")
        params.append(tier)
    join = ("LEFT JOIN daily_snapshots ds ON dp.sid = ds.sid "
            "AND ds.snapshot_date = dp.pick_date") if snapshot else ""
    df = read_sql(
        f"SELECT {_PICK_COLS}{_SNAPSHOT_COLS if snapshot else ''} "
        f"FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid {join} "
        f"WHERE {' AND '.join(where)} ORDER BY dp.cap_tier, dp.rank",
        params=params or None,
    )
    if per_tier is None or df.empty:
        return df
    if per_tier == "book":
        from config import PORTFOLIO
        n = PORTFOLIO["picks_per_tier"]
        keep = df.groupby("cap_tier", sort=False).cumcount() < df["cap_tier"].map(n).fillna(0)
        return df[keep]
    return df.groupby("cap_tier", sort=False).head(per_tier)


def published_picks(per_tier=None):
    """The published pick set with its snapshot signal values (email + dossier)."""
    return picks(per_tier=per_tier, snapshot=True)


# ═══════════════════════════ stock ═══════════════════════════

# Lineage note: db._scan_db_references() sees only literal table names, and these
# are read through f-strings (signals(), latest_rows callers). Spelled out so the
# /system "used by" column credits this module: reads FROM consensus_signals,
# FROM promoter_signals, FROM piotroski_scores, FROM accruals_scores,
# FROM insider_signals, FROM smart_money_scores, FROM forensic_scores,
# FROM sentiment_scores.
# Per-stock signal tables the stock page and dossier DISPLAY (their newest row per
# sid). Since plan 0015 Phase 3 the screener computes factor values via pit.py, so
# these tables are display/history only — a presentation spec, listed once here.
# Only (sid, snapshot_date) tables qualify.
_DISPLAY_SIGNAL_TABLES = ("piotroski_scores", "accruals_scores", "consensus_signals",
                          "promoter_signals", "smart_money_scores",
                          "forensic_scores", "sentiment_scores", "insider_signals")
_ROW_BOOKKEEPING = {"sid", "snapshot_date", "cap_tier", "computed_at", "created_at",
                    "updated_at", "fetched_at"}


@functools.lru_cache(maxsize=None)
def _columns(table):
    with get_db() as conn:
        return tuple(r[1] for r in conn.execute(f"PRAGMA table_info([{table}])"))


def signal_tables():
    return [t for t in _DISPLAY_SIGNAL_TABLES if {"sid", "snapshot_date"} <= set(_columns(t))]


def signals(sid):
    """{column: value} from the newest row of each signal table for `sid`."""
    out = {}
    for table in signal_tables():
        cols = [c for c in _columns(table) if c not in _ROW_BOOKKEEPING]
        try:
            out.update(db.one(
                f"SELECT {', '.join(f'[{c}]' for c in cols)} FROM [{table}] "
                f"WHERE sid = ? ORDER BY snapshot_date DESC LIMIT 1", [sid]))
        except Exception:
            pass
    return out


# daily_snapshots column (the value the ranking used, output/snapshot.py) → the
# signal-table key the stock page and the MCP stock tool show it under. Same quantity
# on both sides; consensus is left out (the snapshot holds reported EPS growth, the
# table's consensus_signal is a 0-1 composite).
RANKED_AS = {"piotroski_f": "f_score", "cf_accruals": "cf_accruals_ratio", "bs_accruals": "bs_accruals_ratio",
             "promoter_qoq": "promoter_qoq", "smart_money": "smart_money_score", "sentiment_7d": "sentiment_7d"}


def ranked(sid):
    """{signal key: value} the ranking used for `sid` on the newest snapshot day (RANKED_AS),
    plus `ranked_as_of`; {} when the stock has no snapshot row."""
    r = db.one(f"SELECT snapshot_date, {', '.join(RANKED_AS)} FROM daily_snapshots WHERE sid = ? "
               "ORDER BY snapshot_date DESC LIMIT 1", [sid])
    if not r:
        return {}
    return {"ranked_as_of": r["snapshot_date"], **{RANKED_AS[c]: r[c] for c in RANKED_AS}}


def stock(sid):
    """One stock now: its `stocks` row, its newest pick (score, rank, the data
    behind it), its signal values and its latest close. None for an unknown sid.

    Headline signal values are the ones the ranking used (`ranked`, point in time with
    filing lags); the *_scores tables, computed without lags, supply component detail
    only. `f_score_filing` keeps the table's score for its nine-test breakdown.

    `stocks.cap_tier` is the tier of record — the pick row's tier is not merged
    (a stale pick row would resurrect yesterday's tier after a MICRO toggle)."""
    s = db.one("SELECT * FROM stocks WHERE sid = ?", [sid])
    if not s:
        return None
    pick = db.one(
        "SELECT final_score, rank, pick_date, cap_tier, eligible_coverage, weight_coverage, price_rows, "
        "fundamental_coverage FROM daily_picks WHERE sid = ? ORDER BY pick_date DESC LIMIT 1", [sid])
    s.update({k: v for k, v in pick.items() if k != "cap_tier"})      # stocks.cap_tier is the tier of record
    s["data"] = pick_data(pick, sid, pick.get("pick_date")) if pick else None
    sig = signals(sid)
    if "f_score" in sig:
        sig["f_score_filing"] = sig["f_score"]
    s.update(sig)
    s.update({k: v for k, v in ranked(sid).items() if v is not None or k not in s})
    close, price_date = latest_close([sid]).get(sid, (None, None))
    if close is not None:
        s["close_price"], s["price_date"] = close, price_date
    return s


# ═══════════════════════════ prices ═══════════════════════════

# Returns are over TRADING days (rows), the one definition every surface uses:
# 1m = 22, 3m = 65, 6m = 130, 1y = 252 sessions back. Rows with close <= 0 are skipped.
RETURN_WINDOWS = (("1m", 22), ("3m", 65), ("6m", 130), ("1y", 252))


def latest_close(sids=None):
    """{sid: (close, date)} for the newest stock_prices row per sid (all sids if None)."""
    if sids is None:
        rows = native_rows(
            "SELECT sid, close, date FROM stock_prices "
            "WHERE (sid, date) IN (SELECT sid, MAX(date) FROM stock_prices GROUP BY sid)")
    else:
        rows = latest_rows("stock_prices", "close, date", sids, order_col="date")
    return {r["sid"]: (r["close"], r["date"]) for r in rows}


def _price_metrics(df):
    """Returns, 52w range and RSI-14 from one sid's (date, close) rows (any order)."""
    if df.empty or len(df) < 5:
        return {}
    ordered = df.sort_values("date")
    closes = ordered["close"]
    latest = closes.iloc[-1]
    result = {"close_price": round(latest, 2), "price_date": ordered["date"].iloc[-1]}
    for label, offset in RETURN_WINDOWS:
        if len(closes) > offset:
            old = closes.iloc[-(offset + 1)]
            if old > 0:
                result[f"return_{label}"] = round((latest / old - 1) * 100, 1)
    result["high_52w"] = round(closes.max(), 2)
    result["low_52w"] = round(closes.min(), 2)
    if result["high_52w"] > 0:
        result["pct_from_52w_high"] = round((latest / result["high_52w"] - 1) * 100, 1)
    if len(closes) >= 15:
        delta = closes.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rsi = 100 - (100 / (1 + avg_gain / avg_loss))
        result["rsi_14"] = round(rsi.iloc[-1], 1)
    return result


def price_metrics(sids):
    """{sid: {close_price, price_date, return_1m/3m/6m/1y (%), high_52w, low_52w,
    pct_from_52w_high, rsi_14}} — {} for a sid with fewer than 5 prices."""
    recs = latest_rows("stock_prices", "date, close", sids,
                       order_col="date", n=RETURN_WINDOWS[-1][1] + 8, where="close > 0")
    out = {sid: {} for sid in sid_params(sids)[0]}
    if recs:
        for sid, g in pd.DataFrame(recs).groupby("sid", sort=False):
            out[sid] = _price_metrics(g.reset_index(drop=True))
    return out


# ═══════════════════════════ regime / changes ═══════════════════════════

def regime():
    """The current VIX regime row (regime, vix_latest, vix_20d_avg, alloc_large/
    mid/small, updated_at) plus its display `color`; None when never computed."""
    r = db.one("SELECT * FROM regime_state WHERE id = 1")
    if not r:
        return None
    from formatting import REGIME_COLORS
    r["color"] = REGIME_COLORS.get(r.get("regime"), "blue")
    return r


def changes(days=1):
    """daily_changes rows of the last `days` days, HIGH → MEDIUM → rest, newest first."""
    return db.rows(
        "SELECT * FROM daily_changes WHERE change_date >= date('now', ?) "
        "ORDER BY CASE UPPER(severity) WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, id DESC",
        [f"-{days} days"],
    )


def change_counts():
    """{change_type: n} for the newest change_date."""
    return {r["change_type"]: r["c"] for r in native_rows(
        "SELECT change_type, COUNT(*) AS c FROM daily_changes "
        "WHERE change_date = (SELECT MAX(change_date) FROM daily_changes) "
        "GROUP BY change_type")}


# ═══════════════════════════ sector narrative ═══════════════════════════

def sector_narrative(key):
    """The latest sector_metadata narrative payload for a sector OR industry name
    (the `sector` column holds either taxonomy key): a manual override wins over
    auto, then the newest. Adds _industry / _source / _generated_at. None if no
    narrative has been generated (or its JSON is unreadable)."""
    row = db.one(
        "SELECT industry, source, generated_at, payload FROM sector_metadata "
        "WHERE sector = ? "
        "ORDER BY CASE source WHEN 'manual' THEN 0 ELSE 1 END, generated_at DESC "
        "LIMIT 1",
        [key],
    )
    if not row:
        return None
    try:
        payload = json.loads(row["payload"])
    except (json.JSONDecodeError, TypeError):
        return None
    payload["_industry"] = row["industry"]
    payload["_source"] = row["source"]
    payload["_generated_at"] = row["generated_at"]
    return payload


# ═══════════════════════════ dossiers ═══════════════════════════

DOSSIER_MAX_AGE_DAYS = 3  # honest staleness cap; matches data_health "daily" threshold


def dossier_index(max_age_days=DOSSIER_MAX_AGE_DAYS, today=None):
    """{sid: (dossier, file_date, age_days)} — the newest dossier WITH a thesis per
    sid across output/dossiers_<date>.json files at most `max_age_days` old. Never
    walks back further: a 20-day-old thesis is not current truth (HALC 2026-05-22)."""
    today = today or date.today()
    index = {}
    for f in sorted(glob.glob(str(PROJECT_ROOT / "output" / "dossiers_*.json")), reverse=True):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", Path(f).name)
        if not m:
            continue
        file_date = datetime.strptime(m.group(1), "%Y-%m-%d").date()
        age_days = (today - file_date).days
        if age_days > max_age_days:
            break
        try:
            with open(f) as fh:
                dossiers = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        for d in dossiers:
            if d.get("thesis") and d.get("sid") not in index:
                index[d.get("sid")] = (d, file_date, age_days)
    return index


def published_dossier(hit):
    """A dossier_index() entry as a reader may see it, or {} when it failed the
    narrative validator (output.dossier.is_publishable)."""
    from output.dossier import is_publishable
    if not hit or not is_publishable(hit[0]):
        return {}
    d, file_date, age_days = hit
    v = d.get("validation")
    return {**d, "as_of": file_date.isoformat(), "age_days": age_days,
            "validated": bool(v and v.get("ok"))}


# ═══════════════════════════ pipeline ═══════════════════════════

_STATUS_SQL = """
    WITH ranked AS (
        SELECT id, run_date, step_name, status, rows_affected, duration_sec,
               error_message, started_at, finished_at,
               ROW_NUMBER() OVER (
                   PARTITION BY run_date, step_name
                   ORDER BY CASE status WHEN 'SUCCESS' THEN 1 WHEN 'FAILED' THEN 2
                                        WHEN 'RUNNING' THEN 3 ELSE 4 END,
                            id DESC) AS rn
        FROM pipeline_log {where}
    )
    SELECT run_date, step_name, status, rows_affected, duration_sec,
           error_message, started_at, finished_at
    FROM ranked WHERE rn = 1
    ORDER BY started_at DESC
"""
RUNNING_STALE_AFTER = timedelta(minutes=5)


def pipeline_status(days=7):
    """One row per (run_date, step) — its FINAL state — newest first; `days`=None
    for all history. The runner logs a RUNNING row then a SUCCESS/FAILED row per
    attempt: a completion row wins over RUNNING, SUCCESS over FAILED. A RUNNING
    row older than RUNNING_STALE_AFTER with no completion is a crashed run → ABORTED."""
    if days is None:
        steps = db.rows(_STATUS_SQL.format(where=""))
    else:
        steps = db.rows(_STATUS_SQL.format(where="WHERE run_date >= date('now', ?)"),
                        [f"-{days} days"])
    cutoff = (datetime.now() - RUNNING_STALE_AFTER).isoformat()
    for r in steps:
        if r["status"] == "RUNNING" and r["started_at"] and r["started_at"] < cutoff:
            r["status"] = "ABORTED"
    return steps


def step_status():
    """{step_name: its newest run's pipeline_status() row}."""
    out = {}
    for r in sorted(pipeline_status(days=None), key=lambda r: r["run_date"] or "", reverse=True):
        out.setdefault(r["step_name"], r)
    return out
