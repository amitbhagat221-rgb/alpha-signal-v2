"""
Alpha Signal v2 — industry explainer (narrative v2, plan 0016 P5)

The twelve-card "explain this industry to a newcomer" block that the Sectors ›
Industry Detail pane renders (docs/research/0013-industry-detail-merged-mockup.html
is the design; all 39 explainers are archived in docs/research/0013-industry-explainers.json, a deliberate exception to the repo-wide *.json ignore). One `explainer` object per industry, stored INSIDE the existing
sector_metadata payload (key `explainer`, plus `explainer_generated_at`), so the
v1 fields (value_chain, segments, competitive_landscape …) stay as they are.

Rule that makes it safe to read: prose fields carry NO raw numbers (an LLM
hallucinates plausible ones). Years and calendar tokens (2024, FY25, Q1, H2)
are fine. Numbers live only in structured fields that a reader can see are
illustrative (the ₹100 P&L walk, five-force scores, lead times) or that the
cockpit fills live (dial readings, cheat-sheet medians).

Auth: ANTHROPIC_API_KEY in env (same as tools/sector_narrative_fetcher.py).

Two routes (plan 0016 D1/D2: LLM work runs on the Claude subscription, the paid
API is the fallback):
    --print-prompt  writes the full prompt for one industry to stdout; a Claude Code
                    session (or a queue worker) answers it and saves the JSON to a file
    --ingest FILE   validates that file and merges it into sector_metadata
    (no flag)       the paid API with web search, when ANTHROPIC_API_KEY has credit

Usage:
    python -m tools.sector_explainer --industry "Chemicals & Specialty" --print-prompt > prompt.txt
    python -m tools.sector_explainer --industry "Chemicals & Specialty" --ingest chem.json
    python -m tools.sector_explainer --all --skip-existing --workers 4       # API route
    python -m tools.sector_explainer --missing                               # list industries without one
    python -m tools.sector_explainer --restore docs/research/0013-industry-explainers.json   # rebuild from the archive
"""

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import db
from hosts import HOSTS
from tools.sector_narrative_fetcher import (
    INDUSTRY_LIST, _extract_json_object, _get_client, _top_stocks_for_key,
    _recent_news_for_key, _log_run,
)

MODEL = HOSTS["anthropic"]["models"]["sector_narrative"]

# Cheat-sheet metrics the cockpit can fill from fundamentals_screener medians
# (cockpit/explainer.py: industry_financial_medians). The LLM picks from these keys.
METRIC_KEYS = {
    "gross_margin_pct":   "gross margin % = (sales − raw material cost) / sales",
    "ebitda_margin_pct":  "operating profit / sales, %",
    "net_margin_pct":     "net profit / sales, %",
    "inventory_days":     "inventory / sales × 365",
    "receivable_days":    "receivables / sales × 365",
    "capex_to_dep":       "change in gross block / depreciation",
    "asset_turn":         "sales / net block",
    "cwip_to_gross_block": "capital work in progress / gross block, %",
    "roce_pct":           "(profit before tax + interest) / (equity + reserves + borrowings), %",
    "debt_to_ebitda":     "borrowings / operating profit",
    "power_fuel_pct":     "power and fuel / sales, %",
    "employee_cost_pct":  "employee cost / sales, %",
    "interest_to_ebitda_pct": "interest / operating profit, %",
    "sales_growth_pct":   "sales growth vs prior year, %",
}

# Macro indicators the cockpit already holds (macro_history). The LLM maps a dial
# to one of these ids or null; the pane shows the latest value for mapped dials.
INDICATOR_IDS = [
    "brent_crude", "usdinr", "us_10y", "india_money_rate", "india_vix", "gold", "silver",
    "copper", "aluminium", "nifty50", "bank_nifty", "nifty_auto", "nifty_energy",
    "nifty_fmcg", "nifty_infra", "nifty_it", "nifty_media", "nifty_metal", "nifty_pharma",
    "nifty_psubank", "nifty_realty", "gsec10_etf", "credit_excess_idx",
    "iip_general", "iip_manufacturing", "iip_mining", "iip_electricity", "iip_capital_goods",
    "iip_consumer_durables", "iip_consumer_nondurables", "iip_infrastructure_goods",
    "iip_intermediate_goods", "iip_primary_goods",
    "core_combined", "core_cement", "core_coal", "core_crude_oil", "core_natural_gas",
    "core_electricity", "core_fertilizers", "core_iron_ore", "core_refinery", "core_steel",
    "cpi_general", "cpi_food_beverages", "cpi_housing_fuel", "cpi_transport", "cpi_health",
    "cpi_clothing_footwear", "cpi_education", "cpi_household", "cpi_recreation",
    "india_exports", "india_imports",
]

PROMPT = """You are writing the plain-words explainer for ONE Indian stock-market industry, for a reader who knows nothing about it and wants to come out fluent: what it does, how a rupee becomes profit, where the cycle is, which macro dials move it, what the rules are, who keeps the profit, which numbers to read in a results call, and what to watch to predict its direction. Write like Finshots: short sentences, one idea each, concrete, no jargon without a definition. Everything must be true for INDIA and for this industry specifically.

Industry: {industry}
Parent sector: {sector}
Listed names in this industry, largest first (ticker · name · market cap ₹ crore), from our database:
{top_stocks}
Recent headlines from our news table (last 90 days):
{news_sample}
The written story we already hold for this industry (for consistency; do not repeat it verbatim):
  one-line summary: {v1_summary}
  value-chain stages: {v1_stages}
  segments: {v1_segments}
  regulators: {v1_regulators}

Search the web for what has happened to this industry in India from 2019 to today (cycle, policy, China or other foreign competition, the latest results season) before writing. Today is {today}.

THE ONE HARD RULE: prose fields carry NO digits except years (2019, 2024) and calendar tokens (FY25, Q1, H2). Say "a third", "roughly half", "double", "high twenties" instead of numbers. Numbers are allowed ONLY in: pnl.walk (an illustrative ₹100 walk), forces.scores, dials.weight, lead_indicators.lead_quarters, clock.phases.years, clock.timeline.when, cheat_sheet.good, glossary definitions. A prose field with a stray digit fails validation.

Return EXACTLY this JSON (no markdown fences, no preamble):
{{
  "one_liner": "<one sentence, what the industry does, the tea-stall version>",
  "doors": [
    {{"name": "<business type 1>", "sub": "<how it is sold / how it makes money, one line>", "examples": ["<ticker from the list above>", ...1-4], "profit_kept": "low|medium|high", "blurb": "<one line: what a stock of this type is a bet on>"}},
    ... 2 to 4 doors: the distinct business models inside this industry (e.g. commodity vs specialty vs contract; or retail vs corporate vs ...). Every industry has at least two.
  ],
  "door_analogy": "<one or two sentences, an everyday analogy for the doors>",
  "door_so_what": "<one sentence: so what for the stock>",
  "kitchen": {{
    "stations": [{{"name": "<stage>", "what": "<what happens here, one line>", "who": "<who stands here: Indian companies from the list, PSUs, importers, or the foreign rival>"}}, ... exactly 5, upstream to the final customer],
    "bands": [{{"label": "<≤3 words: who holds this station>", "kind": "india|rival|other"}}, ... exactly 5, one per station; kind=india where Indian LISTED names stand, rival where the dominant foreign competitor stands, other elsewhere],
    "rival": "<the dominant foreign competitor or cost benchmark for this industry, e.g. China, or null if none>",
    "note": "<one or two sentences: geography, clusters, where the cost lines are>",
    "so_what": "<one sentence>"
  }},
  "end_markets": [{{"name": "<customer industry or buyer>", "buys": "<what it buys>", "moves_with": "<the one or two things that move that buyer>"}}, ... 6 to 8],
  "end_markets_so_what": "<one sentence>",
  "pnl": {{
    "walk": {{
      "input_label": "<the biggest input cost line for this industry, e.g. Raw materials, Interest paid, Fuel, Content cost>",
      "opex_label": "<the running-cost line, e.g. Power, people, freight>",
      "a": {{"name": "<door A name>", "input": <0-90>, "opex": <0-60>, "dep_int": <0-30>}},
      "b": {{"name": "<door B name>", "input": <0-90>, "opex": <0-60>, "dep_int": <0-30>}}
    }},
    "lines": [{{"line": "<P&L or balance-sheet line>", "matters": "yes|some|no", "why": "<one line>"}}, ... 6 to 8: always include Depreciation, Capex / asset turn, Working capital, Interest; mark honestly],
    "analogy": "<one or two sentences>",
    "so_what": "<one sentence>"
  }},
  "clock": {{
    "is_cyclical": "<one or two sentences: cyclical or not, what the cycle is tied to>",
    "phases": [{{"name": "Boom|Peak|Bust|Bottom", "years": "<e.g. 2020–22>", "what": "<one line>"}}, ... exactly 4 in order Boom, Peak, Bust, Bottom, describing the LAST full cycle in this industry],
    "position": "bottom|early_up|boom|peak|early_down|bust",
    "position_label": "<≤4 words, e.g. early up-cycle>",
    "position_detail": "<≤8 words, e.g. volumes back, prices capped>",
    "timeline": [{{"when": "<year or range>", "what": "<one or two sentences>", "tone": "boom|bust|neutral|now"}}, ... 5 to 7 entries from 2019 to today, the last one tone=now],
    "hands": [{{"name": "<what to watch>", "reading": "<≤4 words, current reading>", "tone": "up|down|flat|mixed", "meaning": "<what a change means>"}}, ... exactly 4],
    "so_what": "<one sentence>"
  }},
  "dials": [{{"name": "<macro or geopolitical dial>", "channel": "<through what it acts>", "rise_does": "<what a RISE in the dial does to this industry, ≤10 words>", "direction": "up|down|mixed", "weight": <1-3>, "indicator_id": "<one of: {indicator_ids} or null>"}}, ... 8 to 10, most important first],
  "dials_so_what": "<one sentence: the two dials to track if you track only two>",
  "bottlenecks": [{{"name": "<≤5 words>", "why": "<one or two sentences>", "severity": "structural|recurring|cyclical|two-sided|slow"}}, ... 5 to 8, including India-specific quirks],
  "bottlenecks_so_what": "<one sentence>",
  "rulebook": [{{"body": "<regulator or rule>", "what": "<what it does>", "why": "<why an investor cares>", "status": "always|live|new|coming"}}, ... 6 to 9],
  "regulatory_keywords": ["<lowercase word or phrase that identifies a news headline as being about THIS industry rather than its parent sector>", ... 10 to 20],
  "forces": {{
    "a_name": "<door A>", "b_name": "<door B or 'the rest'>",
    "scores": {{"rivalry": [<a 0-3>, <b 0-3>], "supplier": [a, b], "buyer": [a, b], "entrants": [a, b], "substitutes": [a, b]}},
    "why": {{"rivalry": "<one line>", "supplier": "<one line>", "buyer": "<one line>", "entrants": "<one line>", "substitutes": "<one line>"}},
    "so_what": "<one sentence: who keeps the profit>"
  }},
  "cheat_sheet": [{{"metric": "<number to read every quarter>", "tells": "<what it tells you>", "good": "<what good looks like, numbers allowed>", "metric_key": "<one of: {metric_keys} or null>"}}, ... exactly 8],
  "lead_indicators": [{{"name": "<signal from outside the industry>", "lead_quarters": <0|1|2|3>, "channel": "<how it reaches this industry's earnings>"}}, ... 6 to 8],
  "rule": {{"text": "<one sentence: the up-cycle rule, three signs>", "signs": [{{"name": "<sign>", "ok": <true|false>, "note": "<≤6 words, current state>"}}, ... exactly 3]}},
  "call": {{"headline": "<one or two sentences: the directional call today and what to prefer>", "points": ["<supporting point>", ... 2 to 3], "would_change": ["<what would flip the call>", ... 2 to 3]}},
  "tell_a_friend": "<the sixty-second version, 120 to 170 words, one paragraph, no digits except years>",
  "glossary": [{{"term": "<term used above>", "def": "<one line, plain words>"}}, ... 12 to 25: every piece of jargon used anywhere above]
}}

Checks before you answer: every "examples" ticker is in the list above; the pnl walk numbers sum to less than 100 for each door; the four phases are in order; exactly 4 hands, exactly 3 signs, exactly 8 cheat-sheet rows, exactly 5 stations and 5 bands; no digits in prose. Return ONLY the JSON object."""

# ── validation ────────────────────────────────────────────────────────────────

_ALLOWED_TOKENS = re.compile(r"\b(19|20)\d\d(s)?\b|\bFY\s?\d\d(\d\d)?\b|\b[QH][1-4]\b|\bCY\d\d(\d\d)?\b|\b\d\d?(st|nd|rd|th)\b|\bCOVID-19\b|\bG20\b|\bH1N1\b|\b5G\b|\b4G\b|\b3G\b|\bEV\d?\b|\bBS-?VI\b|\bBS-?IV\b|\bNifty ?50\b|\bNifty ?500\b|\bTop ?\d+\b|\bChina\+1\b|\bTier[- ]?[123I]+\b|\bPM2\.5\b|\bScope ?[123]\b|\bB2[BCG]\b|\b[1-5]PL\b|\bL1\b|\bH-1B\b|\bP2P\b|\bO2O\b|\bD2C\b|\bTier-?[12]\b", re.I)


def prose_digits(text):
    """Digits left in a prose string after removing years and calendar tokens.
    Returns the offending fragments (empty list = clean)."""
    if not isinstance(text, str):
        return []
    cleaned = _ALLOWED_TOKENS.sub(" ", text)
    return re.findall(r"\S*\d\S*", cleaned)


def _walk(node, path=""):
    """Yield (path, value) for every string leaf in a nested dict/list."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


# string fields where digits are allowed (structured, not prose)
_NUMERIC_OK = re.compile(
    r"^(clock\.phases\[\d+\]\.years|clock\.timeline\[\d+\]\.when|cheat_sheet\[\d+\]\.(good|metric_key)"
    r"|glossary\[\d+\]\.(def|term)|dials\[\d+\]\.indicator_id|doors\[\d+\]\.examples\[\d+\]"
    r"|regulatory_keywords\[\d+\]|kitchen\.bands\[\d+\]\.label|forces\.(a_name|b_name)"
    r"|pnl\.walk\.(a|b)\.name|pnl\.walk\.(input_label|opex_label))$"
)


def validate_explainer(ex, tickers=None):
    """Return a list of errors (empty = valid)."""
    errs = []
    if not isinstance(ex, dict):
        return ["explainer is not an object"]
    req = ["one_liner", "doors", "door_analogy", "door_so_what", "kitchen", "end_markets",
           "pnl", "clock", "dials", "bottlenecks", "rulebook", "regulatory_keywords", "forces",
           "cheat_sheet", "lead_indicators", "rule", "call", "tell_a_friend", "glossary"]
    for k in req:
        if k not in ex:
            errs.append(f"missing key: {k}")
    if errs:
        return errs

    def count(name, lst, lo, hi):
        if not isinstance(lst, list) or not (lo <= len(lst) <= hi):
            errs.append(f"{name}: expected {lo}-{hi} items, got {len(lst) if isinstance(lst, list) else type(lst).__name__}")

    count("doors", ex["doors"], 2, 4)
    count("kitchen.stations", ex["kitchen"].get("stations", []), 5, 5)
    count("kitchen.bands", ex["kitchen"].get("bands", []), 5, 5)
    count("end_markets", ex["end_markets"], 5, 9)
    count("pnl.lines", ex["pnl"].get("lines", []), 5, 9)
    count("clock.phases", ex["clock"].get("phases", []), 4, 4)
    count("clock.timeline", ex["clock"].get("timeline", []), 4, 8)
    count("clock.hands", ex["clock"].get("hands", []), 4, 4)
    count("dials", ex["dials"], 6, 11)
    count("bottlenecks", ex["bottlenecks"], 4, 9)
    count("rulebook", ex["rulebook"], 5, 10)
    count("regulatory_keywords", ex["regulatory_keywords"], 6, 25)
    count("cheat_sheet", ex["cheat_sheet"], 7, 9)
    count("lead_indicators", ex["lead_indicators"], 5, 9)
    count("rule.signs", ex["rule"].get("signs", []), 3, 3)
    count("glossary", ex["glossary"], 10, 30)

    for side in ("a", "b"):
        w = (ex["pnl"].get("walk") or {}).get(side) or {}
        try:
            tot = float(w.get("input", 0)) + float(w.get("opex", 0)) + float(w.get("dep_int", 0))
            if not (0 < tot < 100):
                errs.append(f"pnl.walk.{side}: input+opex+dep_int must be between 0 and 100, got {tot}")
        except (TypeError, ValueError):
            errs.append(f"pnl.walk.{side}: non-numeric values")

    pos = ex["clock"].get("position")
    if pos not in ("bottom", "early_up", "boom", "peak", "early_down", "bust"):
        errs.append(f"clock.position invalid: {pos!r}")
    phases = [p.get("name", "").lower() for p in ex["clock"].get("phases", [])]
    if phases and phases != ["boom", "peak", "bust", "bottom"]:
        errs.append(f"clock.phases must be Boom, Peak, Bust, Bottom in order, got {phases}")

    sc = (ex["forces"].get("scores") or {})
    for f in ("rivalry", "supplier", "buyer", "entrants", "substitutes"):
        v = sc.get(f)
        if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and 0 <= x <= 3 for x in v)):
            errs.append(f"forces.scores.{f} must be [a, b] in 0..3")

    for i, d in enumerate(ex["dials"]):
        iid = d.get("indicator_id")
        if iid not in (None, "") and iid not in INDICATOR_IDS:
            errs.append(f"dials[{i}].indicator_id unknown: {iid}")
        if d.get("direction") not in ("up", "down", "mixed"):
            errs.append(f"dials[{i}].direction invalid")
    for i, c in enumerate(ex["cheat_sheet"]):
        mk = c.get("metric_key")
        if mk not in (None, "") and mk not in METRIC_KEYS:
            errs.append(f"cheat_sheet[{i}].metric_key unknown: {mk}")
    if tickers:
        tset = set(tickers)
        for i, d in enumerate(ex["doors"]):
            bad = [t for t in d.get("examples", []) if t not in tset]
            if bad:
                errs.append(f"doors[{i}].examples not in the industry: {bad}")

    words = len((ex.get("tell_a_friend") or "").split())
    if not (80 <= words <= 230):
        errs.append(f"tell_a_friend should be 120-170 words, got {words}")

    # the hard rule: no digits in prose
    for path, s in _walk(ex):
        if _NUMERIC_OK.match(path):
            continue
        bad = prose_digits(s)
        if bad:
            errs.append(f"digits in prose at {path}: {bad[:3]}")
    return errs


# ── the long-form layer (Amit 2026-10-17: "prose too thin … diagrams explained in a very detailed way") ──
# ex["deep"][card] = {"story": html, "read": html}: the story before the card's diagram, how to read it after.
# Card 12 (tell a friend) keeps its sixty-second version. Same hard rule: no digits except years.
DEEP_CARDS = {"c1": "doors", "c2": "kitchen", "c3": "who buys", "c4": "rupee to profit", "c5": "the clock",
              "c6": "wiring diagram", "c7": "bottlenecks", "c8": "rulebook", "c9": "five forces",
              "c10": "results-call cheat sheet", "c11": "cross-intelligence and the call"}
DEEP_TAGS = {"p", "b", "strong", "em", "i", "ul", "ol", "li", "blockquote", "br"}
DEEP_MIN_WORDS = {"story": 180, "read": 110}


def validate_deep(deep):
    """Errors in the long-form layer (empty = valid)."""
    if not isinstance(deep, dict):
        return ["deep is not an object"]
    errs = []
    for card in DEEP_CARDS:
        d = deep.get(card)
        if not isinstance(d, dict):
            errs.append(f"deep.{card}: missing")
            continue
        for part, need in DEEP_MIN_WORDS.items():
            html = d.get(part)
            if not isinstance(html, str) or not html.strip():
                errs.append(f"deep.{card}.{part}: missing")
                continue
            bad_tags = {t.lower() for t in re.findall(r"</?([a-zA-Z0-9]+)\b", html)} - DEEP_TAGS
            if bad_tags:
                errs.append(f"deep.{card}.{part}: tags not allowed {sorted(bad_tags)}")
            text = re.sub(r"<[^>]+>", " ", html)
            if len(text.split()) < need:
                errs.append(f"deep.{card}.{part}: {len(text.split())} words, at least {need}")
            if prose_digits(text):
                errs.append(f"deep.{card}.{part}: digits in prose {prose_digits(text)[:3]}")
    extra = set(deep) - set(DEEP_CARDS)
    if extra:
        errs.append(f"deep: unknown cards {sorted(extra)}")
    return errs


def ingest_deep(industry, deep):
    """Merge a validated long-form layer into the industry's current explainer and save it (archived)."""
    errs = validate_deep(deep)
    if errs:
        raise ValueError(f"{industry}: " + "; ".join(errs[:10]))
    row = db.one("SELECT payload FROM sector_metadata WHERE sector = ? AND source = 'auto'", [industry])
    ex = (json.loads(row["payload"]) if row else {}).get("explainer")
    if not ex:
        raise ValueError(f"{industry}: no explainer to extend")
    ex = {**ex, "deep": deep}
    errs = validate_explainer(ex)
    if errs:
        raise ValueError(f"{industry}: " + "; ".join(errs[:10]))
    save_explainer(industry, ex)


# ── generation ────────────────────────────────────────────────────────────────

def _v1_payload(industry):
    row = db.one("SELECT payload FROM sector_metadata WHERE sector = ? "
                 "ORDER BY CASE source WHEN 'manual' THEN 0 ELSE 1 END, generated_at DESC LIMIT 1",
                 [industry])
    if not row:
        return {}
    try:
        return json.loads(row["payload"])
    except (TypeError, json.JSONDecodeError):
        return {}


def _tickers(industry, n=40):
    rows = db.rows("SELECT ticker FROM stocks WHERE industry = ? ORDER BY market_cap_cr DESC LIMIT ?",
                   [industry, n])
    return [r["ticker"] for r in rows]


def build_prompt(industry, sector, v1):
    return PROMPT.format(
        industry=industry, sector=sector or "—",
        top_stocks=_top_stocks_for_key(industry, by="industry", n=15),
        news_sample=_recent_news_for_key(industry, by="industry", n=8),
        v1_summary=v1.get("summary", "—"),
        v1_stages=", ".join(s.get("name", "") for s in v1.get("value_chain", [])) or "—",
        v1_segments=", ".join(s.get("name", "") for s in v1.get("segments", [])) or "—",
        v1_regulators=", ".join(r.get("body", "") for r in v1.get("regulators", [])) or "—",
        today=datetime.now().strftime("%Y-%m-%d"),
        indicator_ids=", ".join(INDICATOR_IDS),
        metric_keys=", ".join(f"{k} ({v})" for k, v in METRIC_KEYS.items()),
    )


def fetch_explainer(client, industry, retries=1, log=print):
    """One industry → validated explainer dict. One retry with the validator's
    errors appended to the prompt. Raises on failure."""
    sector = db.scalar("SELECT sector FROM stocks WHERE industry = ? GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 1",
                       [industry])
    v1 = _v1_payload(industry)
    tickers = _tickers(industry)
    prompt = build_prompt(industry, sector, v1)
    feedback = ""
    last_err = None
    for attempt in range(retries + 1):
        log(f"  → {industry}: call {attempt + 1}")
        resp = client.messages.create(
            model=MODEL, max_tokens=16000,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 6}],
            messages=[{"role": "user", "content": prompt + feedback}],
        )
        text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        text = (text_parts[-1] if text_parts else "").strip()
        ex = _extract_json_object(text)
        if ex is None:
            last_err = f"no parseable JSON (first 300 chars: {text[:300]!r})"
        else:
            errs = validate_explainer(ex, tickers)
            if not errs:
                usage = getattr(resp, "usage", None)
                if usage:
                    ex["_usage"] = {"in": usage.input_tokens, "out": usage.output_tokens}
                return ex
            last_err = "; ".join(errs[:12])
        feedback = ("\n\nYour previous answer failed validation with these errors; fix every one and return the full JSON again:\n- "
                    + last_err.replace("; ", "\n- "))
        log(f"  ✗ {industry}: {last_err[:300]}")
    raise RuntimeError(f"{industry}: {last_err}")


def save_explainer(industry, ex):
    """Merge the explainer into the industry's auto narrative row (keeps v1 fields).
    Creates a minimal row when the industry has no narrative yet."""
    usage = ex.pop("_usage", None)
    with db.get_db() as conn:
        row = conn.execute("SELECT payload, industry FROM sector_metadata WHERE sector = ? AND source = 'auto'",
                           [industry]).fetchone()
        payload = {}
        if row:
            try:
                payload = json.loads(row[0])
            except (TypeError, json.JSONDecodeError):
                payload = {}
        payload["explainer"] = ex
        payload["explainer_generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if usage:
            payload["explainer_usage"] = usage
        # every version is also kept in the dated archive (plan 0028): sector_metadata holds the current one only
        from output import desk_archive
        desk_archive.save("industry_explainer", ex, payload["explainer_generated_at"][:10], item=industry, method="manual", conn=conn)
        if row:
            conn.execute("UPDATE sector_metadata SET payload = ? WHERE sector = ? AND source = 'auto'",
                         [json.dumps(payload, ensure_ascii=False), industry])
        else:
            conn.execute("INSERT INTO sector_metadata (sector, industry, source, generated_at, payload) "
                         "VALUES (?, ?, 'auto', datetime('now'), ?)",
                         [industry, industry, json.dumps(payload, ensure_ascii=False)])
        conn.commit()


def industries_without_explainer(keys):
    have = {r["sector"] for r in db.rows(
        "SELECT sector FROM sector_metadata WHERE source = 'auto' AND payload LIKE '%\"explainer\":%'")}
    return [k for k in keys if k not in have]


def main(argv=None):
    ap = argparse.ArgumentParser(description="industry explainer (narrative v2)")
    ap.add_argument("--industry", action="append", help="industry name; repeatable")
    ap.add_argument("--all", action="store_true", help="every industry in INDUSTRY_LIST")
    ap.add_argument("--skip-existing", action="store_true", help="skip industries that already have an explainer")
    ap.add_argument("--ingest-deep", metavar="FILE", help="merge a long-form layer {card: {story, read}} into --industry's explainer")
    ap.add_argument("--check-deep", metavar="FILE", help="validate a long-form layer file without saving")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true", help="print the JSON, do not write")
    ap.add_argument("--print-prompt", action="store_true", help="print the prompt for --industry and exit")
    ap.add_argument("--ingest", metavar="FILE", help="validate FILE (a JSON explainer) for --industry and save it")
    ap.add_argument("--missing", action="store_true", help="list industries without an explainer and exit")
    ap.add_argument("--restore", metavar="ARCHIVE",
                    help="re-ingest every industry from an archive (docs/research/0013-industry-explainers.json)")
    args = ap.parse_args(argv)

    if args.restore:
        with open(args.restore, encoding="utf-8") as fh:
            arch = json.load(fh)
        n_ok = 0
        for industry, rec in arch.items():
            errs = validate_explainer(rec["explainer"], _tickers(industry))
            if errs:
                print(f"  ✗ {industry}: {errs[:2]}")
                continue
            if not args.dry_run:
                save_explainer(industry, dict(rec["explainer"]))
            n_ok += 1
        print(f"restored {n_ok} of {len(arch)}{' (dry run)' if args.dry_run else ''}")
        return 0 if n_ok == len(arch) else 1

    if args.check_deep or args.ingest_deep:
        with open(args.check_deep or args.ingest_deep, encoding="utf-8") as fh:
            deep = json.load(fh)
        if args.check_deep:
            errs = validate_deep(deep)
            words = sum(len(re.sub(r"<[^>]+>", " ", d.get(p, "")).split()) for d in deep.values() if isinstance(d, dict) for p in ("story", "read"))
            print("\n".join(f"  ✗ {e}" for e in errs) if errs else f"  ✓ valid, {words} words")
            return 1 if errs else 0
        if not args.industry or len(args.industry) != 1:
            ap.error("--ingest-deep takes exactly one --industry")
        ingest_deep(args.industry[0], deep)
        print(f"  ✓ {args.industry[0]}: long-form layer saved")
        return 0

    if args.missing:
        for k in industries_without_explainer(INDUSTRY_LIST):
            print(k)
        return 0
    if args.print_prompt or args.ingest:
        if not args.industry or len(args.industry) != 1:
            ap.error("--print-prompt / --ingest take exactly one --industry")
        industry = args.industry[0]
        if args.print_prompt:
            sector = db.scalar("SELECT sector FROM stocks WHERE industry = ? GROUP BY sector ORDER BY COUNT(*) DESC LIMIT 1", [industry])
            print(build_prompt(industry, sector, _v1_payload(industry)))
            return 0
        with open(args.ingest, encoding="utf-8") as fh:
            ex = _extract_json_object(fh.read())
        if ex is None:
            print("no parseable JSON object in the file")
            return 1
        errs = validate_explainer(ex, _tickers(industry))
        if errs:
            print(f"INVALID ({len(errs)} errors):")
            for e in errs:
                print("  -", e)
            return 1
        if args.dry_run:
            print("valid (dry run, not saved)")
            return 0
        save_explainer(industry, ex)
        print(f"saved explainer for {industry}")
        return 0

    keys = list(args.industry or [])
    if args.all:
        keys = list(INDUSTRY_LIST)
    if not keys:
        ap.error("give --industry NAME or --all")
    if args.skip_existing:
        before = len(keys)
        keys = industries_without_explainer(keys)
        print(f"--skip-existing: {before} → {len(keys)}")
    if not keys:
        print("nothing to do")
        return 0

    client = _get_client()
    started = datetime.now().isoformat(timespec="seconds")
    done, failed, failures = 0, 0, []
    t0 = time.time()

    def work(k):
        ex = fetch_explainer(client, k)
        if args.dry_run:
            print(json.dumps(ex, ensure_ascii=False, indent=1)[:4000])
        else:
            save_explainer(k, ex)
        return k

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(work, k): k for k in keys}
        for f in as_completed(futs):
            k = futs[f]
            try:
                f.result()
                done += 1
                print(f"  ✓ {k}  ({done + failed}/{len(keys)}, {time.time() - t0:.0f}s)", flush=True)
            except Exception as e:  # one industry failing must not stop the rest
                failed += 1
                failures.append(f"{k}: {e}")
                print(f"  ✗ {k}: {str(e)[:300]}", flush=True)

    status = "SUCCESS" if failed == 0 else ("PARTIAL" if done else "FAILED")
    if not args.dry_run:
        _log_run(started, status, done, failed, "explainer\n" + "\n".join(failures))
    print(f"\n{status}: {done} saved, {failed} failed, {time.time() - t0:.0f}s")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
