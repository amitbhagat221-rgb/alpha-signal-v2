# HANDOFF
Updated: 2026-10-08 | Branch: master (0 unpushed) | HEAD: 81655ca feat: news editor (plan 0021), investor playbooks + sleeve backtest, BSE SHP holders feed

## Left off
The factor audit (plan 0020) is shipped and pushed (692ef44 code, b504ff3 docs, ADR 0062–0064): corrected inputs, new weights on all three tiers, a missing factor scores as neutral; every morning since 2026-10-05 ranks LARGE 101 / MID 140 / SMALL ~1,535. The evidence table still predates the 10-04 fixes (demergers, board-meeting result filings, neutral rule): the panel re-run started 2026-10-04 06:21 died at once on `database is locked` (`output/factor_audit_pass4.log`, `exit4=1`).

## Pick up here
1. **Re-run the evidence pass outside the 02:45–05:45 UTC window** (nothing else writing): `python -m tools.reconstruct_pit` with every producer that reads `px` / `prices` / `close` / `base` / `bse_results` (list them from `factors.PIT_PRODUCERS`) and `--date` for each of the 204 `daily_snapshots_pit` anchors (~3 h), then `python -m tools.backtest_pit`, `python -m tools.multiple_testing`, `python -m tools.factor_audit --wired`. Compare with `docs/studies/promotion-review-2026-10.md`; no weight change without a review.
2. **Act on the auditor's 2026-10-04 memo** (`python -m org scorecard`, Boardroom `/org`; 4 of 4 calls matched the re-run, drill 7 of 7): `stocks.market_cap_cr` holds rupees and is shown as crore (= work order 1, `python -m org work 1`), and `stocks.pe_ratio / pb_ratio / roe / debt_to_equity` are empty for every stock while `tables.py` says yfinance fills them. Fix or drop, then add each as a rule in `tools/dq_probes.py`. Next scheduled run Sunday 2026-10-11 06:30 UTC.
3. **Next build, in order:** dead names in the panel ([plan 0020 §7](docs/plans/0020-factor-audit.md)) → feature-layer refactor + one label table + cadence fields ([study §5](docs/studies/factor-audit-2026-10.md)) → new LARGE factors (none proven; `iv_skew_25d` LARGE flagged by `FACTOR_DECAY`).

## Watch out
- **Long panel rebuilds lose to the morning run's lock.** `reconstruct_pit` holds no retry beyond the 30 s busy timeout: start it after ~06:00 UTC and finish before 02:45.
- **The auditor's `top_action` was stale** ("finish the re-test of the eight weights", done 10-03 as ADR 0063): its brief lists past findings but not decisions taken since. Tune `.claude/routines/roles/dq-auditor.md` or add recent ADRs to `_build_dq_audit` in `alpha_mcp/org_kinds.py`.
- **Shared tree again:** another session has uncommitted plan 0017 work (`datamodel/sync.py`, `schema.sql`, `tables.py`, `backup_db.sh`, `datamodel/retire.py`, a checklist line). Do not sweep it into a factor commit; this handoff commit stages only its own hunks.
- `tools/session_classify*` stay untracked on purpose (INSERT OR REPLACE ratchet, 665eab8).

## Active plan
docs/plans/0020-factor-audit.md (shipped; open: evidence re-run, R11, dead-names panel §7, refactor + backtest redesign) · docs/plans/0019-agent-org.md (Phase 2: tune charters from the first weekly memos) · docs/plans/0017-data-model-redesign.md (parity gaps, other session)
