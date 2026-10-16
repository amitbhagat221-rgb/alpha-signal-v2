"""
Slow factors from the Kite minute archive, tested at a 90-day horizon — 2026-10 study
(Amit 2026-10-16: "do feature engineering to create a slow factor (for example 1 min candles to
10 min candles etc) and test that slow factor for a horizon of 90 days").

Two stages:
  1. build-daily   minute bars (ADR 0072 Parquet, close+volume) → one row per stock-session with
                   10-minute-candle statistics, written to INTRADAY_DIR/daily_1m/sid=<SID>.parquet
                   and recorded in `intraday_files` (dataset daily_1m, kind daily). This is the
                   `intraday_daily` summary ADR 0072 says the factors read; nothing reads Kite.
  2. study         factors at the backtest's monthly anchors (daily_snapshots_pit, point-in-time
                   cap tier) against a 90-CALENDAR-day forward return built here from adjusted
                   closes (entry = first close after the anchor, exit = last close within 90 days),
                   Newey-West lag 2 for the 3-month overlap; the panel's fwd_return_20d beside it.

Per session (09:15–15:29 IST, 1-minute closes in paise) — the `intraday_daily` columns of research 0009,
sums not ratios so any window is an exact roll-up:
  n_bars, vol, value (Σ close·volume ₹), px_first, px_last, high, low; vwap_close_num / _den (15:00–15:29);
  r_first30 (09:15→09:44), r_mid (09:44→15:00), r_last30 (15:00→15:29) as ln ratios of 1-minute closes;
  realized moments on 5- and 10-minute candle log returns (candle = last close in the bucket):
  rv Σr², rs_up Σr²[r>0], rs_down Σr²[r<0], r3 Σr³, r4 Σr⁴, bpv Σ|r_t||r_t−1|, abs_r Σ|r|, n candles;
  vol_first30, vol_last30; signed_vol = tick-rule signed 1-minute volume (zero ticks carry the previous
  sign); bvc_buy_vol = bulk-volume buy share Σ V·Φ(Δp/σ_day); flat_at_high_min / flat_at_low_min =
  minutes the close sat at the day's high / low (circuit proxy).
  The study below uses the 10-minute moments (Amit's example); the 5-minute ones are research 0009's
  choice for thin names and sit in the same file for the fast candidates.

Pre-registered before the run (formula, sign, horizon = 90 days):
  rvol_60d            √Σ rv, 60 sessions                                   sign −  (low-vol)
  rskew_60d           realized skewness of 10-min returns, 60 sessions       sign −  (Amaya et al.)
  jump_share_60d      Σ(rv − π/2·bpv)⁺ / Σ rv, 60 sessions                  sign −
  ofi_60d             Σ signed_vol / Σ vol, 60 sessions                      sign +  (buying pressure)
  late_vol_share_60d  Σ vol_last30 / Σ vol, 60 sessions                      two-sided (research 0009 S4: '?')
  vwap_dev_60d        ln(last close / 60-session VWAP)                       two-sided
  smart_money_12_1    Σ (ret_last30 − ret_first30), sessions t−252 … t−22    sign +  (Lou–Polk–Skouras)
  vol_of_vol_60d      std / mean of daily √rv, 60 sessions                   sign −
  amihud_10m_60d      mean of √rv / value(₹ Cr), 60 sessions                 sign +  (illiquidity)
Minimum 40 of 60 sessions (150 of 231 for 12-1). Verdict bar |t| ≥ 2.5, halves agree, max |ρ| with
a wired factor < 0.5 (Bonferroni 4.2 still applies: 9 more hypotheses). The archive is
survivors-only (Kite lists no delisted stock): every IC here carries that caveat.

READ-ONLY on the DB except the `intraday_files` manifest rows for the daily files.

Usage:
    python -m tools.intraday_slow_study build-daily [--workers 3] [--sids RELI,COFO]
    python -m tools.intraday_slow_study study [--md docs/studies/intraday-slow-factors-2026-10.md]
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pit                                                   # noqa: E402
from config import INTRADAY_DIR                              # noqa: E402
from db import get_db, read_sql                              # noqa: E402
from signals._prices import apply_adjustments                # noqa: E402
from tools import backtest_pit as bp                         # noqa: E402
from tools.ownership_flow_study import max_corr_wired, wired_cols   # noqa: E402

DATASET = "daily_1m"
SRC = INTRADAY_DIR / "bars_1m" / "_staging"
OUT = INTRADAY_DIR / DATASET
IST = "Asia/Kolkata"
OPEN, CLOSE = 9 * 60 + 15, 15 * 60 + 30            # minutes of the day, [OPEN, CLOSE)
TIERS3 = ["LARGE", "MID", "SMALL"]
SIGNS = {"rvol_60d": -1, "rskew_60d": -1, "jump_share_60d": -1, "ofi_60d": 1, "late_vol_share_60d": 0,
         "vwap_dev_60d": 0, "smart_money_12_1": 1, "vol_of_vol_60d": -1, "amihud_10m_60d": 1}
CANDIDATES = list(SIGNS)
WIN, MIN_WIN = 60, 40
BAR, BONFERRONI = 2.5, 4.2
HORIZON_DAYS = 90
TRADEABLE_CR = 1.0                 # the SMALL slice that can take real money
NW_LAG_90 = 2
MOMENTS = ("rv", "rs_up", "rs_down", "r3", "r4", "bpv", "abs_r", "n")
DAILY_SCHEMA = pa.schema(
    [("sid", pa.string()), ("day", pa.date32()), ("n_bars", pa.int16()),
     ("px_first", pa.float64()), ("px_last", pa.float64()), ("high", pa.float64()), ("low", pa.float64()),
     ("vol", pa.int64()), ("value", pa.float64()),
     ("vwap_close_num", pa.float64()), ("vwap_close_den", pa.int64()),
     ("r_first30", pa.float64()), ("r_mid", pa.float64()), ("r_last30", pa.float64()),
     ("vol_first30", pa.int64()), ("vol_last30", pa.int64())]
    + [(f"{m}_{w}", pa.int16() if m == "n" else pa.float64()) for w in ("5m", "10m") for m in MOMENTS]
    + [("signed_vol", pa.float64()), ("bvc_buy_vol", pa.float64()),
       ("flat_at_high_min", pa.int16()), ("flat_at_low_min", pa.int16())])


# ── stage 1: minute bars → one row per session ─────────────────────────────────────────────
def _moments(df, width):
    """Realized moments per session from candles `width` minutes wide (last close in each bucket)."""
    c = df.groupby(["day", (df["mod"] - OPEN) // width], sort=True)["px"].last()
    r = np.log(c).groupby(level=0).diff().dropna()
    L = pd.DataFrame({"r2": r ** 2, "r3": r ** 3, "r4": r ** 4, "a": r.abs(),
                      "up": (r ** 2).where(r > 0, 0.0), "dn": (r ** 2).where(r < 0, 0.0)})
    L["bp"] = L["a"] * L.groupby(level=0)["a"].shift(1)
    agg = L.groupby(level=0).agg(rv=("r2", "sum"), rs_up=("up", "sum"), rs_down=("dn", "sum"), r3=("r3", "sum"),
                                 r4=("r4", "sum"), bpv=("bp", "sum"), abs_r=("a", "sum"), n=("r2", "size"))
    return agg.add_suffix(f"_{width}m")


def daily_summary(bars):
    """Minute bars of one stock (sid, ts UTC, close paise, volume) → one row per session."""
    local = bars["ts"].dt.tz_convert(IST)
    mod = (local.dt.hour * 60 + local.dt.minute).to_numpy()
    sess = (mod >= OPEN) & (mod < CLOSE)
    df = pd.DataFrame({"day": local.dt.normalize().dt.tz_localize(None).to_numpy()[sess],
                       "mod": mod[sess],
                       "px": bars["close"].to_numpy()[sess] / 100.0,
                       "vol": bars["volume"].to_numpy()[sess].astype("float64")})
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("day", sort=True)
    out = pd.DataFrame({"n_bars": g.size(), "px_first": g["px"].first(), "px_last": g["px"].last(),
                        "high": g["px"].max(), "low": g["px"].min(), "vol": g["vol"].sum(),
                        "value": (df["px"] * df["vol"]).groupby(df["day"]).sum()})
    early, mid, late = df[df["mod"] < OPEN + 30], df[(df["mod"] >= OPEN + 29) & (df["mod"] <= CLOSE - 30)], \
        df[df["mod"] >= CLOSE - 30]
    for name, part in (("first30", early), ("mid", mid), ("last30", late)):
        gp = part.groupby("day")
        out[f"r_{name}"] = np.log(gp["px"].last() / gp["px"].first())
        if name != "mid":
            out[f"vol_{name}"] = gp["vol"].sum()
    gl = late.groupby("day")
    out["vwap_close_num"] = (late["px"] * late["vol"]).groupby(late["day"]).sum()
    out["vwap_close_den"] = gl["vol"].sum()
    out = out.join(_moments(df, 5)).join(_moments(df, 10))
    # tick rule on 1-minute closes, zero ticks carry the previous sign, first bar of the day unsigned
    dpx = g["px"].diff()
    tick = np.sign(dpx).replace(0, np.nan).groupby(df["day"]).ffill().fillna(0)
    out["signed_vol"] = (tick * df["vol"]).groupby(df["day"]).sum()
    # bulk volume classification (Easley, López de Prado, O'Hara): buy share Φ(Δp / σ_day) per minute
    from scipy.stats import norm
    sigma = dpx.groupby(df["day"]).transform("std")
    z = (dpx / sigma.where(sigma > 0)).fillna(0)
    out["bvc_buy_vol"] = (norm.cdf(z) * df["vol"]).groupby(df["day"]).sum()
    out["flat_at_high_min"] = (df["px"] == g["px"].transform("max")).groupby(df["day"]).sum()
    out["flat_at_low_min"] = (df["px"] == g["px"].transform("min")).groupby(df["day"]).sum()
    fill = {c: 0 for c in out.columns if c.startswith(("vol_", "vwap_close")) or c.split("_", 1)[0] in MOMENTS}
    out = out.fillna(fill)
    out.index.name = "day"
    return out.reset_index()


def _build_one(sid):
    src = SRC / f"sid={sid}.parquet"
    bars = pq.read_table(src).to_pandas()
    d = daily_summary(bars)
    if d.empty:
        return sid, None, 0, None, None, 0
    d.insert(0, "sid", sid)
    d["day"] = pd.to_datetime(d["day"]).dt.date
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"sid={sid}.parquet"
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(pa.Table.from_pandas(d, schema=DAILY_SCHEMA, preserve_index=False), tmp, compression="zstd")
    os.replace(tmp, path)
    return sid, path, len(d), d["day"].min(), d["day"].max(), path.stat().st_size


def _record(sid, path, n, first, last, nbytes, src_fetched_on):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO intraday_files (dataset, kind, key, path, n_rows, n_days, first_ts, last_ts, bytes,
                                           fetched_on, note, written_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?, datetime('now'))
               ON CONFLICT(dataset, kind, key) DO UPDATE SET
                   path=excluded.path, n_rows=excluded.n_rows, n_days=excluded.n_days,
                   first_ts=excluded.first_ts, last_ts=excluded.last_ts, bytes=excluded.bytes,
                   fetched_on=excluded.fetched_on, note=excluded.note, written_at=excluded.written_at""",
            (DATASET, "daily", sid, str(path) if path else None, n, n,
             first.isoformat() if first else None, last.isoformat() if last else None, nbytes,
             date.today().isoformat(), f"10-minute candle summary of bars_1m fetched {src_fetched_on}"))


def build_daily(workers=3, sids=None):
    files = read_sql("SELECT key AS sid, fetched_on FROM intraday_files WHERE dataset = 'bars_1m' "
                     "AND kind = 'staging' AND path IS NOT NULL ORDER BY key")
    if sids:
        files = files[files["sid"].isin(sids)]
    fetched = dict(zip(files["sid"], files["fetched_on"]))
    todo = list(files["sid"])
    print(f"{DATASET}: {len(todo)} stocks, {workers} workers", flush=True)
    done = 0
    with mp.get_context("fork").Pool(workers) as pool:
        for sid, path, n, first, last, nbytes in pool.imap_unordered(_build_one, todo, chunksize=4):
            _record(sid, path, n, first, last, nbytes, fetched[sid])
            done += 1
            if done % 100 == 0 or done == len(todo):
                print(f"  [{done}/{len(todo)}] {sid}: {n:,} sessions", flush=True)


def load_daily():
    paths = read_sql("SELECT path FROM intraday_files WHERE dataset = ? AND kind = 'daily' AND path IS NOT NULL",
                     params=[DATASET])["path"]
    frames = [pq.read_table(p).to_pandas() for p in paths]
    d = pd.concat(frames, ignore_index=True)
    d["sid"] = d["sid"].astype(str)
    d["day"] = pd.to_datetime(d["day"])
    return d


# ── stage 2: factors at anchors ────────────────────────────────────────────────────────────
def _wide(d):
    cols = {"last": "px_last", "vol": "vol", "value": "value", "vol_last30": "vol_last30", "ret_first30": "r_first30",
            "ret_last30": "r_last30", "rv": "rv_10m", "r3": "r3_10m", "bpv": "bpv_10m", "n10": "n_10m",
            "signed_vol": "signed_vol"}
    W = {k: d.pivot(index="day", columns="sid", values=c) for k, c in cols.items()}
    W["sess"] = W["last"].notna().astype(float)
    return W


def _roll(X, win, min_periods):
    return X.rolling(win, min_periods=min_periods).sum()


def factors_at(W, i):
    """All candidates from sessions up to and including row i (the anchor's last close)."""
    lo = max(0, i - WIN + 1)
    sl = slice(lo, i + 1)
    n = W["sess"].iloc[sl].sum()
    ok = n >= MIN_WIN
    rv, r3, bpv = (W[k].iloc[sl] for k in ("rv", "r3", "bpv"))
    n10 = W["n10"].iloc[sl].sum()
    vol, value = W["vol"].iloc[sl].sum(), W["value"].iloc[sl].sum()
    out = {}
    srv = rv.sum()
    out["rvol_60d"] = np.sqrt(srv)
    m2, m3 = srv / n10, r3.sum() / n10
    out["rskew_60d"] = np.sqrt(n10) * m3 / np.power(m2, 1.5)          # realized skewness (Amaya et al.)
    out["jump_share_60d"] = (rv - (np.pi / 2) * bpv).clip(lower=0).sum() / srv
    out["ofi_60d"] = W["signed_vol"].iloc[sl].sum() / vol
    out["late_vol_share_60d"] = W["vol_last30"].iloc[sl].sum() / vol
    out["vwap_dev_60d"] = np.log(W["last"].iloc[i] / (value / vol))
    drv = np.sqrt(rv.where(W["sess"].iloc[sl] > 0))
    out["vol_of_vol_60d"] = drv.std() / drv.mean()
    out["amihud_10m_60d"] = (drv / (W["value"].iloc[sl] / 1e7)).replace([np.inf, -np.inf], np.nan).mean()
    out["ln_adtv_60d"] = np.log((value / n) / 1e7)                 # control: ln ₹ Cr traded per session
    F = pd.DataFrame(out)
    F = F.where(ok, np.nan)
    lo12, hi12 = max(0, i - 252 + 1), i - 21                        # sessions t−252 … t−22
    if hi12 > lo12:
        sm = (W["ret_last30"].iloc[lo12:hi12] - W["ret_first30"].iloc[lo12:hi12])
        F["smart_money_12_1"] = sm.sum(min_count=150)
    else:
        F["smart_money_12_1"] = np.nan
    F = F.replace([np.inf, -np.inf], np.nan)
    return F


def _adj_closes():
    raw = pit.load_raw({"adjustments"})
    px = read_sql("SELECT sid, date, close, volume FROM stock_prices WHERE close > 0 ORDER BY sid, date")
    px = apply_adjustments(px, raw["adjustments"], date.max)
    px["date"] = pd.to_datetime(px["date"])
    return px.pivot(index="date", columns="sid", values="adj_close")


def label_90d(adj, anchor):
    """Return from the first close after `anchor` to the last close within HORIZON_DAYS calendar days."""
    dates = adj.index
    i = dates.searchsorted(anchor, side="right")          # first session after the anchor
    j = dates.searchsorted(anchor + pd.Timedelta(days=HORIZON_DAYS), side="right") - 1
    if i >= len(dates) or j <= i or dates[j] < anchor + pd.Timedelta(days=HORIZON_DAYS - 7):
        return None                                        # window not complete yet
    entry = adj.iloc[i]
    fut = adj.iloc[i: j + 1]
    exit_ = fut.iloc[-1].fillna(fut.ffill().iloc[-1])      # a series that stops exits at its last close
    return exit_ / entry - 1


def build_panel(d):
    W = _wide(d)
    adj = _adj_closes()
    wired = wired_cols()
    wcols = sorted({c for cs in wired.values() for c in cs})
    panel = read_sql("SELECT sid, snapshot_date, cap_tier, fwd_return_20d, " + ", ".join(wcols) +
                     " FROM daily_snapshots_pit WHERE cap_tier IN ('LARGE','MID','SMALL')")
    panel["snapshot_date"] = pd.to_datetime(panel["snapshot_date"])
    anchors = sorted(a for a in panel["snapshot_date"].unique() if bp._is_month_start_anchor(a))
    rows = []
    for a in anchors:
        i = W["sess"].index.searchsorted(a, side="right") - 1   # last session on or before the anchor
        if i < WIN:
            continue
        lab = label_90d(adj, a)
        if lab is None:
            continue
        F = factors_at(W, i)
        F["fwd_return_90d"] = lab.reindex(F.index)
        F["snapshot_date"] = a
        rows.append(F.reset_index().rename(columns={"index": "sid"}))
    P = pd.concat(rows, ignore_index=True)
    P = P.merge(panel, on=["sid", "snapshot_date"], how="inner")
    P["slice"] = P["cap_tier"].where(~((P["cap_tier"] == "SMALL") & (P["ln_adtv_60d"] >= np.log(TRADEABLE_CR))),
                                     "SMALL_1CR")
    return P, wired


def ic_table(P, label, nw_lag, group_col="cap_tier", groups=TIERS3):
    dates = sorted(P["snapshot_date"].unique())
    split = dates[len(dates) // 2]
    rows = []
    for sig in CANDIDATES:
        for g in groups:
            d = P[P[group_col] == g]
            ics = bp._compute_ic(d, sig, label)
            agg = bp._aggregate(ics, sig, g, "intraday_slow_study", nw_lag=nw_lag) if ics else None
            if not agg:
                rows.append(dict(signal=sig, tier=g, n=0))
                continue
            ic = pd.Series({e: v for e, v, _ in ics})
            h1, h2 = ic[ic.index < split], ic[ic.index >= split]
            rows.append(dict(signal=sig, tier=g, n=agg["n_periods"], stocks=agg["n_stocks_avg"],
                             mean_ic=agg["mean_ic"], t=agg["t_stat"], ic_h1=h1.mean(), ic_h2=h2.mean(),
                             halves=bool(np.sign(h1.mean()) == np.sign(h2.mean()) == np.sign(ic.mean())
                                         and len(h1) >= 6 and len(h2) >= 6)))
    return pd.DataFrame(rows), split


def verdict(sig, r, corr):
    if r["n"] < 36 or pd.isna(r.get("t")):
        return "INSUFFICIENT (n<36)"
    s = SIGNS[sig]
    if s and np.sign(r["mean_ic"]) != s and abs(r["t"]) >= 1.5:
        return "WRONG SIGN"
    if abs(r["t"]) >= BAR and r["halves"] and not (pd.notna(corr) and abs(corr) >= 0.5):
        return "KEEP" + (" (clears Bonferroni)" if abs(r["t"]) >= BONFERRONI else "") + (" — two-sided" if not s else "")
    if abs(r["t"]) >= BAR and pd.notna(corr) and abs(corr) >= 0.5:
        return "REDUNDANT"
    return "WEAK" if abs(r["t"]) >= 1.5 else "DROP"


def incremental(P, sig, tier, controls, label="fwd_return_90d", nw_lag=NW_LAG_90):
    """IC of `sig` after removing, per anchor, its rank-linear fit on the controls (all together)."""
    ctl = [c for c in controls if c in P.columns and c != sig]
    parts = []
    for _, g in P[P.cap_tier == tier].groupby("snapshot_date"):
        g = g[["sid", "snapshot_date", sig, label] + ctl].dropna(subset=[sig, label])
        if len(g) < 30:
            continue
        y = g[sig].rank(pct=True).values
        # a control with no value ranks 0.5, the scorer's own convention for a missing factor
        X = np.column_stack([np.ones(len(g))] + [g[c].rank(pct=True).fillna(0.5).values for c in ctl])
        parts.append(g.assign(resid=y - X @ np.linalg.lstsq(X, y, rcond=None)[0]))
    if not parts:
        return dict(n=0)
    agg = bp._aggregate(bp._compute_ic(pd.concat(parts), "resid", label), sig, tier, "incr", nw_lag=nw_lag)
    return dict(n=agg["n_periods"], mean_ic=agg["mean_ic"], t=agg["t_stat"]) if agg else dict(n=0)


BENCHED = ["max_lottery_21d", "low_vol_252d", "mom_6m"]          # the nearest benched / wired relatives


def deciles(P, sig, tier, label="fwd_return_90d"):
    """Mean label by within-anchor decile of `sig` (1 = lowest), equal-weight across anchors, in %."""
    parts = []
    for _, g in P[P.cap_tier == tier].groupby("snapshot_date"):
        g = g[[sig, label]].dropna()
        if len(g) < 100:
            continue
        parts.append(g.groupby(pd.qcut(g[sig].rank(method="first"), 10, labels=False) + 1)[label].mean())
    m = pd.concat(parts, axis=1).mean(axis=1) * 100
    return dict(signal=sig, tier=tier, **{f"d{k}": v for k, v in m.items()}, spread_10_1=m.iloc[-1] - m.iloc[0])


def structure(P, d, sig, tier):
    """Mean per-anchor Spearman of `sig` with trading-structure descriptors over the same 60 sessions:
    is it thin trading or circuit locks in disguise?"""
    from scipy.stats import spearmanr
    nb = d.pivot(index="day", columns="sid", values="n_bars")
    fl = d.pivot(index="day", columns="sid", values="flat_at_low_min")
    S = P[P.cap_tier == tier]
    rows = []
    for a, g in S.groupby("snapshot_date"):
        i = nb.index.searchsorted(a, side="right") - 1
        sl = slice(max(0, i - WIN + 1), i + 1)
        desc = pd.DataFrame({"bars_per_day": nb.iloc[sl].mean(), "thin_days": (nb.iloc[sl] < 100).mean(),
                             "flat_at_low": (fl.iloc[sl] / nb.iloc[sl]).mean(), "sessions": nb.iloc[sl].notna().sum()})
        g = g.set_index("sid").join(desc)
        r = {}
        for c in ("bars_per_day", "thin_days", "flat_at_low", "sessions", "ln_adtv_60d", "rvol_60d"):
            x = g[[sig, c]].dropna()
            r[c] = spearmanr(x[sig], x[c])[0] if len(x) > 30 and x[c].nunique() > 1 else np.nan
        rows.append(r)
    return dict(signal=sig, tier=tier, **pd.DataFrame(rows).mean().to_dict())


def run():
    d = load_daily()
    P, wired = build_panel(d)
    t90, split = ic_table(P, "fwd_return_90d", NW_LAG_90)
    t20, _ = ic_table(P[P["fwd_return_20d"].notna()], "fwd_return_20d", 0)
    t90 = t90.merge(t20[["signal", "tier", "mean_ic", "t"]].rename(columns={"mean_ic": "ic_20d", "t": "t_20d"}),
                    on=["signal", "tier"], how="left")
    corr = {(s, tier): max_corr_wired(P, s, tier, wired) for s in CANDIDATES for tier in TIERS3}
    t90["max_corr_wired"] = [corr[(r.signal, r.tier)][0] for r in t90.itertuples()]
    t90["with"] = [corr[(r.signal, r.tier)][1] for r in t90.itertuples()]
    t90["verdict"] = [verdict(r.signal, r._asdict(), r.max_corr_wired) for r in t90.itertuples()]
    # the SMALL names that can take real money
    t1cr, _ = ic_table(P, "fwd_return_90d", NW_LAG_90, "slice", ["SMALL_1CR"])
    # what a strong row adds net of liquidity, realized vol and the tier's wired factors
    inc = []
    for r in t90[t90["t"].abs() >= BAR].itertuples():
        for name, ctl in (("ln_adtv_60d", ["ln_adtv_60d"]), ("rvol_60d", ["rvol_60d"]),
                          ("wired " + r.tier, wired[r.tier]),
                          ("all", ["ln_adtv_60d", "rvol_60d"] + wired[r.tier])):
            x = incremental(P, r.signal, r.tier, ctl)
            inc.append(dict(signal=r.signal, tier=r.tier, net_of=name, **x))
    inc = pd.DataFrame(inc)
    strong = list(t90[t90["t"].abs() >= BAR][["signal", "tier"]].itertuples(index=False))
    bench = sorted({c for c in BENCHED} - set(P.columns))
    if bench:
        X = read_sql("SELECT sid, snapshot_date, " + ", ".join(bench) + " FROM daily_snapshots_pit")
        X["snapshot_date"] = pd.to_datetime(X["snapshot_date"])
        P = P.merge(X, on=["sid", "snapshot_date"], how="left")
    near = pd.DataFrame([dict(signal=sg, tier=t, net_of=c, **incremental(P, sg, t, [c])) for sg, t in strong for c in BENCHED])
    dec = pd.DataFrame([deciles(P, sg, t) for sg, t in strong])
    struct = pd.DataFrame([structure(P, d, sg, t) for sg, t in strong])
    return dict(table=t90, tradeable=t1cr, incremental=inc, nearest=near, deciles=dec, structure=struct, split=split, anchors=P["snapshot_date"].nunique(),
                span=(P["snapshot_date"].min().date(), P["snapshot_date"].max().date()),
                stocks=P["sid"].nunique(), sessions=len(d), stocks_daily=d["sid"].nunique(),
                first_day=d["day"].min().date(), last_day=d["day"].max().date())


def _md(df, floatfmt=4):
    df = df.copy()
    for c in df.columns:
        if df[c].dtype.kind == "f":
            df[c] = df[c].map(lambda v: "" if pd.isna(v) else f"{v:+.{floatfmt}f}" if abs(v) < 10 else f"{v:,.1f}")
    head = "| " + " | ".join(df.columns) + " |\n|" + "---|" * len(df.columns)
    return head + "\n" + "\n".join("| " + " | ".join("" if v is None else str(v) for v in r) + " |" for r in df.values)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["build-daily", "study"])
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--sids", help="comma-separated sids (build-daily only)")
    ap.add_argument("--md", help="write the study here")
    a = ap.parse_args()
    if a.stage == "build-daily":
        build_daily(a.workers, a.sids.split(",") if a.sids else None)
        return
    R = run()
    T = R["table"]
    print(_md(T))
    if a.md:
        keep = T[T["verdict"].str.startswith("KEEP")]
        slow = T[(T["t"].abs() >= BAR) & (T["t_20d"].abs() < BAR)]
        head = [
            "# Slow factors from the minute archive at a 90-day horizon — 2026-10 study",
            "",
            f"_Run {date.today().isoformat()} · `python -m tools.intraday_slow_study study` · read-only on the DB "
            "(the `intraday_files` rows for the daily summary are the only writes)._",
            "",
            f"**Sample:** {R['anchors']} monthly anchors {R['span'][0]} → {R['span'][1]} (halves split at "
            f"{pd.Timestamp(R['split']).date()}), point-in-time cap tier from `daily_snapshots_pit`, {R['stocks']} stocks "
            f"with a complete 90-day label. Daily summary: {R['stocks_daily']} stocks, {R['sessions']:,} stock-sessions, "
            f"{R['first_day']} → {R['last_day']}, from the Kite 1-minute archive (ADR 0072) resampled to 10-minute candles.",
            "",
            "**Label:** `fwd_return_90d` = return from the first close after the anchor to the last close within 90 "
            "calendar days (built here from adjusted closes; the panel's `fwd_return_20d` beside it). Monthly anchors "
            f"overlap a 90-day label three times, so t uses Newey–West lag {NW_LAG_90}; the 20-day t is classical.",
            "",
            "**Survivorship caveat:** Kite serves listed stocks only, so the archive and every IC here are "
            "survivors-only. The day/night study showed the daily-data analogue of one factor survives delisted "
            "names; nothing here has that check yet.",
            "",
            "## Pre-registered candidates",
            "",
            "| factor | definition | sign |", "|---|---|---|",
            "| `rvol_60d` | √Σ rv over 60 sessions, rv = Σ 10-min log-return² | − |",
            "| `rskew_60d` | realized skewness of the 10-min returns, 60 sessions | − |",
            "| `jump_share_60d` | Σ(rv − π/2 · bipower)⁺ / Σ rv, 60 sessions | − |",
            "| `ofi_60d` | tick-rule signed 1-min volume / volume, 60 sessions | + |",
            "| `late_vol_share_60d` | volume 15:00–15:29 / volume, 60 sessions | two-sided (0009 S4) |",
            "| `vwap_dev_60d` | ln(last close / 60-session VWAP) | two-sided |",
            "| `smart_money_12_1` | Σ (last-30-min return − first-30-min return), sessions t−252 … t−22 | + |",
            "| `vol_of_vol_60d` | std / mean of daily √rv, 60 sessions (uncertainty about risk: Baltussen, van Bekkum, van der Grient 2018) | − |",
            "| `amihud_10m_60d` | mean √rv / ₹ Cr traded, 60 sessions | + |",
            "",
            f"Verdict: |t| ≥ {BAR} at 90 days, both halves agree in sign, max |ρ| with a wired factor < 0.5 "
            f"(Bonferroni {BONFERRONI} for the 269+ hypotheses tested so far).",
            "",
            "**Relation to research 0009:** `late_vol_share_60d` is its S4; `rskew`, `ofi` (tick rule, not BVC), "
            "`vwap_dev` and `amihud` are its fast candidates F1 / F3 / F5 / T1 tested here at the slow horizon; "
            "`smart_money_12_1` is S1's minute-bar version (last half hour minus first). 0009 left realized "
            "volatility and jump share off its menu on purpose (duplicate of the failed `low_vol_252d`; a size proxy): "
            "they run here as controls, not as new hypotheses. S5 (semibeta) needs the synthetic market series and is not here.",
            "",
            "## Verdicts",
            "",
            ("**KEEP at 90 days:** " + ", ".join(f"`{r.signal}` {r.tier} (t {r.t:.2f})" for r in keep.itertuples()))
            if len(keep) else "**Nothing clears the bar at 90 days.**",
            "",
            ("**Slow, not fast (|t| ≥ 2.5 at 90 days, < 2.5 at 20 days):** "
             + ", ".join(f"`{r.signal}` {r.tier} (t 90d {r.t:.2f} vs 20d {r.t_20d:.2f})" for r in slow.itertuples()))
            if len(slow) else "**No factor is strong at 90 days while weak at 20 days.**",
            "",
            "## IC table (panel, PIT tier, label fwd_return_90d; 20-day beside it)",
            "",
            _md(T.rename(columns={"t": "t_90d", "mean_ic": "ic_90d"})),
            "",
            "## SMALL names trading ≥ ₹1 Cr a day (label fwd_return_90d)",
            "",
            _md(R["tradeable"].rename(columns={"t": "t_90d", "mean_ic": "ic_90d", "tier": "slice"})),
            "",
            "## What the strong rows add (|t| ≥ 2.5): IC net of liquidity, realized vol, the tier's wired factors",
            "",
            _md(R["incremental"]) if len(R["incremental"]) else "_none_",
            "",
            "## The strong rows net of their nearest relatives (benched `max_lottery_21d`, `low_vol_252d`; wired `mom_6m`)",
            "",
            _md(R["nearest"]) if len(R["nearest"]) else "_none_",
            "",
            "## Decile shape of the strong rows (mean 90-day return in %, decile 1 = lowest factor value)",
            "",
            _md(R["deciles"], 1) if len(R["deciles"]) else "_none_",
            "",
            "## Are the strong rows trading structure in disguise? (mean per-anchor Spearman with descriptors)",
            "",
            _md(R["structure"], 2) if len(R["structure"]) else "_none_",
            "",
            "## Reading it",
            "",
            "- `t_90d` is the Newey–West t of the mean monthly rank IC against the 90-day label; `t_20d` the "
            "classical t against the 20-day label on the same anchors.",
            "- `halves` = both halves of the sample carry the sign of the whole.",
            "- `max_corr_wired` = the strongest mean per-anchor Spearman correlation with a factor already wired "
            "in that tier (`with`); ≥ 0.5 means the information is already in the model.",
            "- WRONG SIGN = the pre-registered sign failed with |t| ≥ 1.5; WEAK = 1.5 ≤ |t| < 2.5; DROP otherwise.",
            "",
            "## Next",
            "",
            "- A KEEP goes to a promotion review (registration in `factors.FACTORS` as LIBRARY with a PIT twin "
            "from the daily summary, then `tools/multiple_testing.py`); never a weight from this table.",
            "- The survivorship check needs delisted minute history, which Kite does not have: the fallback is the "
            "daily-data analogue on `stock_prices_unlisted` where one exists.",
            "- The daily summary (`data/intraday/daily_1m/`) is the `intraday_daily` deliverable of ADR 0072; the "
            "weekly forward fetch must append to it.",
        ]
        Path(a.md).write_text("\n".join(head) + "\n")
        print(f"\nwrote {a.md}")


if __name__ == "__main__":
    main()
