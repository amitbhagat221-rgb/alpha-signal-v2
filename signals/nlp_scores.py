"""
Alpha Signal v2 — Earnings-call transcript NLP scoring (Plan 0002 §3.2.4).

Turns the raw `transcripts` text into the structured "enriched" layer `nlp_scores`
(one row per transcript), mirroring news_articles → news_enriched. The per-stock
factors read from here:
    #37 uncertainty_word_density   — LM-uncertainty hits / words   (evasive / hedged tone)
    #36 forward_looking_intensity  — forward-looking phrases / 1k words (promise-heavy calls)
    #34 earnings_call_tone_qoq     — net_tone(latest) − net_tone(prior)  (derived per sid)
plus net_tone itself (Loughran-McDonald positive − negative, the finance-standard
tone measure — VADER is social-media-tuned and saturates on long filings).

Lexicons are CURATED Loughran-McDonald subsets (high-signal words). The full LM
dictionary (~2,300 negatives) is a later refinement; the curated set captures the
dominant signal and is fast (pure word-counting over ~8k-word transcripts).

Writes: nlp_scores  (INSERT OR REPLACE; PK sid+doc_type+doc_date)

Usage:
    python -m signals.nlp_scores               # score transcripts not yet scored
    python -m signals.nlp_scores --rescore     # re-score everything
    python -m signals.nlp_scores --dry-run     # score a sample + print, no write
"""

import argparse
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from db import read_sql, get_db

# ── Curated Loughran-McDonald lexicons (subset) ──
UNCERTAINTY = frozenset("""
uncertain uncertainty uncertainties risk risks risky may might could possible possibly
probable probably likely unlikely depend depends depending dependent contingent contingency
fluctuate fluctuated fluctuating fluctuation fluctuations volatile volatility unpredictable
unknown unclear ambiguous ambiguity approximate approximately assume assumed assumes assuming
assumption assumptions cautious cautiously caution conditional exposure exposures indefinite
indefinitely pending preliminary tentative tentatively speculative sometimes somewhat roughly
nearly vary varied varies variable variability unforeseen unproven unspecified unsettled
susceptible turbulence reconsider rumors intangible reexamine seldom sudden suddenly
""".split())

LM_POSITIVE = frozenset("""
able achieve achieved achievement achievements advanced advancement attractive beneficial
benefit benefits best better boost confident constructive delight delighted effective
efficiency efficient enhance enhanced enhancement excellent exceptional favorable favorably
gain gains good great greater growth healthy ideal improve improved improvement improvements
improving leadership leading opportunity opportunities outperform positive profitable progress
robust solid strength strengthen strengthened strong stronger strongest success successful
successfully superior surpass tremendous upside win winning record momentum resilient
""".split())

LM_NEGATIVE = frozenset("""
adverse adversely alarming breakdown challenge challenged challenges challenging concern
concerned concerns contraction crisis damage damaged decline declined declines declining
decrease decreased decreases decreasing deficit deficits deteriorate deteriorated
deteriorating deterioration difficult difficulties difficulty disappoint disappointed
disappointing disappointment downturn drop dropped fail failed failing fails failure failures
fell headwind headwinds hurt impair impaired impairment inadequate ineffective instability
lag lagged loss losses lost negative negatively painful plunge poor pressure pressured
pressures problem problems recession restructuring shortfall shortage slow slowdown slowed
slowing sluggish soft softness stagnant stress struggle struggled struggling subdued suffer
suffered suffering terminate terminated tough trouble troubled unable underperform
underperformance weak weakened weakening weakness worse worsen worsened worst writedown
""".split())

FORWARD_RE = re.compile(
    r"\b(will|shall|expects?|expected|expecting|anticipates?|anticipated|intends?|"
    r"plans?\s+to|planning|going\s+forward|outlook|guidance|guides?|guided|targets?|"
    r"targeting|forecasts?|projects?|projected|going\s+to|in\s+future|future\s+growth|"
    r"next\s+(?:quarter|year|fiscal)|over\s+the\s+next|by\s+fy\d{2,4}|in\s+the\s+coming|"
    r"we\s+aim|we\s+expect|long[-\s]term|medium[-\s]term|road\s?map|pipeline|upcoming)\b",
    re.IGNORECASE)
WORD_RE = re.compile(r"[a-z]+")
SENT_RE = re.compile(r"[.!?]+")


def score_text(text: str) -> dict | None:
    """Score one transcript. Returns None if too short to be meaningful."""
    if not text:
        return None
    low = text.lower()
    words = WORD_RE.findall(low)
    n = len(words)
    if n < 200:
        return None
    pos = sum(1 for w in words if w in LM_POSITIVE)
    neg = sum(1 for w in words if w in LM_NEGATIVE)
    unc = sum(1 for w in words if w in UNCERTAINTY)
    fwd = len(FORWARD_RE.findall(low))
    return {
        "word_count": n,
        "lm_positive": pos,
        "lm_negative": neg,
        "net_tone": round((pos - neg) / n * 100, 3),
        "uncertainty_density": round(unc / n * 100, 3),
        "forward_looking_intensity": round(fwd / (n / 1000.0), 2),
    }


def compute(rescore: bool = False, limit: int | None = None, write: bool = True) -> pd.DataFrame:
    q = """
        SELECT t.sid, t.doc_type, t.doc_date, t.raw_text
        FROM transcripts t
        LEFT JOIN nlp_scores n
          ON n.sid = t.sid AND n.doc_type = t.doc_type AND n.doc_date = t.doc_date
        WHERE t.raw_text IS NOT NULL AND (:rescore = 1 OR n.sid IS NULL)
        ORDER BY t.doc_date DESC
    """
    df = read_sql(q, params={"rescore": 1 if rescore else 0})
    if limit:
        df = df.head(limit)
    rows = []
    for r in df.itertuples(index=False):
        s = score_text(r.raw_text)
        if s:
            s.update(sid=r.sid, doc_type=r.doc_type, doc_date=r.doc_date)
            rows.append(s)
    out = pd.DataFrame(rows)
    if write and not out.empty:
        cols = ["sid", "doc_type", "doc_date", "word_count", "lm_positive", "lm_negative",
                "net_tone", "uncertainty_density", "forward_looking_intensity"]
        with get_db() as conn:
            conn.executemany(
                f"INSERT OR REPLACE INTO nlp_scores ({','.join(cols)}) "
                f"VALUES ({','.join('?' * len(cols))})",
                [tuple(row[c] for c in cols) for _, row in out.iterrows()],
            )
        print(f"nlp_scores: wrote {len(out)} rows "
              f"(net_tone μ={out['net_tone'].mean():.2f}, "
              f"uncertainty μ={out['uncertainty_density'].mean():.2f}, "
              f"fwd μ={out['forward_looking_intensity'].mean():.1f}/1k)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true", help="re-score all transcripts")
    ap.add_argument("--dry-run", action="store_true", help="score sample, no write")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    df = compute(rescore=args.rescore, limit=args.limit, write=not args.dry_run)
    if df.empty:
        print("Nothing to score (all transcripts already scored — use --rescore).")
        return
    # validation: most negative-tone + most uncertain recent calls
    j = df.merge(read_sql("SELECT sid, name FROM stocks"), on="sid", how="left")
    pd.set_option("display.width", 200)
    show = ["name", "doc_date", "net_tone", "uncertainty_density", "forward_looking_intensity", "word_count"]
    print("\n=== most NEGATIVE-tone calls ===")
    print(j.nsmallest(8, "net_tone")[show].to_string(index=False))
    print("\n=== most POSITIVE-tone calls ===")
    print(j.nlargest(8, "net_tone")[show].to_string(index=False))
    print("\n=== most UNCERTAIN (hedged) calls ===")
    print(j.nlargest(8, "uncertainty_density")[show].to_string(index=False))


if __name__ == "__main__":
    main()
