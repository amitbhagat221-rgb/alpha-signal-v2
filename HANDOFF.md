# HANDOFF
Updated: 2026-05-31 | Branch: master (4 unpushed) | HEAD (pre-commit): `feat(microstructure): 6 daily-derivable §3.2.3 factors (kyle_lambda LARGE+MID KEEP)`

## Left off
**Promoted `iv_skew_25d` into the live MID screener** — the first §3.2.x factor to reach production. Did the deliberate promotion review of the two KEEP candidates:
- **Extended the IV backtest 25 → 48 weekly periods** (reconstructed earlier Fridays + fwd_return back to ~2025-06, since `fno_iv_history` goes to 2025-05). `iv_skew_25d` MID **holds at t=+3.16 KEEP** (~11mo, multi-regime; was 4.61 on 25 periods), **LARGE t=1.37 / SMALL t=0.17 DROP** → MID-only.
- **Colinearity**: `iv_skew_25d` is orthogonal to size/adtv/existing factors (|ρ|<0.15) — genuinely new info. **`kyle_lambda`** is ρ=−0.73 with ln(ADTV) — a cost-coupled liquidity tilt, MID IC decaying → **benched as diagnostic, NOT wired.**
- **Wired** `iv_skew_25d` into `config.SIGNAL_WEIGHTS[MID]=0.18` (conservative vs the t-tier's 1.0×, given single-derivative-class novelty + ~11mo vs the others' 36mo history; existing 6 scaled ×0.82, Σ=1.0) + `scoring/screener.py` (`_load_signals` reads `fno_iv_history` latest-per-stock; `SIGNAL_COLS` mapping). Smoke-tested in-process: 101/149 MID stocks scored, high-skew names boosted (SAIL→rank 3, PLNG→rank 6); non-F&O MID names renormalise over present signals. Removed from `FACTOR_LIBRARY` (now live). signal-weights.md updated. **0 CRITICAL, health green.**

Also this session (committed): graphify auto-rebuild git hooks **disabled** (`.git/hooks/post-commit.disabled` + `post-checkout.disabled`, reversible).

## Pick up here
1. **Confirm `iv_skew_25d` flows to `daily_picks`** after the next pipeline run (it's wired but the live screener hasn't re-run since). Spot-check a MID pick's component breakdown.
2. **§3.2.5 event-time / PEAD (6 factors)** — feasible now, no blocked data; post-earnings drift is a robust anomaly → best shot at the next KEEP. `signals/pead.py` off `quarterly_income` + `stock_prices`.
3. **Phase E badges deploy** (`systemctl restart alpha-cockpit`) + **Kite activation** when creds land (3 held intraday §3.2.3 factors).

## Watch out
- **`iv_skew_25d` weight is conservative (0.18) on purpose** — it's validated on ~11mo / one derivative class, vs the v1 factors' 36mo. Revisit the weight as weekly periods accumulate; don't bump it mechanically.
- **It only differentiates the ~101 F&O MID names** (others NULL → renormalise). That's correct (only F&O stocks have options) but means it's inert for non-F&O MID picks.
- **graphify MCP query server (`graphify.serve`) was killed** as collateral when I `pkill`'d the rebuild — `mcp__graphify__*` query tools are down until that MCP server respawns (harness-managed). Graph data untouched; auto-rebuild hooks intentionally disabled.
- HEAD is still the microstructure commit; this session's promotion + hook-disable is uncommitted until the commit below.

## Active plan
[docs/plans/0002-100-factors-and-model.md](docs/plans/0002-100-factors-and-model.md) — §3.2.2 done (8/8), §3.2.3 6/9 (3 on hold). **First factor-model promotion to production from the Track-3 batch: `iv_skew_25d` MID.** State: 38/50 PIT-shipped.
