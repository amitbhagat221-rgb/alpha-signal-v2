# HANDOFF
Updated: 2026-10-02 | Branch: master (0 unpushed) | HEAD: 2e43462 feat(pipeline): LLM steps run through the llm_tasks queue on the subscription (+ this handoff commit)

## Left off
Plan 0016 P1–P3 are live. The five LLM pipeline steps (`dossier`, `compute_sector_dossiers`, `news_brief`, `classify_news`, `classify_regulatory`) now run through `alpha_mcp/steps.py` → `llm_tasks` → `ops/llm_worker_local.sh` (`claude -p` on the subscription), switched by `config.LLM_WORK`. On 10-02 each was run through `pipeline.py --step` with SUCCESS (15/15 dossiers, 11/11 sector dossiers, the brief, 183 news, 508 regulatory), and health dropped from 13 CRITICALs to 6. The rest of the 6 clear with tomorrow's run, except SPRE's garbage Yahoo price target.

## Pick up here
1. Check the 2026-10-03 03:30 run (the first fully queue-driven morning):
   - `SELECT step_name,status,rows_affected FROM pipeline_log WHERE run_date='2026-10-03' AND step_name IN ('dossier','compute_sector_dossiers','news_brief','classify_news','classify_regulatory')`
   - the email shows theses (or "AI thesis pending")
   - `tail output/llm_worker.log`
   - the plan 0016 P3 gate is 3 clean mornings
2. Check that `datamodel.reconcile` parity is back to PASS: run `python -m datamodel.reconcile --show`. The 10-02 FAILs (news_briefs, news_enriched, regulatory_signals, sector_dossiers, pipeline_log) came from my manual refresh writing during the first live sync.
3. P5: the `industry_classify` and `sector_narrative` kinds in `alpha_mcp/tasks.py`, then delete `tools/classify_industries.py` and `tools/sector_narrative_fetcher.py`.

## Watch out
- **The worker must never see `ANTHROPIC_API_KEY`.** `run.sh` exports it, and the claude CLI would then bill the empty-credit API key. `ops/llm_worker_local.sh` unsets it; keep that in any wrapper.
- **Never edit `run.sh` while a cron job is running it.** Bash reads the script as it runs, and the 10-01 datamodel steps were silently skipped after a 06:27 edit mid-run. Check with `ps -eo args | grep "[r]un.sh"`.
- **Never use `pgrep -f`/`pkill -f` with a pattern that appears in your own command.** It matches its own shell: it killed one shell (exit 144) and gave a false "still running" twice.
- **`crontab <file>` fails on long scratchpad paths.** Use `crontab - < file`.
- **The worker sometimes quits after 5–6 submits and mistypes long task_ids.** The server rejects the bad id and the lease expires. The `llm_local` cron (05:07 / 14:37) drains leftovers.

## Active plan
docs/plans/0016-alpha-signal-mcp.md (P3 live, 3-morning gate pending; P5 next) · docs/plans/0017-data-model-redesign.md (v3 shadow tables live since 10-02, parity week, other session)
