# Multibagger Cohort Study — Data Requirements (Phase 2b unblock)

> **Why this exists.** Phase 1 (the funnel + the gross-profitability anchor) is built and produces credible candidates, but the *rigorous validation* — "did the historical top-decile actually 3x?" — is **data-gated**. A 3–4yr survivorship-corrected cohort study needs data we don't have today. This spec is the exact shopping list. Owner decided (2026-06-03) to backfill before running the study (Option B) rather than ship a caveated first-cut.
>
> The cohort study (`tools/multibagger_cohort.py`, not yet built) will: take historical anchor dates (2022–2023), reconstruct the funnel as-of-then, take the top decile, and measure realized 2–4yr forward returns — reporting **top-decile − median spread**, **≥2x/≥3x/≥5x hit-rates**, and **right-tail capture**. Each item below removes a specific blocker.

---

## ✅ Backfill status (2026-06-03) — sources found + tested

**All four backfills now have a confirmed, FREE source via `nselib`. No paid feed needed.** Probed live this session:

| # | Backfill | Status | Confirmed source |
|---|---|---|---|
| 1 | Adjusted prices (corporate actions to 2022) | **✅ DONE** | `nselib.corporate_actions_for_equity` reaches 2022; **ran it** → `corporate_actions` now **2022-05 → 2026-06, 9,811 rows (218 splits, 224 bonuses)** |
| 2 | Survivorship / true historical universe | **✅ SOURCE CONFIRMED** | `nselib.bhav_copy_with_delivery('03-04-2023')` → **2,258 symbols** (the real 2023 universe, incl. since-delisted). Deaths = set-diff vs `equity_list()` (today's 2,376) |
| 3 | Historical market cap | **✅ DERIVABLE** | historical bhavcopy `close` × shares (`fundamentals_screener` "No. of Equity Shares") — now even cleaner since bhavcopy covers the full historical universe |
| 4 | Deep historical shareholding (promoter/pledge) | **⏳ PARTIAL GAP** | Tickertape window is shallow; deep history TBD. Only affects 2 historical gates — cohort can run without them (note as limitation) |

**The survivorship method (the hard one), concretely:** for each anchor date, pull `bhav_copy_with_delivery(anchor)` → that's the unbiased universe + prices. A symbol in the 2023 bhavcopy but absent from today's `equity_list` (or with no recent bhavcopy) = **delisted/dead** → its forward return is terminal (last-known price ÷ anchor price, floored at −100% if truly gone). This separates deaths from survivors with zero paid data and reconstructs the true opportunity set.

**Remaining before the cohort study is purely implementation, not data-sourcing:**
1. `tools/build_historical_universe.py` — pull bhavcopy for anchor dates → a `historical_universe` table (sid/symbol, date, close, listed-then flag).
2. `pit_multibagger()` — port `signals/multibagger.py:_build` to as-of-date (reuse `knowable_screener`, `apply_pit_adjustments` on the now-deep `corporate_actions`).
3. `tools/multibagger_cohort.py` — top-decile forward returns + hit-rates + decile lift, deaths included.

*(Verify `apply_pit_adjustments` parses split/bonus ratios from `corporate_actions.subject`/`ind` before relying on it — the table stores ratio as text.)*

---

## What we verified we DON'T have (the blockers)

| Blocker | Evidence (2026-06-03) | Consequence |
|---|---|---|
| No split-adjusted prices | `stock_prices` has raw `close` only | Multi-year returns distorted by splits/bonuses (a 1:5 split reads as −80%) |
| `corporate_actions` too shallow | rows only 2024-06 → 2026-06 | Can't adjust a 2022/2023-anchored window |
| No delisting/index master | panel is current-names-only (1,346 sids in 2023-04 vs 2,093 now) | Survivorship bias — winners over-counted, can't separate deaths from graduations |
| Shallow shareholding history | `shareholding` is a rolling ~6-quarter window | Can't reconstruct the pledge / promoter gates as-of 2023 |

---

## The four backfills (priority order)

### 1. Extend `corporate_actions` back to 2022-07  ·  **EASY · HIGH VALUE**
- **Unblocks:** split/bonus-adjusted multi-year returns (the #1 correctness issue).
- **No new table** — the schema and the adjustment machinery already exist: `tools/reconstruct_pit.py:apply_pit_adjustments()` computes `adj_close` from `corporate_actions` (ex_date ≤ eval_date). The cohort tool reuses it verbatim.
- **Need:** splits, bonuses, (and ideally consolidations) for all NSE equities, **2022-07-11 → present** (to match `stock_prices` start). Columns already in the table: `sid, ex_date, <type>, <ratio/factor>`.
- **Source:** `nselib` corporate-actions archive (memory: `nselib_apis` — date-range access via the NSE cookie session). The existing `sources/nselib_pull.py:pull_corporate_actions` already fetches these — just run it with a 2022-07 start window and backfill.
- **Acceptance:** for a known 2023 split (e.g. any 1:N stock), `adj_close` makes the multi-year return continuous (no phantom −X% step at the ex-date).

### 2. Delisting / index-membership master  ·  **HARD · ESSENTIAL for true survivorship correction**
- **Unblocks:** reconstructing the *true* historical universe (names that later delisted/demoted), and separating **deaths** from **upward graduations** (Report B: of 82.5% Smallcap-250 turnover, only ~19.6% were deaths; ~40% graduated up). A flat −4.5%/yr penalty is wrong — we correct by reconstructing the real set.
- **Proposed new table `index_membership_history`:**
  ```
  sid TEXT, index_name TEXT,            -- e.g. NIFTY_SMALLCAP_250, NIFTY_500
  entry_date TEXT, exit_date TEXT,      -- NULL exit_date = still in
  exit_reason TEXT                      -- DELISTED | GRADUATED_UP | DEMOTED_DOWN
  ```
  **and/or `delistings`:** `sid, delisting_date, reason (merger|bankruptcy|voluntary|suspended), last_price`.
- **Coverage:** NIFTY 500 + Smallcap-250 (or the broad NSE list) reconstitution history, **2022 → present**.
- **Source ideas:** NSE index reconstitution circulars + NSE/BSE delisted-securities lists; AMFI categorization history (semi-annual). This likely needs manual assembly or a paid feed (CMIE Prowess / Bloomberg) — the hardest item.
- **Minimal viable version:** even just a **delisting date + flag** per dead sid (deaths only) lets us bound the bias by adding back terminal returns; the full index-membership table is the gold standard.

### 3. Historical market caps  ·  **DERIVABLE — likely NO backfill needed**
- **Unblocks:** the ₹1,000–20,000cr size band applied *as-of* each historical anchor (not today's mcap, which is look-ahead).
- **Derivation:** `historical_mcap = close(anchor) × shares_outstanding(anchor)`. We have historical `stock_prices.close` and shares from `fundamentals_screener` (`No. of Equity Shares`, 16,141 rows; or `Equity Share Capital ÷ Face value`). The cohort tool computes this inline — **no backfill, just code.**
- **Caveat:** verify `No. of Equity Shares` coverage/units before relying on it; fall back to `Equity Share Capital / Face value` where missing.

### 4. Deep historical shareholding  ·  **MEDIUM · enables the pledge/promoter gates historically**
- **Unblocks:** reconstructing Stage-1 pledge gate + Stage-2 promoter-holding hurdle as-of 2022–2023. Without it, the historical funnel must *skip* those two (acceptable degradation — note it).
- **Need:** quarterly `promoter_pct` + `pledge_pct` per sid back to ~2022 (the `shareholding` table already has the schema; it just keeps a rolling window).
- **Source:** `sources/tickertape_shareholding.py` (check if it exposes older quarters) or NSE/BSE quarterly shareholding-pattern filings (available historically). Append into `shareholding` (PK is sid+end_date, so deeper quarters slot in).

---

## Minimal vs gold-standard

- **Minimal defensible study:** #1 (adjusted returns) + #2-lite (delisting dates, deaths-only) → a spread-vs-median study that's first-order survivorship-neutral. ~80% of the value.
- **Gold standard:** #1 + #2 (full index-membership) + #4 (deep shareholding) → full funnel reconstruction + true universe + deaths-vs-graduations. #3 is code either way.

## What I do once data lands
1. Build `pit_multibagger()` (port `signals/multibagger.py:_build` to as-of-date, reusing `knowable_screener`/`knowable_shareholding`/`apply_pit_adjustments`).
2. Build `tools/survivorship_panel.py` (reconstruct true universe; deaths vs graduations).
3. Build `tools/multibagger_cohort.py` (top-decile forward returns, hit-rates, decile lift; calibrate the funnel thresholds here).

---

*Written 2026-06-03. Pairs with the plan at `~/.claude/plans/i-was-going-theough-polished-dolphin.md` and the research at `docs/reference/multibagger-research.md`. Phase 1 is built; this unblocks Phase 2b.*
