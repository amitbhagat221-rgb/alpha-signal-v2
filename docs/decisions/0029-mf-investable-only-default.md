# 0029 — MF cockpit defaults to investable-only universe

**Status:** Accepted
**Date:** 2026-05-28

## Context
The AMFI scheme master holds **14,364 active schemes** after the [sources/mf_amfi_master.py](../../sources/mf_amfi_master.py) ingest. Of those, only ~60% are realistically investable for an individual researching mutual funds today:

| Bucket | Count | Why not investable |
|---|---:|---|
| Active + TRUSTED + NAV ≤ 30 days old | **8,492** | (this is the investable set) |
| Active + TRUSTED + NAV > 30 days old | **5,610** | Matured FMPs, delisted plans, sub-AMC mergers. NAV stopped updating. |
| Active + non-TRUSTED (wound-up / segregated / interval / bonus / anomalous) | 608 | Already filtered by `data_quality` ([ADR not numbered — see checklist line 132](../../docs/plans/0000-checklist.md)). |

Before this commit, the cockpit `/mutual-funds` universe browser defaulted to filtering only on `active=1` + `data_quality='TRUSTED'`, which left **5,610 stale-NAV schemes in the rankings** — confusingly, schemes that haven't priced in months were sitting in the sortable table. Users could rank by 3Y CAGR and the top of the list would surface long-matured Sundaram Capital Protection Series 5 (NAV last updated 2022) ahead of legitimate equity funds.

The same audit found that `mf_category_stats` was being read raw by the heatmap, so debt-legacy categories (with 1,375 schemes in stats but only 224 investable) were shown at the top of the heatmap purely by historical count — not by relevance.

Also separately: the ETMoney name-matcher was using normalised-string substring matching, which is order-sensitive after stop-word removal. SBI CONTRA FUND - DIRECT PLAN - GROWTH and sbi-contra-direct-plan-growth normalised to `sbicontrafunddirectplangrowth` vs `sbicontradirectplangrowth` respectively — neither substring contained the other, so they never matched, even though the underlying fund is identical. Token-set subset matching closes the gap.

## Decision
1. **`get_mf_universe_overview` accepts `include_non_investable: bool = False`** ([cockpit/api.py:1455](../../cockpit/api.py#L1455)). When False (default), the SQL adds:
   - `(sm.data_quality IS NULL OR sm.data_quality = 'TRUSTED')`
   - `EXISTS (SELECT 1 FROM mf_nav_history n WHERE n.scheme_code = sm.scheme_code AND n.nav_date >= date('now','-30 days'))`
2. **`get_mf_category_heatmap` accepts the same flag** ([cockpit/api.py:1548](../../cockpit/api.py#L1548)). When False, the heatmap (a) re-counts scheme_count as `investable_count` per category, (b) drops categories with zero investable schemes, (c) sorts by the new count. Before: legacy-debt category shows first with stale 1,375; after: Index/Equity shows first with 1,266 investable.
3. **Route maps `show_all` → `include_non_investable`** ([cockpit/app.py:389](../../cockpit/app.py#L389)). UI exposes a single "Investable only" / "Show all" pill toggle in [mutual_funds.html](../../cockpit/templates/mutual_funds.html); URL state carried via `&show_all=1`.
4. **`investable` is defined as `active=1 AND (data_quality IS NULL OR data_quality='TRUSTED') AND latest NAV ≤ 30 days old`.** This is the single canonical cut applied to both the universe table and the category heatmap. The 30-day NAV freshness threshold is a hardcoded constant in the SQL — not a config var — because the bar shouldn't drift.
5. **ETMoney matcher rewritten as token-set subset** in [sources/mf_holdings_scrape.py:90-150](../../sources/mf_holdings_scrape.py) (drive-by from same session, semantically related):
   - `_STOP_TOKENS` strips noise words (fund/plan/option/scheme/the/formerly/known/...).
   - `_PLAN_TOKENS = {direct, regular}`, `_OPTION_TOKENS = {growth, idcw, dividend}` separated out from identity tokens.
   - `_identity_tokens(name)` returns the fund-name signature WITHOUT plan/option markers.
   - `_plan_marker(name)` returns `'direct'` / `'regular'` / `'regular'` (pre-2013 AMFI names without plan token defaulted to Regular).
   - Match if `etm_identity_tokens ⊆ amfi_identity_tokens` AND plan markers align. Sibling propagation in the scrape phase (`GROUP BY etm_id`) then writes the holdings to every AMFI scheme sharing that etm_id, so 1 fetch covers Direct/Regular × Growth/IDCW = up to 4 AMFI variants.
6. **`--skip-fresh-days=N` flag** on the scraper for incremental top-ups after a remap. The scrape v2 hit 1,349 new URLs (vs the 2,463 from v1) in ~75 min, 0 errors.

## Rationale (alternatives weighed)
- **Add stale-NAV badge to each row in the table, don't filter** — would surface the broken state to users but still pollute the rankings (a 7% CAGR stale-NAV liquid fund would beat a 4% real-NAV liquid fund). The user can't tell which row is real without inspecting metadata. Rejected.
- **Two separate flags `include_flagged` (TRUSTED) + `show_stale` (NAV)** — orthogonal but creates UI clutter (two checkboxes for a single conceptual question: "do you want to see funds you can actually buy?"). Combined into one `show_all` toggle. Rejected the granular variant for UX simplicity; the underlying SQL still has two clauses if a future case needs splitting them.
- **NAV freshness threshold of 7 days, not 30** — 7d would miss the legitimate ~3-day-old funds during weekends + Indian holidays. 30d is the natural fence for "still pricing".
- **Make the threshold a config var** — would make it tunable but also tunable means it'll drift across deploys. Hardcoded keeps the semantic stable for the cockpit consumer contract.
- **For the ETMoney matcher: keep substring matching, add manual override file** — would work for the ~50 known-broken cases but doesn't scale and creates a curated mapping table to maintain. Token-set subset is structurally right and self-maintaining.

## Constraints / known limits
- **The 5,872-scheme universe drop is invisible by default.** A user reasonably expects /mutual-funds to show the whole AMFI universe; the Show All toggle is the escape hatch but isn't loud about it. Counter-argument: the prominent count "8,492 investable" in the header makes the cut visible.
- **NAV freshness gate misses schemes whose AMFI publishing is just slow.** Some AMCs file NAVs T+2 or later; a long weekend pushes a real fund into "stale" territory. The 30-day window is loose enough to handle this but a 31-day-old genuinely-active fund will be hidden until next NAV refresh.
- **Heatmap counts are now coupled to the universe cut.** If `get_mf_category_heatmap` is called with show_all=False but the universe table query was called with show_all=True (or vice versa), the heatmap shows different counts than the underlying table. Both flags are routed identically through [cockpit/app.py:391-396](../../cockpit/app.py#L391-L396) so this can only diverge if a new caller forgets to pass the flag. Add a code review check.
- **ETMoney matcher's plan-marker default rule (`None → regular`)** — assumes pre-2013 unsuffixed AMFI names are Regular plans. Mostly correct (Direct Plan was introduced Jan 2013) but a handful of pre-2013 specialty schemes were marked Direct retroactively; those would mis-match to bare-slug Regular ETMoney URLs. Holdings are still correct because Direct + Regular share underlying portfolio; only the attributed `etm_slug` would be the Regular variant.

## Consequences
- **5,872 schemes silently disappear from the default `/mutual-funds` view**. The toggle is the recovery path.
- **The MF cockpit cache survives a code change to the filter semantics — it must be busted manually after this commit lands** via `rm data/.cockpit_cache/mf_*.pkl`. The cache key includes `include_non_investable=False` as an arg, but stale `mf_category_heatmap` pickles from before the flag existed have a different signature and never get evicted. Already done at end of session 2026-05-28.
- **Holdings coverage delta** post-matcher-rewrite + scrape v2: 3,438 schemes with holdings → 3,959 (+521, +15%). 47% of investable universe vs 35% prior.
- **The scoring + metrics pipeline (mf_metrics, mf_rolling_returns) still processes the full active universe.** Only the cockpit surface filters. This is intentional — the underlying scores stay computed in case a different surface (API consumer, future page) wants the broader cut.

## Files
- [cockpit/api.py:1455](../../cockpit/api.py#L1455) — `get_mf_universe_overview(include_non_investable=False, ...)`.
- [cockpit/api.py:1548](../../cockpit/api.py#L1548) — `get_mf_category_heatmap(include_non_investable=False)` with re-count + sort + drop-empty.
- [cockpit/app.py:389](../../cockpit/app.py#L389) — `/mutual-funds` route accepts `show_all=0|1`.
- [cockpit/templates/mutual_funds.html:111](../../cockpit/templates/mutual_funds.html#L111) — `qs_keep` preserves `show_all`; toolbar pill toggle around line 140.
- [sources/mf_holdings_scrape.py:90-150](../../sources/mf_holdings_scrape.py) — `_STOP_TOKENS`, `_PLAN_TOKENS`, `_OPTION_TOKENS`, `_identity_tokens()`, `_plan_marker()`, `build_mapping()` rewritten as token-set subset matcher.
- [sources/mf_holdings_scrape.py:417](../../sources/mf_holdings_scrape.py#L417) — `scrape(skip_fresh_days=N)` for incremental top-ups.
- `mf_scheme_master.etm_id` / `etm_slug` columns (already shipped) re-populated: 6,872 → 7,806 mapped.
