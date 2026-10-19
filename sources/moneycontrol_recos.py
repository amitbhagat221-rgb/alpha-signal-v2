"""
Alpha Signal v2 — Moneycontrol Broker Recommendations

STATUS: ACTIVE (daily step fetch_broker_recos, 90-min host budget) — decided
2026-09-28 (plan 0018). NOT a factor input: yfinance carries the consensus
aggregate. Kept for per-broker dispersion, PDF report links and the cross-source
price-target check (validators/cross_source, trust layer), which read the target,
not the date. PIT: Moneycontrol often omits the call date; such rows get today's
date WITH reco_date_imputed = 1 — never use an imputed date as event time.
Operating notes:
  - Keep the 12s host gap (hosts.HOSTS["moneycontrol"]; 2s tripped the WAF)
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
    python -m sources.moneycontrol_recos --discover-only --rediscover --sids A,B --dry-run   # re-check stored slugs
    python -m sources.moneycontrol_recos --aggregate-only      # rebuild analyst_consensus from existing recos
"""

import argparse
import re
from datetime import date as _date, datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup


from db import get_db, read_sql, upsert_df
from hosts import HOSTS
from sources import _http
from sources._http import polite_get

# Politeness lives in hosts.HOSTS["moneycontrol"]: 12s between calls (2s tripped
# the WAF), WAF-tuned browser headers (Referer pin + JSON-advertising Accept), and
# the daily time budget — pipeline runs stalest-first (stocks.mc_checked_at). The
# old weekly full sweep took ~18h and held the harvest lock all Sunday, starving
# run.sh forward. 90 min/day ≈ 300 stocks → full cycle ~8-9 days; broker
# PTs are episodic, so that cadence loses nothing.
TIMEOUT = 15
MAX_RETRIES = 2

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
    # Renamed companies, slug confirmed by the autosuggest ISIN on 2026-10-19 (the strict
    # name rule, validators.identity_check.mc_name_matches, cannot see a rename)
    "GHCH":  "/india/stockpricequote/chemicals/gujaratheavychemicals/GHC",          # GHCL = Gujarat Heavy Chemicals
    "OSGL":  "/india/stockpricequote/fertilisers/oswalchemicalsfertilisers/OCF",    # Oswal Greentech, ex Oswal Chemicals
    "JRE":   "/india/stockpricequote/miscellaneous/ebix/TE03",                      # Eraaya Lifespaces, ex Ebix Foods
    "NHIT":  "/india/stockpricequote/miscellaneous/nhit/NHIT6531",                  # National Highways Infra Trust
    "ILFE":  "/india/stockpricequote/constructioncontracting-civil/ilandfsengineeringconstructioncompany/MI50",
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
        if "mc_checked_at" not in cols:
            conn.execute("ALTER TABLE stocks ADD COLUMN mc_checked_at TEXT")


# ─────────────────────── Slug discovery ───────────────────────


class SearchFailed(RuntimeError):
    """The autosuggest call itself failed (WAF 403, timeout, not JSON) — unlike an
    answered search with no confident match, this says nothing about the stock."""


_SEARCH_SESSION = None


def _search_session():
    """Autosuggest sits behind Akamai: python-requests gets 403, a warmed chrome
    session (hosts.HOSTS["moneycontrol"]["impersonate"]) gets 200 (probed 2026-10-19).
    Quote pages are fetched without a session, so they are unaffected."""
    global _SEARCH_SESSION
    if _SEARCH_SESSION is None:
        _SEARCH_SESSION = _http.warm_session("https://www.moneycontrol.com/")
    return _SEARCH_SESSION


def parse_suggestions(text):
    """Autosuggest JSON(P) → [{slug, name, isin, symbol, bse}] (records without a
    stock-quote slug dropped). The NSE symbol is not a top-level field: it sits in
    pdt_dis_nm as "<Company Name>&nbsp;<span>ISIN, NSE_SYM, BSE_CODE</span>"."""
    import json as _json
    m = re.search(r"\[\s*\{.*\}\s*\]", (text or "").strip(), re.DOTALL)
    if not m:
        raise ValueError("no JSON array in the autosuggest response")
    out = []
    for rec in _json.loads(m.group(0)):
        link = rec.get("link_src") or rec.get("seo_name") or rec.get("link") or ""
        slug_m = re.search(r"(/india/stockpricequote/[a-z0-9-]+/[a-z0-9-]+/[A-Za-z0-9]+)", link)
        if not slug_m:
            continue
        span = re.search(r"<span>([^<]+)</span>", rec.get("pdt_dis_nm") or "")
        parts = [p.strip() for p in span.group(1).split(",")] if span else []
        isin = parts[0].upper() if parts and re.fullmatch(r"IN[A-Z0-9]{10}", parts[0].upper()) else None
        sym = (rec.get("symbol") or rec.get("nse_symbol") or (parts[1] if len(parts) >= 2 else "")).strip().upper()
        out.append({"slug": slug_m.group(1), "name": rec.get("stock_name") or rec.get("name") or "",
                    "isin": isin, "symbol": sym, "bse": parts[2] if len(parts) >= 3 else None})
    return out


def choose_suggestion(cands, ticker, name, isin=None):
    """The ONE identity rule for a discovered slug → (slug or None, why).

    - The stock's ISIN (scrip_master) on a record is decisive: that record, or —
      when an exact-symbol record carries a DIFFERENT ISIN — nothing.
    - Otherwise the record needs the exact NSE symbol AND a name that is this
      company (validators.identity_check.mc_name_matches, the producer gate's rule).
    The symbol alone was the whole check before: 46 stored slugs pointed at another
    company (TRIDENT → Trent, ASHOKA → Ashok Leyland), and the gate's loose name
    test (similarity ≥ 0.55) let their broker targets through (2026-10-19)."""
    from validators.identity_check import mc_name_matches
    want = (ticker or "").strip().upper()
    if isin:
        hit = [c for c in cands if c["isin"] == isin]
        if hit:
            return hit[0]["slug"], f"ISIN {isin} match ({hit[0]['name']})"
        if any(c["symbol"] == want and c["isin"] for c in cands):
            return None, f"symbol {want} answered with another ISIN"
    for c in cands:
        if c["symbol"] != want:
            continue
        slug_co = c["slug"].strip("/").split("/")[-2]
        if mc_name_matches(name, c["name"]) or mc_name_matches(name, slug_co):
            return c["slug"], f"symbol + name match ({c['name']})"
        return None, f"symbol {want} matched but name '{c['name']}' is not '{name}'"
    return None, f"no record with symbol {want}"


def _autosuggest(ticker, name=None, isin=None):
    """Moneycontrol autosuggest → (slug or None, why). Raises SearchFailed when the
    search itself failed. Before 2026-05-25 the first URL in the response was taken
    (21% mis-mapped: IOC → ITC, BAJAJ-AUTO → Bajaj Finance); see choose_suggestion."""
    params = {"classic": "true", "query": ticker, "type": 1, "format": "json", "callback": "suggest1"}
    try:
        r = polite_get(SEARCH_URL, session=_search_session(), params=params, timeout=TIMEOUT, retries=0)
        cands = parse_suggestions(r.text if r is not None else "")
    except (*_http._REQ_ERRORS, ValueError) as e:
        raise SearchFailed(f"autosuggest {ticker}: {type(e).__name__}: {e}") from e
    return choose_suggestion(cands, ticker, name or ticker, isin)


def _isin_of(sid):
    """The stock's ISIN from scrip_master (Upstox), or None."""
    try:
        r = read_sql("SELECT isin FROM scrip_master WHERE sid = ? AND isin IS NOT NULL "
                     "ORDER BY nse_symbol IS NULL, source = 'upstox' DESC LIMIT 1", params=[sid])
        return r["isin"].iloc[0] if len(r) else None
    except Exception:                                    # noqa: BLE001 — table absent on a fresh DB
        return None


def discover_slug_for(sid, ticker, name=None, *, clear_if_unmatched=False, dry_run=False):
    """Find (and store) the stock's Moneycontrol slug. Returns the slug or None.

    Curated overrides win (MC_SLUG_OVERRIDES: renames and known autosuggest traps).
    An answered search without a confident match leaves the stored slug alone, or
    sets it NULL with clear_if_unmatched (re-discovery: a wrong slug is worse than
    none). A FAILED search (WAF, timeout) never touches the stored slug: it reaches
    run_events and returns None."""
    import runlog
    if sid in MC_SLUG_OVERRIDES:
        slug = MC_SLUG_OVERRIDES[sid]
        if not dry_run:
            with get_db() as conn:
                conn.execute("UPDATE stocks SET mc_slug = ? WHERE sid = ?", (slug, sid))
        return slug
    try:
        slug, why = _autosuggest(ticker, name, _isin_of(sid))
    except SearchFailed as e:
        runlog.item_failed("mc_discover", sid, str(e), symptom="A")
        print(f"  [discover] {sid} {ticker}: search failed — {e}")
        return None
    print(f"  [discover] {sid} {ticker}: {slug or '—'} ({why})")
    if (slug or clear_if_unmatched) and not dry_run:
        with get_db() as conn:
            conn.execute("UPDATE stocks SET mc_slug = ? WHERE sid = ?", (slug, sid))
    return slug


# ─────────────────────── Page fetch + parse ───────────────────────


def _fetch_html(slug):
    """GET the Moneycontrol quote page, or None on any failure. The door keeps
    ≥12s between Moneycontrol calls and retries only 429/5xx/timeouts (a 403 from
    the WAF is not re-hit 2s later any more)."""
    try:
        r = polite_get(QUOTE_URL_TEMPLATE.format(slug=slug),
                       timeout=TIMEOUT, retries=MAX_RETRIES)
    except requests.RequestException:
        return None
    return r.text if r is not None else None


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
        r["reco_date_imputed"] = 0
        if not r["reco_date"]:
            # keep the row (its target feeds the cross-source check) but say the date
            # is ours, not the broker's: an imputed date must never be an event time
            r["reco_date"] = today
            r["reco_date_imputed"] = 1
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
    # A broker's latest call can be years old (pre-split, pre-crash): the mean then sits
    # at many times today's price. This aggregate runs daily and used to rewrite those
    # targets every morning, a week ahead of the Yahoo sweep that nulls them. The same
    # rule now applies at the write (validators.plausibility.PT_CLOSE_RATIO).
    import views
    from validators.plausibility import pt_implausible, record_pt_plausibility_fail
    closes = views.latest_close(agg["sid"].tolist())
    today = datetime.now().date().isoformat()
    rejected = 0
    for i, r in agg.iterrows():
        close = closes.get(r["sid"], (None, None))[0]
        if pt_implausible(r["price_target"], close):
            record_pt_plausibility_fail(r["sid"], today,
                                        f"broker-mean PT {r['price_target']:.0f} vs close {close:.1f} (implausible)")
            agg.at[i, "price_target"] = None
            rejected += 1
    if rejected:
        print(f"aggregate_consensus: {rejected} implausible broker-mean targets not written (verdicts recorded).")
    agg["buy_pct"] = agg["buy_pct"].round(2)
    agg["has_analyst_data"] = (agg["total_analysts"] > 0).astype(int)
    agg["fetched_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Yahoo owns price_target / total_analysts wherever it published a range (pt_source
    # 'yfinance'): its mean, median, high, low and analyst count are one consistent set.
    # The broker mean used to overwrite the mean (and count) every day, leaving it outside
    # its own low-high (178 rows, 2026-10-10). Here we add only buy_pct on those rows.
    yahoo = set(read_sql("SELECT sid FROM analyst_consensus WHERE pt_source = 'yfinance' "
                         "AND price_target_high IS NOT NULL")["sid"])
    owned = agg["sid"].isin(yahoo)
    rows = 0
    if owned.any():
        rows += upsert_df(agg.loc[owned, ["sid", "buy_pct"]], "analyst_consensus")
    if (~owned).any():
        rows += upsert_df(
            agg.loc[~owned, ["sid", "total_analysts", "buy_pct", "price_target",
                             "has_analyst_data", "fetched_at"]],
            "analyst_consensus",
        )
    print(f"aggregate_consensus: rebuilt {rows} rows in analyst_consensus.")
    return rows


def compute(limit=None, ticker=None, discover_only=False, aggregate_only=False, dry_run=False,
            max_minutes=_http.HOST_BUDGET, sids=None, rediscover=False):
    """Pipeline entry point. Visits stocks least-recently-checked first and
    stops after `max_minutes` (default: the host's budget_min; None = no budget,
    full sweep). Pacing is the host door's alone (12s per call) — no extra
    sleeps between stocks. `sids` restricts the run; `rediscover` ignores the
    stored slug and searches again, setting it NULL when no record is
    confidently this company (choose_suggestion)."""
    _ensure_schema()

    if aggregate_only:
        return aggregate_consensus()

    where = ""
    params = []
    if ticker:
        where = "WHERE ticker = ?"
        params = [ticker]
    elif sids:
        where = f"WHERE sid IN ({','.join('?' * len(sids))})"
        params = list(sids)
    stocks = read_sql(
        f"SELECT sid, ticker, COALESCE(name, '') AS name, COALESCE(mc_slug, '') AS mc_slug "
        f"FROM stocks {where} ORDER BY mc_checked_at IS NOT NULL, mc_checked_at, sid",
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
    if max_minutes is _http.HOST_BUDGET:
        max_minutes = HOSTS["moneycontrol"]["budget_min"]
    over_budget = _http.time_budget("moneycontrol", max_minutes)
    checked = []           # sids visited this run → stocks.mc_checked_at
    n_visited = 0

    for i, (sid, ticker_str, name_str, slug) in enumerate(stocks.itertuples(index=False), 1):
        if over_budget():
            print(f"  budget of {max_minutes} min reached after {i - 1} stocks — "
                  f"rest continue next run (stalest-first)", flush=True)
            break
        if not discover_only:          # a discovery pass fetches no recos: it must not
            checked.append(sid)        # push the stock to the back of the fetch queue
        n_visited = i
        if not slug or rediscover:
            slug = discover_slug_for(sid, ticker_str, name_str or None,
                                     clear_if_unmatched=rediscover, dry_run=dry_run)
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

        if discover_only or not slug:   # no MC page (override None / autosuggest miss) → nothing to fetch
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

        if i % 50 == 0 and not dry_run:
            if buf:
                upsert_df(pd.DataFrame(buf), "broker_recommendations")
                saved += len(buf)
                buf = []
            _mark_checked(checked)
            checked = []

    if not dry_run:
        if buf:
            upsert_df(pd.DataFrame(buf), "broker_recommendations")
            saved += len(buf)
        _mark_checked(checked)

    print(f"Done. {saved} broker recos written ({n_recos_total} parsed). "
          f"no_slug={no_slug}, no_recos={no_recos}, gate_quarantined={gate_quarantined}")

    # ~3/4 of covered stocks carry recos; zero across a real batch = parser or
    # WAF breakage, not an empty market (CLAUDE.md: raise on 0 output).
    if not discover_only and not ticker and n_visited >= 50 and n_recos_total == 0:
        raise RuntimeError(f"0 broker recos parsed across {n_visited} stocks — "
                           f"Moneycontrol page format or WAF changed")

    if not discover_only and not dry_run:
        aggregate_consensus()

    return saved


def _mark_checked(sids):
    if not sids:
        return
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.executemany("UPDATE stocks SET mc_checked_at = ? WHERE sid = ?",
                         [(now, s) for s in sids])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", help="Run for one ticker (smoke test)")
    parser.add_argument("--limit", type=int, help="Limit stocks (smoke test)")
    parser.add_argument("--discover-only", action="store_true",
                        help="Populate stocks.mc_slug; don't fetch recos")
    parser.add_argument("--aggregate-only", action="store_true",
                        help="Rebuild analyst_consensus from existing recos")
    parser.add_argument("--sids", help="Comma-separated sids to restrict the run to")
    parser.add_argument("--rediscover", action="store_true",
                        help="Search again even where a slug is stored; NULL it when no confident match")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-minutes", type=float, default=None,
                        help=f"Time budget (pipeline uses {HOSTS['moneycontrol']['budget_min']}); "
                             "default: full sweep")
    args = parser.parse_args()
    compute(limit=args.limit, ticker=args.ticker,
            sids=[s.strip() for s in args.sids.split(",") if s.strip()] if args.sids else None,
            rediscover=args.rediscover,
            discover_only=args.discover_only,
            aggregate_only=args.aggregate_only,
            dry_run=args.dry_run,
            max_minutes=args.max_minutes)
