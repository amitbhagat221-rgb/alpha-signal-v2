"""
Alpha Signal v2 — Sector Narrative Fetcher (plan 0006)

Generates the per-sector structured narrative for the cockpit /sectors
deep-dive page. Uses Claude (Sonnet 4.6) with web search for fresh facts,
seeded with our local context (stocks in the sector + last-90d news headlines).

Fully automated; 0 hand-curation per the plan-0006 lock-in.

Reads:
    stocks                   (universe + sectors)
    news_articles            (recent themes per sector)
    fundamentals_screener    (top players' market cap rough check)

Writes:
    sector_metadata           (one row per sector, source='auto')
    sector_narrative_runs     (audit log)

Auth:
    ANTHROPIC_API_KEY in env (same as regulatory_classifier.py)

Usage:
    python -m tools.sector_narrative_fetcher                 # all sectors
    python -m tools.sector_narrative_fetcher --sector "Banking"   # single
    python -m tools.sector_narrative_fetcher --dry-run       # don't write
"""

import argparse
import json
import os
import time
from datetime import date, datetime

from db import get_db, read_sql

# Latest production-grade Claude with web-search; sector content is structured
# generation, not novel reasoning, so Sonnet over Opus for cost-efficiency.
SONNET_MODEL = "claude-sonnet-4-6"

# GICS sector → dominant IIM industry (legacy — kept for back-compat
# with sector-keyed runs; new runs default to the industry-level list below).
SECTOR_INDUSTRY_MAP = {
    "Energy":                  "Oil & Gas",
    "Materials":               "Cement",
    "Industrials":             "Logistics",
    "Consumer Discretionary":  "Retail",
    "Consumer Staples":        "FMCG",
    "Health Care":             "Pharmaceuticals",
    "Financials":              "Banking",
    "Information Technology":  "IT & ITeS",
    "Communication Services":  "Telecom",
    "Utilities":               "Utilities",
    "Real Estate":             "Real Estate",
}

# Full 25-industry list (matches tools/classify_industries.INDUSTRIES_BY_SECTOR).
# Default unit of work going forward.
INDUSTRY_LIST = [
    # Energy
    "Oil & Gas",
    # Materials
    "Cement", "Iron & Steel", "Chemicals & Specialty", "Mining & Minerals",
    "Paper, Wood & Forest Products",
    # Industrials
    "Capital Goods & Industrial Machinery", "Logistics & Transport", "Aviation",
    "Defence & Aerospace", "Construction & Engineering", "Industrial Services & Misc",
    # Consumer Discretionary
    "Automobiles", "Auto Components", "Hospitality & Hotels", "Retail",
    "E-Commerce", "Consumer Durables",
    # Consumer Staples
    "FMCG", "Food & Beverages", "Personal Care & Household Products",
    # Health Care
    "Pharmaceuticals", "Hospitals & Diagnostics", "Medical Devices",
    # Financials
    "Banks", "NBFCs / Finance", "Asset Management", "Insurance",
    "Capital Markets & Exchanges",
    # IT
    "IT Services & ITeS", "Software Products & SaaS",
    # Communication Services
    "Telecom", "Media & Entertainment",
    # Utilities
    "Power Generation", "Power T&D", "Gas Utilities",
    # Real Estate
    "Real Estate Developers", "REITs",
]


PROMPT_TEMPLATE = """You are a sector analyst building a structured Indian-equity sector narrative for a one-person hedge fund's research cockpit. The output drives a UI page that anyone should grok in 90 seconds.

GICS Sector: {sector}
Dominant industry: {industry}

Universe context (top stocks in this sector by market cap, from our DB):
{top_stocks}

Recent themes from our news_articles table (last 90 days, sample):
{news_sample}

Your task: search the web for the LATEST 2024-2025 information about this sector in India, then return a JSON object matching the exact schema below. Use authoritative sources (IBEF, sector reports, recent annual reports of top players, government / RBI / regulator announcements). Do NOT use stale 2020-2021 figures.

Required JSON schema (return EXACTLY this shape, no markdown, no commentary):
{{
  "summary": "one-sentence pitch — 25 words max — what this sector IS for Indian equities right now",
  "industry_size_inr_cr": <number — total industry size in ₹ crores, latest available>,
  "industry_cagr_pct": <number — projected forward CAGR>,
  "value_chain": [
    {{"name": "<stage 1>", "items": ["<sub-activity 1>", ..., "<sub-activity 6-10>"]}},
    {{"name": "<stage 2>", "items": [...]}},
    {{"name": "<stage 3>", "items": [...]}},
    {{"name": "<stage 4>", "items": [...]}},
    {{"name": "<stage 5>", "items": [...]}}
  ],
  "drivers": {{
    "revenue": [{{"item": "...", "type": "structural|cyclical|policy"}}, ... 4-6 items],
    "cost":    [{{"item": "...", "type": "..."}}, ... 4-6 items],
    "growth":  [{{"item": "...", "type": "..."}}, ... 4-6 items]
  }},
  "segments": [
    {{"name": "<segment 1>", "kpis": [
        {{"name": "<KPI>", "formula": "<plain English>", "direction": "higher_is_better|lower_is_better"}},
        ... 3-5 KPIs
    ]}},
    ... 5-8 segments
  ],
  "regulators": [
    {{"body": "<e.g. RBI>", "what": "<one line — what they regulate in this sector>"}},
    ... typically 2-4 regulators
  ],
  "competitive_landscape": {{
    "share_basis": "<what the share % represents — e.g. 'domestic passenger market share (DGCA)', 'revenue', 'AUM', 'subscriber base'>",
    "as_of": "<period — e.g. 'FY25', 'CY2024', 'Mar-2025'>",
    "players": [
      {{"name": "<company name as commonly known>", "ticker": "<NSE ticker if listed, else null>", "share_pct": <number 0-100>, "listed": <true|false>, "note": "<≤6 words — e.g. 'Tata Group', 'state-owned', 'subsidiary of X'>"}},
      ... 6-10 players covering AT LEAST 90% of industry by share, including BOTH listed and non-listed (private, PSU-unlisted, foreign subsidiaries) players. Order by share desc.
    ]
  }},
  "cyclicality": "<one paragraph — how cyclical is the sector, what's the cycle length, what drives it>",
  "india_specific": [
    "<bullet 1 — something that is uniquely true for THIS sector in INDIA>",
    "<bullet 2>",
    ... 4-6 bullets
  ],
  "trend_bullets": {{
    "industry_size":     ["<bullet on size + growth, with the latest number cited>"],
    "structural_shifts": ["<bullet 1>", "<bullet 2>", ... 2-3 bullets],
    "regulatory":        ["<bullet on the most consequential recent / upcoming regulatory move>"],
    "headwinds":         ["<bullet on the most-watched risk>", ...],
    "india_specific":    ["<bullet on India-specific tailwinds — UPI, Make-in-India, PLI, etc>", ...]
  }}
}}

Rules:
- Every field required. Output VALID JSON only — no markdown fences, no preamble.
- Numbers as JSON numbers (not strings).
- For Indian sectors with no obvious IBEF page (Utilities, Real Estate), construct from scratch using authoritative sources (CEA, MoP, NHB, etc).
- Industry size in ₹ crores; CAGR as a percent (e.g. 12.5 not 0.125).
- "value_chain" stages should reflect the ACTUAL flow of the sector — for Banking it's Marketing → Sales → Products → Transactions; for Pharma it's R&D → Testing → Approval → Distribution → Marketing; etc. Match what actually happens in this industry.
- "segments" should be how investors / analysts split the sector, with KPIs they actually use.
- "cyclicality" = one paragraph, plain English.
- "india_specific" should NOT repeat what's said in trend_bullets — make these structural / persistent factors, not news.
- "trend_bullets" should be FRESH (2024-2025 oriented), citing specific numbers and policies where possible.
- "competitive_landscape.players" MUST include private / unlisted majors — e.g. Air India in Aviation, BSNL in Telecom, NPCI in Payments, LIC's unlisted subsidiaries, IKEA, foreign banks, MNC unlisted arms. Set `listed: false` and `ticker: null` for these. The share_pct of all listed + unlisted players should reflect real industry concentration; do not normalise to 100% over listed-only.

Return ONLY the JSON object."""


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Run: source ~/alpha-signal/run_pipeline.sh"
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _top_stocks_for_key(key: str, by: str = "industry", n: int = 8) -> str:
    """Top stocks by market cap within `key`. by='industry' or 'sector'."""
    col = "industry" if by == "industry" else "sector"
    df = read_sql(
        f"SELECT ticker, name, market_cap_cr "
        f"FROM stocks "
        f"WHERE {col} = ? AND ticker IS NOT NULL "
        f"ORDER BY market_cap_cr DESC LIMIT ?",
        params=[key, n],
    )
    if df.empty:
        return f"(no stocks in our universe for this {by})"
    lines = []
    for _, r in df.iterrows():
        mcap_cr = r["market_cap_cr"] / 1e7
        lines.append(f"- {r['ticker']} ({r['name']}) — ₹{mcap_cr:,.0f} cr")
    return "\n".join(lines)


def _recent_news_for_key(key: str, by: str = "industry", n: int = 10) -> str:
    col = "industry" if by == "industry" else "sector"
    df = read_sql(
        f"""
        SELECT DISTINCT a.title, a.published_at
        FROM news_articles a
        JOIN news_article_stocks nas ON a.article_id = nas.article_id
        JOIN stocks s ON nas.sid = s.sid
        WHERE s.{col} = ?
          AND a.published_at >= date('now', '-90 days')
        ORDER BY a.published_at DESC
        LIMIT ?
        """,
        params=[key, n],
    )
    if df.empty:
        return f"(no recent news in our DB for this {by})"
    return "\n".join(
        f"- [{r['published_at'][:10]}] {r['title'][:140]}"
        for _, r in df.iterrows()
    )


def _extract_json_object(text: str):
    """Find the first balanced top-level JSON object in `text` and parse it.

    Handles all the ways Claude can wrap JSON despite being told not to:
      - "```json\\n{...}\\n```" fenced blocks
      - "Here is the JSON:\\n\\n{...}" preamble + raw JSON
      - "...preamble...\\n\\n```json\\n{...}\\n```\\n...trailing..." mixed
      - Raw JSON-only output (the happy path)

    Returns the parsed dict, or None if nothing parses.
    """
    # 1. Try parsing the whole text as JSON (happy path)
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass  # fall through to bracket-walk

    # 2. Try extracting from a ```json ... ``` (or plain ```) fence anywhere
    import re
    fence_match = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", text, re.DOTALL)
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. Bracket-walk: find first '{' and walk forward tracking string-escape
    #    state and brace depth to identify the matching close. Tolerates
    #    preamble text before and trailing text after.
    in_string = False
    escape = False
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if start < 0:
            if ch == "{":
                start = i
                depth = 1
            continue
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    # keep walking — there might be a later, valid object
                    start = -1
                    continue
    return None


def _validate_payload(payload: dict, sector: str) -> list:
    """Return a list of validation errors. Empty list = valid."""
    errors = []
    required_top = ["summary", "industry_size_inr_cr", "industry_cagr_pct",
                    "value_chain", "drivers", "segments", "regulators",
                    "cyclicality", "india_specific", "trend_bullets",
                    "competitive_landscape"]
    for k in required_top:
        if k not in payload:
            errors.append(f"missing top-level key: {k}")

    if "competitive_landscape" in payload:
        cl = payload["competitive_landscape"]
        if not isinstance(cl, dict):
            errors.append("competitive_landscape must be an object")
        else:
            if "players" not in cl or not isinstance(cl["players"], list) or len(cl["players"]) < 3:
                errors.append("competitive_landscape.players should be a list of ≥3 players")
            else:
                for i, pl in enumerate(cl["players"]):
                    for f in ("name", "share_pct", "listed"):
                        if f not in pl:
                            errors.append(f"competitive_landscape.players[{i}] missing '{f}'")

    if "value_chain" in payload:
        if not isinstance(payload["value_chain"], list) or len(payload["value_chain"]) < 4:
            errors.append("value_chain should be a list of ≥4 stages")
        else:
            for i, stage in enumerate(payload["value_chain"]):
                if "name" not in stage or "items" not in stage:
                    errors.append(f"value_chain[{i}] missing name/items")

    if "drivers" in payload:
        for kind in ("revenue", "cost", "growth"):
            if kind not in payload["drivers"]:
                errors.append(f"drivers missing '{kind}' bucket")

    if "segments" in payload:
        if not isinstance(payload["segments"], list) or len(payload["segments"]) < 2:
            errors.append("segments should be a list of ≥2 entries")

    if "trend_bullets" in payload:
        for kind in ("industry_size", "structural_shifts", "regulatory",
                     "headwinds", "india_specific"):
            if kind not in payload["trend_bullets"]:
                errors.append(f"trend_bullets missing '{kind}' bucket")

    return errors


def fetch_one(client, key: str, by: str = "industry", dry_run: bool = False) -> dict:
    """Fetch one industry's (or sector's) narrative. Returns parsed payload.

    `by='industry'`: looks up stocks/news by industry, prompt is industry-keyed.
    `by='sector'`: legacy sector-keyed flow.
    """
    if by == "industry":
        # When by-industry, the prompt's 'sector' slot becomes the industry name
        # and the 'industry' slot is the same (single label). The schema fields
        # in the output JSON are unaffected.
        sector_label = key
        industry_label = key
    else:
        sector_label = key
        industry_label = SECTOR_INDUSTRY_MAP.get(key, key)

    top_stocks = _top_stocks_for_key(key, by=by)
    news_sample = _recent_news_for_key(key, by=by)

    prompt = PROMPT_TEMPLATE.format(
        sector=sector_label,
        industry=industry_label,
        top_stocks=top_stocks,
        news_sample=news_sample,
    )

    print(f"  → Calling Claude for {key!r} ({by})…")
    resp = client.messages.create(
        model=SONNET_MODEL,
        max_tokens=8000,
        # Enable web search so Claude can cite latest sources
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
        }],
        messages=[{"role": "user", "content": prompt}],
    )

    # Extract the final text block (after any tool-use turns)
    text_parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
    text = (text_parts[-1] if text_parts else "").strip()

    payload = _extract_json_object(text)
    if payload is None:
        raise RuntimeError(
            f"Claude returned no parseable JSON for {key}.\n"
            f"First 600 chars:\n{text[:600]}"
        )

    errors = _validate_payload(payload, key)
    if errors:
        raise RuntimeError(
            f"Validation failed for {key}:\n  " + "\n  ".join(errors)
        )

    return payload


def save_payload(sector: str, industry: str, payload: dict, source: str = "auto"):
    """Upsert sector_metadata row."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO sector_metadata (sector, industry, source, generated_at, payload)
               VALUES (?, ?, ?, datetime('now'), ?)
               ON CONFLICT(sector, source) DO UPDATE SET
                 industry = excluded.industry,
                 generated_at = excluded.generated_at,
                 payload = excluded.payload""",
            (sector, industry, source, json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()


def _log_run(started_at: str, status: str, done: int, failed: int, detail: str = ""):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO sector_narrative_runs
                 (started_at, finished_at, status, sectors_done, sectors_failed, detail)
                 VALUES (?, datetime('now'), ?, ?, ?, ?)""",
            (started_at, status, done, failed, detail[:5000]),
        )
        conn.commit()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--industry", help="single industry name (e.g. 'Automobiles')")
    parser.add_argument("--sector", help="legacy: single sector name (e.g. 'Financials')")
    parser.add_argument("--dry-run", action="store_true", help="don't write to DB")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip keys with a recent (≤30 days) auto row")
    args = parser.parse_args()

    if args.industry:
        keys_to_fetch = [args.industry]
        by = "industry"
    elif args.sector:
        keys_to_fetch = [args.sector]
        by = "sector"
    else:
        keys_to_fetch = list(INDUSTRY_LIST)
        by = "industry"

    if args.skip_existing:
        existing = read_sql(
            "SELECT sector FROM sector_metadata "
            "WHERE source='auto' AND generated_at >= datetime('now', '-30 days')"
        )["sector"].tolist()
        before = len(keys_to_fetch)
        keys_to_fetch = [k for k in keys_to_fetch if k not in existing]
        print(f"  --skip-existing: {before} → {len(keys_to_fetch)} keys to fetch")

    print(f"Fetching narratives for {len(keys_to_fetch)} {by}(s)…\n")

    client = _get_client()
    started_at = datetime.now().isoformat(timespec="seconds")
    done = 0
    failed = 0
    failures = []

    for i, key in enumerate(keys_to_fetch, 1):
        # `industry_label` is the IIM industry hint stored on the row;
        # for industry-keyed runs, it's just the same string.
        industry_label = key if by == "industry" else SECTOR_INDUSTRY_MAP.get(key, key)
        print(f"[{i}/{len(keys_to_fetch)}] {key}")
        try:
            payload = fetch_one(client, key, by=by, dry_run=args.dry_run)
            if not args.dry_run:
                save_payload(key, industry_label, payload)
            print(f"  ✓ saved · summary: {payload['summary'][:80]}")
            done += 1
        except Exception as e:
            print(f"  ✗ FAILED: {type(e).__name__}: {str(e)[:200]}")
            failed += 1
            failures.append(f"{key}: {e}")
        if i < len(keys_to_fetch):
            time.sleep(1.0)

    status = "SUCCESS" if failed == 0 else ("PARTIAL" if done > 0 else "FAILED")
    detail = "\n".join(failures) if failures else ""
    if not args.dry_run:
        _log_run(started_at, status, done, failed, detail)

    print(f"\nDone. {done} saved, {failed} failed. Status: {status}")


if __name__ == "__main__":
    main()
