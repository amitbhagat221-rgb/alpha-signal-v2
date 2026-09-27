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
    for d in [date(2026, 9, 28) + timedelta(days=i) for i in range(7)] + [date(2026, 10, 1), date(2026, 11, 1)]:
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


def test_runner_executes_the_derived_order(monkeypatch, caplog):
    """config.PIPELINE['derived_order'] → run_pipeline runs graph.order, not list order."""
    import logging
    import pipeline
    steps = [("b", "m", "f", False), ("a", "m", "f", False)]
    monkeypatch.setitem(pipeline.PIPELINE, "derived_order", True)
    monkeypatch.setattr(pipeline, "shadow_order", lambda s, write=True: {"derived": ["a", "b"]})
    with caplog.at_level(logging.INFO, logger="pipeline"):
        pipeline.run_pipeline(steps, dry_run=True)
    lines = [r.getMessage() for r in caplog.records if "→ m.f()" in r.getMessage()]
    assert [l.split()[1] for l in lines] == ["a", "b"]
    monkeypatch.setitem(pipeline.PIPELINE, "derived_order", False)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="pipeline"):
        pipeline.run_pipeline(steps, dry_run=True)
    lines = [r.getMessage() for r in caplog.records if "→ m.f()" in r.getMessage()]
    assert [l.split()[1] for l in lines] == ["b", "a"]


def test_post_check_failure_fails_the_step_without_retry(monkeypatch):
    import pipeline
    calls = []
    monkeypatch.setattr(pipeline, "log_step", lambda *a, **k: calls.append(a[1]))
    monkeypatch.setitem(pipeline.STEP_SPECS, "x", {"name": "x", "table": "t", "reads": []})
    monkeypatch.setattr(pipeline, "_post_check", lambda n: ["t is OUTDATED after x"])
    import types, sys
    mod = types.ModuleType("fake_step_mod"); mod.run = lambda: 3
    monkeypatch.setitem(sys.modules, "fake_step_mod", mod)
    assert pipeline.run_step("x", "fake_step_mod", "run", False) is None
    assert calls == ["RUNNING", "FAILED"]
    monkeypatch.setattr(pipeline, "_post_check", lambda n: [])
    assert pipeline.run_step("x", "fake_step_mod", "run", False) is True


def test_month_start_scrapes_stay_off_the_email_path():
    """Review F1 (2026-09-27): the monthly Tickertape scrapes (~3.6h together) were
    email ancestors on the 1st — the 2026-09-01 email went out at 07:47 UTC. Their
    writes are declared lagged, so on a weekday 1st neither may precede the email."""
    from datetime import date
    import config
    import pipeline

    class D(date):
        @classmethod
        def today(cls):
            return date(2026, 10, 1)            # a Thursday
    real, pipeline.date = pipeline.date, D
    try:
        act = [s for s in config.PIPELINE_STEPS if pipeline._step_should_run_today(s)]
    finally:
        pipeline.date = real
    names = {s["name"] for s in act}
    assert {"fetch_analyst", "fetch_shareholding"} <= names
    assert not {"fetch_analyst", "fetch_shareholding"} & graph.ancestors(act)


def test_critical_failure_aborts_alerts_once_and_exits_nonzero(monkeypatch, tmp_path):
    """Review F3: a critical failure used to log 'Email alert would fire here' and exit 0."""
    import sys
    import config
    import pipeline
    ran, alerts = [], []
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)            # graph_shadow report
    monkeypatch.setattr(pipeline, "shadow_order", lambda s, write=True: None)
    monkeypatch.setattr(pipeline, "log_step", lambda *a, **k: None)
    monkeypatch.setattr(pipeline, "time", type("T", (), {"time": staticmethod(lambda: 0.0),
                                                         "sleep": staticmethod(lambda s: None)}))
    monkeypatch.setattr(pipeline, "run_step",
                        lambda name, *a: ran.append(name) or name != "fetch_bhavcopy")
    monkeypatch.setattr(pipeline, "_alert_critical", lambda names: alerts.append(list(names)))
    steps = [("fetch_bhavcopy", "m", "f", True), ("screener", "m", "f", True), ("email", "m", "f", False)]
    res = pipeline.run_pipeline(steps)
    assert res["failed_critical"] and alerts == [["fetch_bhavcopy"]]
    assert ran == ["fetch_bhavcopy", "fetch_bhavcopy"]                  # retried once, then abort
    monkeypatch.setattr(pipeline, "run_pipeline", lambda s, dry_run=False: res)
    monkeypatch.setattr(sys, "argv", ["pipeline.py"])
    monkeypatch.setattr(pipeline, "STEPS", steps)
    monkeypatch.setattr(pipeline, "_step_should_run_today", lambda spec: True)
    monkeypatch.setattr(pipeline, "STEP_SPECS", {n: {} for n, *_ in steps})
    try:
        pipeline.main()
        raise AssertionError("main() returned normally after a critical failure")
    except SystemExit as e:
        assert e.code == 1
