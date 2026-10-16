"""
Alpha Signal Cockpit - page data for the multibagger desk (plan 0026 phase 5, ADR 0075).

One function per number, each reading the one module that owns it:

  thesis rows / stage counts   multibagger_scores (signals/multibagger.py)
  the lists                    multibagger_book + multibagger_book_log (output/mb_book.py, the only writer)
  evidence card, events, govt  signals/mb_watch.py
  results, ownership, peers    output/mb_deepdive.py
  valuation field              valuation_ranges (signals/valuation.py)
  dossier narrative            mb_dossiers (output/mb_dossier.py)
  deep research                mb_research (output/mb_research.py, brief docs/research/0011)
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
from output import mb_capacity
from cockpit._shared import _persisted_cache, _ttl_cache

TTL = 300
ACTOR = "cockpit"
BENCH = "NIFTY SMALLCAP 250"

# The grade line (ADR 0073 / 0075). The numbers are the ADR's, dated by its study.
GRADE = {"grade": "C", "label": "Grade C — a shortlist for judgement (ADR 0075, 0076)",
         "evidence": ("Beats an equal-weight basket of the same small, cheap stocks by about 9 %/yr in a 2016–26 backtest "
                      "that includes delisted stocks (+8.7 %/yr survivors, t 2.25; +9.6 %/yr full market, t 1.89), and the "
                      "SMALLCAP 250 by +12.7 %/yr (t 1.90, worst 12 months −33 %). It does not clear a multiple-testing bar "
                      "(deflated Sharpe 0.76 over 67 tries) and does not avoid blow-ups (full-market halving odds 0.72× the "
                      "basket). The return edge comes from the price parts (size, momentum, 52-week position): on the same "
                      "survivors the fundamental parts add about 0 %/yr. Forward risk: a momentum crash in a junk rally (Apr 2020 → "
                      "Apr 2021 it fell 60 points behind the basket while the basket rose 146 %). Independent critique and our answer: research 0008, "
                      "16 Oct 2026. A place to look, measured live against the basket, not a ranking that picks the winner."),
         }

# bar methods of the football field, in display order (label, what it is); the reverse DCF is not a bar, it is the line above
METHODS = [("ev_ebitda_band", "Own EV/EBITDA band"), ("ev_sales", "Own EV/Sales band"), ("pe_band", "Own P/E band"),
           ("pb_band", "Own P/B band"), ("peer_ev_ebitda", "Peer EV/EBITDA"), ("peer_ev_sales", "Peer EV/Sales"),
           ("peer_pe", "Peer P/E"), ("dcf", "DCF, bear to bull"), ("analyst", "Analyst targets"),
           ("range_52w", "52-week range")]
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


@_ttl_cache(TTL)
def _surveillance_date():
    return _one("SELECT MAX(flag_date) AS d FROM surveillance_flags")


def exit_flags(sid, card=None):
    """Name exits by process, not price (ADR 0076, config.MB_EXITS): [{text, tone, as_of, kind}] where kind is
    'exit' (leave at the next liquid session) or 'review' (decide within a week)."""
    x, out, today = config.MB_EXITS, [], date.today()
    ev = _events(sid)                                            # the cached 365-day timeline the card already built
    since = (today - pd.Timedelta(days=x["auditor_days"])).isoformat()
    aud = [e for e in ev if e["category"] == "auditor_resignation" and e["date"] >= since]
    if aud:
        out.append({"text": "Exit: auditor resigned", "tone": "red", "as_of": aud[0]["date"], "kind": "exit"})
    last = _surveillance_date()
    if last and last.get("d"):
        g = _rows("SELECT flag_type FROM surveillance_flags WHERE sid = ? AND flag_date = ? AND flag_type IN ("
                  + ",".join("?" * len(x["gsm_types"])) + ")", [sid, last["d"], *x["gsm_types"]])
        if g:
            out.append({"text": f"Exit: on the {g[0]['flag_type']} list", "tone": "red", "as_of": last["d"], "kind": "exit"})
    q = _one("SELECT MAX(end_date) AS d FROM quarterly_income WHERE sid = ?", [sid])
    if q and q.get("d"):
        due = (pd.Timestamp(q["d"]) + pd.offsets.QuarterEnd(1) + pd.Timedelta(days=x["results_grace_days"])).date()
        filed = [e for e in ev if e["category"] == "results"
                 and e["source"] in ("bse_announcements", "nse_announcements") and e["date"] > q["d"]]
        if today > due and not filed:
            out.append({"text": "Exit: results overdue", "tone": "red", "as_of": due.isoformat(), "kind": "exit"})
    p = ((card or {}).get("pledge") or {}).get("pledge_pct")
    if p is not None and p > x["pledge_review_pct"]:
        out.append({"text": f"Review: pledge {p:.0f} %", "tone": "amber", "as_of": card["pledge"].get("end_date"), "kind": "review"})
    pr = _rows("SELECT end_date, promoter_pct FROM shareholding_categories WHERE sid = ? AND promoter_pct IS NOT NULL "
               "ORDER BY end_date DESC LIMIT 3", [sid])
    if len(pr) == 3 and pr[2]["promoter_pct"] - pr[0]["promoter_pct"] > x["promoter_drop_pts"]:
        out.append({"text": f"Review: promoter down {pr[2]['promoter_pct'] - pr[0]['promoter_pct']:.1f} pts",
                    "tone": "amber", "as_of": pr[0]["end_date"], "kind": "review"})
    dm = _one("SELECT MAX(ex_date) AS d FROM corporate_adjustments WHERE sid = ? AND inds LIKE '%DEMERGER%' AND ex_date >= ?",
              [sid, (today - pd.Timedelta(days=x["demerger_days"])).isoformat()])
    if dm and dm.get("d"):
        out.append({"text": "Review: demerged, score uses pre-demerger results", "tone": "amber", "as_of": dm["d"],
                    "kind": "review"})
    return out


def _last_event(sid):
    ev = [e for e in _events(sid) if e["source"] not in ("news_articles", "regulatory_events")]
    return ev[0]["date"] if ev else None


# ── Funnel: the top 100 as evidence cards ───────────────────────────────────────────────────────

@_persisted_cache(3600, name="mb_funnel_cards_v3")
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
                    "flags": exit_flags(r["sid"], c) + _flags(c), "card_as_of": c.get("as_of")})
    return out


def funnel():
    """Funnel tab: counts, gate tally, grade, and the cards with each name's current book status and research verdict."""
    counts = funnel_counts()
    cards = funnel_cards(counts["as_of"]) if counts["as_of"] else []
    status = book_status([c["sid"] for c in cards])
    res = research_verdicts()
    return {**counts, "grade": GRADE, "n_researched": sum(c["sid"] in res for c in cards),
            "cards": [{**c, "status": status.get(c["sid"]), "research": res.get(c["sid"])} for c in cards]}


# ── Deep research (plan 0026 stage 4b) ──────────────────────────────────────────────────────────

RESEARCH_TONE = {"clean": "green", "flag": "amber", "reject": "red"}
RESEARCH_WORD = {"clean": "Research: clean", "flag": "Research: flagged", "reject": "Research: reject"}


def research_verdicts():
    """{sid: {verdict, multibagger_case, verdict_reason, as_of_date, n_high_flags, tone, word}}, newest per stock.
    Not cached: it changes whenever a research wave is loaded."""
    rows = _rows("SELECT r.sid, r.verdict, r.multibagger_case, r.verdict_reason, r.as_of_date, r.n_high_flags "
                 "FROM mb_research r JOIN (SELECT sid, MAX(as_of_date) AS d FROM mb_research GROUP BY sid) m "
                 "ON m.sid = r.sid AND m.d = r.as_of_date")
    return {r["sid"]: {**r, "tone": RESEARCH_TONE.get(r["verdict"], "muted"), "word": RESEARCH_WORD.get(r["verdict"], r["verdict"])}
            for r in rows}


def research(sid):
    """The newest deep research for one stock, shaped for the stock page, or None."""
    if not _rows("SELECT 1 AS x FROM mb_research WHERE sid = ? LIMIT 1", [sid]):
        return None
    from output import mb_research
    r = mb_research.latest(sid)
    f = r["fields"]
    sev = {"high": 0, "medium": 1, "low": 2}
    return {"as_of": r["as_of_date"], "verdict": r["verdict"], "verdict_reason": r["verdict_reason"],
            "case": r["multibagger_case"], "case_reason": r["case_reason"], "model": r.get("model"),
            "tone": RESEARCH_TONE.get(r["verdict"], "muted"), "word": RESEARCH_WORD.get(r["verdict"], r["verdict"]),
            "red_flags": sorted(f.get("red_flags") or [], key=lambda x: sev.get(x.get("severity"), 3)),
            "checks": [(k.replace("_", " "), v) for k, v in (f.get("red_flag_checks") or {}).items()],
            "business": f.get("business") or {}, "growth_drivers": f.get("growth_drivers") or [],
            "catalysts": f.get("catalysts_12m") or [], "breaks": f.get("what_would_break_it") or [],
            "unknowns": f.get("unknowns") or [], "sources": f.get("sources") or [], "report": r["report"]}


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
        f["dec"] = 0 if max([m["high"] for m in shown] + [price]) >= 100 else 1      # one precision per field
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

def capacity_for(book):
    """{sid: capacity block} for book rows: the per-name amount is book_inr / max_held for a held name and
    book_inr / max_book for a candidate (output.mb_capacity). Texts are prepared here, not in the template."""
    cfg, out = config.MB_THESIS, {}
    for max_names, status in ((cfg["max_book"], "candidate"), (cfg["max_held"], "held")):
        sids = [b["sid"] for b in book if b["status"] == status]
        for sid, c in (mb_capacity.capacity(_rows, sids, max_names) if sids else {}).items():
            out[sid] = {**c, "max_text": mb_capacity.inr_short(c["max_inr"]), "per_name_text": mb_capacity.inr_short(c["per_name_inr"]),
                        "adv_text": mb_capacity.inr_short(c["adv_inr"]), "share_pct": None if c["share"] is None else round(c["share"] * 100, 1),
                        "names": max_names}
    return out


def candidates():
    book = book_rows()
    sids = tuple(b["sid"] for b in book)
    th, vf, cap = thesis_rows(sids), valuation_fields(sids), capacity_for(book)
    rows = []
    for b in book:
        t = th.get(b["sid"])
        c = _card(b["sid"]) if b["name"] else {}
        rows.append({**b, "cap": cap.get(b["sid"]), "thesis": t, "parts": parts_of(t), "score": None if not t or t["thesis_score"] is None
                     else round(t["thesis_score"] * 100), "field": vf.get(b["sid"]),
                     "flags": (exit_flags(b["sid"], c) if b["name"] else []) + _flags(c),
                     "last_event": _last_event(b["sid"]) if b["name"] else None})
    return {"rows": rows, "n_book": len(book), "max_book": config.MB_THESIS["max_book"],
            "thesis_as_of": snapshot(), "n_held": sum(r["status"] == "held" for r in rows),
            "max_held": config.MB_THESIS["max_held"], "book_text": mb_capacity.inr_short(config.MB_THESIS["book_inr"]),
            "adv_share_pct": round(config.MB_THESIS["max_adv_share"] * 100)}


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


def paper_books():
    """The three forward paper books and their kill rules as tools/mb_paper.py last wrote them ({} before the
    first `run.sh mb_paper start`). One reader: views.mb_paper."""
    import views
    return views.mb_paper()


def held():
    """The held names: return since entry against NIFTY SMALLCAP 250 over the same dates, the conviction verdict
    (monitor only), days since the last logged decision and events since entry (medium and up)."""
    book = [b for b in book_rows() if b["status"] == "held"]
    verdicts = _verdicts(tuple(b["sid"] for b in book))
    log_ts = {r["sid"]: r["ts"] for r in _rows(
        "SELECT sid, MAX(ts) AS ts FROM multibagger_book_log GROUP BY sid")} if book else {}
    b_now, b_now_d = _bench()
    cap = capacity_for(book)
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
        rows.append({**b, "cap": cap.get(b["sid"]), "exits": exit_flags(b["sid"], _card(b["sid"]) if b["name"] else None),
                     "price": px, "price_date": px_d, "return_pct": own, "bench_pct": idx,
                     "vs_bench_pts": None if own is None or idx is None else round(own - idx, 1),
                     "verdict": v and v["verdict"], "drawdown_pct": v and round(v["drawdown"] * 100, 1),
                     "months_underwater": v and v["months_underwater"],
                     "days_since_review": None if not ts else (today - date.fromisoformat(ts[:10])).days,
                     "events_since_entry": len(ev) if b["entry_date"] else None})
    return {"rows": rows, "n_held": len(rows), "max_held": config.MB_THESIS["max_held"], "bench": BENCH,
            "n_book": len(book_rows()), "max_book": config.MB_THESIS["max_book"],
            "bench_as_of": b_now_d, "book_inr": config.MB_THESIS["book_inr"],
            "book_text": mb_capacity.inr_short(config.MB_THESIS["book_inr"]),
            "adv_share_pct": round(config.MB_THESIS["max_adv_share"] * 100), "paper": paper_books()}


def watch(days=90):
    """The merged event feed of every candidate and held name for the last `days` days, newest first. All
    severities are included; the page filters (default medium and up)."""
    book = book_rows()
    since = (pd.Timestamp.now().normalize() - pd.Timedelta(days=days)).strftime("%Y-%m-%d")
    rows = []
    for b in book:
        for e in _events(b["sid"]):
            if e["date"] >= since:
                rows.append({**e, "sid": b["sid"], "ticker": b["ticker"], "name": b["name"] or b["sid"], "status": b["status"],
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
            ("events", _events, (sid,)), ("dossier", dossier, (sid,)), ("research", research, (sid,))):
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
