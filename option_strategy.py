"""
Alpha Signal v2 — strategy views for the ops cockpit's options pages (plan 0029).

Turns a paper trade (option_book) or the open live legs (options_live) into one shape the
strategy builder on /options/capital and /options/live renders: legs with entry price, the
latest price and an implied volatility, the index reference, the clock (start → expiry) and
open interest by strike. The page prices every leg with Black-76 from these (payoff at expiry,
value on a target date, greeks); nothing here decides or trades.

Reads: fno_bhav (chains: settle, OI, index level), option_live_settings via options_live.page_data.
"""

from datetime import date, datetime, timedelta, timezone

import numpy as np

from db import read_sql
from sources.fno_iv import R, _invert_iv

IST = timezone(timedelta(hours=5, minutes=30))
STEP = {"NIFTY": 50, "SENSEX": 100}             # strike spacing of the weekly chain
OI_BAND = 0.06                                  # OI bars within 6 % of the index
YEAR_S = 365.0 * 86400


def close_ts(d):
    """15:30 IST on ISO date d (the close; index options settle then)."""
    return datetime.combine(date.fromisoformat(d), datetime.min.time(), IST).replace(hour=15, minute=30)


def years(t0, t1):
    return max((t1 - t0).total_seconds(), 0.0) / YEAR_S


def _iv(px, F, K, T, cp):
    v = _invert_iv(px, F, K, T, cp) if px and T > 0 else np.nan
    return None if v is None or np.isnan(v) else float(v)


def _chain(u, expiry, since):
    return read_sql("SELECT trade_date, option_type, strike, settle, oi, underlying_price FROM fno_bhav "
                    "WHERE symbol = ? AND instrument_type = 'IDO' AND expiry_date = ? AND trade_date >= ? "
                    "AND settle > 0", params=[u, expiry, since])


def atm_iv(sl, F, T):
    """Mean IV of the call and put at the strike nearest F in one day's chain (the ±SD lines)."""
    if sl.empty or T <= 0:
        return None
    k = float(sl.strike.iloc[(sl.strike - F).abs().argmin()])
    ivs = [_iv(float(sl[(sl.strike == k) & (sl.option_type == o)].settle.iloc[0]), F, k, T, o[0])
           for o in ("CE", "PE") if not sl[(sl.strike == k) & (sl.option_type == o)].empty]
    ivs = [v for v in ivs if v]
    return float(np.mean(ivs)) if ivs else None


def oi_by_strike(sl, F):
    """[{K, call, put}] open interest within OI_BAND of F, from one day's chain."""
    s = sl[(sl.strike - F).abs() <= OI_BAND * F]
    p = s.pivot_table(index="strike", columns="option_type", values="oi", aggfunc="sum").fillna(0)
    return [{"K": float(k), "call": int(r.get("CE", 0)), "put": int(r.get("PE", 0))} for k, r in p.iterrows()]


def paper(r):
    """One paper trade (an option_book.page_data row) → the builder's view, per lot:
    legs_naked / legs_winged with entry (settle on the entry day), now (latest settle, or the
    intrinsic value once settled) and IV at entry; cost_pts per lot for each variant."""
    u, e, t0, F, lot = r["underlying"], r["expiry"], r["entry_date"], r["forward"], r["lot"]
    ch = _chain(u, e, t0)
    start, end = close_ts(t0), close_ts(e)
    T = years(start, end)
    day0 = ch[ch.trade_date == t0]
    last_day = ch.trade_date.max() if not ch.empty else t0
    last = ch[ch.trade_date == last_day]
    settled = r["status"] == "SETTLED" and r.get("settle_index") is not None
    spot = r["settle_index"] if settled else (float(last.underlying_price.iloc[0]) if not last.empty
                                              and last.underlying_price.iloc[0] else F)

    T_last = years(close_ts(last_day), end)

    def leg(cp, K, side, entry):
        # IV from the latest settle while open (the builder then agrees with the mark at the default point),
        # from the entry price once settled
        iv = None
        if settled:
            now = max(spot - K, 0.0) if cp == "C" else max(K - spot, 0.0)
        else:
            m = last[(last.strike == K) & (last.option_type == cp + "E")]
            now = float(m.settle.iloc[0]) if not m.empty else None
            iv = _iv(now, spot, K, T_last, cp) if now else None
        return {"cp": cp, "K": float(K), "side": side, "entry": float(entry), "now": now,
                "iv": iv or _iv(float(entry), F, K, T, cp)}

    shorts = [leg("P", r["short_put"], -1, r["put_entry"]), leg("C", r["short_call"], -1, r["call_entry"])]
    out = {"key": f"{u}:{e}", "underlying": u, "expiry": e, "entry_date": t0, "status": r["status"],
           "lot": lot, "forward": F, "spot": spot, "spot_date": e if settled else last_day, "r": R,
           "step": STEP.get(u, 50), "start": start.isoformat(), "end": end.isoformat(),
           "now": (end if settled else min(max(close_ts(last_day), start), end)).isoformat(),
           "atm_iv": (None if settled else atm_iv(last, spot, T_last)) or atm_iv(day0, F, T), "legs_naked": shorts, "cost_naked": r["entry_cost_pts"],
           "oi": oi_by_strike(last, spot), "oi_date": last_day,
           "margin_naked": {k: r.get(k) for k in ("span_rs", "exposure_rs", "expiry_extra_rs", "expiry_margin_rs")},
           "pnl_naked": r["net_rs"] if settled else (r["mark"] or {}).get("mtm_rs"),
           "settle_index": r.get("settle_index"), "margin_source": r.get("margin_source")}
    if r.get("w_call") is not None:
        pc = day0[(day0.strike == r["w_call"]) & (day0.option_type == "CE")].settle
        pp = day0[(day0.strike == r["w_put"]) & (day0.option_type == "PE")].settle
        if not pc.empty and not pp.empty:
            wings = [leg("P", r["w_put"], 1, pp.iloc[0]), leg("C", r["w_call"], 1, pc.iloc[0])]
            out.update({"legs_winged": [wings[0]] + shorts + [wings[1]],
                        "cost_winged": r["entry_cost_pts"] + r["w_cost_pts"] - float(pc.iloc[0]) - float(pp.iloc[0]),
                        "margin_winged": {"span_rs": r.get("w_span_rs"), "exposure_rs": r.get("w_exposure_rs"),
                                          "expiry_extra_rs": r.get("w_extra_rs"),
                                          "expiry_margin_rs": r.get("w_expiry_margin_rs")},
                        "pnl_winged": r.get("w_pnl"), "max_loss_winged": r.get("w_max_loss_rs")})
    return out


def _spot(u, quote):
    """The freshest index level the cockpit holds: the 15:01 sizing quote, else the last EOD chain."""
    m = ((quote or {}).get("markets") or {}).get(u) or {}
    if m.get("spot"):
        return float(m["spot"]), quote["at"]
    s = read_sql("SELECT trade_date, underlying_price FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                 "AND trade_date = (SELECT MAX(trade_date) FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO') "
                 "AND underlying_price > 0 LIMIT 1", params=[u, u])
    return (float(s.underlying_price.iloc[0]), close_ts(s.trade_date.iloc[0]).isoformat()) if not s.empty else (None, None)


def live(L):
    """The open live legs (options_live.page_data) → one view per (underlying, expiry, source):
    qty in units (+ long, − short), entry = average fill, now = the last mark, IV from the mark."""
    groups = {}
    for l in L.get("open") or []:
        if l.get("net_qty"):
            groups.setdefault((l["underlying"], l["expiry"], l["source"]), []).append(l)
    quote = (L.get("sizing") or {}).get("quote")
    out = []
    for (u, e, src), g in sorted(groups.items()):
        spot, spot_at = _spot(u, quote)
        end = close_ts(e)
        marks = [l["mark_at"] for l in g if l.get("mark_at")]
        start = datetime.fromisoformat(max(marks)) if marks else datetime.now(timezone.utc)
        start = min(start, end)
        T = years(start, end)
        legs_ = []
        for l in sorted(g, key=lambda x: x["strike"]):
            cp, side = l["option_type"][0], 1 if l["net_qty"] > 0 else -1
            entry = l["buy_avg"] if side > 0 else l["sell_avg"]
            legs_.append({"cp": cp, "K": float(l["strike"]), "side": side, "qty": abs(int(l["net_qty"])),
                          "entry": entry, "now": l.get("mark_price"), "symbol": l["tradingsymbol"],
                          "lot": l.get("lot"), "mtm_rs": l.get("mtm_rs"),
                          "iv": _iv(l.get("mark_price"), spot, l["strike"], T, cp) if spot else None})
        ivs = [x["iv"] for x in legs_ if x["iv"]]
        ch = _chain(u, e, (end - timedelta(days=10)).date().isoformat())
        last = ch[ch.trade_date == ch.trade_date.max()] if not ch.empty else ch
        out.append({"key": f"{u}:{e}:{src}", "underlying": u, "expiry": e, "source": src, "spot": spot,
                    "spot_at": spot_at, "r": R, "step": STEP.get(u, 50), "start": start.isoformat(),
                    "end": end.isoformat(), "now": start.isoformat(), "legs": legs_,
                    "cost_rs": sum(l.get("charges_rs") or 0 for l in g),
                    "atm_iv": (atm_iv(last, spot, years(close_ts(last.trade_date.iloc[0]), end)) if not last.empty and spot
                               else None) or (float(np.median(ivs)) if ivs else None),
                    "oi": oi_by_strike(last, spot) if spot and not last.empty else [],
                    "oi_date": ch.trade_date.max() if not ch.empty else None,
                    "margin_rs": next((l.get("mark_margin_rs") or l.get("margin_rs") for l in g
                                       if l.get("mark_margin_rs") or l.get("margin_rs")), None),
                    "mtm_rs": sum(l.get("mtm_rs") or 0 for l in g), "mark_at": max(marks) if marks else None,
                    "entry_date": min((l["entry_date"] for l in g if l.get("entry_date")), default=None)})
    return out

