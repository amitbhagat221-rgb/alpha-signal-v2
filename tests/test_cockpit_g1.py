"""G1 pages: model weights/validation source, action queue counts, outcome colouring."""
import re

from fastapi.testclient import TestClient


def test_weights_pct_uses_absolute_weights():
    from cockpit_ops.api import get_model_overview
    tiers = get_model_overview.__wrapped__()["tiers"] if hasattr(get_model_overview, "__wrapped__") else get_model_overview()["tiers"]
    for rows in tiers.values():
        assert all(0 <= r["pct"] <= 100 for r in rows)
        assert abs(sum(r["pct"] for r in rows) - 100) < 1.0
        assert all(r["inverted"] == (r["weight"] < 0) for r in rows)


def test_validation_reads_current_evidence_not_v1_csv():
    import cockpit_ops.api as ops
    assert not hasattr(ops, "V1_BACKTEST_DIR")
    v = ops.get_validation_evidence()
    if v["rows"]:
        assert v["meta"]["n_wired"] == sum(r["wired"] for r in v["rows"])
        wired = [r["wired"] for r in v["rows"]]
        assert wired == sorted(wired, reverse=True)   # wired first


def test_outcome_decile_cells_coloured_by_sign():
    from cockpit.app import templates
    html = templates.get_template("model_outcomes.html").render(
        page="model-outcomes", top_n=10, request=None,
        summary={"windows_status": [], "by_window_tier": [], "headline_window": 63, "bench_staleness_days": 0,
                 "time_series": [],
                 "rank_deciles": [{"cap_tier": "LARGE", "decile": 1, "avg_fwd": -1.5},
                                  {"cap_tier": "LARGE", "decile": 10, "avg_fwd": 2.0}]})
    cells = re.findall(r'mo-decile-cell ([a-z]*)">\s*D(\d+)', html)
    assert cells == [("down", "1"), ("up", "10")]
