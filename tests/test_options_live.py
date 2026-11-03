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
        out = {}
        for k in keys:
            if k in self.spot:
                out[k] = {"last_price": self.spot[k]}
            else:
                out[k] = {"last_price": self.book[k.split(":", 1)[1]][2]}
        return out

    def quote(self, keys):
        self._log("quote", keys)
        out = {}
        for k in keys:
            bid, ask, last = self.book[k.split(":", 1)[1]]
            out[k] = {"depth": {"buy": [{"price": bid or 0}], "sell": [{"price": ask or 0}]}, "last_price": last,
                      "volume": 1000, "oi": 5000}
        return out

    hedge = 0.5                                               # a basket with long wings: this share of the naked margin

    def basket_order_margins(self, orders, consider_positions=True, mode=None):
        self._log("basket_order_margins", orders)
        total = sum(self.margin_per_lot / 2 * o["quantity"] / self.lots[o["tradingsymbol"]]
                    for o in orders if o["transaction_type"] == "SELL")
        if any(o["transaction_type"] == "BUY" for o in orders):
            total *= self.hedge
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
        while True:
            self._fill_open()
            if not self._next_slices():
                break
        return [{k: v for k, v in o.items() if not k.startswith("_")} for o in self.orders_.values()]

    def _next_slices(self):
        """Kite's iceberg: our order id carries slice 1; each later slice is a NEW order (its own id,
        parent_order_id = ours) placed once the previous slice completes."""
        made = False
        for o in list(self.orders_.values()):
            ice = o.get("_ice")
            if not ice or ice["left"] <= 0 or self.orders_[ice["last"]]["status"] != "COMPLETE":
                continue
            q = min(ice["leg"], ice["left"])
            cid = f"O{next(_IDS)}"
            self.orders_[cid] = {"order_id": cid, "parent_order_id": o["order_id"], "tradingsymbol": o["tradingsymbol"],
                                 "transaction_type": o["transaction_type"], "quantity": q, "price": ice["price"],
                                 "status": "OPEN", "filled_quantity": 0, "average_price": 0.0, "tag": o["tag"],
                                 "tags": [o["tag"]], "variety": "iceberg"}
            ice.update(left=ice["left"] - q, last=cid)
            made = True
        return made

    def _fill_open(self):
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
        first = iceberg_quantity if variety == "iceberg" else quantity
        self.orders_[oid] = {"order_id": oid, "tradingsymbol": tradingsymbol, "transaction_type": transaction_type,
                             "quantity": first, "price": price, "status": "AMO REQ RECEIVED" if variety == "amo" else "OPEN", "filled_quantity": 0,
                             "average_price": 0.0, "tag": tag, "tags": [tag], "variety": variety}
        if variety == "iceberg":
            assert iceberg_legs * iceberg_quantity >= quantity and iceberg_quantity < quantity
            self.orders_[oid]["_ice"] = {"leg": iceberg_quantity, "left": quantity - first, "last": oid, "price": price}
        return oid

    def modify_order(self, variety, order_id, price=None, order_type=None, **kw):
        self._log("modify_order", order_id=order_id, price=price)
        self.orders_[order_id]["price"] = price
        if self.orders_[order_id].get("_ice"):                # the working slice and the ones still to come
            ice = self.orders_[order_id]["_ice"]
            ice["price"] = price
            self.orders_[ice["last"]]["price"] = price
        return order_id

    def cancel_order(self, variety, order_id, **kw):
        self._log("cancel_order", order_id=order_id)
        if self.orders_[order_id]["status"] == "OPEN":
            self.orders_[order_id]["status"] = "CANCELLED"
        parent = self.orders_[self.orders_[order_id].get("parent_order_id") or order_id]
        if parent.get("_ice"):                                # cancelling an iceberg stops the slices to come
            parent["_ice"]["left"] = 0
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
    html = authed.get("/options/live").text
    assert 'id="live"' in html and "SHADOW · no orders" in html and "Open live legs" in html
    assert "NIFTY261027" in html and "Live panel unavailable" not in html
    assert 'id="os-builder"' in html and "Payoff chart" in html                 # the builder opens on the open legs
    assert authed.get("/api/options/live").json()["settings"]["mode"] == "shadow"
    book = authed.get("/options").text                                         # the paper book links to it
    assert 'href="/options/live"' in book and "SHADOW · no orders" in book


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
    html = authed.get("/options/live").text
    assert "Not read yet" in html                                         # no Kite margin read so far
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto")
    res, _ = run("mark", fake, Clock(FRI, "15:31"))
    assert res["status"] == "ok"
    m = ol.get_state("margin")
    assert m["used"] > 0 and m["free"] == fake.available - m["used"] and m["total"] == fake.available
    html = authed.get("/options/live").text
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


# ───────────────────────────── protective wings (Amit 2026-10-28) ─────────────────────────────

def _wing_syms(fake, p):
    return {w["option_type"]: w["tradingsymbol"] for w in p["wings"]}


def test_wing_strikes_are_the_offered_strikes_nearest_the_distance():
    chain = pd.DataFrame(_chain("NIFTY", 25800.0, NIFTY_EXP, FRI.isoformat(), 50))
    k = {"C": 26500.0, "P": 25100.0}
    assert ol.wing_strikes(chain, k, 25800.0, 0) is None                      # off
    w = ol.wing_strikes(chain, k, 25800.0, 1.75)                              # 1.75 % of 25,800 = 451.5 points
    assert w == {"C": 26950.0, "P": 24650.0}
    assert ol.wing_strikes(chain, k, 25800.0, 0.01) == {"C": 26550.0, "P": 25050.0}   # at least one strike out
    chain.loc[(chain.option_type == "CE") & (chain.strike > 26500), "ask"] = None
    with pytest.raises(RuntimeError, match="no offered CE"):
        ol.wing_strikes(chain, k, 25800.0, 1.75)


def test_wings_are_bought_first_and_lots_size_on_the_hedged_margin(conn):
    # naked: 150 K + 2 % × F × 65 × 2 (≈ 67 K) a lot → floor(950 K / 217 K) = 4 lots.
    # wings: Kite's basket is half (75 K) → floor(950 K / 142 K) = 6 lots.
    fake = FakeKite()
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 10}, wing_pct=1.75)
    assert res["status"] == "ok", res
    places = [c[2] for c in fake.calls if c[0] == "place_order"]
    assert [p["transaction_type"] for p in places] == ["BUY", "BUY", "SELL", "SELL"]
    led = ledger(conn).set_index("tradingsymbol")
    assert sorted(led.net_qty) == [-390, -390, 390, 390]
    short = {r.option_type: r.strike for r in led.itertuples() if r.net_qty < 0}
    long_ = {r.option_type: r.strike for r in led.itertuples() if r.net_qty > 0}
    assert long_["CE"] > short["CE"] and long_["PE"] < short["PE"]
    d = events(conn, "proposed")
    assert set(d.transaction_type) == {"BUY", "SELL"} and '"wing_pct": 1.75' in d.detail.iloc[0]
    assert '"max_loss_per_lot"' in d.detail.iloc[0] and "wings" in ctx["sent"][-1][0]


def test_no_wing_fill_means_no_sale_and_a_lone_wing_is_sold_back(conn):
    fake = FakeKite()
    ctx = ctx_for(fake, Clock(FRI, "15:12"), mode="auto", wing_pct=1.75)
    w = _wing_syms(fake, ol.build_plan(ctx, "NIFTY", NIFTY_EXP))
    fake.reject_on_place.add(w["PE"])                                         # the put wing is refused
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY")
    assert res["status"] == "failed" and "wings not filled" in res["detail"] and ctx["sent"][-1][1]
    sells = [c[2]["tradingsymbol"] for c in fake.calls if c[0] == "place_order" and c[2]["transaction_type"] == "SELL"]
    assert sells == [w["CE"]]                                                 # only the call wing, sold back
    assert all(q == 0 for q in fake.pos.values())


def test_partly_filled_wings_cap_the_lots_sold(conn):
    fake = FakeKite(liquidity=65)
    looks = []
    ctx = ctx_for(fake, Clock(FRI, "15:12"), mode="auto", wing_pct=1.75, lots_cap={"NIFTY": 3})
    w = _wing_syms(fake, ol.build_plan(ctx, "NIFTY", NIFTY_EXP))

    def put_wing_dries_up(f):                                                 # after the first fill no one offers it
        if f.orders_:
            looks.append(1)
        if len(looks) >= 2:
            f.book[w["PE"]][1] = None
    fake.on_look = put_wing_dries_up
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY")
    assert res["status"] == "ok" and "wings filled for 1 of 3 lots" in res["detail"], res
    pos = {s: q for s, q in fake.pos.items() if q}
    assert pos[w["PE"]] == 65 and pos[w["CE"]] == 195
    assert sorted(q for s, q in pos.items() if s not in w.values()) == [-65, -65]


def test_tuesday_buyback_leaves_the_wings_and_sensex_still_enters(conn):
    ol.set_setting("wing_pct", 1.75)
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    assert len(ledger(conn, "underlying = 'NIFTY' AND net_qty > 0")) == 2
    bb, _ = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "ok", bb
    nifty = ledger(conn, "underlying = 'NIFTY'")
    assert set(nifty[nifty.net_qty < 0].status) == set() and set(nifty[nifty.net_qty > 0].status) == {"OPEN"}
    assert ol.rotation_gate(ctx_for(fake, Clock(TUE, "15:16")))[0]            # long wings do not block SENSEX
    res, _ = run("entry", fake, Clock(TUE, "15:17"), "SENSEX")
    assert res["status"] == "ok", res
    assert sorted(ledger(conn, "underlying = 'SENSEX'").net_qty) == [-20, -20, 20, 20]
    d = events(conn, "proposed")
    assert "no credit" not in d[d.underlying == "SENSEX"].detail.iloc[0]      # NIFTY's wings leave with nothing to hedge


def test_settle_charges_stt_on_an_exercised_wing(conn):
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="shadow", wing_pct=1.75)
    conn.execute("INSERT INTO fno_bhav (symbol, instrument_type, expiry_date, strike, option_type, trade_date, settle, "
                 "underlying_price) VALUES ('NIFTY', 'IDO', ?, 25800, 'CE', ?, 0, 23000)", (NIFTY_EXP, NIFTY_EXP))
    conn.commit()
    st, _ = run("settle", fake, Clock(date(2026, 10, 28), "10:30"))
    assert st["status"] == "ok"
    led = ledger(conn)
    put_w = led[(led.net_qty > 0) & (led.option_type == "PE")].iloc[0]
    assert put_w.exit_price == put_w.strike - 23000
    stt = ob.STT_EXERCISE * put_w.exit_price * put_w.net_qty
    assert abs(put_w.net_rs - (put_w.gross_rs - put_w.charges_rs - stt)) < 1e-6
    short_p = led[(led.net_qty < 0) & (led.option_type == "PE")].iloc[0]
    assert abs(short_p.net_rs - (short_p.gross_rs - short_p.charges_rs)) < 1e-6     # no exercise STT on a short
    width = short_p.strike - put_w.strike                                          # the loss stops at the wing
    assert put_w.gross_rs + short_p.gross_rs >= -(width * 65) - 1e-6


def test_wing_setting_validation(conn):
    for bad in (-1, 6, "wide", True):
        with pytest.raises(ValueError):
            ol.set_setting("wing_pct", bad)
    ol.set_setting("wing_pct", 1.75)
    assert ol.settings()["wing_pct"] == 1.75


def test_live_panel_shows_the_wings(ops):
    authed, _ = ops
    run("entry", FakeKite(), Clock(FRI, "15:12"), "NIFTY", mode="shadow", wing_pct=1.75)
    html = authed.get("/options/live").text
    assert "wings 1.75% beyond the sold strikes" in html and "bought " in html and "(1.75% wings)" in html   # the plan line


# ───────────────────────────── sizing choices card (Amit 2026-10-29) ─────────────────────────────

def _quote(naked=150_000.0, winged=85_000.0, extra=60_000.0, crash_n=160_000.0, crash_w=25_000.0):
    m = {"lot": 65, "extra": extra, "expiry": NIFTY_EXP,
         "naked": {"margin": naked, "weekly": 900.0, "crash": crash_n},
         "winged": {"margin": winged, "weekly": 450.0, "crash": crash_w}}
    return {"wing_pct": 1.75, "markets": {"NIFTY": m, "SENSEX": dict(m, expiry=SENSEX_EXP)}}


def test_sizing_choices_are_the_four_setups(conn):
    s = {**ol.settings(), "lots_cap": {"NIFTY": 15, "SENSEX": 15}, "wing_pct": 0.0, "margin_buffer_rs": 50_000}
    rows = {r["key"]: r for r in ol.sizing_choices(_quote(), 4_600_000, s)}
    assert rows["A"]["caps"] == {"NIFTY": 15, "SENSEX": 15} and rows["A"]["current"]       # naked at today's caps
    assert rows["B"]["per"]["NIFTY"]["lots"] == 8                                          # 30 % × 46 L / 1.6 L
    assert rows["B"]["crash_pct"] <= 0.30 < rows["A"]["crash_pct"]
    assert rows["C"]["per"]["NIFTY"]["lots"] == 15 and not rows["C"]["current"]
    assert rows["D"]["per"]["NIFTY"]["lots"] == 29                                         # (46 L − 2.4 L − 50 K) / 145 K
    assert rows["D"]["wing_pct"] == 1.75 and rows["A"]["wing_pct"] == 0
    assert abs(rows["D"]["weekly"] - 2 * 29 * 450.0) < 1e-6 and rows["D"]["crash"] == 29 * 25_000.0
    big = {r["key"]: r for r in ol.sizing_choices(_quote(), 50_000_000, s)}
    assert big["D"]["per"]["NIFTY"]["lots"] == s["lots_hard_max"]                          # a cap the settings accept
    on = {r["key"]: r for r in ol.sizing_choices(_quote(), 4_600_000, {**s, "wing_pct": 1.75})}
    assert on["C"]["current"] and not on["A"]["current"]
    assert ol.sizing_choices(None, 4_600_000, s) == [] and ol.sizing_choices(_quote(), None, s) == []


def _two_markets_friday():
    fake = FakeKite()
    fake.add_market("SENSEX", 84000.0, SENSEX_EXP, FRI, 20, 100, "BFO")
    return fake


def test_sizing_quote_reads_both_markets_naked_and_winged(conn):
    fake = _two_markets_friday()
    fake.place_order = None                                                    # read-only
    res, _ = run("quote", fake, Clock(FRI, "15:01"))
    assert res["status"] == "ok", res
    q = ol.get_state("sizing_quote")
    for u, lot in (("NIFTY", 65), ("SENSEX", 20)):
        m = q["markets"][u]
        assert m["lot"] == lot and m["winged"]["margin"] == fake.hedge * m["naked"]["margin"]
        assert m["strikes"]["wing_C"] > m["strikes"]["C"] and m["strikes"]["wing_P"] < m["strikes"]["P"]
        assert 0 < m["winged"]["crash"] < m["naked"]["crash"] and m["winged"]["weekly"] < m["naked"]["weekly"]
        assert abs(m["extra"] - ob.expiry_day_extra(m["forward"], lot)) < 1e-6
    assert q["wing_pct"] == 1.75 and ol.get_state("margin")["total"] == 1_000_000.0      # quoted with wings while off


def test_live_panel_shows_the_sizing_choices(ops):
    authed, _ = ops
    run("quote", _two_markets_friday(), Clock(FRI, "15:01"))
    html = authed.get("/options/live").text
    assert "Sizing for the next entries" in html and "Your plan" in html and 'id="ol-sz-data"' in html
    assert 'id="ol-sz-lots-NIFTY"' in html and 'id="ol-sz-lots-SENSEX"' in html and "Save plan" in html   # one form, prefilled
    assert "Max lots for my margin" in html and "Crash-safe" in html and "ol-apply" not in html.split('id="ol-plan"')[1].split("</details>")[0]


# ───────────────────────────── SENSEX buy-back on a NIFTY entry day (Amit 2026-10-29) ─────────────────────────────

TUE3, THU5 = date(2026, 11, 3), date(2026, 11, 5)          # SENSEX entry / expiry; Tue 10 Nov is a holiday → NIFTY expires Mon 9 Nov,
NIFTY_EXP9, SENSEX_EXP5 = "2026-11-09", "2026-11-05"       # so its entry falls on Thu 5 Nov, the SENSEX expiry


def _holiday_week(conn, mode="auto"):
    for sym, exp in (("NIFTY", NIFTY_EXP9), ("SENSEX", SENSEX_EXP5)):
        conn.execute("INSERT INTO fno_bhav (symbol, instrument_type, expiry_date, strike, option_type, trade_date, settle, "
                     "underlying_price, volume) VALUES (?, 'IDO', ?, 25000, 'CE', '2026-11-02', 10, 25800, 5)", (sym, exp))
    conn.commit()
    tue = FakeKite(underlying="SENSEX", spot=84000.0, expiry=SENSEX_EXP5, today=TUE3, lot=20, step=100, exchange="BFO")
    res, _ = run("entry", tue, Clock(TUE3, "15:17"), "SENSEX", mode=mode)
    assert res["status"] == "ok", res
    thu = FakeKite(underlying="NIFTY", expiry=NIFTY_EXP9, today=THU5)
    thu.add_market("SENSEX", 84000.0, SENSEX_EXP5, THU5, 20, 100, "BFO")
    for sym, q in tue.pos.items():                                        # the SENSEX position carries into Thursday
        thu.pos[sym] = q
        thu.book[sym] = [0.05, 0.10, 0.05]
    return thu


def test_sensex_is_bought_back_when_nifty_enters_the_same_day(conn):
    thu = _holiday_week(conn)
    early, ctx = run("entry", thu, Clock(THU5, "15:12"), "NIFTY")         # before the buy-back: gated
    assert early["status"] == "skipped" and "rotation gate" in early["detail"] and "SENSEX" in early["detail"]
    bb, ctx = run("buyback", thu, Clock(THU5, "15:00"), "SENSEX")
    assert bb["status"] == "ok", bb
    assert set(ledger(conn, "underlying = 'SENSEX' AND net_qty < 0").status) == set()
    assert ol.get_state(f"rotation:{THU5.isoformat()}:SENSEX")["ok"] and "NIFTY can enter" in ctx["sent"][-1][0]
    res, _ = run("entry", thu, Clock(THU5, "15:12"), "NIFTY")
    assert res["status"] == "ok", res
    assert set(ledger(conn, f"underlying = 'NIFTY' AND expiry = '{NIFTY_EXP9}'").net_qty) == {-65}


def test_sensex_is_held_to_expiry_on_a_normal_thursday(conn):
    fake = _tuesday_broker()
    res, _ = run("buyback", fake, Clock(date(2026, 10, 29), "15:00"), "SENSEX", mode="auto")
    assert res["status"] == "idle" and "held to expiry" in res["detail"] and "place_order" not in fake.names()


def test_precheck_asks_for_a_login_before_the_sensex_buyback(conn):
    _holiday_week(conn)
    res, ctx = run("precheck", NoKiteSession("x"), Clock(THU5, "14:45"))
    assert res["status"] == "failed" and "SENSEX buy-back (15:00)" in ctx["sent"][0][0] and "before 15:00" in ctx["sent"][0][0]


# ───────────────────────────── Refresh from Kite (Amit 2026-10-29) ─────────────────────────────

def test_refresh_from_kite_runs_the_quote_step_and_reports_the_new_margin(ops, monkeypatch):
    import subprocess
    authed, anon = ops
    assert anon.post("/api/options/live/refresh", json={}).status_code == 401
    calls = []

    def fake_run(cmd, **kw):                                              # the step itself is tested above; here only the wiring
        calls.append(cmd)
        if len(calls) == 2:
            ol.put_state("margin", {"at": "2026-10-29T10:00:00+00:00", "total": 4_900_000.0, "free": 1.0, "used": 1.0}, "test")
        return subprocess.CompletedProcess(cmd, 0, stdout="no Kite login today: no sizing quote\n", stderr="")
    monkeypatch.setattr(subprocess, "run", fake_run)
    r = authed.post("/api/options/live/refresh", json={})                # nothing written → said so, not a silent OK
    assert r.status_code == 409 and "no Kite login" in r.json()["error"]
    r = authed.post("/api/options/live/refresh", json={})
    assert r.status_code == 200 and r.json()["margin"]["total"] == 4_900_000.0 and r.json()["quote_refreshed"] is False
    assert all(c[-2:] == ["options_live", "quote"] and c[0].endswith("run.sh") for c in calls)


def test_quote_step_reads_the_margin_even_when_the_quote_fails(conn, monkeypatch):
    # 2026-10-29 02:00 IST: no offers on the SENSEX wing strikes → sizing_quote raised before the margin was read
    def boom(ctx):
        raise RuntimeError("no offered CE beyond 76,700 for the wing")
    monkeypatch.setattr(ol, "sizing_quote", boom)
    fake = FakeKite()
    res, _ = run("quote", fake, Clock(FRI, "20:00"))
    assert res["status"] == "skipped" and "the last one stays" in res["detail"]
    assert ol.get_state("margin")["total"] == fake.available


# ───────────────────────────── 2026-10-30: iceberg slices counted (controls) ─────────────────────────────

def _friday_32_lots(conn):
    """2026-10-30 replayed: 32 protected NIFTY lots = 2,080 units a leg, over the 1,800 freeze → icebergs of 2 × 1,040."""
    fake = FakeKite(available=1e9, margin_per_lot=10_000.0)
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 32}, wing_pct=1.75)
    return fake, res, ctx


def test_iceberg_wings_count_every_slice_and_the_full_strangle_is_sold(conn):
    fake, res, _ = _friday_32_lots(conn)
    assert res["status"] == "ok" and "wings filled for" not in res["detail"]
    held = {s: q for s, q in fake.pos.items() if q}
    assert sorted(held.values()) == [-2080, -2080, 2080, 2080]                 # 32 lots sold, 32 lots of wings
    kids = [o for o in fake.orders_.values() if o.get("parent_order_id")]
    assert len(kids) == 4 and all(o["quantity"] == 1040 for o in kids)          # every leg went as 2 slices


def test_the_sale_is_sized_on_kite_positions_when_the_order_reading_is_short(conn, monkeypatch):
    # the order loop misreads the wings (as on 2026-10-30); Kite's positions decide the lots sold, and a push says so
    real = ol._combined
    monkeypatch.setattr(ol, "_combined", lambda members, b: (lambda st, f, a: ("COMPLETE", min(f, 1040), a) if b["side"] == "BUY" else (st, f, a))(*real(members, b)))
    fake, res, ctx = _friday_32_lots(conn)
    assert res["status"] == "ok"
    assert sorted(q for q in fake.pos.values() if q) == [-2080, -2080, 2080, 2080]
    assert any("sized on Kite (32 lots)" in m for m, _ in ctx["sent"])


def test_entry_check_stops_entries_when_kite_does_not_match(conn, monkeypatch):
    # a short Kite holds that the sale did not account for: kill switch on, urgent push
    real_held = ol._held

    def lying(ctx, syms, before=None, expect=None, tries=4):
        out = real_held(ctx, syms, before, expect, tries)
        return {k: (v - 65 if v < 0 else v) for k, v in out.items()} if expect is None and before is not None else out
    monkeypatch.setattr(ol, "_held", lying)
    fake, res, ctx = _friday_32_lots(conn)
    assert res["status"] == "failed" and "entry check failed" in res["detail"]
    assert ol.settings()["kill"] is True and any(urgent for _, urgent in ctx["sent"])


def test_reconcile_checks_the_shape_of_the_live_book(conn):
    # clean 2-lot winged strangle: passes; spare wings are a note; an expired open leg stops entries
    ol.set_setting("wing_pct", 1.75)
    fake = FakeKite(available=1e9, margin_per_lot=10_000.0)
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 2})
    res, _ = run("reconcile", fake, Clock(FRI, "15:50"))
    assert res["status"] == "ok" and "spare" not in res["detail"]
    problems, notes = ol.shape_check(FRI.isoformat())
    assert problems == [] and notes == []
    later = (FRI + timedelta(days=30)).isoformat()                           # the same legs, a month on, never settled
    problems, _ = ol.shape_check(later)
    assert any("not settled after expiry" in p for p in problems)


def test_reconcile_flags_unbalanced_shorts(conn):
    fake = FakeKite(available=1e9, margin_per_lot=10_000.0)
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 2}, wing_pct=0)
    with ol.get_db() as c:                                                    # one short leg bought back by hand
        sym = c.execute("SELECT tradingsymbol FROM option_live_trades WHERE option_type = 'CE' AND net_qty < 0").fetchone()[0]
        c.execute("UPDATE option_live_trades SET net_qty = net_qty + 65 WHERE tradingsymbol = ?", (sym,))
    problems, _ = ol.shape_check(FRI.isoformat())
    assert any("short calls 65 ≠ short puts 130" in p for p in problems)


def test_ledger_writes_wait_out_a_long_db_lock(conn, monkeypatch):
    # 2026-10-30 06:00 UTC: settle died on "database is locked"; now it waits and writes
    import sqlite3
    tries = []
    real = ol.upsert_df

    def flaky(df, table):
        tries.append(table)
        if len(tries) < 3:
            raise sqlite3.OperationalError("database is locked")
        return real(df, table)
    monkeypatch.setattr(ol, "upsert_df", flaky)
    clock = Clock(FRI, "11:30")
    ctx = ctx_for(FakeKite(), clock)
    ol._write(ctx, [{"underlying": "NIFTY", "expiry": NIFTY_EXP, "tradingsymbol": "X", "source": "live", "status": "OPEN"}])
    assert len(tries) == 3 and clock.waits == [30, 60]
    monkeypatch.setattr(ol, "upsert_df", lambda df, table: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    with pytest.raises(sqlite3.OperationalError):
        ol._write(ctx, [{"underlying": "NIFTY", "expiry": NIFTY_EXP, "tradingsymbol": "X", "source": "live", "status": "OPEN"}])


def test_marks_skip_expired_legs_and_refuse_impossible_prices(conn):
    fake = FakeKite(available=1e9, margin_per_lot=10_000.0)
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 1}, wing_pct=0)
    for sym in list(fake.book):                                               # the feed returns the index level
        fake.book[sym] = [25800.0, 25800.0, 25800.0]
    res, _ = run("mark", fake, Clock(FRI, "15:31"))
    assert all((l["mtm_rs"] or 0) > -1e6 for l in ol.legs("status = 'OPEN'"))   # no −₹ crore marks
    after = (date.fromisoformat(NIFTY_EXP) + timedelta(days=1))
    res, _ = run("mark", fake, Clock(after, "10:00"))
    assert res["status"] == "idle"                                            # expired: settle's job, not mark's


def test_a_crashed_step_is_pushed_urgently(conn, monkeypatch):
    sent = []
    monkeypatch.setitem(ol.STEPS, "settle", lambda ctx: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        ol.run_step("settle", push=lambda m, urgent=False: sent.append((m, urgent)))
    assert sent and sent[0][1] is True and "CRASHED" in sent[0][0]


def test_dear_wings_step_out_until_the_cap_fits_then_refuse():
    # Amit 2026-10-30: the wings may cost at most 20-30 % of the credit; the protection is for a gap inside a calm
    # window (0 of 530 guarded weeks reached a wing), so never pay a silly price for it.
    chain = pd.DataFrame(_chain("NIFTY", 25800.0, NIFTY_EXP, FRI.isoformat(), 50))
    k = {"C": 26500.0, "P": 25100.0}
    plain = ol.wing_strikes(chain, k, 25800.0, 1.75)                          # {"C": 26950, "P": 24650}
    credit = 20.0
    assert ol.wing_strikes(chain, k, 25800.0, 1.75, credit=credit, max_share=0.30, max_pct=3.5) == plain   # fits: unchanged
    # a thin wing strike quoted wide (SENSEX 2026-10-29: asks at 63 % of the credit): 8.00 asked on both wings
    chain.loc[(chain.option_type == "CE") & (chain.strike == plain["C"]), "ask"] = 8.0
    chain.loc[(chain.option_type == "PE") & (chain.strike == plain["P"]), "ask"] = 8.0
    w = ol.wing_strikes(chain, k, 25800.0, 1.75, credit=credit, max_share=0.30, max_pct=3.5)
    assert w == {"C": plain["C"] + 50, "P": plain["P"] - 50}                  # each side one offered strike out
    asks = chain.set_index(["option_type", "strike"]).ask
    assert asks[("CE", w["C"])] + asks[("PE", w["P"])] <= 0.30 * credit
    # every strike up to 3.5 % out quoted wide: no entry
    chain.loc[(chain.option_type == "CE") & (chain.strike > k["C"]), "ask"] = 8.0
    chain.loc[(chain.option_type == "PE") & (chain.strike < k["P"]), "ask"] = 8.0
    with pytest.raises(ol.WingsTooDear, match="80% of the credit"):
        ol.wing_strikes(chain, k, 25800.0, 1.75, credit=credit, max_share=0.30, max_pct=3.5)


def test_dear_wings_skip_the_entry_with_a_push(conn):
    fake = FakeKite()
    ctx = ctx_for(fake, Clock(FRI, "15:12"), mode="auto", wing_pct=1.75, wing_max_share_pct=30)
    p = ol.build_plan(ctx, "NIFTY", NIFTY_EXP)
    assert p["wing_share"] is not None and p["wing_share"] <= 0.30 and "of the credit, limit 30%" in ol._plan_text(p)
    short = {l["option_type"]: l["strike"] for l in p["legs"]}
    for r in fake.ins["NFO"]:                                                 # far strikes quoted wide: asks × 5
        if (r["instrument_type"] == "CE" and r["strike"] >= short["CE"] + 150) or (r["instrument_type"] == "PE" and r["strike"] <= short["PE"] - 150):
            fake.book[r["tradingsymbol"]][1] *= 5
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", wing_pct=1.75, wing_max_share_pct=5)
    assert res["status"] == "skipped" and "wings too dear" in res["detail"], res
    assert not [c for c in fake.calls if c[0] == "place_order"]              # nothing placed
    assert ctx["sent"][-1][1] and "Nothing placed" in ctx["sent"][-1][0]     # urgent push
    assert ol.pick_legs(ctx, "NIFTY", NIFTY_EXP, 1.75, capped=False)[5] is not None   # the sizing quote still reports the plain wing
    with pytest.raises(ValueError):
        ol.set_setting("wing_max_share_pct", 3)
    assert ol.set_setting("wing_max_share_pct", 25) == 25 and ol.settings()["wing_max_share_pct"] == 25


def test_kill_switch_pressed_mid_entry_cancels_the_working_orders(conn):
    # control (2026-10-30 gap list): the kill switch is re-read at every re-price; Stop pressed while the wings are
    # being bought cancels them and sells nothing.
    fake = FakeKite(liquidity=1)                                              # one unit a look: orders stay working
    ctx = ctx_for(fake, Clock(FRI, "15:12"), mode="auto", wing_pct=1.75, lots_cap={"NIFTY": 2})
    p = ol.build_plan(ctx, "NIFTY", NIFTY_EXP)
    shorts = [l["tradingsymbol"] for l in p["legs"]]

    def stop(f):                                                              # Amit presses Stop once the wings are out
        if any(c[0] == "place_order" for c in f.calls):
            ol.set_kill(True, "Stop on the cockpit", "cockpit")
    fake.on_look = stop
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY")
    assert res["status"] == "failed" and "kill switch" in res["detail"], res
    assert [c for c in fake.calls if c[0] == "cancel_order"]                   # the working wing orders cancelled
    assert not [c for c in fake.calls if c[0] == "place_order" and c[2]["tradingsymbol"] in shorts]   # nothing sold
    assert ctx["sent"][-1][1] and "STOPPED" in ctx["sent"][-1][0]
    assert not events(conn, "abort").empty and all(q == 0 for q in fake.pos.values())   # the unit that filled was sold back


def test_kill_switch_pressed_while_planning_places_nothing(conn):
    fake = FakeKite()
    fake.on_look = lambda f: ol.set_kill(True, "Stop", "cockpit")            # already_entered looks at the order book, before the plan
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", wing_pct=1.75, kill=False)
    assert res["status"] == "skipped" and "while planning" in res["detail"]
    assert not [c for c in fake.calls if c[0] == "place_order"]


def test_a_crash_inside_the_order_loop_cancels_the_working_orders(conn):
    fake = FakeKite()
    ctx = ctx_for(fake, Clock(FRI, "15:12"), mode="auto", wing_pct=1.75)
    w = _wing_syms(fake, ol.build_plan(fake and ctx, "NIFTY", NIFTY_EXP))

    def kite_dies(f):                                                         # after the wings are placed, every look fails
        if any(c[0] == "place_order" for c in f.calls):
            for sym in w.values():
                f.book[sym][1] += 5.0                                         # and nothing filled meanwhile
            raise RuntimeError("Kite: connection reset")
    fake.on_look = kite_dies
    with pytest.raises(RuntimeError, match="connection reset"):
        run("entry", fake, Clock(FRI, "15:12"), "NIFTY")
    placed = [c[2]["tradingsymbol"] for c in fake.calls if c[0] == "place_order"]
    cancelled = [c for c in fake.calls if c[0] == "cancel_order"]
    assert sorted(placed) == sorted(w.values()) and len(cancelled) == 2         # both wing orders cancelled on the way out
    d = events(conn, "cancel")
    assert len(d) == 2 and all("crash" in x for x in d.detail)


def test_mark_pushes_when_free_margin_is_short_of_the_expiry_day_extra(conn):
    fake = FakeKite()
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", lots_cap={"NIFTY": 1})
    assert res["status"] == "ok"
    res, ctx = run("mark", fake, Clock(TUE, "10:00"))
    assert "margin watch" not in res["detail"] and not any("margin watch" in m for m, _ in ctx["sent"])
    fake.available = 10_000.0                                                  # cash withdrawn: below the ₹50 K buffer
    res, ctx = run("mark", fake, Clock(TUE, "10:00"))
    assert "margin watch" in res["detail"] and "safety buffer" in res["detail"]
    assert ctx["sent"][-1][1] and "square off" in ctx["sent"][-1][0]
    fake.available = 150_000.0 + 60_000.0                                      # free 60 K (the lot blocks 150 K): above the buffer, below the expiry-day extra (2 % × 2 legs ≈ 67 K)
    res, ctx = run("mark", fake, Clock(TUE, "10:00"))
    assert "expiry-day extra" in res["detail"]


def test_health_flags_an_entry_day_whose_steps_never_ran(conn, monkeypatch):
    ol.set_setting("mode", "auto", by="test")
    monkeypatch.setattr(ol, "_health_now", lambda: datetime(2026, 10, 23, 20, 0, tzinfo=ol.IST))   # FRI evening: NIFTY was due
    v = ol.health_check()
    assert v["severity"] == "CRITICAL" and "entry:NIFTY did not run on 2026-10-23" in v["sample"] and v["n_bad"] == 3
    for k in ("step:entry:NIFTY", "step:record:ALL", "step:reconcile:ALL"):
        ol.put_state(k, {"date": FRI.isoformat(), "status": "ok", "detail": "x", "mode": "auto"}, "t")
    assert ol.health_check()["n_bad"] == 0
    monkeypatch.setattr(ol, "_health_now", lambda: datetime(2026, 10, 24, 9, 30, tzinfo=ol.IST))    # Saturday morning judges Friday
    assert ol.health_check()["n_bad"] == 0
    ol.set_setting("mode", "shadow", by="test")                               # shadow: silence is not money
    ol.put_state("step:entry:NIFTY", {"date": "2026-10-16", "status": "ok", "detail": "x", "mode": "shadow"}, "t")
    assert ol.health_check()["n_bad"] == 0


# ───────────────────────────── hand trades on the live book (2026-11-02) ─────────────────────────────

def _placed(fake):
    return [c[2]["tradingsymbol"] for c in fake.calls if c[0] == "place_order"]


def test_a_leg_closed_by_hand_in_kite_is_booked_live_and_not_bought_back_again(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    ce = next(s for s, q in fake.pos.items() if q < 0 and s.endswith("CE"))
    fake.trades_.append({"trade_id": "H1", "order_id": "HAND1", "tradingsymbol": ce, "transaction_type": "BUY",
                         "quantity": 65, "average_price": 2.0})          # Amit buys the short call back in Kite, untagged
    fake.pos[ce] = 0
    bb, ctx = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "ok", bb
    assert ce not in _placed(fake) and len(_placed(fake)) == 1              # only the put is bought back
    led = ledger(conn, "underlying = 'NIFTY'")
    assert set(led.source) == {"live"} and set(led.status) == {"CLOSED"}    # one leg per contract, no manual row
    assert led[led.tradingsymbol == ce].buy_avg.iloc[0] == 2.0
    assert ol.rotation_gate(ctx_for(fake, Clock(TUE, "15:16")))[0]
    ok, _ = run("reconcile", fake, Clock(TUE, "15:50"))
    assert ok["status"] == "ok" and not ol.settings()["kill"]


def test_every_leg_closed_by_hand_means_nothing_to_buy_back(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    for i, (s, q) in enumerate(list(fake.pos.items())):
        fake.trades_.append({"trade_id": f"H{i}", "order_id": f"HAND{i}", "tradingsymbol": s, "transaction_type": "BUY",
                             "quantity": -q, "average_price": 1.0})
        fake.pos[s] = 0
    bb, ctx = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "ok" and "closed by hand" in bb["detail"] and not _placed(fake)
    assert ol.rotation_gate(ctx_for(fake, Clock(TUE, "15:16")))[0]
    assert "can enter" in ctx["sent"][-1][0]


def test_buyback_never_buys_more_than_kite_holds(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    ce = next(s for s, q in fake.pos.items() if q < 0 and s.endswith("CE"))
    fake.pos[ce] = 0                                                      # closed on a day with no login: the ledger still says short
    bb, _ = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert ce not in _placed(fake) and len(_placed(fake)) == 1
    assert bb["status"] == "ok", bb                                       # the put was bought back; the call is not "left"
    skip = events(conn, "skip")
    assert list(skip.tradingsymbol) == [ce] and "Kite holds 0 short" in skip.detail.iloc[0]
    bad, _ = run("reconcile", fake, Clock(TUE, "15:50"))                 # the stale row is reconcile's job, loudly
    assert bad["status"] == "failed" and ol.settings()["kill"]


def test_a_wing_sold_by_hand_is_booked_live_and_noted_not_a_mismatch(conn):
    fake = FakeKite()
    run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="auto", wing_pct=1.75)
    wing = next(s for s, q in fake.pos.items() if q > 0 and s.endswith("CE"))
    fake.trades_.append({"trade_id": "W1", "order_id": "HANDW", "tradingsymbol": wing, "transaction_type": "SELL",
                         "quantity": 65, "average_price": 1.5})          # the call wing sold at the open, untagged
    fake.pos[wing] = 0
    rec, _ = run("record", fake, Clock(FRI, "15:45"))
    assert rec["status"] == "ok"
    led = ledger(conn)
    assert set(led.source) == {"live"}
    assert led[led.tradingsymbol == wing].status.iloc[0] == "CLOSED"
    ok, _ = run("reconcile", fake, Clock(FRI, "15:50"))
    assert ok["status"] == "ok" and "CE wing sold by hand (0 of 65" in ok["detail"] and not ol.settings()["kill"]
    assert "PE wing" not in ok["detail"]                                  # the untouched put wing is neither spare nor short


def test_closeall_holds_on_a_gap_down_when_asked_once(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    prev = fake.spot["NSE:NIFTY 50"]
    floor = prev * (1 - 0.0025)
    ol.set_setting("closeall_hold_below", {"NSE:NIFTY 50": floor}, by="test")
    fake.spot["NSE:NIFTY 50"] = prev * 0.995                              # opens 0.5% down: hold
    res, ctx = run("closeall", fake, Clock(TUE, "09:16"))
    assert res["status"] == "skipped" and "holding" in res["detail"], res
    assert not _placed(fake) and not ol.settings()["kill"] and "HELD" in ctx["sent"][-1][0]
    assert ol.settings()["closeall_hold_below"] is None                   # one-shot: a later Close-all closes
    ol.set_setting("closeall_hold_below", {"NSE:NIFTY 50": floor}, by="test")
    fake.spot["NSE:NIFTY 50"] = prev                                      # flat open: close
    res, _ = run("closeall", fake, Clock(TUE, "09:17"))
    assert res["status"] == "ok" and len(_placed(fake)) == 2 and ol.settings()["kill"]
    assert ol.settings()["closeall_hold_below"] is None
    with pytest.raises(ValueError):
        ol.set_setting("closeall_hold_below", {"NSE:NIFTY 50": -1})
    with pytest.raises(ValueError):
        ol.set_setting("closeall_hold_below", {"BSE:FOO": 100})


# ───────────────────────────── controls after 2026-11-03 (ADR 0093) ─────────────────────────────

def test_buyback_preflight_blocks_when_kite_holds_more_short_than_the_ledger(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    ce = next(s for s, q in fake.pos.items() if q < 0 and s.endswith("CE"))
    fake.pos[ce] = -130                                                    # Kite: 2 lots short; ledger: 1 — unexplained
    bb, ctx = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "failed" and "more short than the ledger" in bb["detail"]
    assert not _placed(fake) and ol.settings()["kill"] and ctx["sent"][-1][1]      # urgent, nothing placed


def test_buyback_preflight_blocks_on_a_dead_session(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    from kiteconnect.exceptions import TokenException
    fake.profile = lambda: (_ for _ in ()).throw(TokenException("Incorrect `api_key` or `access_token`."))
    bb, ctx = run("buyback", fake, Clock(TUE, "15:08"), "NIFTY")
    assert bb["status"] == "failed" and "no live Kite session" in bb["detail"] and not _placed(fake)


def test_closeall_keeps_the_hold_rule_when_the_quote_fails(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    ol.set_setting("closeall_hold_below", {"NSE:NIFTY 50": 25000.0}, by="test")
    real_ltp = fake.ltp
    fake.ltp = lambda keys: (_ for _ in ()).throw(RuntimeError("TokenException: Incorrect `api_key` or `access_token`."))
    with pytest.raises(RuntimeError):
        run("closeall", fake, Clock(TUE, "09:16"))
    assert ol.settings()["closeall_hold_below"] == {"NSE:NIFTY 50": 25000.0}  # 2026-11-03: it was cleared before the quote
    assert not _placed(fake) and not ol.settings()["kill"]
    fake.ltp = real_ltp
    fake.spot["NSE:NIFTY 50"] = 24000.0                                     # below the level: the rule still holds
    res, _ = run("closeall", fake, Clock(TUE, "09:17"))
    assert res["status"] == "skipped" and "holding" in res["detail"] and not _placed(fake)


def test_precheck_fails_loudly_when_legs_are_open_and_the_session_is_dead(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    res, ctx = run("precheck", NoKiteSession("x"), Clock(TUE, "09:05"))
    assert res["status"] == "failed" and "before 09:10" in ctx["sent"][0][0] and ctx["sent"][0][1]
    ol._health_now = lambda: datetime.combine(TUE, datetime.min.time(), tzinfo=IST).replace(hour=9, minute=30)
    h = ol.health_check()
    ol._health_now = None
    assert h["severity"] == "CRITICAL" and "precheck:ALL failed" in h["sample"]


def test_precheck_warns_when_the_login_was_before_0830(conn, monkeypatch):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    monkeypatch.setattr(ol, "login_info", lambda: {"date": TUE.isoformat(), "at": "2026-10-27T00:49:07+00:00", "early": True})
    res, ctx = run("precheck", fake, Clock(TUE, "09:05"))
    assert res["status"] == "skipped" and "log in AGAIN after 08:30" in ctx["sent"][0][0]
    monkeypatch.setattr(ol, "login_info", lambda: {"date": TUE.isoformat(), "at": "2026-10-27T03:30:00+00:00", "early": False})
    res, ctx = run("precheck", fake, Clock(TUE, "09:05"))
    assert res["status"] == "ok"


def test_a_stopped_order_step_cancels_its_working_order_and_alerts(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    for sym, q in fake.pos.items():
        fake.book[sym] = [0.05, 50.0, 0.05]                                # nobody sells at our price: the order keeps working

    fired = []

    def stop(f):                                                           # once: the real handler ignores further signals
        if not fired and any(o["status"] == "OPEN" for o in f.orders_.values()):
            fired.append(1)
            raise ol.StepInterrupted("SIGTERM")
    fake.on_look = stop
    ctx = ctx_for(fake, Clock(TUE, "15:08"))
    ctx["step"] = "buyback"
    with pytest.raises(ol.StepInterrupted):
        ol._loud(ctx, "buyback", lambda: ol.STEPS["buyback"](ctx, "NIFTY"))
    assert "cancel_order" in fake.names() and not [o for o in fake.orders_.values() if o["status"] == "OPEN"]
    assert ctx["sent"][-1][1] and "CRASHED: StepInterrupted" in ctx["sent"][-1][0]


def test_a_real_signal_raises_step_interrupted():
    import os
    import signal
    saved = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
    try:
        ol._install_stop_signals()
        with pytest.raises(ol.StepInterrupted):
            os.kill(os.getpid(), signal.SIGTERM)
            import time
            time.sleep(1)
    finally:
        for sig, h in saved.items():
            signal.signal(sig, h)


def test_morning_precheck_pages_only_for_open_shorts_and_not_on_a_holiday(conn, monkeypatch):
    res, ctx = run("precheck", NoKiteSession("x"), Clock(FRI, "09:05"), mode="auto")      # an entry day, nothing open
    assert res["status"] == "idle" and not ctx["sent"]
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    monkeypatch.setattr(ob, "is_session", lambda d, hol: False)
    res, ctx = run("precheck", NoKiteSession("x"), Clock(TUE, "09:05"))
    assert res["status"] == "idle" and "holiday" in res["detail"]


def test_strike_sigma_widens_the_sold_strikes_and_is_validated(conn):
    fake = FakeKite()
    res, _ = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="shadow")
    assert res["status"] == "ok"
    near = ledger(conn, "net_qty < 0").strike.tolist()
    conn.execute("DELETE FROM option_live_trades"); conn.execute("DELETE FROM option_live_orders"); conn.commit()
    ol.set_setting("strike_sigma", 2.5, by="test")
    fake = FakeKite()
    res, ctx = run("entry", fake, Clock(FRI, "15:12"), "NIFTY", mode="shadow")
    assert res["status"] == "ok"
    wide = ledger(conn, "net_qty < 0").strike.tolist()
    assert min(wide) < min(near) and max(wide) > max(near)                 # further out on both sides
    for bad in (1, 5, True, "x"):
        with pytest.raises(ValueError):
            ol.set_setting("strike_sigma", bad)
    ol.set_setting("strike_sigma", 0, by="test")
    assert ol.settings()["strike_sigma"] == 0


def test_strike_sigma_matches_the_study_formula():
    import math
    from sources import kite_quotes as kq
    fake = FakeKite()
    rows = pd.DataFrame(_chain("NIFTY", 25800.0, NIFTY_EXP, FRI.isoformat(), 50))
    rows["volume"] = 100
    F, _, k = kq.pick(rows, FRI.isoformat(), NIFTY_EXP, sigma=2.5)
    move = kq.atm_move(rows, F, FRI.isoformat(), NIFTY_EXP)
    assert abs(k["C"] - F * math.exp(2.5 * move)) <= 50 and abs(k["P"] - F * math.exp(-2.5 * move)) <= 50


# ───────────────────────────── orders by day + the armed AMO (ADR 0094) ─────────────────────────────

def _armed(conn, fake, limit=60.0):
    _enter_nifty_friday(conn, fake, "auto")
    ce = next(s for s, q in fake.pos.items() if q < 0 and s.endswith("CE"))
    ol.arm_amo([{"tradingsymbol": ce, "limit": limit}])
    return ce


def _amo_orders(fake):
    return [c[2] for c in fake.calls if c[0] == "place_order"]


def test_login_inside_the_window_places_a_limit_amo_and_kite_confirms_it(conn):
    fake = _tuesday_broker()
    ce = _armed(conn, fake)
    res, ctx = run("amo", fake, Clock(TUE, "06:18"))
    assert res["status"] == "ok", res
    o = _amo_orders(fake)
    assert len(o) == 1 and o[0]["variety"] == "amo" and o[0]["order_type"] == "LIMIT" and o[0]["price"] == 60.0
    assert o[0]["tradingsymbol"] == ce and o[0]["transaction_type"] == "BUY" and o[0]["quantity"] == 65
    assert "confirmed by Kite" in ctx["sent"][-1][0] and not ctx["sent"][-1][1]
    assert ol.get_state("amo_arm")["status"] == "placed"
    assert pd.read_sql_query("SELECT status FROM option_kite_orders", conn).status.tolist() == ["AMO REQ RECEIVED"]
    again, _ = run("amo", fake, Clock(TUE, "06:30"))                       # never twice
    assert again["status"] == "idle" and len(_amo_orders(fake)) == 1


@pytest.mark.parametrize("hhmm", ["01:00", "03:00", "05:29", "09:10", "12:00", "15:44"])
def test_outside_zerodhas_window_nothing_is_placed_and_it_stays_armed(conn, hhmm):
    fake = _tuesday_broker()
    _armed(conn, fake)
    res, ctx = run("amo", fake, Clock(TUE, hhmm))
    assert res["status"] == "skipped" and not _amo_orders(fake) and ctx["sent"][-1][1]
    assert ol.get_state("amo_arm")["status"] == "armed"


@pytest.mark.parametrize("hhmm", ["00:59", "05:30", "09:09", "15:45", "23:30"])
def test_inside_zerodhas_window(hhmm):
    h, m = map(int, hhmm.split(":"))
    assert ol.amo_window_open(datetime(2026, 11, 3, h, m, tzinfo=IST))


def test_a_refused_amo_alerts_urgently_and_does_not_retry(conn):
    fake = _tuesday_broker()
    ce = _armed(conn, fake)
    fake.reject_on_place.add(ce)
    res, ctx = run("amo", fake, Clock(TUE, "06:18"))
    assert res["status"] == "failed" and "REFUSED" in res["detail"] and ctx["sent"][-1][1]
    assert ol.get_state("amo_arm")["status"] == "failed"
    n = fake.names().count("place_order")
    again, _ = run("amo", fake, Clock(TUE, "06:30"))
    assert again["status"] == "idle" and fake.names().count("place_order") == n


def test_an_amo_kite_rejects_in_the_book_alerts_urgently(conn):
    fake = _tuesday_broker()
    _armed(conn, fake)
    real = fake.place_order

    def place(**kw):
        oid = real(**kw)
        fake.orders_[oid].update(status="REJECTED", status_message="price out of range")
        return oid
    fake.place_order = place
    res, ctx = run("amo", fake, Clock(TUE, "06:18"))
    assert res["status"] == "failed" and "price out of range" in res["detail"] and ctx["sent"][-1][1]


def test_amo_buys_only_what_kite_holds(conn):
    fake = _tuesday_broker()
    ce = _armed(conn, fake)
    fake.pos[ce] = 0
    fake.trades_.append({"trade_id": "H9", "order_id": "HANDX", "tradingsymbol": ce, "transaction_type": "BUY",
                         "quantity": 65, "average_price": 2.0})
    res, _ = run("amo", fake, Clock(TUE, "06:18"))
    assert res["status"] == "ok" and not _amo_orders(fake) and ol.get_state("amo_arm") is None


def test_amo_sizes_stay_under_the_freeze_in_whole_lots():
    assert ol._amo_slices(4000, 65, 1800) == [1755, 1755, 490]
    assert ol._amo_slices(1040, 65, 1800) == [1040]


def test_arm_only_takes_open_short_legs(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    with pytest.raises(ValueError):
        ol.arm_amo([{"tradingsymbol": "NIFTYNOPE", "limit": 10}])
    ce = next(s for s, q in fake.pos.items() if q < 0)
    for bad in (0, -1, True, "x", None):
        with pytest.raises(ValueError):
            ol.arm_amo([{"tradingsymbol": ce, "limit": bad}])


def test_amocheck_alerts_when_the_amo_did_not_fill(conn):
    fake = _tuesday_broker()
    _armed(conn, fake)
    run("amo", fake, Clock(TUE, "06:18"))
    res, ctx = run("amocheck", fake, Clock(TUE, "09:20"))
    assert res["status"] == "failed" and "NOT FILLED" in ctx["sent"][-1][0] and ctx["sent"][-1][1]
    for o in fake.orders_.values():
        o.update(status="COMPLETE", filled_quantity=o["quantity"], average_price=60.0)
    res, _ = run("amocheck", fake, Clock(TUE, "09:21"))
    assert res["status"] == "ok" and ol.get_state("amo_arm") is None


def test_market_day_puts_a_night_amo_on_the_next_session():
    assert ol.market_day(datetime(2026, 11, 2, 23, 21, tzinfo=IST), set()) == "2026-11-03"
    assert ol.market_day(datetime(2026, 11, 3, 1, 0, tzinfo=IST), set()) == "2026-11-03"
    assert ol.market_day(datetime(2026, 11, 3, 10, 0, tzinfo=IST), set()) == "2026-11-03"
    assert ol.market_day(datetime(2026, 11, 7, 11, 0, tzinfo=IST), set()) == "2026-11-09"


def test_events_ahead_flags_a_heavyweights_results_and_the_open_hold(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")                                # short until NIFTY_EXP = 2026-10-27
    conn.execute("INSERT OR IGNORE INTO stocks (sid, ticker, name, cap_tier, market_cap_cr) VALUES ('RELI', 'RELIANCE', 'Reliance Industries', 'LARGE', 1800000)")
    conn.execute("INSERT OR IGNORE INTO stocks (sid, ticker, name, cap_tier, market_cap_cr) VALUES ('TINY', 'TINY', 'Tiny Ltd', 'SMALL', 500)")
    for sid, d in (("RELI", "2026-10-26"), ("TINY", "2026-10-26"), ("RELI", "2026-12-20")):
        conn.execute("INSERT INTO earnings_calendar (date, symbol, sid, company, purpose) VALUES (?, ?, ?, ?, 'Financial Results')", (d, sid, sid, sid))
    conn.commit()
    e = ol.events_ahead("2026-10-23")
    results = [x for x in e["items"] if x["kind"] == "results"]
    assert [x["what"] for x in results] == ["Reliance Industries results"] and results[0]["in_hold"] and results[0]["date"] == "2026-10-26"


def test_orders_page_shows_each_status_the_warning_and_the_arm_controls(ops, conn):
    authed, anon = ops
    fake = _tuesday_broker()
    ce = _armed(conn, fake)
    run("amo", fake, Clock(TUE, "06:18"))
    html = authed.get("/options/orders").text
    assert "Orders by day" in html and ce in html and "AMO accepted, waiting for 09:15" in html and "Placed and confirmed by Kite" in html
    assert "Results checked for the 15 largest companies" in html
    for path in ("arm", "fire", "disarm", "refresh"):
        assert anon.post(f"/api/options/orders/{path}", json={}).status_code == 401
    assert authed.post("/api/options/orders/arm", json={"legs": []}).status_code == 400   # no confirm word


# ───────────────────────────── the daily position check (ADR 0095) ─────────────────────────────

def _leg(sym, ot, k, net, sold=None, bought=None):
    return {"tradingsymbol": sym, "option_type": ot, "strike": float(k), "net_qty": net, "sell_qty": -net if sold else 0, "sell_avg": sold,
            "buy_qty": net if bought else 0, "buy_avg": bought}


def _chain_of(rows):
    return pd.DataFrame([{"option_type": o, "strike": float(k), "bid": m, "ask": m, "mid": m} for o, k, m in rows])


def test_position_math_replays_the_2026_11_02_close():
    """The real settle prices of that evening, and the real 16-lot short strangle with the wings gone."""
    chain = _chain_of([("CE", 23300, 91.15), ("PE", 23300, 62.65), ("CE", 23350, 65.75), ("PE", 23350, 86.35), ("CE", 23400, 46.35), ("PE", 23400, 114.5),
                       ("CE", 23500, 21.15), ("PE", 23500, 188.0), ("CE", 23700, 4.0), ("PE", 22400, 2.65), ("PE", 22200, 1.2)])
    legs_ = [_leg("23500CE", "CE", 23500, -1040, sold=6.5), _leg("22400PE", "PE", 22400, -1040, sold=8.3)]
    r = ol.position_math(chain, legs_, "2026-11-02", "2026-11-03", 200_000)
    assert 23_300 < r["forward"] < 23_360 and 0.7 < r["sigma_pct"] < 0.9
    near = next(s for s in r["shorts"] if s["strike"] == 23500)
    assert 0.7 < near["z"] < 1.1 and near["ask"] == 21.15
    assert abs(r["keep_rs"] - 15392) < 1 and r["verdict"] == "over" and r["tail_rs"] < -200_000
    assert abs(r["close_cost_rs"] - (21.15 + 2.65) * 1040) < 1
    assert ol.position_math(chain, legs_, "2026-11-02", "2026-11-03", 300_000)["verdict"] == "watch"


def test_wings_reduce_the_bad_day():
    chain = _chain_of([("CE", 98, 6.0), ("PE", 98, 4.0), ("CE", 100, 5.0), ("PE", 100, 5.0), ("CE", 102, 4.0), ("PE", 102, 6.0),
                       ("CE", 105, 1.0), ("PE", 95, 1.0), ("CE", 108, 0.5), ("PE", 92, 0.5)])
    naked = [_leg("C", "CE", 105, -100, sold=2.0), _leg("P", "PE", 95, -100, sold=2.0)]
    winged = naked + [_leg("WC", "CE", 108, 100, bought=0.5), _leg("WP", "PE", 92, 100, bought=0.5)]
    a = ol.position_math(chain, naked, "2026-11-02", "2026-11-03", 10 ** 9)
    b = ol.position_math(chain, winged, "2026-11-02", "2026-11-03", 10 ** 9)
    assert b["moves"][2]["up"] > a["moves"][2]["up"]


def test_poscheck_places_nothing_and_alerts_only_when_over_the_limit(conn):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    res, ctx = run("poscheck", fake, Clock(TUE, "10:00"), position_limit_rs=10 ** 8)
    assert res["status"] == "ok" and "place_order" not in fake.names() and not ctx["sent"]
    res, ctx = run("poscheck", fake, Clock(TUE, "10:00"), position_limit_rs=0)
    if "OVER YOUR LIMIT" in res["detail"]:
        assert ctx["sent"][-1][1]


def test_poscheck_without_a_session_alerts_and_a_crash_does_not_stop_the_step(conn, monkeypatch):
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    res, ctx = run("poscheck", NoKiteSession("x"), Clock(TUE, "10:00"))
    assert res["status"] == "failed" and ctx["sent"][-1][1]
    monkeypatch.setattr(ol, "position_math", lambda *a, **k: 1 / 0)
    res, ctx = run("record", fake, Clock(TUE, "15:45"))
    assert res["status"] == "ok" and "Position check failed" in ctx["sent"][-1][0] and ctx["sent"][-1][1]


def test_orders_page_shows_the_position_check(ops, conn):
    authed, _ = ops
    fake = _tuesday_broker()
    _enter_nifty_friday(conn, fake, "auto")
    run("poscheck", fake, Clock(TUE, "10:00"))
    html = authed.get("/options/orders").text
    assert "position check" in html and "Your choices:" in html and "if it stays here to expiry" in html
