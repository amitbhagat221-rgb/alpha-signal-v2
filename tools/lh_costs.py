"""Plan 0024 — what one trade really costs in a Zerodha retail account (equity delivery).

    one_way_cost_bps(adtv_inr, price, trade_value_inr, tier)  -> basis points of trade value

One-way = the average of a buy and a sell (a round trip is twice this). Three parts:
  1. Statutory and Zerodha charges (ZERODHA below; zerodha.com/charges read 2026-10-12).
  2. Half the bid-ask spread, by liquidity (20-session median traded value, ADTV).
  3. Market impact, square-root law: Y * daily volatility * sqrt(trade / ADTV).

Calibration (`python -m tools.lh_costs --calibrate`, read-only on the DB) writes
data/lh/costs.json, which one_way_cost_bps reads:
  - spreads: the panel's Corwin-Schultz `bidask_spread_proxy` (daily high/low) is scaled down
    to the spread seen in 1-minute closes (Roll estimator on the Kite minute-bar archive)
    wherever that archive covers the stock; the ratio is taken per ADTV bucket.
  - then checked against the real fills of 2026-10-12 (Kite trades/orders, read-only) and,
    if those fills cost more than the model says, the spread is scaled UP (never down: one
    day of sells cannot prove trading is cheaper than the model).
  - a per-year scale from the panel's spread history, so a backtest in 2020 pays 2020 spreads.

Nothing here writes to the DB or places orders.
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sqlite3
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = os.environ.get("ALPHA_DB") or str(ROOT / "data" / "alpha_signal.db")
OUT = Path(os.environ.get("ALPHA_LH", ROOT / "data" / "lh")) / "costs.json"   # ALPHA_LH: a worktree has no data/
BARS = ROOT / "data" / "intraday" / "bars_1m"
FILLS = ROOT / "data" / "lh" / "fills_2026-10-12.json"   # the account's fills, saved by --calibrate

# ── 1. Charges: Zerodha equity delivery, individual account (zerodha.com/charges, read 2026-10-12) ──
ZERODHA = {
    "brokerage": 0.0,                 # ₹0 on delivery for individuals
    "stt": 0.001,                     # 0.1 % on buy AND sell
    "exchange_nse": 0.0000307,        # NSE transaction charge 0.00307 % (BSE 0.00375 %)
    "exchange_bse": 0.0000375,
    "sebi": 10 / 1e7,                 # ₹10 per crore
    "ipft_nse": 0.01 / 1e7,           # ₹0.01 per crore (+GST) as quoted; negligible either way
    "gst": 0.18,                      # on brokerage + exchange + SEBI (+ IPFT)
    "stamp_buy": 0.00015,             # 0.015 % on the buy side only
    "dp_per_sell_rs": 15.34,          # per scrip per sell day, GST included (₹3.5 CDSL + ₹9.5 Zerodha + ₹2.34 GST)
    "source": "https://zerodha.com/charges read 2026-10-12",
}
STRESS_MULT = 2.0    # sensitivity: spread and impact doubled
IMPACT_Y = 1.0        # square-root impact coefficient (literature: of order 1 with daily vol and volume)
ADTV_WINDOW = 20      # sessions for the median traded value
VOL_WINDOW = 60       # sessions for daily volatility (std of log returns, |move| < 20 %)
ROLL_WINDOW = 20      # sessions of minute bars for the Roll spread
ADTV_EDGES_CR = [0, 0.5, 1, 2, 5, 10, 25, 100, 500, 1e9]   # ₹ crore
TRADE_SIZES = {"50k": 50_000, "1L": 100_000, "2L": 200_000}


def statutory_bps(trade_value_inr: float, side: str = "avg", exchange: str = "NSE") -> float:
    """Charges in bps for one trade. side = 'buy' | 'sell' | 'avg' (the one-way average)."""
    z = ZERODHA
    exch = z["exchange_bse"] if exchange == "BSE" else z["exchange_nse"]
    taxed = (z["brokerage"] + exch + z["sebi"] + z["ipft_nse"]) * (1 + z["gst"])
    buy = z["stt"] + taxed + z["stamp_buy"]
    sell = z["stt"] + taxed + z["dp_per_sell_rs"] / max(trade_value_inr, 1.0)
    frac = {"buy": buy, "sell": sell, "avg": (buy + sell) / 2}[side]
    return frac * 1e4


def _tick(price):
    # NSE tick: ₹0.01 below ₹250 (2025 revision), ₹0.05 above — assumption, only a floor
    return 0.01 if price < 250 else 0.05


@lru_cache(maxsize=1)
def _model():
    if not OUT.exists():
        raise FileNotFoundError(f"{OUT} missing — run `python -m tools.lh_costs --calibrate` first")
    return json.loads(OUT.read_text())


def _interp(adtv_inr, curve):
    """Piecewise-linear in log(ADTV) through the bucket medians; flat beyond the ends."""
    x = np.log([p["adtv_cr"] * 1e7 for p in curve])
    y = [p["v"] for p in curve]
    return float(np.interp(math.log(max(adtv_inr, 1.0)), x, y))


def cost_breakdown(adtv_inr, price, trade_value_inr, tier, side="avg", year=None, exchange="NSE", stress=False):
    """All parts in bps. adtv_inr None → the tier's median ADTV. year → that year's spread scale.
    stress → spread and impact doubled (the sensitivity case for the illiquid end, see 02-costs.md)."""
    m = _model()
    if adtv_inr is None or not np.isfinite(adtv_inr) or adtv_inr <= 0:
        adtv_inr = m["tier_median_adtv_inr"][tier]
    scale = STRESS_MULT if stress else 1.0
    if year is not None:
        ys = m["spread_scale_by_year"].get(tier) or m["spread_scale_by_year"]["ALL"]
        years = sorted(int(k) for k in ys)
        scale *= ys[str(min(max(int(year), years[0]), years[-1]))]
    half = _interp(adtv_inr, m["half_spread_curve_bps"]) * m["fill_calibration"]["spread_multiplier"]
    half = max(half, _tick(price) / 2 / price * 1e4) * scale
    sigma = _interp(adtv_inr, m["daily_vol_curve"])
    impact = IMPACT_Y * sigma * math.sqrt(trade_value_inr / adtv_inr) * 1e4 * scale
    fees = statutory_bps(trade_value_inr, side, exchange)
    return {"fees": fees, "half_spread": half, "impact": impact, "total": fees + half + impact}


def one_way_cost_bps(adtv_inr, price, trade_value_inr, tier, side="avg", year=None, stress=False):
    """One-way cost of a delivery trade, bps of trade value (fees + half-spread + impact).
    adtv_inr: 20-session median traded value in ₹ (None → the tier median). price in ₹.
    year: scale spread + impact to that year's liquidity (panel spread history). stress: x2."""
    return cost_breakdown(adtv_inr, price, trade_value_inr, tier, side, year, stress=stress)["total"]


# ─────────────────────────── calibration (read-only) ───────────────────────────

def _ro():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def _bucket(adtv_cr):
    return pd.cut(adtv_cr, ADTV_EDGES_CR, right=False,
                  labels=[f"{a:g}-{b:g}cr" if b < 1e9 else f">{a:g}cr"
                          for a, b in zip(ADTV_EDGES_CR[:-1], ADTV_EDGES_CR[1:])])


def stock_liquidity(con, asof):
    """Per stock at `asof`: price, ADTV (₹), daily vol, Corwin-Schultz spread, tier."""
    dates = [r[0] for r in con.execute(
        "SELECT DISTINCT date FROM stock_prices WHERE date<=? ORDER BY date DESC LIMIT ?",
        (asof, VOL_WINDOW + 1))]
    px = pd.read_sql("SELECT sid, date, close, volume, traded_value FROM stock_prices WHERE date>=? AND date<=?",
                     con, params=(dates[-1], asof)).sort_values(["sid", "date"])
    px["tv"] = px["traded_value"].where(px["traded_value"] > 0, px["volume"] * px["close"])
    last20 = set(dates[:ADTV_WINDOW])
    adtv = px[px.date.isin(last20)].groupby("sid")["tv"].median()
    px["lr"] = np.log(px["close"]).groupby(px["sid"]).diff()
    # std of daily log returns, dropping |move| >= 20 % (splits / bonuses in raw closes)
    mad = px[px.lr.abs() < 0.2].groupby("sid")["lr"].std()
    last = px.groupby("sid").tail(1).set_index("sid")
    snap = con.execute("SELECT max(snapshot_date) FROM daily_snapshots_pit WHERE snapshot_date<=?", (asof,)).fetchone()[0]
    pan = pd.read_sql("SELECT sid, cap_tier, bidask_spread_proxy cs FROM daily_snapshots_pit WHERE snapshot_date=?",
                      con, params=(snap,)).set_index("sid")
    df = pd.DataFrame({"price": last["close"], "last_date": last["date"], "adtv_inr": adtv, "sigma_d": mad}).join(pan, how="inner")
    df = df[(df.adtv_inr > 0) & df.price.gt(0) & df.cap_tier.notna()]
    df.attrs["panel_date"] = snap
    return df


def roll_spreads(asof, sids):
    """Full spread (fraction) from 1-minute closes, Roll (1984): 2*sqrt(-cov(r_t, r_t-1)),
    within-day returns only, last ROLL_WINDOW sessions up to asof. NaN when cov >= 0."""
    import pyarrow.parquet as pq
    lo = pd.Timestamp(asof, tz="UTC") - pd.Timedelta(days=ROLL_WINDOW * 1.6)
    hi = pd.Timestamp(asof, tz="UTC") + pd.Timedelta(days=1)
    out = {}
    for f in glob.glob(str(BARS / "**" / "sid=*.parquet"), recursive=True):
        sid = Path(f).stem.split("=", 1)[1]
        if sid not in sids:
            continue
        try:
            d = pq.read_table(f, columns=["ts", "close"], filters=[("ts", ">=", lo), ("ts", "<", hi)]).to_pandas()
        except Exception:
            continue   # a file the running backfill is still writing
        if len(d) < 1000:
            continue
        d = d.sort_values("ts")
        d["day"] = (d.ts + pd.Timedelta(minutes=330)).dt.date
        days = sorted(d.day.unique())[-ROLL_WINDOW:]
        d = d[d.day.isin(days)]
        d["r"] = np.log(d.close.astype(float)).groupby(d.day).diff()
        d["r1"] = d.r.groupby(d.day).shift(1)
        x = d.dropna(subset=["r", "r1"])
        if len(x) < 500:
            continue
        cov = float(np.cov(x.r, x.r1)[0, 1])
        out[sid] = 2 * math.sqrt(-cov) if cov < 0 else np.nan
    return pd.Series(out, name="roll", dtype=float)


def spread_history(con):
    """Median Corwin-Schultz spread per tier per year on the monthly anchors, as a multiple of
    the latest year's — how much wider trading was then."""
    d = pd.read_sql("SELECT snapshot_date, cap_tier, bidask_spread_proxy cs FROM daily_snapshots_pit "
                    "WHERE bidask_spread_proxy IS NOT NULL AND cap_tier IS NOT NULL", con)
    d["snapshot_date"] = pd.to_datetime(d.snapshot_date)
    from tools.backtest_pit import _is_month_start_anchor
    anchors = {x for x in d.snapshot_date.unique() if _is_month_start_anchor(pd.Timestamp(x))}
    d = d[d.snapshot_date.isin(anchors)]
    d["year"] = d.snapshot_date.dt.year
    med = d.groupby(["cap_tier", "year"])["cs"].median().unstack(0)
    med["ALL"] = d.groupby("year")["cs"].median()
    last = med.index.max()
    scale = (med / med.loc[last]).round(3)
    return ({t: {str(y): float(v) for y, v in scale[t].dropna().items()} for t in scale.columns},
            {t: {str(y): round(float(v) * 1e4, 1) for y, v in med[t].dropna().items()} for t in med.columns})


def load_fills(refresh):
    """The account's fills of 2026-10-12, read-only from Kite (trades, orders, one quote call).
    Saved to FILLS so the calibration can be rerun after the token expires."""
    if FILLS.exists() and not refresh:
        return json.loads(FILLS.read_text())
    from sources.kite_pull import kite
    from sources import _http
    kc = kite(cached_only=True)
    with _http.pace("kite"):
        trades = kc.trades()
    with _http.pace("kite"):
        orders = kc.orders()
    syms = sorted({o["tradingsymbol"] for o in orders})
    with _http.pace("kite"):
        quotes = kc.quote([f"NSE:{s}" for s in syms])
    keep = lambda r: {k: (str(v) if not isinstance(v, (int, float, str, type(None))) else v) for k, v in r.items()}
    blob = {"trades": [keep(t) for t in trades], "orders": [keep(o) for o in orders],
            "quotes": {k: {"last_price": v["last_price"], "average_price": v.get("average_price"),
                           "open": v["ohlc"]["open"], "high": v["ohlc"]["high"], "low": v["ohlc"]["low"],
                           "prev_close": v["ohlc"]["close"], "volume": v.get("volume")}
                       for k, v in quotes.items()}}
    FILLS.parent.mkdir(parents=True, exist_ok=True)
    FILLS.write_text(json.dumps(blob, indent=1))
    return blob


def _prefill_minute_close(sid, fill_ts_ist):
    """Close of the last full 1-minute bar before the fill (₹), from the minute-bar archive."""
    import pyarrow.parquet as pq
    f = BARS / "_staging" / f"sid={sid}.parquet"
    if not f.exists():
        return np.nan
    t = pd.Timestamp(fill_ts_ist).tz_localize("Asia/Kolkata").tz_convert("UTC")
    d = pq.read_table(f, columns=["ts", "close"],
                      filters=[("ts", ">=", t - pd.Timedelta(minutes=30)), ("ts", "<", t.floor("min"))]).to_pandas()
    return float(d.sort_values("ts").close.iloc[-1]) / 100 if len(d) else np.nan   # stored in paise


def fill_slippage(blob, liq, con):
    """Each completed order: realised cost (bps, + = worse for us) against the day's VWAP,
    the day's close, (H+L+C)/3, and the last 1-minute close before the fill where we have bars."""
    o = pd.DataFrame(blob["orders"])
    o = o[(o.status == "COMPLETE") & (o.filled_quantity > 0)]
    st = pd.read_sql("SELECT sid, ticker FROM stocks", con)
    o = o.merge(st, left_on="tradingsymbol", right_on="ticker", how="inner")   # drops ETFs
    rows = []
    for _, r in o.iterrows():
        q = blob["quotes"].get(f"NSE:{r.tradingsymbol}")
        if not q or r.sid not in liq.index:
            continue
        fill = float(r.average_price)
        sgn = 1 if r.transaction_type == "SELL" else -1      # a sell below the reference is a cost
        close = q["last_price"]
        typ = (q["high"] + q["low"] + close) / 3
        pre = _prefill_minute_close(r.sid, r.order_timestamp)
        val = fill * r.filled_quantity
        L = liq.loc[r.sid]
        model = cost_parts_raw(L.adtv_inr, L.price, val, L.half_spread_bps, L.sigma_d)
        bp = lambda ref: sgn * (ref - fill) / ref * 1e4 if ref and np.isfinite(ref) else np.nan
        rows.append({"symbol": r.tradingsymbol, "sid": r.sid, "tier": L.cap_tier, "order_type": r.order_type,
                     "exchange": r.exchange, "side": r.transaction_type, "value_inr": round(val),
                     "adtv_cr": round(L.adtv_inr / 1e7, 2), "pct_of_adtv": round(100 * val / L.adtv_inr, 3),
                     "vs_vwap_bps": bp(q["average_price"]), "vs_close_bps": bp(close), "vs_typical_bps": bp(typ),
                     "vs_prev_minute_bps": bp(pre),
                     "model_half_spread_bps": model["half_spread"], "model_impact_bps": model["impact"]})
    return pd.DataFrame(rows)


def cost_parts_raw(adtv_inr, price, value, half_spread_bps, sigma_d):
    half = max(half_spread_bps, _tick(price) / 2 / price * 1e4)
    return {"half_spread": half, "impact": IMPACT_Y * sigma_d * math.sqrt(value / adtv_inr) * 1e4}


def calibrate(asof=None, refresh_fills=False):
    con = _ro()
    asof = asof or con.execute("SELECT max(date) FROM stock_prices").fetchone()[0]
    liq = stock_liquidity(con, asof)
    liq["adtv_cr"] = liq.adtv_inr / 1e7
    liq["bucket"] = _bucket(liq.adtv_cr)
    liq["roll"] = roll_spreads(asof, set(liq.index))
    ok = liq.roll.notna() & liq.cs.gt(0)
    liq["ratio"] = np.where(ok, liq.roll / liq.cs, np.nan)
    ratio_b = liq.groupby("bucket", observed=False)["ratio"].agg(["median", "count"])
    # buckets with < 10 Roll stocks borrow the ratio of the nearest bucket that has them
    good = ratio_b[ratio_b["count"] >= 10]["median"]
    pos = {b: i for i, b in enumerate(ratio_b.index)}
    near = {b: good.iloc[int(np.argmin([abs(pos[g] - pos[b]) for g in good.index]))] for b in ratio_b.index}
    liq["half_spread_bps"] = np.where(liq.roll.notna(), liq.roll / 2,
                                      liq.cs * liq.bucket.map(near).astype(float) / 2) * 1e4

    # bucket curves (pooled over tiers: liquidity, not the label, drives cost)
    g = liq.groupby("bucket", observed=False)
    table = pd.DataFrame({"n": g.size(), "n_roll": g["roll"].count(),
                          "median_adtv_cr": g["adtv_cr"].median(),
                          "cs_full_spread_bps": g["cs"].median() * 1e4,
                          "roll_full_spread_bps": g["roll"].median() * 1e4,
                          "roll_over_cs": ratio_b["median"], "ratio_used": pd.Series(near),
                          "half_spread_bps": g["half_spread_bps"].median(),
                          "daily_vol_pct": g["sigma_d"].median() * 100}).dropna(subset=["median_adtv_cr"])
    curve_hs = [{"adtv_cr": float(r.median_adtv_cr), "v": float(r.half_spread_bps)} for _, r in table.iterrows()]
    curve_vol = [{"adtv_cr": float(r.median_adtv_cr), "v": float(r.daily_vol_pct / 100)} for _, r in table.iterrows()]

    # real fills
    calib = {"spread_multiplier": 1.0, "n_fills": 0, "note": "no fills available"}
    fills = pd.DataFrame()
    try:
        blob = load_fills(refresh_fills)
        fills = fill_slippage(blob, liq, con)
    except Exception as e:   # token expired and nothing saved
        calib["note"] = f"fills unavailable: {type(e).__name__}: {e}"
    if len(fills):
        model_tot = fills.model_half_spread_bps + fills.model_impact_bps
        real = fills.vs_vwap_bps
        mult = float(np.nanmedian(real) / np.nanmedian(model_tot)) if np.nanmedian(model_tot) > 0 else 1.0
        calib = {"n_fills": int(len(fills)),
                 "median_real_vs_vwap_bps": round(float(np.nanmedian(real)), 1),
                 "median_real_vs_close_bps": round(float(np.nanmedian(fills.vs_close_bps)), 1),
                 "median_real_vs_typical_bps": round(float(np.nanmedian(fills.vs_typical_bps)), 1),
                 "n_prev_minute": int(fills.vs_prev_minute_bps.notna().sum()),
                 "median_real_vs_prev_minute_bps": (round(float(np.nanmedian(fills.vs_prev_minute_bps)), 1)
                                                    if fills.vs_prev_minute_bps.notna().any() else None),
                 "median_model_bps": round(float(np.nanmedian(model_tot)), 1),
                 "raw_ratio_real_over_model": round(mult, 2),
                 "bootstrap_90ci_median_vs_vwap_bps": [round(float(x), 1) for x in np.percentile(
                     [np.nanmedian(np.random.default_rng(i).choice(real.dropna().values, real.notna().sum()))
                      for i in range(2000)], [5, 95])],
                 "market_orders": {"n": int((fills.order_type == "MARKET").sum()),
                                   "median_vs_vwap_bps": round(float(fills[fills.order_type == "MARKET"].vs_vwap_bps.median()), 1),
                                   "median_model_bps": round(float(model_tot[fills.order_type == "MARKET"].median()), 1)},
                 "limit_orders": {"n": int((fills.order_type == "LIMIT").sum()),
                                  "median_vs_vwap_bps": round(float(fills[fills.order_type == "LIMIT"].vs_vwap_bps.median()), 1),
                                  "median_model_bps": round(float(model_tot[fills.order_type == "LIMIT"].median()), 1)},
                 "prev_minute_model_bps": (round(float(model_tot[fills.vs_prev_minute_bps.notna()].median()), 1)
                                           if fills.vs_prev_minute_bps.notna().any() else None),
                 "value_weighted_vs_vwap_bps": round(float((fills.vs_vwap_bps * fills.value_inr).sum() / fills.value_inr.sum()), 1),
                 # raise only, and only with >= 10 fills: one day of sells cannot prove trading is cheaper
                 "spread_multiplier": round(max(1.0, mult), 2) if len(fills) >= 10 else 1.0}
    liq_med_adtv = liq.groupby("cap_tier")["adtv_inr"].median()
    scale_year, cs_year = spread_history(con)
    model = {"asof_prices": asof, "panel_date": liq.attrs["panel_date"], "zerodha": ZERODHA,
             "impact_y": IMPACT_Y, "adtv_window": ADTV_WINDOW, "vol_window": VOL_WINDOW,
             "half_spread_curve_bps": curve_hs, "daily_vol_curve": curve_vol,
             "fill_calibration": calib,
             "tier_median_adtv_inr": {t: float(v) for t, v in liq_med_adtv.items()},
             "spread_scale_by_year": scale_year, "cs_median_full_spread_bps_by_year": cs_year,
             "buckets": json.loads(table.reset_index(names="bucket").round(3).to_json(orient="records"))}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(model, indent=1))
    _model.cache_clear()

    # per-tier costs for the standard trade sizes, each stock at its own liquidity
    per_tier = {}
    for tier, grp in liq.groupby("cap_tier"):
        row = {"n_stocks": int(len(grp)), "median_adtv_cr": round(float(grp.adtv_cr.median()), 2)}
        for name, v in TRADE_SIZES.items():
            parts = pd.DataFrame([cost_breakdown(r.adtv_inr, r.price, v, tier) for r in grp.itertuples()])
            row[name] = {"median_bps": round(float(parts.total.median()), 1),
                         "p75_bps": round(float(parts.total.quantile(.75)), 1),
                         "p90_bps": round(float(parts.total.quantile(.90)), 1),
                         "median_fees_bps": round(float(parts.fees.median()), 2),
                         "median_half_spread_bps": round(float(parts.half_spread.median()), 1),
                         "median_impact_bps": round(float(parts.impact.median()), 1),
                         "share_over_1pct_adtv": round(float((v / grp.adtv_inr > 0.01).mean()), 3),
                         "median_stress_bps": round(float(np.median([one_way_cost_bps(r.adtv_inr, r.price, v, tier, stress=True)
                                                                     for r in grp.itertuples()])), 1)}
        per_tier[tier] = row
    by_bucket = {}
    for b, grp in liq.groupby("bucket", observed=True):
        by_bucket[str(b)] = {"n": int(len(grp)), **{name: round(float(np.median(
            [one_way_cost_bps(r.adtv_inr, r.price, v, r.cap_tier) for r in grp.itertuples()])), 1)
            for name, v in TRADE_SIZES.items()}}
    model["per_tier_one_way_bps"] = per_tier
    model["by_adtv_bucket_one_way_bps"] = by_bucket
    model["fills"] = json.loads(fills.round(2).to_json(orient="records")) if len(fills) else []
    OUT.write_text(json.dumps(model, indent=1))
    _model.cache_clear()
    return model, liq, fills


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--asof")
    ap.add_argument("--refresh-fills", action="store_true", help="re-read today's fills from Kite")
    a = ap.parse_args()
    if a.calibrate:
        m, liq, fills = calibrate(a.asof, a.refresh_fills)
        pd.set_option("display.width", 220)
        print(pd.DataFrame(m["buckets"]).to_string())
        print(json.dumps(m["fill_calibration"], indent=1))
        if len(fills):
            print(fills.round(1).to_string())
        print(json.dumps(m["per_tier_one_way_bps"], indent=1))
        print(json.dumps(m["by_adtv_bucket_one_way_bps"], indent=1))
        print(json.dumps(m["spread_scale_by_year"], indent=1))


if __name__ == "__main__":
    main()
