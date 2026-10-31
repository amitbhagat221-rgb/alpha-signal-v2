"""
Alpha Signal v2 — the /options/expected page's inputs (plan 0029): what the weekly strangle is expected
to make over any period, with the loss weeks as an assumption you can change.

Model, per index and per lot (the page does the arithmetic and the simulation):
  a winning week keeps `keep` × the credit; a loss week loses `loss` × the credit; a crash week
  (a −13.9 % gap, as the Live book's sizing card) loses the quote's crash loss. Credit = today's sizing
  quote (unprotected, or net of the wings when protected), else the backtest's last 8 weeks × today's lot.
Defaults are the backtest's own trades (tools.combined_book_study cache: exp2, 0.05 delta, EOD settles,
1 % slippage and charges inside `net`), less the per-order brokerage it charged on ONE lot (₹23.6 an order
over 65 units is ~26 % of a winged NIFTY credit; at 30 lots it is <1 %): the page charges brokerage per
order at your lots (freeze-quantity slices, as options_live.slices). With the live VIX guard: no entry at VIX ≥ vix_halt, half the
lots above vix_halve. NIFTY 2019-01 →, SENSEX 2024-01 → (BSE weeklies).

Reads: data/lh/v2/combined_trades_{strangle,condor}.parquet, option_live_settings (quote, caps, margin).
"""

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
TRADES = {"naked": ROOT / "data" / "lh" / "v2" / "combined_trades_strangle.parquet",
          "winged": ROOT / "data" / "lh" / "v2" / "combined_trades_condor.parquet"}
EXPIRY_DOW = {"NIFTY": 1, "SENSEX": 3}             # Tuesday, Thursday (a holiday moves the expiry, not the week)
LEGS = {"naked": 2, "winged": 4}                # orders per entry (cash-settled: no exit orders)
WIN_KEEP_PCT = 99                                   # a winning week keeps 99 % of the credit (Amit 2026-10-29; backtest 96-99 %)
WING_SHARE_WEEKS = 8                                # protected credit: the wings' typical cost = median share of the last 8 entries
TAX_DEFAULT = 31.2                                  # % on profit: 30 % slab + 4 % cess (F&O is business income)


def _guard(t, s):
    """The live VIX guard on the backtest's weeks: weight 0 (no entry), 0.5 (half the lots) or 1."""
    v = t["vix"].fillna(0)
    return np.where(v >= s["vix_halt"], 0.0, np.where(v > s["vix_halve"], 0.5, 1.0))


def stats(t, s, legs):
    """One index × structure of the backtest → the page's defaults and its by-year record. A week's result
    r is a share of its credit, after slippage, exchange charge, STT and stamp, before brokerage."""
    from option_book import BROKERAGE_RS, GST
    net = t["net"] + legs * BROKERAGE_RS * (1 + GST) / t["lot"]
    t = t.assign(w=_guard(t, s), r=net / t["credit"], pct=net / t["F"])          # pct: the week as a share of the index
    g = t[t.w > 0]
    win, loss = g[g.r > 0], g[g.r <= 0]
    years = [{"year": y, "weeks": len(x), "loss_weeks": int((x.r <= 0).sum()), "kept": float(x.r.mean()),
              "worst": float(x.r.min())} for y, x in g.groupby(g.entry.str[:4])]
    return {"n": len(g), "n_all": len(t), "traded_share": len(g) / len(t), "first": g.entry.min(), "last": g.entry.max(),
            "keep": float(win.r.mean()), "loss": float(-loss.r.mean()) if len(loss) else 0.0,
            "loss_per_year": len(loss) / len(g) * 52, "worst": float(-g.r.min()),
            "losses": sorted(float(-x) for x in loss.r), "losses_pct": sorted(float(-x) for x in loss.pct),
            "loss_pct": float(-loss.pct.mean()) if len(loss) else 0.0, "mean": float(g.r.mean()),
            "credit_pts_recent": float(g.sort_values("entry").credit.tail(8).median()),
            "years": years,
            "weeks": [{"expiry": e, "r": float(r), "w": float(w)} for e, r, w in zip(g.expiry, g.r, g.w)]}


def wing_share(tr, u):
    """The wings' cost as a share of the unprotected credit at entry (exchange settle), median of the index's last
    WING_SHARE_WEEKS entries. Kite's day-of quote can be far off: on 2026-10-29 the SENSEX wing strikes for the
    week-ahead expiry had not traded yet and their asks priced the wings at 63 % of the credit (entries: 22-32 %)."""
    m = tr["naked"][tr["naked"].underlying == u].merge(tr["winged"][tr["winged"].underlying == u], on="expiry", suffixes=("_s", "_c"))
    m = m[m.credit_s > 0].sort_values("expiry").tail(WING_SHARE_WEEKS)
    return float((1 - m.credit_c / m.credit_s).median()) if len(m) else None


def page_data():
    import config
    import options_live as ol
    import option_book as ob
    from datetime import date
    s = ol.settings()
    quote = ol.get_state("sizing_quote") or {}
    margin = ol.get_state("margin") or {}
    missing = [str(p.relative_to(ROOT)) for p in TRADES.values() if not p.exists()]
    if missing:
        return {"error": "backtest trades not cached: run `python -m tools.combined_book_study --smoke` (" + ", ".join(missing) + ")"}
    tr = {k: pd.read_parquet(p) for k, p in TRADES.items()}
    today = date.today().isoformat()
    out, pool = {}, {"naked": [], "winged": []}
    for u in ("NIFTY", "SENSEX"):
        m = (quote.get("markets") or {}).get(u) or {}
        lot = m.get("lot") or ob.lot_size(u, today)
        per = {}
        for kind in ("naked", "winged"):
            st = stats(tr[kind][tr[kind].underlying == u], s, LEGS[kind])
            q = m.get(kind) or {}
            credit = q.get("credit_rs") or st["credit_pts_recent"] * lot
            ws, ws_quote = None, None
            if kind == "winged" and (m.get("naked") or {}).get("credit_rs"):
                ws = wing_share(tr, u)
                ws_quote = 1 - (q.get("credit_rs") or 0) / m["naked"]["credit_rs"] if q.get("credit_rs") else None
                if ws is not None:
                    credit = m["naked"]["credit_rs"] * (1 - ws)
            cap = None                                  # the most a protected week can lose, per lot
            if kind == "winged" and m.get("strikes"):
                k = m["strikes"]
                cap = max(k["wing_C"] - k["C"], k["P"] - k["wing_P"]) * lot - credit
            pool[kind] += st["losses_pct"]
            per[kind] = {**st, "legs": LEGS[kind], "credit_rs": credit, "credit_from": "quote" if q.get("credit_rs") else "backtest",
                         "wing_share": ws, "wing_share_quote": ws_quote, "credit_quote_rs": q.get("credit_rs"),
                         "crash_rs": q.get("crash"), "margin_rs": q.get("margin"), "max_loss_rs": cap}
        spot = m.get("spot") or float(tr["naked"][tr["naked"].underlying == u].sort_values("entry").F.iloc[-1])
        out[u] = {"lot": lot, "notional_rs": spot * lot, "expiry_dow": EXPIRY_DOW[u], "freeze": config.OPTIONS_LIVE["freeze_qty"][u], "lots": int(s["lots_cap"].get(u, 0)), "extra_rs": m.get("extra"),
                  **per}
    # a loss week's size, pooled over both indices as a share of the index: SENSEX alone has 4 loss weeks (2024 →),
    # one of them 0.92 % of the index, and a lot of either is ~₹15 L of index, so one loss size fits both
    pooled = {k: {"losses_pct": sorted(v), "loss_pct": float(np.mean(v)) if v else 0.0, "n": len(v)} for k, v in pool.items()}
    for u, m in out.items():                        # the page defaults per lot: a loss week's ₹ and the average week before brokerage
        for kind in ("naked", "winged"):
            k = m[kind]
            loss = pooled[kind]["loss_pct"] * m["notional_rs"]
            k["loss_rs"] = min(loss, k["max_loss_rs"]) if k["max_loss_rs"] else loss
            k["p_week"] = k["loss_per_year"] / 52
            k["week_lot_rs"] = (1 - k["p_week"]) * WIN_KEEP_PCT / 100 * k["credit_rs"] - k["p_week"] * k["loss_rs"]
    return {"markets": out, "pooled": pooled, "kind": "winged" if s["wing_pct"] else "naked", "wing_pct": quote.get("wing_pct") or s["wing_pct"],
            "keep_pct": WIN_KEEP_PCT, "buffer_rs": s["margin_buffer_rs"], "lots_max": s["lots_hard_max"], "brokerage_rs": ob.BROKERAGE_RS * (1 + ob.GST), "capital": margin.get("total"), "tax_pct": TAX_DEFAULT, "quote_at": quote.get("at"),
            "guard": {"halve": s["vix_halve"], "halt": s["vix_halt"]}, "crash_gap": ol.SIZING["crash_gap"],
            "today": today}
