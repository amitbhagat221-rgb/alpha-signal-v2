# HANDOFF
Updated: 2026-05-31 | Branch: master (5 unpushed) | HEAD (pre-commit): `feat(screener): promote iv_skew_25d → live MID factor (first Track-3 promotion)`

## Left off
Built **§3.2.5 event-time/PEAD (4 of 6 factors)** — and the honest headline: **the core PEAD did NOT replicate.** [signals/pead.py](signals/pead.py), backtested on the deep panel:
- `earnings_surprise_std` (seasonal-random-walk SUE): **DROP all tiers** (best LARGE t=0.52).
- `pead_drift_60d`: SMALL t=-1.54 **WEAK with a reversal sign** (opposite of drift), LARGE/MID DROP.
- `corporate_action_density`: LARGE **t=-3.67 KEEP** (CI [-5.99,-2.06] strictly <0) but **mechanism unclear** (likely a maturity/value proxy) + corporate_actions only 2yr deep → **NOT promoted**, verify vs value factors first.
- `buyback_announcement_30d`: DROP (too sparse, ~9/date, n=2 periods LARGE/MID).

**Root cause** (recorded in memory `pead_needs_announce_dates`): `quarterly_income` has no earnings-announcement date (`reporting` = consolidation basis) and we have no quarterly consensus EPS → the SUE/drift construction is too noisy. PEAD needs a real earnings-calendar + consensus feed. Deferred `dividend_change_signal` (brittle text-parse) + `index_inclusion_proximity` (needs historical mcap — current snapshot = look-ahead). All 4 built → bench. 0 CRITICAL, health green.

Fully wired like the prior batches (PIT helper `pit_pead` + 4 cols + BACKTEST_SIGNALS group "Event/PEAD" + SIGNAL_COLUMN_MAP + 4 lineage, drift clean); `corp_actions` added to `load_raw`; reconstructed over all 149 panel dates; monthly cadence.

## Pick up here
1. **§3.2.6 industry dummies (1) + §3.2.7 macro extensions (4)** — the last §3.2 factors not blocked on Kite/NLP. `industry_id` one-hot is trivial. §3.2.7 (`inr_carry_proxy`, `india_credit_spread`, `commodity_beta_oil/metals`) needs INR-forward / G-Sec / commodity series — **check `macro_history` coverage first** (may need new sources).
2. **Deploy Phase E badges** (`systemctl restart alpha-cockpit`) + **Kite activation** when creds land (3 held intraday §3.2.3 factors).
3. **Confirm `iv_skew_25d` reaches `daily_picks`** after the next pipeline run (wired last commit, screener hasn't re-run).

## Watch out
- **Don't re-attempt PEAD with the time-series proxy** — it's a data problem (missing announce dates + consensus), not a tuning problem. See memory.
- `corporate_action_density`'s KEEP is **suspect** — negative-IC count factor over a single 2yr regime with no clean mechanism. Run `factor_correlation` vs value factors before ever trusting it.
- This session shipped a lot (6 commits): F&O OI+IV, microstructure, iv_skew promotion, graphify-disable, PEAD. Factor model now **42/50 PIT-shipped**; one live production promotion (`iv_skew_25d` MID).
- graphify MCP query server still down (killed earlier); auto-rebuild hooks disabled.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — §3.2.1✅ §3.2.2✅(8/8) §3.2.3 6/9 §3.2.5 4/6; remaining buildable-now: §3.2.6 (1) + §3.2.7 (4). §3.2.3-rest/§3.2.4 blocked on Kite/NLP. State: 42/50 PIT-shipped.
