# ADR 0069 — Cockpit v2: one fact, one home; Today trades the sized book

**Status:** accepted 2026-10-10 (live at master db04f06 → 1bc17fc). Supersedes the page set of the 2026-05 cockpit split; keeps ADR 0059's "a surface never decides severity".

## Decision

1. **Every fact has one home**, and other pages link to it rather than recomputing it:
   - regime, VIX and allocation → Model › Rules (one line on Today);
   - sector verdict → the Markets sector call (`api.get_sector_call`, ordered by `sector_tilt`), which Sectors Today reuses;
   - factor evidence → Model › Evidence;
   - pick count → `config.TIERS`;
   - rank text → `views.tier_sizes` + the `rank_text` filter;
   - score colour → `formatting.score_band` / `score_tone`;
   - analyst target → the median, with its basis shown;
   - health counts → `checks/report.gather()`.
2. **Today's buys and sells are changes to the HRP sized book** (`portfolio_weights`, banded per ADR 0046), not raw rank entries and exits. Raw ranks put 54 names in both Buy and Exit within 7 days.
3. **Site map:**
   - Main: Today · Explorer (heatmap) · Stocks (screener) · Markets (news + sector call) · Sectors (incl. the industry tile grid) · Investor Playbooks · Book · Model · Funds.
   - Ops: Health · Feeds · Flow · Boardroom · Options · More › SQL.
   - Retired: `/actions`, `/portfolio`, `/news`, `/ideas`, `/model/outcomes`, `/multibagger` and `/command`. All redirect.
   - The stock page has 7 tabs. Analyst consensus sits on Overview; the Data tab is gone.
4. **Amit keeps the exploration surfaces:** Explorer, Sectors, Playbooks and the stock tabs. Consolidation fixes the data behind a page before it removes the page.
5. **Big interface changes ship through the read-only preview first.** `COCKPIT_PREVIEW=1` adds a compare banner and a read-only guard, served on preview.* subdomains (units and nginx in `ops/`). Each change gets a Playwright pass at 1440 and 375, including a stale-cache browser.

## Why
A five-reviewer audit (2026-10-10) found 23 pages, 67 tabs and 124 sections, with only 40% ending in an action. Regime, sector view, pick count, factor counts and health status each appeared in up to six places, and the copies disagreed (Health Care was "likely to boom" on one page and "be careful" on another; VIX read 15.3 vs 14.4).

## Consequences
- **Tests guard the structure:**
  - `tests/test_cockpit_v2.py`: every rail page loads and every old URL redirects.
  - `tests/test_cockpit_css.py`: every template class has a style rule.
  - `tests/test_static_cache.py`: every script carries `?v=`.
- **A new page joins the shared helpers** (`page_title`, `tab_bar`, `.pill`, `makeChart`) and the `preview.COMPARE` map.
