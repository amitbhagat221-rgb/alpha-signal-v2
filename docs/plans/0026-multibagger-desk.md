# Plan 0026 — Multibagger desk: thesis → 30 candidates → 10 held, valuation football field, per-name watch

Status: **LIVE 2026-10-15** (merged + cockpit restarted; open items in the to-do) (Amit: "build this please"; D1, D2, D5 answered; D3 money later; D4 shown in the preview). Branches: phase 2 lists + score, phase 4 watch, NSE announcements, deep-dive pieces → `mb-desk` → cockpit. Owner: Amit. Phase 1 is read-only research; phases 2–5 change the DB, the pipeline and the cockpit, so they are built on a worktree branch (`ALPHA_DB` set) and merged only after a preview.

## Why
Amit 2026-10-15: *"fundamentally revamp the multibagger page … a solid thesis basis the history and all our knowledge that can shortlist high quality likely candidates from the universe (with a little loose bar) … arrive at 30 candidates … 10 of these will be invested … all 30 will have a valuation football field page … closely followed for quarterly results, regulatory, sector … political backing, new funding … 1 new subpage called valuation."*

The current screen points at the wrong part of the market:
- **The 10-year study (2026-10-15).** 127 of 995 survivors went 10x from Oct 2016.
  - Full market incl. delisted, Oct anchors 2011–2021: size is the strongest and most stable trait. The least-liquid fifth has a 1.2–1.3× lift, the most-liquid fifth 0.4–0.5×.
  - Cheapness lifts about 1.5×; the most expensive fifth is 0.3×.
  - Momentum is weak but in the right direction: 1.1–1.2× for the top fifth.
  - The least-volatile fifth is 0.65×.
  - Quality hurts: ROCE ≥ 18 % is 0.65×.
  - The 2016 10x median stock was ₹368 Cr, P/B 1.1, P/E 13, ROCE 9 %.
  - Capital goods and iron & steel hit 28–33 % vs 13 % overall.
- **Today's funnel gates** (ROCE ≥ 18 %, D/E ≤ 0.5, ₹1–20k Cr) caught **3 of the 74** 2016 10x stocks (lift 0.35×).
- **ADR 0039 / 0040:** ranking within the gated pond has no edge; the regime and the sector decide; the alpha is in *holding* (81 % of 3x winners fall 30 %+ on the way).
- **Plan 0025:** stock-level winner hunting fails (6.1, 7.2, 7.3); 6-month momentum, 52-week position and SMALL quarterly profit-growth levels are the robust triggers; warning events are noise ex-ante → review, never sell.
- **Cockpit:** `/multibagger` redirects to `/playbooks#strict` (`cockpit/pages.py:63`); there is no page of its own.

So the desk is built for *where to look + who to follow closely*, not for a ranking that claims to pick the winner.

## Ground rules (Amit 2026-10-15: "this does not dilute our model and findings right?")
1. **Separate from the main model.** Plan 0026 never edits `factors.FACTORS`, `SIGNAL_WEIGHTS`, `pit.features_at`, the screener, `daily_picks`, `fast_v1` / `slow_v2` or the paper sleeve. Its score lives in `multibagger_scores` and its lists in `multibagger_book`.
2. **Separate money.** The desk is graded C (ADR 0073), below the SMALL sleeve's two grade-B books. It never takes capital from them. Its size is D3, paper first unless Amit says otherwise.
3. **Separate labels.** The cockpit shows the multibagger rank as its own lens, with its grade and horizon. A stock can rank low in the daily model and high here; that is expected, not a conflict.
4. **Findings flow one way.** The desk reuses validated findings (momentum, 52-week position, SMALL quarterly growth). A desk result reaches the main model only through a normal promotion review (ADR 0043 / 0063).
5. **Count the tests.** Every variant tried here (31 + 6 so far) is recorded in its tool. The next re-test pre-registers again and keeps v1 unless a rule passes.

## The thesis (v1 — frozen before the phase 1 test)
**Loose bar = safety gates only, no quality hurdle.** A stock enters the pond if it is:
- SMALL or MID, market cap ≤ ₹5,000 Cr, ADTV ≥ ₹0.5 Cr (buyable);
- not in CIRP, not under a SEBI order, no statutory-auditor resignation in 12 months, not GSM, pledge ≤ 50 %, revenue > 0.

Forensic flags show beside the name and do not cut it (ADR 0073).

**Thesis score:** equal-weight within-pond percentiles, so nothing is fitted:
1. Smallness: −log market cap.
2. Cheapness: mean percentile of book/price, sales/price and earnings/price.
3. Price trigger: 6-month momentum and 52-week position.
4. Business trigger: latest-quarter EBITDA change and revenue YoY (plan 0025 5.1, SMALL t 3.85 / 2.93).
5. Industry tailwind: 6-month industry momentum (ADR 0040, t 3–4 at 1–6 months).

**Successive funnel** (Amit 2026-10-15: "we need successive funnel structure and then for the final 30 the whole valuation and detailed shebang"). Each stage narrows; the work per name grows as the list shrinks.

| stage | names | how | effort per name |
|---|---|---|---|
| 0 Universe | ~2,450 | every listed stock | none |
| 1 Safety gates (pond) | ~700 | ₹ ≤ 5,000 Cr, liquidity floor, revenue > 0, no auditor resignation / CIRP in 12 months, pledge ≤ 50 %, not GSM | automatic |
| 2 Thesis score → **top 100** | 100 | equal-weight smallness · cheapness · price · latest quarter · industry momentum (ADR 0075) | automatic |
| 3 Evidence card → **30 candidates** | 30 | per-name card: score parts, known-investor entries, latest results vs a year ago, orders / new funding / governance events, own-history P/E · P/B position, forensic flags. The system pre-sorts the card list (the rules phase 1c accepts); **Amit picks the 30** | light: one screen per name |
| 4 Deep dive on the 30 | 30 | **the full shebang**: valuation football field (7 methods + reverse DCF), LLM dossier (thesis, bull, bear, catalysts, risks, no numbers), 12-quarter results trend, ownership and named-holder timeline, event timeline (results, orders, funding, ratings, management, regulatory, sector), government / political links card, peers table, one-line "why this could 5x" approved by Amit | heavy, refreshed quarterly |
| 5 **10 held** | 10 | Amit picks, each with a logged reason | daily watch + alerts |

- **Refresh:** stages 1–3 monthly (the top 100 moves); the 30 change only at Amit's review, yearly at the least (phase 1b: a yearly refresh beats holding longer); the 10 change at the quarterly review.
- **No stop-loss.** The conviction verdict (ADR 0040) is a monitor, not an exit rule (phase 1b).

## To-do

### Phase 1 — test the thesis (read-only, ~2 days)
- [x] **1.1 `tools/mb_thesis.py`** (DONE 2026-10-15: fails the pre-registered bar — T1 4/8 anchors, book grade C on the worst-12-month test only: 30 names +14.1 %/yr vs Smallcap 250, t 2.01, 12/12 starts, worst −32.8 %; top-30 halving lift 0.28; old funnel lift < 1 → ships as a labelled list per D1), pre-registered in its docstring before any run.
  - Full NSE market incl. delisted, via `tools.lh_price_history.load` (survivorship-free).
  - Price-based parts from Oct 2011; fundamental parts from Oct 2015 (Screener annuals only cover today's universe, so those anchors are survivor-only, and that is stated).
  - **T1 tail capture:** at each October anchor, the top-30 score's P(≥ 3x in 3y) and P(≥ 5x in 5y) vs the pond base rate; P(halve) and P(stop trading) vs base.
  - **T2 book:** 10- and 30-name equal-weight books, held 12 months, across 12 start months, after costs (`tools/lh_costs`) and tax, graded by ADR 0073 against the Smallcap 250.
  - **T3 head-to-head:** today's funnel gates and `slow_v2` on the same harness.
  - **Pass (grade B):** T1 top-30 lift ≥ 1.5× with P(halve) ≤ base in ≥ 70 % of anchors, and T2 30-name grade ≥ B.
- [x] **1.2 Verdict** ([study](../studies/multibagger-thesis-2026-10.md), [ADR 0075](../decisions/0075-multibagger-thesis-replaces-quality-funnel.md)) in `docs/studies/multibagger-thesis-2026-10.md` + ADR (supersedes ADR 0039's funnel; keeps ADR 0040's holding rules).

### Phase 1b — test everything v1 left out (Amit 2026-10-15: "test everything, we don't want to go half baked")
- [x] **1b.1 (DONE 2026-10-15: v2 = v1 — none of 25 changes passed; the sector-policy pass was disqualified as hindsight-curated input; v1 at realistic costs +12.7 %/yr, t 1.90, DSR 0.961, PBO 0.29, worst −33 %, grade C; yearly refresh beats conviction holding; edge lives in ₹0.5–1 Cr ADTV names)** `tools/mb_thesis_v2.py`, pre-registered in its docstring before the first run.
  - Realistic costs by liquidity (`tools.lh_costs`) on every book, including v1 re-run.
  - Candidates:
    - C1 five new-listing slots (plan 0025 6.2 score);
    - C2 bear-market rules (no rebalance in a bear / hold the index in a bear);
    - C3 superinvestor entry (a frozen list of 15 investors known before 2018, `shareholding_holders` 2016+);
    - C4 announcement reaction, delivery anomaly, accruals (−), retail-holder growth (−), quarterly margin change;
    - C5 drop-one and only-one ablation of the five parts;
    - C6 holding rules (24-month hold, top-90 band, ADR 0040 conviction exits);
    - C7 liquidity floor ₹0.5 / 1 / 2 Cr;
    - C8 sector policy score;
    - C9 overlap with the SMALL sleeve.
  - Pre-registered accept / drop rules: better in both halves of the window, T1 not worse, worst year not > 5 points worse; book rules must cut the worst year by ≥ 5 points.
  - v2 assembled automatically, graded once, with DSR and PBO over every variant tried.
- [x] **1b.2 Verdict** ([study §1b](../studies/multibagger-thesis-2026-10.md); ADR 0075 amended: yearly refresh, capacity note) appended to the study and ADR 0075 (or a superseding ADR if v2 differs from v1).

### Phase 1c — test the funnel's mechanical rules (read-only, ~½ day)
- [x] **1c.1 (DONE 2026-10-15: no mechanical stage rule passed — industry cap −2.0 pts in 2021–26 and more halvings; investor promotion −1.6 pts; floor ₹0.25 Cr +1.9 pts overall but loses 2016–20 under doubled costs. The top 100 holds 177 of 485 later 3x stocks vs 158 by chance; the top 30 holds 63 vs 47 → stage 3 is Amit's judgement on evidence cards, pre-sorted by the thesis score)** `tools/mb_funnel.py`, pre-registered in its docstring before the first run. F1 ≤ 4 names per industry; F2 top 100 with known-investor entries promoted into the 30; F3 = F2 + the cap; F4 liquidity floor ₹0.25 Cr, also under doubled costs. Plus stage capture: winners in the top 100 and in the 30, vs chance.

### Phase 1d — answer the independent critique (Amit 2026-10-16: "complete all and prepare answer for the reviewer")
Source: [research 0008 findings](../research/0008-multibagger-critique-findings.md). Answer: [response](../research/0008-multibagger-critique-response.md), [ADR 0076](../decisions/0076-multibagger-desk-after-independent-critique.md). The reviewer's pass bars are used as written (set before we ran anything); the answer goes to `docs/research/0008-multibagger-critique-response.md`.
- [x] **1d.1 (PASS: +8.7 %/yr t 2.25 survivors; +9.6 %/yr t 1.89 full market incl. delisted)** EW-pond benchmark (reviewer test 1): top 30 vs the equal-weight pond, same costs, 12 starts. Bar: ≥ +5 %/yr median, t ≥ 1.5.
- [x] **1d.2 (FAIL: DSR 0.764 at 67 trials, null variance; 0.888 observed var; 0.977 N_eff 7.5)** Honest DSR (test 3): every configuration ever run on this window, Bailey–López de Prado with skew and kurtosis, effective N from the trials' correlation. Bar: DSR ≥ 0.90.
- [x] **1d.3 (FAIL: halving lift 0.72, ≤ 0.3x lift 1.01 → the tail claim is withdrawn)** Full-market tails (test 2): halving and ≤ 0.3x lifts, top 30 vs pond, price-only score incl. delisted. Bar: halving lift ≤ 0.7.
- [x] **1d.4 (PASS: +12.7 → +11.0 %/yr)** Quarterly look-ahead audit (test 4): the Tickertape quarter lag 60 → 90 days. Bar: excess within 2 points.
- [x] **1d.5 (PASS: ₹90 lakh +11.9 %/yr, ₹3 crore +10.4 %/yr)** Capacity stress (problem 3): the book at 3× and 10× the tested size. Bar: excess ≥ +5 %/yr at 3×.
- [x] **1d.6 (PASS: 8–10 % more stocks per date; +8.6 %/yr over the pond, t 2.31)** Live-like pond (finding 4.1): the pond rebuilt on `market_caps()` history, no fundamentals requirement. Report pond size and the 1d.1 result on it.
- [x] **1d.7 (both rejected: −0.8 / −1.6 pts)** Promoter overlay and cash-conversion gate (tests 5, 6), each under the phase 1b accept rule.
- [x] **1d.8 (LIVE 2026-10-16: capacity column; paper books started, cron 2nd 06:50 UTC; valuation fixes recomputed for the top 100; process exit/review flags on Held, Candidates and Funnel)** Build:
  - capacity cap (≤ 5 % of 20-day ADTV per name, shown per row);
  - three forward paper books (EW pond / EW top 30 / Amit's 10) with the reviewer's kill rules;
  - valuation fixes (cost of equity 16–20 % by size, EV/Sales for loss-makers, analyst targets only with ≥ 3 houses).

### Phase 2 — the pipeline and the lists (~3 days, worktree)
- [x] **2.1 (BUILT on `mb-desk`)** Score. Rewrite `signals/multibagger.py` to the thesis score (one compute function; the gates as data in `config`), monthly. Add new columns to `multibagger_scores` with column-level `db.upsert_df`; the old columns stay until plan 0017 retires them.
- [x] **2.2 (BUILT on `mb-desk`: `output/mb_book.py`)** The lists are decisions, not scores.
  - New table `multibagger_book`: sid, status (`candidate` / `held` / `dropped`), since, thesis, entry price, reason.
  - Plus `multibagger_book_log`, append-only, so every add / promote / drop is kept.
  - Both go in `schema.sql` and `tables.TABLES`.
  - Written only from the cockpit or a CLI, never by the pipeline.
- [x] **2.3 (BUILT on `mb-desk`: `signals/mb_watch.card`, `output/mb_deepdive.py`, `output/mb_dossier.py` + kind `mb_dossier`)** Stage-3 evidence card and stage-4 deep-dive builders (one function each, reading existing tables; the LLM dossier as a queue kind with the no-numbers validator).
- [ ] **2.4 Review packet.** At each quarterly review: the new top 100, what entered and left, and the conviction verdict for every held name. As an LLM kind `mb_review` on the `say_do` template, no numbers in the narrative, and an Amit approve step.

### Phase 3 — valuation football field (~4 days, worktree)
- [x] **3.1 (BUILT 2026-10-15 on branch `worktree-agent-aaf54a9d4619d9e07`, 46f4c4f, not merged; 22 tests pass)** `signals/valuation.py` → table `valuation_ranges`** (sid, as_of, method, low, mid, high, basis): structured numbers only, for the 30 candidates first and then for the universe. Methods, each a bar on the field:
  1. **Own P/E band:** 10th–90th percentile of `daily_snapshots_pit.earnings_yield` (2019-12 → today) × TTM EPS.
  2. **Own P/B band:** same, from `book_to_price` × book per share.
  3. **Own EV/EBITDA band:** new; EV from Borrowings − Cash & Bank + market cap, EBITDA TTM from quarterly operating profit.
  4. **Industry peers:** IQR of the industry's P/E and EV/EBITDA within the tier, applied to the stock (38 industries; finer peer groups are a later step).
  5. **DCF range:** bear / base / bull growth (industry median / own 3-year / bull = the top-quartile 3-year growth in its industry), fade to 6 % by year 10, cost of equity 13–15 %. **Reverse DCF:** the 10-year growth the current price implies, shown as a label, not a bar.
  6. **Analyst targets:** low / median / high from `analyst_consensus` where they exist (sparse in small caps; marked n/a).
  7. **52-week range:** computed from `stock_prices`, because `stocks.fifty_two_week_*` is empty.
- [x] **3.2 Golden test** (KEIN, GRSE, HDBK; KEIN P/E mid recomputed by hand) on 3 names, with a hand recompute of each method.

### Phase 4 — per-name watch (~1 week, worktree; depends on the BSE feed fix)
- [x] **4.0 (NSE route BUILT on `mb-desk`: `sources/nse_announcements.py`, feed on probation, runs in `run.sh forward`; NSE goes back to 2018)** Pre-req: fix the `bse_announcements` canary (failing 2026-10-14/15) through the data-engineer seat. **Diagnosed 2026-10-15: BSE's Akamai WAF returns 403 on `AnnSubCategoryGetData/w` only (other BSE APIs answer from the same session); not bypassed.** Branch `worktree-agent-adfa93db58a021ea2` (39fa94f) only makes the error say "WAF block". Options: (a) another egress IP, (b) build `nse_announcements` (NSE `corporate-announcements` answers with date ranges; own table + route + canary, ~½ day) — Amit to choose.
- [x] **4.1 (BUILT on `mb-desk`: `signals/mb_watch.timeline`, BSE + NSE)** One timeline per stock from existing tables. Category map in `config` (BSE subcategory → watch category, severity):
  - **Results:** `quarterly_income` + Screener quarterly, YoY / QoQ vs the thesis.
  - **Orders and deals:** BSE Award of Order, Acquisition, Open Offer, MoU.
  - **New money in:**
    - BSE Preferential Issue / QIP / Raising of Funds / Allotment / warrants;
    - new named holders > 1 % (`shareholding_holders` quarter-on-quarter);
    - bulk / block buyers (`bulk_deals`);
    - insider buys (`insider_trades`).
  - **Ownership:** promoter / FII / MF / pledge change (`shareholding`, SAST Reg 29 / 31).
  - **Governance:** auditor / CFO / director resignations, change in management, clarifications, surveillance (ASM / GSM), credit ratings.
  - **Regulatory and sector:** `regulatory_events` for the stock's sector; industry momentum turn.
  - **News:** `news_article_stocks` (thin: 1,114 stocks tagged).
- [~] **4.2 (BUILT except the electoral-bond file: `mb_watch.govt_links`)** Government / political link card (context for a human, never a score; the doubler study found connection runs ended badly):
  - (a) government / PSU / LIC / state holders in `shareholding_holders`;
  - (b) orders from government buyers (headline match: ministries, railways, defence, NHAI, PSU names);
  - (c) the ECI electoral-bond purchaser list (public, one-off 2024 file) → donor flag;
  - (d) LLM read of the stock's news for policy links, no numbers.
- [ ] **4.3 Alerts:**
  - a new event for any of the 30 → the morning email / push and the Today page;
  - a "since last review" badge per name;
  - a severity HIGH event on a held name → a review card in the Boardroom inbox.
- [ ] **4.4 Announcement PDFs** (D5): text for issue size, price and allottees of preferential / QIP / warrant issues; name resolution across SAST, bulk and holder lists so a new backer is one entity.

### Phase 5 — cockpit (~4 days, worktree → preview → Amit → merge)
- [x] **5.1 (BUILT on `mb-desk`, design-reviewed, 769 tests pass)** `/multibagger` comes back as its own rail page.** Remove the redirect in `pages.py` and update `tests/test_cockpit_v2.py` and `test_playbook_tabs.py`. Tabs:
  - **Thesis:** rules, evidence, funnel counts, regime.
  - **Funnel:** stage counts (universe → pond → 100 → 30 → 10) and the top 100 as evidence cards, with a "promote to candidates" action.
  - **Candidates (30):** thesis line, score parts, valuation position, flags, last event; each opens the stage-4 deep dive.
  - **Held (10):** entry, return vs Smallcap 250, conviction HOLD / WATCH / REVIEW, days since last review.
  - **Watch:** event feed for the 30, filter by category and severity.
- [x] **5.2 (BUILT; deep dive at `/multibagger/stock/<sid>`)** New subpage `/multibagger/valuation`:** a grid of 30 mini football fields, sorted by where the price sits. `/multibagger/valuation/<sid>` is the full field with each method's basis, plus a link from the stock page.
- [ ] **5.3 Retire the Playbooks "Strict compounders" tab** (D4), or relabel it as the old quality funnel.
- [x] **5.4 (design review: 25 findings fixed)** Checks: Playwright at 1440 / 375, plus the design-review agent.

## Decisions for Amit
- [x] **D1 → ship as a labelled "where to look" list even if graded C** (Amit 2026-10-15). Was: If phase 1 grades the thesis C (fails the bar), still ship it as a labelled "where to look" list (the good-enough rule), or rework the thesis first?
- [x] **D2 → Amit picks the 10 from the 30**, using the thesis note, the field and the timeline; each pick is logged with a reason (Amit 2026-10-15). Was: How the 10 are chosen: Amit picks from the 30 using the thesis notes and the field, or mechanically the top 10 by score with ≤ 2 per industry?
- [ ] **D3 (Amit: "will review later")** 10 names is more concentrated than ADR 0040's 20–30 (and plan 0025 6.2 found a 10-name book lottery-shaped). Paper first for one review cycle, then real money; or real money at once with a per-name cap?
- [ ] **D4** Retire the Playbooks "Strict compounders" tab?
- [x] **D5 → "anything and everything that helps"** (Amit 2026-10-15): government holders and orders, the electoral-bond file, LLM news read, and announcement-PDF parsing are all in scope, as context cards only. Was: OK to load the ECI electoral-bond file and show a government / political link card as context?

- [x] **D6 → a pre-registered forward test (2026-10-16, the reviewer's round-2 verdict).** The fundamental parts add +0.0 %/yr over a price-only score on survivors (t 0.39), and the two top 30s share only 4 of 30 names. Fourth paper book `price30` started 2026-10-16. After 24 months, the five-part top 30 minus the price-only 30: > +3 points keeps the five-part score; < −3 switches the desk to price-only; within ±3 the simpler price-only score wins (`config.MB_THESIS["kill"]["d6_pts"]`, `tools/mb_paper.py`, tested). Until then the live score stays five-part.

## Done when
- The phase 1 verdict and its ADR are written.
- The thesis score runs monthly.
- `multibagger_book` holds 30 candidates and 10 held, with a log.
- Every candidate has a valuation field with a golden test.
- The watch timeline and alerts run for the 30.
- `/multibagger` (4 tabs) and `/multibagger/valuation` are live after Amit's preview.

## Considered and rejected
- **Quality-gated funnel** (ADR 0039): it caught 3 of 74.
- **Ranking inside the pond as if it picks winners:** ADR 0040 and plan 0025 6.1.
- **Stop-losses:** they eject 3x winners.
- **Mania exclusion:** plan 0025 7.3, a two-sided lottery.
- **A generic doubler model:** fails out of sample.
- **Political links as a score:** context only.

## Implementation notes
- 2026-10-15, phase 1: arm B's pond is the survivors only (Screener annuals exist only for today's universe) and starts 2015; the business part only from 2019. `slow_v2` was not put in T3 (its panel starts 2019-12 with 12-month labels, not comparable); the old funnel and the pond are the comparison. Three code-only fixes after the first run are recorded in the tool's docstring (T1 denominator, book cash before the first score, share counts carried through splits).
- 2026-10-15, phase 3 as built:
  - TTM EPS = the sum of the last 4 `quarterly_income.eps` (reproduces `earnings_yield` exactly).
  - Book per share comes from `book_to_price`; EBITDA from `quarterly_income.ebitda` (`operating_profit` is empty).
  - Reverse DCF solves the *starting* growth that fades to 6 % by year 10.
  - Financials have no EV or DCF methods.
  - Gaps: the P/E band covers only ~2 years (`earnings_yield` PIT starts 2024-08) and EV/EBITDA ~8–9 quarters (`quarterly_income` 2023-09+). Owner earnings fall back to net profit when CFO + capex ≤ 0. The HDBK P/E band is distorted by the merger.
  - Also touched `datamodel/sync.py` (parity registration).
- 2026-10-15, build: five branches merged into `mb-desk`. Integration fixes: `nse_announcements` registered as a v3 event source; signals/ no longer imports db (valuation writer → `output/valuation.py`, deep dive → `output/mb_deepdive.py`); held returns carry the entry price through splits.
  - Production schema applied (additive: 5 empty tables + thesis columns).
  - Still open: data writes need Amit's OK (the NSE backfill was blocked by the permission check); 4.3 alerts into the morning email / push; 4.4 announcement PDFs; the electoral-bond file; mb_book's live strict-tab side effect (financials + MICRO rows raise the strict tab's universe count).
  - The backtest's market cap (`tools/mb_thesis.py`: annual shares carried through splits × raw close) differs from the live `market_caps()` basis (`.claude/rules/factors-backtest.md`); the live code uses `market_caps()`. Re-run the backtest on `market_caps()` history at the next re-test.
- 2026-10-16, critique round 2 (`tools/mb_critique.py crash fundinc`): the −60 % worst window vs the pond is the Apr 2020 → Apr 2021 momentum crash (pond +146 %, bottom momentum quintile +142 % vs top +69 %), so the paper books' risk kill gained a momentum-crash exemption (`risk_crash_pond_up` 0.50). The fundamental parts add +0.0 %/yr over a price-only score on the same survivors → D6. The promoter test ran on 2020 starts (PIT data from 2019-12).
- 2026-10-16, stage 4b deep research (Amit: "lets do a heavy 100 but create a structure first"): `output/mb_research.py` builds a per-stock pack of what the DB already holds (+ direct BSE `AttachHis` PDF links and a gaps list) so research agents fetch only what is missing; brief [research 0011](../research/0011-multibagger-deep-research-brief.md); results in `mb_research`, shown as a verdict chip on the funnel cards and a section on the stock page. The red-flag verdict and 5x case are pre-registered against 24-month forward returns. Found while building: 3 of the top 100 (BHIL #1, VERAN #10, DCM #82) are scored on pre-demerger fundamentals against post-demerger prices → review flag `demerger_days`; the thesis score itself is unchanged pending Amit's call (exclude recent demergers from the pond, or rebase).
