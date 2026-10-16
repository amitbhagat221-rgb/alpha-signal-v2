# Research 0008 — the designers' response to the independent critique

To: the reviewer of [research 0008](0008-multibagger-critique-findings.md). From: the Alpha Signal multibagger desk (plan 0026). 2026-10-16.

Thank you: the critique was specific, and it was right on the points that matter most for real money. We ran every test you proposed, with your pass bars copied before anything ran. The code is `tools/mb_critique.py` (pre-registration in its docstring); the outputs are `data/lh/v2/mbc_results.json`. Below, each of your points: what we found, and what we changed.

## Summary

| your point | test (your bar) | result | verdict |
|---|---|---|---|
| 1 wrong benchmark | top 30 vs the **equal-weight pond** (≥ +5 %/yr, t ≥ 1.5) | survivors, full thesis: **+8.7 %/yr, t 2.25**, 12 / 12 starts. Full market incl. delisted, price-only score: **+9.6 %/yr, t 1.89**, 12 / 12 starts | **pass**: the selection edge is real, not the size premium |
| 2 nominal deflation | honest DSR, 67 counted trials, null variance (≥ 0.90) | **0.764** (0.888 on the trials' own Sharpe spread; 0.977 at N_eff 7.5) | **fail**: you were right |
| 3 capacity | book at 3× and 10× (≥ +5 %/yr at 3×) | ₹90 lakh: +11.9 %/yr; ₹3 crore: +10.4 %/yr | **pass**, within the impact model |
| 4 halving result too good | full-market halving lift (≤ 0.70) | **0.72**; lift of falling to ≤ 0.3x: **1.01** | **fail**: the tail protection was a survivor effect |
| 4.6 quarterly look-ahead | Tickertape lag 60 → 90 days (within 2 points) | +12.7 → +11.0 %/yr | **pass** |
| 4.1 tested pond ≠ live pond | pond rebuilt on the live market-cap source | 8–10 % more stocks per date; top 30 vs pond still **+8.6 %/yr, t 2.31** | **pass** (see below) |
| test 5 promoter overlay | phase 1b accept rule | −0.8 pts/yr, no half better | rejected |
| test 6 cash-conversion gate | accept rule; how many winners it removes | −1.6 pts/yr; removes 8 % of the pond and 10 % of later 3x outcomes | rejected |

**What survives:** a stock-selection edge over an equal-weight small-cap basket of about +9 %/yr. It holds with delisted stocks included, with a later quarterly lag, and on a pond built like today's.

**What does not:**
- the claim that the shortlist avoids blow-ups;
- the claim that the evidence clears a multiple-testing bar.

The desk stays grade C. Its label now says why.

## Your problems, one by one

**1. Benchmark.** Fair challenge, wrong conclusion. The equal-weight pond beats the NIFTY SMALLCAP 250 by only about 1–3.5 %/yr (survivors 16.6 % vs 13.1 %; full market 14.9 % vs 14.0 %). The top 30 beats the pond by +8.7 / +9.6 %/yr. So most of the excess is selection, not the size or equal-weight premium.
- **Caveat:** on the full market (price-only score) the per-start t ranges from 0.5 to 3.5, and the worst 12 months against the pond is −60 % (the April 2016 start). The survivors version is steadier (worst −21 %, every start +3.8 to +15 %/yr). We now show the pond as a second benchmark.

**2. Multiple testing.** Conceded.
- Counting every configuration run on this window gives 67 trials: the four first books, 31 re-test variants, 6 funnel variants, the 1d variants, the retired quality funnel, and 10 for the trait study that chose the parts.
- The trials' Sharpe ratios spread less (sd 0.073) than one estimate's sampling noise under the null (0.091), so they are near-clones, as you said. With the null variance the DSR is 0.764. Our earlier 0.961 used the clones' own spread and left out skew and kurtosis.
- The monthly Sharpe is 0.28 (0.97 annualised), skew 0.50, kurtosis 2.85, over 121 months.
- **We record it as you asked:** the pre-set T1 bar failed 4 of 8, and the grade rule that replaced it was ours. That was a goalpost move, and the label now says so.

**3. Capacity.** Within our impact model the edge survives 10× (+10.4 %/yr at a ₹3 crore book). But the model is a square-root curve calibrated on our own ₹1 lakh fills; it says nothing about leaving a stock locked at its lower circuit. So we take your cap, not our model:
- each name at most 5 % of its 20-day traded value;
- the book stops adding when any name exceeds 10 %;
- the desk is sized as a satellite of at most ₹3 crore.

**4. Survivors and halving.** Conceded. On the full market including delisted stocks, the price-only top 30 halves 0.72× as often as the pond (your bar: 0.70) and falls to ≤ 0.3x **just as often** (1.01×). The 0.28× figure came from survivors plus the fundamental parts, which cannot be tested on delisted names. We withdraw the claim that the shortlist avoids blow-ups.
- **Consequences:** "no stop-loss" can no longer lean on it. It rests only on ADR 0040's separate finding that price stops eject eventual winners. Process-based exits (below) now carry the risk control.

**5. Ten hand-picked names.** Agreed. We built your three-book design (below), so the human stage is measured from day one.

## Your "implausible numbers"

- **Historical pond ~300 vs 755 live.** Your arithmetic was right; the cause is mostly market growth, not coverage.
  - The pond grew from 124 stocks (Oct 2016) to 459 (2021) and 679 (2026), as more companies cleared the ₹0.5 crore liquidity floor and the deflated cap.
  - Rebuilt on the live market-cap source it is only 8–10 % larger per date (2016: 163, 2021: 498, 2026: 778), and the result holds (+8.6 %/yr over the pond, t 2.31).
  - It is still a population the score saw in fewer, thinner years, which is the regime caveat again.
- **Lifts 1.34 vs 1.24.** Two calculations: the funnel table divides totals across dates, T1 averages per-date ratios. Not an error, but you are right that the gap is as large as the effect.
- **DSR vs t.** Conceded, see 2.
- **"77 % under ₹1,000 crore" without the base.** The base was 46 % of the 588 (272 stocks), so the lift is 1.67×. Likewise:
  - P/B ≤ 1: 24 % of the pond, 35 % of the 10x stocks, lift 1.47×;
  - ROCE ≥ 18 %: 25 % of the pond, 16 % of the 10x stocks, 0.65×.
- **sd ≈ 20 %/yr, so two years cannot separate the strategy from zero.** Agreed. This is why the forward kill rules below are about process and relative performance, not about proving the edge.
- **Quarterly lag.**
  - NSE results are timed at their first filing (`filed_at`).
  - Tickertape quarters were assumed known 60 days after quarter end; at 90 days the result moves −1.7 points (pass).

## Your open questions

1. **How t 1.90 is computed:** per start, on that path's non-overlapping annual excess (9–10 points), then the median across the 12 starts. It is not pooled. But the 12 starts overlap heavily, so the real evidence is about one 10-year path.
2. **Delisted names:** valued at their last traded close, which is kept, not dropped.
3. **Base shares:** above.
4. **Industry:** today's `stocks.industry` is applied historically. This is a small classification look-ahead we cannot remove without dated classification data; it touches only the industry-momentum part.
5. **The 150-day annual lag:** conservative for timely filers (annual results are due within 60 days of the year end). Restatements are a real risk: Screener keeps the latest restated figure, so the cheapness part can see corrected numbers. Unfixed; noted.
6. **Football field:** adopted.
   - Cost of equity now rises with smallness: 14 % at ₹20,000 crore and above, 20 % at ₹500 crore and below, +1 point below ₹1 crore a day of trading.
   - The DCF shows its terminal-value share and is flagged low-confidence above 75 %.
   - Reverse DCF leads; mid-cycle EV/EBITDA uses the median of the last 3 years.
   - EV/Sales and peer EV/Sales are added for loss-makers.
   - Analyst targets are shown only when at least 3 analysts cover the stock.

## What we changed

1. **Three paper books from day one:** an equal-weight pond, an equal-weight top 30, and the investor's 10, marked monthly at realistic costs. Each carries your kill rules:
   - **score kill:** the top 30 trails the pond by > 5 points over 24 months;
   - **human kill:** the 10 trail the 30 by > 10 points, or their share of names up ≥ 50 % is below the 30's;
   - **risk kill:** any rolling 12-month excess below −35 % halts new buying;
   - **capacity kill:** any name above 10 % of its 20-day traded value.
2. **Sizing:**
   - the 10 at most 10 % of the equity portfolio;
   - each name at most 10 % of the book at cost and at most 5 % of its 20-day traded value;
   - the desk at most about ₹3 crore.
3. **Name exits (process, not price):**
   - **Automatic exit at the next liquid session:** statutory-auditor resignation, GSM/ESM entry, or results not filed on time. These rarely reverse, and waiting risks being locked in.
   - **Review within a week:** pledge above 50 %, or promoter stake down more than 5 points in two quarters. Our own event study found these to be false alarms 44–57 % of the time as return predictors.
4. **The label** on the desk now reads: *grade C — beats an equal-weight small-cap basket by about 9 %/yr in a 2016–26 backtest that includes delisted stocks, but does not clear a multiple-testing bar (DSR 0.76) and does not avoid blow-ups; a shortlist for judgement, measured live against the basket.*
5. **Not adopted:** the promoter-buying part and the cash-conversion gate. Both failed the accept rule; the gate would have removed 10 % of later winners.

If you have a second round, the questions we would most like challenged are these:
- Is the full-market price-only result (+9.6 %/yr, t 1.89, but a −60 % worst year against the pond) better read as momentum-crash risk than as an edge?
- What would you accept as evidence for or against the fundamental parts, given that no delisted fundamentals are available?

---

## Round 2 (2026-10-16, after the reviewer's second reply)

Code: `python -m tools.mb_critique crash fundinc` → `data/lh/v2/mbc_round2.json`.

**1. The −60 % worst 12 months against the pond is a momentum crash. You were right.**
- **The window:** April 2020 → April 2021 (the full-market price-only book, April 2016 start).
- **The pond** rose +146 % in it, its best 12 months on that path.
- **Ranked by 6-month momentum at the start**, the pond's fifths earned:

  | 6-month momentum fifth | 12-month return | share that tripled |
  |---|---|---|
  | bottom | +142 % | 33 % |
  | 2nd | +134 % | |
  | 3rd | +116 % | |
  | 4th | +83 % | |
  | top | +69 % | 21 % |

  Bottom minus top was +72 points; in a typical window it is −18 (90th percentile +3). That is Daniel & Moskowitz (2016) after a bear bottom.
- **The risk kill would have fired** in exactly that month (April 2021, pond +139 %). We adopted your exemption: the paper books' risk kill now halts new buying only if the pond itself did not rise more than 50 % in the same window (`config.MB_THESIS["kill"]["risk_crash_pond_up"]`, tested).
- **The label** now names momentum-crash risk as the forward risk to carry.
- **The survivors-thesis book's worst window** (−21 %, March 2025 → March 2026, pond +2 %) is not a crash, and the risk kill never fires on its paths.

**2. The capacity pass:** agreed. It runs inside the same square-root model. The adopted cap (≤ 5 % of 20-day traded value, stop adding at 10 %, desk ≤ ₹3 crore) is the control. The test only says costs do not eat the edge before the cap binds.

**3. The promoter test's window:** stated now. It ran on starts January–December 2020, because `promoter_trend_4q` exists only from December 2019 in our point-in-time panel. So its baseline (+18.9 %/yr excess) is the later, stronger window, not the 2016–26 headline (+12.7 %). Its rejection compares like with like.

**4. Evidence for the fundamental parts.** We ran your first route, and the answer is uncomfortable:
- On the same survivor pond, the full thesis earned 25.8 %/yr; a price-only score (smallness by liquidity, 6-month momentum, 52-week position) earned 25.3 %/yr.
- **The fundamental parts' increment is +0.0 %/yr** (t 0.39, positive in 6 of 12 starts).
- **Your bias bound:** the full-market pond delists 3.0 %/yr, but the median delisted pond stock ended near its entry price (mergers and buyouts more than collapses). So at twice the rate the bound is about 0. Even assuming total losses (−6 %/yr), it can only lower an increment that is already zero.
- **Reading:** the return edge over the pond is size + momentum + nearness to the 52-week high. Cheapness, the latest quarter and industry momentum add nothing measurable to returns. On survivors they cut the halving rate (0.28 vs 0.59), but that is the claim we could not verify with delisted names.
- **What we did:** we keep the five-part score live for now. It costs nothing in return; the fundamental parts carry the human stage's reading of each card; and the forward books will show it. The cockpit label says the edge is the price parts.
- **For the investor:** whether to simplify to the price-only score is a decision (plan 0026 D6). The forward pond / top-30 / held books are the clean test you named.

**5. Industry look-ahead and restated Screener figures:** still open, as you said, and not worth fixing at this size.

## Round 3 (2026-10-16): D6 pre-registered, as you asked

- **A fourth paper book**, `price30`, started 2026-10-16 beside the pond, the five-part top 30 and the investor's 10. It holds the 30 best stocks on the price parts alone, inside the same pond.
- **The two top 30s share only 4 of 30 names.** So your point stands that the fundamental parts change the ranking a lot even when they do not change the backtest return.
- **The rule, fixed before any forward data:** after 24 months, five-part top 30 minus price-only 30, cumulative:
  - above +3 points: keep the five-part score;
  - below −3 points: switch the desk to price-only;
  - within ±3: the simpler price-only score wins.
- **Where it lives:** `config.MB_THESIS["kill"]["d6_pts"]`, `tools/mb_paper.py`, tested. It is shown with the kill rules on the cockpit's Held tab.
- **The halving caveat:** agreed. The survivors' 0.28 vs 0.59 is the only evidence for the fundamental parts, and the label does not use it.
