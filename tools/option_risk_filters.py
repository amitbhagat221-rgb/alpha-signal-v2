"""
Alpha Signal v2 — can any market factor avoid or shrink the option book's worst weeks?

Pre-registered 2026-10-22: docs/studies/option-risk-filters-preregistration-2026-10.md.
Study: docs/studies/option-risk-filters-2026-10.md.  READ-ONLY: writes nothing to the DB, changes no rule.

The rule under test is plan 0022: NIFTY weekly 0.05-delta short strangle, entered 2 sessions before
expiry, held to expiry (SENSEX from 2024 as a second check).  Per-trade results come from the same
code as tools/option_premium_backtest.py (exp2 / delta 0.05 / strangle).

For each candidate predictor (value known at the entry close) three actions are tested:
  skip      the trade when the predictor is beyond a threshold
  half      trade at half size beyond the threshold
  scaled    size proportional to 1/VIX or 1/20-day realised vol (no threshold)
Thresholds are picked on 2019-02 → 2022-12 only (70/80/90/95th percentile of that window, best
P&L ÷ max drawdown there) and frozen for 2023-01 → 2026-10.  A walk-forward logistic model on all
predictors is the combined test.  See the pre-registration for the decision rule.

Usage:
  python -m tools.option_risk_filters                       # full study, prints every table
  python -m tools.option_risk_filters --csv rules.csv       # also write the per-rule table
  python -m tools.option_risk_filters --smoke               # 40 trades only
"""

import argparse
from datetime import date, timedelta

import numpy as np
import pandas as pd

CAPITAL = 3_500_000            # ₹35 L: the base book deploys all of it as margin every week
CHOOSE = ("2019-02-01", "2022-12-31")
TEST = ("2023-01-01", "2026-12-31")
PCTS = (70, 80, 90, 95)
HALF = 0.5
DD_FALL = 0.30                 # decision rule: max drawdown falls at least this much
PNL_KEEP = 0.85                # decision rule: keep at least this share of the base P&L
BAD_Q = 0.05                   # combined model: "bad trade" = bottom 5 % of training returns
TOP_DECILE = 0.90
N_PERM = 20000

# Danger direction fixed BEFORE running (pre-registration: "beyond a threshold").  HI = only the high
# tail is dangerous by construction (a strangle seller is hurt by big vol or big moves of either sign);
# BOTH = sign unknown a priori, so both tails are tested and counted.
HI = ("vix", "vix_chg5", "vix_pct252", "rv5", "rv20", "abs_ret1", "abs_ret5", "abs_ret20",
      "abs_dist20", "abs_dist50", "dd52")
BOTH = ("iv_rv", "atm_iv", "iv_skew", "iv_term", "pcr_oi", "pcr_vol", "max_pain_dist", "fii_fut", "fii_opt",
        "ret5", "ret20", "us10y_chg5", "usdinr_chg5", "brent_chg5", "credit_m", "z_strike")
BINARY = ("ev_any", "ev_rbi", "ev_fomc", "ev_budget_elec", "holiday", "regime_caution")
# only NIFTY + VIX history needed -> also testable on the 2015-2019 stress model
STRESS_OK = ("vix", "vix_chg5", "vix_pct252", "rv5", "rv20", "abs_ret1", "abs_ret5", "abs_ret20",
             "abs_dist20", "abs_dist50", "dd52", "iv_rv", "ret5", "ret20", "regime_caution")
# no series in the DB for these (listed as untested in the study)
UNTESTED = {
    "us_vix": "no US VIX series in macro_history or any table",
    "sp500_1d_5d": "no S&P 500 series in the DB (macro_history has only India indices, US 10y, USDINR, Brent, metals)",
    "fii_cash_5d": "fii_dii_cash_flow starts 2026-04-30 (112 days): no 2019-2026 history",
}
FII_SINCE = "2022-01-03"       # fii_dii_positioning starts here: choose window for fii_* is 2022 only (thin)


# ───────────────────────── point-in-time predictors ─────────────────────────

def asof_strict(series, dates):
    """Value of `series` (index = ISO date) on the last observation STRICTLY before each date.

    Used for anything that may print after the Indian close (US 10y, Brent, FII participant OI)."""
    s = series.dropna().sort_index()
    idx = np.searchsorted(s.index.values.astype(str), np.asarray(dates, dtype=str), side="left") - 1
    return pd.Series([s.iloc[i] if i >= 0 else np.nan for i in idx], index=list(dates), dtype=float)


def regime_series(vix):
    """scoring/regime.py replayed on history: regime from VIX, 3-day hysteresis (config.REGIMES).

    The live module is a pure function of the VIX path and the previous state, so its history IS
    reconstructable point in time (it equals a VIX-band rule with a short lag)."""
    import config
    def band(v):
        for name, spec in config.REGIMES.items():
            lo, hi = spec["vix"]
            if lo <= v < hi:
                return name
        return "NORMAL"
    order = list(config.REGIMES)
    out, cur, hist = {}, None, []
    for d, v in vix.dropna().items():
        r = band(v)
        hist.append(r)
        if cur is None:
            cur = r
        elif len(hist) >= config.VIX_HYSTERESIS_DAYS and all(h == r for h in hist[-config.VIX_HYSTERESIS_DAYS:]):
            cur = r
        out[d] = order.index(cur)
    return pd.Series(out)


def build_market(raw):
    """Daily market predictors, one row per NIFTY session, each using data dated <= that session close
    (macro and FII series strictly earlier).  Pure function of `raw`, so it can be unit-tested for look-ahead.

    raw: close (Series by ISO date), vix (Series), iv (DataFrame by date: atm_iv, iv_skew_25d, iv_term_structure),
         pcr (DataFrame by date: pcr_oi, pcr_volume, max_pain_distance), fii (DataFrame by date: long/short cols),
         macro (dict name -> Series)."""
    close = raw["close"].astype(float).sort_index()
    d = pd.DataFrame(index=close.index)
    d["close"] = close
    vix = raw["vix"].astype(float).sort_index().reindex(close.index).ffill()
    d["vix"] = vix
    d["vix_chg5"] = vix / vix.shift(5) - 1
    d["vix_pct252"] = vix.rolling(252, min_periods=200).apply(lambda w: (w[:-1] < w[-1]).mean(), raw=True)
    lr = np.log(close).diff()
    d["rv5"] = lr.rolling(5).std() * np.sqrt(252) * 100
    d["rv20"] = lr.rolling(20).std() * np.sqrt(252) * 100
    d["iv_rv"] = vix - d["rv20"]
    d["ret1"] = close.pct_change(1)
    d["ret5"] = close.pct_change(5)
    d["ret20"] = close.pct_change(20)
    for k in (1, 5, 20):
        d[f"abs_ret{k}"] = d[f"ret{k}"].abs()
    d["abs_dist20"] = (close / close.rolling(20).mean() - 1).abs()
    d["abs_dist50"] = (close / close.rolling(50).mean() - 1).abs()
    d["dd52"] = 1 - close / close.rolling(252, min_periods=200).max()          # depth below the 52-week high (>= 0)
    reg = regime_series(vix)
    d["regime"] = reg.reindex(d.index)
    d["regime_caution"] = (d["regime"] >= 2).astype(float)                     # CAUTION or CRISIS
    for col, src in (("atm_iv", "atm_iv"), ("iv_skew", "iv_skew_25d"), ("iv_term", "iv_term_structure")):
        s = raw["iv"][src] * (100 if col == "atm_iv" else 1)
        d[col] = s.reindex(d.index)
    for col, src in (("pcr_oi", "pcr_oi"), ("pcr_vol", "pcr_volume"), ("max_pain_dist", "max_pain_distance")):
        d[col] = raw["pcr"][src].reindex(d.index)
    f = raw["fii"]
    if len(f):
        fut = (f["future_index_long"] - f["future_index_short"]) / (f["future_index_long"] + f["future_index_short"])
        opt = (((f["option_index_call_long"] - f["option_index_call_short"])
                - (f["option_index_put_long"] - f["option_index_put_short"]))
               / (f["option_index_call_long"] + f["option_index_call_short"]
                  + f["option_index_put_long"] + f["option_index_put_short"]))
        d["fii_fut"] = asof_strict(fut, d.index)                                # participant OI prints after the close
        d["fii_opt"] = asof_strict(opt, d.index)
    else:
        d["fii_fut"] = d["fii_opt"] = np.nan
    m = raw["macro"]
    d["us10y_chg5"] = _chg5(m["us_10y"], d.index, diff=True)
    d["usdinr_chg5"] = _chg5(m["usdinr"], d.index)
    d["brent_chg5"] = _chg5(m["brent_crude"], d.index)
    return d


def _chg5(series, dates, diff=False):
    """5-observation change of a macro series as known strictly before each session."""
    s = series.dropna().sort_index()
    s5 = s - s.shift(5) if diff else s / s.shift(5) - 1
    return asof_strict(s5, dates)


def event_flags(entry, expiry):
    """Scheduled events landing inside the hold (calendars are public in advance, hence PIT)."""
    import tools.option_premium_backtest as opb
    rbi = any(entry < x <= expiry for x in opb.RBI_MPC_DAYS)
    fomc = any(entry <= x < expiry for x in opb.FOMC_DAYS)
    big = any(entry < x <= expiry for x in opb.BUDGET_DAYS + opb.ELECTION_RESULT_DAYS)
    return {"ev_rbi": float(rbi), "ev_fomc": float(fomc), "ev_budget_elec": float(big),
            "ev_any": float(rbi or fomc or big)}


def holiday_in_window(entry, expiry, sessions):
    """True when a weekday strictly between entry and expiry was not a trading session."""
    sset = set(sessions)
    d = date.fromisoformat(entry) + timedelta(days=1)
    end = date.fromisoformat(expiry)
    while d < end:
        if d.weekday() < 5 and d.isoformat() not in sset:
            return True
        d += timedelta(days=1)
    return False


def trade_features(trades, mkt):
    """One row per trade: market predictors at the entry close + the trade's own richness measures."""
    X = mkt.reindex(trades["entry"].values).reset_index(drop=True)
    sessions = list(mkt.index)
    ev = [event_flags(e, x) for e, x in zip(trades.entry, trades.expiry)]
    X = pd.concat([X, pd.DataFrame(ev)], axis=1)
    X["holiday"] = [float(holiday_in_window(e, x, sessions)) for e, x in zip(trades.entry, trades.expiry)]
    X["credit_m"] = (trades["credit"] / trades["margin"]).values
    dte = np.array([(date.fromisoformat(x) - date.fromisoformat(e)).days for e, x in zip(trades.entry, trades.expiry)])
    s = trades["vix"].values / 100 * np.sqrt(dte / 365)
    X["z_strike"] = 0.5 * (np.log(trades.short_call.values / trades.F.values)
                           + np.log(trades.F.values / trades.short_put.values)) / s
    X.index = trades.index
    return X


# ───────────────────────── books and metrics ─────────────────────────

def book(ret, size, years):
    """P&L, drawdown and friends for per-trade returns (fraction of margin) at per-trade size."""
    r = np.asarray(ret) * np.asarray(size)
    cum = np.concatenate([[0.0], np.cumsum(r)])
    dd = float((cum - np.maximum.accumulate(cum)).min())
    pnl = float(r.sum())
    traded = np.asarray(size) > 0
    return {"n": int(traded.sum()), "pnl": pnl, "ann": pnl / years, "ann_inr": pnl / years * CAPITAL,
            "worst": float(r[traded].min()) if traded.any() else 0.0, "dd": dd,
            "ratio": pnl / abs(dd) if dd < 0 else (np.inf if pnl > 0 else 0.0),
            "mean_size": float(np.mean(size))}


def window_years(a, b):
    return max((date.fromisoformat(b) - date.fromisoformat(a)).days / 365.0, 1e-9)


def in_window(entry, w):
    return ((entry >= w[0]) & (entry <= w[1])).values


def equal_margin(b0, b1):
    """The filtered book rescaled to the base book's average margin (rule 1-3 of the decision rule)."""
    k = 1.0 / b1["mean_size"] if b1["mean_size"] > 0 else np.nan
    return {"pnl": b1["pnl"] * k, "dd": b1["dd"] * k}


def verdict_conditions(base, filt):
    """The pre-registered decision rule on one window: (dd_fall_ok, ratio_ok, pnl_ok, numbers)."""
    em = equal_margin(base, filt)
    dd_change = em["dd"] / base["dd"] - 1 if base["dd"] < 0 else np.nan          # negative = smaller drawdown
    pnl_kept = em["pnl"] / base["pnl"] if base["pnl"] > 0 else np.nan
    c1 = bool(dd_change <= -DD_FALL)
    c2 = bool(filt["ratio"] > base["ratio"])
    c3 = bool(pnl_kept >= PNL_KEEP)
    return c1, c2, c3, {"dd_change_em": dd_change, "pnl_kept_em": pnl_kept}


# ───────────────────────── rules: choose on window 1, freeze, apply ─────────────────────────

def make_sizes(flag, action):
    return 1.0 - (1.0 if action == "skip" else HALF) * flag


def tails():
    """[(predictor, tail, column-sign)] in the fixed order; tail 'hi' flags x >= p, 'lo' flags -x >= p."""
    out = [(p, "hi") for p in HI] + [(p, t) for p in BOTH for t in ("hi", "lo")]
    return out


def choose_threshold(x, ret, entry, action):
    """(pct, thr) with the best P&L / max drawdown on the choose window; x already signed (higher = riskier)."""
    m = in_window(entry, CHOOSE)
    xc, rc = x[m], ret[m]
    ok = ~np.isnan(xc)
    if ok.sum() < 20:
        return None
    best = None
    for p in PCTS:
        thr = float(np.nanpercentile(xc[ok], p))
        flag = np.where(np.isnan(xc), 0.0, (xc >= thr).astype(float))
        b = book(rc, make_sizes(flag, action), window_years(*CHOOSE))
        key = (b["ratio"], p)
        if best is None or key > best[0]:
            best = (key, p, thr)
    return best[1], best[2]


def signed(X, pred, tail):
    x = X[pred].astype(float).values
    return x if tail == "hi" else -x


def flags_for(rule, X):
    x = signed(X, rule["pred"], rule["tail"])
    return np.where(np.isnan(x), 0.0, (x >= rule["thr"]).astype(float))


def build_rules(X, trades):
    """Pick every threshold rule on the choose window (binary predictors need none)."""
    ret = trades["ret"].values
    entry = trades["entry"]
    rules = []
    for action in ("skip", "half"):
        for pred in BINARY:
            if X[pred].isna().all():
                continue
            rules.append({"pred": pred, "tail": "hi", "action": action, "pct": None, "thr": 0.5})
        for pred, tail in tails():
            if pred not in X or X[pred].isna().all():
                continue
            x = signed(X, pred, tail)
            if pred.startswith("fii_"):
                m = (entry >= FII_SINCE).values
                x2 = np.where(m, x, np.nan)
            else:
                x2 = x
            pick = choose_threshold(x2, ret, entry, action)
            if pick is None:
                continue
            rules.append({"pred": pred, "tail": tail, "action": action, "pct": pick[0], "thr": pick[1]})
    return rules


def worst_labels(sizes, worst_idx):
    """One char per worst trade, in date order: S skipped, H halved, . untouched."""
    return "".join("S" if sizes[i] == 0 else ("H" if sizes[i] < 1 else ".") for i in worst_idx)


def evaluate(rules, X, trades, worst_idx):
    rows = []
    ret, entry = trades["ret"].values, trades["entry"]
    for r in rules:
        flag = flags_for(r, X)
        size = make_sizes(flag, r["action"])
        row = dict(r)
        row["name"] = f"{r['pred']}{'' if r['pred'] in BINARY or r['tail'] == 'hi' else '(low)'}"
        row["worst4"] = worst_labels(size, worst_idx)
        for tag, w in (("c", CHOOSE), ("t", TEST)):
            m = in_window(entry, w)
            yrs = window_years(*w)
            b0 = book(ret[m], np.ones(m.sum()), yrs)
            b1 = book(ret[m], size[m], yrs)
            c1, c2, c3, nums = verdict_conditions(b0, b1)
            row.update({f"{tag}_n": b1["n"], f"{tag}_ann": 100 * b1["ann"], f"{tag}_inr": b1["ann_inr"],
                        f"{tag}_worst": 100 * b1["worst"], f"{tag}_dd": 100 * b1["dd"], f"{tag}_ratio": b1["ratio"],
                        f"{tag}_base_ratio": b0["ratio"], f"{tag}_given_up": 100 * (1 - b1["pnl"] / b0["pnl"]),
                        f"{tag}_dd_change": 100 * nums["dd_change_em"], f"{tag}_pnl_kept_em": 100 * nums["pnl_kept_em"],
                        f"{tag}_c1": c1, f"{tag}_c2": c2, f"{tag}_c3": c3})
        row["flag_share_t"] = float(flag[in_window(entry, TEST)].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def perm_pvalue(ret, size, n_draws=N_PERM, seed=7):
    """P(random flags of the same count and weight give a P&L/max-DD at least as good).  One-sided."""
    rng = np.random.default_rng(seed)
    n = len(ret)
    obs = book(ret, size, 1.0)["ratio"]
    flagged = size < 1
    k = int(flagged.sum())
    if k == 0:
        return 1.0
    w = size[flagged][0]
    idx = np.argsort(rng.random((n_draws, n)), axis=1)[:, :k]
    sizes = np.ones((n_draws, n))
    np.put_along_axis(sizes, idx, w, axis=1)
    r = sizes * ret
    cum = np.concatenate([np.zeros((n_draws, 1)), np.cumsum(r, axis=1)], axis=1)
    dd = (cum - np.maximum.accumulate(cum, axis=1)).min(axis=1)
    pnl = r.sum(axis=1)
    ratio = np.where(dd < 0, pnl / np.abs(np.where(dd < 0, dd, 1)), np.inf)
    return float((1 + (ratio >= obs - 1e-12).sum()) / (1 + n_draws))


# ───────────────────────── risk-scaled sizing ─────────────────────────

def scaled_size(x, mask):
    """size proportional to 1/x, normalised to mean 1 on the window (equal average margin)."""
    s = np.full(len(x), np.nan)
    inv = 1.0 / x[mask]
    s[mask] = inv / np.nanmean(inv)
    return s


def sizing_rows(X, trades, name, windows):
    ret, entry = trades["ret"].values, trades["entry"]
    out = []
    for label, col in (("1/VIX", "vix"), ("1/rv20", "rv20")):
        x = X[col].values.astype(float)
        for tag, w in windows:
            m = in_window(entry, w) & ~np.isnan(x)
            if m.sum() < 10:
                continue
            yrs = window_years(*w)
            size = scaled_size(x, m)[m]
            b0, b1 = book(ret[m], np.ones(m.sum()), yrs), book(ret[m], size, yrs)
            c1, c2, c3, nums = verdict_conditions(b0, b1)
            out.append({"book": name, "sizing": label, "window": tag, "n": int(m.sum()),
                        "base_ann": 100 * b0["ann"], "ann": 100 * b1["ann"], "ann_inr": b1["ann_inr"],
                        "base_dd": 100 * b0["dd"], "dd": 100 * b1["dd"], "worst": 100 * b1["worst"],
                        "base_worst": 100 * b0["worst"], "base_ratio": b0["ratio"], "ratio": b1["ratio"],
                        "max_size": float(size.max()), "dd_change": 100 * nums["dd_change_em"],
                        "pnl_kept": 100 * nums["pnl_kept_em"], "c1": c1, "c2": c2, "c3": c3})
    return pd.DataFrame(out)


# ───────────────────────── combined walk-forward model ─────────────────────────

def model_columns(X, min_cover=0.9):
    cols = list(HI) + [c for c in BOTH if c != "ret5" and c != "ret20"] + ["ret5", "ret20"] + list(BINARY)
    cols = [c for c in dict.fromkeys(cols) if c in X and X[c].notna().mean() >= min_cover]
    return cols


def walk_forward(X, trades, cols, first_year=2021, C=0.3):
    """Refit yearly on trades whose expiry is before 1 Jan of year Y (expanding window), predict year Y.

    'Bad' = bottom 5 % of the training returns; the flag is the top decile of the model's fitted
    probability on its own training set.  Returns (size per trade, dict year -> fitted model bundle)."""
    from sklearn.linear_model import LogisticRegression
    size = np.ones(len(trades))
    bundles = {}
    ret, entry, expiry = trades["ret"].values, trades["entry"].values, trades["expiry"].values
    years = sorted({e[:4] for e in entry if e[:4] >= str(first_year)})
    for y in years:
        tr = expiry < f"{y}-01-01"
        if tr.sum() < 60:
            continue
        bad = ret[tr] <= np.quantile(ret[tr], BAD_Q)
        if bad.sum() < 3:
            continue
        bundles[y] = fit_bundle(X.loc[tr, cols], bad, cols, C)
        te = np.array([e[:4] == y for e in entry])
        p = predict_bundle(bundles[y], X.loc[te, cols])
        size[te] = np.where(p >= bundles[y]["cut"], HALF, 1.0)
    return size, bundles


def fit_bundle(Xtr, bad, cols, C):
    from sklearn.linear_model import LogisticRegression
    med = Xtr.median()
    A = Xtr.fillna(med)
    mu, sd = A.mean(), A.std().replace(0, 1)
    clf = LogisticRegression(C=C, max_iter=2000).fit(((A - mu) / sd).values, bad)
    ptr = clf.predict_proba(((A - mu) / sd).values)[:, 1]
    return {"clf": clf, "med": med, "mu": mu, "sd": sd, "cut": float(np.quantile(ptr, TOP_DECILE)), "cols": cols}


def predict_bundle(b, Xte):
    A = Xte[b["cols"]].fillna(b["med"])
    return b["clf"].predict_proba(((A - b["mu"]) / b["sd"]).values)[:, 1]


def model_rows(size, trades, worst_idx, name, windows):
    ret, entry = trades["ret"].values, trades["entry"]
    out = []
    for tag, w in windows:
        m = in_window(entry, w)
        yrs = window_years(*w)
        b0, b1 = book(ret[m], np.ones(m.sum()), yrs), book(ret[m], size[m], yrs)
        c1, c2, c3, nums = verdict_conditions(b0, b1)
        out.append({"book": name, "window": tag, "n": int(m.sum()), "halved": int((size[m] < 1).sum()),
                    "base_ann": 100 * b0["ann"], "ann": 100 * b1["ann"], "ann_inr": b1["ann_inr"],
                    "base_dd": 100 * b0["dd"], "dd": 100 * b1["dd"], "base_worst": 100 * b0["worst"],
                    "worst": 100 * b1["worst"], "base_ratio": b0["ratio"], "ratio": b1["ratio"],
                    "dd_change": 100 * nums["dd_change_em"], "pnl_kept": 100 * nums["pnl_kept_em"],
                    "c1": c1, "c2": c2, "c3": c3, "worst4": worst_labels(size, worst_idx) if name == "NIFTY" else ""})
    return pd.DataFrame(out)


# ───────────────────────── data loading ─────────────────────────

def load_raw():
    from db import read_sql
    nse = read_sql("SELECT trade_date AS date, close FROM nse_index_history WHERE index_symbol = 'NIFTY 50' ORDER BY 1")
    mac = read_sql("SELECT date, value AS close FROM macro_history WHERE indicator_id = 'nifty50' ORDER BY 1")
    mac = mac[mac.date < nse.date.min()]            # splice the pre-2019 history from macro_history (yfinance)
    close = pd.concat([mac, nse]).drop_duplicates("date").set_index("date")["close"]
    v = read_sql("SELECT date, vix FROM vix_history ORDER BY date").set_index("date")["vix"]
    iv = read_sql("SELECT trade_date AS date, atm_iv, iv_skew_25d, iv_term_structure FROM fno_iv_history "
                  "WHERE symbol = 'NIFTY' ORDER BY 1").set_index("date")
    pcr = read_sql("SELECT trade_date AS date, pcr_oi, pcr_volume, max_pain_distance FROM fno_pcr_history "
                   "WHERE symbol = 'NIFTY' ORDER BY 1").set_index("date")
    fii = read_sql("SELECT * FROM fii_dii_positioning WHERE client_type = 'FII' ORDER BY trade_date")
    fii = fii.set_index("trade_date")
    macro = {}
    for k in ("us_10y", "usdinr", "brent_crude"):
        m = read_sql("SELECT date, value FROM macro_history WHERE indicator_id = ? ORDER BY date", (k,))
        macro[k] = m.set_index("date")["value"]
    return {"close": close, "vix": v, "iv": iv, "pcr": pcr, "fii": fii, "macro": macro}


def load_trades(underlying, start, limit=None):
    """exp2 / delta 0.05 / strangle trades, via the backtest's own functions (one implementation)."""
    import option_book as ob
    import tools.option_premium_backtest as opb
    opb.UNDERLYING = underlying
    chain, vix = opb.load_chain(), opb.load_vix()
    cb = opb.Chain(chain)
    days, sched = opb.schedule(chain, "exp2")
    sched = [s for s in sched if s[0] >= start]
    if limit:
        sched = sched[:limit]
    rows = [opb.one_trade(cb, days, t, x, e, 0.05, "strangle", ob.SLIP, vix) for t, x, e in sched]
    df = pd.DataFrame([r for r in rows if r is not None])
    df["hold"], df["structure"], df["delta"] = "exp2", "strangle", 0.05
    return df.reset_index(drop=True)


# ───────────────────────── reporting ─────────────────────────

def fmt_table(df, floatfmt=2):
    return df.round(floatfmt).to_string(index=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--csv", help="write the per-rule table to this CSV")
    ap.add_argument("--md", help="write the per-rule markdown appendix to this file")
    ap.add_argument("--smoke", action="store_true", help="40 trades only; prints the join and exits")
    ap.add_argument("--nifty-csv", help="reuse a trades CSV from tools.option_premium_backtest (exp2/0.05/strangle rows)")
    a = ap.parse_args()
    pd.set_option("display.width", 250, "display.max_columns", 60, "display.max_rows", 500)

    raw = load_raw()
    mkt = build_market(raw)
    if a.nifty_csv:
        t = pd.read_csv(a.nifty_csv)
        t = t[(t.hold == "exp2") & (t.delta == 0.05) & (t.structure == "strangle")].reset_index(drop=True)
    else:
        t = load_trades("NIFTY", "2019-02-01", limit=40 if a.smoke else None)
    t["vix"] = mkt["vix"].reindex(t["entry"]).values          # vix_history has gaps on a few entry days: ffill'd
    X = trade_features(t, mkt)
    if a.smoke:
        print(pd.concat([t[["entry", "expiry", "ret"]], X[["vix", "rv20", "pcr_oi", "atm_iv", "ev_any", "holiday"]]], axis=1).head(10))
        return

    print(f"NIFTY trades {len(t)}  {t.entry.min()} → {t.entry.max()}  base ann {100*book(t.ret.values, np.ones(len(t)), window_years(t.entry.min(), '2026-10-21'))['ann']:.1f}% of margin")
    worst_idx = sorted(t["ret"].nsmallest(4).index, key=lambda i: t.entry[i])
    print("\n4 worst trades (full sample):")
    show = ["vix", "vix_chg5", "vix_pct252", "rv5", "rv20", "iv_rv", "ret1", "ret5", "ret20", "abs_dist20", "dd52", "atm_iv",
            "iv_skew", "pcr_oi", "pcr_vol", "fii_fut", "us10y_chg5", "usdinr_chg5", "brent_chg5", "ev_any", "ev_rbi",
            "ev_fomc", "holiday", "credit_m", "z_strike", "regime"]
    w = pd.concat([t.loc[worst_idx, ["entry", "expiry", "ret"]], X.loc[worst_idx, show]], axis=1).T
    print(w.round(3).to_string())
    print("\nsame predictors: percentile of each worst trade among all 399 entries (100 = highest):")
    pct = {c: [100 * (X[c].dropna() <= X.loc[i, c]).mean() if pd.notna(X.loc[i, c]) else np.nan for i in worst_idx]
           for c in show}
    print(pd.DataFrame(pct, index=[t.entry[i] for i in worst_idx]).T.round(0).to_string())

    rules = build_rules(X, t)
    ev = evaluate(rules, X, t, worst_idx)
    m_t = in_window(t.entry, TEST)
    ev["p_perm"] = [perm_pvalue(t.ret.values[m_t], make_sizes(flags_for(r, X), r["action"])[m_t]) if True else np.nan
                    for r in rules]
    n_tests = len(ev)
    ev["p_bonf"] = np.minimum(1, ev["p_perm"] * n_tests)
    ev["p_by"] = _by_adjust(ev["p_perm"].values)
    ev["pass_test"] = ev.t_c1 & ev.t_c2 & ev.t_c3
    # descriptive, full sample: did the rule flag the 4 worst trades, and how likely is that by luck?
    flags = [flags_for(r, X) > 0 for r in rules]
    ev["hits4"] = [int(f[worst_idx].sum()) for f in flags]
    ev["share_flagged"] = [100 * float(f.mean()) for f in flags]
    ev["p_all4"] = [_p_all4(len(t), int(f.sum()), int(f[worst_idx].sum())) for f in flags]

    # SENSEX + stress for every rule (frozen thresholds from the NIFTY choose window)
    sx = load_trades("SENSEX", "2024-01-01")
    sx["vix"] = mkt["vix"].reindex(sx["entry"]).values
    Xs = trade_features(sx, mkt)
    ev = ev.merge(_sensex_cols(rules, Xs, sx), left_index=True, right_index=True)
    ev = ev.merge(_stress_cols(rules, mkt, t), left_index=True, right_index=True)
    ev["pass_all"] = ev.pass_test & ev.sx_c1 & ev.sx_c2 & ev.sx_c3 & (ev.p_bonf < 0.05)
    base = {tag: book(t.ret.values[in_window(t.entry, w)], np.ones(in_window(t.entry, w).sum()), window_years(*w))
            for tag, w in (("choose", CHOOSE), ("test", TEST))}
    print("\nBASE BOOK (NIFTY)", {k: {kk: round(vv, 3) for kk, vv in v.items()} for k, v in base.items()})
    sxb = book(sx.ret.values, np.ones(len(sx)), window_years(sx.entry.min(), "2026-10-21"))
    print("BASE BOOK (SENSEX)", {k: round(v, 3) for k, v in sxb.items()}, "n", len(sx))
    print(f"\nTESTS TRIED: {n_tests} (predictor tails x skip/half); Bonferroni-implied two-sided |t| bar at 5%: "
          f"{_t_bar(n_tests):.2f}")

    cols = ["name", "action", "pct", "thr", "c_n", "c_ann", "c_dd", "c_ratio", "c_base_ratio", "t_n", "t_ann", "t_inr", "t_worst", "t_dd",
            "t_ratio", "t_base_ratio", "t_given_up", "t_dd_change", "t_pnl_kept_em", "worst4", "p_perm", "p_bonf", "pass_test"]
    print("\nPER-RULE (choose = 2019-22, test = 2023-26); sorted by test P&L/DD")
    print(fmt_table(ev.sort_values("t_ratio", ascending=False)[cols]))
    print("\nTOP 5 BY TEST P&L/DD with SENSEX and stress")
    c2 = ["name", "action", "t_ratio", "t_ann", "t_given_up", "t_dd_change", "t_pnl_kept_em", "p_bonf", "sx_ratio", "sx_base_ratio",
          "sx_dd_change", "sx_pnl_kept_em", "st_base_dd", "st_dd", "st_base_ann", "st_ann", "pass_all"]
    print(fmt_table(ev.sort_values("t_ratio", ascending=False)[c2].head(5)))
    print("\nRULES PASSING THE TEST-WINDOW CONDITIONS:", int(ev.pass_test.sum()), " passing everything incl. haircut:", int(ev.pass_all.sum()))
    print(fmt_table(ev[ev.pass_test][c2]) if ev.pass_test.any() else "none")
    near = ev[(ev.t_c1.astype(int) + ev.t_c2.astype(int) + ev.t_c3.astype(int)) == 2].sort_values("t_ratio", ascending=False)
    print("\nNEAR MISSES (2 of 3 conditions on test):")
    print(fmt_table(near[c2 + ["t_c1", "t_c2", "t_c3"]].head(8)) if len(near) else "none")

    print("\nBY-adjusted p, smallest 5:", np.sort(ev["p_by"].values)[:5].round(3), " smallest Bonferroni p:", ev["p_bonf"].min().round(3))
    print("\nSTRESS MODEL 2015-06 → 2019-02, rules that need only NIFTY + VIX (frozen thresholds)")
    s = ev[ev.get("st_ok", False) == True].copy()
    s["st_dd_change"] = 100 * (s.st_dd / s.st_base_dd - 1)
    print(fmt_table(s.sort_values("st_dd_change")[["name", "action", "pct", "thr", "st_base_ann", "st_ann", "st_base_dd", "st_dd", "st_dd_change"]]))
    print("\nDESCRIPTIVE: rules that flagged the most of the 4 worst trades (full sample; p_all4 = chance a random set of that size does as well)")
    print(fmt_table(ev.sort_values(["hits4", "p_all4"], ascending=[False, True])[
        ["name", "action", "pct", "thr", "share_flagged", "hits4", "worst4", "p_all4", "t_given_up", "t_ratio", "p_perm", "p_bonf", "p_by"]].head(14), 4))

    wins = (("choose", CHOOSE), ("test", TEST), ("all", ("2019-02-01", "2026-12-31")))
    sz = pd.concat([sizing_rows(X, t, "NIFTY", wins), sizing_rows(Xs, sx, "SENSEX", (("all", ("2024-01-01", "2026-12-31")),))])
    print("\nRISK-SCALED SIZING")
    print(fmt_table(sz))
    st = stress_sizing(mkt, t)
    print("\nRISK-SCALED SIZING on the 2015-06 → 2019-02 stress model (Tuesday entries)")
    print(fmt_table(st))

    mcols = model_columns(X)
    msize, bundles = walk_forward(X, t, mcols)
    print("\nCOMBINED MODEL columns:", mcols)
    mw = (("2021-26 (all predicted)", ("2021-01-01", "2026-12-31")), ("test 2023-26", TEST))
    mr = model_rows(msize, t, worst_idx, "NIFTY", mw)
    print(fmt_table(mr))
    msx = np.ones(len(sx))
    for y, b in bundles.items():
        mm = np.array([e[:4] == y for e in sx.entry])
        if mm.any():
            msx[mm] = np.where(predict_bundle(b, Xs[mm]) >= b["cut"], HALF, 1.0)
    print(fmt_table(model_rows(msx, sx, [], "SENSEX", (("2024-26", ("2024-01-01", "2026-12-31")),))))
    last = max(bundles)
    coefs = pd.Series(bundles[last]["clf"].coef_[0], index=mcols).sort_values()
    print(f"\nmodel coefficients (standardised, fit through {int(last)-1}):")
    print(coefs.round(2).to_string())
    pm = perm_pvalue(t.ret.values[m_t], msize[m_t])
    print(f"model p (perm, test window) {pm:.4f}; Bonferroni x{n_tests+1}: {min(1, pm*(n_tests+1)):.3f}")
    if a.csv:
        ev.to_csv(a.csv, index=False)
    if a.md:
        with open(a.md, "w") as fh:
            fh.write(md_rules(ev) + "\n")


def _by_adjust(p):
    """Benjamini-Yekutieli adjusted p (the headline correction of tools/multiple_testing.py)."""
    from tools.multiple_testing import _bh_adjusted
    m = len(p)
    return _bh_adjusted(np.asarray(p, dtype=float), float(np.sum(1.0 / np.arange(1, m + 1))))


def _p_all4(n, k, hits):
    """P(a random flagged set of size k out of n holds at least `hits` of the 4 worst trades)."""
    from scipy.stats import hypergeom
    return float(hypergeom.sf(hits - 1, n, 4, k)) if hits > 0 else 1.0


def md_rules(ev):
    """Markdown appendix: one row per rule, both windows."""
    lines = ["| predictor | action | pct | threshold | share flagged | 4 worst (04-20, 05-20, 07-22, 05-26) | "
             "choose: kept / ann % / ann ₹ / worst % / maxDD % / P&L÷DD (base) / given up % | "
             "test: kept / ann % / ann ₹ / worst % / maxDD % / P&L÷DD (base) / given up % | test DD chg (eq. margin) / P&L kept | p perm / Bonf | pass |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in ev.sort_values(["name", "action"]).iterrows():
        def w(p):
            return (f"{r[p+'_n']:.0f} / {r[p+'_ann']:.1f} / {r[p+'_inr']:,.0f} / {r[p+'_worst']:.1f} / {r[p+'_dd']:.1f} / "
                    f"{r[p+'_ratio']:.1f} ({r[p+'_base_ratio']:.1f}) / {r[p+'_given_up']:.0f}")
        pct = "binary" if pd.isna(r["pct"]) else f"{r['pct']:.0f}"
        lines.append(f"| {r['name']} | {r['action']} | {pct} | {r['thr']:.3g} | {r['share_flagged']:.0f}% | `{r['worst4']}` | "
                     f"{w('c')} | {w('t')} | {r['t_dd_change']:+.0f}% / {r['t_pnl_kept_em']:.0f}% | "
                     f"{r['p_perm']:.3f} / {r['p_bonf']:.2f} | {'TEST-PASS' if r['pass_test'] else ''} |")
    return "\n".join(lines)


def _t_bar(n):
    from scipy import stats
    return float(stats.norm.isf(0.05 / n / 2))


def _sensex_cols(rules, Xs, sx):
    ret = sx.ret.values
    yrs = window_years(sx.entry.min(), "2026-10-21")
    b0 = book(ret, np.ones(len(ret)), yrs)
    out = []
    for r in rules:
        size = make_sizes(flags_for(r, Xs), r["action"])
        b1 = book(ret, size, yrs)
        c1, c2, c3, nums = verdict_conditions(b0, b1)
        out.append({"sx_ratio": b1["ratio"], "sx_base_ratio": b0["ratio"], "sx_dd_change": 100 * nums["dd_change_em"],
                    "sx_pnl_kept_em": 100 * nums["pnl_kept_em"], "sx_c1": c1, "sx_c2": c2, "sx_c3": c3})
    return pd.DataFrame(out)


def stress_book(mkt, t):
    """2015-06 → entry of the chain: the backtest's NIFTY+VIX model, Tuesday entries (the old weekly day)."""
    import tools.option_premium_backtest as opb
    cal = opb.calibrate(t)
    idx = opb.load_index()
    st = opb.stress(idx, cal.loc[[("exp2", "strangle", 0.05)]], idx.date.min(), t.entry.min())
    st = st[st["entry"].map(lambda d: date.fromisoformat(d).weekday() == 1)].reset_index(drop=True)
    st["expiry"] = st["exit"]
    Xs = mkt.reindex(st["entry"].values).reset_index(drop=True)
    for c in HI + BOTH + BINARY:
        if c not in Xs:
            Xs[c] = np.nan
    return st, Xs


def _stress_cols(rules, mkt, t):
    st, Xs = stress_book(mkt, t)
    ret = st.ret.values
    yrs = window_years(st.entry.min(), st.entry.max())
    b0 = book(ret, np.ones(len(ret)), yrs)
    out = []
    for r in rules:
        if r["pred"] not in STRESS_OK:
            out.append({"st_base_dd": np.nan, "st_dd": np.nan, "st_base_ann": np.nan, "st_ann": np.nan, "st_ok": False})
            continue
        size = make_sizes(flags_for(r, Xs), r["action"])
        b1 = book(ret, size, yrs)
        out.append({"st_base_dd": 100 * b0["dd"], "st_dd": 100 * b1["dd"], "st_base_ann": 100 * b0["ann"],
                    "st_ann": 100 * b1["ann"], "st_ok": True})
    return pd.DataFrame(out)


def stress_sizing(mkt, t):
    st, Xs = stress_book(mkt, t)
    rows = sizing_rows(Xs, st, "stress", (("2015-19", ("2015-06-01", "2019-02-12")),))
    return rows


if __name__ == "__main__":
    main()
