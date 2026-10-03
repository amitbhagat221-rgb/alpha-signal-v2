"""factors.py is the one factor registry; every factor list is derived from it.

The hand-kept lists it replaced were checked equal to their derived versions
before deletion (commit "feat(factors): one factor registry"); the resolved
discrepancies are pinned here, plus the invariants that keep the registry whole.
"""
import config
import db
import factors
from eligibility import registry as eligibility
import pit
from tools import backtest_pit, pit_replay


def test_consumers_use_the_registry():
    assert db.BACKTEST_SIGNALS is factors.BACKTEST_SIGNALS
    assert db.FACTOR_LIBRARY is factors.FACTOR_LIBRARY
    assert db.get_backtest_cadence is factors.get_backtest_cadence
    assert not hasattr(config, "SIGNAL_WEIGHTS")          # weights live on the factor (D4)
    assert backtest_pit.SIGNAL_COLUMN_MAP is factors.SIGNAL_COLUMN_MAP
    assert pit.PIT_COLUMNS is factors.PIT_COLUMNS
    assert pit.VALIDATION_RANGES is factors.VALIDATION_RANGES
    assert eligibility.SIGNAL_ELIGIBILITY is factors.SIGNAL_ELIGIBILITY
    assert pit_replay.INPUT_COLS is factors.SCREENER_INPUT_COLS


def test_resolved_discrepancies():
    # momentum: dropped from SIGNAL_WEIGHTS 2026-07-05 but never benched
    assert {"mom_6m_adj", "mom_12m_adj"} <= set(factors.FACTOR_LIBRARY)
    # pt_upside: pulled (ADR 0045), only zero weights were left
    assert factors.FACTOR_STATUS["pt_upside"] == "BLOCKED"
    # financial_quality/_recovery carry their alias financial_signal range
    assert factors.VALIDATION_RANGES["financial_quality"] == (-3, 3, True)
    # backtest keys on the registry id; news_volume is backtested; v2 column known
    assert "momentum_composite" in factors.SIGNAL_COLUMN_MAP and "mom_composite" not in factors.SIGNAL_COLUMN_MAP
    assert factors.SIGNAL_COLUMN_MAP["news_volume"] == (None, "news_volume_7d")
    assert factors.SIGNAL_COLUMN_MAP["earnings_beat_rate"] == ("earnings_beat_rate", "earnings_beat_rate")
    # momentum ranks mom_12m in SMALL, mom_6m elsewhere — one alias, tier-aware
    assert factors.signal_for("momentum", "SMALL") == "mom_12m_adj"
    assert factors.signal_for("momentum", "LARGE") == factors.signal_for("momentum") == "mom_6m_adj"


def test_partition_holds():
    assert factors.partition_check() == ([], [])


def test_wired_factors_follow_weights():
    wired = {k for tw in factors.SIGNAL_WEIGHTS.values() for k, w in tw.items() if w}
    assert set(factors.wired_weight_keys()) == wired
    for key in wired:   # every wired factor is scored and frozen (checks/model.py reads the freeze)
        assert key in factors.SCREENER_COLS
        assert factors.SCREENER_COLS[key] in pit_replay.INPUT_COLS
        assert factors.status(factors.signal_for(key)) == "WIRED"


def test_pit_columns_ranged_and_produced():
    for col in factors.PIT_COLUMNS[3:]:
        assert col in factors.VALIDATION_RANGES, col
    for name, spec in factors.PIT_PRODUCERS.items():
        if spec["fn"]:
            assert callable(getattr(pit, spec["fn"], None)), name
    for sid, (v1, v2) in factors.SIGNAL_COLUMN_MAP.items():
        assert v2 is None or v2 in factors.PIT_COLUMNS, sid


def test_live_pit_cols_are_screener_columns():
    assert set(factors.LIVE_PIT_COLS) <= set(factors.SCREENER_INPUT_COLS)


def test_one_range_per_column():
    """A PIT column registered under two factor ids must carry ONE validation range
    (plan 0015: eps_revision_yoy vs consensus_signal_combined disagreed)."""
    import factors
    eps = {tuple(factors.FACTORS[k]["pit_range"]) for k in ("eps_revision_yoy", "consensus_signal_combined")}
    assert len(eps) == 1


# ── Weights live on the factor (ADR 0052 D4); SIGNAL_WEIGHTS is derived ──

def test_weights_sum_to_one_per_tier():
    """Σ|w| = 1.0 in every rankable tier (ADR 0049 rule; the screener's
    weight_coverage denominator assumes it)."""
    assert tuple(factors.SIGNAL_WEIGHTS) == factors.TIERS == config.PICKABLE_TIERS
    for tier, tw in factors.SIGNAL_WEIGHTS.items():
        assert tw, tier
        assert abs(sum(abs(w) for w in tw.values()) - 1.0) < 1e-9, (tier, tw)


def test_weight_sign_and_tier_sanity():
    for sid, f in factors.FACTORS.items():
        w = f.get("weights")
        if not w:
            continue
        assert set(w) <= set(factors.TIERS), sid            # only rankable tiers
        assert all(v != 0 and abs(v) <= 0.35 for v in w.values()), sid   # no zero rows; cap ~0.30
        assert not f.get("bench"), sid                      # wired ⇒ not benched
        assert "tiers" not in f or set(w) <= set(f["tiers"]), sid
        assert f["weight_key"] in factors.SCREENER_COLS or "tiers" in f, sid
        # sign: negative only for event penalties (ADR 0042) — a new negative weight
        # must be added here deliberately, with its evidence.
        if any(v < 0 for v in w.values()):
            assert sid in {"governance_resignation"}, sid
    # the derived view keys each weight by the screener's name, tier-aware
    for tier, tw in factors.SIGNAL_WEIGHTS.items():
        for key, w in tw.items():
            assert factors.FACTORS[factors.signal_for(key, tier)]["weights"][tier] == w


def test_signal_weights_order_is_canonical():
    """Heaviest |w| first, ties by key — the screener sums in this order."""
    for tw in factors.SIGNAL_WEIGHTS.values():
        items = list(tw.items())
        assert items == sorted(items, key=lambda kw: (-abs(kw[1]), kw[0]))


def test_variants_are_weight_keys():
    for scheme in factors.WEIGHT_SCHEMES[1:]:
        for tier, tw in getattr(factors, scheme).items():
            assert tier in factors.TIERS
            for key in tw:
                assert factors.signal_for(key, tier) in factors.FACTORS, (scheme, key)


def test_inferred_fields_are_not_restated():
    """An explicit field equal to its inferred default is noise (plan 0015 Phase 6)."""
    import ast, re
    src = open(factors.__file__).read()
    body = src[src.index("FACTORS = {"):src.index("\n}\n", src.index("FACTORS = {"))]
    restated = []
    for m in re.finditer(r'^    "(\w+)": \{\n(.*?)^    \},', body, re.S | re.M):
        sid, entry = m.group(1), m.group(2)
        fields = dict(re.findall(r'^        "(\w+)": (.*?),\s*(?:#.*)?$', entry, re.M))
        def lit(k):
            try:
                return ast.literal_eval(fields[k])
            except Exception:
                return object()
        f = factors.FACTORS[sid]
        defaults = {"pit_column_v1": None, "pit_column_v2": sid, "status": "READY",
                    "status_reason": "", "cadence": "monthly",
                    "screener_col": f.get("weight_key"),
                    "replay_col": factors.pit_column(sid) if "weight_key" in f else object()}
        if "weights" in fields:
            defaults["weight_key"] = sid
        restated += [(sid, k) for k, d in defaults.items() if k in fields and lit(k) == d]
    assert restated == []
    assert not any("live_table" in f for f in factors.FACTORS.values())   # read by nothing


# ── Table-level reads are stated once (FACTORS.source_tables); lineage derives ──

def _raw_sql_tables(key):
    import re
    sql = pit.RAW_SQL[key]
    sql = sql() if callable(sql) else sql
    return set(re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql))


def test_input_tables_match_pit_raw_sql():
    """factors.INPUT_TABLES (producer input → tables) is what pit actually loads."""
    used = {k for spec in factors.PIT_PRODUCERS.values()
            for k in (*spec.get("inputs", ()), *spec.get("needs", ()), *spec.get("nonempty", ()))}
    assert used <= set(factors.INPUT_TABLES)
    for key in used:
        raw_keys = [r for r in pit._INPUT_RAW.get(key, (key,)) if r in pit.RAW_SQL]
        expect = set().union(*(_raw_sql_tables(r) for r in raw_keys)) if raw_keys else set()
        assert set(factors.INPUT_TABLES[key]) == expect, key


def test_source_tables_are_the_producer_tables():
    for sid, f in factors.FACTORS.items():
        derived = factors.producer_tables(f.get("producer"))
        if derived:
            assert f["source_tables"] == derived, sid


def test_lineage_is_derived_for_every_factor():
    import lineage
    import sqlite3
    assert list(lineage.FACTOR_LINEAGE) == list(factors.FACTORS)
    assert lineage.missing_factors() == [] and lineage.orphan_factors() == []
    conn = sqlite3.connect(":memory:")
    conn.executescript(open(config.SCHEMA_PATH).read())
    schema = {t: {c[1] for c in conn.execute(f"PRAGMA table_info('{t}')")}
              for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for sid, detail in lineage.LINEAGE_DETAIL.items():
        tables = set(factors.FACTORS[sid]["source_tables"])
        for spec in detail.get("reads", []):
            # column detail only for tables the factor reads, naming real columns
            assert spec["table"] in tables, (sid, spec["table"])
            assert set(spec["cols"]) <= schema[spec["table"]], (sid, spec["table"])
    for sid, entry in lineage.FACTOR_LINEAGE.items():
        if "composite_of" not in entry:
            assert {r["table"] for r in entry["reads"]} == \
                set(factors.FACTORS[sid]["source_tables"]) - {"—"}, sid
