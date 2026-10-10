"""
Alpha Signal Cockpit — data layer for Stocks (/stocks screener and the stock page chips).

  universe()        every ranked stock (latest daily_picks) plus the unranked tiers, one row each
  screen(params)    filter + sort + page that universe, state read from the URL query
  stock_chips(sid)  the small facts the stock page shows as chips: red flags, avoid list,
                    say-vs-do verdict, Lynch category, screen memberships

Reads named view functions only (views.py, cockpit/api.py, cockpit/playbooks.py). Ranking facts
come from daily_picks via views.picks (ungated: the screener lists every ranked stock, like the
old Explorer), "in the book" from the HRP-sized book, the data number from views.pick_data (the one
wording), the target from the MEDIAN analyst target against the latest close.
"""

from urllib.parse import urlencode

import pandas as pd

import views
from db import read_sql
from cockpit import api, playbooks
from cockpit._shared import _ttl_cache
from validators.plausibility import PT_CLOSE_RATIO

PAGE_SIZE = 100

# Pill text for the screens: the Investor Playbooks tab names (playbooks.SLEEVE_NAMES), broad cloning under the same name.
PLAY_SHORT = {k: playbooks.SLEEVE_NAMES[k] for k in ("quality", "deep_value", "breakouts", "insiders", "cloning")} | {
    "cloning_broad": playbooks.SLEEVE_NAMES["cloning"]}
# screens a stock shows as a pill (the Avoid screen is a flag, not a screen to buy from)
PLAY_ORDER = ("quality", "deep_value", "breakouts", "insiders", "cloning", "cloning_broad")

SORTS = {                      # key -> (label, default direction)
    "rank": ("Rank in tier", "asc"), "score": ("Score", "desc"), "ticker": ("Stock", "asc"),
    "change": ("Rank change", "desc"), "data": ("Data", "desc"), "pt": ("Median target", "desc"),
}


def _median_upside(pt_median, close):
    """% upside of the median analyst target over the latest close; None when there is no
    target or it is implausible against the close (validators.plausibility.PT_CLOSE_RATIO)."""
    try:
        pt, px = float(pt_median), float(close)
    except (TypeError, ValueError):
        return None
    lo, hi = PT_CLOSE_RATIO
    if pt != pt or px != px or px <= 0 or pt <= 0 or pt > hi * px or pt < lo * px:
        return None
    return round((pt / px - 1) * 100, 1)


def _rank_changes(today, yesterday):
    """{sid: places moved up since the previous ranking (negative = down)} for stocks ranked in
    the same tier on both dates; a stock new to a tier gets 'new'."""
    if yesterday is None or yesterday.empty:
        return {}
    prev = dict(zip(yesterday["sid"], zip(yesterday["cap_tier"], yesterday["rank"])))
    out = {}
    for r in today.itertuples():
        p = prev.get(r.sid)
        out[r.sid] = "new" if p is None or p[0] != r.cap_tier else int(p[1] - r.rank)
    return out


@_ttl_cache(120)
def universe():
    """{as_of, prev_date, tiers, sectors, rows}: one dict per stock. A ranked stock carries
    score (0-100), rank, tier size, rank change, data share, target upside; an unranked one
    (MICRO) has `ranked` False and only its identity."""
    dates = views.pick_dates(2)
    as_of = dates[0] if dates else None
    today = views.picks(as_of, gated=False) if as_of else pd.DataFrame()
    yesterday = views.picks(dates[1], gated=False) if len(dates) > 1 else None
    moves = _rank_changes(today, yesterday) if not today.empty else {}
    stocks = read_sql("SELECT sid, ticker, name, sector, cap_tier FROM stocks")
    ranked = {r.sid: r for r in today.itertuples()}
    tier_size = views.tier_sizes(as_of) if as_of else {}

    close = {sid: c for sid, (c, _) in views.latest_close().items()}      # all sids: one grouped read, not 2,400 windows
    targets = {r["sid"]: r["price_target_median"] for r in views.native_rows(
        "SELECT sid, price_target_median FROM analyst_consensus WHERE price_target_median IS NOT NULL")}
    analysts = {r["sid"]: r["total_analysts"] for r in views.native_rows(
        "SELECT sid, total_analysts FROM analyst_consensus WHERE price_target_median IS NOT NULL")}
    forensic = views.latest_per_sid("forensic_scores", ["m_score_flag", "z_score_flag"])
    forensic = {r.sid: (r.m_score_flag, r.z_score_flag) for r in forensic.itertuples()}
    avoid = playbooks.avoid_list()["flag_counts"]
    book = {r["sid"] for r in (api.get_sized_book() or {}).get("rows", [])}
    plays, veto = {}, set()
    for r in views.native_rows(
            "SELECT sid, sleeve FROM playbook_members WHERE in_sleeve = 1 AND snapshot_date = "
            "(SELECT MAX(snapshot_date) FROM playbook_members)"):
        if r["sleeve"] == "flagged":
            veto.add(r["sid"])
        elif r["sleeve"] in PLAY_SHORT:
            plays.setdefault(r["sid"], set()).add(PLAY_SHORT[r["sleeve"]])

    rows = []
    for s in stocks.itertuples():
        p = ranked.get(s.sid)
        tier = p.cap_tier if p is not None else s.cap_tier
        manip, distress = forensic.get(s.sid, (None, None))
        accounts = manip == "LIKELY_MANIPULATOR"
        distressed = distress == "DISTRESS" and s.sector != "Financials"      # Altman Z does not fit lenders
        data = views.pick_data({"eligible_coverage": p.eligible_coverage}) if p is not None else None
        rows.append({
            "sid": s.sid, "ticker": s.ticker, "name": s.name, "tier": tier, "sector": s.sector or "",
            "ranked": p is not None,
            "score": None if p is None else int(round(p.final_score * 100)),
            "rank": None if p is None else int(p.rank), "tier_size": int(tier_size.get(tier, 0)) if p is not None else None,
            "change": moves.get(s.sid) if p is not None else None,
            "data": data["score"] if data else None, "data_colour": data["colour"] if data else None,
            "book": s.sid in book,
            "avoid": avoid.get(s.sid, 0) >= playbooks.AVOID_MIN_FLAGS,
            "forensic": [x for x, on in (("Accounts", accounts), ("Distress", distressed)) if on],
            "veto": s.sid in veto,
            "plays": sorted(plays.get(s.sid, ())),
            "pt_up": _median_upside(targets.get(s.sid), close.get(s.sid)),
            "analysts": int(analysts[s.sid]) if analysts.get(s.sid) else None,
        })
    for r in rows:
        r["flagged"] = bool(r["avoid"] or r["forensic"] or r["veto"])
    return {"as_of": as_of, "prev_date": dates[1] if len(dates) > 1 else None, "rows": rows,
            "tiers": views.display_tiers() + views.unpickable_tiers(), "unpickable": views.unpickable_tiers(),
            "sectors": sorted({r["sector"] for r in rows if r["sector"]})}


def _truthy(v):
    return str(v or "").lower() in ("1", "true", "yes", "on")


def screen(params):
    """The screener for the URL query `params` (a mapping of strings): tier, unranked, sector, book,
    flagged, q, sort, dir, page. Returns the page of rows plus everything the template needs to
    draw the controls and the links (state lives in the URL, nothing in the browser)."""
    u = universe()
    tier = (params.get("tier") or "").upper()
    sector, q = params.get("sector") or "", (params.get("q") or "").strip()
    book, flagged = _truthy(params.get("book")), _truthy(params.get("flagged"))
    unranked = _truthy(params.get("unranked")) or _truthy(params.get("micro"))      # "micro" = the old name of the toggle
    sort = params.get("sort") if params.get("sort") in SORTS else "rank"
    direction = params.get("dir") if params.get("dir") in ("asc", "desc") else SORTS[sort][1]
    try:
        page = max(1, int(params.get("page") or 1))
    except ValueError:
        page = 1

    unpick = set(u["unpickable"])
    rows = u["rows"]
    if tier in u["tiers"]:
        rows = [r for r in rows if r["tier"] == tier]
    if not unranked and tier not in unpick:       # the default view is exactly the ranked stocks
        rows = [r for r in rows if r["ranked"] or (book and r["book"])]      # a held name stays visible even when unranked today
    if sector:
        rows = [r for r in rows if r["sector"] == sector]
    if book:
        rows = [r for r in rows if r["book"]]
    if flagged:
        rows = [r for r in rows if r["flagged"]]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["ticker"].lower() or ql in (r["name"] or "").lower()]

    tier_order = {t: i for i, t in enumerate(u["tiers"])}
    rev = direction == "desc"
    if sort == "rank":                    # tier by tier, best rank first (ranks never mix tiers)
        rows = sorted(rows, key=lambda r: (not r["ranked"], tier_order.get(r["tier"], 99),
                                           (r["rank"] or 0) * (-1 if rev else 1), r["ticker"]))
    elif sort == "ticker":
        rows = sorted(rows, key=lambda r: r["ticker"], reverse=rev)
    else:
        key = {"score": "score", "data": "data", "pt": "pt_up",
               "change": "change"}[sort]

        def val(r):
            v = r[key]
            return v if isinstance(v, (int, float)) else None     # 'new' has no number to sort on
        have = [r for r in rows if val(r) is not None]
        rest = [r for r in rows if val(r) is None]
        rows = sorted(have, key=lambda r: (val(r), r["ticker"]), reverse=rev) + rest

    total = len(rows)
    pages = max(1, -(-total // PAGE_SIZE))
    page = min(page, pages)
    chosen = {"tier": tier if tier in u["tiers"] else "", "unranked": unranked, "sector": sector, "book": book,
              "flagged": flagged, "q": q, "sort": sort, "dir": direction}
    def link(**change):
        """The /stocks URL for the current state with `change` applied (page resets unless given)."""
        state = {"tier": chosen["tier"], "unranked": "1" if unranked else "", "sector": sector, "book": "1" if book else "",
                 "flagged": "1" if flagged else "", "q": q, "sort": sort if sort != "rank" else "",
                 "dir": direction if (sort != "rank" or direction != SORTS["rank"][1]) else ""}
        state.update({k: ("" if v is None else str(v)) for k, v in change.items()})
        if state.get("sort") == "rank" and state.get("dir") == SORTS["rank"][1]:
            state["sort"] = state["dir"] = ""
        qs = urlencode({k: v for k, v in state.items() if v and not (k == "page" and v == "1")})
        return "/stocks" + (f"?{qs}" if qs else "")

    return {"link": link, "as_of": u["as_of"], "prev_date": u["prev_date"], "rows": rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE],
            "total": total, "page": page, "pages": pages, "page_size": PAGE_SIZE, "chosen": chosen,
            "tiers": u["tiers"], "unpickable": sorted(unpick), "sectors": u["sectors"],
            "n_ranked": sum(r["ranked"] for r in u["rows"]), "n_unranked": sum(not r["ranked"] for r in u["rows"]),
            "n_micro": sum(not r["ranked"] and r["tier"] in unpick for r in u["rows"]),
            "n_gate": sum(not r["ranked"] and r["tier"] not in unpick for r in u["rows"]),
            "unproven": views.unproven_tiers(),
            "n_book": sum(r["book"] for r in u["rows"]),
            "n_book_unranked": sum(r["book"] and not r["ranked"] for r in u["rows"]),
            "n_flagged": sum(r["flagged"] and r["ranked"] for r in u["rows"]),
            "sorts": SORTS,
            "default_view": not (chosen["tier"] or unranked or sector or book or flagged or q)}


def rank_move(sid):
    """Places `sid` moved up (negative = down) between the last two rankings, in its tier; None when it
    was not ranked in the same tier on both dates."""
    dates = views.pick_dates(2)
    if len(dates) < 2:
        return None
    rows = {r["pick_date"]: r for r in views.native_rows(
        "SELECT pick_date, rank, cap_tier FROM daily_picks WHERE sid = ? AND pick_date IN (?, ?)", [sid, *dates])}
    new, old = rows.get(dates[0]), rows.get(dates[1])
    if not new or not old or new["cap_tier"] != old["cap_tier"] or new["rank"] is None or old["rank"] is None:
        return None
    return int(old["rank"] - new["rank"])


# ═══════════════════════════ stock page chips ═══════════════════════════

SAY_DO_LABELS = playbooks.VERDICT_LABELS      # keeps_word / mixed / overpromises / no_guidance, in words
SAY_DO_TONE = {"keeps_word": "green", "mixed": "amber", "overpromises": "red", "no_guidance": "muted"}


def say_do_for(sid):
    """The stored say-vs-do verdict for one stock (output/say_do.json, written by the LLM queue), or None.
    {verdict, label, tone, summary, promises:[{said, outcome, label, evidence}], latest_call, earlier_call, generated_at}."""
    from output import say_do as sd
    for d in sd.load():
        if d.get("sid") == sid:
            return {"verdict": d["verdict"], "label": SAY_DO_LABELS.get(d["verdict"], d["verdict"]),
                    "tone": SAY_DO_TONE.get(d["verdict"], "muted"), "summary": d.get("summary"),
                    "promises": [{**p, "label": playbooks.OUTCOME_LABELS.get(p["outcome"], p["outcome"])}
                                 for p in d.get("promises", [])],
                    "latest_call": d.get("latest_call"), "earlier_call": d.get("earlier_call"),
                    "generated_at": (d.get("generated_at") or "")[:10]}
    return None


def stock_chips(sid):
    """What the stock page's Overview shows as chips, each {label, tone, tip}: the red flags, the avoid
    list, the say-vs-do verdict, the Lynch category and the screens it passes. Chips never repeat
    a number that has its own tab; they say which list the stock is on and why."""
    chips = {"flags": [], "plays": [], "category": None, "say_do": say_do_for(sid)}
    avoid = next((r for r in playbooks.avoid_list()["rows"] if r["sid"] == sid), None)
    if avoid:
        chips["flags"].append({"label": f"Avoid list · {avoid['n_flags']} red flags", "tone": "red",
                               "tip": "; ".join(f"{f['label']}: {f['detail']}" for f in avoid["flags"])})
    members = {r["sleeve"] for r in views.native_rows(
        "SELECT sleeve FROM playbook_members WHERE sid = ? AND in_sleeve = 1 AND snapshot_date = "
        "(SELECT MAX(snapshot_date) FROM playbook_members)", [sid])}
    if "flagged" in members:
        chips["flags"].append({"label": "Avoid screen", "tone": "amber",
                               "tip": "On the Avoid screen: a key resignation in 180 days, a distress-zone balance sheet or heavy promoter pledging"})
    import sleeves
    for key in PLAY_ORDER:
        if key in members:
            chips["plays"].append({"label": PLAY_SHORT[key], "tone": "blue",
                                   "tip": f"{PLAY_SHORT[key]}: {sleeves.SLEEVES[key]['rule']}"})
    cat = playbooks.categories()
    key = (cat.get("by_sid") or {}).get(sid)
    if key:
        c = next(c for c in cat["categories"] if c["key"] == key)
        chips["category"] = {"label": c["label"], "tone": "muted", "tip": c["rule"]}
    return chips

