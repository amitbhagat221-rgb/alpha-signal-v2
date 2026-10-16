"""
Plan 0026 stage 4b — deep research on the multibagger top 100: the "already known" pack per stock, the
research brief's fixed answer shape, and the loader into `mb_research`.

The pack is everything our database already holds for one stock, so a research agent spends its budget only on
what we do not have (business model, management, related parties, legal, capex plans, customers ...). Each section
names its table and as-of date; the closing "Gaps" section lists what is missing or thin for that stock.

    python -m output.mb_research --packs [--sids A,B]   # write output/mb_research/<sid>/pack.md for the top 100
    python -m output.mb_research --show SID             # print one pack
    python -m output.mb_research --load [--sids A,B]    # validate verdict.json + report.md, upsert mb_research
    python -m output.mb_research --status               # packs / reports / loaded per stock

The research brief agents follow: docs/research/0011-multibagger-deep-research-brief.md.
"""
import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

import db

ROOT = Path(__file__).resolve().parent / "mb_research"
BSE_ATTACH = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"   # serves new and archived filings
MAX_PACK_BYTES = 90_000

ANNUAL_ITEMS = ["Sales", "Net profit", "Cash from Operating Activity", "Cash from Investing Activity",
                "Equity Share Capital", "Reserves", "Borrowings", "Gross Block", "Capital Work in Progress",
                "Trade receivables", "Inventories", "No. of Equity Shares", "Other Income"]
# BSE filings worth reading, by subcategory pattern → (label, how many of the newest to list)
DOC_KINDS = [
    ("Reg. 34 (1) Annual Report%", "Annual report", 3),
    ("Earnings Call Transcript%", "Earnings call transcript", 6),
    ("Investor Presentation%", "Investor presentation", 4),
    ("Analyst / Investor Meet%", "Analyst / investor meet (concall transcripts often filed here)", 8),
    ("Credit Rating%", "Credit rating", 5),
    ("Press Release / Media Release%", "Press release", 8),
    ("Change in Management%", "Change in management", 8),
    ("Change in Directorate%", "Change in directorate", 8),
    ("Resignation%", "Resignation", 8),
    ("Award of Order%", "Order win", 10),
    ("Memorandum of Understanding%", "MoU / agreement", 6),
    ("Acquisition%", "Acquisition", 6),
    ("Preferential Issue%", "Preferential issue", 6),
    ("Allotment%", "Allotment", 6),
    ("Clarification%", "Clarification", 6),
]
VERDICTS = ("clean", "flag", "reject")
CHECKS = ("auditor", "related_party", "promoter", "regulatory_legal", "accounting", "dilution", "debt_liquidity",
          "governance", "disclosure", "concentration", "corporate_actions", "other")
CHECK_ANSWERS = ("found", "not_found", "could_not_check")
CASE = ("strong", "plausible", "weak")
SEVERITY = ("high", "medium", "low")
FLAG_AREAS = ("governance", "related_party", "audit", "accounting", "legal_regulatory", "dilution", "promoter",
              "pledge", "liquidity_debt", "business", "disclosure", "other")
REQUIRED = {"sid": str, "ticker": str, "as_of": str, "verdict": str, "verdict_reason": str, "multibagger_case": str,
            "case_reason": str, "red_flags": list, "red_flag_checks": dict, "business": dict, "growth_drivers": list, "management": dict,
            "govt_political_links": list, "funding_dilution": list, "catalysts_12m": list, "what_would_break_it": list,
            "unknowns": list, "sources": list}
MIN_SOURCES = 6


# ── the pack ─────────────────────────────────────────────────────────────────

def top100(as_of=None):
    """sids of the latest thesis top 100, best first."""
    d = as_of or db.one("SELECT MAX(snapshot_date) AS d FROM multibagger_scores WHERE thesis_rank IS NOT NULL")["d"]
    sids = [r["sid"] for r in db.rows("SELECT sid FROM multibagger_scores WHERE snapshot_date = ? AND thesis_rank "
                                      "<= 100 ORDER BY thesis_rank", [d])]
    if not sids:
        raise ValueError(f"no thesis top 100 on {d}")
    return sids


def _md(rows, cols=None, limit=None):
    """Pipe table from a list of dicts; None → '-'."""
    rows = list(rows)[:limit] if limit else list(rows)
    if not rows:
        return "_none in our database_"
    cols = cols or list(rows[0])
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(_cell(r.get(c)) for c in cols) + " |")
    return "\n".join(out)


def _cell(x):
    if x is None or x != x:
        return "-"
    if isinstance(x, float):
        return f"{x:,.0f}" if abs(x) >= 1e5 else f"{x:.1f}" if abs(x) >= 100 else f"{x:.2f}"
    return str(x).replace("|", "/").replace("\n", " ")


def warnings(sid, quarters, valuation, price):
    """Our own numbers that are known-bad or suspect for this stock: the agent should verify, not trust, these."""
    w = []
    dm = db.rows("SELECT ex_date, factor FROM corporate_adjustments WHERE sid = ? AND inds LIKE '%DEMERGER%' AND "
                 "ex_date >= date('now', '-365 day') ORDER BY ex_date", [sid])
    for d in dm:
        w.append(f"DEMERGER on {d['ex_date']} (price kept {d['factor'] * 100:.0f} % of its value). Our annual and "
                 "most quarterly figures, every valuation range and the thesis cheapness / latest-quarter parts use "
                 "the PRE-demerger company. Establish what the remaining company is and its own revenue / profit; "
                 "judge the stock on that, not on sections 1–4.")
    sh = db.one("SELECT end_date, total_shares FROM shareholding_categories WHERE sid = ? AND total_shares > 0 "
                "ORDER BY end_date DESC LIMIT 1", [sid])
    mc = db.one("SELECT mcap_cr FROM multibagger_scores WHERE sid = ? AND mcap_cr > 0 ORDER BY snapshot_date DESC LIMIT 1", [sid])
    if sh and mc and price:
        adj = db.one("SELECT EXP(SUM(LN(factor))) AS f FROM corporate_adjustments WHERE sid = ? AND ex_date > ? AND "
                     "(inds LIKE '%SPLIT%' OR inds LIKE '%BONUS%') AND factor > 0", [sid, sh["end_date"]])
        sh = {**sh, "total_shares": sh["total_shares"] / ((adj or {}).get("f") or 1.0)}   # a 1:1 bonus after the filing doubles it
        ratio = sh["total_shares"] * price / 1e7 / mc["mcap_cr"]
        if ratio > 1.3 or ratio < 1 / 1.3:
            w.append(f"SHARE COUNT: the latest shareholding filing ({sh['end_date']}) shows {sh['total_shares']:,.0f} shares, "
                     f"a market cap of Rs {sh['total_shares'] * price / 1e7:,.0f} Cr, {ratio:.2f}x our Rs "
                     f"{mc['mcap_cr']:,.0f} Cr. Our market cap, per-share values and the thesis small / cheap parts use a "
                     "stale share count (merger, allotment, split). Verify the count and judge size and value on it.")
    fy = db.one("SELECT MAX(period_end) AS d FROM fundamentals_screener WHERE sid = ? AND period_type = 'annual'", [sid])
    if fy and fy["d"] and fy["d"] < str(dt.date.today() - dt.timedelta(days=550)):
        w.append(f"STALE ANNUALS: our newest annual figures are for the year to {fy['d']}. Section 2 and every "
                 "valuation range built on annual data (DCF, EV bands, net debt) are out of date: use the latest "
                 "annual report instead.")
    rq = db.one("SELECT q.end_date, q.revenue, f.value AS sales FROM quarterly_income q JOIN fundamentals_screener f ON f.sid = q.sid "
                  "AND f.period_type = 'quarterly' AND f.line_item = 'Sales' AND f.period_end = q.end_date WHERE q.sid = ? "
                  "ORDER BY q.end_date DESC, CASE q.reporting WHEN 'consolidated' THEN 0 ELSE 1 END LIMIT 1", [sid])
    if rq and rq["revenue"] and rq["sales"] and not (1 / 1.25 <= rq["revenue"] / rq["sales"] <= 1.25):
        w.append(f"QUARTER REVENUE: for the quarter to {rq['end_date']} our results table shows revenue Rs "
                 f"{rq['revenue']:,.1f} Cr but Screener's sales are Rs {rq['sales']:,.1f} Cr "
                 f"({rq['revenue'] / rq['sales']:.2f}x). A one-off gain or other income is probably counted as revenue, "
                 "which inflates section 3 and the thesis latest-quarter part. Read the filed result.")
    for q in quarters:
        m = q.get("ebitda_margin_pct")
        if m is not None and (m > 60 or m < -100):
            w.append(f"Quarter {q['period']}: EBITDA margin {m} % is implausible for most businesses, likely a bad row: check the filed result before using it.")
    if price:
        for v in valuation:
            if v.get("mid") and (v["mid"] > 4 * price or v["mid"] < price / 4) and v["method"] not in ("range_52w", "dcf", "reverse_dcf"):
                w.append(f"Valuation '{v['method']}' mid Rs {v['mid']:.0f} is over 4x away from the price Rs "
                         f"{price:.1f}: suspect inputs (corporate action, stale shares or one-off profit).")
    return w


def annual(sid, years=10):
    """{period_end: {line_item: value}} newest `years` annual rows from fundamentals_screener (Rs crore)."""
    ph = ",".join("?" * len(ANNUAL_ITEMS))
    df = db.read_sql(f"SELECT period_end, line_item, value FROM fundamentals_screener WHERE sid = ? AND "
                     f"period_type = 'annual' AND line_item IN ({ph})", [sid, *ANNUAL_ITEMS])
    if df.empty:
        return []
    w = df.pivot_table(index="period_end", columns="line_item", values="value", aggfunc="last").sort_index()
    w = w.tail(years)
    return [{"FY end": i, **{c: (None if pd.isna(w.at[i, c]) else round(float(w.at[i, c]), 1))
                             for c in ANNUAL_ITEMS if c in w.columns}} for i in w.index]


def documents(sid):
    """{label: [{date, title, url}]} BSE filings worth reading, newest first."""
    out = {}
    extra = db.rows("SELECT dt_tm, news_sub, headline, attachment FROM bse_announcements WHERE sid = ? AND "
                    "subcategory NOT LIKE 'Reg. 34 (1) Annual Report%' AND (news_sub LIKE '%Annual Report%' OR "
                    "headline LIKE '%Annual Report%') AND COALESCE(attachment, '') <> '' ORDER BY dt_tm DESC LIMIT 3", [sid])
    if extra:                                     # annual reports filed under 'General' / 'AGM' (new listings do this)
        out["Annual report (filed under AGM / general)"] = [
            {"date": r["dt_tm"][:10], "title": (r["news_sub"] or r["headline"] or "")[:140], "url": BSE_ATTACH + r["attachment"]}
            for r in extra]
    for pat, label, n in DOC_KINDS:
        rows = db.rows("SELECT dt_tm, news_sub, headline, attachment FROM bse_announcements WHERE sid = ? AND "
                       "subcategory LIKE ? AND COALESCE(attachment, '') <> '' ORDER BY dt_tm DESC LIMIT ?",
                       [sid, pat, n])
        if rows:
            out[label] = [{"date": r["dt_tm"][:10], "title": (r["news_sub"] or r["headline"] or "")[:140],
                           "url": BSE_ATTACH + r["attachment"]} for r in rows]
    return out


def _counts(sid):
    one = lambda q: (db.one(q, [sid]) or {}).get("n") or 0  # noqa: E731
    return {
        "bse_filings": one("SELECT COUNT(*) AS n FROM bse_announcements WHERE sid = ?"),
        "shareholding_filings": one("SELECT COUNT(DISTINCT end_date) AS n FROM shareholding_categories WHERE sid = ?"),
        "news_1y": one("SELECT COUNT(*) AS n FROM news_article_stocks s JOIN news_articles a USING(article_id) "
                       "WHERE s.sid = ? AND a.published_at >= date('now', '-365 day')"),
        "transcripts": one("SELECT COUNT(*) AS n FROM transcripts WHERE sid = ?"),
        "ratings": one("SELECT COUNT(*) AS n FROM bse_announcements WHERE sid = ? AND subcategory LIKE 'Credit Rating%'"),
        "analysts": one("SELECT MAX(total_analysts) AS n FROM analyst_consensus WHERE sid = ?"),
        "insider_trades": one("SELECT COUNT(*) AS n FROM insider_trades WHERE sid = ?"),
        "mf_holdings": one("SELECT COUNT(*) AS n FROM mf_holdings WHERE sid = ?"),
    }


def gaps(sid, counts=None, docs=None, quarters=None):
    """What our database lacks or holds thinly for this stock: research these first."""
    c = counts or _counts(sid)
    docs = documents(sid) if docs is None else docs
    g = []
    if not c["bse_filings"]:
        g.append("No BSE filings on file (likely NSE-only): find the annual report, investor presentation, concall "
                 "transcripts and credit-rating letters on nseindia.com or the company website yourself.")
    else:
        for label in ("Annual report", "Investor presentation", "Credit rating"):
            if not any(k.startswith(label) for k in docs):
                g.append(f"No {label.lower()} PDF among our BSE filings: look on the company website / NSE.")
    if not c["shareholding_filings"]:
        g.append("No shareholding pattern history: get promoter %, pledge and top holders from the latest filing.")
    if c["news_1y"] < 5:
        g.append(f"News is thin ({c['news_1y']} tagged articles in the past year): search the business press.")
    if not c["transcripts"]:
        g.append("No concall transcripts parsed: read the newest ones (BSE 'Analyst / investor meet' links above, "
                 "or the company's investor page).")
    if (c["analysts"] or 0) < 3:
        g.append("Fewer than 3 sell-side analysts: there is no consensus; brokerage initiation notes are rare.")
    if quarters is not None and (not quarters or quarters[-1]["end_date"] < str(dt.date.today() - dt.timedelta(days=200))):
        g.append("Quarterly results on file are stale or missing: check the newest filed results.")
    g.append("Never in our database (always research): business model and segments, customers and concentration, "
             "competitors and industry structure, capacity / capex plans and order book, management and promoter "
             "background, related-party transactions, auditor and audit opinions (qualifications, CARO), "
             "litigation and regulator orders (SEBI, NCLT/IBC, tax, ED), group-company troubles, guidance from "
             "concalls, fund-raise plans (QIP, warrants, preferential), government or political links beyond "
             "shareholders.")
    return g


def pack(sid):
    """Markdown 'what our database already knows' for one stock."""
    from output import mb_deepdive as mb
    from signals import mb_watch as w
    st = db.one("SELECT sid, ticker, name, sector, industry, cap_tier, market_cap_cr FROM stocks WHERE sid = ?", [sid])
    if not st:
        raise ValueError(f"unknown sid {sid}")
    card = w.card(sid)
    th = db.one("SELECT snapshot_date, thesis_rank, thesis_score, p_smallness, p_cheapness, p_price, p_business, "
                "p_tailwind, adtv_cr, mcap_cr FROM multibagger_scores WHERE sid = ? AND thesis_rank IS NOT NULL "
                "ORDER BY snapshot_date DESC LIMIT 1", [sid]) or {}
    q = mb.results_trend(sid, 12)
    own = mb.ownership_timeline(sid)
    docs = documents(sid)
    counts = _counts(sid)
    tl = w.timeline(sid, since=pd.Timestamp.now() - pd.Timedelta(days=730))
    tl = tl[tl["severity"].isin(["high", "medium"])].head(60)
    ins = db.rows("SELECT trade_date, person, person_category, transaction_type, shares, value_lakhs FROM "
                  "insider_trades WHERE sid = ? AND trade_date >= date('now', '-730 day') ORDER BY trade_date DESC "
                  "LIMIT 25", [sid])
    bulk = db.rows("SELECT deal_date, deal_type, client_name, buy_sell, quantity, price FROM bulk_deals WHERE sid = ? "
                   "AND deal_date >= date('now', '-730 day') ORDER BY deal_date DESC LIMIT 25", [sid])
    gl = w.govt_links(sid)
    val = mb.latest_valuation(sid)
    px = db.one("SELECT close FROM stock_prices WHERE sid = ? ORDER BY date DESC LIMIT 1", [sid])
    warn = warnings(sid, q, val, px and px["close"])
    f = card.get("forensic") or {}

    s = [f"# {st['name']} ({st['ticker']}, sid {sid}) — what our database already knows",
         f"Built {dt.date.today()} by `output/mb_research.py`. **Do not re-fetch anything below**; cite it as "
         "`[db]`. Spend your research on the Gaps section (end) and on the brief's questions.", ""]
    s += ["## 0. Data warnings — verify these, do not trust our numbers here",
          *([f"- {x}" for x in warn] or ["- none found"]), ""]
    s += ["## 1. Identity and thesis score",
          f"- Sector / industry: {st['sector']} / {st['industry']} · tier {st['cap_tier']}",
          f"- Market cap Rs {_r(th.get('mcap_cr') or st['market_cap_cr'], 0)} Cr · 6-month avg daily traded "
          f"value Rs {_r(th.get('adtv_cr'))} Cr · last close Rs {px and px['close']}",
          f"- Thesis rank {th.get('thesis_rank')} of the top 100 on {th.get('snapshot_date')} (score "
          f"{_r(th.get('thesis_score'))}); parts (0–1, higher = better): small {_r(th.get('p_smallness'))}, cheap "
          f"{_r(th.get('p_cheapness'))}, price momentum {_r(th.get('p_price'))}, latest quarter "
          f"{_r(th.get('p_business'))}, industry momentum {_r(th.get('p_tailwind'))}",
          f"- Forensic: Beneish M {f.get('m_score')} ({f.get('m_score_flag')}, {f.get('m_score_date')}); Altman Z "
          f"{f.get('z_score')} ({f.get('z_score_flag')}, {f.get('z_score_date')})",
          f"- Pledge {_r((card.get('pledge') or {}).get('pledge_pct'))} % · promoter "
          f"{_r((card.get('promoter') or {}).get('promoter_pct'))} % (filing {(card.get('promoter') or {}).get('end_date')})",
          f"- Known investors in the latest filing: {[k['investor'] for k in card.get('known_investors') or []]}", ""]
    s += ["## 2. Annual financials, Rs crore [db: fundamentals_screener]", _md(annual(sid)), ""]
    s += ["## 3. Last 12 quarters, Rs crore [db: quarterly_income / fundamentals_screener]",
          _md(q, ["period", "end_date", "revenue", "ebitda", "pat", "ebitda_margin_pct", "rev_yoy_pct",
                  "pat_yoy_pct", "source"]), ""]
    s += ["## 4. Valuation ranges, Rs per share [db: valuation_ranges]",
          _md(val, ["method", "low", "mid", "high", "basis"]), ""]
    own_rows = [{**o, "entered": "; ".join(f"{e['name']} {e['pct']}" for e in o["entered"][:4]),
                 "exited": "; ".join(f"{e['name']} {e['pct']}" for e in o["exited"][:4])} for o in own[-12:]]
    s += ["## 5. Ownership by filing, % [db: shareholding_categories / shareholding_holders]",
          _md(own_rows, ["end_date", "promoter_pct", "pledge_pct", "fii_pct", "dii_pct", "mf_pct", "retail_pct",
                         "n_shareholders", "entered", "exited"]), ""]
    s += ["## 6. Insider trades (value in Rs lakh) and bulk deals, past 2 years [db: insider_trades / bulk_deals]",
          _md(ins), "", _md(bulk), ""]
    ev = [{"date": str(r.date)[:10], "category": r.category, "severity": r.severity,
           "headline": (r.headline or "")[:150], "url": r.url} for r in tl.itertuples()]
    s += ["## 7. Medium/high-severity events, past 2 years [db: signals.mb_watch.timeline]", _md(ev), ""]
    s += ["## 8. Government links [db: shareholding_holders / bse_announcements]",
          f"- Government holders (latest): {[(h['holder_name'], h['pct'], h['end_date']) for h in gl['govt_holders']]}",
          f"- Government-buyer orders found: {gl['n_govt_orders']}",
          _md(gl["govt_orders"][:10], ["date", "headline", "matched", "url"]),
          "- Electoral-bond donor: not loaded in our database", ""]
    s += ["## 9. Peers, same industry and tier [db: peers]",
          _md(mb.peers(sid, 8), ["ticker", "name", "market_cap_cr", "pe", "pb", "roe_pct", "rev_growth_pct",
                                 "ret_6m_pct", "thesis_score"]), ""]
    s += ["## 10. Filings on file — open these PDFs directly (BSE archive links)"]
    if docs:
        for label, rows in docs.items():
            s += [f"**{label}**", _md(rows, ["date", "title", "url"]), ""]
    else:
        s += ["_none: no BSE filings with attachments on file_", ""]
    s += ["## 11. Coverage counts [db]", ", ".join(f"{k} {v}" for k, v in counts.items()), ""]
    s += ["## 12. Gaps — research these", *[f"- {x}" for x in gaps(sid, counts, docs, q)], ""]
    text = "\n".join(s)
    if len(text.encode()) > MAX_PACK_BYTES:
        raise ValueError(f"pack for {sid} is {len(text.encode())} bytes, over {MAX_PACK_BYTES}")
    return text


def _r(x, nd=2):
    return None if x is None else round(float(x), nd)


def write_packs(sids):
    """Write output/mb_research/<sid>/pack.md; returns {sid: bytes}. Raises when nothing was written."""
    out = {}
    for sid in sids:
        d = ROOT / sid
        d.mkdir(parents=True, exist_ok=True)
        text = pack(sid)
        (d / "pack.md").write_text(text)
        out[sid] = len(text.encode())
    if not out:
        raise ValueError("no pack written")
    return out


# ── the answer ───────────────────────────────────────────────────────────────

def validate(v, report=""):
    """List of problems with one verdict.json (empty = valid)."""
    p = []
    for k, t in REQUIRED.items():
        if not isinstance(v.get(k), t):
            p.append(f"{k}: missing or not {t.__name__}")
    if p:
        return p
    if v["verdict"] not in VERDICTS:
        p.append(f"verdict must be one of {VERDICTS}")
    if v["multibagger_case"] not in CASE:
        p.append(f"multibagger_case must be one of {CASE}")
    for i, f in enumerate(v["red_flags"]):
        if f.get("severity") not in SEVERITY or f.get("area") not in FLAG_AREAS:
            p.append(f"red_flags[{i}]: severity in {SEVERITY}, area in {FLAG_AREAS}")
        if not str(f.get("source_url", "")).startswith(("http", "[db]")):
            p.append(f"red_flags[{i}]: source_url required")
    if v["verdict"] == "reject" and not any(f.get("severity") == "high" for f in v["red_flags"]):
        p.append("reject needs at least one high-severity red flag")
    if v["verdict"] != "reject" and any(f.get("severity") == "high" for f in v["red_flags"]):
        p.append("a high-severity red flag means reject (a stay or pending appeal does not downgrade it)")
    missing = [c for c in CHECKS if v["red_flag_checks"].get(c) not in CHECK_ANSWERS]
    if missing:
        p.append(f"red_flag_checks: {missing} must each be one of {CHECK_ANSWERS}")
    web = [s for s in v["sources"] if str(s.get("url", "")).startswith("http")]
    if len(web) < MIN_SOURCES:
        p.append(f"sources: {len(web)} web sources, need >= {MIN_SOURCES}")
    if len(report.split()) < 600:
        p.append("report.md under 600 words")
    return p


def load(sids=None):
    """Validate and upsert every output/mb_research/<sid>/{verdict.json, report.md}; returns {sid: problems}."""
    done = {}
    rows = []
    for d in sorted(p for p in ROOT.iterdir() if p.is_dir()) if ROOT.exists() else []:
        if sids and d.name not in sids:
            continue
        vj, rp = d / "verdict.json", d / "report.md"
        if not vj.exists() or not rp.exists():
            continue
        try:
            v = json.loads(vj.read_text())
        except json.JSONDecodeError as e:
            done[d.name] = [f"verdict.json: {e}"]
            continue
        report = rp.read_text()
        probs = validate(v, report)
        if v.get("sid") != d.name:
            probs.append(f"sid {v.get('sid')} does not match folder {d.name}")
        done[d.name] = probs
        if probs:
            continue
        rows.append({"sid": d.name, "as_of_date": v["as_of"], "verdict": v["verdict"],
                     "verdict_reason": v["verdict_reason"], "multibagger_case": v["multibagger_case"],
                     "case_reason": v["case_reason"], "n_red_flags": len(v["red_flags"]),
                     "n_high_flags": sum(f["severity"] == "high" for f in v["red_flags"]),
                     "fields": json.dumps(v, ensure_ascii=False), "report": report,
                     "model": v.get("model"), "created_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")})
    if rows:
        db.upsert_df(pd.DataFrame(rows), "mb_research")
        set_sectors()
    return done


# Verdicts that sit on the reject / flag line, for Amit to decide (Amit 2026-10-16: "i'll decide, mark them as
# borderline somewhere"). The verdict stands until he changes it; the reason says which way it could go.
BORDERLINE = {
    "RENA": "Reject rests on a Rs 10.7 Cr purchase of preference shares from the promoter, about 0.7 % of net worth; small enough to call a flag.",
    "FLY": "Reject rests on reading related-party advances as leakage; if they are benign, it is a flag.",
    "ARRO": "Reject rests on reading the promoter-family supplier as leakage; on the 'when in doubt, medium' rule it would be a flag.",
    "ZURI": "Reject rests on a group company's SEBI settlement over misstatements; the listed company itself was not named.",
    "THEM": "Reject rests on circumstantial evidence about promoter-owned distributors' unpaid dues.",
    "VENR": "Reject rests on technology bought from promoter-linked firms with no valuation report seen; one would make it a flag.",
    "KIDI": "Reject rests on promoter LLP capital and advances that were mostly returned within each year.",
    "IRIC": "Reject rests on the seller of a business being an insider not declared as a related party; the company may argue he is not senior management.",
    "DOLP": "Reject rests on a SEBI insider-trading order matched to the MD by name and directorship, not by PAN.",
    "GYSC": "Moved from reject to flag under the substantive-only SEBI rule: late disclosure of loan defaults and a promoter arrest.",
    "PRPF": "Moved from reject to flag under the substantive-only SEBI rule: a related party reported as unrelated.",
    "IGPT": "Flag, but the Rs 230 Cr London property in a subsidiary could be leakage; if so, reject.",
    "ARAI": "Flag, but the money stuck in the sold-off UAE associate could be read as leakage; if so, reject.",
    "HMA": "Flag, but a CBI preliminary enquiry and tax searches were rated medium; a stricter reading is reject.",
    "KRYS": "Reject for promoter-linked loans; separately, a promoter police case left out of the IPO document was rated medium.",
}


def set_sectors():
    """Write sector / sub_sector (output/mb_sectors.py) onto every mb_research row; returns the sids with no entry."""
    from output.mb_sectors import SECTORS
    sids = [r["sid"] for r in db.rows("SELECT DISTINCT sid FROM mb_research")]
    with db.get_db() as c:
        for sid in sids:
            if sid in SECTORS:
                c.execute("UPDATE mb_research SET sector = ?, sub_sector = ? WHERE sid = ?", (*SECTORS[sid], sid))
    return sorted(set(sids) - set(SECTORS))


def points(fields):
    """(penalty, bonus, detail) of one research verdict under config.MB_THESIS['research_overlay']."""
    from config import MB_THESIS
    o = MB_THESIS["research_overlay"]
    n = {"integrity": {"medium": 0, "low": 0}, "business": {"medium": 0, "low": 0}}
    for f in fields.get("red_flags") or []:
        sev = f.get("severity")
        if sev in ("medium", "low"):
            n["integrity" if f.get("area") in o["integrity_areas"] else "business"][sev] += 1
    raw = sum(o["flag_points"][s][g] * k for g, d in n.items() for s, k in d.items())
    penalty = min(raw, o["max_penalty"])
    bonus = o["case_points"].get(fields.get("multibagger_case"), 0.0)
    return round(penalty, 4), bonus, n


def overlay(snapshot=None):
    """The research-adjusted ranking of the thesis top 100: thesis_score - flag points + 5x-case points; a reject is
    out (research_rank NaN). Not researched -> thesis score unchanged, marked. Sorted best first."""
    from config import MB_THESIS
    snap = snapshot or db.one("SELECT MAX(snapshot_date) AS d FROM multibagger_scores WHERE thesis_rank IS NOT NULL")["d"]
    th = db.read_sql("SELECT m.sid, m.thesis_rank, m.thesis_score, s.ticker, s.name FROM multibagger_scores m JOIN stocks s "
                     "USING (sid) WHERE m.snapshot_date = ? AND m.thesis_rank <= ?", [snap, MB_THESIS["top_n"]])
    rs = {r["sid"]: r for r in db.rows(
        "SELECT r.sid, r.as_of_date, r.verdict, r.multibagger_case, r.verdict_reason, r.case_reason, r.fields, r.sector, "
        "r.sub_sector FROM mb_research r JOIN (SELECT sid, MAX(as_of_date) AS d FROM mb_research GROUP BY sid) l "
        "ON l.sid = r.sid AND l.d = r.as_of_date")}
    out = []
    for t in th.to_dict("records"):
        r = rs.get(t["sid"])
        row = {**t, "snapshot_date": snap, "researched": r is not None, "as_of_date": None, "verdict": None,
               "multibagger_case": None, "verdict_reason": None, "case_reason": None, "sector": None, "sub_sector": None,
               "penalty": 0.0, "bonus": 0.0, "n_integrity": 0, "n_business": 0}
        if r:
            f = json.loads(r["fields"])
            pen, bon, n = points(f)
            row.update({k: r[k] for k in ("as_of_date", "verdict", "multibagger_case", "verdict_reason", "case_reason",
                                          "sector", "sub_sector")},
                       penalty=pen, bonus=bon, n_integrity=n["integrity"]["medium"] + n["integrity"]["low"],
                       n_business=n["business"]["medium"] + n["business"]["low"])
        row["borderline"] = BORDERLINE.get(t["sid"])
        row["research_score"] = None if row["verdict"] == "reject" else t["thesis_score"] - row["penalty"] + row["bonus"]
        out.append(row)
    df = pd.DataFrame(out)
    df["research_rank"] = df["research_score"].rank(ascending=False, method="first")
    return df.sort_values(["research_rank", "thesis_rank"], na_position="last").reset_index(drop=True)


def promote_top(n=None, actor="claude", dry_run=False):
    """Make the overlay's top n the candidates (Amit 2026-10-16: "create your top 30 and make those as candidates").
    Skips names already in the book; raises if the book has no room. Returns the sids promoted."""
    from config import MB_THESIS
    from output import mb_book
    n = n or MB_THESIS["research_overlay"]["top_n"]
    o = overlay()
    top = o[o["research_rank"] <= n]
    have = {r["sid"] for r in db.rows("SELECT sid FROM multibagger_book WHERE status IN ('candidate', 'held')")}
    todo = [r for r in top.to_dict("records") if r["sid"] not in have]
    if dry_run:
        return [r["sid"] for r in todo]
    for r in todo:
        mb_book.add_candidate(
            r["sid"], (r["case_reason"] or r["verdict_reason"] or "Research-adjusted top 30")[:300],
            f"Research-adjusted rank {int(r['research_rank'])} of the thesis top 100 (thesis rank {int(r['thesis_rank'])}; "
            f"research {r['verdict']}, 5x case {r['multibagger_case']}, researched {r['as_of_date']}). Amit 2026-10-16: "
            "\"create your top 30 and make those as candidates\".", actor=actor)
    return [r["sid"] for r in todo]


def latest(sid):
    """The newest loaded research for one stock: {verdict, ..., fields (dict), report (str)} or None."""
    r = db.one("SELECT * FROM mb_research WHERE sid = ? ORDER BY as_of_date DESC LIMIT 1", [sid])
    if not r:
        return None
    return {**r, "fields": json.loads(r["fields"]), "report": r["report"]}


def status(sids):
    loaded = {r["sid"] for r in db.rows("SELECT DISTINCT sid FROM mb_research")} \
        if db.one("SELECT 1 AS x FROM sqlite_master WHERE name = 'mb_research'") else set()
    return [{"sid": s, "pack": (ROOT / s / "pack.md").exists(), "report": (ROOT / s / "report.md").exists(),
             "verdict": (ROOT / s / "verdict.json").exists(), "loaded": s in loaded} for s in sids]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--packs", action="store_true")
    ap.add_argument("--show")
    ap.add_argument("--load", action="store_true")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--sectors", action="store_true", help="write sector / sub_sector onto mb_research")
    ap.add_argument("--overlay", action="store_true", help="print the research-adjusted ranking")
    ap.add_argument("--promote", action="store_true", help="make the overlay's top 30 the candidates")
    ap.add_argument("--sids", help="comma-separated; default the thesis top 100")
    a = ap.parse_args()
    sids = a.sids.split(",") if a.sids else None
    if a.show:
        print(pack(a.show))
    elif a.packs:
        out = write_packs(sids or top100())
        print(f"{len(out)} packs, {min(out.values())}–{max(out.values())} bytes → {ROOT}")
    elif a.load:
        res = load(sids)
        bad = {k: v for k, v in res.items() if v}
        print(f"{len(res) - len(bad)} loaded, {len(bad)} rejected")
        for k, v in bad.items():
            print(f"  {k}: {'; '.join(v)}")
        if res and len(bad) == len(res):
            raise SystemExit(1)
    elif a.status:
        st = status(sids or top100())
        print(pd.DataFrame(st).to_string(index=False))
        print({k: sum(r[k] for r in st) for k in ("pack", "report", "verdict", "loaded")})
    elif a.sectors:
        missing = set_sectors()
        print("sectors written" + (f"; no entry in output/mb_sectors.py for: {missing}" if missing else ""))
    elif a.overlay:
        o = overlay()
        cols = ["research_rank", "thesis_rank", "ticker", "sector", "verdict", "multibagger_case", "thesis_score",
                "penalty", "bonus", "research_score"]
        print(o[cols].round(3).to_string(index=False))
    elif a.promote:
        print("promoted:", promote_top())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
