# Pre-registration: SOCAP's expiry-day strategy on our data (2026-11-07)

Written and committed **before any result was computed**. Asked by Amit: "you are supposed to independently verify and backtest socap strategy on our data and report."

**Source of the strategy:** the SOCAP reconstruction in [socap-option-strategy.md](socap-option-strategy.md), which was built from SOCAP's own fills in a separate session. SOCAP's exact rules are not known. The rules below are my reading of what the fills show, fixed now, and the only rules used for the verdict.

**Tool:** `tools/socap_backtest.py`. It is read-only: `fno_bhav` and the `intraday_files` manifest are opened with `mode=ro`, and it reads the 1-minute Parquet files. It writes nothing except a report file named on the command line.

## Data

- **Option prices:** 1-minute trade prices (no bid/ask).
  - Hugging Face archive `data/intraday/options_1m/`: NIFTY expiries from 2021-05-27, SENSEX from 2023-08-11, both to 2026-07-02. Files whose manifest status is `stub` or `suspect` are excluded, as in the stops/wings study.
  - Kite capture `data/intraday/options_1m_kite/`: same columns. Any expiry day it covers is used (today that is SENSEX 2026-11-05).
- **Index:** the 1-minute index file of the same source.
- **Settlement:** the `fno_bhav` `underlying_price` on the expiry day, as in every earlier option study.
- **Sample:** every expiry day in these files that has index bars from 09:30 to 15:29 and an option print at 09:30 on both chosen strikes. Skipped days are counted by reason.

## Primary rule (P), the only one that decides the verdict

1. **Day:** the expiry day of the front contract (weekly, or monthly when it is the nearest), NIFTY and SENSEX. One trade per expiry day.
2. **Forward at 09:30:**
   - Take the strike nearest the 09:30 index close.
   - Take the last close at or before 09:30, between 09:25 and 09:30, for the call and the put at that strike.
   - F = K + C − P.
   - Basis b = F − S(09:30). The basis decays linearly to 0 at 15:30.
3. **Time:** T = remaining trading minutes to 15:30 ÷ (375 × 252). Delta does not depend on this convention; only the annualised volatility figures do.
4. **Entry at 09:30:**
   - Sell 1 unit of the call and 1 unit of the put.
   - Each strike is the one, out of the money on its side, whose Black-76 |Δ| is nearest **0.40**. Δ uses that strike's own implied vol from its 09:25–09:30 last close.
   - The fill is that last close minus slippage.
5. **Hedge (h = 0.5, every 15 min):**
   - At 09:45, 10:00, … 15:15, compute the options' delta. Each leg's IV stays fixed at its entry IV (sticky strike); F_t = S_t + basis_t.
   - Set the hedge to H_t = −h × (options delta), in a synthetic future (call/put pair at the then at-the-money strike).
   - Hedge P&L = H × (F_next − F_t) between rebalances. The last interval runs to the settlement, where F = S_settle.
   - Hedge cost per unit traded = cost of trading one call and one put at the ATM strike. Their prices come from Black-76 at the ATM IV of 09:30 (sticky).
6. **Exit:** none. The short legs settle at intrinsic on S_settle, and the hedge closes at S_settle.
7. **Costs:**
   - Per leg per side: `option_book.charges_pts` (brokerage ₹20 an order + GST, exchange charge, STT 0.1 % on sells, stamp on buys) plus slippage of max(₹0.05, **0.25 %** of the price).
   - 0.25 % is about twice the median half-spread measured on our Kite quotes for |Δ| 0.2–0.6 (0.1–0.2 %).
   - Long hedge legs that finish in the money pay STT on exercise (0.125 % of intrinsic).
8. **Units:**
   - Points per unit, ₹ per lot (`option_book.lot_size` of the day).
   - % of margin, with margin = 14 % of F × lot (12 % as in earlier studies, plus the 2 % expiry-day add-on).

## Verification of SOCAP's reported facts

Each check is reported as holds / doesn't hold on our data.

- **V1 Volatility gap.** On expiry days, the 09:30 ATM implied vol (from the parity-pair straddle) is above the realised vol of 1-minute index log returns from 09:30 to 15:30, with the same annualisation. Holds if the median implied minus realised is > 0 over 2021–26 and also in 2026. SOCAP reported 25 % implied against 21–22 % delivered for NIFTY in October 2026.
- **V2 Hit rate.** SOCAP reported 84 % of NIFTY and 76 % of SENSEX expiry days profitable in 2026. Holds if P's 2026 hit rate on our data is within 15 points of each.
- **V3 Stress days.** SOCAP lost on NIFTY 2026-01-20 and 2026-02-03, and on SENSEX 2026-11-05. Holds if P loses on at least 2 of the 3 (NIFTY 2026-11-03 is not in our minute data).

## Decision rule for P

**KEEP as a forward paper-test candidate** only if all four hold. Otherwise **DROP**.

1. NIFTY 2021–26: mean net P&L per expiry > 0, with t ≥ 2.0 (one observation per expiry, Newey-West with 4 lags).
2. NIFTY: positive in at least 4 of the 6 calendar years (2021–2026).
3. SENSEX 2023–26: mean > 0.
4. **Better than our live rule on the same expiries**, in ₹ per lot. Our rule = the 0.05Δ strangle entered at the T-2 settle and held, from `tools/option_t1_exit_study` (the same replay as the paper book). Better means both of these, measured on the expiries both have, per index:
   - a higher Sharpe (weekly mean ÷ standard deviation × √50);
   - a smaller worst week ÷ mean week.

Also reported, not deciding:
- the correlation of P with our rule week by week;
- a 50/50 book of the two (both on one lot each);
- the yearly table.

## Grid, all reported, none can change the verdict

- **Δ:** 0.15 / 0.25 / 0.40.
- **Hedge ratio h:** 0 (naked) / 0.3 / 0.5 / 1.0.
- **Rebalance N:** 5 / 15 / 30 min. That makes 36 cells.
- **Variants on P:**
  - **tranches:** one sixth sold at each of 09:30, 10:30, 11:30, 12:30, 13:30 and 14:30, each at that hour's Δ 0.40 strikes. This follows SOCAP's selling continuing to 14:30.
  - **tail:** also buy the call and put whose |Δ| is nearest 0.01 at 09:30, with a budget of 10 % of the credit. SOCAP's insurance cost about 11 % of its expiry-day profit.
  - **lean:** from 10:00, add +0.2 delta per unit in the direction of the 09:15→10:00 index move.
  - **slippage:** 0.1 % and 1 %.
- 36 cells plus 5 variants means about 41 tries. A grid cell that beats P is a lead for a new pre-registration, not a result.

## Out of scope (stated now)

- SOCAP's selling on the day before expiry and 4–7 days out (about 40 % of its selling) with overnight carry.
- The standing futures short.
- Order slicing and market impact. SOCAP's size moves the market; one lot does not.
