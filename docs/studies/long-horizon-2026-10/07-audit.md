# Long horizon, step 7: adversarial audit of steps 1–4 (2026-10-12)

Plan 0024. I tried to break the study in `01-horizon.md`, `02-costs.md`, `03-design.md`, `04-slow-model.md`, `05-book.md` and `tools/lh_*.py`. Everything was read-only. The DB was opened with `mode=ro` and nothing was copied. My check scripts are in this session's scratchpad. They are not repo files; each one is described below so it can be rerun.

## Verdict
**The pass/fail calls stand: H2 passes in MID and SMALL, and H3 fails in all three tiers. No flaw I found reverses either. But H1 is much weaker than `01-horizon.md` says, and survivorship is bigger in SMALL than the notes assume.**

| claim | audit result | what changes |
|---|---|---|
| H1: "slow" factors pass in all three tiers | **Numbers reproduce exactly.** The evidence is overstated, because the t-stats treat about 77 overlapping 6-month windows as if they were 77 independent ones. | Counted with the real number of independent windows (about 13), only **SMALL `cons_beat_rate_4q`** survives the BY haircut at 6 months. LARGE and MID lose all their "pass all three" factors. SMALL `avg_delivery_pct_30d` (a live weight) does not hold once delisted and outside-universe stocks are added. |
| H2: slow composite works out of sample in MID and SMALL | **Confirmed.** It reproduces exactly, the embargo is correct, the result does not depend on the unverified consensus factor, and it survives adding the missing stocks. | Nothing. It is thinner on non-overlapping windows (lowest offset t 2.55 MID, 2.57 SMALL), but the bar was set on Newey-West. |
| H3: no long-hold book passes | **Confirmed, and robust.** The best variant that meets the other bars has a raw t of 1.81. A haircut t of 2.0 needs a raw t of about 3.5. | Nothing. Every bias I found flatters the book, which only makes the fail firmer. SMALL's +18.3 %/yr is best read as an upper estimate. |

## What I re-derived (all match the notes)
- **H1, all 1,094 tests**, recomputed from `daily_snapshots_pit` and `data/lh/labels.parquet` with my own loop. The Newey-West t matches `horizon_tests.csv` to within 0.017 on every test. M = 1,094; BY survivors 91; Bonferroni 48; naive |t| ≥ 2.5: 239.
- **H2**, from `oos_scores.parquet` + `labels.parquet`. IC126 (Newey-West t, lag 6): MID `slow_select` 0.0873 (5.68), `slow_icw` 0.1137 (2.81); SMALL `slow_select` 0.0725 (3.29), `slow_icw` 0.1154 (3.63); LARGE `slow_select` −0.0040 (−0.11), `slow_icw` 0.0511 (0.77).
- **The embargo is correct.** `tools/lh_slow_model.py:179` admits training month j only if its entry is at least 127 sessions before the entry of test month k. I checked this against the market calendar from `stock_prices`. For every OOS month and tier, the last training month's 126-session exit falls on or before the OOS anchor; the tightest case has 0 sessions to spare, which still means the label was known at that close. The first OOS month is 2022-06-01, with 24 training months. `fast_select` trains on anchors up to k−2, so its 20-session label ends at least 12 sessions before anchor k.
- **H3**, rerun with `tools.lh_book.simulate` on the three best variants. Excess and t match exactly (LARGE +7.05 % t 1.263, MID +5.17 % t 1.441, SMALL +18.30 % t 1.813). The grid summary also matches: positive-excess variants 36 / 21 / 47; median t 0.49 / 0.03 / 1.35; max t 1.26 / 1.44 / 2.61; 0 passing in every tier.
- **Labels.** Coverage of the 126-session label is 98–100 % in every score quintile (SMALL: 99.3 % bottom fifth, 98.1 % top fifth). Selection on "has a label" does not bias the IC.

## Look-ahead
- **Entry timing: clean.** `pit.forward_returns` enters at the close of the first session after the anchor (`pit.py:411-413`). The book fills at that same close and chains `fwd_next_anchor` from entry to entry (`tools/lh_labels.py:84-101`), so the book and the label line up.
- **Tiers: point-in-time.** The panel tier is `pit.tiers_at` (`pit.py:1460`). Of the panel's LARGE tier at 2021-06-01, only 64 are LARGE today (69 at 2022-06-01, 96 at 2026-10-01), so the panel is not using today's tiers.
- **Fundamentals lag**: 60 days quarterly, 75 / 150 days annual (vendor arrival), 21 days shareholding (`pit.py:30-42`). This is reasonable. Restated vendor numbers cannot be checked.
- **`cons_beat_rate_4q`** is marked `pit_unverified` (`signals/consensus_beat.py:23`). Every Yahoo row was fetched between 2026-09-28 and 2026-10-10. `target_period` is the report date (only 4 % fall on a month-end), so the date filter is correct. Whether the estimate was revised after the report cannot be checked. **Test:** I removed it from every month's SMALL `slow_select` weights and rescored. IC126 went from 0.0725 (t 3.29) to 0.0708 (t 3.21), so H2 SMALL does not depend on it. Removing `value_composite` as well gives 0.0454 (t 2.23).
- **MID macro betas** (`gold_beta`, `inr_beta`, each chosen in 83 % of months) are computed from macro history up to the anchor only (`pit.py:881-900`). Without them, MID `slow_select` IC126 is 0.0616 (t 2.89), still a pass.
- **Book rules**: the 3-month average uses months t, t−1 and t−2 only (`tools/lh_book.py:192`). Liquidity uses prices up to the anchor (`:132`). The red flag is the panel's value at the anchor.

## Survivorship (the plan asked for this; steps 1–4 did not run it)
I compared `daily_snapshots_pit_unlisted` with the panel at the 52 OOS anchors. The unlisted table holds every NSE symbol outside today's 2,448-stock universe. I split it into three groups: **dead** (no price after 2026-08-31), **alive SME** (SM/ST series) and **alive main board**. The 20-session label is the table's own; the panel's is `fwd_20`.

| SMALL tier, 2022-06 → 2026-10 | per anchor | share of tier | return vs listed SMALL, per month (t) | lifts the listed equal-weight average by |
|---|---|---|---|---|
| dead | 59.1 | 5.8 % | −0.45 % (−0.91) | ~0.5 %/yr |
| alive, main board, outside our universe | 125.4 | 9.2 % | **−2.09 % (−4.16)** | **~2.3 %/yr** |
| alive SME | 17.1 | 1.4 % | +1.76 % (+1.02) | ~−0.1 %/yr |

- **The bigger bias is not delistings.** It is that the universe was picked in 2026. Main-board stocks that are still listed but sit outside our 2,448 (440 on EQ series, plus BE/BZ) did about 2 % a month worse. The SMALL equal-weight average, which `05-book.md` uses as the "fair" second benchmark, is overstated by roughly **2.8 %/yr**. That cuts both ways. The benchmark is too high, and the book may be flattered by a similar amount if it would have bought these stocks. So the +15.0 % against the equal-weight average is not a clean measure of selection skill.
- **MID and LARGE are barely affected.** The missing names are 2.8 % of MID (they did +0.66 %/month, n.s.) and 6.4 % of LARGE (dead names −2.45 %/month, t −1.84). **So survivorship cannot explain MID's "weak firms did better" pattern in 2022-26,** although `01-horizon.md` and `04-slow-model.md` both suggest it. I could not test the 2019-22 training years for this.
- **H2 SMALL survives the missing stocks.** I added the missing SMALL stocks to each OOS month, with their own price factors and 0.5 for the fundamentals they lack, and rescored `slow_select`. Their 126-session return is chained from `close / prev_close` in `stock_prices_unlisted`, ending at the last price if the stock stops trading. Result: IC126 0.0725 → **0.0625 (t 3.21)**; top-15 excess +4.86 % → +5.82 %, because the tier average falls. Missing stocks entered the top 15 only 0.04 times per month. *Limit: their fundamentals are missing here, not missing in real time, so this cannot show whether the model would really have avoided them.*
- **H1, price-only factors, rerun on the full market** (126 sessions, all 77 anchors, unlisted EQ-series added):
  - `position_52w` 0.0878 → 0.0975 (t 4.30 → 4.90)
  - `mom_6m` 0.0847 → 0.0937
  - `closing_strength_1m` t 4.47 → 3.60
  - `rate_beta` t −3.97 → −5.10
  - **`avg_delivery_pct_30d` 0.0557 (t 4.00) → 0.0360 (t 1.75)**, and t 1.31 with BE/BZ names included. Its 6-month evidence does not hold on the full market. It is a live SMALL weight (0.12).
- **The book.** No held position in the three best variants ever lacked a monthly return (0 position-months). The "missing return = 0" rule (`tools/lh_book.py:418`) never fired. Because the book only ever held stocks that are still listed, it never held a stock that later went bust. If the model had picked missing stocks at their share of the tier, the flattery would be up to roughly 2.8 %/yr in SMALL. The true figure is likely lower, because the model rarely ranks such stocks high. It cannot move a raw t of 1.81 to 3.5.

## Overfitting
- **H1: the t-stats are generous for overlapping labels** (`tools/lh_horizon.py:45`, Bartlett lag = horizon in months, p on df = n − 1). With 6-month labels on monthly anchors, the 77 months hold about 13 independent windows. I reran all 1,094 tests two ways:
  - **Same Newey-West t, df = independent windows − 1:** 8 survive BY, all in SMALL (4 at 21 sessions, 3 at 63, 1 at 126). At 6 months only `cons_beat_rate_4q` survives (p 0.000035).
  - **Plain t on non-overlapping months (median of the 6 offsets, 13 months each):** 5 survive BY, all SMALL 21-session.
  - For the 17 "pass all three" factors, the non-overlapping 6-month t is:

| tier | factor | non-overlap t | Newey-West t |
|---|---|---|---|
| SMALL | `cons_beat_rate_4q` | 4.51 | 6.43 |
| SMALL | `value_composite` | 4.43 | |
| SMALL | `sector_tilt` | 3.66 | |
| SMALL | `closing_strength_1m` | 3.35 | |
| SMALL | `position_52w` | 3.17 | |
| SMALL | `avg_delivery_pct_30d` | 3.08 | |
| SMALL | `mom_6m` | 2.99 | |
| SMALL | `announcement_car` | 2.86 | |
| SMALL | `rate_beta` | −2.49 | |
| SMALL | `accruals_signal` | 2.21 | |
| MID | `z_score` | −3.23 | −5.75 |
| MID | `interest_coverage` | −2.99 | |
| MID | `roic` | −2.98 | |
| MID | `debt_structure` | 2.49 | |
| MID | `gold_beta` | 2.49 | |
| MID | `gross_profitability` | −2.44 | |
| LARGE | `metals_beta` | 2.79 | 3.73 (lowest offset 0.75) |

  H1 is descriptive: no decision in the plan rests on it alone. But "H1 passes in all three tiers" should read **"SMALL has a few slow factors; MID and LARGE do not, once the overlap is counted honestly."**
- **H2.** There were 2 eligible methods in each of 2 tiers, so 4 tries at the t ≥ 2.0 bar. With a 4-way Bonferroni, the bar is about 2.5. MID `slow_select` (5.68) and SMALL `slow_icw` (3.63) clear it on Newey-West, and their median non-overlapping t's (3.03 and 3.13) clear it too. On the worst offset (2.55 and 2.57, df 7) they would not. The design parameters (t ≥ 2.5, 8 factors, a 12-month floor) are not in the plan. The timeline gives no sign of tuning: the plan was saved at 20:12, before the labels (20:16), and `slow_model.log` shows one run. `lh_slow_model.py` was edited at 20:49, after the 20:40 run, but the saved scores reproduce the saved records exactly.
- **H3.**
  - 48 variants per tier (144 in all), within the plan's cap. The grid rules in `03-design.md` (20:35) were saved before the H2 scores (20:40) and the book (21:02).
  - The Bonferroni ×48 haircut (`tools/lh_book.py:575`) is what the design said.
  - The 33 extra runs (comparisons, status quo, checks) cannot pass, so they need no haircut.
  - **Not pre-registered:** the choice of `slow_select` as the grid's score set. `03-design.md` says only "the H2 OOS scores", and the choice was made after H2. On the same best rule, SMALL earns +18.3 % with `slow_select` but +3.6 % with `slow_icw`, which had the *higher* out-of-sample IC and top-15 excess in H2. That spread is a sign that SMALL's +18.3 % is fragile. It does not change the fail.

## Costs and tax
- **Costs.** `lh_costs.one_way_cost_bps` (SMALL, ₹1 L trade, 2023 scale): 76 bps at ₹0.2 cr ADTV, 36 at ₹2 cr, 30 at ₹4.1 cr, 23 at ₹20 cr; stress mode 1.6–1.8× those. ADTV in the book is volume × close in ₹ (`tools/lh_book.py:132`), so the ₹-lakh `traded_value` trap noted in `05-book.md` is avoided. SMALL's best variant pays about 60 bps per one-way trade (105 bps a year on 88 % turnover), twice the tier median. That is conservative.
- **Tax.**
  - The bill is settled once per financial year, the ₹1.25 L exemption is applied per year after set-off (`:240`), and long-term means held more than 12 months (`:245`).
  - Losses are netted the Indian way and carried forward 8 years.
  - Tax is paid in cash from the book, with forced sales on a shortfall (`:375`). The after-tax liquidation value includes this year's tax on gains not yet realised.
  - Dividends are taxed at 31.2 %.
  - I found no error. Paying tax on 31 March instead of quarterly advance tax slightly favours the book, by the interest on a few months' tax. That is negligible.
- **Fills** at the next session's close, with modelled spread and impact. There was no partial-fill or circuit-limit check. For ₹1 L tickets in SMALL names with at least ₹2 cr ADTV, that is minor.

## The benchmark
- **The dividend credit is there, and slightly generous.**
  - NIFTY 50: price-only CAGR 7.27 % (16,628 → 22,555.75, 2022-06-02 → 2026-10-05). With the credit (0.126 %/month) it is 8.88 %, an add-back of 1.61 points a year.
  - Smallcap 250: 17.48 % → 18.47 %, an add-back of 0.99 points.
  - Without the credit, LARGE's excess would be overstated by about 1.6 points a year and SMALL's by about 1.0.
  - NIFTY 50's usual gap between its total-return and price index is about 1.2–1.4 %/yr. That range is general knowledge; no TRI series is in our DB to check it. So the credit may be a few tenths too high, which is conservative for the book.
- **Cap-weighted index vs the equal-weight tier.** SMALL equal-weight 22.03 % vs Smallcap 250 18.47 % (pre-tax) means about 3.6 points of SMALL's "excess vs the index" come from equal weighting and from the tier reaching far below the index's 251–500 ranks. About 2.8 points of that is survivorship (above). The pass test uses the index, which is right. The second benchmark is not a clean control for selection skill.
- **MID** uses the survivor-only equal-weight average for its first 12 months. MID survivorship is small, so the effect is small.

## What I would change before the verdict document
1. In the verdict, report H1 at about 13 independent windows (effective df) and drop "H1 passes in all three tiers". Only SMALL has slow factors that clear a multiple-testing bar at that df.
2. Add the full-market rerun to H1. Flag `avg_delivery_pct_30d` SMALL: its 6-month t of 4.00 falls to 1.75. It is a live weight, so this also goes to the factor-audit list.
3. Correct the survivorship wording. It does **not** explain MID's weak-firm pattern in 2022-26. It **does** overstate the SMALL equal-weight average by about 2.8 %/yr, mostly through still-listed stocks outside our universe, not delistings.
4. Say that the grid's score set (`slow_select`) was chosen after H2, and that SMALL's +18.3 % falls to +3.6 % on `slow_icw`. Treat +18.3 % as an upper, fragile estimate.
5. The decision is unchanged: H3 fails in every tier, so each tier is the index.
