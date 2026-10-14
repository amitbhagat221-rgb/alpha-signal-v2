"""The /book "Ways to weight" optimisers: every method is fully invested, long only, under the stock
and sector caps, and each one does what its name says on a toy covariance."""
import numpy as np
import pandas as pd

from cockpit import book_methods as bm

CAP, SECTOR_CAP = 0.30, 0.50


def _toy():
    rng = np.random.default_rng(7)
    names = [f"S{i}" for i in range(8)]
    vol = np.array([0.15, 0.20, 0.25, 0.30, 0.18, 0.22, 0.35, 0.40])
    corr = np.full((8, 8), 0.3) + np.diag([0.7] * 8)
    cov = pd.DataFrame(np.outer(vol, vol) * corr, index=names, columns=names)
    mu_fwd = np.array([0.10, 0.11, 0.12, 0.13, 0.10, 0.11, 0.16, 0.18])
    mu_past = rng.normal(0.2, 0.3, 8)
    sectors = ["A", "A", "A", "B", "B", "C", "C", "D"]
    scores = np.linspace(0.4, 0.9, 8)
    return cov, mu_fwd, mu_past, sectors, scores


def test_every_method_is_invested_long_only_and_capped():
    cov, mu_fwd, mu_past, sectors, scores = _toy()
    ws = bm.weights_for(cov, mu_fwd, mu_past, scores, sectors, CAP, SECTOR_CAP)
    assert set(ws) == set(bm.METHODS) - {"live", bm.HINDSIGHT}
    for key, w in ws.items():
        assert abs(w.sum() - 1) < 1e-6, key
        assert w.min() >= -1e-9 and w.max() <= CAP + 1e-6, key
        by_sector = pd.Series(w).groupby(sectors).sum()
        assert by_sector.max() <= SECTOR_CAP + 1e-6, key


def test_each_method_wins_on_its_own_objective():
    cov, mu_fwd, mu_past, sectors, scores = _toy()
    ws = bm.weights_for(cov, mu_fwd, mu_past, scores, sectors, CAP, SECTOR_CAP)
    c = cov.values
    var = {k: w @ c @ w for k, w in ws.items()}
    ret = {k: w @ mu_fwd for k, w in ws.items()}
    sharpe = {k: ret[k] / np.sqrt(var[k]) for k in ws}
    assert min(var, key=var.get) == "min_var"
    assert max(ret, key=ret.get) == "return_fwd"
    assert max(sharpe, key=sharpe.get) == "sharpe_fwd"
    assert np.allclose(ws["equal"], 1 / 8)


def test_equal_risk_contributions_are_equal_when_caps_do_not_bind():
    cov, mu_fwd, mu_past, sectors, scores = _toy()
    w = bm.weights_for(cov, mu_fwd, mu_past, scores, list("ABCDEFGH"), 1.0, 1.0)["erc"]
    rc = w * (cov.values @ w)
    assert rc.max() / rc.min() < 1.02


def test_frontier_runs_from_min_variance_to_max_return():
    cov, mu_fwd, _, sectors, _ = _toy()
    pts = bm.frontier(mu_fwd, cov.values, sectors, CAP, SECTOR_CAP, points=6)
    vols, rets = zip(*pts)
    assert all(b >= a - 1e-6 for a, b in zip(rets, rets[1:]))     # return rises along the line
    assert all(b >= a - 1e-6 for a, b in zip(vols, vols[1:]))     # and so does risk
    w_min = bm.min_variance(cov.values, sectors, CAP, SECTOR_CAP)
    assert abs(vols[0] - np.sqrt(w_min @ cov.values @ w_min)) < 1e-4
