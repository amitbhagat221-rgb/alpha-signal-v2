"""tools.lh_costs honours ALPHA_LH (a worktree has no data/, so costs.json lives in the main tree)."""
import importlib


def test_alpha_lh_sets_costs_path(monkeypatch, tmp_path):
    monkeypatch.setenv("ALPHA_LH", str(tmp_path))
    from tools import lh_costs
    try:
        mod = importlib.reload(lh_costs)
        assert mod.OUT == tmp_path / "costs.json"
    finally:
        monkeypatch.delenv("ALPHA_LH")
        importlib.reload(lh_costs)


def test_default_costs_path_without_alpha_lh(monkeypatch):
    monkeypatch.delenv("ALPHA_LH", raising=False)
    from tools import lh_costs
    mod = importlib.reload(lh_costs)
    assert mod.OUT == mod.ROOT / "data" / "lh" / "costs.json"
