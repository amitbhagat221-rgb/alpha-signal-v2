# Multibagger Identification — Research Synthesis

> **What this is.** A cited, adversarially-verified literature review on what actually predicts Indian small/mid-cap "multibaggers" (3x–10x over 2–4 years), commissioned to inform the multibagger-model build. Read this before reviewing the implementation plan (`~/.claude/plans/i-was-going-theough-polished-dolphin.md`).
>
> **Method.** Deep-research harness, 2026-06-03: 5 search angles → 22 sources fetched → 92 claims extracted → **25 claims verified by 3-vote adversarial check** → **17 confirmed, 8 killed**. 104 agents, ~2.9M tokens. Each finding below carries its vote and primary source.
>
> **How to read confidence.** `3-0` = all three skeptics failed to refute (strong). `2-1` = one refuted (use with care). "Refuted" = the majority killed it — **do not act on it**.

---

## TL;DR — the bottom line

The evidence backs a **quality-gated value funnel with a hard forensic-accounting exclusion, weighted toward earnings growth over re-rating** — and the effect is *stronger in small caps*, which is precisely our target universe.

The single biggest design implication: prefer a **hurdle/filter funnel** (all-must-pass gates → threshold hurdles → composite rank), **not** a pure weighted-average of pillars. This mirrors how Marcellus actually funnels ~500 stocks down to ~13–15.

Two new factors are worth building immediately (we have the data): **gross-profitability-to-assets** (the anchor quality factor) and a **Beneish M-Score forensic gate** (a hard exclusion, not a soft input).

---

## ✅ Confirmed findings

### 1. Gross profitability is the strongest standalone quality predictor `[3-0, high]`
`Gross profitability = (Revenue − COGS) / Total Assets`.

- **2.7%/yr raw spread (t=2.15)** — the *only* one of seven quality measures with a significant standalone raw spread (ROIC 2.17 [t=1.16] and F-score 2.24 [t=1.69] are insignificant raw).
- **5.21%/yr FF3 alpha (t=4.65)** — the largest of the group; spanning tests show it **subsumes** ROIC, F-score, accruals/earnings-quality, and Graham/Grantham quality.
- **We do not compute this today** (we have ROIC/ROIIC/FCF-margin, not gross-profits-to-assets). **Buildable now** from the Screener feed's `sales` + `COGS`. → *Recommended NEW anchor factor.*

Source: Novy-Marx, *Quality Investing* (QDoVI) — [PDF](https://mysimon.rochester.edu/novy-marx/research/QDoVI.pdf)

### 2. Combine quality + value as a JOINT sort, not side-by-side sleeves `[3-0, high]`
- Combined quality+value long/short earned **7.4%/yr** vs **3.2%** (gross profitability alone), **3.8%** (book-to-price alone), and **3.5%** (the two pure strategies run side-by-side).
- Mechanism: a joint sort captures stocks loading moderately-high on *both* factors that a 50/50 mix misses — "buy cheap, but cheap *with a purpose*." Removes value-trap risk.
- **Design implication:** *gate* cheap small/mid-caps on quality (positive/improving ROIC, F-score, low accruals, deleveraging) rather than scoring value and quality independently and averaging. Corroborated by Asness/Frazzini/Pedersen *Quality Minus Junk* (positive in 23/24 countries).

Sources: [QDoVI](https://mysimon.rochester.edu/novy-marx/research/QDoVI.pdf), [abacademies (India QARP)](https://www.abacademies.org/articles/exploring-multibagger-opportunities-through-value-and-quality-investment-strategies-in-small-and-midcap-indian-stocks-17432.html)

### 3. Quality factors are markedly STRONGER in small caps `[3-0, high]`
Within the Russell 2000, **all seven** quality strategies generate significant 3-factor alpha. Measures with near-zero power market-wide become strong among small caps:

| Measure | Full-sample alpha (t) | Russell 2000 small-cap alpha (t) |
|---|---|---|
| Graham G-score | 1.69 (1.93, insig.) | **4.10 (3.92)** |
| Grantham | — | 3.58 (3.93) |
| Gross profitability | — | 3.85 (3.53) |
| Piotroski | — | 3.68 (3.38) |
| ROIC | — | 2.73 (2.08) |

- **Caveat:** US (Russell 2000), gross-of-cost. Capacity/liquidity in Indian SMALL/MICRO may erode net returns — this is what our net-of-cost promotion gate exists to test.
- **Design implication:** justifies running the quality stack *within* the SMALL/MID tier and expecting stronger signal than full-universe backtests suggest.

Source: [QDoVI Table 4 Panel B](https://mysimon.rochester.edu/novy-marx/research/QDoVI.pdf)

### 4. Piotroski F-Score is durable in emerging markets `[3-0, high]`
- High-minus-low F-Score: **~10%/yr international (2000-2018)**, **9.9%/yr developed-EAFE (0.79%/mo)**, **12.0%/yr emerging markets (0.95%/mo, t=9.6)** — comparable to US 10.03%/yr.
- Survives controls for size, book-to-market, momentum, operating profitability, investment. Concentrated in smaller firms but meaningful in large caps too (~0.30–0.40%/mo).
- **Caveat:** in-sample, long-decile spread (not net-of-cost), pre-2018; US-only F-score reportedly weakened post-2011.
- **We already compute & validate F-score.** Keep it as a primary quality gate; weight higher in SMALL than LARGE, consistent with the size concentration.

Source: Walkshäusl (2020), *Piotroski's FSCORE: international evidence* — [PDF](https://d-nb.info/121155211X/34)

### 5. Beneish M-Score as a HARD EXCLUSION GATE `[2-1, medium]`
Use a forensic-accounting filter as a **gate, not a soft composite input** — accounting red flags are common even among large Indian firms (~20%; 11 of 65 BSE-100 over 2011-16).

- **Threshold:** `M > −2.22` flags likely manipulators (stricter variant `−1.78`).
- **Formula (canonical Beneish-1999):**
  `M = −4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI + 0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI`
- **Indian-specific strongest predictors:** TATA (total accruals/assets, p=0.002), SGI (sales-growth index, p=0.059), DSRI (days-sales-receivables, p=0.021) — these overlap directly with our existing accruals-quality and working-capital factors.
- **Buildable today** — we have accruals, receivables, sales, COGS, inventory, payables in the 65-line-item feed.
- **Caveats:** the ~20% base rate is BSE-100 large-cap, *cumulative over 5yr* (not an annual or small-cap rate); the −2.22→this-paper attribution is inferred (vote 2-1).

Source: Shah et al., *Indian Journal of Finance* 2018 — [PDF](https://www.indianjournaloffinance.co.in/index.php/IJF/article/download/122796/99702/340936)

### 6. Earnings-drift (PEAD) is noise at the single-name level `[3-0 / 2-1, high]`
The apparent monotonic PEAD is largely an artifact of aggregation:
- SUE→return correlation is **0.693 across 10 deciles** but collapses to **0.007 at the firm level**.
- In the Good-News decile only **51.8%** of 13-week returns are positive (~52% hit rate); only 17.3% drift on all 13 weeks.
- After Bonferroni correction, the hedge return is significant in just **13.6% of 118 quarters** (though positive-signed in 95%).
- **Caveat:** a deliberately contrarian *unpublished* working paper; it does **not** overturn portfolio-level drift (Bernard-Thomas et al.). The load-bearing takeaway is **methodological**: evaluate earnings signals *cross-sectionally* (decile spreads), never as single-stock edges.
- **Maps to us:** confirms our prior memo — *don't re-attempt PEAD without a real earnings-announcement calendar* (data we lack). This is also the empirical signature of a fat-tailed, low-base-rate target generally: thin per-name edge, signal lives in cross-sectional averages and the tail.

Source: Katz, McCubbins & McMullin (2018), *PEAD: An Anomalous Anomaly* (Caltech) — [PDF](https://jkatz.caltech.edu/documents/28622/peads.pdf)

### 7. Weight earnings/cash-flow growth HEAVILY over starting-valuation re-rating `[3-0, high]`
Over long horizons total return converges to earnings growth (**R = G**); multiple re-rating dwindles.
- Marcellus CCP: **24% FCFE CAGR vs 28% price CAGR over 20yr** → ~85%+ of return from growth, only ~4pp/yr from re-rating.
- Marcellus "Consistent Compounders": **~34% weighted-avg ROCE (FY16-21), ~47% reinvestment rate**.
- Motilal Oswal "R=G": **≥20% PAT CAGR** as a shortlist hurdle.
- **Critical caveats:** (a) CCP is a hand-picked basket of ex-post **survivors** (Asian Paints, Titan, Pidilite) — *descriptive of winners, not a predictive base rate*; (b) price 28% slightly *exceeds* FCFE 24%, so some re-rating *did* occur — "mainly growth" is directional, not zero; (c) **at our shorter 2–4yr horizon, the same Motilal study admits fast wealth-creators' returns come from BOTH growth AND P/E expansion** — so re-rating still matters materially at our actual horizon. Don't zero it out.

Sources: [Motilal Oswal 30th Wealth Creation Study](https://www.motilaloswal.com/content/dam/mofsl-website-adobe/investor-relations/wealth-creation/wc30.pdf), [Marcellus CCP deck Feb-2022](https://marcellus.in/wp-content/uploads/2022/02/Marcellus_CCP_Presentation_Feb2022_b.pdf)

### 8. Recommended architecture: hurdle/filter funnel → composite rank `[synthesis, medium]`
A multi-stage funnel, **not** a pure composite-rank that lets a high growth score offset a forensic red flag:

- **Stage 1 — hard gates (all must pass):** Beneish `M < −2.22`; pledge/governance/dilution flags; deleveraging direction.
- **Stage 2 — threshold hurdles:** earnings growth ≥20% PAT CAGR; ROCE/ROIC above cost-of-capital *and rising*; positive/improving reinvestment runway.
- **Stage 3 — composite cross-sectional rank within SMALL/MID:** joint quality+value anchored on **gross-profitability, F-score, FCF-yield**, with growth weighted above starting-valuation re-rating.
- **Validate on tail-capture metrics** — top-decile hit-rate of names reaching ≥3x, decile lift, top-decile forward-return spread — **NOT** mean rank-IC.
- **Honest note:** no source directly A/B-tested hurdle-vs-composite *for multibaggers specifically*. This is a reasoned recommendation from the Marcellus funnel analogy + the value-trap and PEAD evidence — it **must be validated on our own PIT archive**.

Sources: synthesis of [Marcellus](https://marcellus.in/wp-content/uploads/2022/02/Marcellus_CCP_Presentation_Feb2022_b.pdf), [QDoVI](https://mysimon.rochester.edu/novy-marx/research/QDoVI.pdf), [Caltech PEAD](https://jkatz.caltech.edu/documents/28622/peads.pdf), [Motilal](https://www.motilaloswal.com/content/dam/mofsl-website-adobe/investor-relations/wealth-creation/wc30.pdf)

---

## ❌ Refuted — do NOT act on these (failed verification)

These were extracted from sources but **killed** in voting. Listed because they're tempting and wrong:

| Refuted claim | Vote | Why it matters |
|---|---|---|
| Trailing earnings growth is *insignificant* for predicting multibaggers | 1-2 | Verified evidence points the **opposite** way (R=G) — keep weighting growth |
| FCF-yield is the **#1** driver of multibagger outperformance | 0-3 | Do **not** over-prioritize FCF-yield on this basis |
| Optimal entry is **contrarian** (near 12-mo low after a 3–6mo decline) | 1-2 | Do **not** adopt a contrarian-entry rule |
| Survivorship overstates Smallcap-250 returns by 4.94pp / 82.5% turnover | 1-2 / 0-3 | Our ~4.4%/yr assumption is **neither confirmed nor bounded** — open |
| ~7% of top-500 became compounders over 17yr (a base rate) | 1-2 | No clean ex-ante base rate survived — must measure our own |
| Specific Indian value+quality backtest: 12.5% CAGR, Sharpe 0.34 | 0-3 | Don't cite this number |
| Coffee Can twin-filter → 20–30% p.a. with bond-like volatility | 1-2 | The *specific* return/vol numbers didn't survive |

> The first three all come from one source — the BCU "Alchemy of Multibaggers" working paper — whose entire striking thesis was refuted. **Discard it.**

---

## ⚠️ Caveats that frame everything above

1. **Best "numbers" come from marketing decks.** Marcellus CCP and Motilal studies describe ex-post **winners** — descriptive, not a predictive base rate. Don't treat 34% ROCE / 24-28% CAGR as forward expectations.
2. **Academic quality results are gross-of-cost, in-sample, pre-2018, developed-market.** Walkshäusl's EM slice (~12%/yr) is the closest India proxy. Net-of-cost capacity in Indian SMALL/MICRO is unproven — our net-of-cost gate must do the work.
3. **Beneish ~20% base rate** is large-cap, cumulative-over-5yr, not an annual small-cap rate. Small/micro manipulation rates are plausibly *higher* but unmeasured.
4. **PEAD source is a contrarian working paper** — use only for the methodological point (evaluate cross-sectionally), not to deny portfolio-level drift.
5. **Survivorship magnitude is OPEN** — the verified evidence neither confirms nor bounds our 4.4%/yr.

---

## ❓ Open questions — must be measured on OUR PIT data (research couldn't answer)

1. **Actual ex-ante base rate & time-to-multibag** for ≥3x/5x/10x over 3–5yr in Indian SMALL/MID, plus realistic top-decile hit-rate / false-positive rate. (Descriptive winner stats exist; no clean ex-ante base rate survived voting.)
2. **True survivorship-bias correction** for our current-names-only panel (the 4.4%/yr is unbounded by evidence) — needs an independent delisting/index-deletion reconstruction.
3. **Does the hurdle/filter (all-must-pass) architecture actually beat a soft composite-rank** for capturing the multibagger tail on *our* universe? Untested — must A/B on the PIT archive with tail-capture metrics.
4. **Which India-specific catalyst/ownership signals** (order-book/capex visibility like HBL's Kavach win, SME-to-mainboard migration, PLI/policy tailwinds, FII/DII/MF accumulation, delivery-volume/bulk-deal footprints) add measurable forward decile lift? **None were covered by a surviving claim** — they remain unvalidated hypotheses.

---

## What this changes in the build plan

The research **refines, doesn't overturn**. Material changes vs. the originally-approved plan:

| Originally approved | Research-refined |
|---|---|
| 6-pillar weighted-average composite | **3-stage funnel**: hard gates → threshold hurdles → composite rank |
| Reuse existing quality factors only | **Add 2 new factors (buildable today):** `gross_profitability` (anchor) + `beneish_m_score` (exclusion gate) |
| Average quality + value pillars | **Joint sort** — quality *gates* cheap names (no value traps) |
| Equal-ish pillar weights | **Growth weighted above re-rating** (keep some re-rating for the 2–4yr horizon) |
| Cohort study for validation | **Confirmed correct** — tail-capture metrics over mean rank-IC |
| (n/a) | **Drop:** contrarian entry, PEAD re-attempt, FCF-yield-as-king |

**Unchanged and validated:** SMALL/MID focus, separate screen (out of `daily_picks`), long-horizon cohort validation, honesty about thin samples + survivorship.

---

## Source ledger

**Primary, claim-bearing:**
- Novy-Marx, *Quality Investing* — https://mysimon.rochester.edu/novy-marx/research/QDoVI.pdf
- Walkshäusl (2020), *Piotroski FSCORE international* — https://d-nb.info/121155211X/34
- Shah et al., *Beneish in India*, Indian J. Finance 2018 — https://www.indianjournaloffinance.co.in/index.php/IJF/article/download/122796/99702/340936
- Katz et al. (2018), *PEAD: An Anomalous Anomaly* (Caltech) — https://jkatz.caltech.edu/documents/28622/peads.pdf
- Motilal Oswal 30th Wealth Creation Study — https://www.motilaloswal.com/content/dam/mofsl-website-adobe/investor-relations/wealth-creation/wc30.pdf
- Marcellus CCP deck (Feb 2022) — https://marcellus.in/wp-content/uploads/2022/02/Marcellus_CCP_Presentation_Feb2022_b.pdf
- abacademies, *Value & Quality in Indian small/midcap* — https://www.abacademies.org/articles/exploring-multibagger-opportunities-through-value-and-quality-investment-strategies-in-small-and-midcap-indian-stocks-17432.html

**Methodology / factor-combination:**
- AlphaArchitect, *combine vs separate factor exposures* — https://alphaarchitect.com/should-investors-combine-or-separate-their-factor-exposures/
- SSRN 2460551 (factor timing/methodology) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- *Multi-Factor Investing: Mix, Integrate or Sequential Screening* — https://www.researchgate.net/publication/386371516

**Refuted (do not cite for numbers):**
- BCU "Alchemy of Multibaggers" working paper — https://www.open-access.bcu.ac.uk/16180/1/The%20Alchemy%20of%20Multibagger%20Stocks%20-%20Anna%20Yartseva%20-%20CAFE%20Working%20Paper%2033%20(2025).pdf
- arXiv 2603.19380 (Smallcap-250 survivorship) — https://arxiv.org/pdf/2603.19380

---

*Generated 2026-06-03 from deep-research run `wf_c7cc258e-b9a`. Raw verified JSON archived at the run's task output. This is research input, not a decision — the build plan it informs lives at `~/.claude/plans/i-was-going-theough-polished-dolphin.md`.*
