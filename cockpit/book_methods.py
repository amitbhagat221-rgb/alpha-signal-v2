"""
Alpha Signal Cockpit - the /book "Ways to weight" tab: today's model-book names, weighted by each
textbook method, judged on expected return and expected risk from today, then checked on the past year.

Every method gets the same names and the live book's caps (config.PORTFOLIO["hrp"]: per-stock and
per-sector ceilings, long only).

  Forward (the portfolios you would hold today)
    risk:   Ledoit-Wolf covariance of the last EST_DAYS trading days (adjusted closes), annualised
    return: tools.expected_return's forecast per stock = the tier's base market return
            + Grinold alpha (OOS-shrunk composite IC x dispersion x the stock's score z, capped)
    -> per method: expected return, expected volatility, expected Sharpe; the efficient frontier
  Past year (how each rule would have done)
    weights fitted on the year BEFORE the chart, bought at its start and held, no costs. The names
    and scores are today's, so every line shares the same hindsight in what was picked. One extra
    line, max Sharpe fitted on the chart year itself, shows the ceiling no one could have had.

  METHODS             key -> (label, short label, what it does); the order the page lists them
  weights_for(...)    pure: {key: weights} from covariance, return estimates, scores, sectors, caps
  frontier(...)       pure: the long-only capped efficient frontier, as (vol, return) points
  get_methods()       the page data

Sharpe here is return / volatility with no cash rate deducted.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from scipy.optimize import linprog, minimize
from sklearn.covariance import LedoitWolf

import config
import db
import portfolio_construction as pc
import views
from cockpit import api
from cockpit._shared import _persisted_cache
from cockpit.book import PAST_YEAR_INDICES, _beta
from tools import expected_return as er

EST_DAYS = 250            # trading days of returns each fit uses
MIN_EST_OBS = 120         # a name with fewer is left out of every method (named on the page)
SHOW_PCT = 0.5            # weights under this (percent) print as blank in the weights table
FRONTIER_POINTS = 25

METHODS = {   # key: (label, short label for the weights table, what it does)
    "live":        ("Today's book", "Today", "the live book's stored weights"),
    "model":       ("Model method", "Model", "HRP plus the score tilt: what the live book does"),
    "equal":       ("Equal weight", "Equal", "the same amount in every name"),
    "inv_vol":     ("Inverse volatility", "Inv vol", "more in the calmer names, ignoring how they move together"),
    "hrp":         ("HRP, no tilt", "HRP", "risk spread across groups of names that move together; ignores the score"),
    "erc":         ("Equal risk", "Eq risk", "each name adds the same share of the book's swings"),
    "min_var":     ("Minimum variance", "Min var", "the calmest mix the caps allow; ignores returns"),
    "max_div":     ("Most diversified", "Most div", "the most offsetting moves per unit of swing"),
    "sharpe_fwd":  ("Max Sharpe", "Max Sharpe", "Markowitz: the best expected return per unit of expected swing"),
    "return_fwd":  ("Max return", "Max return", "everything into the highest expected returns, up to the caps"),
    "sharpe_past": ("Max Sharpe, past returns", "Sharpe, past", "textbook Markowitz with last year's returns as the forecast"),
    "hindsight":   ("Max Sharpe in hindsight", "Hindsight", "fitted on the chart year itself: not achievable"),
}
HINDSIGHT = "hindsight"
HIGHLIGHT = ("model", "equal", "min_var", "sharpe_fwd")       # drawn in colour when the tab opens


# ── the optimisers (pure) ──────────────────────────────────────────────────────────

def _constraints(sectors, sector_cap):
    """SLSQP constraints: fully invested, and each sector at or under the cap."""
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    for s in sorted(set(sectors)):
        idx = np.array([i for i, x in enumerate(sectors) if x == s])
        cons.append({"type": "ineq", "fun": lambda w, idx=idx: sector_cap - w[idx].sum()})
    return cons


def _feasible(w, sectors, cap, sector_cap, tol=1e-6):
    return (abs(w.sum() - 1) < 1e-4 and w.min() >= -tol and w.max() <= cap + tol
            and pd.Series(w).groupby(list(sectors)).sum().max() <= sector_cap + tol)


def _solve(objective, n, sectors, cap, sector_cap, x0=None, extra=()):
    """Minimise `objective` over long-only weights under the stock and sector caps. SLSQP can stop
    early off the constraint set, so it retries from equal weights, and raises rather than
    rescaling an answer that breaks a cap."""
    best = None
    for start in ([] if x0 is None else [x0]) + [np.full(n, 1.0 / n)]:
        res = minimize(objective, start, method="SLSQP", bounds=[(0.0, cap)] * n,
                       constraints=_constraints(sectors, sector_cap) + list(extra),
                       options={"maxiter": 1000, "ftol": 1e-12})
        w = np.clip(res.x, 0, None)
        if _feasible(w, sectors, cap, sector_cap) and all(c["fun"](w) >= -1e-6 for c in extra):
            if res.success:
                return w / w.sum()
            best = best if best is not None and objective(best) <= objective(w) else w
    if best is None:
        raise RuntimeError(f"no portfolio within the caps (stock {cap:.0%}, sector {sector_cap:.0%})")
    return best / best.sum()


def _capped(w, sectors, cap, sector_cap):
    """The capped portfolio nearest to a rule's weights (least squares), so a rule that already
    fits the caps comes back unchanged."""
    target = np.asarray(w, dtype=float) / np.sum(w)
    return _solve(lambda x: ((x - target) ** 2).sum() * 1e4, len(target), sectors, cap, sector_cap,
                  x0=np.clip(target, 0, cap))


def max_return(mu, sectors, cap, sector_cap):
    """Linear programme: the highest expected return under the caps (fills the best names to the cap)."""
    n, secs = len(mu), sorted(set(sectors))
    a_ub = [[1.0 if x == s else 0.0 for x in sectors] for s in secs]
    res = linprog(-np.asarray(mu), A_ub=a_ub, b_ub=[sector_cap] * len(secs), A_eq=[[1.0] * n], b_eq=[1.0],
                  bounds=[(0.0, cap)] * n, method="highs")
    return res.x


def max_sharpe(mu, cov, sectors, cap, sector_cap):
    mu = np.asarray(mu)
    return _solve(lambda w: -(w @ mu) / np.sqrt(w @ cov @ w), len(mu), sectors, cap, sector_cap)


def min_variance(cov, sectors, cap, sector_cap):
    return _solve(lambda w: w @ cov @ w, len(cov), sectors, cap, sector_cap)


def weights_for(cov, mu_fwd, mu_past, scores, sectors, cap, sector_cap):
    """{method key: weights (np.array, sums to 1)} for every fitted method in METHODS.

    cov: annualised covariance (DataFrame, names in order); mu_fwd: forecast annual return per name;
    mu_past: the fit window's annualised mean return; scores: the model's final_score (the tilt
    reads its strength from config); sectors: sector per name. All in the same order."""
    names, c = list(cov.index), cov.values
    n, vol = len(names), np.sqrt(np.diag(cov.values))
    var = lambda w: w @ c @ w
    hrp = pc.hrp_weights(cov)
    out = {"model": _capped(pc.alpha_tilt(hrp, pd.Series(scores, index=names)).values, sectors, cap, sector_cap),
           "equal": _capped(np.ones(n), sectors, cap, sector_cap),
           "inv_vol": _capped(1 / vol, sectors, cap, sector_cap),
           "hrp": _capped(hrp.values, sectors, cap, sector_cap)}
    out["erc"] = _solve(lambda w: (((w * (c @ w)) / var(w) - 1.0 / n) ** 2).sum() * 1e4,
                        n, sectors, cap, sector_cap, x0=out["inv_vol"])
    out["min_var"] = min_variance(c, sectors, cap, sector_cap)
    out["max_div"] = _solve(lambda w: -(w @ vol) / np.sqrt(var(w)), n, sectors, cap, sector_cap)
    out["sharpe_fwd"] = max_sharpe(mu_fwd, c, sectors, cap, sector_cap)
    out["return_fwd"] = max_return(mu_fwd, sectors, cap, sector_cap)
    out["sharpe_past"] = max_sharpe(mu_past, c, sectors, cap, sector_cap)
    return out


def frontier(mu, cov, sectors, cap, sector_cap, points=FRONTIER_POINTS):
    """[(vol, return)] along the long-only capped frontier, from minimum variance to maximum return."""
    mu = np.asarray(mu)
    lo, hi = min_variance(cov, sectors, cap, sector_cap) @ mu, max_return(mu, sectors, cap, sector_cap) @ mu
    out = []
    for target in np.linspace(lo, hi, points):
        w = _solve(lambda w: w @ cov @ w, len(mu), sectors, cap, sector_cap,
                   extra=[{"type": "ineq", "fun": lambda w, t=target: w @ mu - t + 1e-9}])
        out.append((float(np.sqrt(w @ cov @ w)), float(w @ mu)))
    return out


# ── inputs ─────────────────────────────────────────────────────────────────────────

def forecasts(rows, pick_date):
    """{sid: (forecast annual return, capped score z)}: the tier's base market return plus Grinold
    alpha per unit of z (tools.expected_return.alpha_per_z) times the stock's final_score z within
    its whole ranked tier, capped at +-er.ZBAR_CAP. A held name not ranked today gets z = 0."""
    ranked = views.picks(pick_date, gated=False)
    z = ranked.groupby("cap_tier")["final_score"].transform(lambda s: (s - s.mean()) / (s.std() or 1.0))
    z = z.clip(-er.ZBAR_CAP, er.ZBAR_CAP).set_axis(ranked["sid"]).to_dict()
    per_z = {t: er.alpha_per_z(t) for t in {r["cap_tier"] for r in rows.values()}}
    return {s: (er.BETA_SCENARIOS[r["cap_tier"]]["base"] + per_z[r["cap_tier"]] * z.get(s, 0.0), z.get(s, 0.0))
            for s, r in rows.items()}


def _cov(ret):
    return LedoitWolf().fit(ret.values).covariance_ * 252


def _stats(path, ytd_base, bench):
    daily = path.pct_change().dropna()
    vol = float(daily.std() * 252 ** 0.5 * 100)
    y1 = float(path.iloc[-1] - 100)
    return {"ytd": float((path.iloc[-1] / path.at[ytd_base] - 1) * 100), "y1": y1, "vol": vol,
            "sharpe": y1 / vol if vol else None, "max_dd": float((path / path.cummax() - 1).min() * 100),
            "beta": _beta(path, bench)}


# ── the page data ──────────────────────────────────────────────────────────────────

@_persisted_cache(3600, name="book_methods_v7")
def get_methods():
    """Each weighting method on today's model-book names: today's weights with expected return and
    risk, the efficient frontier, and the past year bought-and-held. None before the first sized
    book or without index history."""
    from signals._prices import apply_adjustments
    sb = api.get_sized_book()
    idx = db.read_sql(
        f"SELECT index_symbol, trade_date, close FROM nse_index_history WHERE index_symbol IN "
        f"({','.join('?' * len(PAST_YEAR_INDICES))}) AND trade_date >= date('now', '-800 days')",
        params=list(PAST_YEAR_INDICES)).pivot(index="trade_date", columns="index_symbol", values="close").sort_index()
    if not sb or idx.empty:
        return None
    cal = idx.index
    T = cal[-1]
    y1_base = cal[cal <= (date.fromisoformat(T) - timedelta(days=365)).isoformat()][-1]
    ytd_base = cal[cal <= f"{int(T[:4]) - 1}-12-31"][-1]
    then_cal = cal[cal <= y1_base][-(EST_DAYS + 1):]
    rows = {r["sid"]: r for r in sb["rows"]}
    sids = sorted(rows)
    ph = ",".join("?" * len(sids))
    raw = db.read_sql(f"SELECT sid, date, close FROM stock_prices WHERE sid IN ({ph}) AND date >= ? ORDER BY sid, date",
                      params=sids + [then_cal[0]])
    adj = db.read_sql(f"SELECT sid, ex_date, factor FROM corporate_adjustments WHERE sid IN ({ph})", params=sids)
    px = (apply_adjustments(raw, adj, T).pivot(index="date", columns="sid", values="adj_close")
          .reindex(cal[cal >= then_cal[0]]).ffill())
    ret = px.pct_change().iloc[1:]
    then_ret, now_ret = ret.loc[:y1_base], ret.iloc[-EST_DAYS:]
    names = [s for s in sids if then_ret[s].notna().sum() >= MIN_EST_OBS and pd.notna(px.at[y1_base, s])]
    left_out = [rows[s]["ticker"] or s for s in sids if s not in names]

    sectors = [rows[s]["sector"] or "UNKNOWN" for s in names]
    scores = [rows[s]["factor_score"] for s in names]
    fc = forecasts({s: rows[s] for s in names}, api.latest_pick_date())
    mu_fwd = np.array([fc[s][0] for s in names])
    hrp_cfg = config.PORTFOLIO["hrp"]
    cap, sector_cap = hrp_cfg["max_stock_weight"], hrp_cfg["max_sector_weight"]
    live = np.array([rows[s]["weight"] for s in names])

    # ── forward: fitted on the last year, judged on the forecast ──
    now = now_ret[names].fillna(0.0)
    cov_now = pd.DataFrame(_cov(now), index=names, columns=names)
    ws_now = {"live": live / live.sum(),
              **weights_for(cov_now, mu_fwd, now.mean().values * 252, scores, sectors, cap, sector_cap)}
    forward = []
    for key, w in ws_now.items():
        label, short, blurb = METHODS[key]
        e_ret, e_vol = float(w @ mu_fwd * 100), float(np.sqrt(w @ cov_now.values @ w) * 100)
        forward.append({"key": key, "label": label, "short": short, "blurb": blurb, "e_ret": e_ret, "e_vol": e_vol,
                        "e_sharpe": e_ret / e_vol if e_vol else None, "eff_n": float(1 / (w ** 2).sum()),
                        "n_held": int((w * 100 >= SHOW_PCT).sum()), "max_w": float(w.max() * 100)})
    stock_vol = np.sqrt(np.diag(cov_now.values))
    scatter = {"frontier": [[round(v * 100, 2), round(r * 100, 2)]
                            for v, r in frontier(mu_fwd, cov_now.values, sectors, cap, sector_cap)],
               "methods": [{"key": f["key"], "label": f["label"], "x": round(f["e_vol"], 2), "y": round(f["e_ret"], 2)}
                           for f in forward],
               "stocks": [{"label": rows[s]["ticker"] or s, "x": round(float(v) * 100, 2), "y": round(float(m) * 100, 2)}
                          for s, v, m in zip(names, stock_vol, mu_fwd)]}

    # ── past year: fitted on the year before, bought at the start and held ──
    then = then_ret[names].fillna(0.0)
    cov_then = pd.DataFrame(_cov(then), index=names, columns=names)
    ws_then = {"live": live / live.sum(),
               **weights_for(cov_then, mu_fwd, then.mean().values * 252, scores, sectors, cap, sector_cap)}
    chart_ret = ret.loc[ret.index > y1_base, names].fillna(0.0)
    ws_then[HINDSIGHT] = max_sharpe(chart_ret.mean().values * 252, _cov(chart_ret), sectors, cap, sector_cap)
    rel = px.loc[y1_base:, names] / px.loc[y1_base, names]
    bench = idx[PAST_YEAR_INDICES[0]].loc[y1_base:]
    past, series = [], []
    for key, w in ws_then.items():
        path = rel.mul(w, axis=1).sum(axis=1) * 100
        label = METHODS[key][0]
        past.append({"key": key, "label": label, "kind": "method", **_stats(path, ytd_base, bench)})
        series.append({"key": key, "label": label, "short": METHODS[key][1], "kind": "hindsight" if key == HINDSIGHT else "method",
                       "values": [round(float(v), 2) for v in path.values]})
    for sym in PAST_YEAR_INDICES:
        s = idx[sym].loc[y1_base:].ffill()
        path = s / s.iloc[0] * 100
        past.append({"key": sym, "label": sym, "kind": "index", **_stats(path, ytd_base, bench)})
        series.append({"key": sym, "label": sym, "short": sym, "kind": "index", "values": [round(float(v), 2) for v in path.values]})

    grid = [{"sid": s, "ticker": rows[s]["ticker"] or s, "tier": rows[s]["cap_tier"], "sector": rows[s]["sector"],
             "e_ret": float(mu_fwd[i] * 100), "vol": float(stock_vol[i] * 100), "z": float(fc[s][1]),
             "w": {k: float(w[i]) * 100 for k, w in ws_now.items()}}
            for i, s in enumerate(names)]
    grid.sort(key=lambda g: -g["w"]["live"])
    market = {t: er.BETA_SCENARIOS[t]["base"] * 100 for t in config.PICKABLE_TIERS if t in er.BETA_SCENARIOS}
    return {"asof": T, "y1_base": y1_base, "ytd_base": ytd_base, "then_start": then_cal[0],
            "now_start": now_ret.index[0], "cap_pct": cap * 100, "sector_cap_pct": sector_cap * 100,
            "left_out": left_out, "market": market, "zcap": er.ZBAR_CAP,
            "shrink": {t: er.OOS_SHRINK[t] for t in market}, "show_pct": SHOW_PCT, "highlight": list(HIGHLIGHT),
            "forward": forward, "scatter": scatter, "past": past, "cols": list(ws_now),
            "short": {k: METHODS[k][1] for k in ws_now}, "grid": grid,
            "chart": {"dates": list(rel.index), "ytd_base": ytd_base, "series": series}}
