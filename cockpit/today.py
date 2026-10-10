"""
Alpha Signal Cockpit - the Today page ("is there anything to buy, sell or check?").

Reads named view functions only (views.py, cockpit/api.py); this module is the logic between
them and the template. The pure functions (diff_books, build_checks, rank_movers, headline) take
plain rows so tests need no database.

  buy / sell   a change to the sized book (portfolio_weights, rebuilt each morning with banded
               rebalancing, ADR 0046): in today's book but not the previous one = buy, the reverse
               = sell. The band is what keeps this from churning daily.
  check        a forensic flag (newest row per stock; Altman Z skipped for Financials) or results
               due within RESULTS_DAYS on a stock in the book or among the top picks.
"""

import config
import views
from cockpit import api, playbooks
from cockpit._shared import _ttl_cache

RESIZE_MIN = 0.01        # a weight moving by >= 1 pp of the book is a resize (below it: noise)
RESULTS_DAYS = 7
MOVER_MIN = 5            # rank places, same threshold as the diff engine
MOVER_TOP = 20           # only moves that touch the top 20 of a tier matter to a reader of picks
TOP_N = 5                # picks shown per tier


def diff_books(cur, prev, resize_min=RESIZE_MIN):
    """(buys, sells, resizes) between two sized books (lists of row dicts with sid and weight).
    buys/sells are rows of the book they come from; a resize carries `prev_weight`. prev=None
    (no earlier book) -> nothing to compare, three empty lists."""
    if prev is None:
        return [], [], []
    cur_by = {r["sid"]: r for r in cur}
    prev_by = {r["sid"]: r for r in prev}
    buys = [r for s, r in cur_by.items() if s not in prev_by]
    sells = [r for s, r in prev_by.items() if s not in cur_by]
    resizes = [{**r, "prev_weight": prev_by[s]["weight"]} for s, r in cur_by.items()
               if s in prev_by and round(abs((r["weight"] or 0) - (prev_by[s]["weight"] or 0)), 9) >= resize_min]
    return buys, sells, resizes


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def headline(buys, sells, resizes, checks, has_prev=True):
    """(sentence, nothing_to_do). 'Today: 3 buys . 2 sells . 1 check' or 'Nothing to do ...'."""
    if not has_prev:
        return "No earlier book to compare with, so no buys or sells today", False
    parts = [_plural(n, w) for n, w in ((len(buys), "buy"), (len(sells), "sell"),
                                        (len(resizes), "resize"), (len(checks), "check")) if n]
    if parts:
        return "Today: " + " · ".join(parts), False
    return "Nothing to do — the book is unchanged and nothing needs checking", True


def build_checks(flags, due, meta, financial_sectors, avoid=None, thin=None):
    """One line per issue. flags = views.forensic_flags, due = views.results_due, meta = {sid:
    {ticker, tier, sector, source}}. Altman Z distress is dropped for Financials (it does not apply
    to banks and lenders); a Beneish flag stays. avoid = {sid: playbooks.avoid_list row} (the stock
    page's "Avoid list" chip), thin = {sid: {adtv_cr, floor_cr, as_of}} for names trading below the
    book's liquidity floor."""
    out = []
    for sid, a in (avoid or {}).items():
        m = meta.get(sid)
        if m:
            out.append({"kind": "avoid", "sid": sid, "ticker": m["ticker"], "tier": m["tier"], "source": m["source"],
                        "text": f"On the Avoid list, {a['n_flags']} red flags",
                        "why": "; ".join(f"{f['label']}: {f['detail']}" for f in a["flags"])})
    for sid, t in (thin or {}).items():
        m = meta.get(sid)
        if m:
            out.append({"kind": "liquidity", "sid": sid, "ticker": m["ticker"], "tier": m["tier"], "source": m["source"],
                        "text": "Trades below the liquidity floor",
                        "why": f"20-day median traded value is ₹{t['adtv_cr']:.2f} Cr a day (as of {t['as_of']}); "
                               f"the book's floor is ₹{t['floor_cr']:.0f} Cr a day"})
    for sid, f in flags.items():
        m = meta.get(sid)
        if not m:
            continue
        z_applies = m.get("sector") not in financial_sectors
        if f.get("m_flag"):
            out.append({"kind": "forensic", "sid": sid, "ticker": m["ticker"], "tier": m["tier"], "source": m["source"],
                        "text": "Reported profits look flattered",
                        "why": f"Beneish M-score flags likely earnings manipulation (as of {f['as_of']})"})
        if f.get("z_flag") and z_applies:
            out.append({"kind": "forensic", "sid": sid, "ticker": m["ticker"], "tier": m["tier"], "source": m["source"],
                        "text": "Balance sheet in the distress zone",
                        "why": f"Altman Z-score is in the distress band (as of {f['as_of']})"})
    for sid, d in due.items():
        m = meta.get(sid)
        if not m:
            continue
        when = "today" if d["days"] == 0 else ("tomorrow" if d["days"] == 1 else f"in {d['days']} days")
        out.append({"kind": "results", "sid": sid, "ticker": m["ticker"], "tier": m["tier"], "source": m["source"],
                    "text": f"Results {when}", "days": d["days"],
                    "why": f"board meets on {d['date']} to approve results; expect a price move, the model does not trade around it"})
    # results first by date, then forensic flags; stocks in the book before top picks
    order = {"results": 0, "avoid": 1, "forensic": 2, "liquidity": 3}
    out.sort(key=lambda c: (order[c["kind"]], c.get("days", 0), c["source"] != "in book", c["ticker"]))
    return out


def rank_movers(cur, prev, top=MOVER_TOP, min_move=MOVER_MIN):
    """Within-tier rank changes between two pick days -> {tier: [{sid, ticker, from_rank, to_rank,
    score}]}, biggest move first. `cur`/`prev` = rows with sid, ticker, cap_tier, rank, final_score.
    Only moves of >= min_move places that touch the top `top` of the tier."""
    prev_rank = {r["sid"]: r["rank"] for r in prev}
    out = {}
    for r in cur:
        old = prev_rank.get(r["sid"])
        if old is None:
            continue
        if abs(old - r["rank"]) >= min_move and min(old, r["rank"]) <= top:
            out.setdefault(r["cap_tier"], []).append(
                {"sid": r["sid"], "ticker": r["ticker"], "from_rank": int(old), "to_rank": int(r["rank"]),
                 "score": r["final_score"]})
    for rows in out.values():
        rows.sort(key=lambda m: -abs(m["from_rank"] - m["to_rank"]))
    return out


def _target(ac):
    """Median analyst target upside (never the mean: it can sit outside the low-high range)."""
    up = (ac or {}).get("pt_upside_median_pct")
    if up is None:
        return None
    return {"upside_pct": up, "analysts": ac.get("total_analysts")}


def _drivers(drivers, labels):
    return [{"label": labels.get(d["factor"], d["factor"].replace("_", " ")),
             "percentile": round(d["percentile"] * 100), "inverted": d.get("inverted", False)} for d in drivers]


def _adtv(sids, asof):
    """{sid: 20-day median traded value in rupees}: portfolio_construction.adtv, the figure the
    book's liquidity floor is applied to."""
    from portfolio_construction import adtv
    return adtv(sids, asof).to_dict() if sids else {}


@_ttl_cache(120)
def build():
    """Everything the Today page shows, as one dict."""
    labels = api.get_factor_labels()
    pick_date = api.latest_pick_date()
    dates = views.pick_dates(2)
    all_cur = views.picks(pick_date, gated=False)
    cur_rows = all_cur.to_dict("records")
    ranked = {r["sid"]: r for r in cur_rows}
    pub = api.get_top_picks(top=TOP_N)
    books = views.book_history(2)
    book = books[0] if books else None
    prev = books[1] if len(books) > 1 else None
    book_rows = book["rows"] if book else []
    buys, sells, resizes = diff_books(book_rows, prev["rows"] if prev else None)
    in_book = {r["sid"] for r in book_rows}

    top_sids = [s["sid"] for t in pub.values() for s in t]
    sids = list(dict.fromkeys([r["sid"] for r in book_rows] + top_sids + [r["sid"] for r in sells]))
    ac = api.get_analyst_consensus_batch(sids)
    sizes = views.tier_sizes(pick_date)
    drivers = views.pick_drivers([r["sid"] for r in buys] + top_sids, pick_date)

    def line(sid, base):
        rk = ranked.get(sid, {})
        data = views.pick_data(rk) if rk else None
        return {**base, "sid": sid, "href": f"/stocks/{sid}", "target": _target(ac.get(sid)), "data": data,
                "drivers": _drivers(drivers.get(sid, []), labels), "in_book": sid in in_book,
                "score": rk.get("final_score"), "now_rank": rk.get("rank"),
                "now_of": sizes.get(rk.get("cap_tier"))}

    buy_rows = [line(r["sid"], {"ticker": r["ticker"], "tier": r["cap_tier"], "weight": r["weight"],
                                "rank": r["rank"]}) for r in buys]
    sell_rows = [line(r["sid"], {"ticker": r["ticker"], "tier": r["cap_tier"], "weight": r["weight"],
                                 "rank": r["rank"], "now_tier": ranked.get(r["sid"], {}).get("cap_tier")})
                 for r in sells]
    resize_rows = [line(r["sid"], {"ticker": r["ticker"], "tier": r["cap_tier"], "weight": r["weight"],
                                   "prev_weight": r["prev_weight"], "rank": r["rank"]}) for r in resizes]

    meta = {}
    for r in book_rows:
        meta[r["sid"]] = {"ticker": r["ticker"], "tier": r["cap_tier"], "sector": r.get("sector"), "source": "in book"}
    for t, stocks in pub.items():
        for s in stocks:
            meta.setdefault(s["sid"], {"ticker": s["ticker"], "tier": t, "sector": s.get("sector"), "source": "top pick"})
    avoid = {r["sid"]: r for r in playbooks.avoid_list()["rows"] if r["sid"] in meta}
    floor = config.PORTFOLIO["hrp"]["min_adtv_inr"]
    traded = _adtv(list(meta), pick_date)
    thin = {sid: {"adtv_cr": v / 1e7, "floor_cr": floor / 1e7, "as_of": pick_date}
            for sid, v in traded.items() if v < floor}
    checks = build_checks(views.forensic_flags(list(meta)), views.results_due(list(meta), RESULTS_DAYS),
                          meta, config.SCREEN["financial_sectors"], avoid=avoid, thin=thin)
    for c in checks:
        c["href"] = f"/stocks/{c['sid']}" + ("#forensic" if c["kind"] == "forensic" else "")

    picks = {t: [line(s["sid"], {"ticker": s["ticker"], "tier": t, "rank": s["rank"], "name": s.get("name")})
                 for s in pub.get(t, [])] for t in views.display_tiers()}

    book_split = {}
    for r in book_rows:
        book_split[r["cap_tier"]] = book_split.get(r["cap_tier"], 0) + (r["weight"] or 0)
    book_split = {t: book_split[t] for t in views.display_tiers() if t in book_split}
    prev_date = dates[1] if len(dates) > 1 else None
    prev_picks = views.picks(prev_date, gated=False).to_dict("records") if prev_date else []
    movers = rank_movers(cur_rows, prev_picks) if prev_date else {}
    sentence, nothing = headline(buy_rows, sell_rows, resize_rows, checks, has_prev=prev is not None)
    return {
        "headline": sentence, "nothing": nothing, "pick_date": pick_date,
        "book_asof": book["asof"] if book else None, "prev_asof": prev["asof"] if prev else None,
        "book_n": len(book_rows), "has_book": bool(book),
        "buys": buy_rows, "sells": sell_rows, "resizes": resize_rows, "checks": checks,
        "regime": api.get_regime(), "book_split": book_split, "picks": picks, "movers": movers,
        "mover_count": sum(len(v) for v in movers.values()), "prev_pick_date": prev_date,
        "exit_rank": config.PORTFOLIO["hrp"]["rebalance"]["rank_exit"],
        "evidence": playbooks.evidence(), "unproven": views.unproven_tiers(),
        "top_n": TOP_N, "tier_sizes": sizes,
    }
