"""
Alpha Signal Cockpit - page data for the multibagger desk (plan 0026 phase 5, ADR 0075).

One function per number, each reading the one module that owns it:

  thesis rows / stage counts   multibagger_scores (signals/multibagger.py)
  the lists                    multibagger_book + multibagger_book_log (output/mb_book.py, the only writer)
  evidence card, events, govt  signals/mb_watch.py
  results, ownership, peers    output/mb_deepdive.py
  valuation field              valuation_ranges (signals/valuation.py)
  dossier narrative            mb_dossiers (output/mb_dossier.py)
  conviction verdict           cockpit.api._conviction_verdicts (a monitor, never an exit rule)

Pages
  funnel()            stage counts, gate-fail tally, grade line and the top 100 as evidence cards
  candidates()        the candidate + held table
  held()              the held names against NIFTY SMALLCAP 250
  watch()             merged event feed for every candidate and held name
  valuation_page()    football fields for every candidate and held name, sorted by price vs the field
  deep_dive(sid)      stage 4: every section for one name

The tables are empty until Amit approves the first data run, so every function returns an empty shape
(never raises on a missing table, column or row) and the template shows the empty state.
Writes go through promote() / hold() / drop(), which call output.mb_book (its caps and rules are enforced
there, not in the page) and then clear this module's caches.
"""
import json
import sqlite3
from datetime import date

import pandas as pd

import config
import db
from cockpit._shared import _persisted_cache, _ttl_cache

TTL = 300
ACTOR = "cockpit"
BENCH = "NIFTY SMALLCAP 250"

# The grade line (ADR 0073 / 0075). The numbers are the ADR's, dated by its study.
GRADE = {"grade": "C", "label": "Grade C — a shortlist for judgement (ADR 0075)",
         "evidence": ("30-name book, realistic costs, Oct 2011 to Oct 2026 study: +12.7 %/yr, t 1.90, "
                      "worst 12 months −33 % (multibagger-thesis-2026-10, 15 Oct 2026). "
                      "A place to look, not a ranking that picks the winner."),
         }

# bar methods of the football field, in display order (label, what it is)
METHODS = [("pe_band", "Own P/E band"), ("pb_band", "Own P/B band"), ("ev_ebitda_band", "Own EV/EBITDA band"),
           ("peer_pe", "Peer P/E"), ("peer_ev_ebitda", "Peer EV/EBITDA"), ("dcf", "DCF, bear to bull"),
           ("analyst", "Analyst targets"), ("range_52w", "52-week range")]
VALUE_METHODS = {m for m, _ in METHODS if m != "range_52w"}     # the 52-week range is a price range, not a value
PARTS = [("p_smallness", "Small"), ("p_cheapness", "Cheap"), ("p_price", "Price"),
         ("p_business", "Business"), ("p_tailwind", "Industry")]
SEVERITIES = [("high", "High only"), ("medium", "Medium and up"), ("low", "All")]
FLAG_TEXT = {"m": {"LIKELY_MANIPULATOR": "Earnings-quality flag (Beneish)"},
             "z": {"DISTRESS": "Distress zone (Altman Z)", "GREY_ZONE": "Grey zone (Altman Z)"}}


# ── plumbing ────────────────────────────────────────────────────────────────────────────────────

def _missing(e):
    return "no such table" in str(e) or "no such column" in str(e)


def _rows(sql, params=None):
    """db.rows, or [] when the table / column does not exist yet (the desk's tables arrive with its first run)."""
    try:
        return db.rows(sql, params)
    except (sqlite3.Error, pd.errors.DatabaseError) as e:
        if _missing(e):
            return []
        raise


def _one(sql, params=None):
    r = _rows(sql, params)
    return r[0] if r else {}


def _in(n):
    return ",".join("?" * n)


def _num(x, nd=None):
    if x is None or x != x:
        return None
    return round(float(x), nd) if nd is not None else float(x)


def _clean(obj):
    """NaN / None-safe copy (so a template never prints 'nan')."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, float) and obj != obj:
        return None
    return obj


def label(cat):
    return str(cat or "").replace("_", " ").capitalize()


def clear_caches():
    for fn in (funnel_cards, _card, _events, _verdicts, valuation_fields, book_rows, thesis_rows, funnel_counts):
        fn.cache_clear()


def snapshot():
    """Date of the latest thesis run, or None while there has been none."""
    return _one("SELECT MAX(snapshot_date) AS d FROM multibagger_scores WHERE thesis_score IS NOT NULL").get("d")


# ── stage counts, gate-fail tally ───────────────────────────────────────────────────────────────

def _gate_labels():
    t = config.MB_THESIS
    return {"adtv": f"Daily turnover under ₹{t['adtv_min_cr']:g} Cr",
            "adtv_rank": f"Among the {t['adtv_rank_min']} most liquid stocks",
            "mcap": f"Market cap over ₹{t['mcap_max_cr']:,} Cr", "sales": "No revenue",
            "survivor": "Not in today's universe", "red_flag": "Auditor resignation or CIRP in 12 months",
            "pledge": f"Promoter pledge over {t['pledge_max_pct']:g} %", "gsm": "Under GSM surveillance"}


@_ttl_cache(TTL)
def funnel_counts():
    """{as_of, stages: [{key, label, n, how}], gate_fail: [{gate, label, n}], n_failed}. n is None where the
    thesis has not run (the stages after it still count the lists)."""
    snap = snapshot()
    st = {r["status"]: r["n"] for r in _rows("SELECT status, COUNT(*) AS n FROM multibagger_book GROUP BY status")}
    t = config.MB_THESIS
    scored = _one("SELECT COUNT(*) AS n, SUM(thesis_pond = 1) AS pond, SUM(thesis_stage = 'top100') AS top "
                  "FROM multibagger_scores WHERE snapshot_date = ?", [snap]) if snap else {}
    cands, held = st.get("candidate", 0) + st.get("held", 0), st.get("held", 0)
    stages = [
        {"key": "universe", "label": "Universe", "n": scored.get("n"), "how": "every listed stock scored in the run"},
        {"key": "pond", "label": "Pond", "n": None if not snap else int(scored.get("pond") or 0),
         "how": "passes every safety gate"},
        {"key": "top", "label": f"Top {t['top_n']}", "n": None if not snap else int(scored.get("top") or 0),
         "how": "best thesis score in the pond"},
        {"key": "cands", "label": "Candidates", "n": cands, "how": f"your picks, at most {t['max_book']} with held"},
        {"key": "held", "label": "Held", "n": held, "how": f"your picks, at most {t['max_held']}"},
    ]
    tally, n_failed = {}, 0
    if snap:
        for r in _rows("SELECT thesis_gate_fail AS g FROM multibagger_scores WHERE snapshot_date = ? "
                       "AND thesis_pond = 0 AND thesis_gate_fail IS NOT NULL AND thesis_gate_fail != ''", [snap]):
            n_failed += 1
            for g in r["g"].split(","):
                tally[g] = tally.get(g, 0) + 1
    names = _gate_labels()
    gate_fail = [{"gate": g, "label": names.get(g, g), "n": n} for g, n in sorted(tally.items(), key=lambda kv: -kv[1])]
    return {"as_of": snap, "stages": stages, "gate_fail": gate_fail, "n_failed": n_failed,
            "n_book": cands, "n_held": held, "max_book": t["max_book"], "max_held": t["max_held"]}


# ── the book ────────────────────────────────────────────────────────────────────────────────────

@_ttl_cache(TTL)
def book_rows(status=None):
    """multibagger_book rows (candidate + held when status is None) with name, ticker, tier, newest first by since."""
    where = "b.status = ?" if status else "b.status IN ('candidate', 'held')"
    return _rows("SELECT b.sid, b.status, b.since, b.thesis_line, b.entry_date, b.entry_price, b.reason, b.updated_at, "
                 "s.name, s.ticker, s.cap_tier, s.industry, s.market_cap_cr FROM multibagger_book b "
                 f"LEFT JOIN stocks s ON s.sid = b.sid WHERE {where} ORDER BY b.status DESC, b.since DESC, b.sid",
                 [status] if status else None)


def book_status(sids):
    """{sid: status} for the given sids (not cached: a promote shows at once on the next card render)."""
    if not sids:
        return {}
    return {r["sid"]: r["status"] for r in _rows(
        f"SELECT sid, status FROM multibagger_book WHERE sid IN ({_in(len(sids))})", list(sids))}


def book_log(sid=None, limit=100):
    return _rows("SELECT ts, sid, action, from_status, to_status, reason, actor FROM multibagger_book_log "
                 + ("WHERE sid = ? " if sid else "") + "ORDER BY id DESC LIMIT ?", [sid, limit] if sid else [limit])


@_ttl_cache(TTL)
def thesis_rows(sids, snap=None):
    """{sid: thesis row} at the latest run: score and the five parts (percentiles, 0 to 1), rank, stage, adtv_cr."""
    snap = snap or snapshot()
    if not snap or not sids:
        return {}
    cols = "sid, thesis_pond, thesis_score, thesis_rank, thesis_stage, adtv_cr, mcap_cr, " + ", ".join(p for p, _ in PARTS)
    return {r["sid"]: {**r, "snapshot_date": snap} for r in _rows(
        f"SELECT {cols} FROM multibagger_scores WHERE snapshot_date = ? AND sid IN ({_in(len(sids))})",
        [snap, *sids])}


def parts_of(row):
    """[(label, share 0-100 or None)] for the five parts of a thesis row."""
    return [{"label": lab, "pct": None if not row or row.get(col) is None else round(row[col] * 100)}
            for col, lab in PARTS]


# ── evidence card, events ───────────────────────────────────────────────────────────────────────

def _watch():
    from signals import mb_watch
    return mb_watch


@_ttl_cache(TTL)
def _card(sid):
    return _clean(_watch().card(sid))


@_ttl_cache(TTL)
def _events(sid, days=365):
    """The stock's dated events for the last `days` days, newest first: [{date, source, category, severity,
    headline, url, sev_rank}]. Headlines are third-party text, shown escaped."""
    t = _watch().timeline(sid, since=pd.Timestamp.now().normalize() - pd.Timedelta(days=days))
    out = []
    for r in t.itertuples():
        out.append({"date": str(r.date)[:10], "source": r.source, "category": r.category, "severity": r.severity,
                    "sev_rank": config.WATCH_SEVERITY.get(r.severity, 0), "headline": r.headline,
                    "url": r.url if isinstance(r.url, str) and r.url else None})
    return out


def _flags(card):
    f = (card or {}).get("forensic") or {}
    out = []
    if f.get("m_score_flag") in FLAG_TEXT["m"]:
        out.append({"text": FLAG_TEXT["m"][f["m_score_flag"]], "tone": "amber", "as_of": f.get("m_score_date")})
    if f.get("z_score_flag") in FLAG_TEXT["z"]:
        out.append({"text": FLAG_TEXT["z"][f["z_score_flag"]], "tone": "red" if f["z_score_flag"] == "DISTRESS" else "amber",
                    "as_of": f.get("z_score_date")})
    p = ((card or {}).get("pledge") or {}).get("pledge_pct")
    if p and p >= 1:
        out.append({"text": f"Promoter pledge {p:.1f} %", "tone": "amber", "as_of": card["pledge"].get("end_date")})
    return out


def _last_event(sid):
    ev = [e for e in _events(sid) if e["source"] not in ("news_articles", "regulatory_events")]
    return ev[0]["date"] if ev else None


# ── Funnel: the top 100 as evidence cards ───────────────────────────────────────────────────────

@_persisted_cache(3600, name="mb_funnel_cards")
def funnel_cards(snap):
    """The top-100 evidence cards of one thesis run, thesis_rank order. Keyed by the run date; cached on disk
    because each card reads a dozen tables (mb_watch.card)."""
    if not snap:
        return []
    rows = _rows("SELECT m.sid, m.thesis_rank, m.thesis_score, m.mcap_cr, m.adtv_cr, m.cap_tier, s.name, s.ticker, s.industry, "
                 + ", ".join("m." + p for p, _ in PARTS) + " FROM multibagger_scores m JOIN stocks s ON s.sid = m.sid "
                 "WHERE m.snapshot_date = ? AND m.thesis_stage = 'top100' ORDER BY m.thesis_rank, m.sid", [snap])
    out = []
    for r in rows:
        c = _card(r["sid"])
        res = c.get("results") or {}
        inv = [i for i in c.get("known_investors") or [] if i.get("investor")]
        out.append({**{k: r[k] for k in ("sid", "thesis_rank", "thesis_score", "mcap_cr", "adtv_cr", "cap_tier", "name",
                                         "ticker", "industry")},
                    "parts": parts_of(r), "snapshot_date": snap, "investors": inv,
                    "results": res or None, "events": {k: v for k, v in (c.get("events_90d") or {}).items() if v},
                    "top_events": c.get("top_events_90d") or [], "valuation": c.get("valuation_position") or {},
                    "flags": _flags(c), "card_as_of": c.get("as_of")})
    return out


def funnel():
    """Funnel tab: counts, gate tally, grade, and the cards with each name's current book status."""
    counts = funnel_counts()
    cards = funnel_cards(counts["as_of"]) if counts["as_of"] else []
    status = book_status([c["sid"] for c in cards])
    return {**counts, "grade": GRADE, "cards": [{**c, "status": status.get(c["sid"])} for c in cards]}


# ── Valuation fields ────────────────────────────────────────────────────────────────────────────

def _pos(x, lo, hi):
    return max(0.0, min(100.0, (x - lo) / (hi - lo) * 100)) if hi > lo else 50.0


def _field(sid, rows):
    """One football field from a stock's newest valuation_ranges rows. Positions are percentages of an axis that runs
    from just under the lowest low to just over the highest high, capped at three times the price (a bull-case DCF
    must not flatten the other bars); a bar running off the axis is marked `clipped`."""
    by = {r["method"]: r for r in rows}
    any_row = rows[0]
    price, as_of = _num(any_row.get("price")), any_row["as_of"]
    meths = []
    for key, lab in METHODS:
        r = by.get(key)
        ok = r is not None and None not in (r["low"], r["mid"], r["high"])
        meths.append({"key": key, "label": lab, "basis": (r or {}).get("basis") or "not computed", "ok": ok,
                      "low": r["low"] if ok else None, "mid": r["mid"] if ok else None, "high": r["high"] if ok else None})
    shown = [m for m in meths if m["ok"]]
    rev = by.get("reverse_dcf") or {}
    f = {"sid": sid, "as_of": as_of, "price": price, "methods": meths, "n_methods": len(shown),
         "implied_growth_pct": None if rev.get("implied_growth_10y") is None else round(rev["implied_growth_10y"] * 100, 1),
         "reverse_basis": rev.get("basis"), "discount_pct": None, "axis": None}
    mids = sorted(m["mid"] for m in shown if m["key"] in VALUE_METHODS)
    if price and mids:
        med = mids[len(mids) // 2] if len(mids) % 2 else (mids[len(mids) // 2 - 1] + mids[len(mids) // 2]) / 2
        f["median_mid"] = med
        f["discount_pct"] = round((price / med - 1) * 100, 1)
    if shown and price:
        lo = min([m["low"] for m in shown] + [price]) * 0.92
        hi = min(max([m["high"] for m in shown] + [price]) * 1.05, price * 3)
        hi = max(hi, price * 1.15)
        for m in meths:
            if m["ok"]:
                m["left"] = round(_pos(m["low"], lo, hi), 1)
                m["width"] = round(max(_pos(m["high"], lo, hi) - m["left"], 0.8), 1)
                m["mid_at"] = round(_pos(m["mid"], lo, hi), 1)
                m["clipped"] = m["high"] > hi
        f["axis"] = {"lo": lo, "hi": hi, "price_at": round(_pos(price, lo, hi), 1)}
    return f


@_ttl_cache(TTL)
def valuation_fields(sids):
    """{sid: field} from the newest valuation_ranges rows per stock; a stock with none is absent."""
    if not sids:
        return {}
    ph = _in(len(sids))
    rows = _rows("SELECT v.sid, v.as_of, v.method, v.low, v.mid, v.high, v.basis, v.price, v.implied_growth_10y "
                 f"FROM valuation_ranges v JOIN (SELECT sid, MAX(as_of) AS a FROM valuation_ranges WHERE sid IN ({ph}) "
                 "GROUP BY sid) m ON m.sid = v.sid AND m.a = v.as_of", list(sids))
    by = {}
    for r in rows:
        by.setdefault(r["sid"], []).append(r)
    return {sid: _field(sid, rs) for sid, rs in by.items()}


def valuation_page():
    """/multibagger/valuation: a field per candidate and held name, cheapest against its own field first."""
    book = book_rows()
    sids = tuple(b["sid"] for b in book)
    fields = valuation_fields(sids)
    items = []
    for b in book:
        f = fields.get(b["sid"])
        items.append({**b, "field": f})
    have = sorted((i for i in items if i["field"] and i["field"]["axis"]),
                  key=lambda i: (i["field"]["discount_pct"] is None, i["field"]["discount_pct"] or 0))
    without = [i for i in items if i not in have]
    return {"rows": have, "without": without, "n_book": len(book), "max_book": config.MB_THESIS["max_book"],
            "as_of": max((i["field"]["as_of"] for i in have), default=None)}


# ── Candidates / Held / Watch ───────────────────────────────────────────────────────────────────

def candidates():
    book = book_rows()
    sids = tuple(b["sid"] for b in book)
    th, vf = thesis_rows(sids), valuation_fields(sids)
    rows = []
    for b in book:
        t = th.get(b["sid"])
        c = _card(b["sid"]) if b["name"] else {}
        rows.append({**b, "thesis": t, "parts": parts_of(t), "score": None if not t or t["thesis_score"] is None
                     else round(t["thesis_score"] * 100), "field": vf.get(b["sid"]), "flags": _flags(c),
                     "last_event": _last_event(b["sid"]) if b["name"] else None})
    return {"rows": rows, "n_book": len(book), "max_book": config.MB_THESIS["max_book"],
            "thesis_as_of": snapshot(), "n_held": sum(r["status"] == "held" for r in rows),
            "max_held": config.MB_THESIS["max_held"]}


@_ttl_cache(900)
def _verdicts(sids):
    from cockpit import api
    if not sids:
        return {}
    return api._conviction_verdicts(pd.DataFrame({"sid": list(sids)})) or {}


def _price_on(sid, d=None):
    """(close, date) on or before d (latest when None)."""
    r = _one("SELECT close, date FROM stock_prices WHERE sid = ? AND close > 0 "
             + ("AND date <= ? " if d else "") + "ORDER BY date DESC LIMIT 1", [sid, d] if d else [sid])
    return (r.get("close"), r.get("date")) if r else (None, None)


def _bench(d=None):
    r = _one("SELECT close, trade_date FROM nse_index_history WHERE index_symbol = ? AND close > 0 "
             + ("AND trade_date <= ? " if d else "") + "ORDER BY trade_date DESC LIMIT 1", [BENCH, d] if d else [BENCH])
    return (r.get("close"), r.get("trade_date")) if r else (None, None)


def _split_factor(sid, since):
    """Product of split / bonus factors with ex-date after `since` (corporate_adjustments: factor < 1 multiplies
    pre-ex prices), so entry × factor is the entry price on today's share basis."""
    if not since:
        return 1.0
    rows = _rows("SELECT factor FROM corporate_adjustments WHERE sid = ? AND ex_date > ? "
                 "AND (inds LIKE '%SPLIT%' OR inds LIKE '%BONUS%')", [sid, since])
    f = 1.0
    for r in rows:
        if r["factor"]:
            f *= r["factor"]
    return f


def _ret(a, b):
    return None if not a or not b else round((b / a - 1) * 100, 1)


def held():
    """The held names: return since entry against NIFTY SMALLCAP 250 over the same dates, the conviction verdict
    (monitor only), days since the last logged decision and events since entry (medium and up)."""
    book = [b for b in book_rows() if b["status"] == "held"]
    verdicts = _verdicts(tuple(b["sid"] for b in book))
    log_ts = {r["sid"]: r["ts"] for r in _rows(
        "SELECT sid, MAX(ts) AS ts FROM multibagger_book_log GROUP BY sid")} if book else {}
    b_now, b_now_d = _bench()
    rows, today = [], date.today()
    for b in book:
        px, px_d = _price_on(b["sid"])
        b_entry, _ = _bench(b["entry_date"]) if b["entry_date"] else (None, None)
        entry_adj = b["entry_price"] * _split_factor(b["sid"], b["entry_date"]) if b["entry_price"] else None
        own, idx = _ret(entry_adj, px), _ret(b_entry, b_now)
        ev = [e for e in _events(b["sid"]) if b["entry_date"] and e["date"] >= b["entry_date"] and e["sev_rank"] >= 1
              and e["source"] not in ("news_articles", "regulatory_events")]
        v = verdicts.get(b["sid"])
        ts = log_ts.get(b["sid"])
        rows.append({**b, "price": px, "price_date": px_d, "return_pct": own, "bench_pct": idx,
                     "vs_bench_pts": None if own is None or idx is None else round(own - idx, 1),
                     "verdict": v and v["verdict"], "drawdown_pct": v and round(v["drawdown"] * 100, 1),
                     "months_underwater": v and v["months_underwater"],
                     "days_since_review": None if not ts else (today - date.fromisoformat(ts[:10])).days,
                     "events_since_entry": len(ev) if b["entry_date"] else None})
    return {"rows": rows, "n_held": len(rows), "max_held": config.MB_THESIS["max_held"], "bench": BENCH,
            "n_book": len(book_rows()), "max_book": config.MB_THESIS["max_book"],
            "bench_as_of": b_now_d}


def watch(days=90):
    """The merged event feed of every candidate and held name for the last `days` days, newest first. All
    severities are included; the page filters (default medium and up)."""
    book = book_rows()
    since = (pd.Timestamp.now().normalize() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    for b in book:
        for e in _events(b["sid"]):
            if e["date"] >= since:
                rows.append({**e, "sid": b["sid"], "name": b["name"] or b["sid"], "status": b["status"],
                             "category_label": label(e["category"])})
    rows.sort(key=lambda r: (r["date"], r["sev_rank"]), reverse=True)
    cats = sorted({r["category"] for r in rows})
    return {"rows": rows[:600], "n_rows": len(rows), "n_names": len(book), "days": days,
            "categories": [(c, label(c)) for c in cats], "severities": SEVERITIES,
            "as_of": date.today().isoformat()}


# ── Deep dive ───────────────────────────────────────────────────────────────────────────────────

def dossier(sid):
    r = _one("SELECT as_of_date, thesis_line, thesis, bull, bear, catalysts, risks, what_would_break_it, created_at "
             "FROM mb_dossiers WHERE sid = ? ORDER BY as_of_date DESC LIMIT 1", [sid])
    if not r:
        return None
    for k in ("bull", "bear", "catalysts", "risks", "what_would_break_it"):
        try:
            r[k] = [str(x) for x in json.loads(r[k] or "[]")]
        except ValueError:
            r[k] = []
    return r


def _bars(rows, key):
    """Bar heights (percent of the tallest) for a small chart; a negative value is flagged."""
    vals = [r.get(key) for r in rows]
    top = max([abs(v) for v in vals if v is not None] or [0])
    return [{"end_date": r["end_date"], "value": v,
             "h": 0 if v is None or not top else max(round(abs(v) / top * 100), 2), "neg": v is not None and v < 0}
            for r, v in zip(rows, vals)]


def ownership(sid, n=12):
    from output import mb_deepdive
    rows = mb_deepdive.ownership_timeline(sid)[-n:]
    for r in rows:
        for k in ("entered", "exited"):
            r[k] = [{**h, "investor": _watch().investor_of(h["name"])} for h in r[k]]
    return list(reversed(rows))        # newest first


def _section(fn, *a):
    """(value, error): a section that fails shows its error on the page instead of 500-ing the deep dive."""
    try:
        return _clean(fn(*a)), None
    except Exception as e:           # noqa: BLE001 - shown on the page, never swallowed
        return None, f"{type(e).__name__}: {e}"


def deep_dive(sid):
    """Stage 4, every section for one name (None when the sid is not in the universe)."""
    st = _one("SELECT sid, ticker, name, sector, industry, cap_tier, market_cap_cr FROM stocks WHERE sid = ?", [sid])
    if not st:
        return None
    from output import mb_deepdive
    d = {"stock": st, "sections_failed": {}}
    for key, fn, args in (
            ("trend", mb_deepdive.results_trend, (sid, 12)), ("own", ownership, (sid,)),
            ("peers", mb_deepdive.peers, (sid, 8)), ("govt", _watch().govt_links, (sid,)),
            ("events", _events, (sid,)), ("dossier", dossier, (sid,))):
        d[key], err = _section(fn, *args)
        if err:
            d["sections_failed"][key] = err
    d["field"] = valuation_fields((sid,)).get(sid)
    d["thesis"] = thesis_rows((sid,)).get(sid)
    d["parts"] = parts_of(d["thesis"])
    d["card"], err = _section(_card, sid)
    d["flags"] = _flags(d["card"])
    b = _one("SELECT status, since, thesis_line, entry_date, entry_price, reason FROM multibagger_book WHERE sid = ?", [sid])
    d["book"], d["log"] = (b or None), book_log(sid)
    d["trend"] = d["trend"] or []
    d["charts"] = {"revenue": _bars(d["trend"], "revenue"), "margin": _bars(d["trend"], "ebitda_margin_pct")}
    d["n_book"], d["max_book"] = len(book_rows()), config.MB_THESIS["max_book"]
    d["n_held"], d["max_held"] = sum(1 for r in book_rows() if r["status"] == "held"), config.MB_THESIS["max_held"]
    d["events_shown"] = [e for e in (d["events"] or []) if e["sev_rank"] >= 1][:60]
    return d


# ── Writes (output.mb_book owns the rules and the caps) ─────────────────────────────────────────

def _write(fn, *a, **kw):
    from output import mb_book
    try:
        getattr(mb_book, fn)(*a, actor=ACTOR, **kw)
    except (sqlite3.OperationalError, sqlite3.IntegrityError) as e:
        raise ValueError(f"the book could not be written: {e}") from e
    finally:
        clear_caches()


def promote(sid, thesis_line, reason):
    _write("add_candidate", sid, thesis_line, reason)


def hold(sid, reason, entry_price=None):
    if entry_price not in (None, ""):
        try:
            entry_price = float(entry_price)
        except (TypeError, ValueError):
            raise ValueError("entry price must be a number") from None
        if not entry_price > 0:
            raise ValueError("entry price must be above zero")
    else:
        entry_price = None
    _write("hold", sid, reason, entry_price=entry_price)


def drop(sid, reason):
    _write("drop", sid, reason)
