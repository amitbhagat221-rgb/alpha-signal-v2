"""
The Decisions writers (plan 0030 stage 1 part 3, ADR 0084).

The four producers of the Decisions concept write the v3 tables here — `runs`, `picks`,
`book_weights`, `outcomes` (+ the `entities` a new sid needs) — from the same legacy-shaped
frame they still write to the legacy table, in the same transaction, until the stage's drop
commit. `datamodel/sync.py` no longer mirrors these four tables, so the two sides agree
only if the writer wrote both: the daily `datamodel_reconcile` (counts + checksums) and
`python -m datamodel.gate decisions` (row for row through the compatibility views) are the
gate, and a writer that misses v3 fails parity the same morning.

Each writer takes the frame in the legacy table's shape (the compatibility view in
schema.sql is the contract: core columns become picks / outcomes columns, every other
legacy column rides in `attrs` JSON, typed as the legacy column was). After the drop the
producers pass their own frame and nothing here changes.

    screener               → write_picks(conn, pick_date, frame)
    portfolio_construction → write_book_weights(conn, asof_date, frame)
    compute_pick_outcomes  → write_pick_outcomes(conn, frame, superseded_before=…, since=…)
    portfolio_outcomes     → write_portfolio_outcomes(conn, frame)
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

# Legacy column → type, for the columns that ride in attrs (the view unpacks them by name).
# REAL → float, INTEGER → int, TEXT → str; NULL / NaN → JSON null, as the sync wrote them.
PICK_ATTRS = {"base_score": "REAL", "sentiment_adj": "REAL", "insider_adj": "REAL", "forensic_adj": "REAL",
              "macro_adj": "REAL", "piotroski_adj": "REAL", "accruals_adj": "REAL", "consensus_adj": "REAL",
              "promoter_adj": "REAL", "smart_money_adj": "REAL", "sector": "TEXT", "weight_coverage": "REAL",
              "price_rows": "INTEGER", "fundamental_coverage": "REAL", "eligible_coverage": "REAL",
              "integrity_reasons": "TEXT", "uhs_breakdown_json": "TEXT", "uhs_label": "TEXT", "uhs_worst_dim": "TEXT"}
BOOK_ATTRS = {"factor_score": "REAL", "marginal_risk_contrib": "REAL", "cap_tier": "TEXT", "sector": "TEXT",
              "name": "TEXT", "rank": "INTEGER", "created_at": "TEXT"}
PICK_OUTCOME_ATTRS = {"cap_tier": "TEXT", "rank_at_pick": "INTEGER", "final_score": "REAL", "entry_price": "REAL",
                      "exit_price": "REAL", "bench_index": "TEXT"}
BOOK_OUTCOME_ATTRS = {"eqw_return_pct": "REAL", "hrp_vs_eqw_pct": "REAL", "n_names": "INTEGER", "n_matured": "INTEGER"}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def git_sha():
    """(sha, dirty) of the working tree, or (None, None) outside git."""
    try:
        sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True).stdout.strip() != ""
        return sha or None, int(dirty)
    except Exception:  # noqa: BLE001 — provenance is best-effort
        return None, None


def _null(v):
    if v is None:
        return True
    try:
        return bool(v != v)           # NaN; pd.NA raises on bool() and is null too
    except (TypeError, ValueError):
        return True


def typed(v, kind):
    """A frame cell as the legacy column stored it (numpy scalars → Python)."""
    if _null(v):
        return None
    if hasattr(v, "item"):            # numpy / pandas scalar
        v = v.item()
    if kind == "REAL":
        return float(v)
    if kind == "INTEGER":
        return int(v)
    return str(v)


def attrs_json(row, spec):
    """JSON of the attrs columns, every key present (NULL → null), in the legacy column order."""
    return json.dumps({k: typed(row.get(k), t) for k, t in spec.items()}, allow_nan=False)


# ─────────────────────────── runs + entities ───────────────────────────

def run_for(conn, kind, as_of_date, official=1):
    """The run_id of the `kind` run on `as_of_date`, created on first use (status 'ok', with the code
    version). Every writer of that day reuses it."""
    r = conn.execute("SELECT run_id FROM runs WHERE kind=? AND as_of_date=?", (kind, as_of_date)).fetchone()
    if r:
        return r[0]
    sha, dirty = git_sha()
    cur = conn.execute("INSERT INTO runs (kind, as_of_date, started_at, status, official, git_sha, dirty, attrs) "
                       "VALUES (?, ?, ?, 'ok', ?, ?, ?, '{\"writer\": \"datamodel.decisions\"}')",
                       (kind, as_of_date, now(), official, sha, dirty))
    return cur.lastrowid


def morning_run(conn, as_of_date):
    """The morning run's run_id on `as_of_date` (the official run of the day)."""
    return run_for(conn, "morning", as_of_date, official=1)


def morning_runs(conn, dates):
    return {d: morning_run(conn, d) for d in sorted(set(dates))}


def entity_ids(conn, sids):
    """{sid: entity_id} for securities, creating the ones not seen before (named from `stocks`;
    a sid outside the universe gets an unnamed entity flagged orphan, as the sync did)."""
    sids = sorted({s for s in sids if s})
    if not sids:
        return {}
    ts = now()
    for i in range(0, len(sids), 500):
        chunk = sids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        conn.execute(f"INSERT OR IGNORE INTO entities (kind, key, name, attrs, created_at, updated_at) "
                     f"SELECT 'security', sid, name, '{{\"from\": \"writer\"}}', ?, ? FROM stocks WHERE sid IN ({ph})", [ts, ts, *chunk])
        conn.executemany("INSERT OR IGNORE INTO entities (kind, key, attrs, created_at, updated_at) "
                         "VALUES ('security', ?, '{\"orphan_from\": \"writer\"}', ?, ?)", [(s, ts, ts) for s in chunk])
    out = {}
    for i in range(0, len(sids), 500):
        chunk = sids[i:i + 500]
        ph = ",".join("?" * len(chunk))
        out.update(conn.execute(f"SELECT key, entity_id FROM entities WHERE kind='security' AND market='IN' AND key IN ({ph})",
                                chunk).fetchall())
    return out


def book_entity(conn):
    ts = now()
    conn.execute("INSERT OR IGNORE INTO entities (kind, key, name, created_at, updated_at) VALUES ('portfolio', 'book', 'HRP book', ?, ?)",
                 (ts, ts))
    return conn.execute("SELECT entity_id FROM entities WHERE kind='portfolio' AND key='book'").fetchone()[0]


# ─────────────────────────── writers ───────────────────────────

def _records(frame):
    return frame.to_dict("records") if hasattr(frame, "to_dict") else list(frame)


def _selected(tier, rank):
    n = int((config.TIERS.get(tier) or {}).get("picks") or 0)
    return int(rank is not None and n > 0 and rank <= n)


def write_picks(conn, pick_date, frame):
    """The ranked universe of `pick_date` → runs + picks (the run's picks are replaced).
    `frame`: daily_picks-shaped rows. Returns rows written."""
    rows = _records(frame)
    run_id = morning_run(conn, pick_date)
    ents = entity_ids(conn, [r["sid"] for r in rows])
    out = []
    for r in rows:
        rank = typed(r.get("rank"), "INTEGER")
        tier = typed(r.get("cap_tier"), "TEXT")
        out.append((run_id, ents[r["sid"]], tier if tier is not None else "?", rank, typed(r.get("final_score"), "REAL"),
                    _selected(tier, rank), typed(r.get("integrity_status"), "TEXT"), typed(r.get("uhs_score"), "REAL"),
                    attrs_json(r, PICK_ATTRS)))
    conn.execute("DELETE FROM picks WHERE run_id=?", (run_id,))
    n = conn.executemany("INSERT INTO picks (run_id, entity_id, tier, rank, score, selected, gate, uhs, attrs) VALUES (?,?,?,?,?,?,?,?,?)",
                         out).rowcount
    _count(n, "picks")
    return n


def write_book_weights(conn, asof_date, frame):
    """The sized book of `asof_date` → book_weights (the run's book is replaced). `frame`:
    portfolio_weights-shaped rows; a row without created_at keeps the one already stored, else now."""
    rows = _records(frame)
    run_id = morning_run(conn, asof_date)
    ents = entity_ids(conn, [r["sid"] for r in rows])
    kept = dict(conn.execute("SELECT entity_id, json_extract(attrs, '$.created_at') FROM book_weights WHERE run_id=?", (run_id,)).fetchall())
    out = []
    for r in rows:
        e = ents[r["sid"]]
        if _null(r.get("created_at")):
            r = {**r, "created_at": kept.get(e) or now()}
        out.append((run_id, e, typed(r.get("weight"), "REAL"), attrs_json(r, BOOK_ATTRS)))
    conn.execute("DELETE FROM book_weights WHERE run_id=?", (run_id,))
    n = conn.executemany("INSERT INTO book_weights (run_id, entity_id, weight, attrs) VALUES (?,?,?,?)", out).rowcount
    _count(n, "book_weights")
    return n


_OUTCOME_UPSERT = ("INSERT INTO outcomes (run_id, entity_id, horizon_days, start_date, end_date, ret, bench_ret, excess, attrs, computed_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(run_id, entity_id, horizon_days) DO UPDATE SET start_date=excluded.start_date, "
                   "end_date=excluded.end_date, ret=excluded.ret, bench_ret=excluded.bench_ret, excess=excluded.excess, "
                   "attrs=excluded.attrs, computed_at=excluded.computed_at")


def write_pick_outcomes(conn, frame, superseded_before=None, since=None):
    """Realised pick returns → outcomes (upsert by run × stock × horizon). `frame`: pick_outcomes-shaped
    rows. With `superseded_before`, security outcomes computed before that time (on pick dates ≥ `since`)
    are removed, as compute_pick_outcomes removes them from the legacy table. Returns (upserted, removed)."""
    rows = _records(frame)
    runs = morning_runs(conn, [r["pick_date"] for r in rows])
    ents = entity_ids(conn, [r["sid"] for r in rows])
    ts = now()
    out = [(runs[r["pick_date"]], ents[r["sid"]], typed(r["window_days"], "INTEGER"), r["pick_date"], typed(r.get("exit_date"), "TEXT"),
            typed(r.get("fwd_return_pct"), "REAL"), typed(r.get("bench_return_pct"), "REAL"), typed(r.get("excess_return_pct"), "REAL"),
            attrs_json(r, PICK_OUTCOME_ATTRS), typed(r.get("computed_at"), "TEXT") or ts) for r in rows]
    n = 0
    for i in range(0, len(out), 5000):
        n += conn.executemany(_OUTCOME_UPSERT, out[i:i + 5000]).rowcount
    _count(n, "outcomes")
    gone = 0
    if superseded_before:
        gone = conn.execute("DELETE FROM outcomes WHERE computed_at < ? AND entity_id IN (SELECT entity_id FROM entities WHERE kind='security') "
                            "AND run_id IN (SELECT run_id FROM runs WHERE kind='morning'" + (" AND as_of_date >= ?" if since else "") + ")",
                            (superseded_before, since) if since else (superseded_before,)).rowcount
    return n, gone


def write_portfolio_outcomes(conn, frame):
    """Realised book returns → outcomes for the `book` entity (upsert by run × horizon)."""
    rows = _records(frame)
    runs = morning_runs(conn, [r["asof_date"] for r in rows])
    e = book_entity(conn)
    ts = now()
    out = [(runs[r["asof_date"]], e, typed(r["window_days"], "INTEGER"), r["asof_date"], None, typed(r.get("hrp_return_pct"), "REAL"),
            typed(r.get("bench_return_pct"), "REAL"), typed(r.get("hrp_excess_pct"), "REAL"), attrs_json(r, BOOK_OUTCOME_ATTRS),
            typed(r.get("computed_at"), "TEXT") or ts) for r in rows]
    n = conn.executemany(_OUTCOME_UPSERT, out).rowcount
    _count(n, "outcomes")
    return n


def _count(n, table):
    try:
        import db
        db._count_write(table, n)
    except Exception:  # noqa: BLE001 — the run log's row count is best-effort
        pass
