"""
Alpha Signal v2 — Industry classifier (plan-0006 follow-up)

Populates `stocks.industry` with IIM-casebook-style granularity. GICS sectors
are too coarse for Indian-market analysis — "Consumer Discretionary" lumps
Maruti, Indian Hotels, Trent, and Zomato together. We classify each stock
into one of ~25 industries that match how Indian analysts actually think
about the market.

Uses Claude Haiku for cost — task is closed-set classification (pick one
from a fixed list), not novel reasoning.

Inputs:
    stocks                  (sid, ticker, name, sector)
    ANTHROPIC_API_KEY       env var (load via run_pipeline.sh)

Writes back:
    stocks.industry         one of the 25-industry list

Usage:
    python -m tools.classify_industries                 # all stocks
    python -m tools.classify_industries --sector "Consumer Discretionary"
    python -m tools.classify_industries --dry-run       # don't write
    python -m tools.classify_industries --limit 50      # smoke test
"""

import argparse
import json
import os
import time
from datetime import datetime

from db import get_db, read_sql

HAIKU_MODEL = "claude-haiku-4-5-20251001"
BATCH_SIZE = 25       # stocks per Haiku call — small payload, ~1 token / stock

# Industry taxonomy: 25 industries grouped under 11 GICS sectors.
# Aligned to IIM casebook industries + Indian-market common-sense splits.
# Each industry must belong to exactly one sector — keeps drill-down sane.
INDUSTRIES_BY_SECTOR = {
    "Energy": [
        "Oil & Gas",
    ],
    "Materials": [
        "Cement",
        "Iron & Steel",
        "Chemicals & Specialty",
        "Mining & Minerals",
        "Paper, Wood & Forest Products",
    ],
    "Industrials": [
        "Capital Goods & Industrial Machinery",
        "Logistics & Transport",
        "Aviation",
        "Defence & Aerospace",
        "Construction & Engineering",
        "Industrial Services & Misc",
    ],
    "Consumer Discretionary": [
        "Automobiles",
        "Auto Components",
        "Hospitality & Hotels",
        "Retail",
        "E-Commerce",
        "Consumer Durables",
    ],
    "Consumer Staples": [
        "FMCG",
        "Food & Beverages",
        "Personal Care & Household Products",
    ],
    "Health Care": [
        "Pharmaceuticals",
        "Hospitals & Diagnostics",
        "Medical Devices",
    ],
    "Financials": [
        "Banks",
        "NBFCs / Finance",
        "Asset Management",
        "Insurance",
        "Capital Markets & Exchanges",
    ],
    "Information Technology": [
        "IT Services & ITeS",
        "Software Products & SaaS",
    ],
    "Communication Services": [
        "Telecom",
        "Media & Entertainment",
    ],
    "Utilities": [
        "Power Generation",
        "Power T&D",
        "Gas Utilities",
    ],
    "Real Estate": [
        "Real Estate Developers",
        "REITs",
    ],
}

# Flatten for validation
ALL_INDUSTRIES = {ind: sec for sec, inds in INDUSTRIES_BY_SECTOR.items() for ind in inds}


def _get_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Run: source ~/alpha-signal/run_pipeline.sh"
        )
    import anthropic
    return anthropic.Anthropic(api_key=api_key)


def _build_prompt(stocks_batch, sector):
    """Build the Haiku prompt: bucket each stock into one of the sector's industries."""
    industries = INDUSTRIES_BY_SECTOR.get(sector, [])
    industries_str = "\n".join(f"  - {ind}" for ind in industries)

    rows = "\n".join(
        f"{i+1}. {s['ticker']} — {s['name']}"
        for i, s in enumerate(stocks_batch)
    )

    return f"""You are classifying Indian stocks into industries.

Sector: {sector}
Allowed industries (pick exactly one per stock):
{industries_str}

Stocks to classify:
{rows}

Return ONLY a JSON array of {{"ticker": "...", "industry": "..."}} objects, in the same order.
- The "industry" field MUST exactly match one of the allowed industries listed above.
- For ambiguous companies, pick the industry that captures their primary revenue source.
- Holding companies / conglomerates: classify by the operating business with the largest revenue contribution.
- No commentary. No markdown fences. Just the JSON array."""


def _build_prompt_from_scratch(stocks_batch):
    """Pick from ALL 25 industries — used when we don't trust the input sector
    tag (platform companies wrongly bucketed as Communication Services, etc).
    The chosen industry's parent sector overwrites stocks.sector too."""
    lines = []
    for sec, inds in INDUSTRIES_BY_SECTOR.items():
        lines.append(f"  [{sec}]")
        for ind in inds:
            lines.append(f"    - {ind}")
    industries_str = "\n".join(lines)

    rows = "\n".join(
        f"{i+1}. {s['ticker']} — {s['name']}"
        for i, s in enumerate(stocks_batch)
    )

    return f"""You are classifying Indian stocks into industries. The GICS sector tag in our database is sometimes wrong (especially for platform companies — Zomato, Swiggy, Paytm, Naukri are wrongly filed under Communication Services). Ignore any prior sector tag and pick the most accurate industry from the full list below.

All allowed industries (grouped by sector for context — pick exactly one industry per stock):
{industries_str}

Stocks to classify:
{rows}

Return ONLY a JSON array of {{"ticker": "...", "industry": "..."}} objects, in the same order.
- The "industry" field MUST exactly match one industry name from the list above (e.g. "E-Commerce", "Banks", "Automobiles").
- For ambiguous companies, pick the industry that captures their primary revenue source.
- Examples to guide:
    - Zomato / Eternal → E-Commerce
    - Swiggy → E-Commerce
    - Paytm / PB Fintech / Bajaj Finance → NBFCs / Finance (if lending) or Capital Markets & Exchanges (if pure-broker)
    - Naukri / IndiaMART / Just Dial → E-Commerce (online marketplaces / platforms)
    - IRCTC → E-Commerce (online booking platform)
    - Holding cos / conglomerates → classify by largest operating-revenue segment
- No commentary. No markdown fences. Just the JSON array."""


def _parse_response(text):
    """Extract JSON array from Claude's response (handles markdown / preamble)."""
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:].lstrip()
    # Find first '[' if there's preamble
    start = text.find("[")
    end = text.rfind("]")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


def classify_batch(client, sector, stocks_batch, from_scratch=False):
    """Classify one batch via Haiku. Returns dict {ticker: industry}.

    In from_scratch mode, the prompt offers all 25 industries (not just the
    sector's allowed list) and Haiku is told to ignore the existing sector
    tag. Used to fix GICS mis-classifications (Zomato/Swiggy/Paytm wrongly
    filed as Communication Services etc)."""
    if from_scratch:
        prompt = _build_prompt_from_scratch(stocks_batch)
        allowed = set(ALL_INDUSTRIES.keys())
    else:
        prompt = _build_prompt(stocks_batch, sector)
        allowed = set(INDUSTRIES_BY_SECTOR.get(sector, []))

    resp = client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text
    try:
        parsed = _parse_response(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Haiku returned invalid JSON: {e}\nFirst 400 chars:\n{text[:400]}")

    out = {}
    for item in parsed:
        ticker = item.get("ticker")
        ind = item.get("industry")
        if ticker and ind in allowed:
            out[ticker] = ind
    return out


def _write_industries(updates, sync_sector=False):
    """Bulk-update stocks.industry.

    If sync_sector=True, also overwrite stocks.sector based on the industry's
    parent sector in INDUSTRIES_BY_SECTOR — used in from-scratch mode where
    we don't trust the existing GICS tag.
    """
    if not updates:
        return 0, 0
    with get_db() as conn:
        n_ind, n_sec = 0, 0
        for ticker, ind in updates.items():
            if sync_sector:
                sec = ALL_INDUSTRIES.get(ind)
                if sec:
                    r = conn.execute(
                        "UPDATE stocks SET industry = ?, sector = ? WHERE ticker = ?",
                        (ind, sec, ticker),
                    )
                    n_ind += r.rowcount
                    n_sec += r.rowcount
                    continue
            r = conn.execute(
                "UPDATE stocks SET industry = ? WHERE ticker = ?",
                (ind, ticker),
            )
            n_ind += r.rowcount
        conn.commit()
    return n_ind, n_sec


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--sector", help="only classify stocks in this sector")
    parser.add_argument("--limit", type=int, default=0, help="cap to N stocks (smoke test)")
    parser.add_argument("--dry-run", action="store_true", help="don't write to DB")
    parser.add_argument("--skip-existing", action="store_true",
                        help="skip stocks that already have industry set")
    parser.add_argument("--from-scratch", action="store_true",
                        help="ignore current sector tag — pick from all 25 industries "
                             "and overwrite both stocks.industry and stocks.sector based "
                             "on the chosen industry's parent sector")
    args = parser.parse_args()

    # Pull stocks needing classification
    where = "ticker IS NOT NULL AND sector IS NOT NULL"
    params = []
    if args.sector:
        where += " AND sector = ?"
        params.append(args.sector)
    if args.skip_existing:
        where += " AND (industry IS NULL OR industry = '')"

    df = read_sql(
        f"SELECT sid, ticker, name, sector FROM stocks WHERE {where} ORDER BY sector, market_cap_cr DESC",
        params=params,
    )
    if args.limit:
        df = df.head(args.limit)

    if df.empty:
        print("No stocks to classify.")
        return

    print(f"Classifying {len(df)} stock(s) across {df['sector'].nunique()} sector(s)…\n")
    client = _get_client()

    total_done = 0
    total_failed = 0
    all_updates = {}

    if args.from_scratch:
        # One unified pool — sector is irrelevant
        stocks_list = df[["ticker", "name"]].to_dict("records")
        print(f"=== FROM-SCRATCH MODE · {len(stocks_list)} stocks · 25 industries ===")
        for i in range(0, len(stocks_list), BATCH_SIZE):
            batch = stocks_list[i:i + BATCH_SIZE]
            try:
                updates = classify_batch(client, None, batch, from_scratch=True)
                all_updates.update(updates)
                total_done += len(updates)
                sample = list(updates.items())[:3]
                sample_str = ", ".join(f"{t}→{ind}" for t, ind in sample)
                print(f"  [{i+1}-{i+len(batch)}/{len(stocks_list)}] {len(updates)}/{len(batch)} ok · {sample_str}…")
            except Exception as e:
                print(f"  [{i+1}-{i+len(batch)}/{len(stocks_list)}] FAILED: {type(e).__name__}: {str(e)[:200]}")
                total_failed += len(batch)
            time.sleep(0.15)
    else:
        for sector, sec_df in df.groupby("sector"):
            if sector not in INDUSTRIES_BY_SECTOR:
                print(f"[skip] sector '{sector}' not in taxonomy")
                total_failed += len(sec_df)
                continue

            stocks_list = sec_df[["ticker", "name"]].to_dict("records")
            print(f"=== {sector} · {len(stocks_list)} stocks · "
                  f"{len(INDUSTRIES_BY_SECTOR[sector])} industries ===")

            for i in range(0, len(stocks_list), BATCH_SIZE):
                batch = stocks_list[i:i + BATCH_SIZE]
                try:
                    updates = classify_batch(client, sector, batch)
                    all_updates.update(updates)
                    total_done += len(updates)
                    sample = list(updates.items())[:3]
                    sample_str = ", ".join(f"{t}→{ind}" for t, ind in sample)
                    print(f"  [{i+1}-{i+len(batch)}/{len(stocks_list)}] {len(updates)}/{len(batch)} ok · {sample_str}…")
                except Exception as e:
                    print(f"  [{i+1}-{i+len(batch)}/{len(stocks_list)}] FAILED: {type(e).__name__}: {str(e)[:200]}")
                    total_failed += len(batch)
                time.sleep(0.15)  # gentle on the API

    if args.dry_run:
        print(f"\n[dry-run] would update {len(all_updates)} stocks.")
        return

    n_ind, n_sec = _write_industries(all_updates, sync_sector=args.from_scratch)
    print(f"\nDone. {n_ind} industry updates, {n_sec} sector updates, {total_failed} failed/skipped.")

    # Coverage summary
    print("\n=== Coverage summary (industry counts per sector) ===")
    summary = read_sql(
        """
        SELECT sector, industry, COUNT(*) AS n
        FROM stocks WHERE ticker IS NOT NULL AND industry IS NOT NULL
        GROUP BY sector, industry
        ORDER BY sector, n DESC
        """
    )
    for sec, g in summary.groupby("sector"):
        print(f"\n{sec}")
        for _, r in g.iterrows():
            print(f"  {r['n']:>5}  {r['industry']}")


if __name__ == "__main__":
    main()
