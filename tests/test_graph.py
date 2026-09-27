"""graph.py — order, lagged edges, critical path (plan 0015 Phase 1)."""
import pytest

import graph


def _s(name, freq="daily", reads=(), writes=(), **kw):
    return {"name": name, "frequency": freq, "reads": list(reads), "writes": list(writes), **kw}


def test_lagged_write_keeps_slow_fetch_off_the_critical_path():
    """The 2026-09-27 incident: a slow weekly fetch feeding a daily signal must not
    sit on the critical path — its write is declared lagged."""
    steps = [
        _s("fetch_bhavcopy", writes=["stock_prices"]),
        _s("fetch_yf_analyst", "weekly", reads=["stocks"], writes=["analyst_consensus"]),
        _s("signal_consensus", reads=["analyst_consensus", "stock_prices"], writes=["consensus_signals"]),
        _s("screener", reads=["consensus_signals", "stock_prices"], writes=["daily_picks"]),
        _s("email", reads=["daily_picks"]),
    ]
    assert graph.slow_on_critical_path(steps, {"fetch_yf_analyst": 14.0}) == ["fetch_yf_analyst"]
    assert "fetch_yf_analyst" in graph.ancestors(steps, needed_only=True)
    steps[1]["lagged_writes"] = ["analyst_consensus"]
    kinds = {(w, r): k for w, r, _, k in graph.edges(steps)}
    assert kinds[("fetch_yf_analyst", "signal_consensus")] == "lagged"
    assert kinds[("signal_consensus", "screener")] == "blocking"
    order = graph.order(steps)
    assert order.index("email") < order.index("fetch_yf_analyst")
    assert order.index("signal_consensus") < order.index("fetch_yf_analyst")   # sees last week's
    assert graph.ancestors(steps, needed_only=True) == {"fetch_bhavcopy", "signal_consensus", "screener"}
    assert graph.slow_on_critical_path(steps, {"fetch_yf_analyst": 14.0}) == []


def test_order_respects_blocking_edges_and_keeps_list_position_otherwise():
    steps = [_s("b", reads=["t_a"]), _s("a", writes=["t_a"]), _s("c"), _s("email", reads=["t_b"]),
             _s("d", writes=["t_b"])]
    order = graph.order(steps)
    assert order.index("a") < order.index("b")
    assert order.index("d") < order.index("email")
    assert order.index("c") > order.index("email")        # not needed by the email → after it


def test_declared_lagged_read():
    steps = [_s("classify", writes=["stocks"]), _s("screener", reads=["stocks"], lagged_reads=["stocks"]),
             _s("email", reads=[])]
    assert {k for *_, k in graph.edges(steps)} == {"lagged"}


def test_lagged_read_sees_previous_version_deterministically():
    steps = [_s("screener", reads=["health_score"], writes=["daily_picks"], lagged_reads=["health_score"]),
             _s("health", reads=["daily_picks"], writes=["health_score"]), _s("email", reads=["daily_picks"])]
    order = graph.order(steps)
    v = graph.read_versions(steps, order)
    assert v[("health", "screener", "health_score")] is False     # previous run's UHS
    assert v[("screener", "health", "daily_picks")] is True


def test_cycle_raises():
    with pytest.raises(ValueError, match="cycle"):
        graph.order([_s("x", reads=["b"], writes=["a"]), _s("y", reads=["a"], writes=["b"]), _s("email")])


def test_runner_tables_are_not_edges():
    steps = [_s("a", writes=["pipeline_log"]), _s("email", reads=["pipeline_log"])]
    assert graph.edges(steps) == []


def test_lagged_reader_is_pinned_before_its_writer():
    """A reader of the PREVIOUS version must run before the writer — it lands on the
    critical path even though the email does not need its output."""
    steps = [_s("sector_dossiers", reads=["snap"], lagged_reads=["snap"]),
             _s("snapshot", writes=["snap"]), _s("email", reads=["snap"])]
    assert graph.ancestors(steps, needed_only=True) == {"snapshot"}
    assert graph.ancestors(steps) == {"snapshot", "sector_dossiers"}


def test_runtime_check_flags_undeclared_reads(monkeypatch):
    import pipeline
    monkeypatch.setitem(pipeline.STEP_SPECS, "x", {"name": "x", "table": "t_out", "reads": ["t_in"]})
    monkeypatch.setattr(pipeline, "UNDECLARED", {})
    pipeline._check_declared("x", {"reads": {"t_in", "t_out", "t_hidden", "pipeline_log"}, "writes": {"t_out"}})
    assert pipeline.UNDECLARED == {"x": {"reads": ["t_hidden"], "writes": []}}


def test_every_step_declares_reads_and_the_graph_orders():
    """Every step declares `reads`; the derived order exists for every day type and
    gives every read the SAME version (this run / previous run) as the list order."""
    from datetime import date, timedelta
    import config
    import pipeline
    from tables import TABLES
    known = set(TABLES) | {"file:dossiers"}
    for s in config.PIPELINE_STEPS:
        assert "reads" in s, s["name"]
        assert set(s["reads"]) <= known, (s["name"], set(s["reads"]) - known)
    for d in [date(2026, 9, 28) + timedelta(days=i) for i in range(7)] + [date(2026, 11, 1)]:
        class D(date):
            @classmethod
            def today(cls):
                return d
        monkeypatch_date = pipeline.date
        pipeline.date = D
        try:
            act = [s for s in config.PIPELINE_STEPS if pipeline._step_should_run_today(s)]
        finally:
            pipeline.date = monkeypatch_date
        cur = [s["name"] for s in act]
        assert graph.read_versions(act, cur) == graph.read_versions(act, graph.order(act)), d
