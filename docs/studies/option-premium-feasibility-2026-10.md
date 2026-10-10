# Selling NIFTY weekly option premium — feasibility (2026-10-09)

**Question (Amit):** can an agent take option positions every day and earn a small, steady premium on Zerodha?
**Answer (revised the same evening, after the 2019–2024 real-price run; see "Result of the pre-registered run" below):** the version that holds up on real prices is **a short strangle at 0.05 delta, sold two trading days before the weekly expiry and held to expiry (exp2)**:
- **NIFTY 2019–2026:** about 25% a year on margin, Sharpe 2.9, positive every year, worst trade −8.9% of margin.
- **SENSEX 2024–2026:** Sharpe 3.7.

The morning's candidate, one day before expiry (exp1), **failed its pre-registered test**. In 2019–2024 its Sharpe was 0.6 and it lost 28–39% of margin in one trade (2020-03-11). Both vetoes (scheduled events, VIX > 25) failed. exp2 was not the pre-registered primary, so it is a candidate for a pre-registered forward paper test, not a result to trade on. Selling every day and condors with 1% wings still fail.

*Morning version, kept for the record:* one version survives: **a short NIFTY strangle at about 0.05–0.10 delta, sold one trading day before the weekly expiry and held to expiry**. It made money after costs on the real chain (Nov 2024 → Oct 2026) and, in a model, in every year from 2015 to 2026. Selling every day, holding 2–3 days, and iron condors with 1% wings do not survive. The worst days lose 36–46% of the margin. The agent's best use is skipping known event days. It cannot remove surprise days.

Tool: [`tools/option_premium_backtest.py`](../../tools/option_premium_backtest.py) (read-only). Run `python -m tools.option_premium_backtest --vix --sensitivity --stress`. The grid was fixed before any result was seen, and every cell is reported in the tool's output.

## Method

- **Data.** `fno_bhav` NIFTY index options, end of day, 2024-07-15 → 2026-10-08. Main window: entries from 2024-11-20, when SEBI's one-weekly-expiry rules started.
- **Entry.** At the day's settle (the close, for a traded strike). Short strikes chosen by Black-76 delta on that day's own prices, from strikes that traded that day. Expiry settles at intrinsic value on the index settlement.
- **Grid.** Delta 0.05 / 0.10 / 0.15 / 0.20 · hold `exp1`/`exp2`/`exp3` (enter k trading days before expiry, hold to expiry) or `daily` (sell the nearest expiry, buy back the next day) · strangle / iron condor (wings 1% beyond the shorts).
- **Costs.** Brokerage ₹20 per order + GST, exchange charge, STT on the sell side, stamp duty, slippage max(0.05, 1% of price) per leg per side. Sensitivity: STT 0.15%, slippage 3%.
- **Return.** % of margin per trade. Margin is an assumption: strangle 12% of the forward, condor = wing width. **Check 12% on the Kite margin calculator.** An exp1 position is held into expiry day, where SEBI's extra 2% margin on short options applies.

## Results on the real chain (entries 2024-11-20 → 2026-10, ~97 trades per weekly cell)

| Cell | Win % | Mean/trade | Ann. (50/yr) | Sharpe | Worst trade | Max DD |
|---|---|---|---|---|---|---|
| exp1 strangle 0.05 | 96.9 | 0.27% | 13.3% | 2.42 | −7.2% | −7.2% |
| exp1 strangle 0.10 | 90.8 | 0.40% | 19.9% | 1.93 | −10.2% | −12.5% |
| exp2 strangle 0.05 | 96.9 | 0.39% | 19.5% | 4.05 | −5.3% | −5.3% |
| exp3 strangle 0.10 | 90.6 | 0.47% | 23.6% | 1.30 | −13.0% | −18.4% |
| daily strangle 0.10 | 76.8 | 0.07% | 18.7% (250/yr) | 0.86 | −14.4% | −20.9% |
| daily strangle 0.10, slippage 3% | 75.0 | 0.03% | 8.0% | 0.36 | −14.7% | −23.2% |
| exp1 condor 0.10 | 90.8 | 1.41% | 70.5% | 0.70 | −95.5% | −125.5% |
| daily condor 0.05–0.20 | 53–65 | −0.7 to −0.8% | −176 to −212% | −0.9 to −2.3 | ≈ −90% | ≈ −300% |

- STT barely matters: it is charged on a premium of 10–80 points.
- The daily roll pays costs twice every day and does not survive realistic slippage.
- A condor with 1% wings risks the whole margin on any 1.5% move. It behaves like a lottery ticket, not a premium trade.
- This window has no crash day, so these Sharpe ratios overstate. See the stress test below.

## Stress test, 2015-06 → 2026-10 (model, strangles only)

The model expresses strike distance and credit in units of VIX × √T, calibrated on the chain trades above, and applies them to NIFTY and India VIX daily history (`macro_history`). Inside the chain window it reproduces exp1 and exp3 within about 0.1 percentage point a trade; exp2 is less close (model 0.18% against chain 0.41% at 0.10 delta). It fails for condors, whose wing strikes depend on which strikes traded, so condors are not reported. Before 2019 NIFTY had no weekly options, so those years test the market moves, not the product.

One trade a week:

| Cell | Ann. % of margin | Sharpe | Max DD | Worst trade | Losing years |
|---|---|---|---|---|---|
| exp1 0.05 | 19.4 | 3.61 | −12.2% | −36.2% (2020-03-11, any weekday) | none (2015–2026) |
| exp1 0.10 | 28–34 (by weekday) | 2.47 | −14% to −70% | −45.6% (2020-03-11) | none |
| exp2 0.10 | 13.1 | 0.55 | −79.7% | −35.4% | 2015, 2018, 2020, 2024 |
| exp3 0.10 | 20.3 | 0.73 | −47% to −132% | −52.8% | 2020, 2023, 2024 |

Worst exp1 entry days, with the next day's NIFTY move:

| Entry | Move | What it was |
|---|---|---|
| 2020-03-11 | −8.3% | COVID; VIX already 31.6 |
| 2024-06-03 | −5.9% | Election results, a **scheduled** event |
| 2019-09-19 | +5.3% | Corporate tax cut, a surprise |
| 2015-08-21 | −5.9% | China devaluation sell-off, a surprise |
| 2022-02-23 | −4.8% | Ukraine invasion; tension was in the news |
| 2016-02-29 | +3.4% | Budget, a scheduled event |

## What it means

1. **The candidate is exp1 at 0.05–0.10 delta.** Plan on 13–20% a year on margin, which is what the real chain gave at 0.05 delta and the 2015–2026 model gave at 0.10. A single day can lose 36–46% of margin.
2. **Sizing comes before everything else.** Using about one-third of capital as margin turns the worst day into −12% to −15% of capital, and the return into roughly +5–7% a year on capital. That is on top of the yield on the pledged collateral, before tax. F&O profit is business income taxed at your slab rate.
3. **The agent's job is the event veto:** skip or widen before scheduled events (election results, Budget, RBI policy, FOMC), and when VIX or news risk is already elevated. In this list that covers about half the worst days. Surprises remain, which is why sizing (point 2) does the real work.
4. **"Daily" means two exchanges.** NIFTY expires Tuesday on NSE and SENSEX Thursday on BSE, so this rule trades about twice a week. SENSEX is untested because we hold no BSE options data.

## Not covered

- Intraday moves: no stop-loss modelled, and margin can spike during a session.
- Bid/ask: slippage is assumed.
- Real margin: 12% is assumed.
- Option prices before 2024-07: the stress test is a model.
- SENSEX.

Any VIX or event filter is a **new hypothesis**, to be fixed before it is tested, not tuned on these results.

## Pre-registration, 2026-10-09 (written before the 2019–2024 real-price run)

New data: real NIFTY option prices from 2019-02-11 (the first weekly series) to 2024-07-12, loaded from the legacy NSE F&O archive. These years have been seen only through the VIX model above, never at real option prices.

- **H1, base.** exp1 strangle at 0.05 and 0.10 delta is profitable after costs on 2019-02-11 → 2024-07-12. Pass: mean net return per trade > 0 with t ≥ 2 for at least one of the two. Every grid cell is reported; the grid, costs and margin rule are unchanged. Exception: lot size per date comes from the archive's futures turnover, not the hard-coded table.
- **H2, event veto.** Skip an entry when a scheduled event's result lands inside the hold:
  - **Indian events:** Union Budget day, Lok Sabha counting day, RBI MPC decision day. These land during the session of day d; skip if entry < d ≤ expiry.
  - **FOMC:** the decision is released in the US evening of day d and lands on the Indian session of d+1. Skip if entry ≤ d < expiry.
  - **Dates:** from official calendars (rbi.org.in, federalreserve.gov), a fact lookup rather than a choice.
  - **Dates used** (in `tools/option_premium_backtest.py`):
    - 48 RBI MPC decisions, 2019-02 → 2026-10, including off-cycle 2020-03-27, 2020-05-22 and 2022-05-04. The 2022-11-03 meeting is left out: it made no rate decision.
    - 64 FOMC statements, including unscheduled 2020-03-03 and 2020-03-15.
    - 10 Union Budgets and 2 Lok Sabha counting days.
    - Each RBI and FOMC date was checked against an rbi.org.in or federalreserve.gov page.
- **H3, VIX veto.** Skip an entry when India VIX at entry is above 25, the existing `config.VIX_REGIMES` CAUTION boundary. Caveat: this level was picked after seeing 2020-03-11 (VIX 31.6) among the worst days, so H3 is not clean. It counts only if it also holds on 2024-11 → 2026-10, and its real test is forward.
- **Adoption rule for each veto.** Both of these must hold on the 2019–2024 real-price window: (a) the vetoed trades' mean return is below the kept trades' mean return, and (b) the worst trade and max drawdown improve. The same direction must also hold on the 2024-11 → 2026-10 chain and in the 2015–2026 model. No threshold is tuned after the run.

## Result of the pre-registered run (2026-10-09, 21:50 UTC)

**Data loaded tonight:**
- NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY options + futures from the legacy NSE archive, 2019-01 → 2024-07-12, into `fno_bhav` (`sources/fno_pull --legacy`). Index levels went into `nse_index_history`.
- Missing days: 2021-03-30 (no file) and 2024-07-08 → 07-12 (NSE's format switch).
- SENSEX/BANKEX from BSE's UDiFF files, 2024-01-05 → 2026-10-08 (`sources/bse_fo`).
- NIFTY lot sizes measured from the archive: 75 until mid-2021, then 50.

Rerun:
```
python -m tools.option_premium_backtest --start 2019-02-11 --end 2024-07-12 --veto --stress
python -m tools.option_premium_backtest --veto
python -m tools.option_premium_backtest --underlying SENSEX --start 2024-01-05 --veto
```

**H1 (exp1 strangle, 0.05 / 0.10 delta) FAILS on 2019-02 → 2024-07:**

| | Ann. % of margin | Sharpe | t | Worst | Max DD |
|---|---|---|---|---|---|
| 0.05 delta | 8.5 | 0.59 | ≈1.4 | −28.1% (2020-03-11) | −28.1% |
| 0.10 delta | 13.6 | 0.62 | ≈1.4 | −39.2% | −39.2% |

2020 is a losing year. Across 2019–2026 the t-stat reaches only 2.1.

**H2 (event veto) REJECTED.** On 2019–2024 exp1, the skipped event trades did better than the kept ones (0.26% vs 0.15% a trade) and the worst trade was unchanged. Scheduled events are priced: they pay more premium, not less.

**H3 (VIX > 25 veto) REJECTED.** On 2019–2024 exp1 it helps: it removes 2020-03-11 and the worst trade goes from −28% to −17%. It fails the same-direction check on 2024-11 → 2026-10 (3 vetoed trades, which did better) and in the 2015–2019 model. **Result for the agent idea:** a veto on known events or high VIX did not earn its keep. Index premium already prices the scheduled risk.

**The cell that holds up: exp2 strangle at 0.05 delta.** It is in the pre-registered grid but was not the primary, so treat it as a post-hoc pick.

| Sample | Trades | Ann. % of margin | Sharpe | t | Worst | Max DD | Losing years |
|---|---|---|---|---|---|---|---|
| NIFTY 2019-02 → 2026-10 (real prices) | 378 | 24.6 | 2.88 | 7.9 | −8.9% | −12.8% | none |
| SENSEX 2024-01 → 2026-10 | 142 | 18.9 | 3.66 | — | −7.6% | −7.6% | — |

NIFTY by year: 2019 21.5 · 2020 50.5 · 2021 25.6 · 2022 25.4 · 2023 15.1 · 2024 12.8 · 2025 19.5 · 2026 (to Oct) 15.5.

- **Multiple testing.** t = 7.9 clears a Bonferroni bar over the 32 cells (|t| ≈ 3.2) by a wide margin, and the same cell leads in three separate samples (NIFTY 2019–24, NIFTY 2024–26, SENSEX). exp2 at 0.10 delta is weaker (Sharpe 1.58, worst −16.7%).
- **The March 2020 near miss.** The trade entered 2020-03-09 had its short put at 9500 and NIFTY settled at 9590 on 03-12. VIX at 30.8 put the strike 9.4% out of the money, and that is what saved it. One more percent down would have cost a few percent of margin, not a third of it.
- **The VIX model was wrong about exp2.** It predicted losing years; real prices show none. Trust the chain over the model.

**Still assumed:**
- Margin of 12% of notional (check on Kite).
- Slippage of 1%. BSE's far-out-of-the-money options are thinner than NSE's.
- No intraday risk modelled.
- The SENSEX lot change date (assumed 2025-01-01).

**Next:**
1. Pre-register exp2 at 0.05 delta on NIFTY and SENSEX as the forward paper test.
2. Check margin on Kite.
3. Build paper execution. Only after that, live trading.

## Margin check on Kite (2026-10-10, read-only `basket_order_margins`, Friday-close quotes)

| | NIFTY 13-Oct expiry, lot 65 | SENSEX 15-Oct expiry, lot 20 |
|---|---|---|
| 0.05-delta strikes | 23,000 CE (+2.1%) / 21,950 PE (−2.5%) | 74,500 CE (+2.8%) / 69,900 PE (−3.5%) |
| Strangle margin | ₹1,72,308 = **11.8%** of notional | ₹1,55,415 = **10.7%** |
| Premium per lot | ≈ ₹920 | ≈ ₹1,180 |

- **The 12% assumption holds, slightly conservative.**
- **Expiry day:** SEBI's extra 2% on short options applies, and the exp2 hold runs into expiry day, so plan for about 14% then.
- **Lot sizes:** Kite confirms NIFTY 65 and SENSEX 20.

## Next, if pursued

1. Backfill the legacy NSE F&O bhavcopy back to 2019, the first year of NIFTY weeklies, to test exp1 on real prices through 2020.
2. Pre-register and test the event and VIX veto.
3. Get BSE SENSEX options data.
4. Check margin on Kite.
5. Then the execution stack: Kite orders, a pre-trade risk check, a service running all market hours, a kill switch, a paper-trading stage.
