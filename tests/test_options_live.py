"""options_live (plan 0029) against a FAKE Kite client — no test ever reaches Zerodha.

The fake keeps an order book with a tiny matching engine (a SELL limit fills at the bid when it is
at or below it, a BUY at the ask when at or above it, `liquidity` units per look), positions, trades
and a margin account, so the whole weekly flow runs offline on a fake clock.
"""
import contextlib
import itertools
import shutil
import sqlite3
from datetime import date, datetime, timedelta

import pandas as pd
import pytest

import db
import option_book as ob
import options_live as ol
from sources import _http
from sources.fno_iv import _black76
from sources.kite_pull import NoKiteSession

IST = ol.IST
FRI, TUE = date(2026, 10, 23), date(2026, 10, 27)          # NIFTY entry day, NIFTY expiry / SENSEX entry day
NIFTY_EXP, SENSEX_EXP = "2026-10-27", "2026-10-29"


# ───────────────────────────── the fake broker ─────────────────────────────

def _chain(underlying, spot, expiry, today, step, iv=0.12):
    T = ob.years(today, expiry)
    out = []
    k0 = round(spot * 0.92 / step) * step
    k = k0
    while k <= spot * 1.08:
        for cp, ot in (("C", "CE"), ("P", "PE")):
            px = max(0.05, round(_black76(spot, k, T, iv + 0.1 * abs(k / spot - 1), cp) / 0.05) * 0.05)
            out.append({"underlying": underlying, "tradingsymbol": f"{underlying}{expiry[2:4]}{expiry[5:7]}{expiry[8:]}{int(k)}{ot}",
                        "option_type": ot, "strike": float(k), "mid": round(px, 2),
                        "bid": round(max(0.05, px - 0.05), 2), "ask": round(px + 0.05, 2)})
        k += step
    return out


_IDS = itertools.count(1)          # Kite order ids are unique across days; so are the fake's


class FakeKite:
    """Enough of KiteConnect for options_live. `book[sym] = [bid, ask, last]` is the live touch."""

    def __init__(self, underlying="NIFTY", spot=25800.0, expiry=NIFTY_EXP, today=FRI, lot=65, step=50,
                 available=1_000_000.0, margin_per_lot=150_000.0, liquidity=10 ** 9, exchange="NFO"):
        self.calls, self.orders_, self.trades_, self.pos = [], {}, [], {}
        self.available, self.margin_per_lot, self.liquidity = available, margin_per_lot, liquidity
        self.ins, self.book, self.spot = {}, {}, {}
        self.reject_on_place, self.reject_later = set(), set()
        self.on_look = None                                   # hook run at every orders() look (move the market)
        self.add_market(underlying, spot, expiry, today, lot, step, exchange)
        self._n = 0

    def add_market(self, underlying, spot, expiry, today, lot, step, exchange):
        for r in _chain(underlying, spot, expiry, today.isoformat(), step):
            self.ins.setdefault(exchange, []).append({
                "name": underlying, "instrument_type": r["option_type"], "expiry": date.fromisoformat(expiry),
                "strike": r["strike"], "tradingsymbol": r["tradingsymbol"], "lot_size": lot, "exchange": exchange})
            self.book[r["tradingsymbol"]] = [r["bid"], r["ask"], r["mid"]]
        self.spot["NSE:NIFTY 50" if underlying == "NIFTY" else "BSE:SENSEX"] = spot
        self.spot.setdefault("NSE:INDIA VIX", 15.0)
        self.lots = {**getattr(self, "lots", {}), **{r["tradingsymbol"]: lot for r in self.ins[exchange]}}
        self.exch = {**getattr(self, "exch", {}), **{r["tradingsymbol"]: exchange for r in self.ins[exchange]}}

    def _log(self, name, *a, **kw):
        self.calls.append((name, a, kw))

    def names(self):
        return [c[0] for c in self.calls]

    # reads
    def profile(self):
        self._log("profile")
        return {"user_id": "FAKE"}

    def instruments(self, exchange=None):
        self._log("instruments", exchange)
        return list(self.ins.get(exchange, []))

    def ltp(self, keys):
        self._log("ltp", keys)
        return {k: {"last_price": self.spot[k]} for k in keys}

    def quote(self, keys):
        self._log("quote", keys)
        out = {}
        for k in keys:
            bid, ask, last = self.book[k.split(":", 1)[1]]
            out[k] = {"depth": {"buy": [{"price": bid or 0}], "sell": [{"price": ask or 0}]}, "last_price": last,
                      "volume": 1000, "oi": 5000}
        return out

    def basket_order_margins(self, orders, consider_positions=True, mode=None):
        self._log("basket_order_margins", orders)
        total = sum(self.margin_per_lot / 2 * o["quantity"] / self.lots[o["tradingsymbol"]] for o in orders)
        return {"initial": {"total": total}, "final": {"total": total}}

    def _used(self):
        return sum(self.margin_per_lot / 2 * -q / self.lots[s] for s, q in self.pos.items() if q < 0)

    def margins(self, segment=None):
        self._log("margins", segment)
        used = self._used()
        return {"net": self.available - used, "utilised": {"debits": used, "span": 0.75 * used, "exposure": 0.25 * used},
                "available": {"live_balance": 0.5 * self.available, "collateral": 0.5 * self.available}}

    def positions(self):
        self._log("positions")
        return {"net": [{"tradingsymbol": s, "exchange": self.exch.get(s, "NFO"), "quantity": q, "overnight_quantity": 0,
                         "average_price": self.book.get(s, [0, 0, 0])[2]} for s, q in self.pos.items()], "day": []}

    def trades(self):
        self._log("trades")
        return list(self.trades_)

    def orders(self):
        self._log("orders")
        if self.on_look:
            self.on_look(self)
        for o in self.orders_.values():
            if o["status"] != "OPEN":
                continue
            if o["tradingsymbol"] in self.reject_later:
                o.update(status="REJECTED", status_message="RMS: margin exceeds")
                continue
            bid, ask, _ = self.book[o["tradingsymbol"]]
            sell = o["transaction_type"] == "SELL"
            if (sell and bid and o["price"] <= bid) or (not sell and ask and o["price"] >= ask):
                q = min(self.liquidity, o["quantity"] - o["filled_quantity"])
                px = bid if sell else ask
                o["average_price"] = (o["average_price"] * o["filled_quantity"] + px * q) / (o["filled_quantity"] + q)
                o["filled_quantity"] += q
                self.pos[o["tradingsymbol"]] = self.pos.get(o["tradingsymbol"], 0) + (-q if sell else q)
                self._n += 1
                self.trades_.append({"trade_id": f"T{self._n}", "order_id": o["order_id"], "tradingsymbol": o["tradingsymbol"],
                                     "transaction_type": o["transaction_type"], "quantity": q, "average_price": px})
                if o["filled_quantity"] == o["quantity"]:
                    o["status"] = "COMPLETE"
        return [dict(o) for o in self.orders_.values()]

    # writes
    def place_order(self, variety, exchange, tradingsymbol, transaction_type, quantity, product, order_type,
                    price=None, validity=None, tag=None, iceberg_legs=None, iceberg_quantity=None, **kw):
        self._log("place_order", variety=variety, tradingsymbol=tradingsymbol, transaction_type=transaction_type,
                  quantity=quantity, price=price, tag=tag, order_type=order_type,
                  iceberg_legs=iceberg_legs, iceberg_quantity=iceberg_quantity)
        assert order_type == "LIMIT" and tag == "as0029" and product == "NRML"
        if tradingsymbol in self.reject_on_place:
            raise RuntimeError("InputException: insufficient margin")
        oid = f"O{next(_IDS)}"
        self.orders_[oid] = {"order_id": oid, "tradingsymbol": tradingsymbol, "transaction_type": transaction_type,
                             "quantity": quantity, "price": price, "status": "OPEN", "filled_quantity": 0,
                             "average_price": 0.0, "tag": tag, "tags": [tag], "variety": variety}
        return oid

    def modify_order(self, variety, order_id, price=None, order_type=None, **kw):
        self._log("modify_order", order_id=order_id, price=price)
        self.orders_[order_id]["price"] = price
        return order_id

    def cancel_order(self, variety, order_id, **kw):
        self._log("cancel_order", order_id=order_id)
        if self.orders_[order_id]["status"] == "OPEN":
            self.orders_[order_id]["status"] = "CANCELLED"
        return order_id


class Clock:
    def __init__(self, d, hhmm):
        h, m = map(int, hhmm.split(":"))
        self.t = datetime(d.year, d.month, d.day, h, m, tzinfo=IST)
        self.waits = []

    def now(self):
        return self.t

    def wait(self, s):
        self.waits.append(s)
        self.t += timedelta(seconds=s)
        if self.hook:
            self.hook(self)

    hook = None


# ───────────────────────────── fixtures ─────────────────────────────

@pytest.fixture(scope="module")
def _schema_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("ol") / "schema.db"
    c = sqlite3.connect(path)
    c.executescript(db.SCHEMA_PATH.read_text())
    c.close()
    return path


@pytest.fixture
def conn(tmp_path, monkeypatch, _schema_db):
    path = tmp_path / "ol.db"
    shutil.copy(_schema_db, path)                                         # schema.sql once per module, copied per test
    c = sqlite3.connect(path)
    c.execute("INSERT INTO market_holidays (segment, holiday_date) VALUES ('FO', '2026-11-10')")
    for sym, td, exp in (("NIFTY", "2026-10-22", NIFTY_EXP), ("SENSEX", "2026-10-22", "2026-10-22"),
                         ("SENSEX", "2026-10-26", SENSEX_EXP), ("NIFTY", "2026-10-26", NIFTY_EXP)):
        c.execute("INSERT INTO fno_bhav (symbol, instrument_type, expiry_date, strike, option_type, trade_date, settle, "
                  "underlying_price, volume) VALUES (?, 'IDO', ?, 25000, 'CE', ?, 10, 25800, 5)", (sym, exp, td))
    c.commit()
    monkeypatch.setattr(db, "DB_PATH", path)
    monkeypatch.setattr(_http, "pace", lambda *_: contextlib.nullcontext())
    yield c
    c.close()


def ctx_for(fake, clock, mode=None, **settings_over):
    for k, v in settings_over.items():
        ol.set_setting(k, v, by="test")
    if mode:
        ol.set_setting("mode", mode, by="test")
    pushes = []
    ctx = ol.make_ctx("entry", kite=(lambda: fake) if not isinstance(fake, Exception) else _raiser(fake),
                      now=clock.now, wait=clock.wait, push=lambda m, urgent=False: pushes.append((m, urgent)))
    ctx["sent"] = pushes
    return ctx


def _raiser(exc):
    def f():
        raise exc
    return f


def run(step, fake, clock, u=None, **kw):
    ctx = ctx_for(fake, clock, **kw)
    ctx["step"] = step
    res = ol.STEPS[step](ctx, u) if u else ol.STEPS[step](ctx)
    return res, ctx


def ledger(conn, where="1 = 1"):
    return pd.read_sql_query(f"SELECT * FROM option_live_trades WHERE {where} ORDER BY tradingsymbol", conn)


def events(conn, event=None):
    q = "SELECT * FROM option_live_orders" + (" WHERE event = ?" if event else "") + " ORDER BY event_id"
    return pd.read_sql_query(q, conn, params=[event] if event else None)


# ───────────────────────────── pure rules ─────────────────────────────

def test_sizing_respects_cap_margin_and_buffer():
    assert ol.size_lots(18, 3_500_000, 50_000, 172_000) == 18            # cap binds
    assert ol.size_lots(18, 1_000_000, 50_000, 172_000) == 5             # margin binds: floor(950k / 172k)
    assert ol.size_lots(18, 1_000_000, 200_000, 172_000) == 4            # the buffer is kept free
    assert ol.size_lots(1, 150_000, 50_000, 172_000) == 0                # can't afford one lot
    assert ol.size_lots(0, 9e9, 0, 1) == 0
    with pytest.raises(ValueError):
        ol.size_lots(1, 1e6, 0, None)


def test_iceberg_slicing_keeps_every_slice_under_the_freeze_limit():
    assert ol.slices(130, 65, 1800) == [{"variety": "regular", "quantity": 130}]
    assert ol.slices(1755, 65, 1800) == [{"variety": "regular", "quantity": 1755}]
    (ice,) = ol.slices(18 * 65 * 2, 65, 1800)                           # 2,340 units
    assert ice["variety"] == "iceberg" and ice["legs"] == 2 and ice["leg_qty"] % 65 == 0
    assert ice["leg_qty"] <= 1800 and ice["legs"] * ice["leg_qty"] >= 2340
    big = ol.slices(25_000, 65, 1800)                                    # > 10 legs: several iceberg orders
    assert sum(x["quantity"] for x in big) == 25_000
    for x in big:
        assert x["variety"] == "regular" and x["quantity"] <= 1800 or 2 <= x["legs"] <= 10 and x["leg_qty"] <= 1800


def test_target_price_rules(conn):
    s = ol.settings()
    assert ol.target_price("SELL", (4.0, 4.2, 4.1), {"mid": 4.1}, s) == 4.0
    assert ol.target_price("SELL", (1.0, 1.2, 1.1), {"mid": 4.1}, s) == 2.05            # floor: half the first mid
    assert ol.target_price("SELL", (None, 4.2, 4.1), {"mid": 4.1}, s) is None
    assert ol.target_price("BUY", (0.9, 1.0, 1.0), {"ask": 1.0}, s) == 1.0
    assert ol.target_price("BUY", (5.0, 5.5, 5.2), {"ask": 1.0}, s) == 3.0              # cap: 3× the first ask
    assert ol.target_price("BUY", (5.0, 5.5, 5.2), {"ask": 1.0}, s, aggressive=True) == 7.1   # 5.5 × 1.25 + 4 ticks
    assert ol.target_price("BUY", (None, None, 2.0), {"ask": 1.0}, s, aggressive=True) == 2.7


# ───────────────────────────── entry ─────────────────────────────

def test_strike_pick_is_option_books_on_the_same_chain(conn):
    fake = FakeKite()
    ctx = ctx_for(fake, Clock(FRI, "15:12"))
    p = ol.build_plan(ctx, "NIFTY", NIFTY_EXP)
    chain = pd.DataFrame(_chain("NIFTY", 25800.0, NIFTY_EXP, FRI.isoformat(), 50))
    sl = chain.rename(columns={"mid": "settle"}).assign(volume=1000)[["option_type", "strike", "settle", "volume"]]
    F, deltas = ob.slice_deltas(sl, FRI.isoformat(), NIFTY_EXP)
    k = ob.nearest(deltas, ob.RULE["delta"])
    assert {l["option_type"]: l["strike"] for l in p["legs"]} == {"CE": k["C"], "PE": k["P"]}
    assert abs(p["forward"] - F) < 1e-6 and all(abs(l["delta"] - 0.05) < 0.03 for l in p["legs"])


def test_shadow_entry_records_at_the_bid_and_never_places(conn):
    fake = FakeKite()
    fake.place_order = fake.modify_order = fake.cancel_order = None      # any write would crash
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="shadow")
    assert res["status"] == "ok"
    led = ledger(conn)
    assert list(led.source) == ["shadow", "shadow"] and list(led.net_qty) == [-65, -65]
    bids = {s: fake.book[s][0] for s in led.tradingsymbol}
    assert dict(zip(led.tradingsymbol, led.sell_avg)) == bids
    assert set(fake.names()) <= {"profile", "instruments", "ltp", "quote", "basket_order_margins", "margins", "positions"}
    assert ctx["sent"] and ctx["sent"][0][0].startswith("Options SHADOW:")
    with pytest.raises(RuntimeError, match="refused"):
        ol.call(ctx, "place_order", variety="regular")                    # the door itself refuses


def test_no_kite_login_skips_and_asks_for_a_login(conn):
    res, ctx = run("entry", NoKiteSession("no login"), Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "failed"
    (msg, urgent), = ctx["sent"]
    assert "log in to Kite" in msg and urgent
    assert events(conn).empty


def test_kill_switch_means_nothing_happens(conn):
    fake = FakeKite()
    ol.set_kill(True, "Stopped on the cockpit", "test")
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "skipped" and "kill" in res["detail"]
    assert fake.calls == [] and events(conn).empty


def test_not_an_entry_day_is_quiet(conn):
    fake = FakeKite()
    res, ctx = run("entry", fake, Clock(date(2026, 10, 22), "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "idle" and fake.calls == [] and ctx["sent"] == []


def test_auto_entry_fills_and_a_rerun_never_doubles(conn):
    fake = FakeKite()
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "ok" and fake.names().count("place_order") == 2
    led = ledger(conn)
    assert list(led.source) == ["live", "live"] and list(led.net_qty) == [-65, -65] and (led.margin_rs == 150_000).all()
    again, _ = run("entry", fake, Clock(FRI, "15:13"), "NIFTY")
    assert again["status"] == "skipped" and fake.names().count("place_order") == 2
    # a crash before the DB write: only the broker's order book knows; still no second entry
    conn.execute("DELETE FROM option_live_orders")
    conn.execute("DELETE FROM option_live_trades")
    conn.commit()
    third, _ = run("entry", fake, Clock(FRI, "15:14"), "NIFTY")
    assert third["status"] == "skipped" and "order book" in third["detail"] and fake.names().count("place_order") == 2


def test_sizing_uses_kite_margin_and_cap(conn):
    fake = FakeKite(available=500_000.0, margin_per_lot=150_000.0)
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 5}, margin_buffer_rs=100_000)
    assert res["status"] == "ok"
    # sized on the expiry-day peak: 150k + 2 % × F × 65 × 2 legs (≈ 67k) a lot → floor(400k / ≈217k) = 1 (entry margin alone: 2)
    assert set(ledger(conn).net_qty) == {-65}
    proposed = events(conn, "proposed").detail.iloc[0]
    assert '"expiry_margin_rs"' in proposed


def test_not_enough_margin_skips_in_a_real_mode(conn):
    fake = FakeKite(available=100_000.0)
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "skipped" and "margin" in ctx["sent"][0][0] and "place_order" not in fake.names()


def test_repricing_follows_a_falling_bid_and_handles_partial_fills(conn):
    fake = FakeKite(liquidity=65)
    clock = Clock(FRI, "15:12")
    moved = []

    def bid_drops_once(f):                                                # the first look: the bid fell 2 ticks away
        if f.orders_ and not moved:
            for o in f.orders_.values():
                b = f.book[o["tradingsymbol"]]
                f.book[o["tradingsymbol"]] = [round(b[0] - 0.10, 2), round(b[1] - 0.10, 2), b[2]]
            moved.append(1)
    fake.on_look = bid_drops_once
    res, _ = run("entry", fake, clock, "NIFTY", mode="auto", lots_cap={"NIFTY": 3})
    assert res["status"] == "ok"
    assert fake.names().count("modify_order") == 2                        # each leg re-priced once, to the new bid
    ev = events(conn)
    assert (ev.event == "partial").sum() >= 2                             # 65 of 195 per look
    assert set(ledger(conn).net_qty) == {-195}
    assert clock.waits and all(w <= 20 for w in clock.waits)


def test_a_rejected_leg_is_recorded_and_the_lone_leg_is_bought_back(conn):
    fake = FakeKite()
    ctx = ctx_for(fake, Clock(FRI, "15:12"), mode="auto")
    plan = ol.build_plan(ctx, "NIFTY", NIFTY_EXP)
    fake.reject_on_place.add(plan["legs"][1]["tradingsymbol"])
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY")
    assert res["status"] == "failed" and "flattened" in res["detail"]
    assert (events(conn).event == "reject").sum() == 1
    assert set(ledger(conn).net_qty) == {0}                               # the lone call was bought back
    assert any("unbalanced" in m for m, _ in ctx["sent"])


def test_an_exchange_reject_after_placing_is_handled(conn):
    fake = FakeKite()
    ctx = ctx_for(fake, Clock(FRI, "15:12"), mode="auto")
    sym = ol.build_plan(ctx, "NIFTY", NIFTY_EXP)["legs"][0]["tradingsymbol"]
    fake.reject_later.add(sym)
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY")
    assert res["status"] == "failed"
    assert (events(conn).event == "reject").sum() == 1 and set(ledger(conn).net_qty) == {0}


def test_leftovers_are_cancelled_at_the_cut_off(conn):
    fake = FakeKite()

    def no_bids(f):                                                       # the market walks away: nothing fills
        for s in (f.book if f.orders_ else []):
            f.book[s][0] = None
    fake.on_look = no_bids
    clock = Clock(FRI, "15:27")
    res, ctx = run("entry", fake, clock, "NIFTY", mode="auto")
    assert res["status"] == "failed" and "nothing filled" in res["detail"]
    assert fake.names().count("cancel_order") == 2 and clock.t.strftime("%H:%M") == "15:29"
    assert ledger(conn).empty


def test_iceberg_orders_go_out_above_the_freeze_quantity(conn):
    fake = FakeKite(available=1e9, margin_per_lot=10_000.0)
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 30})
    assert res["status"] == "ok"
    placed = [c[2] for c in fake.calls if c[0] == "place_order"]
    assert all(p["variety"] == "iceberg" and p["quantity"] == 30 * 65 and p["iceberg_legs"] == 2 for p in placed)
    assert all(p["iceberg_quantity"] <= 1800 for p in placed)


# ───────────────────────────── approve ─────────────────────────────

def test_approve_mode_places_nothing_before_approval(conn):
    fake = FakeKite()
    clock = Clock(FRI, "15:12")
    seen = {}

    def approve_at_1515(c):
        if c.t.strftime("%H:%M") >= "15:15" and "done" not in seen:
            seen["places_before"] = fake.names().count("place_order")
            tid = pd.read_sql_query("SELECT ticket_id FROM option_live_orders WHERE event = 'ticket'", conn).ticket_id[0]
            ol.approve(tid, by="test", now=c.t)
            seen["done"] = True
    clock.hook = approve_at_1515
    res, ctx = run("entry", fake, clock, "NIFTY", mode="approve")
    assert seen["places_before"] == 0 and res["status"] == "ok" and fake.names().count("place_order") == 2
    assert "Approve" in ctx["sent"][0][0] and "/options#live" in ctx["sent"][0][0]
    assert {"ticket", "approved"} <= set(events(conn).event)


def test_an_unapproved_ticket_expires_and_late_approval_is_refused(conn):
    fake = FakeKite()
    clock = Clock(FRI, "15:12")
    res, ctx = run("entry", fake, clock, "NIFTY", mode="approve")
    assert res["status"] == "skipped" and "place_order" not in fake.names()
    assert clock.t.strftime("%H:%M") == "15:25" and "expired" in set(events(conn).event)
    tid = events(conn, "ticket").ticket_id[0]
    with pytest.raises(ValueError):
        ol.approve(tid, now=clock.t + timedelta(minutes=1))


def test_approval_after_the_cut_off_is_refused_even_for_a_fresh_ticket(conn):
    ol.ensure_tables()
    ctx = ctx_for(FakeKite(), Clock(FRI, "15:12"))
    ol.log_event(ctx, "ticket", ticket_id="NIFTY-x", underlying="NIFTY", expiry=NIFTY_EXP)
    with pytest.raises(ValueError, match="too late"):
        ol.approve("NIFTY-x", now=datetime(2026, 10, 23, 15, 26, tzinfo=IST))
    assert ol.approve("NIFTY-x", now=datetime(2026, 10, 23, 15, 20, tzinfo=IST))["ok"]
    with pytest.raises(ValueError, match="already"):
        ol.approve("NIFTY-x", now=datetime(2026, 10, 23, 15, 21, tzinfo=IST))


# ───────────────────────────── Tuesday: buy-back, rotation ─────────────────────────────

def _tuesday_broker():
    fake = FakeKite(today=TUE)                                            # NIFTY legs of today's expiry, quoted Tue
    fake.add_market("SENSEX", 84000.0, SENSEX_EXP, TUE, 20, 100, "BFO")
    return fake


def _enter_nifty_friday(conn, fake, mode):
    fri = FakeKite()
    res, _ = run("entry", fri, Clock(FRI, "15:12"), "NIFTY", mode=mode)
    assert res["status"] == "ok"
    for s, q in fri.pos.items():                                          # the position carries into Tuesday
        fake.pos[s] = q
        fake.book[s] = [0.05, 0.10, 0.05]


def test_buyback_reaches_the_final_aggressive_limit_and_frees_margin(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")

    def ask_runs_away(f):                                                 # every look the offer moves up a tick
        if Clock_now[0].strftime("%H:%M") < "15:14":
            for o in f.orders_.values():
                b = f.book[o["tradingsymbol"]]
                f.book[o["tradingsymbol"]] = [b[0], round(o["price"] + 0.05, 2), b[2]]
    clock = Clock(TUE, "15:08")
    Clock_now = [clock.t]
    clock.hook = lambda c: Clock_now.__setitem__(0, c.t)
    fake.on_look = ask_runs_away
    res, ctx = run("buyback", fake, clock, "NIFTY")
    assert res["status"] == "ok", res
    mods = [c for c in fake.calls if c[0] == "modify_order"]
    assert mods and fake.orders_[mods[-1][2]["order_id"]]["status"] == "COMPLETE"
    final = [e for e in events(conn, "modify").detail if e]
    assert "final aggressive limit" in final
    assert set(ledger(conn, "underlying = 'NIFTY'").status) == {"CLOSED"}
    rot = ol.get_state(f"rotation:{TUE.isoformat()}")
    assert rot["ok"] and rot["flat"] and rot["freed_rs"] >= 75_000
    assert "SENSEX can enter" in ctx["sent"][-1][0]


def test_rotation_gate_blocks_sensex_until_nifty_is_flat(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    res, ctx = run("entry", fake, Clock(TUE, "15:17"), "SENSEX")          # the buy-back never ran
    assert res["status"] == "skipped" and "rotation gate" in res["detail"]
    assert "rotation gate failed" in ctx["sent"][0][0]
    assert "place_order" not in fake.names()
    bb, _ = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "ok"
    ok, _ = run("entry", fake, Clock(TUE, "15:17"), "SENSEX")
    assert ok["status"] == "ok" and set(ledger(conn, "underlying = 'SENSEX'").net_qty) == {-20}


def test_rotation_gate_fails_when_the_margin_was_not_freed(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    fake.margins = lambda segment=None: {"net": 400_000.0}               # Kite never shows the margin back
    bb, ctx = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "failed" and "SENSEX entry will be skipped" in ctx["sent"][-1][0]
    res, _ = run("entry", fake, Clock(TUE, "15:17"), "SENSEX")
    assert res["status"] == "skipped" and "rotation gate" in res["detail"]


def test_sensex_without_a_nifty_position_enters(conn):
    fake = _tuesday_broker()
    res, _ = run("entry", fake, Clock(TUE, "15:17"), "SENSEX", mode="auto")
    assert res["status"] == "ok"


def _manual_nifty(fake, lots=5):
    """Amit's own (untagged) NIFTY strangle expiring today: far OTM, so it settles at zero."""
    call = next(r["tradingsymbol"] for r in fake.ins["NFO"] if r["instrument_type"] == "CE" and r["strike"] >= 27000)
    put = next(r["tradingsymbol"] for r in fake.ins["NFO"] if r["instrument_type"] == "PE" and r["strike"] <= 24600)
    fake.pos.update({call: -65 * lots, put: -65 * lots})
    return call, put


def test_sensex_sizing_counts_margin_freed_by_nifty_expiring_first(conn):
    # ₹15 L total; 5 manual NIFTY lots expiring today block ₹7.5 L → ₹7.5 L free at 15:17.
    # SENSEX: ₹150 K a lot now, + 2 % × 84,000 × 20 × 2 = ₹67.2 K on Thursday.
    # Now: (750 K − 50 K) / 150 K → 4. Thursday: NIFTY gone, (1.5 M − 50 K) / 217.2 K → 6. Sold: 4.
    # (The old rule checked Thursday's peak against today's free margin: (750 K − 50 K) / 217.2 K → 3.)
    fake = _tuesday_broker()
    fake.available = 1_500_000.0
    _manual_nifty(fake)
    res, ctx = run("entry", fake, Clock(TUE, "15:17"), "SENSEX", mode="auto", margin_buffer_rs=50_000,
                 lots_cap={"NIFTY": 15, "SENSEX": 15})
    assert res["status"] == "ok", res
    assert set(ledger(conn, "underlying = 'SENSEX'").net_qty) == {-80}
    d = events(conn, "proposed").detail.iloc[0]
    assert '"peak_available": 1500000' in d and '"freed_before_expiry": 750000' in d


def test_sensex_sizing_gives_no_credit_for_a_position_it_cannot_value(conn):
    fake = _tuesday_broker()
    fake.available = 1_500_000.0
    _manual_nifty(fake)
    fake.pos["NIFTY26OCTFUT"] = 65                                        # a future: not a NIFTY/SENSEX option
    res, _ = run("entry", fake, Clock(TUE, "15:17"), "SENSEX", mode="auto", margin_buffer_rs=50_000,
                 lots_cap={"NIFTY": 15, "SENSEX": 15})
    assert res["status"] == "ok" and set(ledger(conn, "underlying = 'SENSEX'").net_qty) == {-60}   # the old 3 lots


def test_peak_available_adds_the_expiry_day_extra_of_legs_expiring_with_the_trade(conn):
    fake = _tuesday_broker()
    call, put = _manual_nifty(fake)
    s_call = next(r["tradingsymbol"] for r in fake.ins["BFO"] if r["instrument_type"] == "CE" and r["strike"] >= 90000)
    fake.pos[s_call] = -40                                                # 2 SENSEX lots of Thursday's expiry
    ctx = ctx_for(fake, Clock(TUE, "15:17"))
    p = ol.peak_available(ctx, SENSEX_EXP, 400_000.0)
    assert p["freed"] == 750_000.0                                        # NIFTY's basket margin, nothing to settle
    assert abs(p["stay_extra"] - 0.02 * 84_000 * 40) < 1e-6
    assert abs(p["available"] - (400_000 + 750_000 - 0.02 * 84_000 * 40)) < 1e-6
    assert ol.peak_available(ctx, NIFTY_EXP, 400_000.0)["freed"] == 0.0   # nothing expires before today


def test_shadow_buyback_and_rotation(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "shadow")
    fake.pos.clear()                                                      # shadow legs never reach the broker
    fake.place_order = None
    bb, _ = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "ok" and set(ledger(conn, "underlying = 'NIFTY'").status) == {"CLOSED"}
    res, _ = run("entry", fake, Clock(TUE, "15:17"), "SENSEX")
    assert res["status"] == "ok" and set(ledger(conn, "underlying = 'SENSEX'").source) == {"shadow"}


# ───────────────────────────── limits, record, reconcile, settle ─────────────────────────────

def test_weekly_loss_limit_pauses_entries(conn):
    conn.execute("INSERT INTO option_live_trades (underlying, expiry, tradingsymbol, source, status, net_rs, closed_at) "
                 "VALUES ('SENSEX', '2026-10-22', 'X', 'live', 'SETTLED', -250000, '2026-10-22')")
    conn.commit()
    fake = FakeKite()
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "skipped" and "weekly loss" in res["detail"]
    assert ol.settings()["kill"] and "loss limit" in ol.settings()["kill_reason"]
    assert ctx["sent"][0][1] and "place_order" not in fake.names()
    # last week's loss does not count
    conn.execute("UPDATE option_live_trades SET closed_at = '2026-10-16'")
    conn.commit()
    ol.set_kill(False, None, "test")
    again, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY")
    assert again["status"] == "ok"


def test_record_reconcile_and_settle(conn):
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    manual = next(s for s in fake.book if s not in fake.pos)              # Amit sells one of his own by hand
    fake.trades_.append({"trade_id": "M1", "order_id": "MAN1", "tradingsymbol": manual, "transaction_type": "SELL",
                         "quantity": 65, "average_price": 3.0})
    fake.pos[manual] = -65
    rec, _ = run("record", fake, Clock(FRI, "15:45"))
    assert rec["status"] == "ok"
    led = ledger(conn)
    assert set(led[led.source == "manual"].tradingsymbol) == {manual}
    assert len(events(conn, "fill")) == 2 + 2 + 1                         # order summaries + the real trades + manual
    assert set(ledger(conn, "source = 'live'").net_qty) == {-65}          # summaries superseded, not double counted
    ok, _ = run("reconcile", fake, Clock(FRI, "15:50"))
    assert ok["status"] == "ok" and ol.get_state("reconcile")["ok"]
    # settle: the index settles between the strikes, both legs expire worthless
    conn.execute("INSERT INTO fno_bhav (symbol, instrument_type, expiry_date, strike, option_type, trade_date, settle, "
                 "underlying_price) VALUES ('NIFTY', 'IDO', ?, 25800, 'CE', ?, 0, 25810)", (NIFTY_EXP, NIFTY_EXP))
    conn.commit()
    st, ctx = run("settle", fake, Clock(date(2026, 10, 28), "10:30"))
    assert st["status"] == "ok"
    live = ledger(conn, "source = 'live'")
    assert set(live.status) == {"SETTLED"} and (live.exit_price == 0).all()
    assert (abs(live.net_rs - (live.sell_qty * live.sell_avg - live.charges_rs)) < 1e-6).all()
    assert (live.charges_rs > 20).all()                                   # brokerage + GST + STT + exchange charge


def test_reconcile_mismatch_stops_trading_and_shows_on_health(conn):
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    sym = next(iter(fake.pos))
    fake.pos[sym] = 0                                                     # closed outside the system
    res, ctx = run("reconcile", fake, Clock(FRI, "15:50"))
    assert res["status"] == "failed" and ol.settings()["kill"] and ctx["sent"][0][1]
    h = ol.health_check()
    assert h["n_bad"] >= 1 and h["severity"] == "CRITICAL" and "broker ≠ ledger" in h["sample"]
    blocked, _ = run("entry", FakeKite(), Clock(FRI, "15:12"), "NIFTY")
    assert blocked["status"] == "skipped" and "kill" in blocked["detail"]


def test_closeall_buys_back_every_tagged_leg_and_stops(conn):
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    for s in fake.pos:
        fake.book[s] = [1.0, 1.1, 1.05]
    res, _ = run("closeall", fake, Clock(FRI, "15:22"))
    assert res["status"] == "ok" and ol.settings()["kill"]
    assert set(ledger(conn).status) == {"CLOSED"} and all(q == 0 for q in fake.pos.values())


def test_mark_without_a_login_uses_the_stored_settle(conn):
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="shadow")
    res, _ = run("mark", NoKiteSession("x"), Clock(date(2026, 10, 26), "10:00"))
    assert res["status"] == "ok"


def test_settings_validation(conn):
    with pytest.raises(ValueError):
        ol.set_setting("mode", "yolo")
    with pytest.raises(ValueError):
        ol.set_setting("lots_cap", {"NIFTY": 41})
    with pytest.raises(ValueError):
        ol.set_setting("tag", "x")


# ───────────────────────────── ops cockpit /options Live panel ─────────────────────────────

@pytest.fixture
def ops(conn, tmp_path, monkeypatch):
    import webauth
    from fastapi.testclient import TestClient
    from cockpit_ops.app import app
    monkeypatch.delenv("COCKPIT_PREVIEW", raising=False)
    monkeypatch.setattr(webauth, "AUTH_FILE", tmp_path / "auth.json")
    webauth.set_password("correct horse battery")
    return TestClient(app, cookies={webauth.COOKIE: webauth.make_token()}), TestClient(app)


def test_live_panel_renders_with_the_paper_book(ops):
    authed, _ = ops
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="shadow")
    html = authed.get("/options").text
    assert 'id="live"' in html and "SHADOW · no orders" in html and "Open live legs" in html
    assert "NIFTY261027" in html and "Live panel unavailable" not in html
    assert authed.get("/api/options/live").json()["settings"]["mode"] == "shadow"


def test_live_controls_need_the_cookie_and_the_confirm_word(ops, monkeypatch):
    authed, anon = ops
    assert anon.post("/api/options/live/kill", json={"on": True, "confirm": "STOP"}).status_code == 401
    assert authed.post("/api/options/live/kill", json={"on": True}).status_code == 400
    assert not ol.settings()["kill"]
    assert authed.post("/api/options/live/kill", json={"on": True, "confirm": "STOP"}).json()["kill"] is True
    assert ol.settings()["kill"] and ol.settings()["kill_reason"] == "Stopped on the cockpit"
    ol.put_state("reconcile", {"ok": False, "detail": "x"}, "t")
    assert authed.post("/api/options/live/kill", json={"on": False, "confirm": "RESUME"}).status_code == 409
    ol.put_state("reconcile", {"ok": True}, "t")
    assert authed.post("/api/options/live/kill", json={"on": False, "confirm": "RESUME"}).status_code == 200
    assert not ol.settings()["kill"]
    # settings: auto needs AUTO typed; a bad value is refused
    assert authed.post("/api/options/live/settings", json={"key": "mode", "value": "auto", "confirm": "SAVE"}).status_code == 400
    assert authed.post("/api/options/live/settings", json={"key": "lots_cap", "value": {"NIFTY": 99}, "confirm": "SAVE"}).status_code == 400
    assert authed.post("/api/options/live/settings", json={"key": "lots_cap", "value": {"NIFTY": 2}, "confirm": "save"}).status_code == 200
    assert ol.settings()["lots_cap"] == {"NIFTY": 2, "SENSEX": 1}
    # close-all: typed confirm, then the job is spawned (patched here)
    spawned = []
    monkeypatch.setattr(ol, "spawn_closeall", lambda: spawned.append(1) or {"ok": True})
    assert authed.post("/api/options/live/closeall", json={"confirm": "close"}).status_code == 400 and not spawned
    assert authed.post("/api/options/live/closeall", json={"confirm": "CLOSE ALL"}).status_code == 200 and spawned
    assert anon.post("/api/options/live/approve", json={"ticket_id": "x", "confirm": "APPROVE"}).status_code == 401
    assert authed.post("/api/options/live/approve", json={"ticket_id": "x", "confirm": "APPROVE"}).status_code == 409


# ───────────────────────────── testorder (one-off order-permission proof) ─────────────────────────────

def _atm_call(fake):
    spot = fake.spot["NSE:NIFTY 50"]
    calls = [r for r in fake.ins["NFO"] if r["instrument_type"] == "CE" and str(r["expiry"]) == NIFTY_EXP]
    return min(calls, key=lambda r: abs(r["strike"] - spot))["tradingsymbol"]


def test_testorder_places_far_below_the_bid_then_cancels(conn):
    fake = FakeKite()
    res, ctx = run("testorder", fake, Clock(FRI, "10:30"), u="NIFTY")
    assert res["status"] == "ok" and "cancelled" in res["detail"]
    place = [c for c in fake.calls if c[0] == "place_order"]
    assert len(place) == 1
    kw = place[0][2]
    sym = _atm_call(fake)
    assert kw["tradingsymbol"] == sym and kw["transaction_type"] == "BUY" and kw["quantity"] == 65
    assert kw["price"] <= fake.book[sym][0] * 0.5 + 1e-9                    # half the bid: cannot fill
    assert "cancel_order" in fake.names() and not fake.pos                    # nothing bought
    ev = events(conn)
    assert list(ev.event) == ["place", "cancel", "status"] and set(ev.source) == {"test"}
    assert ev.status.iloc[-1] == "CANCELLED"
    assert ctx["sent"] and "test order OK" in ctx["sent"][-1][0]


def test_testorder_reports_a_refusal_loudly(conn):
    fake = FakeKite()
    fake.reject_on_place.add(_atm_call(fake))
    res, ctx = run("testorder", fake, Clock(FRI, "10:30"), u="NIFTY")
    assert res["status"] == "failed" and "refused" in res["detail"]
    assert "cancel_order" not in fake.names()
    assert ctx["sent"][-1][1] is True and "REFUSED" in ctx["sent"][-1][0]


def test_testorder_needs_a_login_and_respects_stop(conn):
    res, ctx = run("testorder", NoKiteSession("no login"), Clock(FRI, "10:30"), u="NIFTY")
    assert res["status"] == "skipped" and "log in" in ctx["sent"][-1][0]
    fake = FakeKite()
    res, _ = run("testorder", fake, Clock(FRI, "10:30"), u="NIFTY", kill=True)
    assert res["status"] == "skipped" and "place_order" not in fake.names()


def test_testorder_is_not_scheduled():
    import pathlib
    cron = pathlib.Path(__file__).resolve().parents[1].joinpath("ops", "options_live.cron").read_text()
    assert "testorder" not in cron


def test_live_panel_shows_margin_used_and_free(ops):
    authed, _ = ops
    html = authed.get("/options").text
    assert "Not read yet" in html                                         # no Kite margin read so far
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    res, _ = run("mark", fake, Clock(FRI, "15:31"))
    assert res["status"] == "ok"
    m = ol.get_state("margin")
    assert m["used"] > 0 and m["free"] == fake.available - m["used"] and m["total"] == fake.available
    html = authed.get("/options").text
    from formatting import inr_short
    assert "used by your positions" in html and inr_short(m["used"]) in html and inr_short(m["free"]) in html
    assert ol.page_data()["margin_open"] > 0


# ───────────────────────────── VIX guard (Amit 2026-10-25) ─────────────────────────────

def test_vix_guard_halves_the_lots_between_27_and_30(conn):
    ol.set_setting("lots_cap", {"NIFTY": 4})
    fake = FakeKite()
    fake.spot["NSE:INDIA VIX"] = 28.0
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "ok"
    assert set(ledger(conn, "source = 'live'").net_qty) == {-2 * 65}           # 4 → 2 lots
    assert '"vix_action": "halve"' in events(conn, "proposed").detail.iloc[0]


def test_vix_guard_halts_at_30_and_places_nothing(conn):
    fake = FakeKite()
    fake.spot["NSE:INDIA VIX"] = 30.0
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "skipped" and "VIX guard" in res["detail"] and ctx["sent"][0][1]   # urgent push
    assert "place_order" not in fake.names() and events(conn, "proposed").empty


def test_vix_guard_unknown_vix_halts_but_a_recent_close_is_used(conn):
    fake = FakeKite()
    del fake.spot["NSE:INDIA VIX"]                                               # no live quote
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "skipped" and "no India VIX stored" in res["detail"]
    conn.execute("INSERT INTO macro_history (indicator_id, date, value) VALUES ('india_vix', ?, 16.5)",
                 ((FRI - timedelta(days=1)).isoformat(),))
    conn.commit()
    fake = FakeKite()
    del fake.spot["NSE:INDIA VIX"]
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    assert res["status"] == "ok"
    assert '"vix": 16.5' in events(conn, "proposed").detail.iloc[0]


def test_vix_settings_validation(conn):
    with pytest.raises(ValueError):
        ol.set_setting("vix_halve", 35)                                          # above the halt level
    with pytest.raises(ValueError):
        ol.set_setting("vix_halt", "high")
    ol.set_setting("vix_halt", 32)
    assert ol.settings()["vix_halt"] == 32
