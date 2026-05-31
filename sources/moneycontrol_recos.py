"""
Alpha Signal v2 — Moneycontrol Broker Recommendations

STATUS: PAUSED (2026-05-22) — yfinance now provides the analyst-consensus
aggregate at 98% LARGE / 92% MID coverage with better fields (mean/median/
high/low/recommendation_key) and no WAF risk. See sources/yfinance_analyst.py
and HANDOFF 2026-05-22. This Moneycontrol scraper is kept for a future Phase
where we want per-broker dispersion + PDF report links. When resuming:
  - Bump DELAY to 12s (the previous 2s tripped the WAF)
  - Run --discover-only first to populate stocks.mc_slug for the universe
  - Then run incrementally; full universe = ~10 hours at 12s/stock

Scrapes each stock's Moneycontrol quote page for the broker recommendations
panel (the `brrs_bx` blocks). Each block carries one broker's call:
  - broker name (e.g. "Motilal Oswal", "Emkay Global Financial Services")
  - date the call was published
  - reco type (BUY / HOLD / SELL / ACCUMULATE / REDUCE / NEUTRAL)
  - reco price (price at the time of the call)
  - target price
  - URL to the broker's PDF report

Replaces the broken Tickertape `forecastsHistory.price` feed which returns
lastPrice rather than analyst consensus (see HANDOFF 2026-05-22).

Writes:
    broker_recommendations  — PK (sid, broker, reco_date, target_price)
                              Long format, one row per broker call.
    analyst_consensus       — aggregated (overwritten by aggregate_consensus)

URL format is /india/stockpricequote/{industry}/{slug}/{mc_code}. The mc_code
is Moneycontrol's internal stock identifier (e.g. HI for HINDALCO). Slug
discovery happens once per ticker and is cached in stocks.mc_slug.

Usage:
    python -m sources.moneycontrol_recos --ticker HINDALCO     # smoke test one
    python -m sources.moneycontrol_recos --limit 10            # smoke test
    python -m sources.moneycontrol_recos                       # full universe
    python -m sources.moneycontrol_recos --discover-only       # populate stocks.mc_slug
    python -m sources.moneycontrol_recos --aggregate-only      # rebuild analyst_consensus from existing recos
"""

import argparse
import re
import sys
import time
from datetime import date as _date, datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import get_db, read_sql, upsert_df

DELAY = 12.0   # Per docstring: 2s tripped the Moneycontrol WAF. 12s is safe.
TIMEOUT = 15
MAX_RETRIES = 2
# Browser-like headers. The autosuggest endpoint 403s if Accept doesn't
# advertise JSON, and 403s if we look too much like a bot. The Referer pin
# matters — without it the WAF blocks.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.moneycontrol.com/",
}

QUOTE_URL_TEMPLATE = "https://www.moneycontrol.com{slug}"
SEARCH_URL = "https://www.moneycontrol.com/mccode/common/autosuggestion_solr.php"


# ─────────────────────── Curated slug overrides ───────────────────────
# Companies where MC autosuggest cannot recover the correct page —
# hand-verified 2026-05-31 during the Plan 0007 slug triage. This is the
# single source of truth for both slug discovery (skip autosuggest) and the
# data_sanity name-mismatch auditor (suppress false positives).
#
#   sid → "<slug>" : pin this verified slug; discovery never calls autosuggest
#                    and the auditor allowlists the (legitimate) name mismatch.
#   sid → None     : autosuggest returns a WRONG entity OR no MC page exists —
#                    never write a slug, never scrape.
#
# Why each entry is here (autosuggest is name/symbol-based and these break it):
#   DPSC  — India Power Corporation Ltd still lives under its legacy 'dpsc'
#           slug (ex-Dishergarh Power / DPSC Ltd). Page title = "DPSC Ltd."
#   CUBEI — Cube Highways Trust is hosted as the 'cubeinvit' InvIT page.
#   BRIGT — ticker "BRIGHT" autosuggests to 'brightsolar' (Bright Solar Ltd),
#           a different company. Bright Outdoor Media has no MC quote page.
#   APPA/DED/MER/PUNI — MICRO-tier shells with no MC coverage at all
#           (autosuggest returns nothing); recorded so they stop being re-probed.
MC_SLUG_OVERRIDES = {
    "DPSC":  "/india/stockpricequote/power-generationdistribution/dpsc/DPS",
    "CUBEI": "/india/stockpricequote/miscellaneous/cubeinvit/CUBEI15078",
    "BRIGT": None,
    "APPA":  None,
    "DED":   None,
    "MER":   None,
    "PUNI":  None,
}


# ─────────────────────── Schema bootstrap ───────────────────────

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS broker_recommendations (
    sid              TEXT NOT NULL REFERENCES stocks(sid),
    broker           TEXT NOT NULL,
    reco_date        TEXT NOT NULL,          -- ISO date the broker published
    reco_type        TEXT,                   -- BUY / HOLD / SELL / ACCUMULATE / REDUCE / NEUTRAL
    reco_price       REAL,                   -- price when call was made
    target_price     REAL NOT NULL,          -- the analyst target
    report_url       TEXT,                   -- PDF link if any
    fetched_at       TEXT,
    PRIMARY KEY (sid, broker, reco_date, target_price)
);
CREATE INDEX IF NOT EXISTS idx_brec_sid ON broker_recommendations(sid);
CREATE INDEX IF NOT EXISTS idx_brec_date ON broker_recommendations(reco_date);
"""


def _ensure_schema():
    """Create broker_recommendations + mc_slug column if absent."""
    with get_db() as conn:
        for stmt in CREATE_TABLES_SQL.strip().split(";"):
            s = stmt.strip()
            if s:
                conn.execute(s)
        # Add mc_slug column to stocks if missing (idempotent via PRAGMA check)
        cols = [c[1] for c in conn.execute("PRAGMA table_info(stocks)").fetchall()]
        if "mc_slug" not in cols:
            conn.execute("ALTER TABLE stocks ADD COLUMN mc_slug TEXT")


# ─────────────────────── Slug discovery ───────────────────────


def _autosuggest(ticker):
    """Use Moneycontrol's autosuggest to find the canonical slug for an NSE ticker.

    Endpoint returns a JSON array of result records. Each record carries
    company_name, sc_id, slug, sc_didcode, symbol (the NSE ticker), and more.
    We require an EXACT symbol match before accepting a slug — the previous
    "first /india/stockpricequote URL in response" heuristic mis-mapped 21%
    of stocks (e.g. "IOC" → ITC, "ABB" → ABBW/Hitachi Energy, "BAJAJ-AUTO"
    → Bajaj Finance) because the regex grabbed whatever URL appeared first.
    """
    params = {"query": ticker, "type": 1, "format": "json"}
    try:
        r = requests.get(SEARCH_URL, headers=HEADERS, params=params, timeout=TIMEOUT)
        if r.status_code != 200 or not r.text.strip():
            return None
        # Strip JSONP wrapper if present.
        text = r.text.strip()
        m = re.search(r"\[\s*\{.*\}\s*\]", text, re.DOTALL)
        if not m:
            return None
        try:
            import json as _json
            results = _json.loads(m.group(0))
        except ValueError:
            return None
        want = (ticker or "").strip().upper()
        for rec in results:
            slug = rec.get("link_src") or rec.get("seo_name") or rec.get("link") or ""
            if not slug:
                continue
            slug_m = re.search(r"(/india/stockpricequote/[a-z0-9-]+/[a-z0-9-]+/[A-Z0-9]+)", slug)
            if not slug_m:
                continue
            # Symbol extraction. Moneycontrol's autosuggest does NOT carry a
            # top-level `symbol` / `nse_symbol` field — the prior code reading
            # rec.get("symbol") was silently returning None for every probe
            # (bug surfaced 2026-05-31 by Plan 0007 slug audit). The NSE
            # ticker lives inside pdt_dis_nm as:
            #     "<Company Name>&nbsp;<span>ISIN, NSE_SYM, BSE_CODE</span>"
            # We extract the second comma-separated value in the span.
            sym = (rec.get("symbol") or rec.get("nse_symbol") or "").strip().upper()
            if not sym:
                dis = rec.get("pdt_dis_nm") or ""
                m_span = re.search(r"<span>([^<]+)</span>", dis)
                if m_span:
                    parts = [p.strip() for p in m_span.group(1).split(",")]
                    if len(parts) >= 2:
                        sym = parts[1].upper()
            if not sym:
                continue
            if sym == want:
                return slug_m.group(1)
        return None
    except Exception:
        return None


def discover_slug_for(sid, ticker):
    # Curated overrides win over autosuggest — these are the SIDs where
    # autosuggest is known to return the wrong entity (or nothing). Pin the
    # verified slug (or None) and never re-probe. See MC_SLUG_OVERRIDES.
    if sid in MC_SLUG_OVERRIDES:
        slug = MC_SLUG_OVERRIDES[sid]
        with get_db() as conn:
            conn.execute("UPDATE stocks SET mc_slug = ? WHERE sid = ?", (slug, sid))
        return slug
    slug = _autosuggest(ticker)
    if not slug:
        return None
    with get_db() as conn:
        conn.execute("UPDATE stocks SET mc_slug = ? WHERE sid = ?", (slug, sid))
    return slug


# ─────────────────────── Page fetch + parse ───────────────────────


def _fetch_html(slug):
    """GET the Moneycontrol quote page. Retry on transient failure."""
    url = QUOTE_URL_TEMPLATE.format(slug=slug)
    for attempt in range(MAX_RETRIES + 1):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            if r.status_code == 200:
                return r.text
            if r.status_code in (404, 410):
                return None
            time.sleep(2)
        except (requests.exceptions.Timeout, requests.exceptions.RequestException):
            time.sleep(2)
    return None


def _parse_reco_block(block):
    """Extract one broker reco from a .brrs_bx div. Returns dict or None if invalid."""
    rec = {
        "broker": None, "reco_date": None, "reco_type": None,
        "reco_price": None, "target_price": None, "report_url": None,
    }
    btn = block.find("button", class_=re.compile(r"button_buy"))
    if btn:
        rec["reco_type"] = btn.get_text(strip=True).upper() or None

    for td in block.find_all("td"):
        text = td.get_text(separator=" ", strip=True)
        strong = td.find("strong")
        if not strong:
            continue
        raw = strong.get_text(strip=True)
        try:
            num = float(raw.replace(",", "")) if raw not in ("-", "") else None
        except ValueError:
            num = None
        if "Reco Price" in text or "Reco" in text and "Price" in text:
            rec["reco_price"] = num
        elif "Target" in text:
            rec["target_price"] = num

    d = block.find("div", class_="br_date")
    if d:
        date_str = d.get_text(strip=True)
        if date_str and date_str != "-":
            try:
                rec["reco_date"] = datetime.strptime(date_str, "%d %b, %Y").date().isoformat()
            except ValueError:
                pass

    bn = block.find("div", class_="brstk_name")
    if bn:
        h3 = bn.find("h3")
        if h3:
            rec["broker"] = h3.get_text(strip=True) or None

    pdf = block.find("a", href=re.compile(r"\.pdf", re.I))
    if pdf:
        rec["report_url"] = pdf.get("href")

    # Reject blocks missing the PK fields. Date can be null if MC doesn't
    # publish one — fall back to fetched_at day in the caller.
    if not rec["broker"] or rec["target_price"] is None:
        return None
    return rec


def parse_page(html):
    """Return list of broker reco dicts (without sid)."""
    soup = BeautifulSoup(html, "html5lib")
    blocks = soup.find_all("div", class_="brrs_bx")
    out = []
    for b in blocks:
        r = _parse_reco_block(b)
        if r:
            out.append(r)
    return out


# ─────────────────────── Driver ───────────────────────


def fetch_for_sid(sid, slug, fetched_at):
    html = _fetch_html(slug)
    if html is None:
        return []
    recos = parse_page(html)
    today = _date.today().isoformat()
    for r in recos:
        r["sid"] = sid
        r["fetched_at"] = fetched_at
        if not r["reco_date"]:
            r["reco_date"] = today  # fall back to today; better than dropping the row
    return recos


def aggregate_consensus():
    """Build analyst_consensus from broker_recommendations.

    Strategy:
      - For each (sid, broker), take the most recent reco_date row.
      - Aggregate across brokers: mean target_price, n_distinct brokers,
        % BUY-or-stronger calls.
      - Write into analyst_consensus.
    """
    df = read_sql(
        """
        WITH ranked AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY sid, broker ORDER BY reco_date DESC, fetched_at DESC) AS rn
            FROM broker_recommendations
        )
        SELECT * FROM ranked WHERE rn = 1
        """
    )
    if df.empty:
        print("aggregate_consensus: no broker_recommendations rows.")
        return 0

    # Map reco types to a [BUY/HOLD/SELL] coarse bucket
    bullish = {"BUY", "STRONG BUY", "ACCUMULATE", "OUTPERFORM", "OVERWEIGHT", "ADD"}

    def is_bullish(r):
        if not isinstance(r, str):
            return False
        return r.upper() in bullish

    df["is_buy"] = df["reco_type"].map(is_bullish)
    agg = df.groupby("sid").agg(
        total_analysts=("broker", "nunique"),
        buy_pct=("is_buy", lambda s: 100.0 * s.sum() / len(s)),
        price_target=("target_price", "mean"),
        latest_reco_date=("reco_date", "max"),
    ).reset_index()
    agg["price_target"] = agg["price_target"].round(2)
    agg["buy_pct"] = agg["buy_pct"].round(2)
    agg["has_analyst_data"] = (agg["total_analysts"] > 0).astype(int)
    agg["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    rows = upsert_df(
        agg[["sid", "total_analysts", "buy_pct", "price_target",
             "has_analyst_data", "fetched_at"]],
        "analyst_consensus",
    )
    print(f"aggregate_consensus: rebuilt {rows} rows in analyst_consensus.")
    return rows


def compute(limit=None, ticker=None, discover_only=False, aggregate_only=False, dry_run=False):
    """Pipeline entry point."""
    _ensure_schema()

    if aggregate_only:
        return aggregate_consensus()

    where = ""
    params = []
    if ticker:
        where = "WHERE ticker = ?"
        params = [ticker]
    stocks = read_sql(
        f"SELECT sid, ticker, COALESCE(name, '') AS name, COALESCE(mc_slug, '') AS mc_slug "
        f"FROM stocks {where} ORDER BY sid",
        params=params,
    )
    if limit:
        stocks = stocks.head(limit)

    print(f"Moneycontrol broker recos: {len(stocks)} stocks")
    fetched_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buf = []
    saved = 0
    no_slug = 0
    no_page = 0
    no_recos = 0
    n_recos_total = 0
    gate_quarantined = 0   # Plan 0007 Phase 2 — identity-gate failures (WRONG_ENTITY)

    for i, (sid, ticker_str, name_str, slug) in enumerate(stocks.itertuples(index=False), 1):
        if not slug:
            slug = discover_slug_for(sid, ticker_str)
            time.sleep(DELAY)
            if not slug:
                no_slug += 1

        # Heartbeat — fires in both --discover-only and full-fetch modes.
        # Pre-2026-05-24 this print was AFTER `if discover_only: continue` →
        # discovery ran 30+ min with zero log output. CLAUDE.md rule: silent
        # failures are the enemy.
        if i % 50 == 0:
            mode = "discovery" if discover_only else "fetch"
            print(f"  [{i}/{len(stocks)}] {mode} · slugs_found={i - no_slug} · no_slug={no_slug}"
                  + (f" · recos={n_recos_total}" if not discover_only else ""), flush=True)

        if discover_only:
            time.sleep(DELAY)
            continue

        recos = fetch_for_sid(sid, slug, fetched_at)
        # Plan 0007 Phase 2 — Identity Gate at the producer boundary.
        # `slug` is the page URL we fetched from; the gate checks the slug
        # contains the ticker. If not, the reco rows we parsed are for the
        # wrong company — route them to broker_recommendations_quarantine
        # instead of the live table. The legacy autosuggest exact-match fix
        # (2026-05-25 / commit 0d8d8bd) is the upstream safety net; this gate
        # is the per-write defense in depth.
        if recos:
            from validators.identity_check import (
                verify_identity, quarantine_row, record_verdict,
            )
            # Verify the slug's company segment against the stock NAME (not the
            # ticker — MC slugs are name-derived). expected_url_segment carries
            # the SID so the gate can allowlist MC_SLUG_OVERRIDES.
            v = verify_identity(sid, slug, source="moneycontrol",
                                expected_name=name_str or ticker_str,
                                expected_url_segment=sid)
            if v.status == "WRONG_ENTITY":
                # Quarantine every parsed reco row + record one verdict per SID.
                for r in recos:
                    quarantine_row(
                        source_table="broker_recommendations",
                        row=r, sid=sid, datum_class="broker_target_price",
                        verdict=v,
                    )
                recos = []  # never write these to live table
                gate_quarantined += 1
            else:
                # PASS or UNRESOLVED — record the verdict so UHS provenance
                # can read it later.
                record_verdict(
                    sid=sid, source_table="broker_recommendations",
                    source_key=f'{{"sid":"{sid}"}}',
                    datum_class="broker_target_price", verdict=v,
                )

        if not recos:
            no_recos += 1
        else:
            buf.extend(recos)
            n_recos_total += len(recos)

        if i % 50 == 0:
            if buf and not dry_run:
                upsert_df(pd.DataFrame(buf), "broker_recommendations")
                saved += len(buf)
                buf = []

        time.sleep(DELAY)

    if buf and not dry_run:
        upsert_df(pd.DataFrame(buf), "broker_recommendations")
        saved += len(buf)

    print(f"Done. {saved} broker recos written ({n_recos_total} parsed). "
          f"no_slug={no_slug}, no_recos={no_recos}, gate_quarantined={gate_quarantined}")

    if not discover_only and not dry_run:
        aggregate_consensus()

    return saved


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="Run for one ticker (smoke test)")
    parser.add_argument("--limit", type=int, help="Limit stocks (smoke test)")
    parser.add_argument("--discover-only", action="store_true",
                        help="Populate stocks.mc_slug; don't fetch recos")
    parser.add_argument("--aggregate-only", action="store_true",
                        help="Rebuild analyst_consensus from existing recos")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    compute(limit=args.limit, ticker=args.ticker,
            discover_only=args.discover_only,
            aggregate_only=args.aggregate_only,
            dry_run=args.dry_run)
