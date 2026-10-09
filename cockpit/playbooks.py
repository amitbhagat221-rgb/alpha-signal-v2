"""
Alpha Signal Cockpit — Investor Playbooks data layer (/playbooks).

Other ways to read the same raw data than the factor ranking: filters, events and
watchlists in the style of well-known investors. None of these feed daily_picks and
none is a ranked alpha list — each tab states its rule on the page, and the rule
lives here as a named constant.

  avoid_list()      inversion (Munger / Pabrai): stocks with two or more red flags
  insider_buying()  promoters and directors buying their own stock in the open market
  compounders()     Buffett-style quality list, ordered by how far below its high it trades
  superinvestors()  cloning (Pabrai): followed investors + individuals above 1% in many companies
  breakouts()       O'Neil / Minervini: good results, heavy delivery, price near its high
  deep_value()      Graham: at or below book, earning, little debt — with the red flags beside it
  categories()      Lynch: each business sorted into the six kinds he judged by different rules
  market_cycle()    Marks: a handful of readings on where the market stands, no single score
  say_do()          Fisher: does management deliver what it told investors (LLM, output/say_do.py)

Factor values (earnings yield, book-to-price, delivery anomaly, announcement reaction…)
come from the latest daily_snapshots_pit row — the same numbers the ranking uses.

Reads: stocks, shareholding, forensic_scores, surveillance_flags, bse_announcements,
insider_trades, fundamentals_screener, stock_prices, shareholding_holders.
"""

import re
from datetime import date, timedelta

import pandas as pd

import views
from cockpit._shared import _persisted_cache
from db import read_sql, scalar

# ── rules (shown on the page from these values) ──
# The portfolio rules live in sleeves.py so the backtest tests exactly what the page shows.
import sleeves
from sleeves import (BREAKOUT_DELIVERY_Z, BREAKOUT_POSITION, DEEP_BOOK_TO_PRICE, DEEP_EARNINGS_YIELD,  # noqa: F401
                     DEEP_MAX_DEBT_TO_EQUITY, DEEP_MIN_PE, DEEP_MIN_PRICE_TO_BOOK, INSIDER_CATEGORIES, INSIDER_DAYS,
                     INSIDER_MIN_BUYERS, INSIDER_MIN_CR, PLEDGE_PCT, RESIGNATION_DAYS, RESIGNATIONS, ROCE_BAR,
                     SALES_CAGR_BAR)

SURVEILLANCE = {"ASM_LT": "long-term surveillance (ASM)", "GSM": "graded surveillance (GSM)"}
AVOID_MIN_FLAGS = 2

ROCE_YEARS = 10                 # the page's compounder rule; the backtest uses sleeves.QUALITY_YEARS
ROCE_MIN_HITS = 8
COMPOUNDER_LIMIT = 80

VALUE_MIN_HISTORY = 24          # month-ends of own history needed to call a stock cheap or dear

FAST_GROWTH = 20                # % a year, 3-year sales growth
SLOW_GROWTH = 8
CYCLICAL_SECTORS = ("Materials", "Energy", "Real Estate")
CATEGORY_EXAMPLES = 12

FOLLOWED = sleeves.FOLLOWED          # the registry lives with the cloning rule

HOLDER_LOOKBACK_DAYS = 300      # covers the latest filing and the one before it
INVESTOR_MIN_STOCKS = 5
INVESTOR_LIMIT = 40
_INDIVIDUAL = "ShareholdersHoldingNominalShareCapitalInExcessOfRsTwoLakh"


def _stocks():
    return read_sql("SELECT sid, ticker, name, sector, cap_tier FROM stocks").set_index("sid")


def _since(days):
    return (date.today() - timedelta(days=days)).isoformat()


_SNAP_COLS = ("earnings_yield", "book_to_price", "debt_to_equity", "position_52w", "delivery_anomaly_z",
              "announcement_car", "mom_6m", "roic", "fcf_yield")


@_persisted_cache(900, name="playbook_snapshot")
def _snapshot():
    """Latest factor values per stock (daily_snapshots_pit), indexed by sid."""
    snap = scalar("SELECT MAX(snapshot_date) FROM daily_snapshots_pit")
    df = read_sql(f"SELECT sid, {', '.join(_SNAP_COLS)} FROM daily_snapshots_pit WHERE snapshot_date = ?", params=[snap])
    return {"date": snap, "rows": df.set_index("sid")}


def _flag_counts():
    """{sid: number of avoid-list checks tripped} — shown beside every other screen."""
    return avoid_list()["flag_counts"]


def _base(sid, stocks):
    s = stocks.loc[sid]
    return {"sid": sid, "ticker": s["ticker"], "name": s["name"], "tier": s["cap_tier"], "sector": s["sector"]}


# ═══════════════════════════ 1. Avoid list ═══════════════════════════

@_persisted_cache(900, name="playbook_avoid_v3")
def avoid_list():
    """Stocks carrying AVOID_MIN_FLAGS or more red flags, most flags first."""
    stocks = _stocks()
    flags = {}                                           # sid → [(key, detail)]

    def add(sid, key, detail):
        if sid in stocks.index:
            flags.setdefault(sid, []).append((key, detail))

    pledge = read_sql(
        "SELECT sid, pledge_pct, end_date FROM shareholding WHERE (sid, end_date) IN "
        "(SELECT sid, MAX(end_date) FROM shareholding WHERE end_date >= ? GROUP BY sid) AND pledge_pct >= ?",
        params=[_since(270), PLEDGE_PCT])
    for r in pledge.itertuples():
        add(r.sid, "pledge", f"{r.pledge_pct:.0f}% of promoter shares pledged ({r.end_date})")

    snap = scalar("SELECT MAX(snapshot_date) FROM forensic_scores")
    forensic = read_sql("SELECT sid, m_score_flag, z_score_flag FROM forensic_scores WHERE snapshot_date = ?",
                        params=[snap])
    for r in forensic.itertuples():
        if r.m_score_flag == "LIKELY_MANIPULATOR":
            add(r.sid, "accounts", "accounts look manipulated (Beneish M-score)")
        if r.z_score_flag == "DISTRESS" and r.sid in stocks.index and stocks.at[r.sid, "sector"] != "Financials":
            add(r.sid, "distress", "balance sheet in the distress zone (Altman Z-score)")

    surv = read_sql(
        "SELECT f.sid, f.flag_type, f.stage FROM surveillance_flags f JOIN "
        "(SELECT flag_type, MAX(flag_date) AS d FROM surveillance_flags GROUP BY flag_type) m "
        f"ON m.flag_type = f.flag_type AND m.d = f.flag_date WHERE f.flag_type IN ({','.join('?' * len(SURVEILLANCE))})",
        params=list(SURVEILLANCE))
    for r in surv.itertuples():
        add(r.sid, "surveillance", f"under exchange {SURVEILLANCE[r.flag_type]}" + (f", {r.stage}" if r.stage and len(str(r.stage)) > 2 else ""))

    resign = read_sql(
        f"SELECT sid, subcategory, MAX(substr(dt_tm, 1, 10)) AS d FROM bse_announcements "
        f"WHERE subcategory IN ({','.join('?' * len(RESIGNATIONS))}) AND dt_tm >= ? AND sid IS NOT NULL "
        "GROUP BY sid, subcategory", params=[*RESIGNATIONS, _since(RESIGNATION_DAYS)])
    for r in resign.itertuples():
        who = r.subcategory.replace("Resignation of ", "").split(" (")[0]
        add(r.sid, "resignation", f"{who} resigned ({r.d})")

    labels = {"pledge": "Heavy pledging", "accounts": "Accounts flagged", "distress": "Distress zone",
              "surveillance": "Exchange surveillance", "resignation": "Key resignation"}
    counts = {k: sum(any(f[0] == k for f in v) for v in flags.values()) for k in labels}
    rows = []
    for sid, fl in flags.items():
        kinds = sorted({k for k, _ in fl})
        if len(kinds) >= AVOID_MIN_FLAGS:
            s = stocks.loc[sid]
            rows.append({"sid": sid, "ticker": s["ticker"], "name": s["name"], "sector": s["sector"],
                         "tier": s["cap_tier"], "n_flags": len(kinds), "kinds": kinds,
                         "flags": [{"label": labels[k], "detail": d} for k, d in sorted(fl)]})
    tier_order = {t: i for i, t in enumerate(views.tiers())}
    rows.sort(key=lambda r: (-r["n_flags"], tier_order.get(r["tier"], 99), r["ticker"]))
    listed = {k: sum(k in r["kinds"] for r in rows) for k in labels}
    return {"rows": rows,
            "counts": [{"key": k, "label": labels[k], "n": counts[k], "n_listed": listed[k]} for k in labels],
            "n_any": len(flags), "as_of": snap,
            "flag_counts": {sid: len({k for k, _ in fl}) for sid, fl in flags.items()}}


# ═══════════════════════════ 2. Insider buying ═══════════════════════════

@_persisted_cache(900, name="playbook_insiders_v2")
def insider_buying():
    """Stocks where promoters / directors were net buyers over INSIDER_DAYS."""
    ph = ",".join("?" * len(INSIDER_CATEGORIES))
    t = read_sql(
        f"SELECT sid, person, transaction_type AS side, value_lakhs, trade_date FROM insider_trades "
        f"WHERE trade_date >= ? AND person_category IN ({ph}) AND transaction_type IN ('Buy', 'Sell') "
        "AND value_lakhs > 0", params=[_since(INSIDER_DAYS), *INSIDER_CATEGORIES])
    if t.empty:
        return {"rows": [], "as_of": None}
    stocks = _stocks()
    rows = [{**_base(r.sid, stocks), **{k: getattr(r, k) for k in
                                        ("buyers", "n_buys", "bought_cr", "sold_cr", "net_cr", "last_buy", "top_buyer", "cluster")}}
            for r in sleeves.insider_net_buyers(t).itertuples() if r.sid in stocks.index]
    rows.sort(key=lambda r: -r["net_cr"])
    return {"rows": rows, "as_of": t["trade_date"].max(), "n_clusters": sum(r["cluster"] for r in rows)}


# ═══════════════════════════ 3. Compounders ═══════════════════════════

@_persisted_cache(3600, name="playbook_compounders_v4")
def compounders():
    """Non-financial businesses that earned ROCE_BAR% on capital in ROCE_MIN_HITS of the
    last ROCE_YEARS fiscal years, never made a loss in that window and grew sales by
    SALES_CAGR_BAR% a year — ordered by how far the price sits below its 52-week high.
    Return on capital = (profit before tax + interest) / (equity + reserves + borrowings)."""
    stocks = _stocks()
    out, annual = [], {}
    for sid, years in sleeves.annual_statements().items():
        if sid not in stocks.index or stocks.at[sid, "sector"] == "Financials":
            continue
        q = sleeves.quality_stats(years, ROCE_YEARS, ROCE_MIN_HITS)
        if q is None:
            continue
        annual[sid] = years[["period_end", "Net profit"]].dropna()
        out.append({**_base(sid, stocks), **q, "fy": years["period_end"].iloc[-1][:7]})
    metrics = _adjusted_year([r["sid"] for r in out])
    value = _own_history_value([r["sid"] for r in out], annual)
    flags = _flag_counts()
    for r in out:
        r["from_high"], r["return_1y"] = metrics.get(r["sid"], (None, None))
        r.update(value.get(r["sid"], {"pe": None, "cheaper_than": None, "vs_median": None, "since": None}))
        r["flags"] = flags.get(r["sid"], 0)
    # cheapest against its own history first; stocks without enough history last
    out.sort(key=lambda r: (r["cheaper_than"] is None, -(r["cheaper_than"] or 0)))
    tiers = {}
    for r in out:
        tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
    return {"rows": out[:COMPOUNDER_LIMIT], "n": len(out), "tier_counts": tiers,
            "n_cheap": sum((r["cheaper_than"] or 0) >= 75 for r in out),
            "history_from": min((r["since"] for r in out if r["since"]), default=None)}


def _own_history_value(sids, annual):
    """{sid: {pe, vs_median, cheaper_than, since}} — how today's price-to-earnings compares
    with the stock's own month-end history.

    The multiple's HISTORY is price ÷ annual net profit, with the price adjusted for splits
    and bonuses only and the profit being the latest fiscal year public at the time
    (period end + 75 days). On that basis the share count cancels, so no vendor share
    count is divided by an old price. `pe` (today's level) is the ranking's own earnings
    yield. History starts where both prices and corporate actions exist, so it lengthens
    by itself as older prices and actions are loaded."""
    if not sids:
        return {}
    sids, ph = views.sid_params(sids)
    floor = scalar("SELECT MIN(ex_date) FROM corporate_actions") or "2020-01-01"
    px = read_sql(f"SELECT sid, date, close FROM stock_prices WHERE close > 0 AND date >= ? AND sid IN ({ph}) "
                  "AND date IN (SELECT MAX(date) FROM stock_prices WHERE date >= ? GROUP BY substr(date, 1, 7)) "
                  "ORDER BY sid, date", params=[floor, *sids, floor])
    adj = read_sql(f"SELECT sid, ex_date, factor FROM corporate_adjustments WHERE sid IN ({ph}) "
                   "AND (inds LIKE '%SPLIT%' OR inds LIKE '%BONUS%') ORDER BY sid, ex_date", params=list(sids))
    from signals._prices import apply_adjustments
    px = apply_adjustments(px, adj, date.today())
    snap = _snapshot()["rows"]["earnings_yield"]
    out = {}
    for sid, g in px.groupby("sid"):
        a = annual.get(sid)
        if a is None:
            continue
        known = pd.to_datetime(a["period_end"]) + pd.Timedelta(days=75)
        profit = pd.Series(a["Net profit"].values, index=known).sort_index()
        m = pd.merge_asof(pd.DataFrame({"t": pd.to_datetime(g["date"]), "adj": g["adj_close"].values}),
                          profit.rename("np").rename_axis("t").reset_index(), on="t")
        m = m[m["np"] > 0]
        if len(m) < VALUE_MIN_HISTORY:
            continue
        ratio = m["adj"] / m["np"]
        now, ey = ratio.iloc[-1], snap.get(sid)
        out[sid] = {"pe": round(1 / ey, 1) if ey is not None and ey > 0 else None,
                    "vs_median": round((now / ratio.median() - 1) * 100),
                    "cheaper_than": round(float((ratio > now).mean()) * 100), "since": str(m["t"].iloc[0].date())[:7]}
    return out


def _adjusted_year(sids):
    """{sid: (% below the 52-week high, 1-year return %)} on split/bonus-adjusted closes —
    a raw close makes a bonus issue look like a crash."""
    if not sids:
        return {}
    from signals._prices import apply_adjustments
    sids, ph = views.sid_params(sids)
    prices = read_sql(f"SELECT sid, date, close FROM stock_prices WHERE close > 0 AND date >= ? AND sid IN ({ph}) "
                      "ORDER BY sid, date", params=[_since(366), *sids])
    adj = read_sql(f"SELECT sid, ex_date, factor FROM corporate_adjustments WHERE sid IN ({ph}) ORDER BY sid, ex_date",
                   params=list(sids))
    out = {}
    for sid, g in apply_adjustments(prices, adj, date.today()).groupby("sid"):
        c = g["adj_close"]
        if len(c) >= 5:
            out[sid] = (round((c.iloc[-1] / c.max() - 1) * 100, 1),
                        round((c.iloc[-1] / c.iloc[0] - 1) * 100, 1) if len(c) >= 200 else None)
    return out


# ═══════════════════════════ 4. Superinvestors ═══════════════════════════

_norm = sleeves.norm_name


@_persisted_cache(900, name="playbook_superinvestors_v2")
def superinvestors():
    """Individuals (not promoters) named above 1% in INVESTOR_MIN_STOCKS or more
    companies in each company's latest filing, with the change against the filing
    before it. Names are grouped on exact spelling after upper-casing and stripping
    punctuation — one person filed under two spellings shows as two."""
    h = read_sql(
        "SELECT sid, end_date, filed_at, holder_name, pct FROM shareholding_holders "
        "WHERE end_date >= ? AND holder_category LIKE ? AND promoter_type IS NULL",
        params=[_since(HOLDER_LOOKBACK_DAYS), f"%{_INDIVIDUAL}"])
    filings = read_sql("SELECT sid, end_date, MAX(filed_at) AS filed_at FROM shareholding_holders "
                       "WHERE end_date >= ? GROUP BY sid, end_date", params=[_since(HOLDER_LOOKBACK_DAYS)])
    if h.empty:
        return {"followed": [], "investors": [], "as_of": None, "n_stocks": 0, "n_with_prior": 0}
    stocks = _stocks()
    h = h.merge(filings, on=["sid", "end_date", "filed_at"])          # the latest revision of each quarter
    h["who"] = h["holder_name"].map(_norm)
    h = h.groupby(["sid", "end_date", "who"], as_index=False).agg(pct=("pct", "sum"), name=("holder_name", "first"))
    quarters = {sid: sorted(g["end_date"], reverse=True)[:2] for sid, g in filings.groupby("sid")}
    now = h[[quarters[s][0] == e for s, e in zip(h["sid"], h["end_date"])]]
    prev = h[[len(quarters[s]) > 1 and quarters[s][1] == e for s, e in zip(h["sid"], h["end_date"])]]
    prev_pct = {(r.who, r.sid): r.pct for r in prev.itertuples()}
    has_prev = {s for s, q in quarters.items() if len(q) > 1}

    counts = now.groupby("who")["sid"].nunique()
    keep = set(counts[counts >= INVESTOR_MIN_STOCKS].index)
    investors = []
    for who, g in now[now["who"].isin(keep)].groupby("who"):
        holdings = []
        for r in g.itertuples():
            if r.sid not in stocks.index:
                continue
            before = prev_pct.get((who, r.sid))
            if r.sid not in has_prev:
                change, delta = "unknown", None
            elif before is None:
                change, delta = "new", None
            else:
                delta = round((r.pct or 0) - (before or 0), 2)
                change = "up" if delta > 0.05 else "down" if delta < -0.05 else "same"
            s = stocks.loc[r.sid]
            holdings.append({"sid": r.sid, "ticker": s["ticker"], "name": s["name"], "tier": s["cap_tier"],
                             "pct": round(r.pct, 2) if r.pct is not None else None, "change": change, "delta": delta, "quarter": r.end_date})
        gone = [{"sid": sid, "ticker": stocks.at[sid, "ticker"], "pct": round(p, 2) if p is not None else None}
                for (w, sid), p in prev_pct.items()
                if w == who and sid in stocks.index and sid not in set(g["sid"])]
        holdings.sort(key=lambda x: ({"new": 0, "up": 1, "down": 2, "same": 3, "unknown": 4}[x["change"]], -(x["pct"] or 0)))
        investors.append({"name": g["name"].iloc[0].title(), "n": len(holdings), "holdings": holdings, "below_1pct": gone,
                          "n_new": sum(x["change"] == "new" for x in holdings),
                          "n_up": sum(x["change"] == "up" for x in holdings),
                          "n_down": sum(x["change"] == "down" for x in holdings)})
    followed_names = {_norm(n) for f in _followed(quarters, has_prev, stocks) for n in f["filed_as"]}
    investors = [i for i in investors if _norm(i["name"]) not in followed_names]
    investors.sort(key=lambda i: -i["n"])
    return {"followed": _followed(quarters, has_prev, stocks), "investors": investors[:INVESTOR_LIMIT],
            "as_of": max(q[0] for q in quarters.values()),
            "n_stocks": len(quarters), "n_with_prior": len(has_prev)}


def _followed(quarters, has_prev, stocks):
    """FOLLOWED investors' holdings: every non-promoter filed name that carries all the
    words of one of the investor's patterns, summed per stock."""
    h = read_sql("SELECT sid, end_date, filed_at, holder_name, pct FROM shareholding_holders "
                 "WHERE end_date >= ? AND promoter_type IS NULL", params=[_since(HOLDER_LOOKBACK_DAYS)])
    latest = h.groupby(["sid", "end_date"])["filed_at"].transform("max")
    h = h[h["filed_at"] == latest]
    tokens = {n: set(_norm(n).split()) for n in h["holder_name"].unique()}
    out = []
    for who, patterns in FOLLOWED.items():
        names = {n for n, t in tokens.items() if any(set(p) <= t for p in patterns)}
        mine = h[h["holder_name"].isin(names)]
        if mine.empty:
            continue
        by = mine.groupby(["sid", "end_date"])["pct"].sum()
        holdings = []
        for sid, q in quarters.items():
            if sid not in stocks.index or (sid, q[0]) not in by.index:
                continue
            pct = float(by[(sid, q[0])])
            before = float(by[(sid, q[1])]) if len(q) > 1 and (sid, q[1]) in by.index else None
            if sid not in has_prev:
                change, delta = "unknown", None
            elif before is None:
                change, delta = "new", None
            else:
                delta = round(pct - before, 2)
                change = "up" if delta > 0.05 else "down" if delta < -0.05 else "same"
            holdings.append({**_base(sid, stocks), "pct": round(pct, 2), "change": change, "delta": delta, "quarter": q[0]})
        gone = [{"sid": sid, "ticker": stocks.at[sid, "ticker"], "pct": round(float(by[(sid, q[1])]), 2)}
                for sid, q in quarters.items()
                if len(q) > 1 and sid in stocks.index and (sid, q[1]) in by.index and (sid, q[0]) not in by.index]
        holdings.sort(key=lambda x: ({"new": 0, "up": 1, "down": 2, "same": 3, "unknown": 4}[x["change"]], -x["pct"]))
        out.append({"name": who, "n": len(holdings), "holdings": holdings, "below_1pct": gone,
                    "filed_as": sorted(names), "n_new": sum(x["change"] == "new" for x in holdings),
                    "n_up": sum(x["change"] == "up" for x in holdings),
                    "n_down": sum(x["change"] == "down" for x in holdings)})
    out.sort(key=lambda i: -i["n"])
    return out


# ═══════════════════════════ 5. Breakouts ═══════════════════════════

@_persisted_cache(900, name="playbook_breakouts")
def breakouts():
    """Pickable-tier stocks whose last results were received well (positive announcement
    reaction), that trade near their 52-week high with delivery well above their own norm
    and positive 6-month momentum."""
    snap, stocks, flags = _snapshot(), _stocks(), _flag_counts()
    df = snap["rows"]
    hit = df[sleeves.breakout_mask(df)]
    pickable = set(views.pickable_tiers())
    rows = [{**_base(sid, stocks), "reaction": round(r.announcement_car * 100, 1), "delivery_z": round(r.delivery_anomaly_z, 1),
             "position": round(r.position_52w * 100), "mom_6m": round(r.mom_6m),
             "flags": flags.get(sid, 0)}
            for sid, r in hit.iterrows() if sid in stocks.index and stocks.at[sid, "cap_tier"] in pickable]
    rows.sort(key=lambda r: -r["delivery_z"])
    return {"rows": rows, "as_of": snap["date"]}


# ═══════════════════════════ 6. Deep value ═══════════════════════════

@_persisted_cache(900, name="playbook_deep_value")
def deep_value():
    """Non-financial stocks priced at or below book value that earn DEEP_EARNINGS_YIELD on
    the price and carry little debt — with their red flags, because in India a cheap stock
    is usually cheap for a reason."""
    snap, stocks, flags = _snapshot(), _stocks(), _flag_counts()
    df = snap["rows"]
    cheap = df[(df["book_to_price"] >= DEEP_BOOK_TO_PRICE) & (df["earnings_yield"] >= DEEP_EARNINGS_YIELD)
               & (df["debt_to_equity"].fillna(0) <= DEEP_MAX_DEBT_TO_EQUITY)]
    n_suspect, hit = int((~sleeves.deep_value_sane(cheap)).sum()), df[sleeves.deep_value_mask(df)]
    cash = read_sql("SELECT sid, cash_and_equivalents - COALESCE(total_debt, 0) AS net_cash FROM annual_balance_sheet "
                    "WHERE (sid, end_date) IN (SELECT sid, MAX(end_date) FROM annual_balance_sheet GROUP BY sid)")
    net_cash = dict(zip(cash["sid"], cash["net_cash"]))
    rows = [{**_base(sid, stocks), "price_to_book": round(1 / r.book_to_price, 2), "pe": round(1 / r.earnings_yield, 1),
             "debt_to_equity": None if pd.isna(r.debt_to_equity) else round(r.debt_to_equity, 2),
             "net_cash": bool((net_cash.get(sid) or 0) > 0), "flags": flags.get(sid, 0)}
            for sid, r in hit.iterrows() if sid in stocks.index and stocks.at[sid, "sector"] != "Financials"]
    rows.sort(key=lambda r: (r["flags"], r["price_to_book"]))
    return {"rows": rows, "as_of": snap["date"], "n_clean": sum(r["flags"] == 0 for r in rows), "n_suspect": n_suspect}


# ═══════════════════════════ 7. Lynch categories ═══════════════════════════

CATEGORIES = [   # key, label, the rule, how Lynch read it
    ("turnaround", "Turnarounds", "made a loss the year before, a profit in the latest year",
     "Ask whether the cause of the loss is gone. Balance-sheet survival matters more than growth."),
    ("asset", "Asset plays", "priced at or below book value",
     "The value is on the balance sheet, not in earnings. Check that the assets are real and can be realised."),
    ("cyclical", "Cyclicals", "Materials, Energy and Real Estate businesses",
     "A low price-to-earnings is a warning here: earnings peak just before the cycle turns."),
    ("fast", "Fast growers", f"sales growing {FAST_GROWTH}% a year or more over three years, profitable",
     "Where the big winners come from. Ask how long the growth can last and what it costs."),
    ("stalwart", "Stalwarts", f"LARGE or MID companies growing sales {SLOW_GROWTH}–{FAST_GROWTH}% a year",
     "Steady compounders. Buy when out of favour, take profits after a strong run."),
    ("slow", "Slow growers", f"sales growing under {SLOW_GROWTH}% a year, profitable",
     "Owned for the dividend, if at all. Little reason to expect the price to do much."),
]


@_persisted_cache(3600, name="playbook_categories")
def categories():
    """Every non-financial stock with three years of statements, in ONE of Lynch's six
    kinds (first rule that matches, in CATEGORIES order)."""
    raw = read_sql("SELECT sid, period_end, line_item, value FROM fundamentals_screener WHERE period_type = 'annual' "
                   "AND line_item IN ('Sales', 'Net profit')")
    stocks, snap = _stocks(), _snapshot()["rows"]
    wide = raw.pivot_table(index=["sid", "period_end"], columns="line_item", values="value", aggfunc="first").reset_index()
    wide["month"] = wide["period_end"].str[5:7]
    members = {k: [] for k, *_ in CATEGORIES}
    for sid, g in wide.groupby("sid"):
        if sid not in stocks.index or stocks.at[sid, "sector"] == "Financials":
            continue
        g = g[g["month"] == g["month"].mode().iloc[0]].sort_values("period_end").tail(4)
        if len(g) < 4 or not (g["Sales"].iloc[0] > 0 and g["Sales"].iloc[-1] > 0):
            continue
        growth = ((g["Sales"].iloc[-1] / g["Sales"].iloc[0]) ** (1 / 3) - 1) * 100
        profit, before = g["Net profit"].iloc[-1], g["Net profit"].iloc[-2]
        tier, sector = stocks.at[sid, "cap_tier"], stocks.at[sid, "sector"]
        btp = snap["book_to_price"].get(sid)
        if before <= 0 < profit:
            key = "turnaround"
        elif btp is not None and btp >= DEEP_BOOK_TO_PRICE:
            key = "asset"
        elif sector in CYCLICAL_SECTORS:
            key = "cyclical"
        elif growth >= FAST_GROWTH and profit > 0:
            key = "fast"
        elif tier in ("LARGE", "MID") and growth >= SLOW_GROWTH and profit > 0:
            key = "stalwart"
        elif growth < SLOW_GROWTH and profit > 0:
            key = "slow"
        else:
            continue
        ey = snap["earnings_yield"].get(sid)
        members[key].append({**_base(sid, stocks), "growth": round(growth), "pe": round(1 / ey, 1) if ey and ey > 0 else None})
    tier_order = {t: i for i, t in enumerate(views.tiers())}
    out = []
    for key, label, rule, reading in CATEGORIES:
        rows = sorted(members[key], key=lambda r: (tier_order.get(r["tier"], 99), -r["growth"]))
        tiers = {}
        for r in rows:
            tiers[r["tier"]] = tiers.get(r["tier"], 0) + 1
        out.append({"key": key, "label": label, "rule": rule, "reading": reading, "n": len(rows),
                    "tier_counts": tiers, "examples": rows[:CATEGORY_EXAMPLES]})
    return {"categories": out, "n": sum(c["n"] for c in out)}


# ═══════════════════════════ 8. Market cycle ═══════════════════════════

def _pctile(series, value):
    """Share of `series` below `value`, 0-100."""
    s = pd.Series(series).dropna()
    return None if s.empty or value is None or pd.isna(value) else round(float((s < value).mean()) * 100)


@_persisted_cache(3600, name="playbook_cycle")
def market_cycle():
    """Readings on where the market stands, each against its own history. Deliberately no
    combined score: Marks's point is to know roughly where you are, not to time it."""
    readings = []

    vix = read_sql("SELECT date, vix FROM vix_history ORDER BY date")
    if not vix.empty:
        now, p = float(vix["vix"].iloc[-1]), _pctile(vix["vix"], vix["vix"].iloc[-1])
        readings.append({"label": "Fear (India VIX)", "value": f"{now:.1f}", "as_of": vix["date"].iloc[-1],
                         "context": f"lower than on {100 - p}% of days since {vix['date'].iloc[0][:4]}",
                         "reading": "Complacent — protection is cheap, surprises hurt more" if p <= 25
                         else "Fearful — historically a better time to buy than to sell" if p >= 75 else "Ordinary"})

    idx = read_sql("SELECT trade_date, close FROM nse_index_history WHERE index_symbol = 'NIFTY SMALLCAP 250' "
                   "AND close > 0 ORDER BY trade_date")
    if len(idx) > 200:
        c = idx["close"]
        dd = (c.iloc[-1] / c.max() - 1) * 100
        vs200 = (c.iloc[-1] / c.tail(200).mean() - 1) * 100
        readings.append({"label": "Small caps (Nifty Smallcap 250)", "value": f"{dd:+.0f}% from peak", "as_of": idx["trade_date"].iloc[-1],
                         "context": f"{vs200:+.0f}% against its 200-day average; peak since {idx['trade_date'].iloc[0][:4]}",
                         "reading": "At or near the high — optimism is in the price" if dd > -5
                         else "In a deep drawdown — pessimism is in the price" if dd <= -20 else "Off the high"})

    panel = read_sql("SELECT snapshot_date, cap_tier, mom_6m, book_to_price FROM daily_snapshots_pit")
    if not panel.empty:
        breadth = panel.dropna(subset=["mom_6m"]).groupby("snapshot_date")["mom_6m"].apply(lambda m: (m > 0).mean() * 100)
        now, p = float(breadth.iloc[-1]), _pctile(breadth, breadth.iloc[-1])
        readings.append({"label": "Breadth (stocks up over 6 months)", "value": f"{now:.0f}%", "as_of": breadth.index[-1],
                         "context": f"higher than on {p}% of snapshots since {breadth.index[0][:4]}",
                         "reading": "Almost everything is rising — late in an advance" if p >= 80
                         else "Almost everything is falling — late in a decline" if p <= 20 else "Mixed"})
        large = panel[(panel["cap_tier"] == "LARGE") & (panel["book_to_price"] > 0)]
        btp = large.groupby("snapshot_date")["book_to_price"].median()
        if len(btp) > 12:
            now, p = float(btp.iloc[-1]), _pctile(btp, btp.iloc[-1])
            readings.append({"label": "Large-cap valuation (median price-to-book)", "value": f"{1 / now:.1f}×", "as_of": btp.index[-1],
                             "context": f"cheaper than on {p}% of snapshots since {btp.index[0][:4]}",
                             "reading": "Expensive against its own recent history" if p <= 25
                             else "Cheap against its own recent history" if p >= 75 else "Around its usual level"})

    flows = read_sql("SELECT category, SUM(net_value_cr) AS net, MIN(flow_date) AS d0, MAX(flow_date) AS d1 FROM fii_dii_cash_flow "
                     "WHERE flow_date >= ? GROUP BY category", params=[_since(30)])
    for r in flows.itertuples():
        who = "Foreign investors" if r.category.startswith("FII") else "Domestic institutions"
        readings.append({"label": f"{who}, last 30 days", "value": f"{'+' if r.net >= 0 else '−'}₹{abs(r.net):,.0f} cr", "as_of": r.d1,
                         "context": "net bought" if r.net > 0 else "net sold",
                         "reading": "No history to compare against yet (flows stored since April 2026)"})

    regime = views.regime() or {}
    return {"readings": readings, "regime": regime.get("regime")}


# ═══════════════════════════ 9. Say vs do ═══════════════════════════

VERDICT_LABELS = {"keeps_word": "Keeps its word", "mixed": "Mixed record", "overpromises": "Overpromises",
                  "no_guidance": "Gives no checkable guidance"}
OUTCOME_LABELS = {"delivered": "Delivered", "partly": "Partly", "missed": "Missed", "not_addressed": "Not mentioned"}


def say_do():
    """Stored say-vs-do verdicts (output/say_do.py), best record first, and how much of
    the queue is still to run. Not cached: verdicts arrive as the LLM worker drains."""
    from output import say_do as sd
    stocks = _stocks()
    order = {v: i for i, v in enumerate(VERDICT_LABELS)}
    rows = []
    for d in sd.load():
        if d.get("sid") not in stocks.index:
            continue
        rows.append({**_base(d["sid"], stocks), "verdict": d["verdict"], "label": VERDICT_LABELS.get(d["verdict"], d["verdict"]),
                     "summary": d["summary"], "latest_call": d.get("latest_call"), "earlier_call": d.get("earlier_call"),
                     "promises": [{**p, "label": OUTCOME_LABELS.get(p["outcome"], p["outcome"])} for p in d["promises"]]})
    tier_order = {t: i for i, t in enumerate(views.tiers())}
    rows.sort(key=lambda r: (order.get(r["verdict"], 9), tier_order.get(r["tier"], 99), r["ticker"]))
    q = read_sql("SELECT status, COUNT(*) AS n FROM llm_tasks WHERE kind = 'say_do' GROUP BY status")
    queue = dict(zip(q["status"], q["n"]))
    return {"rows": rows, "counts": [{"key": v, "label": VERDICT_LABELS[v], "n": sum(r["verdict"] == v for r in rows)} for v in VERDICT_LABELS],
            "queued": int(queue.get("queued", 0) + queue.get("claimed", 0)), "total": int(sum(queue.values()))}


# ═══════════════════════════ 10. Portfolios ═══════════════════════════

def portfolios():
    """The sleeve backtest (tools/playbook_backtest.py → output/playbook_backtest.json) and
    the state of the forward record. Read from disk: the backtest takes minutes, so it is
    run from the command line, never on a page load."""
    import json
    from tools.playbook_backtest import OUTPUT_PATH
    bt = json.loads(OUTPUT_PATH.read_text()) if OUTPUT_PATH.exists() else None
    rec = read_sql("SELECT sleeve, COUNT(DISTINCT snapshot_date) AS days, MIN(snapshot_date) AS first, MAX(snapshot_date) AS last "
                   "FROM playbook_members GROUP BY sleeve")
    latest = read_sql("SELECT sleeve, COUNT(*) AS n FROM playbook_members WHERE snapshot_date = "
                      "(SELECT MAX(snapshot_date) FROM playbook_members) GROUP BY sleeve")
    names = dict(zip(latest["sleeve"], latest["n"]))
    labels = {k: v["label"] for k, v in sleeves.SLEEVES.items()} | {"flagged": "Red-flag set"}
    record = [{"sleeve": labels.get(r.sleeve, r.sleeve), "days": int(r.days), "first": r.first, "last": r.last,
               "names": int(names.get(r.sleeve, 0))} for r in rec.itertuples()]
    return {"backtest": bt, "record": record}


# ═══════════════════════════ the other approaches ═══════════════════════════

# Every approach from the 2026-10-04 brainstorm, so the page says what is NOT here.
ROADMAP = [
    ("Avoid list / checklist", "Munger, Pabrai", "live", "Avoid list tab; the flag count also appears beside every other screen"),
    ("Promoter and insider buying", "Event-driven", "live", "Insider buying tab"),
    ("Compounders, bought when cheap", "Buffett, Munger", "live", "Compounders tab: quality rule, then price against the stock's own history"),
    ("Cloning superinvestors", "Pabrai", "partial", "Superinvestors tab; buys and sells fill in as earlier filings load, and only stocks with a BSE listing are covered"),
    ("Earnings + delivery breakouts", "O'Neil, Minervini", "live", "Breakouts tab"),
    ("Net-nets / deep value", "Graham", "live", "Deep value tab, with red flags beside each name"),
    ("Category rules", "Lynch", "live", "Categories tab"),
    ("Market-cycle readings", "Marks, Druckenmiller", "partial", "Market cycle tab; history is short (one cycle), so read it as context, not a signal"),
    ("Downside / upside card", "Pabrai", "partial", "Deep value shows price against book and net cash; a per-stock card on Stock Detail is not built"),
    ("Management says vs does", "Fisher", "partial", "Say vs do tab; verdicts fill in as the LLM worker reads each pair of earnings calls (compounders, LARGE and MID first)"),
    ("Portfolios and backtest", "—", "live", "Portfolios tab: each testable playbook held monthly after costs, plus the forward record"),
    ("Position sizing overlay", "Thorp", "not built", "Applies to the other engines, not an idea source"),
]


# tab key -> producer. A tab's data is computed only when that tab is opened.
TABS = {
    "avoid": avoid_list, "insiders": insider_buying, "compounders": compounders, "investors": superinvestors,
    "breakouts": breakouts, "deep": deep_value, "categories": categories, "saydo": say_do, "cycle": market_cycle,
    "portfolios": portfolios,
    "roadmap": lambda: [{"approach": a, "who": w, "status": s, "note": n} for a, w, s, n in ROADMAP],
}


def rules():
    """The numeric rule constants, shown in each tab's prose."""
    return {k: v for k, v in globals().items() if k.isupper() and isinstance(v, (int, float))}


def tab_data(key):
    """The data behind one /playbooks tab (KeyError for an unknown tab)."""
    return TABS[key]()
