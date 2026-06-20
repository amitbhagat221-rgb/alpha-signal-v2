"""
Alpha Signal v2 — AI Investment Dossier (Claude API)

Generates investment thesis for top N picks using Claude Sonnet.
Each dossier: thesis, bull/bear cases, catalysts, risks, conviction, action.

Reads: daily_picks, stocks, all signal data
Writes: prints dossiers (saved to output/ as JSON)

Requires ANTHROPIC_API_KEY env var.

Usage:
    python -m output.dossier            # generate for top 5
    python -m output.dossier --top 3    # generate for top 3
    python -m output.dossier --dry-run  # show context without calling API
"""

import argparse
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from config import PROJECT_ROOT
from db import read_sql

OUTPUT_DIR = PROJECT_ROOT / "output"


# ─────────────────────── Hallucination validator ───────────────────────
# Narrative fields must contain no raw numbers — see _build_prompt rule 1.
# Any numeric content in these fields is either (a) hallucinated math
# (the HALC "16.5% downside" bug) or (b) a value snuck through that will
# rot the moment the underlying signal changes. Both cases → invalid.

_NARRATIVE_FIELDS = ("thesis", "bull_case", "bear_case", "catalysts", "risks")

# Map narrative keywords to the context field that must be non-None to
# legitimately reference them. 2026-05-24: MUTT + BJAT (both Financials)
# referenced "solid Piotroski" but Piotroski isn't computed for Financial
# sector stocks — they route through the financial sub-model. Validator only
# caught raw numbers, not soft signal-name hallucination.
#
# Pattern → (context key that must exist, human-readable signal name).
_SIGNAL_KEYWORD_MAP = [
    (re.compile(r"\bpiotroski\b", re.I),                            "f_score",            "Piotroski"),
    (re.compile(r"\baccruals?\b", re.I),                            "accruals_signal",    "Accruals"),
    (re.compile(r"\bconsensus\b|\banalyst\s+(?:target|view|coverage)\b", re.I), "consensus_signal", "Consensus"),
    (re.compile(r"\bsmart[\s-]?money\b", re.I),                     "smart_money_score",  "Smart Money"),
    (re.compile(r"\bpromoter\s+(?:holding|trend|qoq|signal|accumulation|stake)\b", re.I), "promoter_qoq", "Promoter"),
    (re.compile(r"\bm[\s-]?score\b|\bbeneish\b|\bmanipulation\b", re.I), "m_score",         "M-Score / Beneish"),
    (re.compile(r"\bz[\s-]?score\b|\baltman\b|\bdistress\b", re.I), "z_score",            "Z-Score / Altman"),
    # "sentiment" alone is generic English ("positive institutional sentiment" —
    # M&M bull_case 2026-05-29 false-positive). Anchor to a scoring noun so we
    # only fire on actual signal references, not narrative mood words.
    (re.compile(r"\bsentiment\s+(?:score|signal|reading|index|gauge|7d|7-day)\b", re.I), "sentiment_7d", "Sentiment"),
]

# Permissive number detector. We intentionally do NOT allow "12-month"
# or "Q2" (calendar references are fine); the regex catches:
#   ₹1038, Rs 1,038, 16.5%, 12.5x, 0.43 (decimal), 7/9 (score-style),
#   $50, integers >= 4 digits.
_NUMBER_PATTERNS = [
    (re.compile(r"₹\s?[\d,]+(?:\.\d+)?"),         "rupee_amount"),
    (re.compile(r"\bRs\.?\s?[\d,]+(?:\.\d+)?"),   "rupee_amount"),
    (re.compile(r"\$\s?[\d,]+(?:\.\d+)?"),        "dollar_amount"),
    (re.compile(r"\d+(?:\.\d+)?%"),                "percentage"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?x\b", re.I),  "multiple"),  # 12.5x, 3x
    (re.compile(r"\b\d+\.\d+\b"),                  "decimal"),   # 0.43, 7.5
    (re.compile(r"\b\d+/\d+\b"),                   "score_ratio"),  # 7/9
    (re.compile(r"\b\d{4,}\b"),                    "large_integer"),  # 1038, 950
]

# Allowed exceptions — calendar tokens that look numeric but aren't claims.
_ALLOW_PATTERNS = [
    re.compile(r"\bQ[1-4]\b", re.I),               # Q1..Q4
    re.compile(r"\b(?:FY|fy)\d{2,4}\b"),            # FY24, FY2025
    re.compile(r"\b(?:H1|H2)\b"),                   # H1, H2
    re.compile(r"\b\d{4}\b(?=\s+(?:capex|infrastructure|budget))", re.I),  # "2025 capex"
]


def _scan_for_numbers(text):
    """Return list of (snippet, kind) hallucinated-number hits in `text`."""
    if not text:
        return []
    # Strip allowed calendar tokens first so they don't double-match
    cleaned = text
    for ap in _ALLOW_PATTERNS:
        cleaned = ap.sub("", cleaned)

    hits = []
    for pat, kind in _NUMBER_PATTERNS:
        for m in pat.finditer(cleaned):
            snippet = m.group(0)
            hits.append((snippet, kind))
    return hits


def _reconcile_narrative_number(snippet, kind, text_around, context):
    """Try to match a narrative number against a known structured field. If
    we find a structured field that the number CLAIMS to be quoting AND the
    structured value differs, return a 'narrative_contradicts_structured'
    violation. Otherwise return None (snippet is still a violation as a raw
    number, just not a specifically contradicting one).

    The 2026-05-22 HALC bug: narrative said "16.5% downside at ₹1038", actual
    PT was 1038 but actual close was 1135 → real downside -8.5%. This function
    flags the +16.5% as actively contradicting the structured fields.
    """
    if context is None:
        return None
    txt = text_around.lower()
    try:
        # Parse the snippet to a float (strip ₹, %, x, commas, etc.)
        num_str = snippet.replace("₹", "").replace("Rs", "").replace("$", "")
        num_str = num_str.replace("%", "").replace("x", "").replace("X", "").replace(",", "").strip()
        val = float(num_str)
    except ValueError:
        return None

    pairs = []  # list of (cue_keywords, structured_value, structured_name, tolerance)
    pt_upside = context.get("pt_upside")
    current_price = context.get("current_price")
    target_price = context.get("target_price") or context.get("price_target")
    pe = context.get("pe_ratio") or context.get("forward_pe")
    roe = context.get("roe")

    if kind in ("percentage",):
        if pt_upside is not None and any(k in txt for k in ("upside", "downside", "target")):
            pairs.append((pt_upside, "pt_upside_pct", 1.0))
        if roe is not None and "roe" in txt:
            pairs.append((roe, "ROE", 1.0))
    elif kind in ("rupee_amount", "large_integer", "decimal"):
        if current_price is not None and any(k in txt for k in ("current", "cmp", "price", "trading at", "at ₹")):
            pairs.append((current_price, "close", current_price * 0.02))  # 2%
        if target_price is not None and any(k in txt for k in ("target", "pt ", "price target", "upside to")):
            pairs.append((target_price, "price_target", target_price * 0.02))
    elif kind == "multiple":
        if pe is not None and any(k in txt for k in ("p/e", "pe ratio", "trading at", "valuation")):
            pairs.append((pe, "forward_pe", max(0.5, pe * 0.1)))

    for structured_val, structured_name, tolerance in pairs:
        try:
            if abs(val - float(structured_val)) > tolerance:
                return {
                    "structured_field": structured_name,
                    "narrative_claimed": val,
                    "actual": float(structured_val),
                    "tolerance": tolerance,
                }
        except (TypeError, ValueError):
            continue
    return None


def _validate_dossier(dossier, context=None):
    """Scan narrative fields for forbidden numbers AND missing-signal hallucination.

    Returns dict { ok: bool, violations: [{field, snippet, kind, contradicts?}], leaked_pt: bool }.
    leaked_pt = LLM sneaked a target_price or stop_loss into the response despite
    the prompt rule (2026-05-23: now a violation, not a requirement).

    `context` (if provided) is the stock context dict from _build_stock_context.
    Used for:
      • Soft hallucination — narrative mentions a signal by name but that signal
        value was None in the context (e.g. MUTT referencing Piotroski when
        f_score is None because Financials route through the sub-model).
      • Narrative-vs-structured cross-check (plan 0005 Phase B Gap 4) — if a
        number in narrative tries to quote a structured field but differs from
        it, escalate the violation to 'narrative_contradicts_structured'. The
        2026-05-22 HALC bug ("16.5% downside" while PT/close = -8.5%) is the
        canonical case.
    """
    violations = []
    for field in _NARRATIVE_FIELDS:
        val = dossier.get(field)
        if val is None:
            continue
        if isinstance(val, list):
            texts = [str(x) for x in val]
        else:
            texts = [str(val)]
        for text in texts:
            for snippet, kind in _scan_for_numbers(text):
                v = {"field": field, "snippet": snippet, "kind": kind}
                contradicts = _reconcile_narrative_number(snippet, kind, text, context)
                if contradicts:
                    v["kind"] = "narrative_contradicts_structured"
                    v["contradicts"] = contradicts
                violations.append(v)

            # Soft hallucination: signal-name mentioned but signal not in context
            if context is not None:
                for pat, ctx_key, signal_name in _SIGNAL_KEYWORD_MAP:
                    if pat.search(text) and context.get(ctx_key) is None:
                        violations.append({
                            "field": field,
                            "snippet": signal_name,
                            "kind": "missing_signal_referenced",
                        })

    # Flag (don't fail-hard) if LLM leaked a target/stop despite the new rule.
    leaked_pt = (
        dossier.get("target_price") is not None or
        dossier.get("stop_loss") is not None or
        dossier.get("stop_loss_price") is not None
    )
    if leaked_pt:
        violations.append({"field": "structured", "snippet": "target_price or stop_loss present", "kind": "leaked_pt"})

    return {
        "ok": len(violations) == 0,
        "violations": violations,
        "leaked_pt": leaked_pt,
        "validated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _build_stock_context(sid):
    """Build context dict for a single stock."""
    stock = read_sql("SELECT * FROM stocks WHERE sid = ?", params=[sid])
    if stock.empty:
        return None

    s = stock.iloc[0].to_dict()

    # Latest signals
    for table, cols in [
        ("piotroski_scores", "f_score"),
        ("accruals_scores", "accruals_signal, cf_accruals_ratio"),
        ("consensus_signals", "consensus_signal, pt_upside, eps_growth, revenue_growth"),
        ("promoter_signals", "promoter_signal, promoter_qoq, promoter_trend, pledge_quality"),
        ("forensic_scores", "m_score, m_score_flag, z_score, z_score_flag"),
        ("smart_money_scores", "smart_money_score"),
        ("sentiment_scores", "sentiment_7d, articles_7d, latest_headline"),
    ]:
        try:
            row = read_sql(
                f"SELECT {cols} FROM [{table}] WHERE sid = ? "
                f"ORDER BY snapshot_date DESC LIMIT 1",
                params=[sid],
            )
            if not row.empty:
                s.update(row.iloc[0].to_dict())
        except Exception:
            pass

    # Latest price
    price = read_sql(
        "SELECT close, date FROM stock_prices WHERE sid = ? ORDER BY date DESC LIMIT 1",
        params=[sid],
    )
    if not price.empty:
        s["current_price"] = price.iloc[0]["close"]
        s["price_date"] = price.iloc[0]["date"]

    # Pick score
    pick = read_sql(
        "SELECT final_score, rank, uhs_score, uhs_label, uhs_worst_dim, uhs_breakdown_json "
        "FROM daily_picks WHERE sid = ? ORDER BY pick_date DESC LIMIT 1",
        params=[sid],
    )
    if not pick.empty:
        s["final_score"] = pick.iloc[0]["final_score"]
        s["rank"] = pick.iloc[0]["rank"]
        # Plan 0007 Phase 8 — UHS context for the LLM prompt
        s["uhs_score"] = pick.iloc[0]["uhs_score"]
        s["uhs_label"] = pick.iloc[0]["uhs_label"]
        s["uhs_worst_dim"] = pick.iloc[0]["uhs_worst_dim"]
        s["uhs_breakdown_json"] = pick.iloc[0]["uhs_breakdown_json"]

    return s


FINANCIAL_SECTORS = {"Financials"}

# Cap raw growth pcts before showing to the LLM. yfinance/Tickertape report
# arithmetic-true but useless numbers (eps_growth = 2941% for VSKI 2026-05-24
# because prior year EPS was near zero). consensus.py clips internally; we
# clip here defensively so the LLM doesn't see "+2941%" and hallucinate.
_GROWTH_DISPLAY_CAP = 300.0


def _clip_growth(val):
    if val is None or pd.isna(val):
        return None
    if val > _GROWTH_DISPLAY_CAP:
        return f"{_GROWTH_DISPLAY_CAP:.0f}+"
    if val < -_GROWTH_DISPLAY_CAP:
        return f"-{_GROWTH_DISPLAY_CAP:.0f}+"
    return round(val, 1)


def _build_signals_section(context):
    """Build the SIGNALS bullet list, suppressing missing values and
    sector-inapplicable signals. Pre-2026-05-24 the prompt always listed
    every signal with `N/A` for missing — the LLM then confabulated 'solid
    Piotroski score' from the field name alone. Now: only show signals that
    actually have a value, and skip Piotroski entirely for Financials (it's
    not computed there — sub-model territory)."""
    sector = context.get("sector")
    in_financial = sector in FINANCIAL_SECTORS

    lines = []
    def add(line, key):
        if context.get(key) is not None:
            lines.append(line)

    if not in_financial:
        add(f"- Piotroski F-Score: {context.get('f_score')}/9", "f_score")
    add(f"- Accruals Signal: {context.get('accruals_signal')}", "accruals_signal")
    if context.get("consensus_signal") is not None:
        pt_part = f" (PT upside: {context.get('pt_upside')}%)" if context.get("pt_upside") is not None else ""
        lines.append(f"- Consensus Signal: {context.get('consensus_signal')}{pt_part}")
    eps_g_clip = _clip_growth(context.get("eps_growth"))
    rev_g_clip = _clip_growth(context.get("revenue_growth"))
    if eps_g_clip is not None or rev_g_clip is not None:
        parts = []
        if eps_g_clip is not None:
            parts.append(f"EPS Growth: {eps_g_clip}%")
        if rev_g_clip is not None:
            parts.append(f"Revenue Growth: {rev_g_clip}%")
        lines.append("- " + " | ".join(parts))
    if context.get("promoter_qoq") is not None or context.get("promoter_trend"):
        parts = []
        if context.get("promoter_qoq") is not None:
            parts.append(f"QoQ={context['promoter_qoq']}%")
        if context.get("promoter_trend"):
            parts.append(f"trend={context['promoter_trend']}")
        if context.get("pledge_quality") is not None:
            parts.append(f"pledge={context['pledge_quality']}")
        lines.append("- Promoter: " + ", ".join(parts))
    if not in_financial:  # Beneish/Altman are not designed for banks
        forensic_parts = []
        if context.get("m_score") is not None:
            forensic_parts.append(f"M-Score={context['m_score']} ({context.get('m_score_flag', '?')})")
        if context.get("z_score") is not None:
            forensic_parts.append(f"Z-Score={context['z_score']} ({context.get('z_score_flag', '?')})")
        if forensic_parts:
            lines.append("- Forensic: " + ", ".join(forensic_parts))
    add(f"- Smart Money: {context.get('smart_money_score')}/100", "smart_money_score")
    if context.get("sentiment_7d") is not None:
        lines.append(f"- Sentiment 7d: {context.get('sentiment_7d')} ({context.get('articles_7d', 0)} articles)")
    lines.append(f"- Final Score: {context.get('final_score', 'N/A')} (Rank #{context.get('rank', '?')} in {context.get('cap_tier', '?')})")
    return "\n".join(lines)


def _build_uhs_block(context):
    """Plan 0007 Phase 8 — UHS context block in the LLM prompt.

    Surfaces uhs_score + uhs_label + uhs_worst_dim so the narrative
    must acknowledge data-confidence weakness. Adds a hard hygiene rule
    that BANS strength claims about dims that scored <12: cannot claim
    "strong fundamentals" if dim_provenance < 12 or dim_consistency < 12.
    """
    score = context.get("uhs_score")
    label = context.get("uhs_label")
    worst = context.get("uhs_worst_dim")
    breakdown = context.get("uhs_breakdown_json")
    if score is None:
        return "DATA-CONFIDENCE: (not yet computed)\n"

    constraints = []
    if breakdown:
        try:
            import json as _json
            dims = (_json.loads(breakdown).get("dims") or {})
            if (dims.get("provenance") or 99) < 12:
                constraints.append(
                    "  - dim_provenance < 12 — DO NOT claim 'strong fundamentals' or 'verified data'"
                )
            if (dims.get("consistency") or 99) < 12:
                constraints.append(
                    "  - dim_consistency < 12 — DO NOT claim 'consistent signal' or 'reliable trajectory'"
                )
            if (dims.get("freshness") or 99) < 12:
                constraints.append(
                    "  - dim_freshness < 12 — bull/bear must acknowledge data is stale"
                )
        except Exception:
            pass
    constraints_text = "\n".join(constraints) if constraints else ""

    return (
        f"\nDATA-CONFIDENCE (Plan 0007 UHS):\n"
        f"- score = {score}/100 · {label} · weakest dim = {worst or 'n/a'}\n"
        f"- HYGIENE CONSTRAINTS (override defaults):\n"
        f"{constraints_text or '  - none active for this pick'}\n"
    )


def _build_prompt(context):
    """Build the Claude prompt for investment thesis.

    Hard constraints encoded:
      - Narrative fields (thesis / bull_case / bear_case / catalysts / risks)
        must contain NO raw numbers. Numbers are a known hallucination class —
        the LLM invents plausible-sounding percentages that don't match the
        actual math (2026-05-22 HALC bug: "16.5% downside at ₹1038" when
        950/1038 = -8.5%).
      - Structured fields (target_price, stop_loss, conviction, action) are
        the only place numbers live. The cockpit renders them from there.
      - Bull/bear cases must REFERENCE the signal by name, not its value
        — "strong Piotroski" not "Piotroski 7/9", "high accruals" not "0.43".
      - Signals section is filtered to non-NULL values + sector-applicable
        (2026-05-24): omitting a signal from context means it shouldn't appear
        in narrative either — the validator now enforces that.
    """
    signals_block = _build_signals_section(context)
    uhs_block = _build_uhs_block(context)
    return f"""You are an expert Indian equity analyst. Generate a concise investment dossier for this stock.

STOCK: {context.get('name', 'Unknown')} ({context.get('ticker', '?')})
SECTOR: {context.get('sector', '?')} | TIER: {context.get('cap_tier', '?')}
PRICE: ₹{context.get('current_price', '?')} ({context.get('price_date', '?')})
{uhs_block}

SIGNALS (only signals listed here are valid to reference — do not invent absent ones):
{signals_block}

FUNDAMENTALS:
- P/E: {context.get('pe_ratio', 'N/A')} | P/B: {context.get('pb_ratio', 'N/A')} | ROE: {context.get('roe', 'N/A')}%
- D/E: {context.get('debt_to_equity', 'N/A')} | Div Yield: {context.get('dividend_yield', 'N/A')}%

═══════════════════════════════════════════════════════════════════
HARD RULES — violations will be rejected by the validator:

1. NO raw numbers anywhere in narrative fields (thesis, bull_case, bear_case,
   catalysts, risks). That means NO percentages ("16.5%"), NO rupee amounts
   ("₹1038"), NO multiples ("12.5x"), NO ratios ("0.43"), NO score values
   ("7/9", "M-Score of -2.1").

2. Reference signals BY NAME, not by value. Write "strong Piotroski score"
   not "Piotroski of 7/9". Write "high accruals signal" not "0.43 accruals".

3. Use QUALITATIVE language for magnitude: substantial, modest, marginal,
   pronounced. Never invent a percentage to make a point sound concrete.

4. Numbers belong ONLY in the structured fields: target_price, stop_loss.
   The cockpit renders those from the JSON; do not duplicate them in text.

5. Do not anchor narrative to the current price or "downside from here".
   Price moves; the dossier is rendered later when math will be wrong.

6. DO NOT provide target_price, stop_loss, or any rupee-amount field. The
   LLM-generated numbers hallucinated 2x against actual sell-side consensus
   (2026-05-22: HALC AI target ₹1320 vs analyst ₹1015). PT data is now
   rendered ONLY from the deterministic analyst_consensus table in the
   cockpit. Your job is narrative, not numbers. See ADR 0020.
═══════════════════════════════════════════════════════════════════

Respond in JSON with these exact keys:
- thesis: 2-3 sentence investment thesis (NO NUMBERS)
- bull_case: 2 bullet points (NO NUMBERS — qualitative only)
- bear_case: 2 bullet points (NO NUMBERS — qualitative only)
- catalysts: 2 near-term catalysts (NO NUMBERS)
- risks: 2 key risks (NO NUMBERS)
- conviction: HIGH / MEDIUM / LOW
- action: BUY / WATCH / AVOID

Be specific to THIS stock. No generic statements."""


def generate(top=5, dry_run=False):
    """Generate dossiers for top picks.

    Raises RuntimeError if ANTHROPIC_API_KEY is missing (in non-dry-run) or
    if every per-stock API call failed — so pipeline.run_step() logs FAILED
    in pipeline_log and the freshness watchdog can see the silent breakage.
    """
    # Fail fast on missing creds — silent placeholder writes hid this bug
    # for 20 days previously. See ADR/HANDOFF 2026-05-22.
    if not dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set — dossier generator cannot run. "
            "Check run_pipeline.sh exports or systemd env."
        )

    # Get top picks per tier.
    # Plan 0005 Phase B: integrity FAIL SIDs (contradictions across sources)
    # are excluded — a stock whose structured fields don't reconcile shouldn't
    # have a dossier written. The SID remains in daily_picks for review in
    # cockpit but doesn't get LLM-narrated. WARN-status picks still get
    # dossiers (the WARN is surfaced in cockpit, not blocking).
    picks = read_sql(
        "SELECT dp.sid, dp.final_score, dp.rank, dp.cap_tier, s.ticker, s.name "
        "FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid "
        "WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks) "
        "  AND (dp.integrity_status IS NULL OR dp.integrity_status != 'FAIL') "
        "ORDER BY dp.cap_tier, dp.rank LIMIT ?",
        params=[top * 3],
    )

    # Take top N overall
    picks = picks.head(top)
    print(f"Generating dossiers for {len(picks)} stocks...\n")

    dossiers = []
    n_thesis = 0
    for _, pick in picks.iterrows():
        sid = pick["sid"]
        context = _build_stock_context(sid)
        prompt = _build_prompt(context)

        print(f"--- {pick['ticker']} ({pick['cap_tier']}, rank #{pick['rank']}) ---")

        if dry_run:
            print(f"  Context keys: {len(context)}")
            print(f"  Prompt length: {len(prompt)} chars")
            print()
            dossiers.append({"sid": sid, "ticker": pick["ticker"], "status": "dry_run"})
            continue

        api_key = os.environ.get("ANTHROPIC_API_KEY")

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            # Try to parse JSON
            try:
                dossier = json.loads(text)
            except json.JSONDecodeError:
                # Extract JSON from markdown code block if present
                if "```" in text:
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                    dossier = json.loads(text)
                else:
                    dossier = {"raw_response": text}

            dossier["sid"] = sid
            dossier["ticker"] = pick["ticker"]
            dossier["generated_at"] = datetime.now().isoformat(timespec="seconds")
            dossier["validation"] = _validate_dossier(dossier, context=context)
            dossiers.append(dossier)
            if dossier.get("thesis") and dossier["validation"]["ok"]:
                n_thesis += 1
            print(f"  Conviction: {dossier.get('conviction', '?')}")
            print(f"  Action: {dossier.get('action', '?')}")
            print(f"  Thesis: {dossier.get('thesis', '?')[:100]}...")
            v = dossier["validation"]
            if not v["ok"]:
                print(f"  ⚠ VALIDATION FAILED — {len(v['violations'])} issues, "
                      f"leaked_pt={v.get('leaked_pt', False)}")
                for vi in v["violations"][:5]:
                    print(f"     {vi['field']}: '{vi['snippet']}' ({vi['kind']})")
            else:
                print(f"  ✓ validation clean")
            print()

        except Exception as e:
            print(f"  Error: {e}")
            dossiers.append({"sid": sid, "ticker": pick["ticker"], "status": f"error: {e}"})

    # Save to file
    out_path = OUTPUT_DIR / f"dossiers_{date.today().isoformat()}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(dossiers, f, indent=2, default=str)
    n_invalid = sum(
        1 for d in dossiers
        if d.get("thesis") and not d.get("validation", {}).get("ok", False)
    )
    print(f"Saved {len(dossiers)} dossiers to {out_path} "
          f"({n_thesis} clean / {n_invalid} validation-failed)")

    # Fail loudly if every per-stock call returned errors and we wrote a file
    # of placeholders. Previously this silently logged SUCCESS for 20 days.
    if not dry_run and len(picks) > 0 and n_thesis == 0:
        raise RuntimeError(
            f"Dossier generator wrote {len(dossiers)} placeholders but 0 clean theses — "
            f"every Claude API call failed OR every output failed validation. "
            f"Check API key, model availability, prompt compliance."
        )

    return len(dossiers)


def compute(dry_run=False):
    """Pipeline entry point."""
    return generate(top=5, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    generate(top=args.top, dry_run=args.dry_run)
