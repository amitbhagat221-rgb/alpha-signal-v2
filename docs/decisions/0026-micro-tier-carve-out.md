# 0026 — MICRO 4th cap-tier excluded from picks

**Status:** Accepted
**Date:** 2026-05-25

## Context
Pre-change, the universe was tiered into LARGE/MID/SMALL (100/150/2,198). SMALL was a 2,200-stock bucket that mixed two very different populations:

- **Legitimate small-caps**: liquid enough to trade, real businesses with audited fundamentals, sell-side coverage, multiple shareholding cohorts. These are appropriate pick candidates.
- **Penny / manipulation-prone stocks**: ADTV under ₹1Cr/day means a single mid-sized operator's buy/sell moves the price; low Piotroski + sparse fundamentals mean the underlying business is too small or too opaque to value; many were perennial pump-and-dump targets (HMT, Jain Irrigation, Ujaas Energy, Spectrum Electrical, Remus Pharma).

Today's screener already gated picks on data coverage (`MIN_FUNDAMENTAL_COVERAGE = 0.50`, `MIN_PRICE_ROWS = 60`), but those gates dropped individual stocks reactively. A more honest model is: separate them up front, label them, and never recommend them.

## Decision
1. **New `MICRO` value in `stocks.cap_tier` CHECK constraint** — migrated via table-rebuild (FK-safe; sqlite_master writes are blocked in modern SQLite). Schema.sql + db.py updated.
2. **Composite classification rule** (locked in [tools/classify_micro_tier.py](../../tools/classify_micro_tier.py)):
   - **AND-gate (manipulation pre-requisite)**: ADTV<₹1Cr/day (from `stocks.adtv_6m_cr` or 90-day computed fallback)
   - **OR-gate (quality / data fail, any one triggers)**: market_cap<₹500Cr OR latest Piotroski f-score≤3 OR <4 quarters of fundamentals
3. **Excluded from picks** via `config.EXCLUDED_FROM_PICKS = ("MICRO",)` — read by `scoring/screener._load_signals()`. MICRO stocks never reach `daily_picks`, dossier, morning_brief, action_queue.
4. **Signal calc continues** for MICRO — signals/* modules don't filter by tier. PIT reconstruction populates `daily_snapshots_pit` for MICRO. Universe eligibility tracks them. Cockpit Explorer shows MICRO with a red badge tagged "excluded from picks".
5. **Daily reclassifier** wired as `classify_micro_tier` in PIPELINE_STEPS. Idempotent: promotes MICRO → SMALL when a stock improves enough to no longer qualify.

## Rationale (alternatives weighed)
- **Pure liquidity (ADTV<₹1Cr, no quality test)** — would catch ~754 stocks but miss quality-poor names that happen to have reasonable turnover. Rejected: misses the "manipulatable AND speculative" intent.
- **Pure market cap (bottom of universe)** — ignores the manipulation angle. Just adds another size cut. Rejected: doesn't change the bug class.
- **Loose composite (ADTV<₹2Cr OR mcap<₹1000Cr OR Piot≤4 OR <6q)** — ~776 stocks but pulls in legitimate microcaps with light analyst coverage. Rejected: too aggressive.
- **Stricter — also exclude from signal calc** — would save some compute but breaks PIT replay and removes visibility for users who explore individual stocks. Rejected: the cost of computing signals for 595 extra stocks is tiny; the visibility is worth keeping.

## Constraints / known limits
- **`market_cap_cr` units are inconsistent** — some rows store crores, others store raw rupees (pre-existing units issue documented in CLAUDE.md). The mcap-leg of the MICRO OR-gate is noisier than ideal. The ADTV gate (which is in actual ₹Cr) and the Piotroski + quarter-count legs are reliable. Net result: 595 reclassified, all of them defensibly MICRO by name inspection.
- **Consumers that assume `daily_picks` covers the whole universe will silently miss 595 stocks.** Today no such consumer exists, but it's a foot-gun for future code. The integrity validator + per-stock cross-source assertions are still applied to MICRO via the signal tables.

## Consequences
- SMALL tier shrinks 2,198 → 1,603 — a more meaningful peer group for tier-relative ranking.
- ~595 stocks (mostly classic penny/SME names) stop appearing in morning briefs and dossier targets.
- Tier-relative percentile ranks in SIGNAL_WEIGHTS["SMALL"] now compute against a cleaner universe; expect slight reshuffling of SMALL picks on next pipeline run. Not breaking, but worth noting.
- PIT replay anchors re-frozen post-change — all 7 still PASS.

## Files
- [tools/classify_micro_tier.py](../../tools/classify_micro_tier.py) — classifier (idempotent, demote-aware)
- [config.py](../../config.py) — `TIERS = ("LARGE","MID","SMALL","MICRO")`, `EXCLUDED_FROM_PICKS = ("MICRO",)`, classifier wired into PIPELINE_STEPS
- [scoring/screener.py `_load_signals()`](../../scoring/screener.py) — MICRO filter at the screener boundary
- [schema.sql:17](../../schema.sql#L17) + live DB CHECK constraint
- [cockpit/static/cockpit.css](../../cockpit/static/cockpit.css) — `.stock-badge.tier-micro` red styling
- [cockpit/templates/explorer.html](../../cockpit/templates/explorer.html) — MICRO tab + criteria footnote
- [cockpit/templates/stock_detail.html](../../cockpit/templates/stock_detail.html) — MICRO badge + tooltip
- [cockpit/api.py `get_heatmap_data` / `get_explorer_table`](../../cockpit/api.py) — MICRO surfaced via UNION on stocks table
