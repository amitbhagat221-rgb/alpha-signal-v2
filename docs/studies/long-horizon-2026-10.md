# A model that gives stocks time — verdict (Plan 0024) — 2026-10-12

Read-only study. Nothing live changed: no weight, pick, book, schema or cron. Step notes are in [`long-horizon-2026-10/`](long-horizon-2026-10/) (01 horizon, 02 costs, 03 design, 04 slow model, 05 book, 06 re-derivation, 07 audit). Numbers are in `data/lh/*.json` / `*.csv`. The pass bars are the ones fixed in [plan 0024](../plans/0024-long-horizon-model.md) before any result. None were moved.

## Verdict per tier

| tier | verdict | in one line |
|---|---|---|
| **LARGE** | **FAIL → the index** | The slow model has no out-of-sample ranking skill (OOS 6-month IC t −0.11). The best long-hold book is close to holding the top half of the index. |
| **MID** | **FAIL → the index** | The slow model ranks MID stocks well (OOS t 5.68), but the skill is at the bottom of the list, not the top. A long-only book of its top names earned nothing reliable. |
| **SMALL** | **FAIL → the index** (closest miss) | The slow model ranks well and the skill reaches the top names. The best long-hold book beat the Smallcap 250 by +18.3 %/yr after costs and tax, but with t 1.81. The plan needs a t of about 3.5 before the 48-variant haircut. The result is not proven, and +18.3 % is an upper, fragile estimate. |

**No tier passes, so no ADR is proposed.** By the plan's own rule, real money in each tier belongs in the index, and the model stays a research and screening tool.

Not one of the 144 book variants came close. The highest raw t anywhere in the grid was 2.61 (SMALL), and that variant failed the holding and turnover bars too. After the haircut for 48 tries, every tier's best t is 0.00. The independent re-derivation and the adversarial audit both confirm the fail. Every bias the audit found flatters the books, which makes the fail firmer, not weaker.

**"Fail" here means "not proven", not "proven worthless".** In SMALL, 47 of 48 variants beat the index after costs and tax (grid median +9.8 %/yr, median t 1.35). But 52 months of noisy returns cannot tell that apart from luck at the bar the plan set. The [arithmetic](#how-long-it-would-take-to-prove) shows why: even if the edge were real and as large as the backtest says, proving it at this volatility takes years, not months.

## The four questions, one paragraph each

**H1: are there slow factors?** **Only in SMALL, and fewer than step 1 said.** Step 1 reported "passes in all three tiers". The audit showed its t-stats treat about 77 overlapping 6-month windows as independent, when there are really about 13. Counted honestly, only SMALL `cons_beat_rate_4q` survives the multiple-testing haircut at 6 months, and LARGE and MID lose all their slow factors. H1 is descriptive only, and no decision rests on it alone.

**H2: does a slow composite work on months it never saw?** **Yes in MID and SMALL, no in LARGE.** OOS 126-session rank IC, Newey-West t: MID `slow_select` 5.68, SMALL `slow_select` 3.29, SMALL `slow_icw` 3.63, LARGE −0.11. This holds under a 24-month factor floor, a 12-month embargo, 4 factors instead of 8, without the unverified consensus factor (SMALL 3.21), without the macro betas (MID 2.89), and with the missing SMALL stocks added back (3.21). It is thinner on strictly non-overlapping windows (median t 3.03 MID, 2.52 SMALL; lowest offset 2.55 and 2.30).

**H3: does a long-hold book earn after costs and tax?** **No tier clears the bar** (details below).

**Costs:** the real Zerodha delivery cost is far below the placeholders. One-way at ₹1 L: LARGE 15.7 bps, MID 17.9 bps, SMALL 30.5 bps, against 30 / 50 / 150 bps in `config.TIERS`. About 10 bps of every trade is STT, which only trading less can reduce.

## The best book in each tier (H3)

All three use the `slow_select` out-of-sample scores, cover 52 months (2022-06 → 2026-10) and start with ₹10 lakh.

| | LARGE | MID | SMALL |
|---|---|---|---|
| rule | quarterly · top 20 · sell below 80 · raw score · 6-month min hold | monthly · top 15 · sell below 45 · raw · 6-month hold | monthly · top 10 · sell below 30 · 3-month average score · 12-month hold |
| book CAGR, before / after tax | 16.85 % / 15.20 % | 25.21 % / 22.19 % | 39.50 % / 35.10 % |
| index CAGR, before / after tax | 8.88 % / 8.15 % (NIFTY 50 + dividends) | 18.71 % / 17.02 % (tier EW to 2023-05, then Midcap 150) | 18.47 % / 16.79 % (Smallcap 250 + dividends) |
| **excess after tax** | **+7.05 %/yr** | **+5.17 %/yr** | **+18.30 %/yr** |
| t (Newey-West) → after the 48-variant haircut | 1.26 → 0.00 | 1.44 → 0.00 | 1.81 → 0.00 |
| rough 95 % range of the mean excess (± 1.96 SE, before haircut) | −4.0 % to +18.3 % | −1.7 % to +11.4 % | −1.4 % to +34.8 % |
| median holding (Kaplan-Meier) | 27.0 months | 10.1 months | 12.9 months |
| one-way turnover | 26 %/yr | 72 %/yr | 88 %/yr |
| worst 12-month excess | −13.4 % | −6.2 % | −12.2 % |
| costs paid | 15.2 bps a year (₹10,027) | 35.3 bps a year (₹27,884) | 105.4 bps a year (₹99,213) |
| tax paid over 4.3 years | ₹1,09,616 | ₹2,19,124 | ₹3,56,706 |
| share of gains taxed long-term | 92 % | 65 % | 98 % |
| bars met | hold, turnover, worst-12m; **fails t** | hold, turnover, worst-12m; **fails t** | hold, turnover, worst-12m; **fails t** |

The range row is the mean monthly excess × 12 (LARGE +7.17 %, MID +4.81 %, SMALL +16.71 %) ± 1.96 standard errors. It is for the *best* of 48 variants, so it is biased upward; the honest centre is lower.

**Why SMALL's +18.3 % should not be taken at face value:**
- **It depends on which score set is used.** On the same rule, the other slow score set (`slow_icw`) earned only **+3.6 %/yr** (t 0.73), although it had the *higher* out-of-sample IC in H2. Choosing `slow_select` for the grid was made after H2 and was not pre-registered.
- **Survivorship.** Against the tier's own equal-weight average, the excess is +15.0 %/yr (t 1.57). The audit found the SMALL equal-weight average is itself overstated by about 2.8 %/yr. The cause is mostly stocks that are still listed but sit outside our 2,448 universe (−2.09 %/month vs listed SMALL, t −4.16), not delistings.
- **Not every year.** The book lost to the index in 2023 (−2.4 %).
- **The typical variant is weaker.** The grid's median was +9.8 %/yr with t 1.35.

**MID: the claimed number is if anything a little low.** The re-derivation got +8.09 %/yr before tax vs +6.50 % claimed. The cause is one month (2024-05 → 06) in which some stocks are marked a session late. A partial Saturday session (2024-05-18) shifts the shared label's exit from 2024-06-04, election-result day, to 06-05. Its t is 1.92 before tax, still far from 3.5. The fail stands.

### How long it would take to prove
The t-stat grows with the square root of time. If SMALL's best book kept exactly its backtest return and volatility:
- a single pre-registered variant would need about **63 months** to reach t 2.0;
- clearing the plan's 48-variant bar (raw t about 3.5) would need about **195 months**.

At the grid-median variant (t 1.35 in 52 months), t 2.0 takes about **114 months**. So a forward paper test can only confirm a large, persistent edge, and only slowly.

## What a long-hold book looks like in practice
This is what the machinery would look like if Amit runs any stock bet at all, using the SMALL best variant as the template. The rules themselves work as designed. The edge is what is not proven.

- **Names:** 10, equal weight at purchase. Winners are never trimmed.
- **Review:** once a month, on the first trading day after the month-start anchor. In 52 months the book made 95 trades, about 22 a year, or 1–2 a month.
- **Buy:** the best-ranked unheld names in the top 10 of the 3-month-average score. Never buy a name with a forensic red flag (`forensic_penalty` ≤ −0.20).
- **Sell:** only when a holding falls below rank 30 *and* has been held 12 months. A red flag forces an immediate sale.
- **Tax deferral:** if a winning sale would turn long-term within 6 weeks, wait. All 21 deferred sales turned long-term before they were sold. Deferral is worth about 3 points a year after tax in SMALL (+15.2 % without it vs +18.3 % with it).
- **Typical holding:** 12.9 months (median). One-way turnover is 88 % a year.
- **Costs and tax:** costs are about 105 bps of the book a year, twice the tier's median per-trade cost because the book buys less liquid names. Tax cut the book's CAGR from 39.50 % to 35.10 %, a 4.4-point drag, against a 1.68-point drag for the index (taxed only on the final sale). 98 % of realised gains were long-term.
- **Expected excess after tax:** not established. The point estimate is +18.3 %/yr on the best variant, with a rough 95 % range of −1.4 % to +34.8 % before any haircut. The grid median is +9.8 %/yr, and the other slow score set on the same rule gives +3.6 %/yr. Zero cannot be ruled out.

**Compared with today's band.** On the same scores, a monthly 5-in / 8-out book (no hold, no deferral) turned over **305–921 %/yr**, realised almost all its gains short-term, and in SMALL paid **₹6.64 L in costs on a ₹10 L book**. Today's real daily band is worse still: about 189 % a month. Across the six score-set × tier pairings, the long-hold rule beat the 5/8 band every time:

| score set | LARGE | MID | SMALL |
|---|---|---|---|
| `slow_select` | +7.05 % vs −6.2 % | +5.17 % vs −4.2 % | +18.30 % vs +12.3 % |
| live weights | +9.1 % vs +8.6 % | +10.5 % vs +9.1 % | +9.5 % vs +6.8 % |

The long-hold rule was the best of 48, so part of that gap is the choice. Whatever the edge, nobody should follow the 5/8 daily band with real money.

## Factors that matter at long horizons
- **SMALL.** On non-overlapping 6-month windows, the following hold:

  | factor | t | note |
  |---|---|---|
  | `cons_beat_rate_4q` | 4.51 | survives the haircut at effective df; Yahoo estimates still `pit_unverified` |
  | `value_composite` | 4.43 | |
  | `sector_tilt` | 3.66 | live |
  | `closing_strength_1m` | 3.35 | |
  | `position_52w` | 3.17 | gets stronger on the full market |
  | `mom_6m` | 2.99 | gets stronger on the full market |
  | `announcement_car` | 2.86 | live |

  The out-of-sample model chose `cons_beat_rate_4q` and `value_composite` in every month and `sector_tilt` in 83 % of months.
- **SMALL, fast and not slow:** `delivery_anomaly_z`, today's largest SMALL weight (0.24). Its t goes from 7.15 at 1 month to 2.41 at 6 months and 1.14 at 12.
- **SMALL, does not hold on the full market:** `avg_delivery_pct_30d`, a live weight of 0.12. Its 6-month t goes from 4.00 to 1.75 once stocks outside our universe are added, and to 1.31 with BE/BZ names.
- **MID:** the slow signal is a "weaker firms did better" pattern: negative `z_score`, `interest_coverage`, `roic` and `gross_profitability`, plus `gold_beta` and −`inr_beta`. It sorts the bottom of the tier, not the top. The top 15 beat the tier by only +0.67 % over 6 months (t 0.31). The audit found survivorship does **not** explain it in 2022-26, so the cause is unknown. `piotroski_f` looks strongly slow, but has only 20 anchors (since 2024).
- **LARGE:** nothing with selection skill. The only H1 "pass", `metals_beta`, is a metal-price bet, and its lowest-offset non-overlapping t is 0.75.

## What changes vs today's model
**Nothing changes automatically.** No tier passed, and the plan forbids weight or book changes without Amit's approval. What this study tells the existing model:

1. **The live weights carry hindsight.** They beat every out-of-sample method in every tier (OOS 6-month IC t: LARGE 2.79, MID 7.74, SMALL 9.37), but they were chosen on this history. In LARGE every honest method is near zero, which supports the existing "LARGE → index" view.
2. **SMALL leans on a one-month signal.** `delivery_anomaly_z` (0.24) is fast. `avg_delivery_pct_30d` (0.12) loses its 6-month evidence on the full market and goes on the factor-audit list.
3. **The cost placeholders are 2–5× too high.** `config.TIERS` has 30 / 50 / 150 bps; the measured one-way cost at ₹1 L is 15.7 / 17.9 / 30.5 bps. The [names-per-tier](names-per-tier-2026-10.md) study found SMALL net returns hinge on the 150 bps placeholder (break-even about 95–150), so it should be re-read with these costs.
4. **The shared label has a calendar bug.** `pit.forward_returns` counts sessions in each stock's own price rows. Two dates shift exits by one session: the partial 2024-05-18 Saturday session (1,411 of about 1,660 stocks) and a stray zero-volume RST row on 2026-09-14, an NSE holiday. It moved one MID month around the 2024 election result. The fix is to count sessions on the market calendar and drop zero-volume rows on exchange holidays.

## Verification
- **Independent re-derivation (06): confirmed, with minor issues.**
  - **H1:** every IC and t checked matches exactly.
  - **H2:** the out-of-sample scores match row for row (76,708 rows, largest difference 0.0).
  - **H3:** SMALL reproduces at +21.22 % vs +21.03 % and LARGE at +7.88 % vs +7.96 % (pre-tax with costs). MID comes out at +8.09 % vs +6.50 %, outside tolerance, from the label bug above. The claimed MID figure is the more cautious one.
- **Adversarial audit (07): confirmed, with issues; no pass or fail reversed.**
  - **Major:** H1 is overstated by overlap.
  - **Major:** survivorship in SMALL is larger than assumed, and it comes from the 2026 universe choice more than from delistings.
  - **Minor:**
    - the MID survivorship explanation is not supported;
    - `slow_select` was chosen for the grid after H2 (SMALL is +3.6 % on `slow_icw`);
    - the H2 design parameters were not pre-registered, though H2 still clears a 4-way haircut;
    - `cons_beat_rate_4q` is `pit_unverified`;
    - the benchmark dividend credit is slightly generous, which is conservative for the book.
  - **No issue was critical.** None could turn a fail into a pass, because each one makes the books look better than they are.

## Caveats
- **One short window:** 52 out-of-sample months (2022-06 → 2026-10). The 2020 crash is in training only. A 12-month minimum hold leaves about 4 independent holding periods.
- **Survivorship:**
  - Fundamentals cover today's 2,448 stocks only.
  - In SMALL, the stocks left out did about 2 %/month worse.
  - The books never held a stock that later disappeared. If the model had picked missing names at their share of the tier, SMALL's book would be flattered by up to about 2.8 %/yr.
- **Hindsight in the candidate list:** the walk-forward chose from today's factor registry, and some of those factors were added because they worked on this history.
- **Costs** for stocks under ₹2 cr ADTV rest on a spread ratio borrowed from more liquid stocks. The stress case (×2) still left SMALL at +17.5 %/yr, t 1.76.
- **Tax** uses today's rules in every year (20.8 % short-term, 13.0 % long-term above ₹1.25 L, dividends 31.2 %). Using the rules in force at the time gives SMALL +18.4 %/yr.

## Recommended next step
1. **Follow the plan's rule: each tier is the index for real money** (NIFTY 50, NIFTY MIDCAP 150, NIFTY SMALLCAP 250 funds). Do not follow the daily 5/8 paper book with real money.
2. **If Amit wants a small stock bet beside the index, run it only with the long-hold rules**, never the 5/8 band. Run it as a pre-registered forward paper test of exactly one variant: SMALL · monthly · top 10 · sell below 30 · 3-month average · 12-month hold · tax deferral, on `slow_select` scores retrained each month. Fix the bar before it starts. Expect it to need about 5 years to say anything, so treat it as a disclosed bet with an unproven edge, not a model result. This needs Amit's approval and a plan; nothing is built yet.
3. **Housekeeping, each as its own checklist item:**
   - fix the session-counting bug in `pit.forward_returns` (market calendar, drop holiday rows), then rebuild the labels;
   - add `avg_delivery_pct_30d` (SMALL) to the factor audit;
   - re-check the cost placeholders in `config.TIERS` against `tools/lh_costs`, and re-read the names-per-tier SMALL verdict with them;
   - re-check `cons_beat_rate_4q` after the Oct–Nov results, as already planned.

## Luck tests on the 48 variants (plan 0025 task 1.1, 2026-10-13)

[`tools/lh_luck.py`](../../tools/lh_luck.py) (pre-registered in its docstring) → `data/lh/luck.json`. Monthly ATLV excess per variant.
- **DSR:** the deflated Sharpe ratio of the best-Sharpe variant, with N_eff from the mean pairwise correlation.
- **PBO:** the probability of backtest overfitting, by CSCV with 8 blocks (70 splits).
- **Pass:** DSR ≥ 0.95 and PBO ≤ 0.20.

| tier | best by Sharpe | Sharpe/yr | mean corr → N_eff | DSR (N_eff) / (48) | PBO | in-sample best loses to index out of sample | in-sample best vs grid median, out of sample |
|---|---|---|---|---|---|---|---|
| LARGE | Q · N20 · k4 · raw · hold 6 | 0.69 | 0.90 → 5.7 | 0.78 / 0.66 | 0.39 | 29 % | +3.2 % vs +3.1 %/yr |
| MID | M · N15 · k3 · raw · hold 6 | 0.60 | 0.72 → 14.3 | 0.68 / 0.59 | 0.61 | 50 % | −0.3 % vs +0.2 %/yr |
| SMALL | M · N20 · k2 · avg3 · hold 6 | 1.15 | 0.74 → 13.3 | **0.93** / 0.89 | 0.47 | **10 %** | +8.3 % vs +8.5 %/yr |

Read:
- **No tier passes.** In every tier, choosing among the 48 rules is no better than picking one at random (PBO ≈ 0.4–0.6): the in-sample winner does no better out of sample than the median rule. Tuning the rule is worthless, so pick one rule for economic reasons and stop searching.
- **SMALL is different in kind.** The in-sample best beat the index in the other half in 90 % of the 70 splits, and the *median* rule earned +8.5 %/yr out of sample. The DSR of 0.93 is just short of 0.95. The edge, if real, is in the score (the whole family is positive), not in the rule. That is why plan 0025 puts the work into `slow_v2`.
- MID and LARGE: nothing beyond what the index would give; consistent with H3.
