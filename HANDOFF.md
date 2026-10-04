# HANDOFF
Updated: 2026-10-04 | Branch: master (1 unpushed: a02cb99; this session's work and the org session's are uncommitted) | HEAD: a02cb99 feat(health): five questions, 23 checks that prove they can fire, UHS retired (ADR 0059-0061)

## Left off
The factor audit (plan 0020) changed the model three times in two days: corrected factor inputs (ADR 0062), new weights for all three tiers (ADR 0063), and a missing factor now counts as neutral (ADR 0064). The 2026-10-04 run was the first on the new weights; 2026-10-05 will be the first with ADR 0064 and the wider result-filing rule, so the ranking moves once more.

## Pick up here
1. **Read the 2026-10-05 morning.** `python -m tools.health_report`: `DAILY_PICKS_COVERAGE_LOW` should be clear (LARGE about 101 of 103 ranked), `PICKS_RESHUFFLED` may fire one more day, `PRICE_JUMP_UNEXPLAINED` should be empty. Then the evidence pass started 06:21 UTC: `tail -30 output/factor_audit_pass4.log` must end `PASS4_DONE`; the current table is `python -m tools.factor_audit --wired`.
2. **Read the auditor's first scheduled memo** (seat `dq-auditor`, Sunday 06:30 UTC): `python -m org scorecard`, Boardroom `/org`. Turn each confirmed finding into a rule in `tools/dq_probes.py` (`RULES` / `NAME_FITS` / `KNOWN`); `python -m tools.dq_probes --drill` must stay 7 of 7.
3. **Next build, in this order:** dead names in the panel ([plan 0020 §7](docs/plans/0020-factor-audit.md)) → feature-layer refactor and the rest of the backtest redesign ([study §5](docs/studies/factor-audit-2026-10.md)) → new LARGE factors. LARGE has no proven factor: `iv_skew_25d` LARGE is already flagged by `FACTOR_DECAY`.

## Watch out
- **Old t-stats are void.** Anything in `docs/reference/signal-weights.md` below the marked line, in older ADRs and in memory notes was measured with today's tiers at every past date, an unadjusted label and consensus look-ahead. Quote only `tools.factor_audit` / `docs/studies/promotion-review-2026-10.md`.
- **The stored panel does not reproduce** (inputs are overwritten without versions): never gate a refactor on "panel identical"; diff old code vs new code on the same inputs.
- **Three Tickertape columns were renamed in the live DB**: `quarterly_income.interest` → `operating_expenses`, `.total_other_income` → `tax_and_minority`, `annual_cash_flow.depreciation` → `dividends_paid`. Code loaded before the rename breaks until restarted (`sudo systemctl restart alpha-cockpit alpha-cockpit-ops` was done 2026-10-03; not after the 10-04 rename).
- **Scratch SQLite + ATTACH:** an unqualified table name resolves to the attached live table when the scratch one does not exist. `tools/dq_probes._scratch` always writes `main.<table>` and attaches the live DB read-only.
- **CHAV and ORIA carry inferred corporate actions** (`corporate_actions.subject` says so): the exchange feed never listed their splits. Replace them if a real record arrives.
- **Shared working tree.** The org session's files (`org.py`, `alpha_mcp/org_kinds.py`, `.claude/routines/`, `cockpit_ops/templates/org.html`, `tests/test_org.py`) are still untracked or uncommitted and now carry this session's `dq-auditor` edits. `datamodel_reconcile` (plan 0017) has failed three mornings on the `pipeline_log` parity row: its owner's item.

## Active plan
docs/plans/0020-factor-audit.md (audit, fixes, weights and guards done; open: R11, dead-names panel §7, refactor + backtest redesign) · docs/plans/0019-agent-org.md (Phase 2: tune charters after the first weekly memos) · docs/plans/0017-data-model-redesign.md (parity week, other session)
