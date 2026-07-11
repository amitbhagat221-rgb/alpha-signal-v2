# 0002 — Compounder / Owner-Operator Sleeve Charter (Engine 2)

**Deep-research dive #2 of the roadmap-to-90.** Gates all of Plan 0011 WS3 (WS3.0).
Decision anchor: [ADR 0051](../decisions/0051-roadmap-to-90-decisions-d1-d12.md) D6 — Engine 2 greenlit,
25% paper-capital share at launch, ≥6mo net-of-tax paper history before any real capital.
Written 2026-07-11 · Status: **charter (research output, not yet built)** · Author: skeptical value quant.

**Reuse-first ledger (read, delta-only research):** ADR 0039/0040 (multibagger regime + holding-vs-selection),
[multibagger-research.md](../reference/multibagger-research.md) (17 confirmed / 8 killed),
[Quantifying Indian Multibagger Stocks.md](../reference/Quantifying%20Indian%20Multibagger%20Stocks.md),
[multibagger-data-requirements.md](../reference/multibagger-data-requirements.md),
[signal-weights.md](../reference/signal-weights.md) "On the bench",
[return-prediction-2026-07-05-report.md](../return-prediction-2026-07-05-report.md),
DLM lens (`signals/management_quality.py` + `signals/managerial_ability.py`, git 2026-06-09).
DB inspected live 2026-07-11. **No new web search was required** — the prior corpus + our own panel answer the charter questions;
the honest gaps are data-depth gaps, not knowledge gaps.

---

## 0. What this engine is (and is NOT)

Engine 2 is the **Buffett / Pabrai / Greenblatt paradigm**: 5–8 concentrated names, multi-year holds,
tax-advantaged (LTCG 12.5% vs the monthly book's STCG 20% — a standing ~7.5pp/turn wedge that only a
long-hold sleeve can bank), selected on **capital-allocation skill + owner-operator alignment + moat +
cloning**, bought only at a fair price. It is a **different mathematical object** from the monthly
cross-sectional factor rank (the daily_picks book) — different objective, horizon, and success metric.
It shares the fund's forensic/ownership data plumbing but not its ranking logic.

---

## 1. QUALITY-FACTOR RECONCILIATION (the central tension)

**The tension, stated honestly.** Our own clean post-ADR-0047 panel says quality is *negative-sign* in India:
`gross_profitability` SMALL t=−3.91 / MID −2.18 / LARGE −1.32 (all negative, the opposite of Novy-Marx);
`roic` and `fcf_margin` negative and counterintuitive (signal-weights "On the bench"). A concentrated
*quality* compounder thesis appears to be betting on exactly the factor our data rejects.

**The resolution — three legs, each removing one driver of the negative sign, and none of them hand-waving.**
(1) **Different question, measured at the wrong frequency.** The rank-factor asks "does high-quality beat
low-quality across all 2,448 stocks *next month*?" In the 2022–26 small-cap junk rally the answer is no —
turnarounds, leveraged cyclicals and penny re-ratings out-run quality over 20-day windows, so the
cross-sectional IC is negative. The compounder sleeve never asks that question: it applies quality as a
**GATE** to strip the left tail, then **holds for years** while earnings-growth-driven compounding (R=G;
ROCE × reinvestment) dominates the monthly re-rating noise the IC is made of. ADR 0040 already proved this
for the sibling problem — "multibagger is a *holding* problem, not a *selection* problem; within the gated
pond the score is noise." The negative monthly IC is literally not a test of a multi-year long-only hold.
(2) **Long-only removes the short leg that did the damage.** Novy-Marx's positive GP premium is a *long-short*
spread; our negative number is a long-short spread too. What blew up in the junk rally is the *short-junk*
leg — and the compounder sleeve does not short. A long-only quality basket sheds the exact leg that turns
negative when junk rallies. (3) **The sign is regime-conditional and sample-bound, not structural.** ADR 0039
measured the flip directly: in the 2018–21 quality-led bear, quality top-decile *out*-performed (+0.10x
spread); in the 2022–26 rally it *under*-performed (−0.30x). Our monthly panel sees only the bull half
(2022-08→2026-07), and it is survivors-only (audit Data-F1) — so it both samples the wrong regime *and*
omits the dead junk names quality would have excluded, systematically under-counting quality's left-tail
protection. The `gross_profitability` KEEP is explicitly a contrarian-sign park flagged "re-read once a
drawdown regime enters the window."

**Verdict: DEFENSIBLE but UNPROVEN on our data — greenlight as PAPER with quality as a GATE, not a bet.**
The holding-vs-rank distinction is real, ADR-established, and removes two of the three drivers of the
negative sign by construction (short leg, monthly horizon); the third (bull-regime junk preference) is a
timing headwind the sleeve accepts and rides through the cycle. But we have **no in-sample India evidence
that concentrated quality compounds net-of-tax over a full cycle** — our only quality evidence is
negative-sign monthly IC in a bull window. So this charter does **not** manufacture a bullish thesis; it
authorizes a *paper* sleeve whose real-capital promotion is gated on the §5 survivorship-free cohort study
**passing** (concentrated-8 beats BSE500 TR net-of-tax across 2018–26 *and* shows measurably lower left-tail
mortality than the ungated universe). **What would falsify it / flip the verdict to DROP:** the cohort study
shows the quality-gated concentrated basket does *not* beat BSE500 TR net-of-tax across the 2018–26 window
(which spans a bear + a bull), or shows no left-tail-mortality reduction from the gates. **What would
strengthen it:** a drawdown regime entering the monthly panel flips `gross_profitability`/`low_vol` back to
canonical sign (the pre-registered re-read trigger), and the roiic/capital-allocation PIT backfill lets us
measure capital-allocation skill on history rather than one 2026 snapshot.

---

## 2. MEASURABLE CRITERIA (4 buckets) — with exact in-house source + GATE/SCORE + India evidence

Data-availability legend: **IN-HOUSE** (queryable today, PIT-safe) · **DERIVABLE** (in-house inputs, needs a
builder) · **PIT-THIN** (values exist but history depth is shallow — noted) · **LLM-EXTRACT** (no field;
needs WS5.1 extraction factory) · **NEEDS-BUILD** (specced, not built).

### (a) Capital-allocation skill

| # | Criterion | Source (exact) | GATE/SCORE | India evidence |
|---|---|---|---|---|
| a1 | **Buffett $1-retained test** — 5y market-value-added per retained rupee ≥ ₹1 | **DERIVABLE**: retained rupees = ΣPAT − Σ`Dividend Amount` (`fundamentals_screener` line-items) *or* Δ`Reserves`; MVA = Δmarket-cap from `historical_universe.close` × shares (`annual_balance_sheet.shares_outstanding`). Needs a builder + PIT-mcap (only 9 anchor snapshots → coarse). | SCORE | Buffett's own retained-earnings test; Motilal Oswal wealth-creation studies (R=G, reinvestment the engine of the "mid-to-mega" 17% transition). *Import — not yet validated on our panel.* |
| a2 | **Incremental ROIC (roiic) inflection** + ROIC ≥ ~15% sustained | **IN-HOUSE / PIT-THIN**: `roiic_scores` (registered signal, FACTOR_LIBRARY, **never backtested** — WS3.1); `roic_scores`. Scores tables only hold 2026 snapshots → PIT reconstruction from `fundamentals_screener` (FY2015–FY2026) required. | SCORE | multibagger-research Rank 2: "inflection in ROIIC frequently precedes an earnings breakout"; ROCE>15% the enduring-compounder baseline. `roic` is *negative-sign* in our monthly panel — same reconciliation as §1 (use as gate/hold input, not rank). |
| a3 | **Payout / reinvestment discipline** | **IN-HOUSE** (payout) / **LLM-EXTRACT** (buyback): `Dividend Amount` + PAT → payout ratio; but `annual_cash_flow` lumps `financing_cash_flow` (no dividend/buyback split) → **buyback discipline needs extraction**. | SCORE | Practitioner (Marcellus CCP ~47% reinvestment rate). Directional; not independently validated here. |

*DLM cross-check (in-house, built):* `management_scores.capital_allocation_z` **already computes** Pillar A =
z(roic, roiic, fcf_margin) within tier (`signals/management_quality.py`); `managerial_ability_scores` gives a
Demerjian-Lev-McVay DEA managerial-ability residual. Both exist but have **1 snapshot (2026-06)** — no PIT
depth yet. Engine 2's capital-allocation score should extend Pillar A, not duplicate it.

### (b) Owner-operator quality

| # | Criterion | Source | GATE/SCORE | India evidence |
|---|---|---|---|---|
| b1 | **Promoter holding ≥ ~40%, non-declining** | **IN-HOUSE / PIT-THIN**: `shareholding.promoter_pct` (2016–2026 but *rolling*; median ~7 quarters/sid → level clean, **trend shallow pre-2022**). | GATE(level ≥ threshold) + SCORE(trend) | multibagger-research Rank 5 / Quantifying §5: promoter holding >35% with stable/rising trend = "skin in the game." `promoter` (QoQ) is a **validated in-house factor** (SMALL t=3.20, wired 0.19). |
| b2 | **Pledge = 0 (hard gate)** | **IN-HOUSE**: `shareholding.pledge_pct`. | **GATE (binary, pledge=0)** | Strongest owner-operator evidence we own: the pledge/SAST family produced `pledge_quality` (SMALL) and is BY-FDR-adjacent; Quantifying §6.3 — pledging triggers forced-sale death spirals. Hard exclusion, no offset. |
| b3 | **Related-party-transaction intensity + promoter-remuneration ratio** | **LLM-EXTRACT**: no field anywhere in the DB (grep confirmed). Needs WS5.1 annual-report extraction (RPT total / revenue; promoter remuneration / PAT). `transcripts` corpus is the extraction backbone. | soft-GATE / SCORE | Marcellus forensic framework (royalty leakage, RPT siphoning); Quantifying §6.2 (CWIP-to-related-parties, contingent liabilities). Import — flagged for the extraction pilot. |

### (c) Moat

| # | Criterion | Source | GATE/SCORE | India evidence |
|---|---|---|---|---|
| c1 | **ROIC persistence vs sector fade (Mauboussin)** | **DERIVABLE**: rolling ROIC stability + sector-relative fade from `roic_scores` + `annual_balance_sheet`/`quarterly_income` history. Builder needed. | SCORE | Mauboussin "measuring the moat" — persistence of high ROIC is the quantitative moat proxy. *Import.* |
| c2 | **Gross-margin stability through input cycles** | **IN-HOUSE**: `quarterly_income` (`revenue`, `operating_profit`, `ebitda`; ~10 quarters/sid) → margin CoV. | SCORE | Coffee-Can / QGLP pricing-power lens. *Import.* |
| c3 | **Market-share momentum** | **IN-HOUSE proxy exists**: `sales_growth_relative_scores.relative_growth` (3y sales growth − sector median) is a serviceable proxy TODAY. Fuller version = **NEEDS-BUILD** (Plan 0003 `market-share-momentum-factor`, specced never built). | SCORE | "Value migration" (unorganized→organized share shift) — multibagger-research Rank 3 / Quantifying §3.2 Lollapalooza. |

### (d) Cloning

| # | Criterion | Source | GATE/SCORE | India evidence |
|---|---|---|---|---|
| d1 | **FII / MF / DII accumulation** | **IN-HOUSE / PIT-THIN** (`shareholding.fii_pct/mf_pct/dii_pct` trend, shallow) + **LIVE-ONLY** (`mf_holdings` 281K rows but **only 3 snapshots** 2026-05→07 — no backtest depth; it's a monitor, not a historical factor). | SCORE | CANSLIM/institutional-footprint (Quantifying Rank 5). `mf_holdings` accumulation is Plan 0011 WS2.3 (unused gem) — depth accrues forward only. |
| d2 | **Superinvestor + bulk/block-deal footprint** | **IN-HOUSE** (`bulk_deals` 2021–2026, 51K rows, has history) + **NEEDS-RECIPE**: >1% superinvestor holders live in SHP annexures → WS3.4 data-recipe research (not yet done). | SCORE | Pabrai "cloning"; O'Neil smart-money. `bulk_deals` cross-reference is buildable now; the named-superinvestor registry is the WS3.4 delta. |

**Coverage honesty:** of ~11 headline criteria, **5 are queryable in-house today** (b1 level, b2, a3-payout, c2,
c3-proxy, d2-bulkdeals), **3 are in-house-derivable but need a builder + PIT depth** (a1, a2, c1), **2 need LLM
extraction** (b3, buyback split), **1 needs a data recipe** (d2-superinvestor registry), and the
capital-allocation/managerial-ability composites **exist but have no PIT history** (1 snapshot). The sleeve is
**buildable on gates + partial scores today**; full fidelity waits on WS5.1 (extraction) and a roiic/mcap PIT backfill.

---

## 3. ENTRY DISCIPLINE — the valuation gate ("wonderful company, fair price" as a number)

"Fair price, not cheap" — a value-trap-proof GARP gate, **entirely in-house** (no forward consensus EPS,
which we lack PIT — confirmed dead end). A name enters only when **all three** hold:

1. **PEG ≤ 1.0 (trailing, in-house).** trailing P/E ÷ 3y PAT CAGR (`quarterly_income`/`fundamentals_screener`).
   multibagger-research Rank 4 / Quantifying §3.1: PEG 0–1 delivered a 33% outperformance hit-rate and ~19%
   3y alpha in India; PEG > 3 → negative alpha. This is the load-bearing number.
2. **Earnings- or FCF-yield ≥ India 10y G-sec (~7%).** `fcf_yield_scores.fcf_yield` / `earnings_yield`.
   Greenblatt "earnings yield" floor — pay a bond-beating starting yield, so the return burden is not
   100% on future growth. Removes the priced-for-perfection tail (P/E 60x names where re-rating is spent).
3. **Reverse-DCF sanity: market-implied growth ≤ sustainable growth.** Implied growth from current EV/FCF
   unwound at ~12% cost of equity must be **≤ ROIC × reinvestment rate** (both in-house: `roic_scores`,
   capex/OCF from `annual_cash_flow`). Reject if the market already prices growth the franchise cannot
   self-fund. This is the "wonderful company, *fair* price" test made mechanical.

Quality gates (§2) are applied **first** (define the pond); the valuation gate selects entry timing *within*
it. This is the joint quality×value sort the research demands (multibagger-research finding #2: joint sort
7.4%/yr vs 3.5% side-by-side) — never value alone (traps) nor quality alone (over-pay).

---

## 4. CONSTRUCTION + relationship to the existing multibagger sleeve

- **Name count:** **5–8 equal-weight** conviction names (per D6). Note the deliberate contrast with ADR 0040's
  **20–30**-name multibagger *basket*: that basket has *no selection skill* (score is noise, tail-lottery) so
  breadth buys the tail; Engine 2 *claims* selection skill (capital-allocation + owner-operator + moat gates)
  so concentration is the point, not a lottery. Name cap ≤ ~18% (concentration is the thesis; still bound tail risk).
- **Review cadence:** **quarterly**, aligned to shareholding-pattern filings + quarterly results, using ADR 0040's
  built rolling 3–6mo `_conviction_verdicts` monitor (HOLD / WATCH / REVIEW) with its **market-regime guard**
  (suppress REVIEW when NIFTY SMALLCAP 250 is ≥20% off peak — eject only *idiosyncratic* weakness).
- **Per-name kill criteria** (thesis-break, not price):
  - **HARD (sell regardless of tax):** pledge rises above 0 (b2 breach) · forensic `m_score_flag` → MANIPULATOR ·
    promoter holding falls materially below entry (skin-in-the-game gone) · governance-resignation cluster fires
    (`governance_resignation`, a validated MID red-flag). A fraud/pledge blow-up loses far more than the tax saved.
  - **SOFT (reassess, don't auto-sell):** roiic inflection reverses · ROIC fades below sector (moat break) ·
    valuation blows out (yield collapses far below entry / PEG ≫ 1 on de-growth).
- **LTCG-aware exit rule:** **hold winners indefinitely** — indefinite compounding + LTCG deferral *is* the engine.
  **No stop-losses** (ADR 0040: 81% of eventual 3x winners endure a ≥30% drawdown; a −30% stop cuts a 1.88x
  basket to 1.56x). For a **SOFT** trigger, never sell before the 12-month LTCG line unless the expected
  drawdown exceeds the STCG−LTCG wedge (~7.5pp) — the tax wedge is a standing hold incentive. **HARD** triggers
  override the tax clock immediately.
- **Relationship to the multibagger sleeve — recommendation: ABSORB.**
  Engine 2 **subsumes** the ADR 0040 multibagger holding sleeve rather than running a second overlapping sleeve.
  Rationale: (i) ADR 0040 already *killed the multibagger ranking* (regime-dominated, score is noise) — there is
  no selection product left to preserve, only the **gates**, the **no-stop discipline**, the **regime-guarded
  monitor**, and the **survivorship cohort machinery**, all of which Engine 2 reuses verbatim; (ii) both draw
  from the *same* junk-stripped pond (forensic + pledge + leverage + size gates). Concretely: Engine 2 is **one
  sleeve with two conviction tiers off one shared gate-set** — a **base layer** (the 20–30 equal-weight ADR-0040
  basket, tail-capture, breadth) and a **conviction layer** (the new 5–8 capital-allocation/owner-operator/moat/
  valuation-gated compounders). This avoids duplicated plumbing, reuses `_conviction_verdicts`, and keeps a
  single cohort-validation harness. (Running *alongside* as two independent sleeves is the rejected alternative —
  it would double the monitoring surface for no diversification the shared pond doesn't already give.)

---

## 5. VALIDATION PLAN — the honest interim test (forward validation needs years)

Forward proof is a ≥6mo→12mo paper track (D6). The **ex-ante** evidence that justifies the paper launch is a
**point-in-time cohort study on the survivorship-free universe** — the same instrument ADR 0039/0040 used, now
pointed at Engine 2's gates.

- **Universe:** `historical_universe` — **9 anchors 2018-04 → 2026-05** (2018, 2019, 2021, 2022×2, 2023×2, 2024,
  2026), each carrying **~30% delisted/untracked names** (sid NULL: 565–759 of ~1.6–2.7K per anchor). This is the
  true opportunity set including deaths — deaths get a **terminal return** (last-known ÷ anchor, floored −100%),
  which is precisely how the quality gate's **left-tail protection** becomes measurable.
- **Method:** for each usable anchor (2018/2019/2021/2022/2023), reconstruct Engine 2 as-of-then — forensic gate
  (`forensic_scores`, 164K rows, deep), size band (`close × shares` from `historical_universe` + `annual_balance_sheet`),
  capital-allocation + moat + valuation scores (`fundamentals_screener` FY2015+, `roic`) — take the concentrated
  **5–8**, the **20–30** base, and the ungated universe; measure forward return to today-or-delisting, split-adjusted
  (`corporate_actions` back to 2022; `apply_pit_adjustments`).
- **Report:** concentrated-8 TWR vs base-30 vs **BSE500 Total-Return, net-of-tax (LTCG 12.5%)**; ≥2x/≥3x hit-rates;
  and the decisive number for §1's claim — **left-tail mortality** (fraction hitting −50% / delisting) of gated vs
  ungated. If the gates don't cut left-tail mortality, the reconciliation is empirically empty regardless of mean return.
- **Pre-committed pass bar:** concentrated-8 beats BSE500 TR net-of-tax across the pooled 2018–26 anchors **AND**
  gated left-tail mortality is materially below the ungated universe. Fail → publish the negative result, keep the
  sleeve on paper (or drop), do **not** allocate real capital (honors guardrail 1 — no reverse-engineering to a target).
- **Known limitations (state them, don't paper over):**
  1. **Only 9 anchors** → wide error bars; this is direction, not a Sharpe.
  2. **Shallow shareholding pre-2022** (median ~7 quarters/sid) → the promoter-trend (b1-trend) and pledge (b2)
     gates degrade historically; run the cohort on the *robust* gates (forensic + size + capital-allocation +
     valuation) and note b1/b2 as a live-only overlay (matches multibagger-data-requirements' documented gap).
  3. **roiic/capital-allocation PIT depth = 2026 only** → a1/a2 need reconstruction from `fundamentals_screener`
     before they enter the historical cohort; until then run them live-only. `mf_holdings` (d1) is 3 snapshots →
     **live monitor, never a historical cohort input.**
  4. **Audit Data-F1 dependency (blocking).** `reconstruct_pit.py` does **not** intersect `historical_universe`
     into its eval frames (confirmed: only `backtest_pit`/`multibagger_cohort`/`survivorship_exposure` reference
     it) — so the monthly-panel numbers this charter leans on are still survivors-only. **WS2.8 must land** for the
     cohort study's forward returns to be trusted, and the cohort tool must pull from `historical_universe`
     directly (as `multibagger_cohort.py` already does), not from the survivors-only PIT frames.
- **Why the cohort can see what the monthly IC can't:** 2018–26 spans a **quality-led bear (2018–20) + a junk bull
  (2020–24) + a correction** — a fuller cycle than the monthly panel's bull-only 2022–26 window. If quality
  compounds through a cycle net-of-tax, the cohort is where it shows up; if it doesn't even here, §1's
  reconciliation is falsified and Engine 2 does not earn real capital.

---

## 6. Build sequence (post-charter, gated by this doc)

1. **WS2.8 first** (survivorship fix) — gates trust in everything below.
2. Cohort harness (reuse `multibagger_cohort.py`) on robust gates → §5 pass/fail. **This is the greenlight-to-paper gate.**
3. Capital-allocation + moat scorers (a1/a2/c1) with PIT reconstruction; extend DLM Pillar A, don't duplicate.
4. Valuation entry gate (§3) — all in-house.
5. Paper sleeve launch (5–8 + base layer), quarterly monitor reuse, cost+tax ledger (WS1.3), ≥6mo tracking (guardrail 4).
6. b3 (RPT/remuneration) + buyback split enter as scores once WS5.1 extraction clears ≥90% field accuracy.

---

*Charter only — no code/config/DB changes made (READ-ONLY dive). Files an ADR at build time (Plan 0011 WS3.5).*
</content>
