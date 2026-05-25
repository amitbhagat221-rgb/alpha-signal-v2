"""
MICRO-tier reclassifier.

Reclassifies a subset of SMALL-cap stocks to MICRO based on the manipulation-risk
composite: ADTV < ₹1Cr/day AND (mcap < ₹500Cr OR Piotroski ≤ 3 OR <4q fundamentals).

These are the SMALL stocks where one large operator's buy/sell can move the price,
the business is too small to absorb a real position, the data is too thin to trust,
or quality is too poor to recommend. MICRO stocks are EXCLUDED from daily_picks (see
scoring/screener.py) — they remain visible in the cockpit Explorer with a MICRO tag.

Idempotent. Run nightly or after a fresh fundamentals refresh.

Usage:
    python -m tools.classify_micro_tier            # apply
    python -m tools.classify_micro_tier --dry-run  # preview
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db import get_db, read_sql


# Spec (locked 2026-05-25): liquidity-gate ALL of, quality OR data fail.
# Liquidity gate is the manipulation pre-requisite; one OR-leg is enough to MICRO it.
ADTV_GATE_CR = 1.0
MCAP_LIMIT_CR = 500.0
PIOTROSKI_LIMIT = 3
MIN_QUARTERS = 4


def candidates() -> "pandas.DataFrame":
    """Return SMALL or already-MICRO stocks meeting the composite criteria."""
    return read_sql(
        """
        WITH small AS (
            SELECT sid, cap_tier FROM stocks WHERE cap_tier IN ('SMALL', 'MICRO')
        ),
        prices AS (
            SELECT sid, AVG(close * volume) / 1e7 AS adtv_cr_90d
            FROM stock_prices WHERE date >= date('now', '-90 days')
            GROUP BY sid
        ),
        quality AS (
            SELECT sid, MAX(f_score) AS f_score FROM piotroski_scores GROUP BY sid
        ),
        fund AS (
            SELECT sid, COUNT(*) AS n_quarters FROM quarterly_income GROUP BY sid
        )
        SELECT s.sid, s.cap_tier AS current_tier,
               st.market_cap_cr,
               COALESCE(st.adtv_6m_cr, p.adtv_cr_90d, 0) AS adtv_cr,
               COALESCE(q.f_score, 0) AS f_score,
               COALESCE(f.n_quarters, 0) AS n_quarters
        FROM small s
        JOIN stocks st USING(sid)
        LEFT JOIN prices p USING(sid)
        LEFT JOIN quality q USING(sid)
        LEFT JOIN fund f USING(sid)
        WHERE COALESCE(st.adtv_6m_cr, p.adtv_cr_90d, 0) < ?
          AND (
              COALESCE(st.market_cap_cr, 0) < ?
              OR COALESCE(q.f_score, 0) <= ?
              OR COALESCE(f.n_quarters, 0) < ?
          )
        """,
        params=[ADTV_GATE_CR, MCAP_LIMIT_CR, PIOTROSKI_LIMIT, MIN_QUARTERS],
    )


def reclassify(dry_run: bool = False) -> int:
    """Apply MICRO classification. Returns count of (sid → MICRO) updates."""
    df = candidates()
    if df.empty:
        print("No MICRO candidates found.")
        return 0

    micro_sids = df["sid"].tolist()
    # Reset MICRO → SMALL for any sid that no longer meets the gate (handles
    # stocks that improved liquidity/quality and should rejoin SMALL).
    if not dry_run:
        with get_db() as conn:
            still_micro = set(micro_sids)
            currently_micro = {
                r[0] for r in conn.execute("SELECT sid FROM stocks WHERE cap_tier='MICRO'").fetchall()
            }
            to_promote = currently_micro - still_micro
            if to_promote:
                placeholders = ",".join("?" * len(to_promote))
                conn.execute(
                    f"UPDATE stocks SET cap_tier = 'SMALL' WHERE sid IN ({placeholders})",
                    list(to_promote),
                )
                print(f"  Promoted {len(to_promote)} stocks MICRO → SMALL (no longer meeting MICRO criteria)")
            placeholders = ",".join("?" * len(micro_sids))
            conn.execute(
                f"UPDATE stocks SET cap_tier = 'MICRO' WHERE sid IN ({placeholders}) AND cap_tier != 'MICRO'",
                micro_sids,
            )

    print(f"\nMICRO criteria:")
    print(f"  ADTV < ₹{ADTV_GATE_CR}Cr/day  AND  (mcap < ₹{MCAP_LIMIT_CR}Cr  OR  Piotroski ≤ {PIOTROSKI_LIMIT}  OR  <{MIN_QUARTERS}q fundamentals)")
    print(f"\n{'DRY RUN — no DB changes' if dry_run else 'Applied'}: {len(micro_sids)} stocks classified as MICRO")

    # Reason breakdown for transparency
    n_mcap = (df["market_cap_cr"].fillna(0) < MCAP_LIMIT_CR).sum()
    n_piot = (df["f_score"] <= PIOTROSKI_LIMIT).sum()
    n_data = (df["n_quarters"] < MIN_QUARTERS).sum()
    print(f"  Trigger overlap: mcap<{MCAP_LIMIT_CR}Cr={n_mcap}, Piot≤{PIOTROSKI_LIMIT}={n_piot}, <{MIN_QUARTERS}q={n_data}")
    return len(micro_sids)


def main():
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1] if __doc__ else "")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    reclassify(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
