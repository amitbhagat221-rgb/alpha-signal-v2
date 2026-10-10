# ADR 0068 — No dynamic filters on the option strangle: the delta rule already adapts

**Status:** proposed 2026-10-10 (plan 0023 result). Builds on ADR 0067 (the paper book's static rule).

## Decision

1. **The paper book keeps the static rule.** It sells a 0.05-delta strangle 2 sessions before expiry, every week, at full size. No market-reading filter skips, halves or tilts it.
2. **Six such filters were tested and rejected.**
   - **How they were tested:** pre-registered, PIT inputs (`option_state.py`), TRAIN 2019-02 → 2024-11, TEST 2024-11 → 2026-10 run once, SENSEX as a second check, bar t ≥ 2.4 plus a shuffle test (`tools/option_dynamic_study.py`).
   - **The six:**
     - skip when IV ≤ realised vol;
     - tilt with the 5-day trend;
     - tilt with skew;
     - skip on an inverted term structure;
     - half size on extreme put/call OI;
     - half size on rupee or oil shocks.
   - **The two with any effect** (trend, skew) changed returns by ≤ 0.03% of margin per trade. The four skip/half rules lost money in every year.
3. **New dynamic ideas need their own pre-registration and a forward test.** Don't re-propose the six above. Untested candidates:
   - sizing *up* when premium is rich (adds tail risk);
   - intraday management (needs Kite minute data collected forward).

## Why

- **A fixed-delta strike is already reactive.** When implied volatility rises, the 0.05-delta strike moves further from the market, so stress is priced into the strike itself.
- **The static rule earns most in the "scary" states.** Return per trade by quintile, 2019 → (% of margin):

  | State | Top quintile | Bottom quintile |
  |---|---|---|
  | Premium over realised | 0.73 | 0.49 |
  | Skew | 0.73 | 0.44 |
  | Inverted term structure | 0.70 | 0.44 |
  | Sharpest 5-day fall (vs sharpest rise) | 0.89 | 0.37 |

  De-risking in those states gives up the best weeks. The worst trade was unchanged, because the tail did not cluster in the flagged states.
- **Same lesson as plan 0022's event and VIX vetoes:** index premium already prices the visible risk.
