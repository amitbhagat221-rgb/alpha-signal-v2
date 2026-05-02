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
from datetime import date
from pathlib import Path

import pandas as pd

from config import PROJECT_ROOT
from db import read_sql

OUTPUT_DIR = PROJECT_ROOT / "output"


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
        "SELECT final_score, rank FROM daily_picks WHERE sid = ? ORDER BY pick_date DESC LIMIT 1",
        params=[sid],
    )
    if not pick.empty:
        s["final_score"] = pick.iloc[0]["final_score"]
        s["rank"] = pick.iloc[0]["rank"]

    return s


def _build_prompt(context):
    """Build the Claude prompt for investment thesis."""
    return f"""You are an expert Indian equity analyst. Generate a concise investment dossier for this stock.

STOCK: {context.get('name', 'Unknown')} ({context.get('ticker', '?')})
SECTOR: {context.get('sector', '?')} | TIER: {context.get('cap_tier', '?')}
PRICE: ₹{context.get('current_price', '?')} ({context.get('price_date', '?')})

SIGNALS:
- Piotroski F-Score: {context.get('f_score', 'N/A')}/9
- Accruals Signal: {context.get('accruals_signal', 'N/A')}
- Consensus Signal: {context.get('consensus_signal', 'N/A')} (PT upside: {context.get('pt_upside', 'N/A')}%)
- EPS Growth: {context.get('eps_growth', 'N/A')}% | Revenue Growth: {context.get('revenue_growth', 'N/A')}%
- Promoter: QoQ={context.get('promoter_qoq', 'N/A')}%, trend={context.get('promoter_trend', 'N/A')}, pledge={context.get('pledge_quality', 'N/A')}
- Forensic: M-Score={context.get('m_score', 'N/A')} ({context.get('m_score_flag', '?')}), Z-Score={context.get('z_score', 'N/A')} ({context.get('z_score_flag', '?')})
- Smart Money: {context.get('smart_money_score', 'N/A')}/100
- Sentiment 7d: {context.get('sentiment_7d', 'N/A')} ({context.get('articles_7d', 0)} articles)
- Final Score: {context.get('final_score', 'N/A')} (Rank #{context.get('rank', '?')} in {context.get('cap_tier', '?')})

FUNDAMENTALS:
- P/E: {context.get('pe_ratio', 'N/A')} | P/B: {context.get('pb_ratio', 'N/A')} | ROE: {context.get('roe', 'N/A')}%
- D/E: {context.get('debt_to_equity', 'N/A')} | Div Yield: {context.get('dividend_yield', 'N/A')}%

Respond in JSON with these exact keys:
- thesis: 2-3 sentence investment thesis
- bull_case: 2 bullet points
- bear_case: 2 bullet points
- catalysts: 2 near-term catalysts
- risks: 2 key risks
- conviction: HIGH / MEDIUM / LOW
- action: BUY / WATCH / AVOID
- target_price: estimated 12-month target (₹)
- stop_loss: suggested stop loss (₹)

Be specific to THIS stock. No generic statements."""


def generate(top=5, dry_run=False):
    """Generate dossiers for top picks."""
    # Get top picks per tier
    picks = read_sql(
        "SELECT dp.sid, dp.final_score, dp.rank, dp.cap_tier, s.ticker, s.name "
        "FROM daily_picks dp JOIN stocks s ON dp.sid = s.sid "
        "WHERE dp.pick_date = (SELECT MAX(pick_date) FROM daily_picks) "
        "ORDER BY dp.cap_tier, dp.rank LIMIT ?",
        params=[top * 3],
    )

    # Take top N overall
    picks = picks.head(top)
    print(f"Generating dossiers for {len(picks)} stocks...\n")

    dossiers = []
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

        # Call Claude API
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("  ANTHROPIC_API_KEY not set — skipping API call")
            dossiers.append({"sid": sid, "ticker": pick["ticker"], "status": "no_api_key"})
            continue

        try:
            import anthropic
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
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
            dossiers.append(dossier)
            print(f"  Conviction: {dossier.get('conviction', '?')}")
            print(f"  Action: {dossier.get('action', '?')}")
            print(f"  Thesis: {dossier.get('thesis', '?')[:100]}...")
            print()

        except Exception as e:
            print(f"  Error: {e}")
            dossiers.append({"sid": sid, "ticker": pick["ticker"], "status": f"error: {e}"})

    # Save to file
    out_path = OUTPUT_DIR / f"dossiers_{date.today().isoformat()}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(dossiers, f, indent=2, default=str)
    print(f"Saved {len(dossiers)} dossiers to {out_path}")

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
