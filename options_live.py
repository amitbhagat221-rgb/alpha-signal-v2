"""
Alpha Signal v2 — option premium, live on Kite (plan 0029).

Runs plan 0022's rule (sell a ~0.05-delta NIFTY / SENSEX strangle 2 sessions before the weekly
expiry, held to expiry) through Kite Connect, plus the Tuesday rotation: NIFTY is bought back at
15:08-15:15 IST so its margin carries the SENSEX entry at 15:17.

One step per cron line (`run.sh options_live <step> [NIFTY|SENSEX]`), each logged to run_events:

    entry      guards → front expiry → live chain ±8% → option_book's 0.05-delta strikes on live mids →
               Kite basket margin per lot + available margin → lots → orders (or a shadow fill / a ticket).
               With wing_pct > 0 the wings (a CE / PE that % of spot beyond each short strike) are BOUGHT first,
               the strangle is sold on the lots both wings filled, and the basket margin is the hedged one.
               Long wings are never bought back: they block no margin and expire on their own.
    buyback    Tue: BUY back the tagged NIFTY legs expiring today; confirm flat + margin freed → rotation flag
    closeall   Stop + buy back every tagged leg now (the cockpit's Close-all)
    record     after the close: today's Kite trades (tagged and manual NIFTY/SENSEX option legs) → ledger
    mark       open legs at live mids (fno_bhav settle without a login) + Kite margin of what is open
    settle     expired legs at the index settlement (option_book.intrinsic + charges)
    reconcile  broker positions vs ledger; a mismatch sets the kill switch and fails the step
    precheck   on a trading day with work to do and no Kite login: push "log in to Kite"
    weekly     the week's P&L push
    plan       read-only: what `entry` would do now (strikes, margin, lots). Writes nothing.
    quote      read-only Kite: per-lot margin naked / winged etc. for the /options sizing choices
               (also taken by every mark while logged in)

Modes (config.OPTIONS_LIVE, overridden by option_live_settings): off · shadow (live quotes, simulated
fills at the bid/ask, nothing sent) · approve (a ticket + push; orders only after Amit taps Approve on
the ops cockpit before `approve_by`) · auto. Only approve / auto ever call place / modify / cancel,
and only through `call()`, which refuses a broker write unless the order loop opened it.

Every order is a tagged LIMIT order (`tag`), never MARKET: placed at the touch (bid to sell, ask to
buy), re-pegged to the touch every `reprice_every_s` (a sell never below `min_sell_frac` of its first
mid, a buy never above `max_buy_mult` of its first ask until the final aggressive limit), leftovers
cancelled at the cut-off. Above the exchange freeze quantity an order goes as iceberg slices.

Tables: option_live_orders (every event, append-only), option_live_trades (the ledger, rebuilt from
the fill events), option_live_settings (settings + state). Reads fno_bhav, market_holidays.

    python -m options_live plan --underlying NIFTY
    python -m options_live entry --underlying NIFTY
    python -m options_live set mode '"shadow"'        # a JSON value
    python -m options_live show
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
import time
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import option_book as ob
import runlog
from config import OPS_HTTPS, OPTIONS_LIVE
from db import SCHEMA_PATH, get_db, read_sql, upsert_df
from sources import _http
from sources import kite_quotes as kq
from sources.kite_pull import LOGIN_PAGE, NoKiteSession

IST = ZoneInfo("Asia/Kolkata")
MARKETS = {u: {"exchange": ex, "spot": key} for u, ex, key in kq.MARKETS}
MODES = ("off", "shadow", "approve", "auto")
LIVE_MODES = ("approve", "auto")
EDITABLE = ("mode", "lots_cap", "margin_buffer_rs", "weekly_loss_limit_rs", "kill", "adopt_manual_nifty",
            "vix_halt", "vix_halve", "wing_pct")
FINAL = ("COMPLETE", "CANCELLED", "REJECTED")
WRITE_CALLS = ("place_order", "modify_order", "cancel_order")
TICK = ob.TICK
PAGE = OPS_HTTPS + "/options#live"
ORDER_COLS = ("at", "trade_date", "step", "mode", "source", "underlying", "expiry", "ticket_id", "event",
              "exchange", "tradingsymbol", "option_type", "strike", "lot", "transaction_type", "variety",
              "quantity", "price", "order_id", "trade_id", "status", "filled_qty", "avg_price", "detail")


# ─────────────────────────── tables, settings, state ───────────────────────────

def ensure_tables():
    """Create this module's three tables on a DB that predates them (the schema.sql block)."""
    s = SCHEMA_PATH.read_text()
    block = s[s.index("-- options_live:begin"): s.index("-- options_live:end")]
    with get_db() as c:
        c.executescript(block)


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _rows(sql, params=()):
    """read_sql that reads a missing table as empty (the cockpit runs before ensure_tables)."""
    try:
        return read_sql(sql, params=list(params))
    except Exception as e:                          # noqa: BLE001
        if "no such table" in str(e):
            return pd.DataFrame()
        raise


def _clean(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else v


def get_state(key, default=None):
    df = _rows("SELECT value FROM option_live_settings WHERE key = ?", [key])
    return default if df.empty else json.loads(df["value"].iloc[0])


def put_state(key, value, by):
    with get_db() as c:
        c.execute("INSERT INTO option_live_settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?) "
                  "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, "
                  "updated_by = excluded.updated_by", (key, json.dumps(value, default=str), _utc(), by))
    runlog.count_write("option_live_settings", 1)


def settings():
    """config.OPTIONS_LIVE with the option_live_settings overrides applied."""
    s = copy.deepcopy(OPTIONS_LIVE)
    df = _rows(f"SELECT key, value FROM option_live_settings WHERE key IN ({','.join('?' * len(EDITABLE))})", EDITABLE)
    for k, v in zip(df.get("key", []), df.get("value", [])):
        v = json.loads(v)
        s[k] = {**s[k], **v} if k == "lots_cap" else v
    s["kill"] = bool(s["kill"])
    s["kill_reason"] = get_state("kill_reason") if s["kill"] else None
    return s


def set_setting(key, value, by="cli"):
    """Validate and store one override. Raises ValueError on a bad key or value."""
    if key not in EDITABLE:
        raise ValueError(f"not a setting: {key} (one of {', '.join(EDITABLE)})")
    if key == "mode" and value not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if key == "lots_cap":
        if not isinstance(value, dict) or set(value) - set(MARKETS):
            raise ValueError(f"lots_cap is {{underlying: lots}} for {sorted(MARKETS)}")
        for u, n in value.items():
            if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= OPTIONS_LIVE["lots_hard_max"]:
                raise ValueError(f"lots_cap[{u}] must be a whole number 0-{OPTIONS_LIVE['lots_hard_max']}")
        value = {**settings()["lots_cap"], **value}
    if key in ("margin_buffer_rs", "weekly_loss_limit_rs"):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise ValueError(f"{key} must be a number ≥ 0")
    if key in ("kill", "adopt_manual_nifty") and not isinstance(value, bool):
        raise ValueError(f"{key} must be true or false")
    if key in ("vix_halt", "vix_halve"):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= 100:
            raise ValueError(f"{key} must be a VIX level between 0 and 100")
        cur = settings()
        halt, halve = (value, cur["vix_halve"]) if key == "vix_halt" else (cur["vix_halt"], value)
        if halve > halt:
            raise ValueError(f"vix_halve ({halve}) must not be above vix_halt ({halt})")
    if key == "wing_pct":
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= value <= 5:
            raise ValueError("wing_pct must be a % of spot between 0 (off) and 5")
    put_state(key, value, by)
    return value


def set_kill(on, reason, by):
    put_state("kill", bool(on), by)
    put_state("kill_reason", reason if on else None, by)


# ─────────────────────────── context, clock, broker door ───────────────────────────

def _real_kite():
    from sources.kite_pull import kite
    return kite(cached_only=True)                   # NoKiteSession without today's login


def make_ctx(step, kite=None, now=None, wait=None, push=None):
    """Everything a step touches outside the DB: the Kite client factory, the clock, the push.
    Tests pass a fake client and a fake clock; nothing else changes."""
    s = settings()
    clock = now or (lambda: datetime.now(IST))
    return {"step": step, "settings": s, "mode": s["mode"], "now": clock, "today": clock().date().isoformat(),
            "wait": wait or time.sleep, "push": push or notify, "kite": kite or _real_kite, "kc": None,
            "may_write": False, "pushes": []}


def client(ctx):
    if ctx["kc"] is None:
        ctx["kc"] = ctx["kite"]()
    return ctx["kc"]


def call(ctx, name, *a, **kw):
    """Every Kite call: through the host door, and a broker write only inside the order loop."""
    if name in WRITE_CALLS and not ctx.get("may_write"):
        raise RuntimeError(f"options_live: {name} refused outside the order loop (mode {ctx['mode']})")
    kc = client(ctx)
    with _http.pace("kite"):
        return getattr(kc, name)(*a, **kw)


def has_session(ctx):
    try:
        call(ctx, "profile")
        return True
    except Exception as e:                          # noqa: BLE001 — NoKiteSession or an expired token
        print(f"options_live: no Kite session ({type(e).__name__}: {e})")
        return False


def _at(ctx, hhmm):
    h, m = map(int, hhmm.split(":"))
    return ctx["now"]().replace(hour=h, minute=m, second=0, microsecond=0)


def notify(text, urgent=False):
    import os
    from sources.kite_pull import _secret_from_file
    from tools.health_report import send_ntfy
    if not os.environ.get("NTFY_TOPIC") and _secret_from_file("NTFY_TOPIC"):    # the cockpit's Close-all child
        os.environ["NTFY_TOPIC"] = _secret_from_file("NTFY_TOPIC")
    return send_ntfy(text, urgent=urgent, click=PAGE)


def push(ctx, text, urgent=False):
    label = {"shadow": "SHADOW", "approve": "APPROVE", "auto": "LIVE"}.get(ctx["mode"], ctx["mode"].upper())
    msg = f"Options {label}: {text}"
    ctx["pushes"].append(msg)
    runlog.note(f"push: {msg}", level="WARN" if urgent else "INFO")
    print(f"  push → {msg}")
    ctx["push"](msg, urgent=urgent)


def outcome(ctx, u, status, detail, msg=None, urgent=False):
    """Record a step's result (state for the health check + a run_events note) and push."""
    if status != "idle":
        put_state(f"step:{ctx['step']}:{u}", {"at": _utc(), "date": ctx["today"], "status": status,
                                              "detail": detail, "mode": ctx["mode"]}, ctx["step"])
    level = {"ok": "INFO", "idle": "INFO", "skipped": "WARN", "failed": "ERROR"}[status]
    runlog.note(f"options_live {ctx['step']} {u}: {status} — {detail}", level=level)
    print(f"options_live {ctx['step']} {u}: {status} — {detail}")
    if msg:
        push(ctx, msg, urgent=urgent)
    return {"status": status, "detail": detail}


def log_event(ctx, event, **f):
    row = {"at": _utc(), "trade_date": ctx["today"], "step": ctx["step"], "mode": ctx["mode"], "event": event, **f}
    if isinstance(row.get("detail"), (dict, list)):
        row["detail"] = json.dumps(row["detail"], default=str)
    cols = [c for c in ORDER_COLS if c in row]
    with get_db() as c:
        n = c.execute(f"INSERT OR IGNORE INTO option_live_orders ({', '.join(cols)}) "
                      f"VALUES ({', '.join('?' * len(cols))})", [_clean(row[k]) for k in cols]).rowcount
    runlog.count_write("option_live_orders", n)
    return n


def _rs(x, sign=False):
    """₹ with the sign in front: -₹930, +₹1,200 (never ₹-930)."""
    return ("-" if x < 0 else "+" if sign and x > 0 else "") + f"₹{abs(x):,.0f}"


def _leg_fields(leg):
    return {k: leg.get(k) for k in ("underlying", "expiry", "exchange", "tradingsymbol", "option_type", "strike", "lot")}


# ─────────────────────────── pure rules (unit-tested) ───────────────────────────

def size_lots(cap, available, buffer, margin_per_lot):
    """Whole lots: min(cap, floor((available − buffer) / margin per lot)), never below 0."""
    if not margin_per_lot or margin_per_lot <= 0:
        raise ValueError(f"no usable Kite margin per lot ({margin_per_lot})")
    return max(0, min(int(cap), math.floor((available - buffer) / margin_per_lot)))


def slices(qty, lot, freeze):
    """The orders that carry `qty` units: one regular order up to the freeze quantity; above it,
    iceberg orders of 2-10 legs, each leg a whole number of lots and ≤ the freeze quantity."""
    leg_max = max(lot, (int(freeze) // lot) * lot)
    if qty <= freeze:
        return [{"variety": "regular", "quantity": int(qty)}]
    out, left = [], int(qty)
    while left > 0:
        q = min(left, 10 * leg_max)
        if q <= freeze:
            out.append({"variety": "regular", "quantity": q})
        else:
            legs = math.ceil(q / leg_max)
            out.append({"variety": "iceberg", "quantity": q, "legs": legs,
                        "leg_qty": math.ceil(q / legs / lot) * lot})
        left -= q
    return out


def _tick_down(x):
    return round(math.floor(x / TICK + 1e-9) * TICK, 2)


def _tick_up(x):
    return round(math.ceil(x / TICK - 1e-9) * TICK, 2)


def target_price(side, quote, first, s, aggressive=False):
    """The limit for one re-price. SELL: the bid, never below min_sell_frac × the first mid.
    BUY: the ask, never above max_buy_mult × the first ask — except the final aggressive limit,
    ask × (1 + final_buy_pct) + final_buy_ticks ticks. None = no price to go to (no quote)."""
    bid, ask, last = quote
    if side == "SELL":
        if not bid:
            return None
        floor = _tick_up(max(TICK, s["min_sell_frac"] * (first.get("mid") or bid)))
        return max(_tick_down(bid), floor)
    ref = ask
    if not ref and aggressive:                      # no offer: the final limit still goes out, off the last known price
        ref = max([x for x in (last, bid, first.get("ask")) if x], default=None)
    if not ref:
        return None
    if aggressive:
        return _tick_up(ref * (1 + s["final_buy_pct"]) + s["final_buy_ticks"] * TICK)
    cap = first.get("ask") or ref
    return min(_tick_up(ref), _tick_down(max(TICK, s["max_buy_mult"] * cap)))


# ─────────────────────────── ledger ───────────────────────────

LEDGER_KEY = ["underlying", "expiry", "tradingsymbol", "source"]


def rebuild_ledger():
    """option_live_trades from the fill events. An order's own summary fill ('order:<id>') stands
    only until its real Kite trades are recorded. A SETTLED leg keeps its settlement."""
    ev = _rows("SELECT * FROM option_live_orders WHERE event IN ('fill', 'shadow_fill', 'seed') ORDER BY event_id")
    if ev.empty:
        return 0
    tid = ev["trade_id"].fillna("")
    real = set(ev.loc[(ev.event == "fill") & ~tid.str.startswith("order:"), "order_id"].dropna())
    ev = ev[~((ev.event == "fill") & tid.str.startswith("order:") & ev.order_id.isin(real))]
    have = _rows("SELECT underlying, expiry, tradingsymbol, source, status FROM option_live_trades")
    settled = {tuple(r) for r in have[have.status == "SETTLED"][LEDGER_KEY].itertuples(index=False)} if not have.empty else set()
    live_rows, settled_rows = [], []
    for key, g in ev.groupby(LEDGER_KEY, dropna=False):
        sells, buys = g[g.transaction_type == "SELL"], g[g.transaction_type == "BUY"]
        sq, bq = int(sells.quantity.sum()), int(buys.quantity.sum())
        sv, bv = float((sells.quantity * sells.price).sum()), float((buys.quantity * buys.price).sum())
        charges, n_orders = 0.0, 0
        for (side, oid), o in g[g.event != "seed"].assign(oid=g.order_id.fillna(g.trade_id)).groupby(["transaction_type", "oid"]):
            q = int(o.quantity.sum())
            if q:
                avg = float((o.quantity * o.price).sum()) / q
                charges += ob.charges_pts(avg, side.lower(), q, o.trade_date.min()) * q
                n_orders += 1
        first = g.iloc[0]
        row = dict(zip(LEDGER_KEY, key), exchange=first.exchange, option_type=first.option_type, strike=first.strike,
                   lot=_clean(first.lot), entry_date=g.trade_date.min(), ticket_id=_clean(g.ticket_id.dropna().iloc[0]) if g.ticket_id.notna().any() else None,
                   sell_qty=sq, sell_avg=sv / sq if sq else None, buy_qty=bq, buy_avg=bv / bq if bq else None,
                   net_qty=bq - sq, n_orders=n_orders, charges_rs=charges, updated_at=_utc())
        if tuple(key) in settled:                   # status rides along: the upsert's INSERT half checks NOT NULL
            settled_rows.append({**row, "status": "SETTLED"})
            continue
        flat = row["net_qty"] == 0
        row.update(status="CLOSED" if flat else "OPEN", gross_rs=sv - bv if flat else None,
                   net_rs=sv - bv - charges if flat else None, closed_at=g.trade_date.max() if flat else None)
        live_rows.append(row)
    n = 0
    for rows in (live_rows, settled_rows):
        if rows:
            n += upsert_df(pd.DataFrame(rows), "option_live_trades")
    return n


def legs(where="1 = 1", params=()):
    df = _rows(f"SELECT * FROM option_live_trades WHERE {where} ORDER BY expiry, underlying, option_type", params)
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict("records")]


def _set_margin(u, e, source, margin):
    with get_db() as c:
        c.execute("UPDATE option_live_trades SET margin_rs = ? WHERE underlying = ? AND expiry = ? AND source = ?",
                  (margin, u, e, source))


def family(ctx):
    """The ledger source this mode trades: simulated legs in shadow, tagged real legs otherwise."""
    return "shadow" if ctx["mode"] == "shadow" else "live"


def week_realised(today, source):
    monday = (date.fromisoformat(today) - timedelta(days=date.fromisoformat(today).weekday())).isoformat()
    df = _rows("SELECT SUM(net_rs) AS s FROM option_live_trades WHERE status IN ('CLOSED', 'SETTLED') "
               "AND closed_at >= ? AND source = ?", [monday, source])
    return float(df["s"].iloc[0]) if not df.empty and pd.notna(df["s"].iloc[0]) else 0.0


# ─────────────────────────── broker reads ───────────────────────────

def _order(exchange, sym, qty, side="SELL"):
    return {"exchange": exchange, "tradingsymbol": sym, "transaction_type": side, "variety": "regular",
            "product": "NRML", "order_type": "MARKET", "quantity": int(qty), "price": 0, "trigger_price": 0}


def _basket_total(ctx, orders):
    if not orders:
        return 0.0
    m = call(ctx, "basket_order_margins", orders, consider_positions=False, mode="compact")
    total = (m.get("final") or m.get("initial") or {}).get("total")
    if total is None:
        raise RuntimeError(f"Kite basket margin returned no total: {m}")
    return float(total)


def basket_margin(ctx, legs_, lots):
    """Kite's margin for `lots` of `legs_` (a leg's `side` is SELL unless it says BUY): long wings first,
    as they are placed, so the basket carries the hedge benefit."""
    legs_ = sorted(legs_, key=lambda l: l.get("side", "SELL") != "BUY")
    return _basket_total(ctx, [_order(l["exchange"], l["tradingsymbol"], lots * l["lot"], l.get("side", "SELL"))
                               for l in legs_])


def peak_available(ctx, e, avail):
    """Free margin on expiry day `e`, before the new trade. Kite checks only today's margin when the
    order goes in; the peak comes later, after positions expiring before `e` have released theirs
    (e.g. NIFTY legs expiring today, while SENSEX expires Thursday). So: today's free margin
    + what those positions block (basket margin of all open option legs − of the ones still open on `e`)
    − their settlement at today's index (intrinsic value of the short legs)
    − the expiry-day extra of short legs that expire on `e` too.
    No credit (returns `avail`) when a derivative position is not a NIFTY/SENSEX option, or a long
    leg expiring before `e` may hedge a short that stays (same index): the release could not be worked
    out safely. A long wing leaving with its own shorts (Tuesday's NIFTY wings) is fine; its value is not credited.
    → {"available": ₹, "freed": ₹, "stay_extra": ₹, "note": text}"""
    pos = {}
    for p in call(ctx, "positions").get("net", []):
        q = int(p.get("quantity") or 0)
        if q and p.get("exchange") in ("NFO", "BFO"):
            pos[p["tradingsymbol"]] = pos.get(p["tradingsymbol"], 0) + q
    pos = {k: q for k, q in pos.items() if q}
    none = {"available": avail, "freed": 0.0, "stay_extra": 0.0}
    if not pos:
        return none | {"note": "no open F&O positions"}
    inst = option_instruments(ctx)
    other = sorted(k for k in pos if k not in inst)
    if other:
        return none | {"note": f"no credit: {', '.join(other)} is not a NIFTY/SENSEX option"}
    leave = {k: q for k, q in pos.items() if inst[k]["expiry"] < e}
    stay = {k: q for k, q in pos.items() if k not in leave}
    if any(q > 0 and any(inst[s]["underlying"] == inst[k]["underlying"] and qs < 0 for s, qs in stay.items())
           for k, q in leave.items()):
        return none | {"note": "no credit: a long leg expires first while a short on its index stays"}
    keys = {u: MARKETS[u]["spot"] for u in {inst[k]["underlying"] for k in pos}}
    ltp = call(ctx, "ltp", sorted(keys.values()))
    spot = {u: float(ltp[key]["last_price"]) for u, key in keys.items()}

    def orders(d):
        return [_order(inst[k]["exchange"], k, abs(q), "SELL" if q < 0 else "BUY") for k, q in d.items()]

    def intrinsic(k):
        i, S = inst[k], spot[inst[k]["underlying"]]
        return max(0.0, S - i["strike"]) if i["option_type"] == "CE" else max(0.0, i["strike"] - S)

    freed = 0.0
    if leave:
        settle = sum(-q * intrinsic(k) for k, q in leave.items() if q < 0)
        freed = max(0.0, _basket_total(ctx, orders(pos)) - _basket_total(ctx, orders(stay)) - settle)
    stay_extra = sum(ob.EXPIRY_ELM_PCT * spot[inst[k]["underlying"]] * abs(q)
                     for k, q in stay.items() if q < 0 and inst[k]["expiry"] == e)
    return {"available": avail + freed - stay_extra, "freed": freed, "stay_extra": stay_extra,
            "note": f"{len(leave)} leg(s) expire before {e} and free ₹{freed:,.0f}"
                    + (f"; legs also expiring {e} add ₹{stay_extra:,.0f} that day" if stay_extra else "")}


def available(ctx):
    m = call(ctx, "margins", "equity")
    return float(m["net"])


def snapshot_margin(ctx):
    """Kite's equity margin → state 'margin' for the Live panel: used (utilised debits: SPAN + exposure +
    premium + M2M), free (net) and total (used + free)."""
    m = call(ctx, "margins", "equity")
    u, a = m.get("utilised") or {}, m.get("available") or {}
    free, used = float(m["net"]), float(u.get("debits") or 0)
    snap = {"at": _utc(), "free": free, "used": used, "total": free + used,
            "span": float(u.get("span") or 0), "exposure": float(u.get("exposure") or 0),
            "cash": float(a.get("cash") or 0) + float(a.get("intraday_payin") or 0),   # opening cash + today's pay-in
            "collateral": float(a.get("collateral") or 0)}
    put_state("margin", snap, ctx["step"])
    return snap


def india_vix(ctx):
    """India VIX at entry → (level, where from): Kite's live quote, else the stored close if it is at most
    vix_max_age_days old, else (None, why) — the VIX guard then halts the entry."""
    try:
        v = call(ctx, "ltp", ["NSE:INDIA VIX"])["NSE:INDIA VIX"]["last_price"]
        if v:
            return float(v), "Kite live"
    except Exception as ex:                         # noqa: BLE001 — fall back to the stored close
        print(f"options_live: no live India VIX ({type(ex).__name__}: {ex})")
    df = read_sql("SELECT date, value FROM macro_history WHERE indicator_id = 'india_vix' AND value > 0 "
                  "ORDER BY date DESC LIMIT 1")
    if df.empty:
        return None, "no India VIX stored"
    d = df["date"].iloc[0]
    if (date.fromisoformat(ctx["today"]) - date.fromisoformat(d)).days > ctx["settings"]["vix_max_age_days"]:
        return None, f"last stored India VIX is from {d}"
    return float(df["value"].iloc[0]), f"close {d}"


def vix_guard(s, vix, lots):
    """(lots, action): halt at VIX ≥ vix_halt or when VIX is unknown; half the lots (at least 1) above vix_halve."""
    if vix is None or vix >= s["vix_halt"]:
        return 0, "halt"
    if vix > s["vix_halve"]:
        return (max(1, lots // 2) if lots else 0), "halve"
    return lots, "normal"


def quotes(ctx, legs_):
    keys = [f"{l['exchange']}:{l['tradingsymbol']}" for l in legs_]
    q = call(ctx, "quote", keys) if keys else {}
    return {k.split(":", 1)[1]: kq.touch(v) for k, v in q.items()}


def option_instruments(ctx):
    """{tradingsymbol: leg fields} for every live NIFTY / SENSEX option on Kite."""
    out = {}
    for u, m in MARKETS.items():
        for r in call(ctx, "instruments", m["exchange"]):
            if r.get("name") == u and r.get("instrument_type") in ("CE", "PE"):
                out[r["tradingsymbol"]] = {"underlying": u, "expiry": str(r["expiry"]), "exchange": m["exchange"],
                                           "tradingsymbol": r["tradingsymbol"], "option_type": r["instrument_type"],
                                           "strike": float(r["strike"]), "lot": int(r["lot_size"])}
    return out


def broker_positions(ctx):
    """{tradingsymbol: net units} across products, from Kite positions (net)."""
    out = {}
    for p in call(ctx, "positions").get("net", []):
        out[p["tradingsymbol"]] = out.get(p["tradingsymbol"], 0) + int(p.get("quantity") or 0)
    return out


# ─────────────────────────── the order loop ───────────────────────────

def _refresh(ctx, book):
    if not book:
        return
    by_id = {str(o["order_id"]): o for o in call(ctx, "orders")}
    for b in book:
        if b["done"] or b["order_id"] is None:
            continue
        o = by_id.get(b["order_id"])
        if not o:
            continue
        status, filled = o.get("status"), int(o.get("filled_quantity") or 0)
        if status != b["status"] or filled != b["filled"]:
            ev = "reject" if status == "REJECTED" else "partial" if 0 < filled < b["quantity"] and status not in FINAL else "status"
            log_event(ctx, ev, source=b["source"], ticket_id=b["ticket_id"], **_leg_fields(b["leg"]),
                      transaction_type=b["side"], variety=b["variety"], quantity=b["quantity"], price=b["price"],
                      order_id=b["order_id"], status=status, filled_qty=filled, avg_price=o.get("average_price"),
                      detail=o.get("status_message"))
        b.update(status=status, filled=filled, avg=o.get("average_price"), done=status in FINAL)
        if status == "REJECTED":
            b["reject"] = o.get("status_message") or "rejected"


def work_orders(ctx, legs_, side, deadline, final_at=None, ticket_id=None, source="live"):
    """Place, re-price and finish LIMIT orders for `legs_` (each with `qty` units). Returns
    {tradingsymbol: {"filled": units, "avg": price, "rejects": [...]}} after cancelling what is
    left at `deadline`. `final_at`: from then on a BUY goes at the final aggressive limit."""
    s = ctx["settings"]
    first = quotes(ctx, legs_)
    book = []
    ctx["may_write"] = True
    try:
        for leg in legs_:
            q = first.get(leg["tradingsymbol"], (None, None, None))
            ref = {"mid": (q[0] + q[1]) / 2 if q[0] and q[1] else q[2] or leg.get("mid"), "ask": q[1] or leg.get("ask")}
            leg["_first"] = ref
            px = target_price(side, q, ref, s, aggressive=bool(final_at and ctx["now"]() >= final_at))
            if px is None:
                log_event(ctx, "error", source=source, ticket_id=ticket_id, **_leg_fields(leg), transaction_type=side,
                          quantity=leg["qty"], detail=f"no {'bid' if side == 'SELL' else 'ask'} to price against")
                book.append({"leg": leg, "order_id": None, "quantity": leg["qty"], "filled": 0, "avg": None, "done": True,
                             "status": "NOQUOTE", "side": side, "variety": "regular", "price": None, "source": source,
                             "ticket_id": ticket_id, "reject": "no quote"})
                continue
            for sl in slices(leg["qty"], leg["lot"], leg["freeze"]):
                params = dict(variety=sl["variety"], exchange=leg["exchange"], tradingsymbol=leg["tradingsymbol"],
                              transaction_type=side, quantity=sl["quantity"], product="NRML", order_type="LIMIT",
                              price=px, validity="DAY", tag=s["tag"])
                if sl["variety"] == "iceberg":
                    params.update(iceberg_legs=sl["legs"], iceberg_quantity=sl["leg_qty"])
                b = {"leg": leg, "order_id": None, "quantity": sl["quantity"], "filled": 0, "avg": None, "done": False,
                     "status": None, "side": side, "variety": sl["variety"], "price": px, "source": source,
                     "ticket_id": ticket_id}
                try:
                    b["order_id"] = str(call(ctx, "place_order", **params))
                    log_event(ctx, "place", source=source, ticket_id=ticket_id, **_leg_fields(leg), transaction_type=side,
                              variety=sl["variety"], quantity=sl["quantity"], price=px, order_id=b["order_id"],
                              detail={k: v for k, v in params.items() if k.startswith("iceberg")} or None)
                except Exception as e:              # noqa: BLE001 — a rejected placement is recorded, not raised
                    b.update(done=True, status="REJECTED", reject=f"{type(e).__name__}: {e}")
                    log_event(ctx, "reject", source=source, ticket_id=ticket_id, **_leg_fields(leg), transaction_type=side,
                              variety=sl["variety"], quantity=sl["quantity"], price=px, detail=b["reject"])
                book.append(b)
        aggressive = bool(final_at and ctx["now"]() >= final_at)
        while True:
            _refresh(ctx, book)
            if all(b["done"] for b in book) or ctx["now"]() >= deadline:
                break
            ctx["wait"](max(1.0, min(s["reprice_every_s"], (deadline - ctx["now"]()).total_seconds())))
            if ctx["now"]() >= deadline:
                break
            if final_at and not aggressive and ctx["now"]() >= final_at:
                aggressive = True
            open_ = [b for b in book if not b["done"]]
            q = quotes(ctx, [b["leg"] for b in open_])
            for b in open_:
                px = target_price(side, q.get(b["leg"]["tradingsymbol"], (None, None, None)), b["leg"]["_first"], s, aggressive)
                if px is None or abs(px - b["price"]) < TICK / 2:
                    continue
                try:
                    call(ctx, "modify_order", b["variety"], b["order_id"], price=px, order_type="LIMIT")
                    log_event(ctx, "modify", source=source, ticket_id=ticket_id, **_leg_fields(b["leg"]), transaction_type=side,
                              variety=b["variety"], quantity=b["quantity"], price=px, order_id=b["order_id"],
                              detail="final aggressive limit" if aggressive and side == "BUY" else None)
                    b["price"] = px
                except Exception as e:              # noqa: BLE001 — filled meanwhile, or the exchange refused the price
                    log_event(ctx, "error", source=source, ticket_id=ticket_id, **_leg_fields(b["leg"]),
                              order_id=b["order_id"], detail=f"modify: {type(e).__name__}: {e}")
        _refresh(ctx, book)
        for b in book:
            if not b["done"]:
                try:
                    call(ctx, "cancel_order", b["variety"], b["order_id"])
                    log_event(ctx, "cancel", source=source, ticket_id=ticket_id, **_leg_fields(b["leg"]),
                              transaction_type=side, quantity=b["quantity"], order_id=b["order_id"],
                              detail="cut-off: leftover cancelled")
                except Exception as e:              # noqa: BLE001
                    log_event(ctx, "error", source=source, ticket_id=ticket_id, **_leg_fields(b["leg"]),
                              order_id=b["order_id"], detail=f"cancel: {type(e).__name__}: {e}")
        _refresh(ctx, book)
    finally:
        ctx["may_write"] = False
    out = {}
    for b in book:
        sym = b["leg"]["tradingsymbol"]
        o = out.setdefault(sym, {"filled": 0, "value": 0.0, "rejects": [], "leg": b["leg"]})
        if b["filled"]:
            log_event(ctx, "fill", source=source, ticket_id=ticket_id, **_leg_fields(b["leg"]), transaction_type=side,
                      variety=b["variety"], quantity=b["filled"], price=b["avg"], order_id=b["order_id"],
                      trade_id=f"order:{b['order_id']}", status=b["status"], filled_qty=b["filled"], avg_price=b["avg"])
            o["filled"] += b["filled"]
            o["value"] += b["filled"] * float(b["avg"] or 0)
        if b.get("reject"):
            o["rejects"].append(b["reject"])
    for o in out.values():
        o["avg"] = o["value"] / o["filled"] if o["filled"] else None
    return out


def shadow_fill(ctx, legs_, side, ticket_id):
    """Simulated fills at the live touch (bid to sell, ask to buy; the mid or last when that side is empty)."""
    q = quotes(ctx, legs_)
    out = {}
    for leg in legs_:
        bid, ask, last = q.get(leg["tradingsymbol"], (leg.get("bid"), leg.get("ask"), None))
        px = (bid if side == "SELL" else ask) or leg.get("mid") or last
        if not px:
            log_event(ctx, "error", source="shadow", ticket_id=ticket_id, **_leg_fields(leg), detail="shadow: no quote")
            out[leg["tradingsymbol"]] = {"filled": 0, "avg": None, "rejects": ["no quote"], "leg": leg}
            continue
        log_event(ctx, "shadow_fill", source="shadow", ticket_id=ticket_id, **_leg_fields(leg), transaction_type=side,
                  quantity=leg["qty"], price=px, trade_id=f"shadow:{ctx['step']}:{ctx['today']}:{leg['tradingsymbol']}:{side}",
                  detail={"bid": bid, "ask": ask, "last": last})
        out[leg["tradingsymbol"]] = {"filled": leg["qty"], "avg": px, "rejects": [], "leg": leg}
    return out


def _fills_text(res):
    return " + ".join(f"{sym} {o['filled']} @ {o['avg']:.2f}" if o["filled"] else f"{sym} unfilled"
                      for sym, o in res.items())


# ─────────────────────────── entry ───────────────────────────

def due_expiry(u, today, hol):
    """The front expiry when today is its entry day (2 sessions before), else None."""
    if not ob.is_session(date.fromisoformat(today), hol):
        return None
    e = kq.front_expiry(u, today)
    return e if e and ob.entry_day(e, hol) == today else None


def already_entered(ctx, u, e, source):
    n = _rows("SELECT COUNT(*) AS n FROM option_live_orders WHERE underlying = ? AND expiry = ? AND source = ? "
              "AND step = 'entry' AND event IN ('shadow_fill', 'place', 'fill', 'ticket')", [u, e, source])
    if not n.empty and int(n["n"].iloc[0]):
        return "this expiry was already entered (or ticketed) — the order log has it"
    if source == "live":                            # a crash before the DB write: the broker's order book decides
        tag = ctx["settings"]["tag"]
        orders = [o for o in call(ctx, "orders") if tag in ([o.get("tag")] + list(o.get("tags") or []))
                  and str(o.get("tradingsymbol", "")).startswith(u)
                  and not (o.get("status") in ("CANCELLED", "REJECTED") and not o.get("filled_quantity"))]
        this = ({k for k, v in option_instruments(ctx).items() if v["expiry"] == e}
                if any(o.get("transaction_type") == "BUY" for o in orders) else set())
        # a SELL, or a BUY of this expiry (the wings bought just before the sale; a buy-back is an older expiry)
        mine = [o for o in orders if o.get("transaction_type") == "SELL" or o.get("tradingsymbol") in this]
        if mine:
            return f"{len(mine)} tagged {u} order(s) already in today's Kite order book"
    return None


def rotation_gate(ctx):
    """SENSEX may enter only when no short NIFTY leg expiring today is still open (tagged, shadow, or
    adopted manual) and, after a buy-back, its margin was seen freed. Long wings are left to expire:
    they block no margin and carry no risk. → (ok, why)."""
    today, s = ctx["today"], ctx["settings"]
    srcs = [family(ctx)] + (["manual"] if s["adopt_manual_nifty"] and family(ctx) == "live" else [])
    open_ = [l for l in legs("underlying = 'NIFTY' AND expiry = ? AND status = 'OPEN' AND net_qty < 0", [today])
             if l["source"] in srcs]
    if open_:
        return False, f"{len(open_)} short NIFTY leg(s) expiring today still open: the buy-back did not finish"
    r = get_state(f"rotation:{today}")
    if r is None:
        return True, "no NIFTY position expiring today"
    return bool(r.get("ok")), r.get("detail") or ""


def wing_strikes(chain, k, spot, pct):
    """{'C': K, 'P': K}: for each short strike, the strike with an offer nearest `pct` % of spot beyond it
    (at least one strike out). None when pct is 0 (no wings). Raises when a side has no offered strike there."""
    if not pct:
        return None
    out = {}
    for cp, ot, sgn in (("C", "CE", 1), ("P", "PE", -1)):
        c = chain[(chain.option_type == ot) & (sgn * (chain.strike - k[cp]) > 0)
                  & (pd.to_numeric(chain.ask, errors="coerce").fillna(0) > 0)]
        if c.empty:
            raise RuntimeError(f"no offered {ot} beyond {k[cp]:,.0f} for the wing")
        target = k[cp] + sgn * pct / 100 * spot
        out[cp] = float(c.strike.iloc[(c.strike - target).abs().to_numpy().argmin()])
    return out


def pick_legs(ctx, u, e, wing_pct):
    """The rule's strikes on the live chain → (F, spot, short legs, wing legs (empty when wing_pct is 0),
    {'C', 'P'} short strikes, wing strikes or None)."""
    s, m = ctx["settings"], MARKETS[u]
    chain, spot = kq.live_chain(client(ctx), u, m["exchange"], m["spot"], e, band=s["chain_band"])
    F, dmap, k = kq.pick(chain, ctx["today"], e)

    def leg(cp, K, side):
        ot = "CE" if cp == "C" else "PE"
        r = chain[(chain.option_type == ot) & (chain.strike == K)].iloc[0]
        return {"underlying": u, "expiry": e, "exchange": m["exchange"], "tradingsymbol": r.tradingsymbol,
                "option_type": ot, "strike": float(r.strike), "lot": int(r.lot), "bid": _clean(r.bid),
                "ask": _clean(r.ask), "mid": _clean(r.mid), "delta": dmap.get((cp, K)), "side": side,
                "freeze": int(r.freeze) if _clean(r.get("freeze")) else int(s["freeze_qty"][u])}

    kw = wing_strikes(chain, k, spot, wing_pct)
    return (F, spot, [leg(cp, k[cp], "SELL") for cp in ("C", "P")],
            [leg(cp, kw[cp], "BUY") for cp in ("C", "P")] if kw else [], k, kw)


def build_plan(ctx, u, e):
    s = ctx["settings"]
    F, spot, legs_, wings, k, kw = pick_legs(ctx, u, e, s["wing_pct"])
    lot = legs_[0]["lot"]
    credit = sum(l["bid"] or 0 for l in legs_)
    wing_cost = sum(w["ask"] or 0 for w in wings)
    # with wings the worst week is fixed: the wider spread, less the net credit (per lot, ₹)
    max_loss = (max(kw["C"] - k["C"], k["P"] - kw["P"]) - credit + wing_cost) * lot if kw else None
    per_lot = basket_margin(ctx, wings + legs_, 1)
    extra = ob.expiry_day_extra(F, legs_[0]["lot"])  # the expiry-day ELM per lot: size so the peak fits
    avail = available(ctx)
    peak = peak_available(ctx, e, avail)
    buf = s["margin_buffer_rs"]
    cap = int(s["lots_cap"].get(u, 0))
    # two checks: Kite takes the entry margin now; the expiry-day peak must fit what is free on `e`
    lots = min(size_lots(cap, avail, buf, per_lot), size_lots(cap, peak["available"], buf, per_lot + extra))
    vix, vix_src = india_vix(ctx)
    lots_pre_vix = lots
    lots, vix_action = vix_guard(s, vix, lots)
    margin = per_lot * lots
    while lots > 1:                                 # the margin at size, not per lot × lots
        margin = basket_margin(ctx, wings + legs_, lots)
        if margin <= avail - buf and margin + extra * lots <= peak["available"] - buf:
            break
        lots -= 1
        margin = per_lot * lots
    return {"underlying": u, "expiry": e, "spot": spot, "forward": F, "legs": legs_, "wings": wings,
            "wing_pct": s["wing_pct"], "credit_pts": credit, "wing_cost_pts": wing_cost, "max_loss_per_lot": max_loss,
            "margin_per_lot": per_lot,
            "available": avail, "peak_available": peak["available"], "freed_before_expiry": peak["freed"],
            "peak_note": peak["note"], "buffer": buf, "cap": cap, "lots": lots, "margin_rs": margin,
            "vix": vix, "vix_src": vix_src, "vix_action": vix_action, "lots_pre_vix": lots_pre_vix, "vix_halt": s["vix_halt"],
            "expiry_extra_per_lot": extra, "expiry_margin_rs": margin + extra * lots}


def _vix_text(p):
    v = f"{p['vix']:.2f}" if p["vix"] is not None else "unknown"
    return {"halt": f"India VIX {v} ({p['vix_src']}): no entry at VIX ≥ {p['vix_halt']:g} or unknown",
            "halve": f"India VIX {v} ({p['vix_src']}): lots halved {p['lots_pre_vix']} → {p['lots']}",
            "normal": f"India VIX {v}"}[p["vix_action"]]


def _wings_text(p):
    if not p.get("wings"):
        return ""
    return (" after buying the wings " + " + ".join(f"{w['tradingsymbol']} (ask {w['ask']})" for w in p["wings"])
            + f" ({p['wing_pct']:g}% beyond; worst week capped at ₹{p['max_loss_per_lot']:,.0f}/lot)")


def _plan_text(p):
    return (f"{p['underlying']} {p['expiry']}: sell " + " + ".join(
        f"{l['tradingsymbol']} (bid {l['bid']}, ask {l['ask']}, Δ {l['delta']:.3f})" for l in p["legs"])
        + f" × {p['lots']} lot(s){_wings_text(p)} · margin ₹{p['margin_per_lot']:,.0f}/lot + ₹{p['expiry_extra_per_lot']:,.0f}/lot on expiry day"
        + f" (₹{p['expiry_margin_rs']:,.0f} at size) · available ₹{p['available']:,.0f} now,"
        + f" ₹{p['peak_available']:,.0f} on expiry day ({p['peak_note']})"
        + f" · {_vix_text(p)}")


def wait_for_approval(ctx, ticket_id):
    s = ctx["settings"]
    by = _at(ctx, s["approve_by"])
    while True:
        a = get_state(f"approval:{ticket_id}")
        if a and a.get("approved"):
            return True
        if ctx["now"]() >= by:
            return False
        ctx["wait"](s["approval_poll_s"])


def approve(ticket_id, by="cockpit", now=None):
    """Amit's Approve on the cockpit. Refused when the ticket is unknown, already decided, not
    today's, or the approve-by time has passed (then nothing will be placed)."""
    now = now or datetime.now(IST)
    t = _rows("SELECT trade_date, event FROM option_live_orders WHERE ticket_id = ? AND event IN "
              "('ticket', 'approved', 'expired') ORDER BY event_id", [ticket_id])
    if t.empty or "ticket" not in set(t.event):
        raise ValueError(f"no ticket {ticket_id}")
    if set(t.event) & {"approved", "expired"} or get_state(f"approval:{ticket_id}"):
        raise ValueError(f"ticket {ticket_id} is already decided")
    s = settings()
    h, m = map(int, s["approve_by"].split(":"))
    if t.trade_date.iloc[0] != now.date().isoformat() or now >= now.replace(hour=h, minute=m, second=0, microsecond=0):
        raise ValueError(f"too late: tickets must be approved before {s['approve_by']} IST on their day")
    if s["kill"]:
        raise ValueError("the kill switch is on: resume first")
    put_state(f"approval:{ticket_id}", {"approved": True, "at": _utc(), "by": by}, by)
    return {"ok": True, "ticket_id": ticket_id}


def entry(ctx, u):
    s, today, mode = ctx["settings"], ctx["today"], ctx["mode"]
    if mode == "off":
        return outcome(ctx, u, "idle", "mode is off")
    e = due_expiry(u, today, ob.holidays())
    if not e:
        return outcome(ctx, u, "idle", "not an entry day")
    now = ctx["now"]()
    if now < _at(ctx, s["entry_earliest"]):
        return outcome(ctx, u, "skipped", f"too early: entries start at {s['entry_earliest']} IST")
    if now >= _at(ctx, s["entry_cutoff"]):
        return outcome(ctx, u, "skipped", f"after the {s['entry_cutoff']} cut-off",
                       f"{u} entry skipped: it ran after the {s['entry_cutoff']} cut-off (no retry).", urgent=True)
    if s["kill"]:
        return outcome(ctx, u, "skipped", f"kill switch on ({s['kill_reason']})",
                       f"{u} entry skipped: the kill switch is on ({s['kill_reason']}). Resume on the cockpit.")
    src = family(ctx)
    loss = -week_realised(today, src)
    if loss >= s["weekly_loss_limit_rs"]:
        set_kill(True, f"weekly loss limit: ₹{loss:,.0f} realised this week", ctx["step"])
        return outcome(ctx, u, "skipped", f"weekly loss ₹{loss:,.0f} ≥ limit ₹{s['weekly_loss_limit_rs']:,.0f}",
                       f"{u} entry skipped: this week's realised loss ₹{loss:,.0f} is over the ₹{s['weekly_loss_limit_rs']:,.0f} "
                       "limit. Entries are paused until you resume them on the cockpit.", urgent=True)
    try:
        client(ctx)
    except NoKiteSession:
        return outcome(ctx, u, "failed", "no Kite login today",
                       f"log in to Kite: {LOGIN_PAGE} — the {u} entry for {e} is skipped until you do "
                       f"(re-run before {s['entry_cutoff']}).", urgent=True)
    dup = already_entered(ctx, u, e, src)
    if dup:
        return outcome(ctx, u, "skipped", dup)
    if u == "SENSEX":
        ok, why = rotation_gate(ctx)
        if not ok:
            return outcome(ctx, u, "skipped", f"rotation gate: {why}",
                           f"SENSEX entry skipped — rotation gate failed: {why}. NIFTY expires normally.", urgent=True)
    plan = build_plan(ctx, u, e)
    if plan["vix_action"] == "halt":
        return outcome(ctx, u, "skipped", f"VIX guard: {_vix_text(plan)}",
                       f"{u} entry for {e} skipped — {_vix_text(plan)}.", urgent=True)
    ticket_id = f"{u}-{e}-{today}"
    for leg in plan["wings"] + plan["legs"]:
        log_event(ctx, "proposed", source=src, ticket_id=ticket_id, **_leg_fields(leg), transaction_type=leg["side"],
                  quantity=plan["lots"] * leg["lot"], price=leg["bid"] if leg["side"] == "SELL" else leg["ask"],
                  detail={k: plan[k] for k in ("lots", "cap", "margin_per_lot", "available", "peak_available", "freed_before_expiry",
                                               "buffer", "margin_rs", "spot", "forward",
                                               "vix", "vix_action", "lots_pre_vix", "expiry_margin_rs",
                                               "wing_pct", "max_loss_per_lot")}
                  | {"delta": leg["delta"], "ask": leg["ask"], "mid": leg["mid"]})
    if plan["lots"] == 0:
        if mode != "shadow":
            return outcome(ctx, u, "skipped", "not enough margin",
                           f"{u} entry skipped: not enough margin for one lot — needs ₹{plan['margin_per_lot']:,.0f} now "
                           f"(free ₹{plan['available']:,.0f}) and ₹{plan['margin_per_lot'] + plan['expiry_extra_per_lot']:,.0f} "
                           f"on expiry day (free then ≈ ₹{plan['peak_available']:,.0f}), each after the "
                           f"₹{plan['buffer']:,.0f} buffer.", urgent=True)
        plan["lots"] = int(s["shadow_min_lots"])
        plan["margin_rs"] = plan["margin_per_lot"] * plan["lots"]
        plan["margin_short"] = True
    for leg in plan["wings"] + plan["legs"]:
        leg["qty"] = plan["lots"] * leg["lot"]
    if mode == "shadow":
        res_w = shadow_fill(ctx, plan["wings"], "BUY", ticket_id) if plan["wings"] else {}
        res = shadow_fill(ctx, plan["legs"], "SELL", ticket_id)
        rebuild_ledger()
        _set_margin(u, e, "shadow", plan["margin_rs"])
        note = " (margin short: a live mode would have skipped)" if plan.get("margin_short") else ""
        credit = _net_credit(res, res_w)
        return outcome(ctx, u, "ok", _fills_text(res_w | res) + note,
                       f"{u} {e} sold (simulated at the bid): {_fills_text(res)}"
                       + (f", wings bought at the ask: {_fills_text(res_w)}" if res_w else "")
                       + f" = ₹{credit:,.0f} net credit, margin ₹{plan['margin_rs']:,.0f}{note} · {_vix_text(plan)}.")
    if mode == "approve":
        log_event(ctx, "ticket", source=src, ticket_id=ticket_id, underlying=u, expiry=e,
                  detail={"lots": plan["lots"], "margin_rs": plan["margin_rs"],
                          "legs": [l["tradingsymbol"] for l in plan["wings"] + plan["legs"]]})
        push(ctx, f"Approve {_plan_text(plan)} — tap Approve on the cockpit before {s['approve_by']} IST: {PAGE}", urgent=True)
        if not wait_for_approval(ctx, ticket_id):
            log_event(ctx, "expired", source=src, ticket_id=ticket_id, underlying=u, expiry=e,
                      detail=f"not approved by {s['approve_by']}")
            return outcome(ctx, u, "skipped", "ticket not approved in time",
                           f"{u} ticket expired unapproved at {s['approve_by']} — nothing was placed.")
        log_event(ctx, "approved", source=src, ticket_id=ticket_id, underlying=u, expiry=e)
        if settings()["kill"]:
            return outcome(ctx, u, "skipped", "kill switch turned on after approval",
                           f"{u}: approved, but the kill switch is now on — nothing was placed.")
    res_w, wing_note = {}, ""
    if plan["wings"]:                               # wings first: Kite then blocks the hedged margin for the sale
        start = ctx["now"]()
        end = min(start + timedelta(seconds=s["wing_buy_s"]), _at(ctx, s["entry_cutoff"]))
        res_w = work_orders(ctx, plan["wings"], "BUY", end, final_at=start + timedelta(seconds=s["wing_buy_s"] * 2 / 3),
                            ticket_id=ticket_id, source="live")
        lot = plan["legs"][0]["lot"]
        hedged = min(o["filled"] for o in res_w.values()) // lot
        if hedged == 0:
            left = _unwind_wings(ctx, res_w, ticket_id)
            rebuild_ledger()
            return outcome(ctx, u, "failed", f"wings not filled ({_fills_text(res_w)}): strangle not sold",
                           f"{u} entry: the wings did not fill ({_fills_text(res_w)}), so the strangle was not sold"
                           + (f"; {left} wing unit(s) could not be sold back and stay open (they cost nothing more)" if left else "")
                           + ".", urgent=True)
        if hedged < plan["lots"]:
            wing_note = f" (wings filled for {hedged} of {plan['lots']} lots: sold {hedged})"
            for leg in plan["legs"]:
                leg["qty"] = hedged * leg["lot"]
    res = work_orders(ctx, plan["legs"], "SELL", _at(ctx, s["entry_cutoff"]), ticket_id=ticket_id, source="live")
    rebuild_ledger()
    _set_margin(u, e, "live", plan["margin_rs"])
    filled = [o["filled"] for o in res.values()]
    rejects = [r for o in res.values() for r in o["rejects"]]
    if len(set(filled)) > 1:
        return _unbalanced(ctx, u, e, res, ticket_id)
    if not any(filled):
        left = _unwind_wings(ctx, res_w, ticket_id)
        rebuild_ledger()
        return outcome(ctx, u, "failed", f"nothing filled by {s['entry_cutoff']}: {'; '.join(rejects) or 'no fill'}",
                       f"{u} entry: nothing filled by {s['entry_cutoff']} ({'; '.join(rejects) or 'no fill at the bid'}). "
                       "Orders cancelled; no position"
                       + (f" ({left} wing unit(s) could not be sold back and stay open)" if left else "") + ".", urgent=True)
    credit = _net_credit(res, res_w)
    return outcome(ctx, u, "ok", _fills_text(res_w | res) + wing_note,
                   f"{u} {e} sold: {_fills_text(res)}" + (f" after buying the wings {_fills_text(res_w)}" if res_w else "")
                   + f" = ₹{credit:,.0f} net credit{wing_note}, margin ₹{plan['margin_rs']:,.0f} "
                   f"(₹{plan['expiry_margin_rs']:,.0f} on expiry day) · {_vix_text(plan)}.")


def _net_credit(res, res_w):
    return (sum((o["avg"] or 0) * o["filled"] for o in res.values())
            - sum((o["avg"] or 0) * o["filled"] for o in res_w.values()))


def _unwind_wings(ctx, res_w, ticket_id):
    """Sell back the wings bought for a strangle that was not sold → units that stayed long (they just expire)."""
    todo = [{**o["leg"], "qty": o["filled"]} for o in res_w.values() if o["filled"]]
    if not todo:
        return 0
    end = min(ctx["now"]() + timedelta(seconds=45), _at(ctx, "15:29") + timedelta(seconds=55))
    back = work_orders(ctx, todo, "SELL", end, ticket_id=ticket_id, source="live")
    return sum(l["qty"] - back[l["tradingsymbol"]]["filled"] for l in todo)


def _unbalanced(ctx, u, e, res, ticket_id):
    """One leg filled more than the other: buy the excess back now, else ask for a manual close."""
    (a, oa), (b, ob_) = sorted(res.items(), key=lambda kv: -kv[1]["filled"])
    excess = oa["filled"] - ob_["filled"]
    push(ctx, f"{u} entry unbalanced at the cut-off: {_fills_text(res)}. Buying back {excess} of {a} now.", urgent=True)
    leg = {**oa["leg"], "qty": excess}
    end = min(ctx["now"]() + timedelta(seconds=45), _at(ctx, "15:29") + timedelta(seconds=55))
    fix = work_orders(ctx, [leg], "BUY", end, final_at=ctx["now"](), ticket_id=ticket_id, source="live")
    rebuild_ledger()
    left = excess - fix[a]["filled"]
    if left:
        return outcome(ctx, u, "failed", f"unbalanced: {left} of {a} still open alone",
                       f"{u}: {left} units of {a} are still open without the other leg — close them by hand in Kite, "
                       "or keep them to expiry.", urgent=True)
    return outcome(ctx, u, "failed", f"unbalanced entry flattened: {_fills_text(res)}, excess {excess} bought back",
                   f"{u}: the excess {excess} of {a} was bought back; the position is {ob_['filled']} units a leg.")


# ─────────────────────────── buy-back, close-all ───────────────────────────

def _close_legs(ctx, legs_, deadline, final_at, label):
    """Buy back short legs: shadow legs simulated, real legs (live / adopted manual) as tagged orders."""
    sim = [l for l in legs_ if l["source"] == "shadow"]
    real = [l for l in legs_ if l["source"] != "shadow"]
    for l in legs_:
        l["qty"] = -int(l["net_qty"])
        l["freeze"] = int(ctx["settings"]["freeze_qty"].get(l["underlying"], 10 ** 9))
    out = {}
    if sim:
        out.update(shadow_fill(ctx, sim, "BUY", label))
    for src in sorted({l["source"] for l in real}):
        out.update(work_orders(ctx, [l for l in real if l["source"] == src], "BUY", deadline, final_at=final_at,
                               ticket_id=label, source="live" if src == "live" else "manual"))
    rebuild_ledger()
    return out


def buyback(ctx, u="NIFTY"):
    s, today = ctx["settings"], ctx["today"]
    if ctx["mode"] == "off":
        return outcome(ctx, u, "idle", "mode is off")
    # shadow touches only simulated legs; a real-money mode its tagged legs (+ Amit's, when adopted).
    # Only Close-all, pressed by hand, closes real legs whatever the mode.
    srcs = ["shadow"] if ctx["mode"] == "shadow" else ["live"] + (["manual"] if s["adopt_manual_nifty"] else [])
    todo = [l for l in legs("underlying = ? AND expiry = ? AND status = 'OPEN' AND net_qty < 0", [u, today])
            if l["source"] in srcs]
    if not todo:
        return outcome(ctx, u, "idle", f"no {u} leg expiring today")
    now = ctx["now"]()
    if not _at(ctx, s["buyback_start"]) <= now < _at(ctx, s["buyback_end"]):
        return outcome(ctx, u, "skipped", f"outside the {s['buyback_start']}-{s['buyback_end']} window")
    key = f"rotation:{today}"
    try:
        client(ctx)
    except NoKiteSession:
        put_state(key, {"ok": False, "detail": "no Kite login: buy-back not done"}, ctx["step"])
        return outcome(ctx, u, "failed", "no Kite login today",
                       f"log in to Kite: {LOGIN_PAGE} — the {u} buy-back has not run. Re-run it before "
                       f"{s['buyback_end']}, or {u} expires normally and SENSEX is skipped.", urgent=True)
    real = [l for l in todo if l["source"] != "shadow"]
    before = available(ctx) if real else None
    expected = sum({(l["source"], l["expiry"]): l["margin_rs"] or 0 for l in real}.values())
    res = _close_legs(ctx, todo, _at(ctx, s["buyback_end"]), _at(ctx, s["buyback_final"]), f"buyback-{u}-{today}")
    left = [l for l in legs("underlying = ? AND expiry = ? AND status = 'OPEN' AND net_qty < 0", [u, today])
            if l["source"] in srcs]
    flat, freed = not left, None
    if real:
        pos = broker_positions(ctx)
        flat = flat and all(pos.get(l["tradingsymbol"], 0) == 0 for l in real if l["source"] == "live" or s["adopt_manual_nifty"])
        for _ in range(3):                          # margin release can lag the fill by a few seconds
            freed = available(ctx) - before
            if expected <= 0 or freed >= s["margin_freed_frac"] * expected:
                break
            ctx["wait"](5)
    margin_ok = freed is None or expected <= 0 or freed >= s["margin_freed_frac"] * expected
    ok = flat and margin_ok
    detail = (f"{_fills_text(res)}; flat={flat}" + (f", margin freed {_rs(freed)} of ₹{expected:,.0f} expected" if freed is not None else ""))
    put_state(key, {"ok": ok, "flat": flat, "freed_rs": freed, "expected_rs": expected, "detail": detail,
                    "mode": ctx["mode"]}, ctx["step"])
    if ok:
        return outcome(ctx, u, "ok", detail, f"{u} buy-back done: {_fills_text(res)}"
                       + (f", {_rs(freed)} margin freed" if freed is not None else "") + " — SENSEX can enter.")
    why = "still open: " + ", ".join(l["tradingsymbol"] for l in left) if left or not flat else f"margin freed only {_rs(freed)}"
    return outcome(ctx, u, "failed", detail, f"{u} buy-back incomplete ({why}). Leftovers cancelled; {u} expires "
                   "normally and the SENSEX entry will be skipped.", urgent=True)


def closeall(ctx):
    """Stop + buy back every open tagged (and shadow) short leg now. Long wings stay: they only gain."""
    s = ctx["settings"]
    set_kill(True, "Close-all", ctx["step"])
    todo = [l for l in legs("status = 'OPEN' AND net_qty < 0") if l["source"] in ("shadow", "live")]
    if not todo:
        return outcome(ctx, "ALL", "ok", "nothing open", "Close-all: no open tagged legs. Kill switch is on.")
    try:
        client(ctx)
    except NoKiteSession:
        return outcome(ctx, "ALL", "failed", "no Kite login today",
                       f"Close-all could not run: log in to Kite ({LOGIN_PAGE}) and press it again, or close in Kite by hand.",
                       urgent=True)
    end = ctx["now"]() + timedelta(minutes=s["closeall_minutes"])
    res = _close_legs(ctx, todo, end, end - timedelta(minutes=1), f"closeall-{ctx['today']}")
    left = [l for l in legs("status = 'OPEN' AND net_qty < 0") if l["source"] in ("shadow", "live")]
    if left:
        return outcome(ctx, "ALL", "failed", f"still open: {[l['tradingsymbol'] for l in left]}",
                       f"Close-all incomplete: {_fills_text(res)}; still open " + ", ".join(l["tradingsymbol"] for l in left)
                       + " — close them in Kite by hand.", urgent=True)
    return outcome(ctx, "ALL", "ok", _fills_text(res), f"Close-all done: {_fills_text(res)}. Kill switch is on.")


# ─────────────────────────── record, mark, settle, reconcile ───────────────────────────

def record(ctx):
    """Today's Kite trades on NIFTY / SENSEX options → fill events (tagged = live, else manual);
    then any manual position the ledger does not explain is adopted from Kite's positions."""
    try:
        client(ctx)
    except NoKiteSession:
        return outcome(ctx, "ALL", "idle", "no Kite login today: nothing to record")
    snapshot_margin(ctx)
    tag = ctx["settings"]["tag"]
    inst = option_instruments(ctx)
    tagged = {str(o["order_id"]) for o in call(ctx, "orders") if tag in ([o.get("tag")] + list(o.get("tags") or []))}
    placed = _rows("SELECT order_id, source FROM option_live_orders WHERE event = 'place' AND trade_date = ?", [ctx["today"]])
    mine = dict(zip(placed.get("order_id", []), placed.get("source", [])))    # an adopted manual leg's buy-back stays manual
    n_fill = 0
    for t in call(ctx, "trades"):
        meta = inst.get(t.get("tradingsymbol"))
        if not meta:
            continue
        oid = str(t["order_id"])
        src = mine.get(oid) or ("live" if oid in tagged else "manual")
        n_fill += log_event(ctx, "fill", source=src, trade_id=str(t["trade_id"]),
                            order_id=oid, transaction_type=t["transaction_type"], quantity=int(t["quantity"]),
                            price=float(t["average_price"]), **meta, detail={"fill_timestamp": str(t.get("fill_timestamp"))})
    rebuild_ledger()
    led = {}
    live_syms = set()
    for l in legs("source IN ('live', 'manual') AND expiry >= ?", [ctx["today"]]):
        led[(l["tradingsymbol"], l["source"])] = l
        if l["source"] == "live":
            live_syms.add(l["tradingsymbol"])
    n_seed = 0
    for p in call(ctx, "positions").get("net", []):
        sym, meta = p["tradingsymbol"], inst.get(p["tradingsymbol"])
        if not meta or sym in live_syms:            # a tagged leg's symbol is reconciled, never absorbed
            continue
        diff = int(p.get("quantity") or 0) - int((led.get((sym, "manual")) or {}).get("net_qty") or 0)
        if diff:
            n_seed += log_event(ctx, "seed", source="manual", trade_id=f"seed:{sym}:{ctx['today']}:{diff}",
                                transaction_type="BUY" if diff > 0 else "SELL", quantity=abs(diff),
                                price=float(p.get("average_price") or 0), **meta,
                                detail="adopted from Kite positions (a manual trade the ledger had not seen)")
    if n_seed:
        rebuild_ledger()
    return outcome(ctx, "ALL", "ok", f"{n_fill} new fill(s), {n_seed} manual position(s) adopted")


def _fno_settle(u, e):
    df = _rows("SELECT option_type, strike, settle, trade_date FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
               "AND expiry_date = ? AND trade_date = (SELECT MAX(trade_date) FROM fno_bhav WHERE symbol = ? "
               "AND instrument_type = 'IDO' AND expiry_date = ?)", [u, e, u, e])
    return {(r.option_type, float(r.strike)): r.settle for r in df.itertuples()}


def _pnl(l, price):
    sv = (l["sell_qty"] or 0) * (l["sell_avg"] or 0)
    bv = (l["buy_qty"] or 0) * (l["buy_avg"] or 0)
    return sv - bv + (l["net_qty"] or 0) * price


def _quote_if_logged_in(ctx):
    """The sizing quote rides on the mark step (10:00, 15:01 IST); a failure is logged, never fatal to the mark."""
    if not has_session(ctx):
        return None
    try:
        return sizing_quote(ctx)
    except Exception as e:                          # noqa: BLE001
        runlog.note(f"options_live: sizing quote failed ({type(e).__name__}: {e})", level="WARN")
        return None


def mark(ctx):
    _quote_if_logged_in(ctx)
    open_ = legs("status = 'OPEN'")
    if not open_:
        return outcome(ctx, "ALL", "idle", "nothing open")
    live = has_session(ctx)
    q = quotes(ctx, open_) if live else {}
    rows, how = [], "Kite mids" if live else "last stored settle (no Kite login)"
    for l in open_:
        bid, ask, last = q.get(l["tradingsymbol"], (None, None, None))
        px = (bid + ask) / 2 if bid and ask else last
        if px is None:
            px = _fno_settle(l["underlying"], l["expiry"]).get((l["option_type"], l["strike"]))
        if px is None:
            continue
        rows.append({**{k: l[k] for k in LEDGER_KEY}, "status": "OPEN", "mark_price": float(px), "mark_at": _utc(),
                     "mtm_rs": _pnl(l, float(px)) - (l["charges_rs"] or 0)})
    if live:
        groups = {}
        for l in open_:
            if l["net_qty"]:
                groups.setdefault((l["underlying"], l["expiry"], l["source"]), []).append(l)
        for (u, e, src), g in groups.items():
            if not any(l["net_qty"] < 0 for l in g):    # only longs left: no margin
                continue
            m = basket_margin(ctx, [{**l, "lot": abs(l["net_qty"]), "side": "SELL" if l["net_qty"] < 0 else "BUY"}
                                    for l in g], 1)
            for r in rows:
                if (r["underlying"], r["expiry"], r["source"]) == (u, e, src):
                    r["mark_margin_rs"] = m
        snapshot_margin(ctx)
    if rows:
        upsert_df(pd.DataFrame(rows), "option_live_trades")
    total = sum(r["mtm_rs"] for r in rows)
    return outcome(ctx, "ALL", "ok", f"{len(rows)} of {len(open_)} open leg(s) marked at {how}: MTM {_rs(total)}")


def settle(ctx):
    today = ctx["today"]
    todo = legs("status = 'OPEN' AND expiry <= ?", [today])
    if not todo:
        return outcome(ctx, "ALL", "idle", "nothing expired")
    done, waiting, msgs = [], [], []
    for (u, e) in sorted({(l["underlying"], l["expiry"]) for l in todo}):
        s = read_sql("SELECT MAX(underlying_price) AS s FROM fno_bhav WHERE symbol = ? AND instrument_type = 'IDO' "
                     "AND trade_date = ? AND expiry_date = ?", params=[u, e, e])["s"].iloc[0]
        if not s:
            waiting.append(f"{u} {e}")
            continue
        S, net = float(s), {}
        rows = []
        for l in (x for x in todo if (x["underlying"], x["expiry"]) == (u, e)):
            exit_ = ob.intrinsic("C" if l["option_type"] == "CE" else "P", l["strike"], S)
            gross = _pnl(l, exit_)
            # a long wing that finishes in the money is exercised: STT on its intrinsic value, in net_rs only
            # (charges_rs stays the fills' charges, which rebuild_ledger recomputes)
            stt = ob.STT_EXERCISE * exit_ * l["net_qty"] if l["net_qty"] > 0 else 0.0
            rows.append({**{k: l[k] for k in LEDGER_KEY}, "status": "SETTLED", "settle_index": S, "exit_price": exit_,
                         "gross_rs": gross, "net_rs": gross - (l["charges_rs"] or 0) - stt, "closed_at": e,
                         "updated_at": _utc()})
            net[l["source"]] = net.get(l["source"], 0) + rows[-1]["net_rs"]
        upsert_df(pd.DataFrame(rows), "option_live_trades")
        done.append(f"{u} {e}")
        msgs.append(f"{u} {e} settled at {S:,.2f}: " + ", ".join(f"{k} {_rs(v, True)}" for k, v in sorted(net.items())))
    stale = [w for w in waiting if date.fromisoformat(w.split()[1]) < date.fromisoformat(today) - timedelta(days=3)]
    detail = f"settled {done or 'nothing'}; waiting for the settlement price: {waiting or 'none'}"
    if stale:
        return outcome(ctx, "ALL", "failed", detail, f"no settlement price for {', '.join(stale)} after 3 days — "
                       "check the morning fno_bhav load.", urgent=True)
    return outcome(ctx, "ALL", "ok", detail, "; ".join(msgs) if msgs else None)


def reconcile(ctx):
    """Kite positions vs the ledger, contract by contract, for every live (non-shadow) leg not yet
    expired. A mismatch sets the kill switch and fails the step (health: OPTIONS_LIVE)."""
    today = ctx["today"]
    led = {}
    for l in legs("source IN ('live', 'manual') AND expiry >= ?", [today]):
        led[l["tradingsymbol"]] = led.get(l["tradingsymbol"], 0) + int(l["net_qty"] or 0)
    try:
        client(ctx)
    except NoKiteSession:
        if any(led.values()):
            put_state("reconcile", {"ok": None, "at": _utc(), "detail": "no Kite login: not reconciled"}, ctx["step"])
            return outcome(ctx, "ALL", "skipped", "no Kite login today: open legs not reconciled")
        return outcome(ctx, "ALL", "idle", "no Kite login and nothing open")
    inst = option_instruments(ctx)
    pos = {k: v for k, v in broker_positions(ctx).items() if k in inst and inst[k]["expiry"] >= today}
    bad = {sym: {"broker": pos.get(sym, 0), "ledger": led.get(sym, 0)} for sym in set(pos) | set(led)
           if pos.get(sym, 0) != led.get(sym, 0)}
    if bad:
        text = "; ".join(f"{k}: Kite {v['broker']}, ledger {v['ledger']}" for k, v in sorted(bad.items()))
        put_state("reconcile", {"ok": False, "at": _utc(), "date": today, "mismatch": bad, "detail": text}, ctx["step"])
        set_kill(True, f"reconcile: broker ≠ ledger ({text})", ctx["step"])
        return outcome(ctx, "ALL", "failed", f"broker ≠ ledger: {text}",
                       f"Kite positions do not match the ledger ({text}). Entries are stopped until it is fixed and "
                       "`run.sh options_live reconcile` passes.", urgent=True)
    put_state("reconcile", {"ok": True, "at": _utc(), "date": today, "detail": f"{len(pos)} contract(s) match"}, ctx["step"])
    return outcome(ctx, "ALL", "ok", f"{len(pos)} broker contract(s) match the ledger")


def precheck(ctx):
    if ctx["mode"] == "off":
        return outcome(ctx, "ALL", "idle", "mode is off")
    hol = ob.holidays()
    due = [f"{u} entry" for u in MARKETS if due_expiry(u, ctx["today"], hol)]
    if legs("underlying = 'NIFTY' AND expiry = ? AND status = 'OPEN' AND net_qty < 0", [ctx["today"]]):
        due.insert(0, "NIFTY buy-back")
    if not due:
        return outcome(ctx, "ALL", "idle", "nothing due today")
    if has_session(ctx):
        return outcome(ctx, "ALL", "ok", f"logged in; due today: {', '.join(due)}")
    return outcome(ctx, "ALL", "skipped", f"no Kite login; due today: {', '.join(due)}",
                   f"log in to Kite before 15:05 IST — today has the {', '.join(due)}: {LOGIN_PAGE}", urgent=True)


def weekly(ctx):
    today = ctx["today"]
    monday = (date.fromisoformat(today) - timedelta(days=date.fromisoformat(today).weekday())).isoformat()
    week = legs("status IN ('CLOSED', 'SETTLED') AND closed_at >= ?", [monday])
    open_ = legs("status = 'OPEN'")
    by = {}
    for l in week:
        by[l["source"]] = by.get(l["source"], 0) + (l["net_rs"] or 0)
    mtm = sum(l["mtm_rs"] or 0 for l in open_)
    text = (f"week from {monday}: " + (", ".join(f"{k} {_rs(v, True)}" for k, v in sorted(by.items())) or "no closed legs")
            + f"; {len(open_)} open leg(s), MTM {_rs(mtm, True)}")
    return outcome(ctx, "ALL", "ok", text, f"weekly P&L — {text}")


# ─────────────────────────── sizing choices (the /options card) ───────────────────────────

SIZING = {
    "wing_pct": 1.75,           # quoted when the setting is off (0), so C / D can be shown
    "crash_gap": 0.139,         # the index gap of the crash column (2020-03-23)
    "crash_budget": 0.30,       # B: lots within this share of the money in that crash (combined-book study)
    "spare": 0.15,              # D: margin kept free beyond the buffer
    "keep": {"NIFTY": 0.853, "SENSEX": 0.823},   # premium kept after losing weeks, before charges (backtest 2019-26)
}


def sizing_quote(ctx):
    """Per lot, for each index's next entry: Kite's basket margin naked and with wings, the expiry-day
    extra, credit at the bid, wing cost at the ask, entry charges, the expected week and the crash loss.
    Read-only Kite calls; stored as state 'sizing_quote' for the Live panel."""
    s, today = ctx["settings"], ctx["today"]
    pct = s["wing_pct"] or SIZING["wing_pct"]
    out = {}
    for u in MARKETS:
        e = due_expiry(u, today, ob.holidays()) or kq.front_expiry(u, today)
        F, spot, legs_, wings, k, kw = pick_legs(ctx, u, e, pct)
        lot = legs_[0]["lot"]
        credit = sum(l["bid"] or 0 for l in legs_)
        wing_cost = sum(w["ask"] or 0 for w in wings)

        def charges(ls):
            return sum(ob.leg_cost(l["bid"] if l["side"] == "SELL" else l["ask"], l["side"].lower(), lot, ob.SLIP, today)
                       for l in ls if (l["bid"] if l["side"] == "SELL" else l["ask"])) * lot
        hit = max(0.0, k["P"] - (1 - SIZING["crash_gap"]) * F)
        kept = credit * lot * SIZING["keep"][u]
        out[u] = {"expiry": e, "spot": spot, "forward": F, "lot": lot, "extra": ob.expiry_day_extra(F, lot),
                  "strikes": {"C": k["C"], "P": k["P"], "wing_C": kw["C"], "wing_P": kw["P"]},
                  "naked": {"margin": basket_margin(ctx, legs_, 1), "credit_rs": credit * lot,
                            "weekly": kept - charges(legs_), "crash": (hit - credit) * lot},
                  "winged": {"margin": basket_margin(ctx, wings + legs_, 1), "credit_rs": (credit - wing_cost) * lot,
                             "weekly": kept - wing_cost * lot - charges(wings + legs_),
                             "crash": (min(hit, k["P"] - kw["P"]) - credit + wing_cost) * lot}}
    q = {"at": _utc(), "wing_pct": pct, "markets": out}
    put_state("sizing_quote", q, ctx["step"])
    snapshot_margin(ctx)                            # the money the choices are sized on, read at the same time
    return q


def sizing_choices(quote, capital, s):
    """The four setups on `capital` (₹: cash + collateral), each applied to both indices:
    A naked at today's caps · B naked within the crash budget · C winged at today's caps ·
    D winged at the margin limit (spare kept, at most lots_hard_max). Lots also fit the expiry-day peak
    after the buffer. The two trades never overlap, so a crash hits one index at a time."""
    if not quote or not capital:
        return []
    wing_on = bool(s["wing_pct"])
    spec = (("A", "naked", "cap", "Unprotected, today's caps"),
            ("B", "naked", "budget", f"Unprotected, crash loss within {SIZING['crash_budget']:.0%} of your money"),
            ("C", "winged", "cap", "Protected, today's caps"),
            ("D", "winged", "margin", f"Protected, as many lots as margin allows ({SIZING['spare']:.0%} spare)"))
    rows = []
    for key, kind, rule, label in spec:
        per = {}
        for u, q in quote["markets"].items():
            x = q[kind]
            peak = x["margin"] + q["extra"]
            fit = max(0, math.floor((capital * (1 - (SIZING["spare"] if rule == "margin" else 0)) - s["margin_buffer_rs"]) / peak))
            if rule == "cap":
                lots = min(int(s["lots_cap"].get(u, 0)), fit)
            elif rule == "budget":
                lots = min(fit, math.floor(SIZING["crash_budget"] * capital / x["crash"])) if x["crash"] > 0 else fit
            else:
                lots = fit
            lots = min(lots, int(s["lots_hard_max"]))      # a cap the settings accept
            per[u] = {"lots": lots, "weekly": lots * x["weekly"], "crash": lots * x["crash"], "peak": lots * peak}
        crash = max(p["crash"] for p in per.values())
        rows.append({"key": key, "kind": kind, "label": label, "per": per,
                     "weekly": sum(p["weekly"] for p in per.values()), "crash": crash, "crash_pct": crash / capital,
                     "wing_pct": quote["wing_pct"] if kind == "winged" else 0,
                     "caps": {u: p["lots"] for u, p in per.items()},
                     "current": (kind == "winged") == wing_on and all(
                         p["lots"] == int(s["lots_cap"].get(u, 0)) for u, p in per.items())})
    return rows


def quote_step(ctx):
    try:
        client(ctx)
    except NoKiteSession:
        return outcome(ctx, "ALL", "idle", "no Kite login today: no sizing quote")
    q = sizing_quote(ctx)
    return outcome(ctx, "ALL", "ok", "sizing quote: " + ", ".join(
        f"{u} naked ₹{m['naked']['margin']:,.0f} / winged ₹{m['winged']['margin']:,.0f} a lot" for u, m in q["markets"].items()))


def plan_only(ctx, u):
    """What `entry` would trade right now, without writing anything (read-only Kite calls only)."""
    e = due_expiry(u, ctx["today"], ob.holidays()) or kq.front_expiry(u, ctx["today"])
    p = build_plan(ctx, u, e)
    print(_plan_text(p))
    print(json.dumps({k: v for k, v in p.items() if k != "legs"}, default=str, indent=1))
    return p


OPEN_STATES = ("OPEN", "OPEN PENDING", "VALIDATION PENDING", "PUT ORDER REQ RECEIVED", "TRIGGER PENDING",
               "MODIFY PENDING", "MODIFY VALIDATION PENDING", "AMO REQ RECEIVED")


def testorder(ctx, u="NIFTY"):
    """One-off proof that this Kite app may place and cancel orders (Amit 2026-10-23): BUY 1 lot of the
    front-expiry at-the-money call at half its bid — far below the market, so it cannot fill — and cancel it
    at once. By hand only (not on cron), in any mode; Stop blocks it."""
    if ctx["settings"].get("kill"):
        return outcome(ctx, u, "skipped", "Stop is on")
    if not has_session(ctx):
        return outcome(ctx, u, "skipped", "no Kite login", f"test order not sent — log in to Kite first: {LOGIN_PAGE}")
    m, e = MARKETS[u], kq.front_expiry(u, ctx["today"])
    spot = call(ctx, "ltp", [m["spot"]])[m["spot"]]["last_price"]
    calls = [l for l in option_instruments(ctx).values() if l["underlying"] == u and l["expiry"] == e and l["option_type"] == "CE"]
    if not calls:
        return outcome(ctx, u, "failed", f"no {u} {e} calls in Kite's instruments")
    leg = min(calls, key=lambda l: abs(l["strike"] - spot))
    bid, _, last = quotes(ctx, [leg])[leg["tradingsymbol"]]
    ref = bid or last
    if not ref or ref < 40 * TICK:                  # half of a price under ₹2 is too close to the market
        return outcome(ctx, u, "failed", f"{leg['tradingsymbol']} has no usable price ({ref})")
    px = round(max(TICK, math.floor(ref * 0.5 / TICK) * TICK), 2)
    fields = dict(source="test", **_leg_fields(leg), transaction_type="BUY", variety="regular", quantity=leg["lot"], price=px)
    ctx["may_write"] = True
    try:
        try:
            oid = call(ctx, "place_order", variety="regular", exchange=leg["exchange"], tradingsymbol=leg["tradingsymbol"],
                       transaction_type="BUY", quantity=leg["lot"], product="NRML", order_type="LIMIT", price=px,
                       validity="DAY", tag=ctx["settings"]["tag"])
        except Exception as ex:                     # noqa: BLE001 — the answer we came for: Kite refused the order
            log_event(ctx, "error", **fields, detail=f"{type(ex).__name__}: {ex}")
            return outcome(ctx, u, "failed", f"Kite refused the order: {type(ex).__name__}: {ex}",
                           f"test order REFUSED by Kite — {type(ex).__name__}: {ex}. Orders from this app don't work yet.",
                           urgent=True)
        log_event(ctx, "place", **fields, order_id=oid)
        ctx["wait"](2)
        o = next((x for x in call(ctx, "orders") if x["order_id"] == oid), {})
        if o.get("status") in OPEN_STATES:
            call(ctx, "cancel_order", variety="regular", order_id=oid)
            log_event(ctx, "cancel", **fields, order_id=oid)
            ctx["wait"](2)
            o = next((x for x in call(ctx, "orders") if x["order_id"] == oid), o)
    finally:
        ctx["may_write"] = False
    status, filled, why = o.get("status"), o.get("filled_quantity") or 0, o.get("status_message") or ""
    log_event(ctx, "status", **fields, order_id=oid, status=status, filled_qty=filled, detail=why or None)
    what = f"BUY {leg['lot']} {leg['tradingsymbol']} @ ₹{px} (bid ₹{bid}), order {oid}"
    if filled:
        return outcome(ctx, u, "failed", f"{what} FILLED {filled} — unexpected",
                       f"test order FILLED {filled} units of {leg['tradingsymbol']} — sell them in Kite", urgent=True)
    if status == "CANCELLED":
        return outcome(ctx, u, "ok", f"{what}: accepted by Kite, then cancelled",
                       f"test order OK — Kite accepted and cancelled {leg['tradingsymbol']} (order {oid}). Orders work.")
    if status == "REJECTED":
        return outcome(ctx, u, "ok", f"{what}: accepted by Kite, rejected downstream: {why}",
                       f"test order reached the exchange (so the app may place orders) but was rejected: {why}")
    return outcome(ctx, u, "failed", f"{what}: still {status} after cancel — check Kite's Orders tab",
                   f"test order {oid} is still {status} — cancel it in Kite's Orders tab", urgent=True)


STEPS = {"entry": entry, "buyback": buyback, "closeall": closeall, "record": record, "mark": mark,
         "settle": settle, "reconcile": reconcile, "precheck": precheck, "weekly": weekly, "testorder": testorder,
         "quote": quote_step}
PER_UNDERLYING = ("entry", "buyback", "testorder")


def run_step(step, underlying=None, **ctx_kw):
    ensure_tables()
    ctx = make_ctx(step, **ctx_kw)
    if step in PER_UNDERLYING:
        u = (underlying or ("NIFTY" if step in ("buyback", "testorder") else "")).upper()
        if u not in MARKETS:
            raise SystemExit(f"--underlying must be one of {sorted(MARKETS)}")
        return STEPS[step](ctx, u)
    return STEPS[step](ctx)


# ─────────────────────────── health, cockpit ───────────────────────────

def health_check():
    """OPTIONS_LIVE (checks/custom.py): broker ≠ ledger, or a live step that failed in the last 3
    days and has not succeeded since. CRITICAL on a mismatch or in a real-money mode, else WARN."""
    df = _rows("SELECT key, value FROM option_live_settings WHERE key = 'reconcile' OR key LIKE 'step:%'")
    if df.empty:
        return {"n_bad": 0, "n_total": 0}
    mode = settings()["mode"]
    since = (datetime.now(IST).date() - timedelta(days=3)).isoformat()
    bad, n, critical = [], 0, False
    for k, v in zip(df["key"], df["value"]):
        v = json.loads(v)
        n += 1
        if k == "reconcile":
            if v.get("ok") is False:
                bad.append(f"broker ≠ ledger: {v.get('detail')}")
                critical = True
        elif v.get("status") == "failed" and (v.get("date") or "") >= since:
            bad.append(f"{k[5:]} failed {v.get('date')}: {v.get('detail')}")
            critical = critical or v.get("mode") in LIVE_MODES or mode in LIVE_MODES
    return {"n_bad": len(bad), "n_total": n, "sample": " · ".join(bad[:3]) or None,
            "severity": "CRITICAL" if critical else "WARN"}


def page_data():
    """The /options Live panel. Reads only; tolerates a DB without the tables."""
    s = settings()
    tk = _rows("SELECT * FROM option_live_orders WHERE event = 'ticket' ORDER BY event_id DESC LIMIT 1")
    ticket = None
    if not tk.empty:
        t = tk.iloc[0]
        ev = set(_rows("SELECT event FROM option_live_orders WHERE ticket_id = ?", [t.ticket_id])["event"])
        prop = _rows("SELECT tradingsymbol, transaction_type, quantity, price, detail FROM option_live_orders "
                     "WHERE ticket_id = ? AND event = 'proposed' ORDER BY event_id", [t.ticket_id])
        now = datetime.now(IST)
        h, m = map(int, s["approve_by"].split(":"))
        pending = not (ev & {"approved", "expired"}) and not get_state(f"approval:{t.ticket_id}") \
            and t.trade_date == now.date().isoformat() and now < now.replace(hour=h, minute=m, second=0, microsecond=0)
        ticket = {"ticket_id": t.ticket_id, "trade_date": t.trade_date, "underlying": t.underlying, "expiry": t.expiry,
                  "status": "approved" if ("approved" in ev or get_state(f"approval:{t.ticket_id}")) else
                            "expired" if "expired" in ev else "pending" if pending else "lapsed",
                  "pending": pending, "detail": json.loads(t.detail) if t.detail else {},
                  "legs": [{"tradingsymbol": r.tradingsymbol, "side": r.transaction_type or "SELL",
                            "quantity": r.quantity, "price": _clean(r.price)} for r in prop.itertuples()]}
    all_legs = legs()
    open_ = [l for l in all_legs if l["status"] == "OPEN"]
    hist = [l for l in all_legs if l["status"] != "OPEN"][::-1][:60]
    totals = {}
    for l in all_legs:
        t = totals.setdefault(l["source"], {"realised": 0.0, "n_closed": 0, "open_mtm": 0.0, "n_open": 0})
        if l["status"] == "OPEN":
            t["open_mtm"] += l["mtm_rs"] or 0
            t["n_open"] += 1
        else:
            t["realised"] += l["net_rs"] or 0
            t["n_closed"] += 1
    states = _rows("SELECT key, value, updated_at FROM option_live_settings WHERE key LIKE 'step:%' ORDER BY updated_at DESC")
    today = datetime.now(IST).date().isoformat()
    groups = {}                                     # one basket margin per (underlying, expiry, source), not per leg
    for l in open_:
        m = l.get("mark_margin_rs") or l.get("margin_rs")
        if m:
            groups[(l["underlying"], l["expiry"], l["source"])] = m
    margin = get_state("margin")
    quote = get_state("sizing_quote")
    if quote:
        quote["at_ist"] = datetime.fromisoformat(quote["at"]).astimezone(IST).strftime("%a %d %b, %H:%M IST")
    choices = sizing_choices(quote, (margin or {}).get("total"), s)
    if margin:
        margin["at_ist"] = datetime.fromisoformat(margin["at"]).astimezone(IST).strftime("%a %d %b, %H:%M IST")
        margin["free_after_buffer"] = margin["free"] - s["margin_buffer_rs"]
    return {"settings": s, "modes": MODES, "ticket": ticket, "open": open_, "history": hist, "totals": totals,
            "rotation": get_state(f"rotation:{today}"), "reconcile": get_state("reconcile"),
            "steps": [{"key": k[5:], **json.loads(v)} for k, v in zip(states.get("key", []), states.get("value", []))][:12],
            "week": {src: week_realised(today, src) for src in ("shadow", "live")},
            "real_money": s["mode"] in LIVE_MODES,
            "margin": margin, "margin_open": sum(groups.values()) if groups else None,
            "sizing": {"quote": quote, "choices": choices, "rules": SIZING},
            "margin_open_missing": sum(1 for l in open_ if not (l.get("mark_margin_rs") or l.get("margin_rs")))}


def spawn_closeall():
    """The cockpit's Close-all: Stop now, then the buy-back in its own process (it runs for minutes)."""
    import subprocess
    from pathlib import Path
    set_kill(True, "Close-all on the cockpit", "cockpit")
    root = Path(__file__).resolve().parent
    log = root / "output" / "options_live_closeall.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    subprocess.Popen([sys.executable, "-m", "options_live", "closeall"], cwd=root, stdout=open(log, "ab"),
                     stderr=subprocess.STDOUT, start_new_session=True,
                     env={**__import__("os").environ, "ALPHA_STEP": "cron_options_live_closeall"})
    return {"ok": True, "log": str(log)}


# ─────────────────────────── CLI ───────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=sorted(STEPS) + ["plan", "set", "show"])
    ap.add_argument("args", nargs="*", help="set: <key> <json value>")
    ap.add_argument("--underlying", "-u")
    a = ap.parse_args(argv)
    if a.step == "show":                            # read-only, like plan: no table is created
        print(json.dumps(page_data(), default=str, indent=1))
        return 0
    if a.step == "plan":
        plan_only(make_ctx("plan"), (a.underlying or "NIFTY").upper())
        return 0
    ensure_tables()
    if a.step == "set":
        key, raw = a.args
        print(f"{key} = {set_setting(key, json.loads(raw), by='cli')}")
        return 0
    if not runlog._ctx.get("run_id"):
        runlog.start(f"manual:options_live_{a.step}", module="options_live")
    try:
        res = run_step(a.step, a.underlying)
    except Exception as e:
        runlog.exception(e)
        runlog.end("FAILED", error=f"{type(e).__name__}: {e}")
        raise
    rc = 1 if res["status"] == "failed" else 0
    if runlog._ctx.get("run_id", "").startswith("manual:"):
        runlog.end("SUCCESS" if rc == 0 else "FAILED", error=None if rc == 0 else res["detail"])
    return rc


if __name__ == "__main__":
    sys.exit(main())
